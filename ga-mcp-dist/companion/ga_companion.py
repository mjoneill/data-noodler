#!/usr/bin/env python3
"""ga-companion: the skill's shell-dependent capability, as MCP tools.

Claude Desktop's normal chat has MCP tools but no shell and no skill
mechanism, so lookup_property.py and mint_adc.py are unreachable there. This
server re-exposes that capability so every harness has the same abilities
regardless of what else it can run.

Runs on the analytics-mcp venv's Python, where `mcp` is already a dependency;
it adds nothing to install.

stdout is the MCP protocol channel. Nothing here may print to it.
"""

import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Switch off W3C trace-context parsing before anything imports opentelemetry's
# propagators (the launchers and Windows entries set it too). mcp 2.x parses
# traceparent/tracestate from every inbound message's _meta, and
# opentelemetry-api 1.44.0's tracestate parser had a quadratic-regex
# advisory (CVE-2026-114603), fixed in the pins since #1986. Nothing here
# exports traces, so the parsing buys nothing and stays off (#162).
os.environ.setdefault("OTEL_PROPAGATORS", "none")

import config
import credential
import export
import ga_admin
import ga_export
import ga_reports
import guidance
import gsc
import matching
import sessions

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

# Set before any Google client is constructed. gRPC's c-ares resolver reads
# /etc/resolv.conf, which macOS ignores; on split-DNS networks every API call
# fails with a fake DNS error while nslookup and curl succeed. The launcher
# also sets this -- belt and braces, because the server may be registered
# directly without it.
os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

# Date of the release this server shipped in; reported as serverInfo.version,
# which mcp 2.x leaves empty unless it is given.
SERVER_VERSION = "2026.10.25"

mcp = MCPServer("ga-companion", instructions=guidance.SERVER_INSTRUCTIONS,
                version=SERVER_VERSION)

# The SDK wraps every inbound message in an OpenTelemetry span, and that
# middleware is what reads the trace context. Its own docs: "a no-op until an
# OTel exporter is installed. Drop it from this list to opt out." No exporter
# is ever installed here, so drop it -- this removes the parsing even if
# OTEL_PROPAGATORS were overridden.
mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware
    if type(m).__name__ != "OpenTelemetryMiddleware"]

# MCP tool annotations: hints an app can use to decide what needs the user's
# approval. They describe what each tool may do, honestly -- an export writes
# a local file and, with overwrite=true, can replace one, so it is not
# read-only even though everything it asks Google is.
TOOL_KINDS = {
    "reads_local": ToolAnnotations(
        read_only_hint=True, open_world_hint=False),
    "reads_google": ToolAnnotations(
        read_only_hint=True, open_world_hint=True),
    "creates_folder": ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True,
        open_world_hint=False),
    "refreshes_snapshot": ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True,
        open_world_hint=True),
    "exports": ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=False,
        open_world_hint=True),
}


def _tool(kind, **kw):
    return mcp.tool(annotations=TOOL_KINDS[kind], **kw)


def _sessions_root():
    """Where a relative out_file lands, or None to use the default.

    Falls back rather than failing: the GSC tools do not otherwise need the
    config, and a missing config should not stop an export that names an
    absolute path.
    """
    try:
        return config.sessions_root(_cfg())
    except config.ConfigError:
        return None


def _cfg():
    """Load config, letting ConfigError surface as the tool's error text."""
    return config.load(os.environ.get("GA_MCP_CONFIG") or None)


# The folder the app started this server in. Set by the app, never by the
# model, so it can name a place to write (#156). Measured 2026-10-25: Claude
# Code starts each session's server in that session's project; Claude
# Desktop chat starts it in "/", which never qualifies.
try:
    LAUNCH_DIR = os.getcwd()
except OSError:
    LAUNCH_DIR = ""

# The client's declared MCP roots, as local paths, refreshed by start_session.
# Claude Code declares them; Codex does not (measured 2026-10-25).
_CLIENT_ROOTS = []


def _roots_to_paths(result):
    paths = []
    for root in getattr(result, "roots", None) or ():
        uri = str(getattr(root, "uri", "") or "")
        if uri.startswith("file://"):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(uri)
            if parsed.netloc not in ("", "localhost"):
                continue  # file://host/... is a network location
            path = unquote(parsed.path)
            if os.name == "nt" and path.startswith("/") and path[2:3] == ":":
                path = path[1:]
            paths.append(path)
    return paths


