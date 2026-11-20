#!/usr/bin/env python3
"""Resolve a GA property name (or fragment) to its numeric property ID.

Why this exists: calling the MCP server's get_account_summaries tool costs
~20k tokens on a large account because it returns every account and property.
This reads a local CSV snapshot instead, and returns only matching rows --
typically a few hundred tokens or less.

It separates exact from partial matches on purpose. On accounts where every
subdomain is its own property, a substring like "example.edu" can match hundreds
of rows while exactly one property is actually named that. Reporting a number
from the wrong property is the most likely way to be confidently wrong here,
so the distinction is surfaced rather than guessed at.

Usage:
    lookup_property.py example.edu
    lookup_property.py admissions --limit 40
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga_config

DEFAULT_LIMIT = 25
COLUMNS = ("property_name", "account_name", "property_id")
INCOMPLETE_ID = "?"


def property_id(row):
    """The row's id, or None when the snapshot row is incomplete.

    The same rule as the server's matching.property_id (#2007 R2). A short
    row -- a truncated last line, a hand edit -- arrives from DictReader with
    None in the missing fields, and formatting None against a width spec
    raised TypeError here long after the server stopped doing so.
    """
    value = row.get("property_id")
    return value if isinstance(value, str) and value.strip() else None


def main():
    # A console that cannot show a character (an ASCII locale, an old Windows
    # code page) must cost a "?" in a name, never the whole answer.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("term", help="property name or fragment to search for")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max partial matches to print (default {DEFAULT_LIMIT})")
    ap.add_argument("--all", action="store_true",
                    help="list partial matches even when an exact match exists")
    args = ap.parse_args()

    cfg = ga_config.load()
    csv_path = cfg["properties_csv"]
    if not os.path.exists(csv_path):
        sys.exit(
            f"No property snapshot at {csv_path}\n"
            f'Build one with:\n  "{cfg["venv_python"]}" '
            f"{os.path.dirname(os.path.abspath(__file__))}/refresh_properties.py"
        )

    rebuild = (f'Rebuild it with:\n  "{cfg["venv_python"]}" '
               f"{os.path.dirname(os.path.abspath(__file__))}/refresh_properties.py")

    term = args.term.strip().lower()
    # Explicit UTF-8: property names are often not ASCII, and a Windows
    # locale would otherwise decode them as something else.
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        absent = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if absent:
            sys.exit(f"The property snapshot at {csv_path} does not have the "
                     f"expected columns (missing: {', '.join(absent)}).\n{rebuild}")
        rows = list(reader)

    def norm(s):
        return (s or "").strip().lower()

    exact = [r for r in rows if norm(r.get("property_name")) == term]
    # A common naming convention is "<domain> - GA4" or "<domain> (archive)";
    # treat a leading exact-domain match as near-exact so it isn't buried.
    near = [r for r in rows
            if r not in exact and norm(r.get("property_name")).startswith(term)]
    partial = [r for r in rows
               if r not in exact and r not in near
               and (term in norm(r.get("property_name"))
                    or term in norm(r.get("account_name")))]

    def show(label, items, cap=None):
        if not items:
            return
        shown = items if cap is None else items[:cap]
        print(f"\n{label} ({len(items)}):")
        incomplete = 0
        for r in shown:
            pid = property_id(r)
            incomplete += pid is None
            print(f"  properties/{(pid or INCOMPLETE_ID):<12} "
                  f"{r.get('property_name') or ''}"
                  f"   [account: {r.get('account_name') or ''}]")
        if cap is not None and len(items) > cap:
            print(f"  ... {len(items) - cap} more not shown "
                  f"(narrow the search term or raise --limit)")
        if incomplete:
            print(f"  (property_id missing on {incomplete} of the rows above, "
                  f"shown as {INCOMPLETE_ID}. The snapshot is truncated or was "
                  f"hand-edited.)\n  {rebuild}")

    total = len(exact) + len(near) + len(partial)
    if total == 0:
        print(f"No property matched '{args.term}'.")
        print("The snapshot may be stale if the property was added recently -- "
              "rerun refresh_properties.py.")
        return

    # One exact hit and nothing near it is the common, answerable case. Listing
    # the partial matches then would burn thousands of tokens on rows nobody
    # asked about -- the exact opposite of why this script exists. Report the
    # count so the breadth is still visible, and let --all expand it.
    # An exact hit whose id is missing is not an answer: fall through to the
    # listing, which shows it as "?" with the rebuild instruction.
    decisive = len(exact) == 1 and not near and property_id(exact[0]) is not None
    show("EXACT name match", exact)

    if decisive and not args.all:
        if partial:
            print(f"\n({len(partial)} other properties contain '{args.term}' in "
                  f"their name or account -- likely subdomains. Re-run with "
                  f"--all to list them.)")
        print(f"\nUnambiguous: use properties/{property_id(exact[0])}")
        if partial:
            print("If the user meant the whole domain family rather than this "
                  "one site, that is a different question -- ask which.")
        return

    show("Name starts with term", near, args.limit)
    show("Partial match", partial, args.limit)

    print()
    print("AMBIGUOUS -- more than one candidate. Confirm which property is "
          "meant before reporting any number, and say which one you used.")
    print("Note: subdomains are usually separate properties, so a parent "
          "domain's property does not include its subdomains' traffic.")


if __name__ == "__main__":
    main()
