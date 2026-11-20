"""GA4 property setup and field compatibility. Read-only. Cards #133, #134.

Both answer "why does this number look wrong" questions that run_report
cannot: which fields can be combined at all, and how the property is set up --
which sites feed it, what counts as a conversion, how long data is kept.

Change history is deliberately absent. Google requires the analytics.edit
scope to read it (measured 2026-10-07: 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT),
and this package mints a read-only credential on purpose. Property access
reports are out of scope by decision: they audit other people.

Clients come from upstream's factories, as in ga_export, and are injectable
so tests need no network.
"""


def _data_client():
    from analytics_mcp.tools.client import create_data_api_client
    return create_data_api_client()


def _admin_clients():
    from analytics_mcp.tools.client import (
        create_admin_alpha_api_client, create_admin_api_client)
    return create_admin_api_client(), create_admin_alpha_api_client()


def _name(enum_value):
    """An enum's name, or the value as text."""
    return getattr(enum_value, "name", None) or str(enum_value)


def _text(value):
    return None if value is None else str(value)


def _request(property_id, dimensions, metrics, dimension_filter,
             metric_filter):
    from google.analytics.data_v1beta.types import (
        CheckCompatibilityRequest, Dimension, FilterExpression, Metric)
    import ga_export
    request = CheckCompatibilityRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dimensions or []],
        metrics=[Metric(name=m) for m in metrics or []])
    if dimension_filter:
        request.dimension_filter = ga_export._coerce_filter(dimension_filter)
    if metric_filter:
        request.metric_filter = ga_export._parse_message(
            FilterExpression, metric_filter, "metric_filter",
            '{"filter": {"fieldName": "sessions", ...}}')
    return request


def _ratings(resp):
    """({api_name: verdict}, {"dimensions": [...], "metrics": [...]})."""
    rated, compatible = {}, {"dimensions": [], "metrics": []}
    for kind, items, attr in (
            ("dimensions", resp.dimension_compatibilities, "dimension_metadata"),
            ("metrics", resp.metric_compatibilities, "metric_metadata")):
        for c in items or []:
            api = getattr(getattr(c, attr), "api_name", "")
            verdict = _name(c.compatibility)
            rated[api] = verdict
            if verdict == "COMPATIBLE":
                compatible[kind].append(api)
    return rated, compatible


def _lookup(rated, field):
    """(verdict, canonical name) -- GA4 accepts any case and rates the field
    under its canonical name (measured: "pagepath" came back as pagePath)."""
    if field in rated:
        return rated[field], field
    canon = {k.lower(): k for k in rated}.get(field.lower())
    return (rated[canon], canon) if canon else (None, None)


def _is_clash(exc):
    return "incompatible" in str(exc).lower()


def check_compatibility(property_id, dimensions, metrics, dimension_filter=None,
                        metric_filter=None, suggest="", client=None):
    """Which of these fields GA4 will combine in one report.

    Google's response rates every field on the property (168 KB measured), so
    only the requested fields are reported, plus -- when `suggest` is given --
    the compatible fields whose name contains it. That is the useful follow-up
    to an INCOMPATIBLE verdict: "which source dimension CAN I use here?"

    Google refuses the check outright when the requested fields clash with
    each other -- the very case it is for (measured, and documented). Then
    each field is checked alone, which rates every other field against it,
    and the clashing pairs are reported by name.
    """
    client = client or _data_client()
    dimensions, metrics = list(dimensions or []), list(metrics or [])
    fields = dimensions + metrics
    out = {"property_id": str(property_id)}
    try:
        resp = client.check_compatibility(_request(
            property_id, dimensions, metrics, dimension_filter, metric_filter))
    except Exception as exc:
        if not _is_clash(exc):
            raise
        resp = None

    if resp is not None:
        rated, compatible = _ratings(resp)
        requested = {}
        for f in fields:
            verdict, canon = _lookup(rated, f)
            if verdict is None:
                requested[f] = ("UNKNOWN: Google did not rate this field. For "
                                "a custom dimension, check the customEvent: "
                                "or customUser: prefix.")
            else:
                requested[f] = (verdict if canon == f
                                else f"{verdict} (GA4 spells it {canon})")
        out["requested"] = requested
        out["all_compatible"] = all(v.startswith("COMPATIBLE")
                                    for v in requested.values())
    else:
        conflicts, compatible = {}, None
        for f in fields:
            alone = _request(property_id, [f] if f in dimensions else [],
                             [f] if f in metrics else [], None, None)
            rated, comp = _ratings(client.check_compatibility(alone))
            compatible = compatible or comp
            clash = [g for g in fields if g != f
                     and (_lookup(rated, g)[0] or "") == "INCOMPATIBLE"]
            if clash:
                conflicts[f] = clash
        out["requested"] = {
            f: (f"INCOMPATIBLE with {', '.join(conflicts[f])}"
                if f in conflicts else "COMPATIBLE") for f in fields}
        out["conflicts"] = conflicts
        out["all_compatible"] = False
        if not conflicts:
            # Every field is fine on its own, so it is the filter that
            # clashes. Say so rather than inventing a culprit.
            out["note"] = ("Each field is compatible on its own; the clash "
                           "involves the filters.")
        # Suggestions are taken from the first field alone -- the whole set
        # has no compatible neighbours, by definition.
        compatible = compatible or {"dimensions": [], "metrics": []}
        if suggest and fields:
            out["compatible_matching_note"] = (
                f"Because the requested fields clash, these suggestions are "
                f"fields compatible with {fields[0]} alone.")

    if suggest:
        needle = suggest.lower()
        out["compatible_matching"] = {
            kind: sorted(n for n in names if needle in n.lower())
            for kind, names in compatible.items()}
    return out


