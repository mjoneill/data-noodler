"""Run a GA4 report and turn the response into rows plus provenance.

The client comes from upstream's own factory rather than being constructed
here, so this inherits the credential handling, the DNS configuration, and
upstream's prevent_stdio_inheritance guard -- which matters because stdout is
the MCP protocol channel.
"""

import re


def _client():
    from analytics_mcp.tools.client import create_data_api_client
    return create_data_api_client()


def rows_from_response(resp):
    """(columns, rows) from a RunReportResponse. Dimensions then metrics."""
    columns = ([h.name for h in resp.dimension_headers]
               + [h.name for h in resp.metric_headers])
    rows = []
    for r in resp.rows or []:
        rows.append([v.value for v in r.dimension_values]
                    + [v.value for v in r.metric_values])
    return columns, rows


def was_sampled(resp):
    """True when GA4 reports the response was sampled.

    Sampling silently changes numbers, so it is recorded rather than inferred.
    """
    meta = getattr(resp, "metadata", None)
    return bool(getattr(meta, "sampling_metadatas", None))


def had_other_row_loss(resp):
    """True when GA4 folded part of the long tail into an "(other)" row.

    That happens on high-cardinality reports and changes what the rows mean,
    so -- like sampling -- it is recorded rather than left to be discovered.
    """
    meta = getattr(resp, "metadata", None)
    return bool(getattr(meta, "data_loss_from_other_row", False))


# GA4's maximum rows per request. Larger reports are paged with offset.
PAGE_SIZE = 250_000

# Backstop against an API that reports more rows than it will ever return.
# 400 pages of 250,000 is 100 million rows -- far past any GA4 property. The
# loop normally stops long before this, on a short or empty page.
MAX_PAGES = 400


_MAX_FILTER_DEPTH = 25


def _filter_mentions_hostname(dimension_filter):
    """True when the filter actually constrains hostName.

    Structural rather than a substring test on str(): a filter on pagePath
    matching the value "/hostName-report" contains the text "hostName" while
    constraining nothing about the host, and would be misread as host-scoped --
    mislabelling provenance in the direction that hides a problem.

    The walk is depth-capped rather than cycle-tracked. A cap handles both a
    self-referential structure and a pathologically deep one with a single
    comparison, and running past it returns False -- mixed_unscoped -- which
    understates the scoping rather than overstating it, matching how every
    other unrecognised filter shape is treated. Real filters nest three to
    five levels; proto-plus refuses to build much beyond sixty. Do not turn
    this into a raise: exceeding the cap is exactly as unrecognised as any
    other shape this function doesn't understand.
    """
    def walk(node, depth):
        if depth > _MAX_FILTER_DEPTH:
            return False
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("fieldName", "field_name") and value == "hostName":
                    return True
                if walk(value, depth + 1):
                    return True
            return False
        if isinstance(node, (list, tuple)):
            return any(walk(item, depth + 1) for item in node)
        if getattr(node, "field_name", None) == "hostName":
            return True
        for attr in ("filter", "not_expression"):
            # Truthiness, not `is not None`: an unset protobuf message field
            # still returns a (falsy) default instance rather than None, so
            # a presence check written as `is not None` never terminates --
            # each empty child hands back another empty child forever.
            child = getattr(node, attr, None)
            if child and walk(child, depth + 1):
                return True
        for attr in ("and_group", "or_group"):
            group = getattr(node, attr, None)
            exprs = getattr(group, "expressions", None) if group else None
            if exprs and walk(list(exprs), depth + 1):
                return True
        return False

    return bool(dimension_filter) and walk(dimension_filter, 0)


def filter_for_meta(dimension_filter):
    """The filter as it should appear in the sidecar.

    A dict -- what an MCP caller can actually send -- is recorded verbatim,
    because it is already JSON and the query can therefore be re-run exactly
    from the provenance record. A protobuf FilterExpression is not
    JSON-serialisable at all, so it is recorded as str(); the sidecar is
    written with json.dump and a raw message would abort the write.
    """
    if dimension_filter is None:
        return None
    if isinstance(dimension_filter, dict):
        return dimension_filter
    return str(dimension_filter)


