"""Search Console over REST.

Search Console has no GAPIC client -- it is discovery-based. Rather than add
google-api-python-client, this uses AuthorizedSession from google-auth, which
is already installed and handles token refresh. Both endpoints we need are a
single request with no discovery document.

Endpoint paths are the v3 "webmasters" paths served under the searchconsole
host; Google consolidated the two services, and only searchconsole.googleapis.com
exists in the API library.

Confirmed against the live API, both that the paths resolve and that they
return real data. On 2026-09-04, before re-consent, a credential holding
analytics.readonly only got HTTP 403 "Request had insufficient
authentication scopes" -- not 404 -- on all three, which already showed the
paths existed and routed correctly (a wrong path would 404 instead of 403).
Later the same day, after re-consent granted webmasters.readonly, all three
were called again and returned real data: 220 Search Console properties from
the sites path, 28 rows of query/date data from the searchAnalytics path,
and PASS verdicts with indexing status from the urlInspection path. All
three:

    GET  https://searchconsole.googleapis.com/webmasters/v3/sites
    POST https://searchconsole.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query
    POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect
"""

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
BASE = "https://searchconsole.googleapis.com"


class GscError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


def authorized_session():
    """An authorised session for the Search Console scope."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    try:
        creds, _ = google.auth.default(scopes=[SCOPE])
    except Exception as exc:
        raise GscError(
            f"Could not load credentials for Search Console ({exc}). Check "
            "credential_status. A Search Console permission failure has two "
            "causes needing opposite responses: the credential may predate "
            "the webmasters.readonly scope, which re-minting fixes, or this "
            "Google account may not be a verified owner or user on the site, "
            "which no re-mint fixes -- someone with access has to add the "
            "account in Search Console. Do not re-mint on a guess; it opens "
            "a browser and replaces a working credential.")
    return AuthorizedSession(creds)


# Our own limits, so they are visible here rather than inherited from
# google-auth's default (120 s for both). A host that can't be reached is
# never merely slow, so connecting gets a short limit. Waiting for the answer
# gets a long one: on 2026-11-20 a healthy 25,000-row page took 61.7 s, and
# cutting off a page that is working costs more than waiting (#2007 R1).
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 300


def call(method, url, session=None, **kw):
    """One request. Raises GscError carrying Google's own message."""
    import requests

    sess = session or authorized_session()
    kw.setdefault("timeout", (CONNECT_TIMEOUT, READ_TIMEOUT))
    try:
        resp = sess.request(method, url, **kw)
    except requests.exceptions.ConnectTimeout:
        raise GscError(
            f"Search Console could not be reached within {CONNECT_TIMEOUT} "
            "seconds. Check the network connection, then try again.")
    except requests.exceptions.Timeout:
        raise GscError(
            f"Search Console did not answer within {READ_TIMEOUT // 60} "
            "minutes. Google is sometimes slow on large requests; try again, "
            "or narrow the date range or the dimensions.")
    except Exception as exc:
        # str(exc) is "" for a message-less exception -- some timeout and
        # connection-reset paths raise one -- which would render as "failed
        # ()." and tell the reader nothing at all. Name the type instead.
        detail = str(exc) or f"{type(exc).__name__} (no message)"
        raise GscError(f"Search Console request failed ({detail}).")

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = (resp.text or "")[:300]
        message = f"Search Console returned {resp.status_code}: {detail}"
        if resp.status_code == 403:
            # The point where a user actually meets this. Naming only the
            # scope sends them to re-mint -- a browser consent flow that
            # destroys a working credential -- for a problem re-minting
            # cannot touch.
            message += ("\n\nTwo different causes produce a 403 here, and "
                        "they need opposite responses: the credential may "
                        "lack the webmasters.readonly scope (call "
                        "credential_status; re-minting fixes it), or this "
                        "Google account may not be a verified owner or user "
                        "on that specific site (no re-mint fixes that -- "
                        "someone with access has to add the account in "
                        "Search Console). If gsc_list_sites shows the site, "
                        "access is not the problem.")
        raise GscError(message)

    try:
        data = resp.json()
    except Exception as exc:
        raise GscError(f"Search Console returned unparseable JSON ({exc}).")

    if not isinstance(data, dict):
        raise GscError(
            f"Search Console returned {type(data).__name__} where an object "
            f"was expected. This usually means something other than the API "
            f"answered — a proxy, a captive portal, or a sign-in page.")
    return data


