"""Pure property-matching logic, free of MCP and config concerns.

Mirrors the behaviour of the data-noodler skill's lookup_property.py so
that the MCP tool and the CLI answer identically. Kept pure so it can be
tested against a fixture CSV with no credential and no network.
"""

import csv

DEFAULT_LIMIT = 25


def norm(s):
    return (s or "").strip().lower()


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def match_properties(rows, term):
    """Split rows into exact / near / partial matches for `term`.

    `near` exists because a common naming convention is "<domain> - GA4" or
    "<domain> (archive)"; a leading exact-domain match would otherwise be
    buried among hundreds of substring hits.
    """
    t = norm(term)
    exact = [r for r in rows if norm(r["property_name"]) == t]
    near = [r for r in rows
            if r not in exact and norm(r["property_name"]).startswith(t)]
    partial = [r for r in rows
               if r not in exact and r not in near
               and (t in norm(r["property_name"]) or t in norm(r["account_name"]))]
    return {"exact": exact, "near": near, "partial": partial}


def is_decisive(m):
    """One exact hit with nothing near it -- the common, answerable case."""
    return len(m["exact"]) == 1 and not m["near"]


INCOMPLETE_ID = "?"

REBUILD_HINT = ("The snapshot is truncated or was hand-edited; call "
                "refresh_property_snapshot to rebuild it.")


def property_id(row):
    """The row's property id, or None when the snapshot row is incomplete.

    csv.DictReader fills a short row -- a truncated final line, a hand edit,
    a row with fewer fields than the header -- with None. Formatting None
    against a width spec (`{...:<12}`) raises TypeError, which reached the
    user as "unsupported format string passed to NoneType.__format__": a
    leaked builtin instead of an instruction. Every read of the id goes
    through here so that shape stays impossible.
    """
    value = row.get("property_id")
    return value if isinstance(value, str) and value.strip() else None


# NOTE: skills/data-noodler/scripts/lookup_property.py -- shipped in
# marketplace/plugins/data-noodler/ and installed at
# ~/.claude/skills/data-noodler/scripts/ -- carries a duplicate of this
# rendering logic and still formats r['property_id'] directly, so it keeps the
# TypeError this module no longer has. Consolidating the two is tracked
# separately; whoever next touches either copy should fix or delete the other.
def _render(label, items, cap=None):
    if not items:
        return []
    shown = items if cap is None else items[:cap]
    lines = ["", f"{label} ({len(items)}):"]
    incomplete = 0
    for r in shown:
        pid = property_id(r)
        if pid is None:
            incomplete += 1
        lines.append(f"  properties/{(pid or INCOMPLETE_ID):<12} "
                     f"{r.get('property_name') or ''}"
                     f"   [account: {r.get('account_name') or ''}]")
    if cap is not None and len(items) > cap:
        lines.append(f"  ... {len(items) - cap} more not shown "
                     f"(narrow the search term or raise the limit)")
    if incomplete:
        lines.append(f"  (property_id missing on {incomplete} of the rows "
                     f"above, shown as {INCOMPLETE_ID}. {REBUILD_HINT})")
    return lines


def format_matches(term, m, include_all=False, limit=DEFAULT_LIMIT):
    """Render matches as text for a model to read.

    When there is one decisive hit, partial matches are counted rather than
    listed: enumerating them would burn thousands of tokens on rows nobody
    asked about, which is the exact opposite of why this exists.
    """
    total = len(m["exact"]) + len(m["near"]) + len(m["partial"])
    if total == 0:
        return (f"No property matched '{term}'.\n"
                "The snapshot may be stale if the property was added recently "
                "-- call refresh_property_snapshot and try again.")

    lines = _render("EXACT name match", m["exact"])

    if is_decisive(m) and not include_all:
        if m["partial"]:
            lines.append("")
            lines.append(f"({len(m['partial'])} other properties contain "
                         f"'{term}' in their name or account -- likely "
                         f"subdomains. Call again with include_all=true to "
                         f"list them.)")
        lines.append("")
        pid = property_id(m["exact"][0])
        if pid:
            lines.append(f"Unambiguous: use properties/{pid}")
        else:
            lines.append("The one exact name match has no property_id, so "
                         f"there is nothing to report. {REBUILD_HINT}")
        if m["partial"]:
            lines.append("If the whole domain family was meant rather than "
                         "this one site, that is a different question -- ask "
                         "which.")
        return "\n".join(lines)

    lines += _render("Name starts with term", m["near"], limit)
    lines += _render("Partial match", m["partial"], limit)
    lines.append("")
    lines.append("AMBIGUOUS -- more than one candidate. Confirm which property "
                 "is meant before reporting any number, and say which one you "
                 "used.")
    lines.append("Note: subdomains are usually separate properties, so a "
                 "parent domain's property does not include its subdomains' "
                 "traffic.")
    return "\n".join(lines)