def _places():
    """(approved places, how the project was chosen or why there is none)."""
    try:
        cfg = _cfg()
    except config.ConfigError:
        cfg = {}
    project, how = sessions.find_project(_CLIENT_ROOTS, LAUNCH_DIR)
    root = None
    try:
        root = config.sessions_root(cfg) if cfg else None
    except config.ConfigError:
        pass
    extra = cfg.get("export_roots") if isinstance(cfg, dict) else None
    places = sessions.build_places(
        sessions_root=root, project=project,
        extra=extra if isinstance(extra, dict) else None)
    return places, how


def _git_warning(project_outputs):
    """A warning when exports would be committable, else None.

    Never edits .gitignore -- that file is the user's -- only says so.
    """
    import subprocess
    project = os.path.dirname(project_outputs)
    try:
        inside = subprocess.run(
            ["git", "-C", project, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        ignored = subprocess.run(
            ["git", "-C", project, "check-ignore", "-q",
             sessions.OUTPUTS_DIR + "/probe.csv"],
            capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if ignored.returncode == 0:
        return None
    return (f"{project} is a git repository and {sessions.OUTPUTS_DIR}/ is "
            "not in its .gitignore, so these exports could be committed. Add "
            f"'{sessions.OUTPUTS_DIR}/' to .gitignore if they should stay "
            "local.")


def _destination(out_file, session_dir, name, save_to):
    """(path, where) inside an approved place; raises SessionError."""
    places, how = _places()
    path, where = sessions.resolve(out_file or None, session_dir or None,
                                   name, places, save_to or "")
    where = dict(where)
    if save_to:
        where["chosen_by"] = "save_to"
    elif session_dir:
        where["chosen_by"] = "session_dir"
    elif where["place"] == "project":
        where["chosen_by"] = how
    else:
        where["chosen_by"] = ("default: no project folder (" + how + ")"
                              if "project" not in places else "default")
    if where["place"] == "project":
        warning = _git_warning(where["root"])
        if warning:
            where["warning"] = warning
    return path, where


@_tool("reads_google", description=guidance.LOOKUP_TOOL_DOC)
def lookup_property(query: str, include_all: bool = False,
                    enrich: bool = False) -> str:
    try:
        cfg = _cfg()
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"

    csv_path = cfg["properties_csv"]
    if not os.path.exists(csv_path):
        return (f"No property snapshot at {csv_path}.\n"
                "Call refresh_property_snapshot to build one.")

    try:
        rows = matching.load_rows(csv_path)
        m = matching.match_properties(rows, query)
        text = matching.format_matches(query, m, include_all=include_all)
    except (KeyError, OSError, csv.Error, UnicodeDecodeError, TypeError) as exc:
        return (f"Property snapshot at {csv_path} exists but could not be "
                f"read as a property snapshot ({exc}).\n"
                "Call refresh_property_snapshot to rebuild it.")

    if not enrich:
        return text

    import enrich as enrich_mod
    candidates = (m["exact"] + m["near"] + m["partial"])[:5]
    lines = ["Candidates, with recent activity so you can tell them apart:", ""]
    for c in candidates:
        pid = matching.property_id(c)
        if pid is None:
            continue
        facts = enrich_mod.candidate_facts(pid)
        lines.append("  " + enrich_mod.describe(c, facts))
    lines.append("")
    lines.append("Ask the user which they meant. Lead with the name and the "
                 "numbers, not the property ID.")
    return "\n".join(lines)


@_tool("reads_local",
    description="""Report whether the GA credential is still valid, and what to
do if it is not.

Call this first whenever a GA tool fails with invalid_grant or "token expired",
and whenever a GA call fails in a way you cannot explain. Google issues 7-day
refresh tokens to OAuth apps in Testing publishing status, so this credential
expires weekly by design -- that is not a misconfiguration.

Returns the days remaining and, when renewal is needed, the exact command for
the user to run in a terminal. Renewal opens a browser for Google consent, so
it cannot be done from here; give the user the command. The application must
be restarted afterward, because the server reads the credential file only when
it spawns.""")
def credential_status() -> str:
    try:
        cfg = _cfg()
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"

    report = credential.credential_report(
        cfg["adc_file"], config.renewal_command(cfg))
    return report["summary"] + "\n\n" + credential.scope_line(
        config.granted_scopes(cfg))


@_tool("refreshes_snapshot",
    description="""Rebuild the local property snapshot from the GA Admin API.

Call this when lookup_property finds nothing for a property that should exist
-- the snapshot is a local file and goes stale when properties are added or
renamed. Makes one Admin API call and rewrites the snapshot atomically.

Requires a valid credential; if it fails, call credential_status.""")
def refresh_property_snapshot() -> str:
    try:
        cfg = _cfg()
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cfg["adc_file"]

    import snapshot
    try:
        rows, accounts = snapshot.rebuild(cfg["properties_csv"])
    except Exception as exc:  # surfaced as tool text, not a traceback
        return (f"Snapshot refresh failed: {exc}\n\n"
                "If this mentions invalid_grant or an expired token, call "
                "credential_status. If it mentions DNS, the server is missing "
                "GRPC_DNS_RESOLVER=native in its environment.")

    return (f"Wrote {rows} properties across {accounts} accounts to "
            f"{cfg['properties_csv']}.")


@_tool("reads_local",
    description="""Return the reporting discipline for GA4, Search Console, or
both.

Read this before answering questions about either source. Covers GA4's metric
ambiguity and subdomain-as-separate-property rule, Search Console's inverted
domain-vs-prefix coverage rule, coverageState semantics, the 2-3 day data lag,
and how to work with these tools.

topic: "ga", "gsc", or "both" (default).""")
def reporting_guide(topic: str = "both") -> str:
    return guidance.guide_for(topic)


@_tool("creates_folder", description=guidance.GSC_TOOL_DOCS["start_session"])
async def start_session(name: str, save_to: str = "",
                        ctx: Context | None = None) -> str:
    # Ask the app which folders it is working in. Only the app can answer
    # this, so it is safe to write there; a folder the model names is not.
    if ctx is not None:
        try:
            result = await ctx.session.list_roots()
            _CLIENT_ROOTS[:] = _roots_to_paths(result)
        except Exception:  # client without the roots capability (Codex)
            pass
    places, how = _places()
    place = save_to or next(iter(places))
    if place not in places:
        return (f"save_to={save_to!r} is not one of the approved places "
                f"({', '.join(places)}).")
    root = places[place]
    if place == "project":
        # The one directory this creates beyond the session folder itself:
        # <project>/_outputs, inside a project the app named.
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as exc:
            return f"Could not create {root} ({exc})."
    try:
        path = sessions.start_session(name, root=root)
    except sessions.SessionError as exc:
        return str(exc)
    lines = [f"Session folder ready:\n  {path}", "",
             f"Place: {place} ({'chosen by ' + how if place == 'project' else 'sessions folder'})."]
    if "project" not in places:
        lines.append(f"No project folder: {how}.")
    if place == "project":
        warning = _git_warning(root)
        if warning:
            lines.append("Warning: " + warning)
    others = [n for n in places if n != place]
    if others:
        lines.append("Other approved places: " + ", ".join(others) + ".")
    lines += ["", "Pass this as session_dir when exporting."]
    return "\n".join(lines)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["export_report"])
def export_report(property_id: str, start_date: str, end_date: str,
                  metrics: list[str], dimensions: list[str] | None = None,
                  save_to: str = "", session_dir: str = "", out_file: str = "",
                  dimension_filter: dict | None = None,
                  hostnames: list[str] | None = None,
                  limit: int = 0, overwrite: bool = False,
                  preview_rows: int = 5,
                  metric_filter: dict | None = None,
                  order_bys: list[dict] | None = None,
                  compare_date_ranges: list[dict] | None = None,
                  currency_code: str = "", pivot_on: str = "") -> str:
    try:
        _cfg()
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"

    dimensions = dimensions or []
    try:
        columns, rows, meta = ga_export.run(
            property_id, start_date, end_date, metrics, dimensions,
            dimension_filter=dimension_filter or None, limit=limit or None,
            metric_filter=metric_filter or None, order_bys=order_bys or None,
            compare_date_ranges=compare_date_ranges or None,
            currency_code=currency_code or None)
    except Exception as exc:
        return (f"GA4 report failed: {exc}\n\n"
                "If this mentions invalid_grant or an expired token, call "
                "credential_status.")

    meta["host_scope"] = ga_export.host_scope(
        dimensions, dimension_filter or None, hostnames or [])
    meta["hostnames_observed"] = list(hostnames or [])

    name = ga_export.suggested_filename(property_id, dimensions,
                                        start_date, end_date)
    if compare_date_ranges:
        # One look at the name should say the file holds more than one range.
        name = name[:-len(".csv")] + "-compared.csv"
    try:
        path, where = _destination(out_file, session_dir, name, save_to)
        meta["saved_to"] = where
        receipt = export.write_export(path, columns, rows, meta,
                                      overwrite=overwrite,
                                      preview_rows=preview_rows)
    except (sessions.SessionError, export.ExportError) as exc:
        return str(exc)
    if pivot_on:
        receipt["pivot"] = _write_pivot(path, columns, rows, meta, pivot_on,
                                        metrics, overwrite)
    return json.dumps(receipt, indent=2)


def _write_pivot(path, columns, rows, meta, pivot_on, metrics, overwrite):
    """A wide copy beside the long file. The long file is always written
    first and stays the complete record; a pivot that cannot be made is
    reported, never a reason to lose the export."""
    try:
        wide_cols, wide_rows = ga_reports.pivot_wide(columns, rows, pivot_on,
                                                     metrics)
        wide_path = f"{path[:-len('.csv')]}-by-{pivot_on}.csv"
        r = export.write_export(
            wide_path, wide_cols, wide_rows,
            # rows_matched describes the long file; carried over, it would
            # make a complete 2,265-row pivot of 33,109 long rows look cut.
            dict(meta, rows_matched=None, long_rows=len(rows),
                 pivot_of=path, pivot_on=pivot_on,
                 pivot_note="Blank means that combination did not occur."),
            overwrite=overwrite, preview_rows=0)
    except (ValueError, export.ExportError) as exc:
        return {"error": str(exc)}
    return {"path": r["path"], "columns": len(wide_cols),
            "row_count": len(wide_rows)}


def _write(meta, columns, rows, name, out_file, session_dir, overwrite,
           preview_rows, save_to=""):
    try:
        path, where = _destination(out_file, session_dir, name, save_to)
        meta["saved_to"] = where
        receipt = export.write_export(path, columns, rows, meta,
                                      overwrite=overwrite,
                                      preview_rows=preview_rows)
    except (sessions.SessionError, export.ExportError) as exc:
        return str(exc)
    return json.dumps(receipt, indent=2)


def _ga_failure(what, exc):
    if isinstance(exc, ValueError):
        return str(exc)
    return (f"{what} failed: {exc}\n\nIf this mentions invalid_grant or an "
            "expired token, call credential_status.")


@_tool("exports", description=guidance.GSC_TOOL_DOCS["export_cohort_report"])
def export_cohort_report(property_id: str, cohorts: list[dict],
                         granularity: str = "WEEKLY", periods: int = 4,
                         metrics: list[str] | None = None,
                         dimensions: list[str] | None = None,
                         accumulate: bool = False, save_to: str = "", session_dir: str = "",
                         out_file: str = "", overwrite: bool = False,
                         preview_rows: int = 5) -> str:
    try:
        _cfg()
        columns, rows, meta = ga_reports.run_cohort(
            property_id, cohorts, granularity=granularity, periods=periods,
            metrics=metrics, dimensions=dimensions, accumulate=accumulate)
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"
    except Exception as exc:
        return _ga_failure("GA4 cohort report", exc)
    d = meta["date_range"]
    name = (f"ga4-{property_id}-cohort-{meta['granularity'].lower()}"
            f"-{d['start'].replace('-', '')}-{d['end'].replace('-', '')}.csv")
    return _write(meta, columns, rows, name, out_file, session_dir,
                  overwrite, preview_rows, save_to)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["export_realtime_report"])
def export_realtime_report(property_id: str, metrics: list[str],
                           dimensions: list[str] | None = None,
                           dimension_filter: dict | None = None,
                           metric_filter: dict | None = None,
                           minutes_ago: int = 29, save_to: str = "", session_dir: str = "",
                           out_file: str = "", overwrite: bool = False,
                           preview_rows: int = 5) -> str:
    try:
        _cfg()
        columns, rows, meta = ga_reports.run_realtime(
            property_id, dimensions or [], metrics,
            dimension_filter=dimension_filter or None,
            metric_filter=metric_filter or None, minutes_ago=minutes_ago)
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"
    except Exception as exc:
        return _ga_failure("GA4 realtime report", exc)
    stamp = meta["captured_at"][:16].replace("-", "").replace(":", "")
    name = f"ga4-{property_id}-realtime-{stamp}.csv"
    return _write(meta, columns, rows, name, out_file, session_dir,
                  overwrite, preview_rows, save_to)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["export_funnel_report"])
