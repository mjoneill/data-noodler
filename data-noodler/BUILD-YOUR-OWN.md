# Build your own: Google Analytics and Search Console for local AI apps

This is a design brief for building a similar system yourself, not install
instructions for an existing one. Give it to a coding agent (Claude Code,
Codex or similar) together with your goal. Every decision below has its
reason next to it, so you can depart from the ones that don't fit your
situation and keep the ones that do.

What gets built: the ability to ask a desktop AI app questions about your
Google Analytics 4 and Search Console data, answered from live data, and to
export full results to files. It runs on each person's own machine, under
their own Google account, read-only, with no administrator rights and no
server to host.

The design was proven on macOS and on Windows 11 without administrator rights, in Claude Code,
Claude Desktop, Codex and the ChatGPT desktop app. It went through two
redesigns, several reviews and installs on other people's machines. Most of
this document is what those installs taught.

---

## 1. The shape of it

```
 Each AI app (Claude Code, Claude Desktop, Codex, ...)
   │  starts as child processes, over stdio:
   ├── analytics-mcp     Google's own GA4 MCP server, unmodified, pinned
   └── data-noodler server  yours: lookup, credential check, exports, Search Console
          │
          ▼  both read:
   ~/.config/<yourtool>/
       config.json        this machine's paths (credential, venv python, snapshot)
       properties.csv     local snapshot of every GA property the user can see
       server/         data-noodler's code (a copy, made by the installer)
       bin/               launcher scripts that set the environment, then exec
       marketplace/       the Codex plugin (optional)
   ~/.config/gcloud/
       <client>.json      your OAuth app's identity, one per deployment
       <credential>.json  this person's refresh token, read-only scopes, mode 600

 Plus two skills (instructions for an agent):
   setup skill           how an agent installs, verifies and repairs it
   query skill           how to query well, for apps that support skills
```

**Nothing is a service.** An MCP stdio server is a child process of the AI
app: it starts when the app starts and exits when the app exits. "Installing"
means a program on disk plus one config entry per app. There is no launchd
job, no Windows service, no port and no listener, and nothing needs
administrator rights. Everything lives under the user's home directory. This
is the property that makes it deployable to people on locked-down machines.

---

## 2. Decisions, and why

### Use Google's server and add your own beside it

Google publishes `analytics-mcp` on PyPI (about 9 tools: reports, realtime,
funnels, property details, custom dimensions). Use it unmodified and **pin an
exact version**. Never enable its optional write tool.

Then build a second server, the "server", for everything Google's server
doesn't do. Don't fork Google's server. A fork has to be maintained, while a
sibling server only has to keep working.

### Why the data-noodler server exists: some apps have tools but no shell

Claude Desktop's normal chat can call MCP tools, but it has **no shell and no
skill mechanism**. Anything you would normally do with a helper script, such
as looking up a property ID, checking whether the credential has expired or
renewing a stale snapshot, can't happen there unless it is an MCP tool. That
single fact drove the design. If every app your users run has a shell, you
need less of the data-noodler server. Most people's apps don't.

### Each person signs in with their own Google account

- **No service account and no shared credential.** Each person sees exactly
  what their own Google account can already see in GA and Search Console.
  Access is granted in GA and Search Console as usual (GA Viewer role is
  enough), never in your code.
- **Exactly two scopes, both read-only:**
  `https://www.googleapis.com/auth/analytics.readonly` and
  `https://www.googleapis.com/auth/webmasters.readonly`. One credential, one
  consent, one renewal. If you ever add a write scope, revisit this decision
  first.
