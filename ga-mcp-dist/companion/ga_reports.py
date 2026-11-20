"""Cohort, realtime and funnel reports to file, and pivoting. Cards #135, #136.

Each returns (columns, rows, meta) for export.write_export, like ga_export.
None pages: cohort and funnel tables are small by construction, and realtime
covers at most the last half hour. Each records GA4's own row count where it
gives one, and marks the file incomplete if fewer rows arrived.

Response shapes were taken from live calls on 2026-10-07.
"""

import datetime

import ga_export

MAX_ROWS = 250_000

COHORT_NTH = {"DAILY": "cohortNthDay", "WEEKLY": "cohortNthWeek",
              "MONTHLY": "cohortNthMonth"}

# GA4 keeps realtime data for the last 30 minutes on standard properties
# (60 on 360). 29 minutes ago through now is the whole window.
REALTIME_MAX_MINUTES = 29

# More distinct values than this, and a pivoted file is wider than anyone can
# read -- the long file is the right one.
PIVOT_MAX_VALUES = 200


def _rows(table, n_metrics=None):
    dims = [h.name for h in table.dimension_headers]
    mets = [h.name for h in table.metric_headers]
    if n_metrics is not None:
        mets = mets[:n_metrics]
    rows = [[v.value for v in r.dimension_values]
            + [v.value for v in r.metric_values]
            for r in table.rows or []]
    return dims + mets, rows


def _completeness(rows, row_count):
    if row_count is None or len(rows) >= row_count:
        return None
    return "server_stopped"


def run_cohort(property_id, cohorts, granularity="WEEKLY", periods=4,
               metrics=None, dimensions=None, accumulate=False, client=None):
    """Retention by acquisition cohort.

    Each cohort is the users whose first session fell in its date range;
    rows follow them for `periods` days, weeks or months after. Dates go in
    the cohorts, not in date_ranges -- GA4 refuses both.
    """
    from google.analytics.data_v1beta.types import (
        Cohort, CohortReportSettings, CohortSpec, CohortsRange, DateRange,
        Dimension, Metric, RunReportRequest)

    granularity = (granularity or "").upper()
    if granularity not in COHORT_NTH:
        raise ValueError(f"granularity must be one of "
                         f"{', '.join(COHORT_NTH)}; got {granularity!r}.")
    if not cohorts:
        raise ValueError("cohorts needs at least one {name, start_date, "
                         "end_date} -- the users who first visited then.")
    if periods is None or periods < 0:
        raise ValueError("periods must be 0 or more: how many days, weeks or "
                         "months after the cohort to follow it.")
    named = []
    for i, c in enumerate(cohorts, start=1):
        start = c.get("start_date") or c.get("startDate")
        end = c.get("end_date") or c.get("endDate")
        if not start or not end:
            raise ValueError(f"Cohort {i} needs start_date and end_date; "
                             f"got {c!r}.")
        named.append({"name": c.get("name") or f"cohort_{i}",
                      "start": start, "end": end})

    metrics = list(metrics or ["cohortActiveUsers", "cohortTotalUsers"])
    dims = ["cohort", COHORT_NTH[granularity]] + list(dimensions or [])
    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in metrics],
        cohort_spec=CohortSpec(
            cohorts=[Cohort(name=c["name"], dimension="firstSessionDate",
                            date_range=DateRange(start_date=c["start"],
                                                 end_date=c["end"]))
                     for c in named],
            cohorts_range=CohortsRange(granularity=granularity,
                                       end_offset=periods),
            cohort_report_settings=CohortReportSettings(
                accumulate=bool(accumulate))),
        limit=MAX_ROWS, return_property_quota=True)
    resp = (client or ga_export._client()).run_report(request)
    columns, rows = _rows(resp)
    return columns, rows, {
        "source": "ga4_cohort", "property_id": str(property_id),
        "cohorts": named, "granularity": granularity, "periods": periods,
        "accumulate": bool(accumulate), "metrics": metrics,
        "dimensions": dims,
        "date_range": {"start": min(c["start"] for c in named),
                       "end": max(c["end"] for c in named)},
        "rows_matched": resp.row_count,
        "row_limit_hit": len(rows) < resp.row_count,
        "incomplete_reason": _completeness(rows, resp.row_count),
        "property_quota": ga_export._quota(resp),
        "sampled": ga_export.was_sampled(resp),
    }


def run_realtime(property_id, dimensions, metrics, dimension_filter=None,
                 metric_filter=None, minutes_ago=REALTIME_MAX_MINUTES,
                 client=None):
    """The last `minutes_ago` minutes, as of now. Recorded with the moment
    it was captured, because a realtime file means nothing without one."""
    from google.analytics.data_v1beta.types import (
        Dimension, FilterExpression, Metric, MinuteRange,
        RunRealtimeReportRequest)

    if not 0 <= minutes_ago <= REALTIME_MAX_MINUTES:
        raise ValueError(f"minutes_ago must be 0-{REALTIME_MAX_MINUTES}: GA4 "
                         "keeps realtime data for the last 30 minutes. For "
                         "anything older, use export_report.")
    request = RunRealtimeReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dimensions or []],
        metrics=[Metric(name=m) for m in metrics],
        minute_ranges=[MinuteRange(start_minutes_ago=minutes_ago,
                                   end_minutes_ago=0)],
        limit=MAX_ROWS, return_property_quota=True)
    if dimension_filter:
        request.dimension_filter = ga_export._coerce_filter(dimension_filter)
    if metric_filter:
        request.metric_filter = ga_export._parse_message(
            FilterExpression, metric_filter, "metric_filter",
            '{"filter": {"fieldName": "activeUsers", ...}}')
    captured = datetime.datetime.now(datetime.timezone.utc)
    resp = (client or ga_export._client()).run_realtime_report(request)
    columns, rows = _rows(resp)
    day = captured.date().isoformat()
    return columns, rows, {
        "source": "ga4_realtime", "property_id": str(property_id),
        "dimensions": list(dimensions or []), "metrics": list(metrics),
        "dimension_filter": ga_export.filter_for_meta(dimension_filter),
        "metric_filter": ga_export.filter_for_meta(metric_filter),
        "minutes_ago": minutes_ago,
        "captured_at": captured.isoformat(timespec="seconds"),
        "date_range": {"start": day, "end": day},
        "rows_matched": resp.row_count,
        "row_limit_hit": len(rows) < resp.row_count,
        "incomplete_reason": _completeness(rows, resp.row_count),
        "property_quota": ga_export._quota(resp),
        "sampled": False,
    }


