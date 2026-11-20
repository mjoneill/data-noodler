"""Rebuild the local property snapshot from the GA Admin API.

The single deliberate Admin API call in this system: one enumeration
maintained on purpose, instead of a 20k-token enumeration on every question.

Lives in the companion rather than the skill because a shell-less harness has
no other way to fix a stale snapshot.
"""

import csv
import os

FIELDS = ["account_name", "property_name", "property_id",
          "property", "account", "property_type"]


def rebuild(csv_path):
    """Rewrite `csv_path` from the Admin API. Returns (rows, accounts).

    Written atomically via a temp file and os.replace so a failure mid-write
    cannot leave a truncated snapshot behind -- a corrupt snapshot would break
    every lookup rather than just this refresh.
    """
    from analytics_mcp.tools.client import create_admin_api_client

    client = create_admin_api_client()

    rows = []
    for account in client.list_account_summaries():
        for prop in (account.property_summaries or []):
            rows.append({
                "account_name": account.display_name,
                "property_name": prop.display_name,
                "property_id": prop.property.split("/")[-1],
                "property": prop.property,
                "account": account.account,
                "property_type": (prop.property_type.name
                                  if prop.property_type else ""),
            })

    rows.sort(key=lambda r: (r["account_name"].lower(),
                             r["property_name"].lower()))

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    tmp = csv_path + ".tmp"
    # Exclusive, no-follow create: a plain open() would follow a symlink
    # planted at the temp name and overwrite its target (2026-10-25 audit).
    # A regular leftover from an interrupted refresh is ours to remove.
    if os.path.lexists(tmp) and not os.path.islink(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, csv_path)

    return len(rows), len({r["account"] for r in rows})