- **Your own Google Cloud project** with the Analytics Data API, Analytics
  Admin API and Search Console API enabled, and an OAuth client of type
  **Desktop app** (it gives the `http://localhost` redirect flow; a "Web
  application" client fails with `redirect_uri_mismatch`). Leave the consent
  screen's "Data access" scope list **empty**. Declaring scopes there is what
  triggers Google's verification requirements. The scopes are requested at
  sign-in instead.
- **Internal vs External audience.** If everyone is in one Google Workspace
  organization, an *Internal* app avoids most of the friction below. An
  *External* app in **Testing** status has three consequences you must design
  for:
  1. Refresh tokens **expire every 7 days**. Weekly renewal is normal
     operation, not a fault. Make the renewal one command and make the
     expiry legible (see `credential_status` below).
  2. Google refuses sign-in, with `Error 403: access_denied`, to any account
     not on the project's **test user list**, including the project owner. The
     list caps at 100. Being on it is the real access gate, so tell people
     before they install.
  3. "Google hasn't verified this app" is an expected screen to click through.
     `access_denied` is a wall. Document the difference.
- **You can't mint this token with `gcloud`.** `gcloud auth
  application-default login` insists on adding the `cloud-platform` scope.
  Write a small mint script using `google_auth_oauthlib.flow.InstalledAppFlow`
  with exactly your two scopes. Have it write the credential with owner-only
  permissions (on Windows, `icacls <file> /inheritance:r /grant:r
  %USERNAME%:F`, because POSIX mode bits mean little there) and **print the
  scopes actually granted**.
- **Don't bake a quota project into the credential.** If the mint script sets
  `quota_project_id` to the project owner's project, every other user needs an
  IAM permission (`serviceusage.services.use`) on a project they don't own,
  and every GA call fails for them. The owner never notices, because they own
  the project.
- **The credential never passes through the model.** The agent runs a command
  that opens a browser, and Google's flow does the rest.
- **The setup flow checks for a valid credential and doesn't re-mint it.**
  An installer that re-runs consent can break a setup that was working.

### Launchers, and why stdout is sacred

Each server is started by a small launcher script that exports the
environment and then `exec`s the server:

- `GOOGLE_APPLICATION_CREDENTIALS` points to the credential.
- `GRPC_DNS_RESOLVER=native`. **Set this unconditionally.** gRPC's bundled
  c-ares resolver reads `/etc/resolv.conf` directly, which macOS itself
  ignores. On split-DNS networks (VPNs, corporate or institutional networks seen
  from off-site) they disagree. `nslookup`, `ping` and `curl` all succeed
  while every Google API call fails with `503 ... Could not contact DNS
  servers`. It looks exactly like an auth failure, and people re-authenticate
  for nothing.

**stdout is the MCP protocol channel.** One stray `print`, a library banner or
a launcher error message on stdout corrupts the JSON-RPC stream, and the app
reports "server failed to start" with no detail. Launchers and servers write
diagnostics to **stderr only**, and a missing prerequisite exits non-zero with
a stderr message naming the setup skill. Test it directly: run the launcher
and assert stdout is empty on failure.

Launchers should read `config.json` with something guaranteed to exist. On
macOS, `/usr/bin/python3` is a stub that pops an "install developer tools"
dialog on machines without Xcode tools. `/usr/bin/plutil` (macOS 12+) parses
JSON and is always present. On Windows, skip launchers entirely: the app's
config entry names the venv's `python.exe` directly and passes the
environment in the entry's `env` block.

The Codex plugin format passes environment variables through by **name, not
value**. That's why a launcher script is needed there rather than a config
value.

### One home directory, machine paths in one config file

All code and state live in one directory independent of any app. Each app's
config points into it, and no app owns it. Paths that differ per machine
(credential file, venv Python, snapshot path, sessions folder) live in
`config.json`, written by a bootstrap script that **discovers** them. Code and
docs read them from there and never hardcode them.

Things that bit us when hardcoding crept in:

- A renewal command naming a skill path that exists only on the author's
  machine, shown by the one tool whose whole job is telling a stranded user
  what to run.
- A credential check that looked for a fixed filename, falsely reported
  "missing" and sent people back through consent.
- pipx console scripts on macOS are **polyglot shell wrappers** (`#!/bin/sh`
  then `'''exec' '/path/with space/python' ...`), because a shebang can't
  contain a space and "Application Support" has one. Reading the first line
  as the interpreter yields `/bin/sh`. Parse the re-exec line.

