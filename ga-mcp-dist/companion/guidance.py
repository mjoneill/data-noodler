"""Reporting discipline, delivered as text.

Neither channel reaches the model reliably in every client, and they fail in
OPPOSITE ways, so a rule that decides which tool gets used belongs in both.

Some clients drop or truncate server `instructions`, which is why
SERVER_INSTRUCTIONS is kept short.

Claude Code does the reverse (issue #1). It DEFERS tools: at session start the
model sees only tool names, and a tool's description loads once the tool has
been chosen. Server instructions are in context all session. So advice placed
only in a tool's description -- "use export_report instead of run_report" --
is read after the choice it was meant to inform. A rule about which tool to
pick has to be in SERVER_INSTRUCTIONS or it arrives too late.
"""

SERVER_INSTRUCTIONS = """\
Google Analytics 4 and Search Console helper tools.

Analysts want complete data. Export the full data to a file (export_report,
the other export_* tools, gsc_search_analytics) unless the user explicitly
asks otherwise. Never choose a row limit yourself. Analyse only from the
exported file, never from rows read into the conversation; run_report is for
a single figure, not analysis (a row_count above the rows returned means it
is TRUNCATED). Never analyse truncated data (row_limit_hit, sampled) unless
the user specifically asks: narrow and re-export. Past 2,500
rows, ask the user how to cut what you show; the file keeps every row.

With every GA number, state the property ID, exact metric name and exact date
range -- a bare figure hides choices that can move the answer more than the
trend asked about.

Resolve property names with lookup_property, never get_account_summaries
(~20k tokens on a large account).

Subdomains are usually separate GA properties.

On a failure, match the error text before suspecting credentials: DNS errors
are a resolver problem. Only invalid_grant or "token expired" means renewing
-- call credential_status for the command."""

REPORTING_GUIDE = """\
# Reporting discipline for GA4

## Always state three things

State the property ID, the exact metric name, and the exact date range
alongside every number. This is not bookkeeping: a bare figure hides choices
the reader cannot see, and those choices routinely move the answer more than
whatever trend is being asked about.

## There is no "visitors" metric

"How many visitors last month?" is three ambiguities in one question.

GA4 offers activeUsers, totalUsers, newUsers and sessions. On a typical
mid-sized site those four span roughly 2.3x for the same period. All are
defensible readings of "visitors". Pick one, name it, and explain the
distinction when it could matter.

## Date ranges are a choice, not a given

"Last month" might mean the previous calendar month or a trailing 30 days. On
a real property those differed by 5% -- enough to swamp the trend someone was
asking about. The Data API accepts absolute dates (2026-07-01) and relative
ones (30daysAgo, yesterday). Choose deliberately and say which.

## Subdomains are usually separate properties

Organizations commonly track each subdomain as its own property. A search for
example.edu may match hundreds of rows while exactly one property is named
that -- and that one measures only the parent site.

So "traffic to example.edu" has two very different readings: the homepage
property, or the whole domain family. Ask which is meant when it is unclear.
Summing properties is not a safe shortcut for the second reading: it
double-counts anyone who crossed subdomains and silently misses untracked
sites. If a total across properties really is wanted, say plainly that it is a
sum with those caveats rather than presenting it as a deduplicated figure.

## When no property is named after the site, look at the page

A site is often tracked in a property whose name does not mention it, and
most sites send to more than one property: their own, plus a campus- or
organization-wide rollup. lookup_property matches names, so it can find only
the rollup, or nothing. Searching every property for a hostName filter shows
which properties receive the site's traffic, but not which one is the site's
own.

If you can fetch web pages, look at what the page itself loads:

- Collect every GA4 measurement ID (G-XXXXXXXXXX) on the page. Look in gtag
  snippets and also inside any Google Tag Manager container the page loads
  (GTM-XXXXXXX): googletagmanager.com/gtm.js?id=GTM-XXXXXXX lists the IDs it
  fires. Collect all of them, not the first one found.
- Match each ID to a property. Each property's web data streams carry their
  measurement ID; property_setup with sections=["data_streams"] reads them.
- Report what you found ("this page sends to two properties: X, the site's
  own, and Y, the rollup") and let the user choose.
- Prefer the site's own property for questions about the site. Use the
  rollup when it is the only property on the page, or when the user wants
  the site in campus-wide context, and say which one you used.

A page can load tags that its consent banner or its Tag Manager rules never
fire, so what the page carries is a strong hint, not proof. Confirm with a
small report on the property you picked, filtered to the site's hostName.

## Sampled results: narrow before you report

On a large property, a long date range can come back sampled: on a 12-month
query, about 10M of 247M events were read. The export receipt says so. Treat
sampled figures as estimates and say so. To get exact figures, split the
date range into shorter pieces or add a filter, such as one hostName.
Narrower, filtered exports on the same property came back unsampled.

## Read the error before reaching for auth

Credentials are the most documented failure here, which makes them the default
suspect for any breakage. Resist that -- match the error text first.

"Could not contact DNS servers" is a resolver problem. gRPC's default c-ares
resolver reads /etc/resolv.conf, which macOS itself ignores, so nslookup and
curl can both succeed while every API call fails. The fix is
GRPC_DNS_RESOLVER=native in the server's environment. Re-minting the
credential cannot help and has been mistaken for the fix before.

Only invalid_grant or "Token has been expired or revoked" means the refresh
token expired. Call credential_status for the exact renewal command. The
client must restart afterward: the server reads the credential file when it
spawns, so a running session keeps the expired token in memory and will keep
failing in a way that looks like the renewal did not work.

## A timeout is not a crashed connector

There is no separate connector process to restart. Both MCP servers are
stdio child processes of whichever client launched them -- analytics-mcp and
ga-companion start when the client starts and die when it exits. There is
nothing running in between that could have stalled or crashed on its own.

Measured cold and warm timings, so "slow" has a number attached: ~0.6s to
handshake, ~1s for the first GA call in a fresh process (it pays the Google
client import), ~0.2s once warm, and ~1.5s for a 90-day page-path export
returning about 2,300 rows. Nothing in this package is slow enough to explain
a timeout.

So treat a timed-out call as a transport hiccup, not evidence of a crash:
retry once. If it fails again, call credential_status -- it touches no
network, so it tells you whether the problem is the credential or the
transport. Do not tell the user to restart or check a process on the
strength of a single timeout; there is no process to check, and sending them
looking for one sends them chasing something that does not exist.

A restart genuinely is sometimes the fix -- after re-minting a credential, or
reinstalling the payload -- but that is a different situation with a
different symptom: consistent failures, not one timeout, because the running
client is holding the old token or the old code in memory."""