def export_funnel_report(property_id: str, steps: list[dict],
                         start_date: str, end_date: str,
                         breakdown_dimension: str = "",
                         is_open_funnel: bool = False, save_to: str = "", session_dir: str = "",
                         out_file: str = "", overwrite: bool = False,
                         preview_rows: int = 5) -> str:
    try:
        _cfg()
        columns, rows, meta = ga_reports.run_funnel(
            property_id, steps, start_date, end_date,
            breakdown_dimension=breakdown_dimension,
            is_open_funnel=is_open_funnel)
    except config.ConfigError as exc:
        return f"Configuration problem: {exc}"
    except Exception as exc:
        return _ga_failure("GA4 funnel report", exc)
    name = (f"ga4-{property_id}-funnel-{start_date.replace('-', '')}"
            f"-{end_date.replace('-', '')}.csv")
    return _write(meta, columns, rows, name, out_file, session_dir,
                  overwrite, preview_rows, save_to)


@_tool("reads_google", description=guidance.GSC_TOOL_DOCS["gsc_list_sites"])
def gsc_list_sites(enrich: bool = False, contains: str = "") -> str:
    try:
        sites = gsc.list_sites(enrich=enrich, contains=contains)
    except gsc.GscError as exc:
        return str(exc)
    if not sites:
        if contains:
            return (f"No Search Console property's site_url contains "
                    f"{contains!r}. Call gsc_list_sites with no arguments "
                    "to see everything this credential can reach.")
        return ("This credential can reach no Search Console properties. "
                "Either the account has none, or the credential lacks the "
                "webmasters.readonly scope -- call credential_status.")
    lines = []
    if enrich:
        window = sites[0].get("impressions_range") or {}
        if window:
            lines.append(f"Impressions cover {window['start']} to "
                         f"{window['end']} (28 complete days).")
            lines.append("")
    for s in sites:
        line = f"{s['site_url']}  [{s['type']}, {s['permission_level']}]"
        if enrich:
            if s.get("impressions") is None:
                # Unknown, not zero. Zero is the answer this enrichment
                # exists to detect, so a failure must never be rendered as
                # one -- that would turn a permission problem into a
                # confident claim that the property is dead.
                line += ("\n    impressions: unknown — "
                         f"{s.get('impressions_error')}")
            else:
                line += f"\n    impressions: {s['impressions']:,}"
        line += f"\n    covers {s['covers']}"
        lines.append(line)
    return "\n".join(lines)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["gsc_inspect_urls"])