def host_scope(dimensions, dimension_filter, hostnames):
    """How this export is scoped across a property's hostnames.

    Provenance, not policy -- the agent decides how to handle a multi-host
    property in conversation with the user; this records what was decided so
    the file can be trusted later without the transcript.
    """
    if "hostName" in (dimensions or []):
        return "dimension"
    if _filter_mentions_hostname(dimension_filter):
        return "filtered"
    if hostnames and len(hostnames) == 1:
        return "single_host"
    return "mixed_unscoped"


def suggested_filename(property_id, dimensions, start, end):
    """A default name legible in Finder without opening the file."""
    part = "-".join(re.sub(r"[^a-z0-9]+", "", d.lower())
                    for d in (dimensions or [])) or "totals"
    return (f"ga4-{property_id}-{part}"
            f"-{start.replace('-', '')}-{end.replace('-', '')}.csv")


def _coerce_filter(dimension_filter):
    """A dict dimension_filter, in either spelling, as a real FilterExpression.

    GA4's own REST/JSON reference spells field names camelCase
    ("fieldName", "stringFilter") -- what anyone reading Google's docs would
    write. proto-plus, which builds the message this gets assigned to,
    resolves dict keys against proto field names only (snake_case), so a
    camelCase dict raises a bare "Unknown field" ValueError with no hint
    that the fix is spelling, not content.

    google.protobuf.json_format.ParseDict implements the canonical proto3
    JSON mapping, which accepts both camelCase and snake_case field names,
    so one conversion handles either spelling. It is applied to the
    proto-plus wrapper's underlying `_pb` message -- proto-plus itself has
    no ParseDict-equivalent -- and the wrapper reflects the parse because
    `_pb` is not a copy.

    Anything that is not a dict (a real FilterExpression, or None) is
    returned unchanged: this function only translates the shape an MCP
    caller can actually send.
    """
    if not isinstance(dimension_filter, dict):
        return dimension_filter

    from google.analytics.data_v1beta.types import FilterExpression
    from google.protobuf import json_format

    fe = FilterExpression()
    try:
        json_format.ParseDict(dimension_filter, fe._pb)
    except Exception as exc:
        # Not left as the bare ParseError: it already names the offending
        # key, but nothing in its text says "dimension_filter" or "filter
        # shape" -- the piece a reader needs to know where to look.
        raise ValueError(
            f"dimension_filter is not a valid GA4 filter shape ({exc}). "
            'Expected a FilterExpression as JSON, e.g. {"filter": '
            '{"fieldName": "hostName", "stringFilter": {"value": "..."}}} '
            "-- camelCase (as in Google's REST docs) and snake_case field "
            "names are both accepted.")
    return fe


def _parse_message(cls, value, label, example):
    """A dict in either camelCase or snake_case, as a proto-plus message.

    The same canonical proto3 JSON mapping _coerce_filter uses, for the other
    request fields a caller sends as JSON. A bad shape names the parameter,
    because ParseDict's own message names only the key.
    """
    from google.protobuf import json_format
    if not isinstance(value, dict):
        return value
    msg = cls()
    try:
        json_format.ParseDict(value, msg._pb)
    except Exception as exc:
        raise ValueError(f"{label} is not a valid GA4 shape ({exc}). "
                         f"Expected, e.g., {example} -- camelCase and "
                         "snake_case field names are both accepted.")
    return msg


# GA4 accepts at most four date ranges in one request.
MAX_DATE_RANGES = 4