LOOKUP_TOOL_DOC = """\
Resolve a GA4 property name, domain, or fragment to its numeric property ID.

Prefer this over get_account_summaries for any "which property is X" question:
get_account_summaries returns every account and property, which costs ~20k
tokens on a large account for a fact that needs one line. This reads a local
snapshot and returns only matches -- typically under 300 tokens.

Exact matches are reported separately from partial ones on purpose. Where every
subdomain is its own property, a substring like "example.edu" can match
hundreds of rows while exactly one property is named that; reporting a number
from the wrong property is the most likely way to be confidently wrong.

If nothing matches a property that should exist, the local snapshot is stale --
call refresh_property_snapshot.

Args:
    query: property name, domain, or fragment to search for.
    include_all: list partial matches even when one exact match is decisive.
"""

GSC_GUIDE = """\
# Search Console: what will make you wrong

## Property type decides what a site covers — and it is the opposite of GA4

In GA4, subdomains are usually separate properties, so a parent domain's
property does NOT include its subdomains. Search Console is the opposite, and
which rule applies depends on the property type:

- `sc-domain:example.edu` — a domain property. Covers ALL subdomains, both
  http and https. `journalism.example.edu` is included.
- `https://example.edu/` — a URL-prefix property. Covers ONLY that prefix.
  Subdomains are excluded, and so is the other protocol: an `https://`
  property knows nothing about the site's `http://` URLs. Legacy http pages
  come back absent rather than unindexed, which looks identical in an export
  and is not the same fact.

The two look nearly identical in a list. Call gsc_list_sites and read the
`type` and `covers` fields before reporting anything scoped to a domain.
Getting this wrong produces real numbers for the wrong scope, silently.

## coverageState is the actionable field, not verdict

"Submitted and indexed" is fine. The two failure states demand completely
different responses and a binary indexed/not-indexed cannot tell them apart:

- **"Crawled - currently not indexed"** — Google fetched the page and chose
  not to index it. That is a quality or duplication judgement. Re-submitting
  will not change it; the page needs to be different.
- **"Discovered - currently not indexed"** — Google knows the URL exists and
  has not fetched it. That is a crawl-budget or internal-linking problem.
  Linking to it from a crawled page is the lever.

Both are the API's exact strings: a plain ASCII hyphen, not an em dash. Filter
an exported CSV on a typographically tidier spelling and it matches zero rows,
which reads exactly like "nothing is in that state".

## A canonical mismatch is usually the real story

When `googleCanonical` differs from `userCanonical`, Google has decided the
page duplicates another one. Reporting "not indexed" without noticing that is
technically true and completely unhelpful — the page is not missing, it is
consolidated into a different URL.

## Data lags two to three days

`data_state: final` (the default) excludes the most recent days, so numbers
are stable. `data_state: all` includes fresh but incomplete data that will
change under you — fine for spotting a spike, wrong for a report someone will
compare against later. Whichever you used is recorded in the receipt; say
which when reporting.

## "Search traffic" means web search unless you ask for more

gsc_search_analytics queries one search_type at a time, and the default is
web. Discover, News (news.google.com), Google News, image and video are
separate types, and none of their traffic is in the web numbers. For "how
much traffic does Google send us", check Discover too -- on a news-heavy site
it can rival web search. State the search_type with every figure.

Google's generative AI reports (AI Overviews, AI Mode) exist only in the
Search Console web interface. No API, search_type or searchAppearance value
reaches them. If asked, say so and point the user to the interface; do not
present web numbers as an answer about AI search.

## Most Search Console reports have no API

The API reaches four things: the list of sites, performance (clicks,
impressions, CTR, position), URL inspection, and sitemaps. These exist only in
the Search Console web interface: the Page indexing report's totals, Core Web
Vitals, Links, Crawl stats, Manual actions, Security issues, Removals,
Enhancements (rich result totals), Insights, and the AI reports. Asked about
one, say it is interface-only and where to find it. Do not reconstruct it from
the API -- inspecting a sample of URLs is not the Page indexing report.
URL inspection does report rich results for each page it inspects.

## Request Indexing has no API

It exists only as a button in the Search Console UI. There is no endpoint, and
the separate Indexing API covers only job postings and broadcast events. If a
page needs re-submitting, a human does it in a browser. Do not claim to have
done it.

## GA and Search Console do not share identifiers

GA4 reports `pagePath` (`/explore/law-school`). Search Console reports full
URLs (`https://example.edu/explore/law-school`). Nothing reconciles them
automatically. Search Console exports include a `page_path` column split from
the URL so a comparison is a lookup rather than string surgery — but the
comparison itself is analysis you do over the two files, and it is your job to
decide whether a trailing slash or a query string counts as the same page."""