def gsc_inspect_urls(site_url: str, urls: list[str], save_to: str = "", session_dir: str = "",
                     out_file: str = "", overwrite: bool = False,
                     preview_rows: int = 5) -> str:
    try:
        columns, rows, meta = gsc.inspect_urls(site_url, urls)
    except gsc.GscError as exc:
        return str(exc)

    # The filename comes from the same day the module recorded in the
    # sidecar, rather than a second call to today() that can land on the
    # other side of midnight.
    day = meta["date_range"]["start"]
    name = gsc.suggested_filename("inspect", site_url, day, day)
    try:
        path, where = _destination(out_file, session_dir, name, save_to)
        meta["saved_to"] = where
        receipt = export.write_export(path, columns, rows, meta,
                                      overwrite=overwrite,
                                      preview_rows=preview_rows)
    except (sessions.SessionError, export.ExportError) as exc:
        return str(exc)

    stopped = meta.get("stopped_reason")
    if stopped:
        warning = (
            f"Partial run: only {meta['rows_written']} of "
            f"{meta['urls_requested']} requested URLs were inspected before "
            f"it stopped ({stopped}). Do not report coverage or index status "
            "for the URLs that were never reached -- they are simply absent "
            "from this file, not confirmed anything.\n\n")
        return warning + json.dumps(receipt, indent=2)
    return json.dumps(receipt, indent=2)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["gsc_search_analytics"])
