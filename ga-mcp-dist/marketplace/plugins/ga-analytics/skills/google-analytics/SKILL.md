---
name: google-analytics
description: Query Google Analytics 4 data through the analytics-mcp MCP server — traffic reports, users, sessions, pageviews, conversions, realtime, funnels — plus resolving property names to IDs cheaply and fixing expired credentials. Also covers Google Search Console — indexed, indexing, coverage, crawl, canonical, sitemap, impressions, clicks, average position, "showing up in Google", "why isn't this page ranking" — and exporting either source's results to a file. Use this skill whenever the user asks about Google Analytics, GA4, website traffic, visitors, sessions, pageviews, bounce rate, or analytics for any specific site or property, even if they don't mention GA by name. Also use it when GA tools fail with invalid_grant or "token expired", when the user needs to set up or re-authenticate the GA MCP server, or when a question mentions a domain or subdomain whose analytics they want.
---

# Google Analytics via MCP

The `analytics-mcp` server exposes 10 read-only tools over the Google Analytics
Admin and Data APIs: `get_account_summaries`, `get_property_details`,
`list_property_annotations`, `list_google_ads_links`, `list_key_events`,
`get_custom_dimensions_and_metrics`, `run_report`, `run_realtime_report`,
`run_funnel_report`, `run_conversions_report`.

Everything is read-only by construction — the credential holds only
`analytics.readonly`, so no query can alter GA configuration. Explore freely;
the risk is a confusing answer, never a destructive one.

Machine-specific paths live in `~/.config/ga-mcp/config.json`. If that file is
missing, this machine hasn't been set up — read `references/setup.md`.

## Resolving property names to IDs

Reports need a numeric property ID, but users name properties by domain or
title. Resolve them with the bundled script rather than the MCP server:

```bash
python <skill>/scripts/lookup_property.py example.edu
```

`get_account_summaries` returns every account and property, which on a large
account is ~20k tokens for a fact you needed one line of. The script reads a
local snapshot and prints only matches — usually under 300 tokens. Reserve
`get_account_summaries` for when the snapshot genuinely can't answer, such as a
property created since the last refresh.

If the script reports no matches on something that should exist, the snapshot is
stale. Rebuild it:

```bash
"$(python -c "import json,os;print(os.path.expanduser(json.load(open(os.path.expanduser('~/.config/ga-mcp/config.json')))['venv_python']))")" \
  <skill>/scripts/refresh_properties.py
```

Reading the whole snapshot file is a poor substitute for searching it — the file
is thousands of tokens and the model then has to scan 
hundreds of rows to find one. Search it.

## The companion server, and harnesses with no shell

Alongside `analytics-mcp` there is a second MCP server, `ga-companion`, which
exposes fifteen tools. Four of them cover GA4 property lookup and
credentials: `lookup_property`, `credential_status`,
`refresh_property_snapshot`, and `reporting_guide`. Two are read-only GA4
checks: `check_compatibility` (can these dimensions and metrics be combined --
run it before a report GA4 might refuse) and `property_setup` (data streams,
key events, retention, audiences, channel groups -- read it when a number
looks wrong). The other nine cover file export and Search Console, and are
documented under "Search Console, and exporting to a file" below:
`start_session`, `export_report`, `export_cohort_report`,
`export_realtime_report`, `export_funnel_report`, `gsc_list_sites`,
`gsc_inspect_urls`, `gsc_search_analytics`, and `gsc_list_sitemaps`.

It exists because Claude Desktop's normal chat has MCP tools but **no shell**
and no skill mechanism, so the scripts this skill documents cannot run there
at all. The companion carries the same capability as tools, which is the only
form that reaches every harness.

**Prefer the tools when they are available**, and fall back to the scripts
otherwise:

| Need | With companion | Shell only |
|---|---|---|
| Resolve a property | `lookup_property` | `lookup_property.py` |
| Check credential expiry | `credential_status` | inspect the ADC file's mtime |
| Rebuild a stale snapshot | `refresh_property_snapshot` | `refresh_properties.py` |
| Reporting discipline | `reporting_guide(topic)` — "ga", "gsc", or "both" | this file |