### Guidance has to reach the model through two channels

The model's behaviour, not just the code, decides whether answers are right.
There are two delivery channels, and each fails in a different client:

- **Server `instructions`** are dropped or truncated by some clients. Keep
  them short.
- **Tool descriptions** always reach the model eventually. But Claude Code
  *defers* tools: at session start the model sees only tool names, and a
  description loads after the tool is chosen. So "use `export_report` rather
  than `run_report`" in a description arrives too late to affect the choice.

So **rules about which tool to pick go in the server instructions**, and
rules about using a tool well go in its description. Put the critical ones
in both. The rules we found necessary:

- State the **property ID, exact metric name and exact date range** with every
  number. A bare figure hides choices that move the answer more than the trend
  being asked about.
- There is no "visitors" metric. `activeUsers`, `totalUsers`, `newUsers` and
  `sessions` can differ by more than 2x on the same site and period. Pick one
  and name it.
- "Last month" means either a calendar month or a trailing 30 days. They
  differ by enough to swamp a trend. Choose and say which.
- **Subdomains are usually separate GA properties.** Summing properties
  double-counts people who cross subdomains. Say so if you do it.
- Never let the model choose a row limit silently. If a result is truncated,
  say so, and export instead.
- **Match the error text before suspecting credentials.** Only `invalid_grant`
  or "token expired" means renewal.

### Cheap property lookup

An organization's GA account can hold hundreds of properties.
`get_account_summaries` returns all of them, about 20k tokens, to answer
"what's the ID for site X". Instead, keep a local `properties.csv` snapshot
built from the Admin API, and give the data-noodler server a `lookup_property` tool that
returns only matches, at about 300 tokens. Report exact matches separately
from partial ones, because a substring like `example.org` matches every
subdomain property while exactly one is the parent site. Provide
`refresh_property_snapshot` as a tool, because a stale snapshot is otherwise
a dead end in a shell-less app.

An optional `enrich` flag adds sessions in the last 28 days and the hostnames
actually receiving traffic for each candidate. That turns "did you mean
properties/123456789?" (unanswerable by a non-specialist) into a list of
named sites with traffic figures, which anyone can answer.

When no property is named after a site, have the agent read the page's
GA4 measurement IDs (`G-XXXXXXXXXX`, including those inside a Tag Manager
container) and match them against each property's data streams. Most sites
send to both their own property and an organization-wide rollup.

### Export to files, with a receipt

Large results shouldn't pass through the model's context on the way to a
spreadsheet. Export tools run the query themselves, write **every row** to
CSV and return a small receipt. The same receipt is written beside the CSV as
`<name>.meta.json`, because a person opening the folder months later has no
transcript.

Receipt fields that matter:

- `row_count`, `columns`, a few `preview` rows
- the exact query as sent: property, metrics, dimensions, **structured
  filter**, date range (also store the resolved calendar dates when the
  request used relative ones like `28daysAgo`)
- **`sampled`** and **`row_limit_hit`**. Silent sampling and silent
  truncation are the two likeliest causes of a confidently wrong report. The
  GA response carries sampling metadata, so use it.
- **`host_scope`**: a GA property can serve many hostnames, and exporting
  `pagePath` without a host dimension sums `/about` across every site into
  one plausible-looking row. Don't force a `hostName` dimension (it can make
  the report invalid or exceed the dimension cap). Have the agent ask the
  user, then record what was decided: `dimension`, `single_host`, `filtered`
  or `mixed_unscoped`.
- **A zero-row result still writes the file**, header included. An empty
  answer is a finding, while a missing file looks like a failure.

Reuse the upstream package's client factory (`analytics_mcp`'s data and admin
client constructors) rather than building your own, so credential handling
and stdio-safety guards are identical.