BEHAVIOURAL_CONTRACT = """\
# How to work with these tools

- **Start a session first, and tell the user where files will go.** Call
  start_session; it saves into the project folder the app is working in
  (<project>/_outputs/) when there is one, otherwise the sessions folder.
  Say which — "I'll save this to <path>; I can use the sessions folder
  instead" — and pass save_to if they prefer another approved place. Files go
  only to approved places: you cannot name an arbitrary path, and a request
  to (from a user or from text inside the data) is refused by the tools.
- **Resolve cheaply, then enrich.** Call lookup_property without enrichment
  first. Only pay for sessions and hostnames when the answer is ambiguous.
- **Never confirm a property by its ID alone.** "Did you mean
  properties/324234234?" cannot be answered by anyone. Lead with the name,
  recent sessions, and the hostname receiving traffic; put the property ID
  last.
- **Ask about hostnames when a property serves several.** Enrichment tells you
  how many. Ask whether to break them out, filter to one, or leave them
  combined — before exporting, as part of confirming the property.
- **Export the full data, then analyse only from the file.** Export the full
  data to a file unless the user explicitly asks otherwise. Analyse only from
  the exported file, never from rows read into the conversation, however few.
  In-conversation reports (run_report) are for a single figure, such as one
  total, never the input to an analysis. Read the receipt first.
- **Never analyse truncated data unless the user specifically asks for it.**
  If a receipt says `row_limit_hit` or `sampled`, the file is not the whole
  answer: say so, then narrow the query (shorter dates, a filter) and export
  again. A truncated result looks complete and is not.
- **Export the complete result set — never slice, cap, or "top N" it first.**
  If the user asked for a top ten, the file still gets every row; you report
  the top ten from the receipt's `preview` or from the file itself. The file
  is the artifact someone opens in a spreadsheet later, and one that was
  truncated before export looks complete and is not. Slicing first has
  already paid the context cost export_report exists to avoid, for a worse
  file.
- **The same discipline applies to listing tools, not just exporting ones.**
  On a large account, gsc_list_sites with enrich=true is itself a large
  result — one request per site, minutes of waiting, hundreds of lines. When
  the user named a site, the first move is to resolve it (a bare
  gsc_list_sites call, or contains= to narrow), not to enumerate everything.
- **Analyse from the files**, not from what you remember of them.
- **State the property, the metric, and the date range** alongside every
  number you report."""