def run_funnel(property_id, steps, start_date, end_date,
               breakdown_dimension="", is_open_funnel=False, client=None):
    """A funnel's step-by-step table: users, completion and abandonment.

    Uses Google's alpha Data API -- the only one with funnels -- through
    upstream's alpha client. Steps are {name, event} for the common case or
    {name, filter_expression} with a FunnelFilterExpression as JSON.
    """
    from google.analytics import data_v1alpha as a

    if not steps:
        raise ValueError("steps needs at least one {name, event}.")
    built = []
    for i, s in enumerate(steps, start=1):
        if not isinstance(s, dict):
            raise ValueError(f"Step {i} must be an object; got {s!r}.")
        name = s.get("name") or f"Step {i}"
        if s.get("event"):
            expr = a.FunnelFilterExpression(
                funnel_event_filter=a.FunnelEventFilter(event_name=s["event"]))
        elif s.get("filter_expression"):
            expr = ga_export._parse_message(
                a.FunnelFilterExpression, s["filter_expression"],
                f"step {i} filter_expression",
                '{"funnelEventFilter": {"eventName": "page_view"}}')
        else:
            raise ValueError(f"Step {i} ({name}) needs an event name or a "
                             "filter_expression.")
        built.append(a.FunnelStep(name=name, filter_expression=expr))

    request = a.RunFunnelReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[a.DateRange(start_date=start_date, end_date=end_date)],
        funnel=a.Funnel(steps=built, is_open_funnel=bool(is_open_funnel)),
        return_property_quota=True)
    if breakdown_dimension:
        request.funnel_breakdown = a.FunnelBreakdown(
            breakdown_dimension=a.Dimension(name=breakdown_dimension))
    if client is None:
        from analytics_mcp.tools.client import create_data_api_alpha_client
        client = create_data_api_alpha_client()
    resp = client.run_funnel_report(request)
    table = resp.funnel_table

    # Measured: the table lists its metric headers twice (8 headers for 4
    # values per row). Keep as many as each row actually carries.
    width = len(table.rows[0].metric_values) if table.rows else None
    columns, rows = _rows(table, n_metrics=width)
    if width is None:
        seen = []
        for c in columns:
            if c not in seen:
                seen.append(c)
        columns = seen
    notes = []
    if breakdown_dimension:
        i = columns.index(breakdown_dimension) \
            if breakdown_dimension in columns else None
        if i is not None:
            for r in rows:
                if r[i] == "RESERVED_TOTAL":
                    r[i] = "(total)"
            notes.append("GA4 labels the all-values row RESERVED_TOTAL; it is "
                         "written as (total). Do not add it to the other rows.")
    return columns, rows, {
        "source": "ga4_funnel", "property_id": str(property_id),
        "steps": [{"name": s.name} for s in built],
        "is_open_funnel": bool(is_open_funnel),
        "breakdown_dimension": breakdown_dimension or None,
        "date_range": {"start": start_date, "end": end_date},
        "notes": " ".join(notes) or None,
        "row_limit_hit": False, "incomplete_reason": None,
        "property_quota": ga_export._quota(resp),
        "sampled": False,
    }


def pivot_wide(columns, rows, pivot_on, metrics):
    """Turn one dimension's values into columns, one per metric per value.

    Lossless: every (row key, value, metric) cell lands in exactly one place.
    A blank cell means that combination did not occur -- not zero, which is
    a claim GA4 never made.
    """
    if pivot_on not in columns:
        raise ValueError(f"Cannot pivot on {pivot_on!r}: not a column of this "
                         f"export ({', '.join(columns)}).")
    p = columns.index(pivot_on)
    mets = [m for m in metrics if m in columns]
    m_idx = [columns.index(m) for m in mets]
    key_idx = [i for i, c in enumerate(columns)
               if i != p and c not in mets]
    values = sorted({r[p] for r in rows})
    if len(values) > PIVOT_MAX_VALUES:
        raise ValueError(
            f"{pivot_on} has {len(values)} distinct values; a pivot that wide "
            f"(over {PIVOT_MAX_VALUES}) is unreadable. The long file has every "
            "row -- use it, or pivot on a coarser dimension.")
    table, order = {}, []
    for r in rows:
        key = tuple(r[i] for i in key_idx)
        if key not in table:
            table[key] = {}
            order.append(key)
        for m, i in zip(mets, m_idx):
            table[key][(m, r[p])] = r[i]
    out_cols = ([columns[i] for i in key_idx]
                + [f"{m}|{v}" for m in mets for v in values])
    out_rows = [list(k) + [table[k].get((m, v), "") for m in mets
                           for v in values] for k in order]
    return out_cols, out_rows
