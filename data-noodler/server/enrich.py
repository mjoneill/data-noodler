"""Facts that let a non-specialist choose between similar properties.

Two cheap queries per candidate: total sessions over the last 28 days, and the
hostnames actually receiving traffic. Between them they separate a live
property from an archived duplicate, and reveal a property serving many sites
-- which the agent must raise with the user before exporting page paths from it.
"""

import matching

HOSTNAME_LIMIT = 10


def candidate_facts(property_id, runner=None, days=28):
    """Sessions and hostnames for one candidate. Never raises."""
    if runner is None:
        import ga_export
        runner = ga_export.run

    start, end = f"{days}daysAgo", "yesterday"
    try:
        _, rows, _ = runner(property_id, start, end, ["sessions"], [])
        sessions = int(rows[0][0]) if rows else 0

        _, host_rows, _ = runner(property_id, start, end, ["sessions"],
                                 ["hostName"], limit=HOSTNAME_LIMIT)
        hostnames = [r[0] for r in host_rows]
        return {"sessions": sessions, "hostnames": hostnames, "error": None}
    except Exception as exc:
        # A message-less exception (`raise RuntimeError()`, some TimeoutError
        # paths) makes str(exc) "" -- falsy, and indistinguishable from "no
        # error" to a truthiness check. Name the type so describe() always
        # has something non-empty to test and to show.
        message = str(exc) or f"{type(exc).__name__} (no message)"
        return {"sessions": None, "hostnames": [], "error": message}


def describe(candidate, facts):
    """One line a strategist can act on, with the ID present but secondary."""
    name = candidate.get("property_name", "(unnamed)")
    account = candidate.get("account_name", "")
    pid = matching.property_id(candidate)

    if pid is None:
        return (f"{name} [account: {account}] — its row in the property "
                f"snapshot is incomplete (no property id). "
                f"{matching.REBUILD_HINT}")

    # Test for presence, not truthiness: an exception with no message
    # produces error == "", which is falsy but is still a real failure --
    # not the same thing as "no traffic", and must not render as one.
    if facts.get("error") is not None:
        return (f"{name} [account: {account}] — could not read recent "
                f"activity ({facts['error']}) — properties/{pid}")

    sessions = facts.get("sessions")
    hosts = facts.get("hostnames") or []

    if sessions:
        head = f"{sessions:,} sessions in the last 28 days"
    else:
        head = "no traffic in the last 28 days"

    if len(hosts) == 1:
        where = f", traffic on {hosts[0]}"
    elif len(hosts) > 1:
        # The query is capped, so a full page means "at least this many",
        # not "this many". Saying 10 when the real figure is 40 overstates a
        # number a reader uses to decide whether a property is safe to
        # export from.
        count = (f"{len(hosts)} or more" if len(hosts) >= HOSTNAME_LIMIT
                  else str(len(hosts)))
        ellipsis = "…" if len(hosts) > 3 else ""
        where = (f", serving {count} hostnames "
                 f"({', '.join(hosts[:3])}{ellipsis})")
    else:
        where = ""

    return f"{name} — {head}{where} [account: {account}] — properties/{pid}"