def gsc_search_analytics(site_url: str, start_date: str, end_date: str,
                         dimensions: list[str], page_contains: str = "",
                         data_state: str = "final", row_limit: int = 0,
                         save_to: str = "", session_dir: str = "", out_file: str = "",
                         overwrite: bool = False,
                         preview_rows: int = 5, search_type: str = "web",
                         filters: list[dict] | None = None,
                         aggregation_type: str = "auto") -> str:
    try:
        columns, rows, meta = gsc.search_analytics(
            site_url, start_date, end_date, dimensions,
            page_contains=page_contains or None, data_state=data_state,
            search_type=search_type, filters=filters,
            aggregation_type=aggregation_type,
            # <= 0 all mean "no limit", same as the documented default of 0.
            # `row_limit or None` alone let a negative value (e.g. -5, still
            # truthy) straight through to search_analytics, which turned it
            # into a negative rowLimit in the request body and earned a 400
            # from Google instead of the unlimited query the caller likely
            # intended by passing something out of range.
            row_limit=row_limit if row_limit > 0 else None)
    except gsc.GscError as exc:
        return str(exc)

    # A Discover export named like a web one gets compared with web numbers.
    kind = ("performance" if search_type == "web"
            else f"performance-{search_type.lower()}")
    name = gsc.suggested_filename(kind, site_url, start_date, end_date)
    try:
        path, where = _destination(out_file, session_dir, name, save_to)
        meta["saved_to"] = where
        receipt = export.write_export(path, columns, rows, meta,
                                      overwrite=overwrite,
                                      preview_rows=preview_rows)
    except (sessions.SessionError, export.ExportError) as exc:
        return str(exc)
    return json.dumps(receipt, indent=2)