SECTIONS = ("property", "data_retention", "data_streams", "key_events",
            "audiences", "channel_groups")


def _stream(s):
    web = getattr(s, "web_stream_data", None)
    android = getattr(s, "android_app_stream_data", None)
    ios = getattr(s, "ios_app_stream_data", None)
    return {"type": _name(s.type_), "display_name": s.display_name,
            "default_uri": getattr(web, "default_uri", None) or None,
            "measurement_id": getattr(web, "measurement_id", None) or None,
            "package_name": getattr(android, "package_name", None) or None,
            "bundle_id": getattr(ios, "bundle_id", None) or None}


def property_setup(property_id, sections=None, admin=None, alpha=None):
    """The property's setup, section by section, as plain JSON.

    A section that fails reports its error in place rather than losing the
    rest: audiences and channel groups come from Google's alpha API, which is
    the likeliest to change under us.
    """
    sections = list(sections or SECTIONS)
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise ValueError(
            f"Unknown section(s) {unknown}. Choices: {', '.join(SECTIONS)}. "
            "Change history is not available: Google requires the "
            "analytics.edit scope to read it, and this package is read-only "
            "by design -- it is in the GA4 interface under Admin > Change "
            "history.")
    if admin is None or alpha is None:
        made_admin, made_alpha = _admin_clients()
        admin, alpha = admin or made_admin, alpha or made_alpha
    p = f"properties/{property_id}"

    readers = {
        "property": lambda: (lambda x: {
            "display_name": x.display_name, "time_zone": x.time_zone,
            "currency_code": x.currency_code,
            "create_time": _text(x.create_time),
            "industry_category": _name(x.industry_category)})(
                admin.get_property(name=p)),
        "data_retention": lambda: (lambda x: {
            "event_data_retention": _name(x.event_data_retention),
            "user_data_retention": _name(x.user_data_retention),
            "reset_user_data_on_new_activity":
                bool(x.reset_user_data_on_new_activity)})(
                admin.get_data_retention_settings(
                    name=f"{p}/dataRetentionSettings")),
        "data_streams": lambda: [_stream(s)
                                 for s in admin.list_data_streams(parent=p)],
        "key_events": lambda: [{
            "event_name": k.event_name,
            "counting_method": _name(k.counting_method),
            "custom": bool(getattr(k, "custom", False))}
            for k in admin.list_key_events(parent=p)],
        "audiences": lambda: [{
            "display_name": a.display_name,
            "membership_duration_days": a.membership_duration_days}
            for a in alpha.list_audiences(parent=p)],
        # Names only. The grouping rules ran to 7.8 KB for the default group
        # alone, and the question is almost always "is there a custom one".
        "channel_groups": lambda: [{
            "display_name": g.display_name,
            "system_defined": bool(getattr(g, "system_defined", False))}
            for g in alpha.list_channel_groups(parent=p)],
    }
    out = {"property_id": str(property_id)}
    for s in sections:
        try:
            out[s] = readers[s]()
        except Exception as exc:
            out[s] = {"error": str(exc).splitlines()[0][:300]}
    return out