def property_type(site_url):
    """domain or url_prefix -- the distinction that changes what a site covers."""
    return "domain" if str(site_url).startswith("sc-domain:") else "url_prefix"


def _covers(site_url):
    if property_type(site_url) == "domain":
        bare = str(site_url).split(":", 1)[1]
        return (f"all subdomains of {bare}, on both http and https")
    return f"only URLs beginning {site_url} — subdomains are NOT included"


def _host(site_url):
    """The host a site names: bare for a domain property, from the URL otherwise."""
    url = str(site_url)
    if property_type(url) == "domain":
        return url.split(":", 1)[1].strip().lower()
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def site_form_groups(sites):
    """{site name: [site_url, ...]} for every site listed in MORE THAN ONE form.

    One site can be verified several ways -- sc-domain:example.com,
    https://example.com/, http://example.com/, https://www.example.com/ --
    and each form covers different URLs, so each gives a different answer.
    Which one the user means is theirs to say (#2000); this only finds where
    the question has to be asked.

    Keyed on the HOST a question would be about, never on a covering domain
    (review of PR #6): keyed on the domain, an institution's apex
    property swallowed every subdomain into one "site", and two nested domain
    properties never met.

    - Every URL-prefix host is a site, with a leading "www." folded in, so
      http and https, and www and bare, land together. A path prefix
      (https://example.com/blog/) joins its host too: for the blog it is a
      different answer, so asking is right.
    - Every domain property's own host is a site.
    - Each site also gets every listed domain property covering it (the host
      itself or a parent), so one domain property can sit in many groups.
    """
    def fold(host):
        return host[4:] if host.startswith("www.") else host

    domains = [(s["site_url"], _host(s["site_url"])) for s in sites
               if property_type(s["site_url"]) == "domain"]
    groups = {}
    for s in sites:
        host = _host(s["site_url"])
        if host:
            groups.setdefault(fold(host), [])
    for s in sites:
        url, host = s["site_url"], _host(s["site_url"])
        if host and property_type(url) != "domain":
            groups[fold(host)].append(url)
    for key in groups:
        for url, d in domains:
            if key == fold(d) or key.endswith("." + fold(d)):
                groups[key].append(url)
    return {k: v for k, v in sorted(groups.items()) if len(v) > 1}


def impressions_window(days=28, today=None):
    """(start, end) ISO dates for the last `days` complete days.

    Ends yesterday rather than today: Search Console data lags two to three
    days, so today's row is always near-empty and would make a live site look
    dead -- the opposite of what this comparison is for.
    """
    import datetime
    end = (today or datetime.date.today()) - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def site_impressions(site_url, session=None, days=28, today=None):
    """Total impressions for one site over the last `days`. Never raises.

    Returns {"impressions": int or None, "error": str or None}. None means
    unknown, never zero: a site the credential can list but cannot query --
    a restricted-permission property, a verification that lapsed -- must
    degrade to unknown rather than abort the listing it appears in, the same
    way enrich.candidate_facts does for GA. Reporting it as zero would be a
    fabricated fact, and zero is exactly the answer this is used to detect.
    """
    start, end = impressions_window(days=days, today=today)
    try:
        columns, rows, _ = search_analytics(
            site_url, start, end, [], row_limit=1, session=session)
    except Exception as exc:
        # A message-less exception makes str(exc) "" -- falsy, and so
        # indistinguishable from "no error" to a truthiness check. Name the
        # type so the caller always has something non-empty to show.
        message = str(exc) or f"{type(exc).__name__} (no message)"
        return {"impressions": None, "error": message, "start": start,
                "end": end}

    try:
        idx = columns.index("impressions")
    except ValueError:  # pragma: no cover - guards a column rename
        return {"impressions": None, "error": "no impressions column returned",
                "start": start, "end": end}

    total = 0
    for row in rows:
        try:
            total += int(float(row[idx]))
        except (IndexError, TypeError, ValueError):
            continue
    return {"impressions": total, "error": None, "start": start, "end": end}