def _date_ranges(start_date, end_date, compare_date_ranges):
    """[{name, start, end}] for the primary range plus any comparisons.

    Every range is named. GA4 adds a dateRange column when there is more than
    one, filled with the name -- and "date_range_1" in a CSV says nothing six
    months later, where "last_year" does. The primary range is "current".
    """
    ranges = [{"name": "current", "start": start_date, "end": end_date}]
    for i, r in enumerate(compare_date_ranges or [], start=1):
        if not isinstance(r, dict):
            raise ValueError("Each compare_date_ranges entry must be an "
                             f"object with start_date and end_date; got {r!r}.")
        start = r.get("start_date") or r.get("startDate")
        end = r.get("end_date") or r.get("endDate")
        if not start or not end:
            raise ValueError("Each compare_date_ranges entry needs start_date "
                             f"and end_date; got {r!r}.")
        ranges.append({"name": r.get("name") or f"compare_{i}",
                       "start": start, "end": end})
    if len(ranges) > MAX_DATE_RANGES:
        raise ValueError(
            f"GA4 accepts at most {MAX_DATE_RANGES} date ranges in one report "
            f"-- the primary range plus up to {MAX_DATE_RANGES - 1} "
            f"comparisons; got {len(ranges)}. Split it into two exports.")
    return ranges


def _quota(resp):
    """Remaining property quota from a response, or None if not reported.

    Recorded because a large export can spend a real share of the day's
    tokens, and the next request failing with "quota exhausted" is far less
    confusing when the previous receipt said how much was left.
    """
    q = getattr(resp, "property_quota", None)
    if not q:
        return None
    out = {}
    for name in ("tokens_per_day", "tokens_per_hour",
                 "tokens_per_project_per_hour"):
        status = getattr(q, name, None)
        if status is not None:
            out[f"{name}_remaining"] = getattr(status, "remaining", None)
    return out or None


def _combinations(resp, rows, n_ranges):
    """How many dimension combinations a page held -- GA4's paging unit.

    The dateRange column is left out of the key, so one combination's rows
    across every range count once.
    """
    names = [h.name for h in resp.dimension_headers]
    if n_ranges <= 1 or "dateRange" not in names:
        return len(rows)
    keep = [j for j, n in enumerate(names) if n != "dateRange"]
    return len({tuple(r[j] for j in keep) for r in rows})