**The refresh row of that table shares one implementation** —
`refresh_properties.py` calls the same `snapshot.rebuild` the tool does — so
those two cannot give different answers.

**The lookup row does not.** `lookup_property` (the tool, in the companion's
`matching.py`) and `lookup_property.py` (this skill's script) are two copies of
the same matching logic, pending consolidation. They agree on a well-formed
snapshot. They differ on a malformed one: given a row with fewer fields than
the header, the tool reports the row as incomplete and names
`refresh_property_snapshot`, while the script raises `TypeError: unsupported
format string passed to NoneType.__format__`. Prefer the tool where it exists,
and read that traceback from the script as the known duplication rather than a
new bug.

Renewal is the one thing no tool can do: it opens a browser for Google
consent. `credential_status` returns the exact command for the user to run.

## Search Console, and exporting to a file

The same `ga-companion` server also covers Google Search Console — "is this
page indexed", "why did impressions drop", "what's our average position for
this query" — and gives GA4 itself a way to write large results to a file
instead of the conversation. Nine tools:

| Tool | Answers |
|---|---|
| `start_session` | Create the folder an export writes into. Call this first. |
| `export_report` | Run a GA4 report straight to CSV, returning a receipt instead of the rows. Takes metric filters, sorting, up to three comparison date ranges (year-over-year), and an optional wide pivot. |
| `export_cohort_report` | Retention by acquisition cohort, to CSV. |
| `export_realtime_report` | The last 30 minutes, to CSV, stamped with when it was captured. |
| `export_funnel_report` | A funnel's step-by-step completion and abandonment, to CSV. |
| `gsc_list_sites` | List the Search Console properties this credential can reach, and what each one covers. |
| `gsc_inspect_urls` | Is a URL indexed, and if not, what's stopping it -- plus any rich results found and their issues. |
| `gsc_search_analytics` | Clicks, impressions, CTR, and position by date, hour, page, query, country, device, or search appearance -- for web, Discover, News, image, or video search, with filters. |
| `gsc_list_sitemaps` | Which sitemaps were submitted, and whether Google fetched them without errors. |

**`sc-domain:` versus a URL prefix is the opposite of GA4's subdomain rule, and
getting it backwards produces real numbers for the wrong scope, silently.** In
GA4, a parent domain's property usually excludes its subdomains — they're
tracked separately. Search Console inverts this:

- `sc-domain:example.edu` is a **domain property** — it covers every
  subdomain, on both http and https. `journalism.example.edu` is included.
- `https://example.edu/` is a **URL-prefix property** — it covers only that
  exact prefix. Subdomains are excluded, and so is the other protocol: an
  `https://` property knows nothing about the site's `http://` URLs, which
  come back absent rather than unindexed.

The two look almost identical in a list. Call `gsc_list_sites` and read the
`type` and `covers` fields before reporting anything scoped to a domain — GA
intuition applied here gets the scope exactly backwards.

**`gsc_search_analytics` reports web search unless told otherwise.** Discover,
News, image and video are separate `search_type`s, and their traffic is not in
the web numbers. Google's AI Overviews and AI Mode reports exist only in the
Search Console web interface -- no API reaches them, so say that rather than
presenting web numbers as an answer about AI search.

**Export the full data, then analyse only from the file.** Export the full
data to a file unless the user explicitly asks otherwise: `export_report`,
the other `export_*` tools, `gsc_inspect_urls` and `gsc_search_analytics` all
write CSV and return a receipt (row count, columns, whether it was sampled or
truncated) rather than the rows. Call `start_session` first so there's a
folder to write into. Analyse only from the exported file, never from rows
read into the conversation, however few: an in-conversation `run_report` is
for a single figure, such as one total, never the input to an analysis.

**Never analyse truncated data unless the user specifically asks for it.** If
a receipt says `row_limit_hit` or `sampled`, the file is not the whole answer:
say so, narrow the query (shorter dates, a filter) and export again.

Exports go only to approved places, chosen with `save_to`: the project
folder the app is working in (`<project>/_outputs/`, the default in Claude
Code and Codex), the sessions folder (the default when there is no project,
as in Claude Desktop chat), or folders the user listed under `export_roots`
in `~/.config/ga-mcp/config.json`. An arbitrary path is refused by design --
text inside GA or Search Console data can steer a model, so the model never
gets to name where a file goes. Tell the user where the file landed; if the
receipt warns that `_outputs/` isn't gitignored, pass that on.

This only scratches the surface — call `reporting_guide("gsc")` for the full
treatment: the coverageState states and what each demands, canonical
mismatches, the 2-3 day data lag, and why GA's `pagePath` and Search
Console's full URLs don't reconcile automatically. Don't duplicate that
guidance here; it lives in one place so the two can't drift apart.

## Reporting discipline

**State the property ID, the exact metric name, and the exact date range
alongside every number you report.** This isn't bureaucratic bookkeeping. A bare
figure hides choices the user can't see, and those choices routinely move the
answer more than whatever trend they're asking about.

"How many visitors last month?" contains three ambiguities:

**The metric.** GA4 has no "visitors" metric. Illustrative figures for a single
property over a single month — invented, but with the proportions a real
mid-sized site shows:

| metric | value (illustrative) |
|---|---|
| activeUsers | 84,200 |
| totalUsers | 91,600 |
| newUsers | 67,300 |
| sessions | 195,400 |

All four are defensible readings of "visitors" and they span roughly 2.3×. Pick
one, name it, and say what it means if the distinction could matter.

**The date range.** "Last month" might be the previous calendar month or a
trailing 30 days. On a real property those differed by 5% — enough to swamp the
trend someone is asking about. The Data API accepts both absolute dates
(`2026-07-01`) and relative ones (`30daysAgo`, `yesterday`) — choose deliberately
and state which.

**The property.** See below.

## Subdomains are usually separate properties

Organizations commonly track each subdomain as its own GA property. A search for
`example.edu` may match hundreds of rows while exactly one property is named
that — and that one measures only the parent site, not its subdomains.

So "traffic to example.edu" has two very different readings: the homepage
property, or the whole domain family. Ask which is meant when it's unclear.
Summing properties is not a safe shortcut for the second reading — it
double-counts anyone who crossed subdomains and silently misses untracked sites.
If a total across properties really is wanted, say plainly that it's a sum with
those caveats rather than presenting it as a deduplicated figure.

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

## When tools fail: read the error before reaching for auth

Credentials are the most *documented* failure here, which makes them the default
suspect for any breakage. Resist that: match the error text first.

**`Could not contact DNS servers` (or a 503 "errors resolving ...") is a resolver
problem, not a credential problem.** The tell is that the message names DNS and
never says `invalid_grant`. gRPC's default c-ares resolver reads
`/etc/resolv.conf`, which macOS itself ignores, so `nslookup` and `curl` to the
same host can both succeed while every API call fails — meaning ordinary
connectivity checks will tell you the network is fine. Fix it with
`GRPC_DNS_RESOLVER=native` in the server's env (see `references/setup.md` §7),
then restart the session. Re-minting the credential cannot help and has been
mistaken for the fix before.

A fast way to tell the two apart: if `lookup_property.py` still works while every
report fails, the credential and the local snapshot are fine and the problem is
network-side — that script never touches the network.

## When tools fail with invalid_grant

An `invalid_grant` or "Token has been expired or revoked" error means the refresh
token expired, not that anything is misconfigured. Google issues 7-day refresh
tokens to OAuth apps whose publishing status is "Testing" when they request
anything beyond basic profile scopes.

Renewal opens a browser for consent, so the user has to run it — offer the
command rather than trying to run it unattended:

```bash
"<venv_python from config>" <skill>/scripts/mint_adc.py --force
```

Afterward the client session must restart. The MCP server process reads the
credential file when it spawns, so a session that was already running keeps the
expired token in memory and will keep failing in a way that looks like the
renewal didn't work.

If the user would rather stop renewing weekly, `references/setup.md` covers the
two durable alternatives and their tradeoffs.

## First-time setup

`references/setup.md` has the full procedure: creating the OAuth desktop client,
enabling the two required APIs, minting a narrow-scope credential, and
registering the MCP server. Read it when `~/.config/ga-mcp/config.json` is
absent, when setting up a new machine, or when the user hits an auth error that
isn't simple expiry. It also documents several traps that cost real time —
including two errors in Google's own README.