@_tool("exports", description=guidance.GSC_TOOL_DOCS["gsc_list_sitemaps"])
def gsc_list_sitemaps(site_url: str, save_to: str = "", session_dir: str = "", out_file: str = "",
                      overwrite: bool = False, preview_rows: int = 5) -> str:
    try:
        sitemaps = gsc.list_sitemaps(site_url)
    except gsc.GscError as exc:
        return str(exc)
    if not sitemaps:
        return (f"No sitemaps have been submitted for {site_url} through "
                "Search Console. Google may still find one through "
                "robots.txt; that does not show up here.")
    # A file, not a reply: a domain property collects every subdomain's
    # sitemaps -- 826 of them on one measured on 2026-10-07.
    columns, rows = gsc.sitemap_rows(sitemaps)
    day = datetime.date.today().isoformat()
    meta = {"source": "gsc_sitemaps", "site_url": site_url,
            "site_type": gsc.property_type(site_url),
            "date_range": {"start": day, "end": day},
            "rows_written": len(rows), "stopped_reason": None,
            "sampled": False, "row_limit_hit": False}
    name = gsc.suggested_filename("sitemaps", site_url, day, day)
    try:
        path, where = _destination(out_file, session_dir, name, save_to)
        meta["saved_to"] = where
        receipt = export.write_export(path, columns, rows, meta,
                                      overwrite=overwrite,
                                      preview_rows=preview_rows)
    except (sessions.SessionError, export.ExportError) as exc:
        return str(exc)
    return json.dumps(receipt, indent=2)


@_tool("reads_google", description=guidance.GSC_TOOL_DOCS["check_compatibility"])
def check_compatibility(property_id: str, dimensions: list[str],
                        metrics: list[str],
                        dimension_filter: dict | None = None,
                        metric_filter: dict | None = None,
                        suggest: str = "") -> str:
    try:
        out = ga_admin.check_compatibility(
            property_id, dimensions, metrics,
            dimension_filter=dimension_filter or None,
            metric_filter=metric_filter or None, suggest=suggest)
    except Exception as exc:
        return (f"Compatibility check failed: {exc}\n\n"
                "If this mentions invalid_grant or an expired token, call "
                "credential_status.")
    return json.dumps(out, indent=2)


@_tool("reads_google", description=guidance.GSC_TOOL_DOCS["property_setup"])
def property_setup(property_id: str,
                   sections: list[str] | None = None) -> str:
    try:
        out = ga_admin.property_setup(property_id, sections=sections or None)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return (f"Reading the property setup failed: {exc}\n\n"
                "If this mentions invalid_grant or an expired token, call "
                "credential_status.")
    return json.dumps(out, indent=2)


if __name__ == "__main__":
    mcp.run()