def run(property_id, start_date, end_date, metrics, dimensions,
        dimension_filter=None, limit=None, client=None, metric_filter=None,
        order_bys=None, compare_date_ranges=None, currency_code=None):
    """Execute the report. Returns (columns, rows, meta_fragment)."""
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, FilterExpression, Metric, OrderBy,
        RunReportRequest)

    ranges = _date_ranges(start_date, end_date, compare_date_ranges)
    client = client or _client()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=r["start"], end_date=r["end"],
                               name=r["name"]) for r in ranges],
        dimensions=[Dimension(name=d) for d in (dimensions or [])],
        metrics=[Metric(name=m) for m in metrics],
        # Always: it costs nothing and lets the receipt say what is left.
        return_property_quota=True,
    )
    if dimension_filter:
        # filter_for_meta below still sees the original dimension_filter,
        # untouched by this coercion, so the sidecar records exactly what
        # the caller sent.
        request.dimension_filter = _coerce_filter(dimension_filter)
    if metric_filter:
        request.metric_filter = _parse_message(
            FilterExpression, metric_filter, "metric_filter",
            '{"filter": {"fieldName": "sessions", "numericFilter": '
            '{"operation": "GREATER_THAN", "value": {"int64Value": "100"}}}}')
    if order_bys:
        request.order_bys = [_parse_message(
            OrderBy, o, "order_bys",
            '[{"metric": {"metricName": "sessions"}, "desc": true}]')
            for o in order_bys]
    if currency_code:
        request.currency_code = currency_code
    # Page with offset until every row the query matched is in hand, or the
    # caller's own limit is reached. This used to be a single request, so an
    # export with no limit got GA4's default of 10,000 rows and wrote a CSV
    # that looked complete and was not (issue #6).
    #
    # Paging counts dimension COMBINATIONS, not rows. With one date range they
    # are the same. With several, GA4's limit, offset and row_count all count
    # combinations and each comes back as one row per range -- measured
    # 2026-10-07: row_count 1,831, rows 3,662. Offsetting by rows returned
    # skipped half the data without an error (card #131).
    columns, rows = None, []
    row_count, pages, quota, units = 0, 0, None, 0
    sampled = other_row_loss = False
    while pages < MAX_PAGES:
        want = PAGE_SIZE
        if limit:
            remaining = limit - units
            if remaining <= 0:
                break
            want = min(want, remaining)
        request.limit = want
        request.offset = units
        resp = client.run_report(request)
        pages += 1

        page_columns, page_rows = rows_from_response(resp)
        if columns is None:
            columns = page_columns
            n_dim_cols = len(resp.dimension_headers)
        row_count = resp.row_count
        sampled = sampled or was_sampled(resp)
        other_row_loss = other_row_loss or had_other_row_loss(resp)
        quota = _quota(resp) or quota
        rows.extend(page_rows)
        units += _combinations(resp, page_rows, len(ranges))

        if not dimensions:
            # No dimensions means one combination: every range's total, all
            # on this page. GA4's row_count here counts the ranges, and it
            # hands the same rows back at any offset, so paging on wrote every
            # row twice (#1993, measured 2026-11-20).
            row_count = 1 if page_rows else 0
            break

        goal = min(row_count, limit) if limit else row_count
        # An empty page means the server has nothing further to give, whatever
        # row_count claims. Stopping there is what keeps a misbehaving API from
        # turning this into MAX_PAGES requests.
        if not page_rows or units >= goal:
            break

    # A GA4 report never repeats a full dimension key (dateRange included),
    # so a repeat means paging went wrong. Counted so the receipt says so
    # instead of reading all-clear over a doubled file (#1993).
    duplicate_rows = 0
    if rows:
        duplicate_rows = len(rows) - len({tuple(r[:n_dim_cols]) for r in rows})

    if units >= row_count:
        incomplete_reason = None
    elif limit and units >= limit:
        incomplete_reason = "caller_limit"
    else:
        incomplete_reason = "server_stopped"

    meta = {
        "source": "ga4",
        "property_id": str(property_id),
        "metrics": list(metrics),
        "dimensions": list(dimensions or []),
        # Never the raw object: a real FilterExpression is a protobuf
        # message, not JSON-serialisable, and this fragment is written to a
        # .meta.json sidecar.
        "dimension_filter": filter_for_meta(dimension_filter),
        "metric_filter": filter_for_meta(metric_filter),
        "order_bys": list(order_bys) if order_bys else None,
        "date_range": {"start": start_date, "end": end_date},
        # Every range with its name, primary first. With more than one, the
        # file has a dateRange column holding these names.
        "date_ranges": ranges,
        "currency_code": currency_code or None,
        "property_quota": quota,
        "sampled": sampled,
        "data_loss_from_other_row": other_row_loss,
        # The total the query matched, independent of any limit. NOT called
        # row_count: write_export sets row_count to the rows WRITTEN, and when
        # this was named row_count it was silently overwritten -- a capped
        # export of 100 out of 23,000 reached the receipt saying 100, and the
        # 23,000 was gone. row_limit_hit keeps its name for compatibility; it
        # means "this file holds fewer rows than the query matched", and
        # incomplete_reason says why.
        #
        # With compared date ranges, GA4's own count is of dimension
        # combinations; a complete file holds one row per combination per
        # range, which is the number recorded here (measured: GA4 returns
        # every range for every combination, zeros included).
        "rows_matched": row_count * len(ranges),
        "dimension_combinations_matched": row_count,
        "rows_fetched": len(rows),
        "pages_fetched": pages,
        "duplicate_rows": duplicate_rows,
        "limit_requested": limit or None,
        "row_limit_hit": units < row_count,
        "incomplete_reason": incomplete_reason,
    }
    return columns, rows, meta