def list_sites(session=None, enrich=False, days=28, today=None,
               contains=""):
    """Every site this credential can reach, with type and coverage.

    contains, when set, filters to sites whose site_url contains it
    (case-insensitive) before anything else happens. That "before anything
    else" is the point: with enrich=True, filtering first means enrichment
    -- one Search Console request per site -- runs only over the filtered
    subset, so the request count follows what the caller actually asked
    about rather than the size of the whole account.

    With enrich=True each entry also carries impressions over the last
    `days` complete days, and the window they cover. That is the only thing
    distinguishing a live property from one that was verified and forgotten --
    and the two forms of the same site
    (sc-domain:example.edu against https://example.edu/) look nearly
    identical in a list while covering very different things.
    """
    data = call("GET", f"{BASE}/webmasters/v3/sites", session=session)
    needle = contains.lower()
    out = []
    for entry in data.get("siteEntry", []) or []:
        url = entry.get("siteUrl", "")
        if needle and needle not in url.lower():
            continue
        row = {
            "site_url": url,
            "permission_level": entry.get("permissionLevel", ""),
            "type": property_type(url),
            "covers": _covers(url),
        }
        if enrich:
            facts = site_impressions(url, session=session, days=days,
                                     today=today)
            row["impressions"] = facts["impressions"]
            row["impressions_error"] = facts["error"]
            row["impressions_range"] = {"start": facts["start"],
                                        "end": facts["end"]}
        out.append(row)
    return out