A `start_session` tool creates one dated folder per piece of work under a
visible root (for example `~/Documents/analyst-sessions/`, never a dotfile
directory, where people can't find it in Finder) and returns its absolute
path. The agent proposes the location and lets the user redirect it. The
server stays **stateless**: no hidden "current session", because each app
runs its own server process.

### Exports go only to approved places

Tool arguments come from a model, and text inside the data can steer the
model. So an export destination is never an arbitrary path:

- Allowed: the project folder the *app* declares (via MCP roots, not a path
  the model supplies), the configured sessions folder, and folders the user
  listed in config. Nothing else.
- Absolute paths only. A server's working directory is whatever app spawned
  it.
- The parent must already exist. Export never creates directories (only
  `start_session` does).
- No symlinked path components. In practice an agent once redirected output
  through a symlink and truncated the system's Python binary, which broke
  every MCP server on the machine.
- Refuse network paths (UNC, `smb://`) before touching the filesystem.
- Deny credential and app-config directories outright (`~/.ssh`,
  `~/.config/gcloud`, `~/.claude`, `~/.codex`, the app-support folders, your
  own payload).
- Don't overwrite unless asked. On a name collision, append `-2`.
- **Neutralize spreadsheet formula injection**: a cell starting with `=`, `+`,
  `-`, `@`, tab or carriage return is prefixed so Excel shows it rather than
  runs it. Page titles and search queries are user-controlled text.

Watch the edge case of a home directory that itself traverses a symlink
(relocated macOS homes, NFS `/home` on Linux). A naive symlink check refuses
every export there with a message that reads like a security alert.

### Search Console over REST: no new dependency

Search Console has no generated Python client. Rather than adding
`google-api-python-client`, use
`google.auth.transport.requests.AuthorizedSession`, which is already installed
with `google-auth`. Every endpoint needed is one POST or GET. Our rule was **no
runtime dependencies beyond what `analytics-mcp` already brings**, so users
have nothing extra to install.

Search Console traps the guidance must carry:

- **Property type sets coverage, the reverse of GA.** `sc-domain:example.org`
  covers every subdomain and both protocols. `https://example.org/` covers only
  that exact prefix. Show type and coverage in the site list.
- **`coverageState` is the actionable field**, not the binary verdict.
  "Crawled — currently not indexed" and "Discovered — currently not indexed"
  need different responses.
- Data **lags 2–3 days**. `dataState: all` includes fresh, incomplete data,
  so record which one was used.
- When Google's chosen canonical differs from the declared one, that's usually
  the real explanation.
- GA reports paths and Search Console reports full URLs. They share no
  identifier. Make columns joinable (split the path out of the URL) but don't
  build a join tool until you've done the join by hand enough times to know
  the rules (trailing slashes, query strings).
- URL Inspection has **no batch endpoint** and a per-property quota (about
  2,000/day, 600/minute). Throttle the loop, and when a quota error stops a
  run, record `urls_requested` against `rows_written` instead of returning a
  short list that looks complete.
- Search Analytics caps at 25,000 rows per request. Paginate with `startRow`,
  but **set a default cap** or warn: page × query over 16 months on a large
  domain is millions of rows held in memory.
- Request Indexing has no API. It's a button in the UI, so it stays manual.

### Mark each tool with MCP annotations

Give every tool honest annotations, which apps use to decide what needs
approval: lookups are `readOnlyHint: true`. An export writes a local file and
can overwrite one, so it is **not** read-only, even though everything it asks
Google is.

### Errors are the interface

In a shell-less app, the tool's error text is the user's **only** diagnostic.
A raw `KeyError: 'property_name'` or `ExceptionGroup: unhandled errors in a
TaskGroup (1 sub-exception)` is a dead end. Use one user-readable exception
type per module, convert it to a sentence at each tool's boundary, and test
malformed input (short CSV rows, non-dict JSON, unreadable files) on every
"always explain" path. In review, this was the most common defect class by
far, found in nine of fifteen build tasks.

Never use a bare `assert` for a safety check. `python -O` strips it.

---

## 3. The tool surface we ended with

Google's `analytics-mcp`: `get_account_summaries`, `get_property_details`,
`get_custom_dimensions_and_metrics`, `list_google_ads_links`,
`list_property_annotations`, `run_report`, `run_realtime_report`,
`run_funnel_report`, `run_conversions_report` (the set varies by version, so
pin it).

data-noodler (15):

| Tool | What it does |
|---|---|
| `lookup_property` | name/domain → property ID from the local snapshot; optional `enrich` |
| `credential_status` | days left on the credential, scopes granted, the exact renewal command; touches no network, so it separates credential problems from transport ones |
| `refresh_property_snapshot` | rebuild the snapshot from the Admin API |
| `reporting_guide` | the reporting discipline as text (`ga`, `gsc`, `both`) |
| `start_session` | create a dated work folder, return its path |
| `export_report` | GA4 report → CSV + receipt |
| `export_cohort_report`, `export_realtime_report`, `export_funnel_report` | the other GA4 report types → CSV + receipt |
| `check_compatibility` | which dimension/metric combinations GA4 will accept, before running a query |
| `property_setup` | read-only view of a property's configuration (data streams, key events, retention) |
| `gsc_list_sites` | Search Console sites with type, coverage and permission |
| `gsc_inspect_urls` | URL Inspection over a list → CSV + receipt |
| `gsc_search_analytics` | clicks/impressions/position → CSV + receipt, paginated |
| `gsc_list_sitemaps` | submitted sitemaps and their status |

About 24 tools across two servers is fine. Above that, tool-selection
reliability starts to suffer, so add carefully.

---

## 4. The installer: the agent finds things, tested code writes them

Two installs on other people's machines taught the central lesson: **every
failure was discovery** (where Python is, which config folder an app actually
reads, what security policy blocks). **No failure was a write**: merging a
JSON entry or copying a folder works the same everywhere. So:

- **The agent does discovery**, helped by one read-only `probe` script that
  reports facts (Python versions, app config locations, what's already
  registered, dependency versions). An agent re-reads the machine each time.
  Code only records what was true when it was written.
- **Every write goes through tested scripts**: `bootstrap_config` (write
  `config.json` from discovered paths, never overwrite an existing one),
  `install` (copy the payload, register each app), `register` (one adapter per
  app). The agent runs them and doesn't reproduce their steps by hand.
- **Every config write**: back up first (*outside* any directory an app scans,
  see traps), refuse a planted symlink, keep or tighten permissions, write
  to a temp file and rename it, re-parse to prove it's still valid, and make a
  second run a no-op.
- **"Done" means an exit code.** A `verify` script starts each registered
  server **exactly as the app's config says**, completes an MCP handshake and
  checks the tool count (`--require name=count`). Don't accept an agent's
  success claim without it. It can't see an app's UI, so the final check is
  still a person restarting the app and asking one question.
- **Walls have named flags** (`--venv-python`, `--base-python`, an override
  for the app's data directory), so an agent that hits one has a documented
  way past it, and the instruction is to stop and report rather than improvise.
- **Upgrade is the one exception**, written as a single transactional script
  the *user* runs with every app quit, because swapping the Python venv
  underneath a running app fails (Windows) or silently runs stale code
  (macOS), and the agent always runs inside one of those apps. It runs a
  read-only `--plan` first, proves the new servers before changing anything
  else, and rolls back on failure, Ctrl-C or a hard kill (`--recover` reads a
  record it left on disk). It never deletes anything that existed before it
  started.

Per-app registration notes:

- **Claude Code**: `mcpServers` in `~/.claude.json`, user scope.
- **Claude Desktop**: `mcpServers` in `claude_desktop_config.json`. On macOS
  there can be **two** data directories (`Claude` and `Claude-3p`), and writing
  to the inactive one fails silently, so pick the one modified most recently
  and report which. On Windows, the Microsoft Store version keeps its config
  inside the app container
  (`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`), which
  ordinary PowerShell can't see at `%APPDATA%\Claude`. Detect it, and refuse
  loudly rather than "skip, not installed". Honour `CLAUDE_USER_DATA_DIR`.
- **Codex**: package both servers and the query skill as a **plugin** in a
  local "marketplace" folder (an index file plus the plugin directory). Let
  the `codex plugin marketplace add` / `codex plugin add name@marketplace`
  CLI write `~/.codex/config.toml`, and never edit that file yourself. The
  plugin's `plugin.json` **must** declare `"mcpServers": "./.mcp.json"`. Without
  it the plugin installs cleanly and registers zero servers. **Bump the plugin
  version on every content change**: Codex caches by version, so changes
  shipped at an unchanged version never reach existing installs. A test that
  fingerprints plugin contents against the version will catch this.
- **ChatGPT desktop app**: its Codex/Work modes share Codex's plugin config.
  Its plain Chat mode runs on OpenAI's servers and can't reach a local
  process.

**Quit apps before registering.** Claude Desktop and the ChatGPT app write
their own settings back to the same config files, and a running app's later
flush can drop the entry you just added. Afterwards, apps must be **fully
quit** (Cmd-Q, or the tray icon on Windows), not just have their windows
closed, to pick up new config, new code or a renewed credential.

**Keep the master copies of your skills in one place and build copies from
them**, never edit the copies. Mark installed skill folders with a marker
file, and never overwrite a folder that lacks it.

---

## 5. Windows differences (measured on managed machines, no admin)

- **Python first, installed by the user** from an ordinary PowerShell window
  or File Explorer. The `python.exe` in `WindowsApps` is a Store stub. An
  installer started from inside the Store version of Claude Desktop fails,
  because the app container redirects `AppData` writes where Windows Installer
  can't see them. Afterwards, name the new interpreter by full path.
- **No uv, no launchers, no `.ps1` scripts.** Stock `python -m venv`. Execution
  policy blocks unsigned PowerShell scripts.
- **Run the server as `python.exe -m analytics_mcp.server`**, not the
  pip-generated `analytics-mcp.exe`. Defender's Attack Surface Reduction rule
  for low-prevalence executables blocks per-machine generated `.exe` files
  with `[WinError 5] Access is denied`, which looks like a file permission
  problem and isn't.
- **Codex plugins that start servers through `/bin/sh` don't work on native
  Windows.** Plan for that or exclude Codex there.
- Test paths containing spaces (`OneDrive - Org Name`). We hadn't when this
  was written.
- **Test the path a person takes by hand, not just the one an agent takes.** An
  agent running inside the Store app inherits its container and never sees
  the config-location bug that a person in PowerShell hits immediately.

---

## 6. Supply chain

- Pin the whole dependency set with a constraints file and check it against
  vulnerability databases before each release. Enforce minimum safe versions
  with a test.
- A fresh venv starts with whatever pip the Python installer bundled, which
  may trust stale or compromised certificate roots (this happened in October
  2026 with a certificate authority's compromised intermediate keys). **Install
  pip itself by exact wheel URL and SHA-256** before anything else, and never
  `pip install --upgrade pip` with the bundled one.
- Turn off what you don't use. The MCP Python library includes OpenTelemetry
  trace-context middleware, and if you export no traces, remove it so nothing
  parses that header.

---

## 7. Traps, collected

| Symptom | Real cause | Fix |
|---|---|---|
| `503 ... Could not contact DNS servers`, while curl works | gRPC c-ares reads `/etc/resolv.conf` on split DNS | `GRPC_DNS_RESOLVER=native` in every launcher |
| `invalid_grant` weekly | Testing-status 7-day refresh tokens | One-command renewal, then **fully quit** the apps |
| Renewal "didn't work" | The running app holds the old token in memory | Quit and reopen, not close the window |
| `Error 403: access_denied` at consent | Account isn't a test user | Owner adds it, once per person |
| Server "failed to start", no detail | Something wrote to stdout | stderr only. Test it directly |
| Plugin installed, no tools | `plugin.json` lacks `mcpServers` pointer | Declare it, and test cross-file agreement |
| Codex still runs old skill | Version unchanged, so the cache was kept | Bump version on every content change |
| Tools missing in Claude Desktop, config looks right | Wrote to the inactive data directory, or app flushed over it | Pick by recency, quit before writing |
| A second copy of a skill appears | Backup was made inside a skill scan directory | Back up outside any directory an app scans |
| Every GA call fails for others, works for author | Author's quota project baked into credential | Omit quota project |
| `venv_python` came out as `/bin/sh` | pipx polyglot wrapper | Parse the re-exec line |
| `uv` not found after its installer | Installer doesn't add it to the current shell's PATH | Use the absolute path it printed |
| First export fails for a new user | Sessions root didn't exist (author made it by hand) | Create it during install, and have the error say exactly what to create |
| Excel mangles accented characters | UTF-8 CSV without BOM | Write a BOM, or offer `.xlsx` |
| Same install command, different behaviour | Unpinned Python version | Pin it (`uv tool install --python X.Y`) |

---

## 8. Non-goals (decide yours deliberately)

- **Hosted/web chat** (claude.ai, ChatGPT web chat). Their tool calls run on
  the vendor's servers. Serving them needs a hosted remote MCP server that
  holds other people's refresh tokens, which is a different project with a
  credential-custody burden.
- **Any write to Google.** Read-only by construction.
- **Signed binaries, `.mcpb` bundles, tray apps.** Packaging cost with no
  gain while the credential lives outside any bundle.
- **A cross-source GA/Search Console join tool**, until the join rules are
  settled by doing it by hand.
- **A curated portfolio file** of sites. Resolve live and confirm with the user
  instead.

---

## 9. Suggested build order

Each step ends verified before the next begins.

1. Cloud project, Desktop OAuth client, mint script, with exactly two
   scopes printed back. Ask one question through Google's `analytics-mcp` in
   Claude Code.
2. data-noodler with `lookup_property`, `credential_status`,
   `refresh_property_snapshot`, `reporting_guide`. Unit tests, plus a real
   MCP handshake test asserting the tool names.
3. Launchers and `config.json`. Test that a missing credential gives a stderr
   message and empty stdout.
4. `register` + `verify`, tested against **copies** of real app config files
   (unrelated keys survive, second run is a no-op, backup exists, output
   parses) before any live file is touched.
5. Register in each app, then restart it and ask a real question.
6. Exports with receipts and the destination rules. Pure functions, testable
   without network.
7. Search Console tools, tested against captured, sanitized real responses.
8. The setup skill. Then **install on someone else's machine** and budget for
   it to find real bugs. Ours found five on the first foreign install, every
   one invisible on the machine that built it. Ask specifically: what does the
   author's machine have that a fresh one doesn't?

Testing discipline that paid off: every test must be able to fail (break the
component and confirm the test catches it). For docs, test that every path a
documented command references actually exists. Run tests with the venv's
interpreter, because the system Python can't import `mcp` and produces errors
that look like broken code.

---

## 10. Before you hand it to anyone

- Read-only scopes only, printed at consent.
- Credential owner-readable only, never copied, never in a repo or zip.
- The OAuth client file is handed over directly (password manager, private
  drive), never over chat or mailing lists, and never committed. It can't read
  data by itself, but it carries your app's name on a consent screen.
- Exports confined as described in section 2, with formulas neutralized.
- Dependencies pinned and scanned. pip installed by hash.
- Keep anything specific to your organization (project ID, test-user list,
  maintainer contact) in one deployment profile file, outside the product
  code, so the product can be shared without a scrub.