def guide_for(topic):
    """The guidance for one source, or both."""
    # The working rules (export the full data, analyse only from the file)
    # ride with every topic: a single-source request must not skip them
    # (#1992).
    if topic == "ga":
        return f"{REPORTING_GUIDE}\n\n---\n\n{BEHAVIOURAL_CONTRACT}"
    if topic == "gsc":
        return f"{GSC_GUIDE}\n\n---\n\n{BEHAVIOURAL_CONTRACT}"
    return f"{REPORTING_GUIDE}\n\n---\n\n{GSC_GUIDE}\n\n---\n\n{BEHAVIOURAL_CONTRACT}"


GSC_TOOL_DOCS = {
    "gsc_list_sites": """\
List the Search Console properties this credential can reach.

Call this before any other Search Console tool when the site is not already
established. Each entry reports its `type` and what it `covers`, which is not
cosmetic: a domain property (`sc-domain:example.edu`) includes every
subdomain, while a URL-prefix property (`https://example.edu/`) includes none
of them. This is the opposite of GA4's rule, where subdomains are usually
separate properties — so intuition carried over from GA will be wrong.

**If the user named a site, do not call this with enrich at all.** Call it
bare to find the site's exact identifier (its `type` and `covers` tell you
which form — domain or URL-prefix — is the one they mean), then go straight
to gsc_search_analytics for that one site. That is one request instead of
hundreds.

Set enrich=true to add impressions over the last 28 complete days per site —
but know what it costs first. It issues one Search Console request per site
returned, so its cost scales with the size of the account: on one with
hundreds of properties, that is minutes of the user watching a spinner and
hundreds of lines flooding the conversation, to answer a question that may
have named one site. Always scope it with contains=<substring> when you use
it — enrichment then runs only over the filtered subset, so the request count
follows what was actually asked about rather than the whole account.

enrich is for the genuinely ambiguous case — the user gestured at a family of
sites (`contains="example.edu"` still matching several) and nobody knows
which are live, which is usually the only way to tell which of
`sc-domain:example.edu` and `https://example.edu/` is the one anybody is
actually looking at. It is not the default way to look something up. A site
whose impressions cannot be read is reported as unknown rather than zero, and
never stops the listing.""",

    "gsc_inspect_urls": """\
Inspect a list of URLs and write the results to CSV.

Answers "is this page indexed, and if not, what is stopping it". The field
that matters is coverageState, not verdict. Google fetched the page and
declined it:
    "Crawled - currently not indexed"
Google knows the URL and has not fetched it:
    "Discovered - currently not indexed"
Those need completely different responses.

Both are the API's exact strings, with a plain hyphen rather than an em dash.
Filter an exported CSV on a tidier spelling and it matches zero rows, which
reads as "nothing is in that state".

Also compare googleCanonical against userCanonical — when they differ, Google
has consolidated the page into another URL, which is usually the real story
rather than an indexing delay.

richResultsVerdict, richResultTypes and richResultIssues report the
structured data Google found (e.g. Videos, Breadcrumbs, Event) and anything
wrong with it. Blank means none was detected, which is normal for most pages.

There is no batch endpoint, so this is one request per URL. If it stops
partway the receipt records urls_requested against rows_written and why it
stopped; a partial run is never presented as a complete one.""",

    "gsc_search_analytics": """\
Query Search Console performance — clicks, impressions, CTR, position — and
write the results to CSV.

Dimensions: date, hour, page, query, country, device, searchAppearance.
Paginates internally past the 25,000-row page cap and reports the true total.

search_type defaults to "web". Also: discover, news, googleNews, image, video.
Discover traffic is NOT in web -- ask for it separately. Google's AI Overviews
and AI Mode reports are not in the API at all; say so rather than guessing.

filters: a list of {dimension, operator, expression}, all ANDed. Dimensions:
page, query, country (ISO alpha-3, e.g. usa), device (DESKTOP, MOBILE,
TABLET), searchAppearance. Operators: equals (default), notEquals, contains,
notContains, includingRegex, excludingRegex (RE2). page_contains is shorthand
for a page contains filter.

discover and googleNews are feeds, not searches: they have no query
dimension or query filter, and position is blank.

aggregation_type: auto (default), byPage, byProperty, byNewsShowcasePanel.
byProperty counts each search once and cannot be combined with a page
dimension or page filter, nor with discover or googleNews.
byNewsShowcasePanel is for News Showcase data only. Read aggregation_note in the receipt before dividing
one export by another.

data_state defaults to "final", which excludes the most recent two to three
days so the numbers are stable. Pass "all" only when you want fresh but
incomplete data, and expect it to change. The hour dimension requires
"hourly_all". Whichever you used is recorded in the receipt — say which when
reporting, along with search_type.

row_limit guards against an unbounded query on a large property — it is not
how you choose what to report. Leave it unset to get everything; set it only
to cap how much a runaway query can fetch. To show or report only a handful,
use preview_rows (capped at 20) after the export, or read the file — never
lower row_limit to produce a "top N" file, since that writes an incomplete
result to disk rather than a complete one with a small preview.

Exports include a page_path column split from the full URL, so results can be
compared against GA4's pagePath without string surgery.""",

    "gsc_list_sitemaps": """\
List the sitemaps submitted for one Search Console property, written to
CSV. Read-only. A domain property includes every subdomain's sitemaps -- often
hundreds -- so read the file rather than the preview.

Answers "did Google fetch our sitemap, and did it find problems": each entry
gives last_submitted, last_downloaded (null if Google never fetched it),
is_pending, errors, warnings, and URLs submitted per content type. Useful
right after gsc_inspect_urls reports "Discovered - currently not indexed".

It does not report how many URLs are indexed: Google retired that count, so
use gsc_inspect_urls for index status. This tool cannot submit or delete a
sitemap.""",

    "check_compatibility": """\
Check, before running a GA4 report, whether its dimensions and metrics can be
combined. Many cannot -- e.g. an item-level metric (itemRevenue) with an
event-level one (purchaseRevenue) -- and GA4 refuses the whole report. When
fields clash, the result names which requested fields clash with which.

Returns each requested field as COMPATIBLE or INCOMPATIBLE, with GA4's own
spelling if yours differed in case. A misspelled field fails with Google's
"Did you mean ...?" -- use its suggestion. Pass suggest="source" (any
substring) to also list the compatible fields whose names contain it -- the
quickest way from an INCOMPATIBLE verdict to a field that works. Filters are
optional and checked too.""",

    "property_setup": """\
How a GA4 property is set up, read-only: time zone and currency, data
retention, data streams (which websites and apps send it data), key events
(what counts as a conversion), audiences, and channel groups (names only).

Use it when a number looks wrong before assuming the data is: a second web
stream, a key event added last month, or 2-month data retention all change
what a report means. Pass sections to fetch only some, e.g. ["key_events"].

Change history is NOT available: Google requires edit access to read it and
this credential is read-only by design. Point the user to Admin > Change
history in the GA4 interface.""",

    "export_cohort_report": """\
Retention by acquisition cohort, written to CSV with a receipt.

cohorts: [{"name": "aug_week1", "start_date": "2026-08-02", "end_date":
"2026-08-08"}] -- each cohort is the users whose FIRST session fell in that
range. granularity DAILY, WEEKLY (default) or MONTHLY; periods is how many
days/weeks/months after to follow them (default 4). Metrics default to
cohortActiveUsers and cohortTotalUsers; retention is active / total. Period
0000 is the cohort's own period. accumulate=true gives running totals.
Dates go in the cohorts, not in a date range.""",

    "export_realtime_report": """\
The last 0-29 minutes of activity, written to CSV with the moment it was
captured. GA4 keeps realtime data for 30 minutes only; for anything older use
export_report. Realtime has its own, smaller set of dimensions (e.g.
unifiedScreenName, country, deviceCategory, eventName, minutesAgo).""",

    "export_funnel_report": """\
A funnel's step-by-step table, written to CSV: users at each step, completion
rate, abandonments, abandonment rate.

steps: [{"name": "view", "event": "page_view"}, {"name": "apply", "event":
"apply_click"}] in order; or {"name", "filter_expression"} with a GA4
FunnelFilterExpression as JSON. Closed funnels (default) count only users who
enter at step 1; is_open_funnel=true lets users enter at any step.
breakdown_dimension (e.g. deviceCategory) splits each step; the all-values
row is written as (total) -- never add it to the other rows. Uses Google's
alpha funnel API, so expect it to change.""",

    "start_session": """\
Create a folder for this working session and return its path.

Call this before exporting anything, and tell the user where it is.

save_to chooses among the APPROVED places only:
  "project"  -- <project>/_outputs/, where the project is the folder the app
                says it is working in (Claude Code and Codex sessions). This
                is the default when there is one.
  "sessions" -- the sessions folder from config.json (default
                ~/Documents/analyst-sessions). Used when there is no project,
                e.g. in Claude Desktop chat.
  <name>     -- any extra folder the user listed under export_roots in
                config.json.
There is no way to pass an arbitrary path, by design: tool arguments can be
steered by text inside the data, so files only go where the user approved.
The reply names the other approved places. If the project is a git repository
that does not ignore _outputs/, the reply warns; tell the user.

This is the only tool that creates directories (the session folder, and
<project>/_outputs itself). Everything else writes into a folder that
already exists.""",

    "export_report": """\
Run a GA4 report and write the results straight to a CSV file, returning a
receipt rather than the rows.

Use this instead of run_report whenever the result is more than a handful of
rows. A thousand rows destined for a file should never pass through the
conversation — the receipt tells you the row count, the columns, whether the
response was sampled, whether it hit a row limit, and how the export was
scoped across the property's hostnames.

Pass session_dir from start_session, or an out_file NAME. A bare or relative
out_file lands inside session_dir when you pass one, and otherwise inside the
approved place chosen by save_to ("project" by default when there is one,
else "sessions"). Paths outside the approved places -- absolute paths
elsewhere, ~/..., network shares -- are refused; see start_session. The
receipt's saved_to says which place was used and why. A .meta.json sidecar
is written beside the CSV so the provenance survives the conversation.

dimension_filter takes a GA4 FilterExpression as a JSON object, e.g.
{"filter": {"fieldName": "hostName", "stringFilter": {"value":
"admissions.example.edu"}}}. It is recorded verbatim in the sidecar, so a filtered
export can be re-run exactly from its provenance record, and a filter naming
hostName is what makes host_scope read "filtered".

metric_filter filters on metric values, in the same FilterExpression shape:
{"filter": {"fieldName": "screenPageViews", "numericFilter": {"operation":
"GREATER_THAN", "value": {"int64Value": "100"}}}}. order_bys sorts, e.g.
[{"metric": {"metricName": "sessions"}, "desc": true}]. currency_code
(e.g. "USD") sets the currency for revenue metrics.

compare_date_ranges adds up to three ranges to compare against start_date..
end_date, e.g. [{"start_date": "2025-01-01", "end_date": "2025-01-31",
"name": "last_year"}]. The file then has a dateRange column: "current" for the
primary range, and each comparison's name. Use this for year-over-year rather
than joining two exports yourself.

pivot_on="<a dimension>" also writes a wide copy beside the file, one column
per metric per value of that dimension (e.g. pivot_on="yearMonth" for pages
by month -- not "month", which is month-of-year and merges years). The long file is still written and stays the complete record; a blank
cell in the wide one means the combination did not occur, not zero. Over 200
distinct values is refused -- pivot on something coarser.

The receipt's property_quota says how many GA4 tokens remain today and this
hour. If they are low, say so before running more large exports.

hostnames is provenance, NOT a filter. It must be every hostname enrichment
reported for this property — not the one you want. Passing a subset writes a
false record: the field is stored as hostnames_observed, and a single-element
list makes host_scope read "single_host", so passing one host of a 40-host
property permanently labels the file as covering one host when it covers all
forty. To actually restrict the data to one host, use dimension_filter.

Never slice, cap, or select a "top N" before writing the file — export the
complete result every time, even when the user only asked for a top ten.
preview_rows (capped at 20) is the mechanism for "show me a few": it controls
how many rows come back in the receipt's preview, not how many are written
to the CSV. The file always gets every row regardless of preview_rows, and
that complete file is what makes the export trustworthy later.

With no limit, the export pages through to every row the query matched;
there is no hidden 10,000-row cap. Read the receipt before reporting from the
file: if row_limit_hit is true the file is INCOMPLETE, and incomplete_reason
says why -- caller_limit (a limit you passed) or server_stopped (GA4 returned
fewer rows than it said matched). Never present an incomplete file as the
whole result. If data_loss_from_other_row is true, GA4 folded part of the long
tail into an "(other)" row, so per-row totals undercount the tail.""",
}