def _count(value):
    """The API sends int64 counts as strings. None stays None: unknown."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_sitemaps(site_url, session=None):
    """Sitemaps submitted for site_url, read-only. Card #130.

    The deprecated per-type `indexed` count is dropped on purpose: Google no
    longer fills it, and a 0 there reads as "nothing indexed". Never-downloaded
    sitemaps report None rather than an empty string, which is a fact about
    Google, not a gap in the data.
    """
    from urllib.parse import quote
    data = call("GET", f"{BASE}/webmasters/v3/sites/"
                       f"{quote(site_url, safe='')}/sitemaps", session=session)
    out = []
    for sm in data.get("sitemap", []) or []:
        out.append({
            "path": sm.get("path", ""),
            "type": sm.get("type"),
            "is_sitemaps_index": sm.get("isSitemapsIndex"),
            "is_pending": sm.get("isPending"),
            "last_submitted": sm.get("lastSubmitted"),
            "last_downloaded": sm.get("lastDownloaded"),
            "errors": _count(sm.get("errors")),
            "warnings": _count(sm.get("warnings")),
            "submitted": {c.get("type", "?"): _count(c.get("submitted"))
                          for c in sm.get("contents", []) or []},
        })
    return out


SITEMAP_COLUMNS = ["path", "type", "is_sitemaps_index", "is_pending",
                   "last_submitted", "last_downloaded", "errors", "warnings",
                   "submitted_urls", "submitted_by_type"]


def sitemap_rows(sitemaps):
    """list_sitemaps() output as CSV rows with fixed columns."""
    rows = []
    for sm in sitemaps:
        counts = {k: v for k, v in sm["submitted"].items() if v is not None}
        total = sum(counts.values()) if counts else None
        rows.append([_cell(sm["path"]), _cell(sm["type"]),
                     _cell(sm["is_sitemaps_index"]), _cell(sm["is_pending"]),
                     _cell(sm["last_submitted"]), _cell(sm["last_downloaded"]),
                     _cell(sm["errors"]), _cell(sm["warnings"]), _cell(total),
                     ";".join(f"{k}={v}" for k, v in sorted(counts.items()))])
    return list(SITEMAP_COLUMNS), rows


INSPECT_COLUMNS = [
    "url", "verdict", "coverageState", "googleCanonical", "userCanonical",
    "robotsTxtState", "indexingState", "pageFetchState", "lastCrawlTime",
    "crawledAs", "sitemap", "referringUrls", "inspectionResultLink",
    # Card #132. Appended, not inserted, so existing column positions hold.
    "richResultsVerdict", "richResultTypes", "richResultIssues",
]


def inspect_row(url, payload):
    """One CSV row from one inspection response, in INSPECT_COLUMNS order."""
    result = (payload or {}).get("inspectionResult", {}) or {}
    status = result.get("indexStatusResult", {}) or {}

    def field(name):
        value = status.get(name, "")
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return "" if value is None else str(value)

    return [
        url,
        field("verdict"),
        field("coverageState"),
        field("googleCanonical"),
        field("userCanonical"),
        field("robotsTxtState"),
        field("indexingState"),
        field("pageFetchState"),
        field("lastCrawlTime"),
        field("crawledAs"),
        field("sitemap"),
        field("referringUrls"),
        str(result.get("inspectionResultLink", "") or ""),
    ] + _rich_results(result.get("richResultsResult") or {})


def _rich_results(rich):
    """[verdict, types, issues] from richResultsResult; blanks if absent.

    Absent is the common case -- most pages carry no structured data Google
    recognises -- and is not an error.
    """
    detected = rich.get("detectedItems", []) or []
    types = [d.get("richResultType", "") for d in detected]
    issues = []
    for d in detected:
        for item in d.get("items", []) or []:
            for i in item.get("issues", []) or []:
                issues.append(f"{d.get('richResultType', '')}: "
                              f"{i.get('issueMessage', '')} "
                              f"({i.get('severity', '')})")
    return [str(rich.get("verdict", "") or ""), ", ".join(types),
            "; ".join(issues)]


def inspect_urls(site_url, urls, session=None, today=None):
    """Inspect each URL. The API has no batch endpoint, so this is a loop.

    A failure partway does not discard what succeeded: rows collected so far
    are returned, and the receipt records how far it got. A truncated run that
    looked complete is the failure most likely to produce a wrong report.
    """
    import datetime
    day = (today or datetime.date.today()).isoformat()

    rows, stopped = [], None
    for url in urls:
        try:
            payload = call(
                "POST", f"{BASE}/v1/urlInspection/index:inspect",
                session=session,
                json={"inspectionUrl": url, "siteUrl": site_url,
                      "languageCode": "en-US"})
        except GscError as exc:
            stopped = f"stopped at {url}: {exc}"
            break
        rows.append(inspect_row(url, payload))

    meta = {
        "source": "gsc_url_inspection",
        "site_url": site_url,
        # site_type belongs here, not in the tool layer that used to add it:
        # a direct caller of this function got a sidecar missing the one
        # field that says what the site_url covers. search_analytics has
        # always recorded it here, and two sidecars from the same server
        # describing the same site with different keys is how a reader six
        # months on concludes one of them is incomplete.
        "site_type": property_type(site_url),
        # An inspection is a point-in-time snapshot rather than a queried
        # range, so start and end are both the day it was taken. Recorded
        # under the same key search_analytics uses, so both sidecars can be
        # read the same way.
        "date_range": {"start": day, "end": day},
        "urls_requested": len(urls),
        "rows_written": len(rows),
        "stopped_reason": stopped,
        "sampled": False,
        "row_limit_hit": False,
    }
    return list(INSPECT_COLUMNS), rows, meta


PAGE_SIZE = 25000

ANALYTICS_METRICS = ["clicks", "impressions", "ctr", "position"]


def _page_path(url):
    """The path component of a GSC page URL.

    Split out so that comparing GA (which reports paths) against GSC (which
    reports full URLs) is a lookup rather than a repair job. The join itself
    stays in analysis; this only keeps it possible.
    """
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).path or ""
    except Exception:
        return ""


def _cell(value):
    """A CSV cell: never the literal text "None"."""
    return "" if value is None else str(value)


_BY_PAGE_NOTE = (
    "Grouped by page: Search Console counts one search once per page of this "
    "site it showed, so these totals can EXCEED the site total for the same "
    "range.")
_BY_QUERY_NOTE = (
    "Grouped by query: anonymised queries are left out, so these totals FALL "
    "SHORT of the site total for the same range.")
_DENOMINATOR_NOTE = (
    "Do not divide a figure from this file by a total from a differently "
    "grouped export. For a share of the site, take the denominator from a "
    "date-only export of the same property and range: aggregation_type "
    "byProperty counts each search once, byPage counts it the way a by-page "
    "export does.")


def aggregation_note(dimensions):
    """Why this file's totals may not match the site total, or None.

    Issue #3. Grouped by [date] a property summed to 126,431 impressions;
    grouped by [page], over the same range, to 128,326. Documented Google
    behaviour, and silent in the receipt -- so a by-page number got divided by
    a by-date total. The note runs both directions because the effect does.
    """
    dims = set(dimensions or [])
    parts = []
    if "page" in dims:
        parts.append(_BY_PAGE_NOTE)
    if "query" in dims:
        parts.append(_BY_QUERY_NOTE)
    if not parts:
        return None
    return " ".join(parts + [_DENOMINATOR_NOTE])


# What the Search Analytics API accepts, as of 2026-10. Checked here, before
# the request leaves, because Google's answer to a bad value is a bare 400 and
# an agent handed a bare 400 guesses. Card #130.
SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
DIMENSIONS = ("date", "hour", "page", "query", "country", "device",
              "searchAppearance")
FILTER_DIMENSIONS = ("page", "query", "country", "device", "searchAppearance")
OPERATORS = ("equals", "notEquals", "contains", "notContains",
             "includingRegex", "excludingRegex")
DATA_STATES = ("final", "all", "hourly_all")
AGGREGATION_TYPES = ("auto", "byPage", "byProperty", "byNewsShowcasePanel")

# Feeds rather than searches: no query, no byProperty, no position.
_FEED_TYPES = ("discover", "googleNews")

# GA4 names an agent working both sources will reach for.
_GA_DIMENSION_HINTS = {"pagePath": "page", "pageLocation": "page",
                       "landingPage": "page", "deviceCategory": "device",
                       "searchTerm": "query"}


def _choices(values):
    return ", ".join(values)


def build_filters(page_contains=None, filters=None):
    """Validated dimension filters, or [] -- ANDed in one filter group.

    One group, not one per filter: the API ANDs filters within a group, and
    page_contains plus a country filter means both. page_contains is kept
    because existing callers and docs use it; it is only shorthand for a page
    `contains` filter.
    """
    out = []
    if page_contains:
        out.append({"dimension": "page", "operator": "contains",
                    "expression": page_contains})
    for f in filters or []:
        if not isinstance(f, dict):
            raise GscError(
                "Each filter must be an object with dimension, operator and "
                f"expression; got {f!r}.")
        dim = f.get("dimension")
        op = f.get("operator") or "equals"
        expr = f.get("expression")
        if dim not in FILTER_DIMENSIONS:
            raise GscError(
                f"Cannot filter on {dim!r}. Filterable dimensions: "
                f"{_choices(FILTER_DIMENSIONS)}. A date range is set with "
                "start_date and end_date, not a filter.")
        if op not in OPERATORS:
            raise GscError(f"Unknown filter operator {op!r}. Operators: "
                           f"{_choices(OPERATORS)}. The regex operators use "
                           "RE2 syntax.")
        if expr is None or str(expr) == "":
            raise GscError(f"The {dim} filter has no expression -- the value "
                           "to match.")
        out.append({"dimension": dim, "operator": op, "expression": str(expr)})
    return out


def validate_request(dimensions, search_type, data_state, aggregation_type,
                     filters):
    """Refuse, with the allowed values, anything the API would 400 on."""
    if search_type not in SEARCH_TYPES:
        raise GscError(
            f"Unknown search_type {search_type!r}. Choices: "
            f"{_choices(SEARCH_TYPES)}. Google's AI Overviews / AI Mode "
            "reports are not in the API -- they exist only in the Search "
            "Console web interface, and no search_type reaches them.")
    for d in dimensions:
        if d not in DIMENSIONS:
            hint = _GA_DIMENSION_HINTS.get(d)
            also = (f" {d!r} is a Google Analytics name; Search Console calls "
                    f"it {hint!r}." if hint else "")
            raise GscError(f"Unknown dimension {d!r}. Dimensions: "
                           f"{_choices(DIMENSIONS)}.{also}")
    if data_state not in DATA_STATES:
        raise GscError(f"Unknown data_state {data_state!r}. Choices: "
                       f"{_choices(DATA_STATES)}.")
    if "hour" in dimensions and data_state != "hourly_all":
        raise GscError("The hour dimension needs data_state='hourly_all'. "
                       "Hourly data covers roughly the last 10 days only.")
    if search_type in _FEED_TYPES:
        # Measured 2026-10-07: Google 400s each of these for discover and
        # googleNews. Feeds are not searches; there is no query to report.
        if "query" in dimensions or any(f["dimension"] == "query"
                                        for f in filters):
            raise GscError(
                f"search_type {search_type!r} has no query dimension and "
                "cannot be filtered by query -- it is a feed, not a search, "
                "so nobody typed anything. Group or filter by page, country, "
                "device or date instead.")
        if aggregation_type == "byProperty":
            raise GscError(
                f"search_type {search_type!r} does not accept aggregation_type "
                "'byProperty'; use 'auto' or 'byPage'.")
    if aggregation_type not in AGGREGATION_TYPES:
        raise GscError(f"Unknown aggregation_type {aggregation_type!r}. "
                       f"Choices: {_choices(AGGREGATION_TYPES)}.")
    if aggregation_type == "byProperty" and (
            "page" in dimensions
            or any(f["dimension"] == "page" for f in filters)):
        raise GscError(
            "aggregation_type 'byProperty' cannot be combined with a page "
            "dimension or a page filter -- Google refuses it. Use 'auto' or "
            "'byPage', and read aggregation_note in the receipt.")


def search_analytics(site_url, start_date, end_date, dimensions,
                     page_contains=None, data_state="final", row_limit=None,
                     session=None, search_type="web", filters=None,
                     aggregation_type="auto"):
    """Query search analytics, paginating past the 25,000-row page cap.

    A page short of PAGE_SIZE always ends pagination -- it is the API's own
    signal that nothing more follows. row_limit is enforced by fetching one
    row beyond what the caller asked for: page fullness alone cannot tell a
    full last page from a full page with more behind it, so only actually
    seeing row_limit + 1 rows proves the result was truncated. The extra row
    is trimmed before returning.
    """
    from urllib.parse import quote

    endpoint = (f"{BASE}/webmasters/v3/sites/"
                f"{quote(site_url, safe='')}/searchAnalytics/query")

    dimensions = list(dimensions or [])
    built_filters = build_filters(page_contains, filters)
    validate_request(dimensions, search_type, data_state, aggregation_type,
                     built_filters)
    # Fetch one row beyond the caller's limit. A result whose true size equals
    # row_limit exactly is complete, and only actually seeing row_limit + 1
    # rows proves otherwise -- page fullness cannot distinguish a full last
    # page from a full page with more behind it. The extra row is trimmed
    # before returning.
    hard_stop = row_limit + 1 if row_limit else None

    # Ask for what is actually wanted. Requesting the full 25,000-row page
    # for row_limit=100 makes Google assemble 250x the data, and the 24,900
    # surplus rows are discarded before the caller ever sees them.
    page_size = min(PAGE_SIZE, hard_stop) if hard_stop else PAGE_SIZE

    body_base = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": page_size,
        "dataState": data_state,
        # Always sent, never left to Google's default. A receipt that says
        # "web" should mean the request said "web".
        "type": search_type,
    }
    if aggregation_type != "auto":
        body_base["aggregationType"] = aggregation_type
    if built_filters:
        body_base["dimensionFilterGroups"] = [{"groupType": "and",
                                               "filters": built_filters}]

    rows, start_row, limit_hit = [], 0, False
    stopped, previous = None, None

    while True:
        data = call("POST", endpoint, session=session,
                    json=dict(body_base, startRow=start_row))
        page = data.get("rows", []) or []
        # The same full page twice means the server ignored startRow. Asking
        # again would get it again, forever, and writing it would double the
        # file (#1994). Stop, and let the receipt say the file is incomplete.
        if page and page == previous:
            stopped = "server_repeated_page"
            break
        previous = page

        for r in page:
            keys = list(r.get("keys", []))
            # Pad a SHORT row to one key per dimension: export refuses a file
            # whose rows don't match its columns, so one short row would cost
            # the whole export, and a missing key is honestly blank (#2007).
            # A LONG row is left alone on purpose: cutting it would discard
            # data nobody understands, and export's refusal is the right
            # answer to it (from review).
            keys += [""] * (len(dimensions) - len(keys))
            page_url = ""
            if "page" in dimensions:
                idx = dimensions.index("page")
                # A row with fewer keys than dimensions asked for would
                # otherwise raise IndexError and lose the whole export.
                page_url = keys[idx] if idx < len(keys) else ""
            rows.append(keys + [_cell(r.get("clicks")),
                                _cell(r.get("impressions")),
                                _cell(r.get("ctr")),
                                _cell(r.get("position")),
                                _page_path(page_url)])
            if hard_stop and len(rows) >= hard_stop:
                break

        # Compared against the size actually requested, not PAGE_SIZE: with a
        # row_limit the request asks for fewer, and a short page is the API's
        # own signal that nothing more follows.
        if (hard_stop and len(rows) >= hard_stop) or len(page) < page_size:
            break
        start_row += page_size

    if row_limit and len(rows) > row_limit:
        limit_hit = True
        rows = rows[:row_limit]

    # A Search Console report never repeats a full key (the requested
    # dimensions), so a repeat means paging went wrong and every sum taken
    # from the file is inflated. Counted so the receipt says so instead of
    # reading all-clear, as GA exports do since #1993 (#1994).
    n_keys = len(dimensions)
    duplicate_rows = len(rows) - len({tuple(r[:n_keys]) for r in rows})

    columns = dimensions + ANALYTICS_METRICS + ["page_path"]
    meta = {
        "source": "gsc_search_analytics",
        "site_url": site_url,
        "site_type": property_type(site_url),
        "dimensions": dimensions,
        "date_range": {"start": start_date, "end": end_date},
        "search_type": search_type,
        "data_state": data_state,
        "aggregation_type": aggregation_type,
        "page_contains": page_contains,
        "filters": built_filters,
        "rows_returned": len(rows),
        "row_limit_hit": limit_hit,
        "sampled": False,
        # Always present, null when nothing went wrong. A key that appears
        # only on failure is ambiguous when it is missing: the reader cannot
        # tell "this run completed" from "this field predates the code that
        # writes it". inspect_urls records it the same way.
        "stopped_reason": stopped,
        "duplicate_rows": duplicate_rows,
        # Always present, null when the totals are directly comparable with a
        # date-only export of the same range. See aggregation_note().
        "aggregation_note": aggregation_note(dimensions),
    }
    return columns, rows, meta


def suggested_filename(kind, site_url, start, end):
    """A default name legible in Finder without opening the file."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-",
                  str(site_url).lower().replace("sc-domain:", "")).strip("-")
    return (f"gsc-{slug}-{kind}"
            f"-{start.replace('-', '')}-{end.replace('-', '')}.csv")
