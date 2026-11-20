# First-time setup: analytics-mcp with a narrow-scope credential

Read this when `~/.config/ga-mcp/config.json` is absent, when setting up a new
machine, or when an auth failure isn't simple token expiry.

The goal is a credential holding **only** `analytics.readonly`. Google's own
README has you authorize `cloud-platform` alongside it, which grants Cloud
actions as the user across *every project their account can reach*. An analytics
reader has no use for that, and it turns a leaked token from "someone read my
traffic stats" into "someone has my Google Cloud account."

## 1. Install the server

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh

# The installer puts uv at ~/.local/bin and edits shell rc files only, which
# does nothing for the shell you are already in. Set PATH here or the next
# line fails with "command not found: uv". This also covers the analytics-mcp
# console script, which lands in the same directory.
export PATH="$HOME/.local/bin:$PATH"
uv tool install analytics-mcp==1.1.0 --with google-auth-oauthlib
uv tool update-shell    # puts the tool dir on PATH permanently
```

Pin the version. Google's README suggests `pipx run analytics-mcp`, which
re-resolves from PyPI at every launch — an auto-updating dependency that reads
your credential file. `google-auth-oauthlib` is needed by `mint_adc.py` and
isn't a dependency of the server itself, so it rides along via `--with`.
There is no `uv tool inject` — that is pipx's verb, and `uv` rejects it
outright.

`uv`'s installer needs nothing beyond `curl` and provisions its own Python —
Homebrew is not a dependency of this package, whether or not you happen to
have it.

**Either `uv` or `pipx` works** — the rest of this document and
`bootstrap_config.py` detect which one you used and work identically either
way. This machine happens to run `pipx`; if you'd rather use it (or already
have `analytics-mcp` installed that way), that path is:

```bash
brew install pipx   # or any other way of getting pipx onto your machine
pipx install 'analytics-mcp==1.1.0'
pipx inject analytics-mcp google-auth-oauthlib
```

`pipx inject` — not `uv tool inject` — is the correct verb here; the two
tools' equivalent of "add an extra dependency into the tool's own
environment" genuinely uses different words, which is exactly the kind of
detail that gets copied across by mistake. If you go this route, note that
Homebrew is only how you're getting pipx, not a requirement of
`analytics-mcp` itself — `pipx` has other install methods too.

The pipx venv Python ends up somewhere like
`~/Library/Application Support/pipx/venvs/analytics-mcp/bin/python` on macOS.
Note the real path; the scripts need it and it contains a space. (The `uv`
path's interpreter lives under `~/.local/share/uv/tools/analytics-mcp/` with
no space, but always read the real path out of `venv_python` in
`config.json` rather than assuming either location.)

## 2. Google Cloud project and APIs

In the **Google Cloud Console** (`console.cloud.google.com` — a different site
from `analytics.google.com`, which is never used during setup):

1. Create a project. Record the **project ID** — Google appends digits if the
   name is taken, so it looks like `ga-mcp-483921` rather than the display name
   you typed.
2. Enable both APIs, with the project pinned in the URL so there's no chance of
   configuring the wrong one:
   - `console.cloud.google.com/apis/library/analyticsadmin.googleapis.com?project=PROJECT_ID`
   - `console.cloud.google.com/apis/library/analyticsdata.googleapis.com?project=PROJECT_ID`

There is no Save button — **Enable** applies immediately. Once enabled the page
shows "API enabled" with Manage/Disable instead.

Skipping this produces a runtime error reading "Admin API has not been used in
project X before or it is disabled." That error means authentication *succeeded*
— it's a project configuration problem, not a credential problem.

## 3. OAuth consent screen

Under **Google Auth Platform** (formerly "OAuth consent screen"):

- **Branding**: set an app name that will be recognizable months later in the
  user's [account permissions list](https://myaccount.google.com/permissions).
  Something like `GA MCP — Claude Code (read-only)`. This name also appears on
  the unverified-app warning, which is how the user confirms they're consenting
  to their own client rather than something phishing them. Google rejects names
  containing "Google".
- **Audience**: **External** is the only option for a consumer Gmail account —
  "Internal" requires the project to belong to a Google Workspace organization
  and appears greyed out otherwise.
- Add the user's own address under **Test users**. In Testing status Google
  blocks everyone not on that list, including the project owner, with
  `Error 403: access_denied`.

**Leave the Data Access page empty.** Declaring scopes there is what triggers
Google's verification requirements; the scopes that actually get granted are the
ones requested at runtime by the OAuth flow. An empty list costs nothing.

### Testing vs. Production

Testing status means Google issues **7-day refresh tokens** for any app
requesting more than basic profile scopes, so the credential needs weekly
renewal. Publishing to Production removes that expiry, but Google's own
confirmation dialog warns that apps requesting sensitive scopes need
verification — and `analytics.readonly` is sensitive. Publishing also widens who
may consent to any Google account.

Widening the audience does **not** expose the user's data: anyone else consenting
would be granting access to *their* GA properties, not the user's. And "External"
never means listed or discoverable — there is no directory in which the app
appears. But weekly renewal is one command, so Testing is usually the better
trade for a personal tool. Keep the user on the test-user list either way, so a
reversion to Testing doesn't lock them out.

## 4. Create the OAuth client

**Clients → Create client → Application type: Desktop app.** The type matters;
it selects a loopback redirect (`http://localhost`) plus PKCE. Download the JSON
and save it to the path named as `oauth_client_file` in the config.

A correct file has a top-level `installed` key (a web client would say `web`) and
`redirect_uris: ["http://localhost"]`.

This "secret" is not truly secret — installed apps can't hold confidential
credentials (RFC 8252), which Google accounts for. Still worth `chmod 600` and
keeping out of any repo. The credential that genuinely matters is the ADC token
minted next.

## 5. Write the config

`~/.config/ga-mcp/config.json`:

```json
{
  "oauth_client_file": "~/.config/gcloud/ga-mcp-client.json",
  "adc_file": "~/.config/gcloud/adc-ga-personal.json",
  "venv_python": "~/Library/Application Support/pipx/venvs/analytics-mcp/bin/python",
  "properties_csv": "~/.config/ga-mcp/properties.csv"
}
```

`quota_project` is **not** written by default and is not shown above. Both
the GA Data API and the GA Admin API work fine with no `x-goog-user-project`
header at all, and defaulting it to someone else's Cloud project would
require that project's owner to grant every colleague
`serviceusage.services.use` there, which they don't have. Add
`"quota_project": "YOUR_PROJECT_ID"` yourself only if you own a Cloud project
and want usage billed/reported against it.

## 6. Mint the credential

```bash
"<venv_python>" <skill>/scripts/mint_adc.py
```

The user must run this — it opens a browser for consent. It prints the scopes
Google actually granted; that line is the verification that the narrowing worked.

**Do not substitute `gcloud auth application-default login`.** Its ADC path
contains an unconditional check that rejects any scope set lacking
`cloud-platform`, in `lib/surface/auth/application_default/login.py`:

```python
if auth_util.CLOUD_PLATFORM_SCOPE not in scopes:
    raise c_exc.InvalidArgumentException(...)
```

No flag bypasses it, and it fires before the browser opens. That's gcloud's
policy about what ADC files should contain, not a Google API restriction — the
same OAuth flow requesting one scope works fine, which is what `mint_adc.py`
does.

Also note: passing `--client-id-file` to gcloud means it won't write a quota
project into ADC at all, per its own help text. `mint_adc.py` embeds
`quota_project_id` directly, so no environment variable is needed.

## 7. Register the MCP server

```bash
claude mcp add analytics-mcp --scope user \
  -e "GOOGLE_APPLICATION_CREDENTIALS=<adc_file>" \
  -e "GRPC_DNS_RESOLVER=native" \
  -- "<path to ~/.local/bin/analytics-mcp>"
```

`--scope user` makes it available in every folder. For other MCP clients (Gemini
CLI, Claude Desktop, Cursor), the equivalent config is:

```json
{
  "mcpServers": {
    "analytics-mcp": {
      "command": "/absolute/path/to/analytics-mcp",
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/absolute/path/to/adc.json",
        "GRPC_DNS_RESOLVER": "native"
      }
    }
  }
}
```

Set `GRPC_DNS_RESOLVER=native` from the start rather than saving it for
troubleshooting. The Google client libraries use gRPC, whose default c-ares
resolver reads `/etc/resolv.conf` directly — a file the rest of macOS ignores in
favor of the system resolver. On any split-DNS or VPN-dependent network (campus,
corporate) those can disagree, and every API call then fails with
`Could not contact DNS servers` while `nslookup` and `curl` to the same host
succeed. `native` routes gRPC through `getaddrinfo` so it agrees with the OS.
The only thing given up is c-ares' async resolution, which is irrelevant at this
call volume. Verified on this setup: identical call, default resolver fails,
`native` succeeds.

Use absolute paths — most clients don't expand `~` or `$HOME` inside JSON, and
this fails silently when they don't.

There is nothing to start or stop. MCP stdio servers are spawned by the client
per session and terminated when that client exits; `claude mcp list` showing
"Connected" means "this launches and responds," not "a process is running."

Process lifetime in practice is messier than "one per session," and it matters
because **each process reads its credential and env once, at spawn time**. A
week-old process is still using a week-old token and whatever env it started
with — which is why renewing a credential or changing server env needs a new
spawn, not just a re-run.

Two things observed on this setup:

- A session that stays open for days keeps its server process alive for days.
  Several `analytics-mcp` processes of varying age are normal rather than leaked
  — check parent PIDs before concluding otherwise.
- `/mcp` reconnect spawns a **replacement without terminating the previous
  child**, so one live session can own several. The newest is the one in use;
  the older ones idle harmlessly but make process lists confusing.

To find which process is actually current, compare ages and check env directly:

```bash
for p in $(ps -eo pid,args | grep "[a]nalytics-mcp" | awk '{print $1}'); do
  ps eww -p "$p" | grep -q "GRPC_DNS_RESOLVER=native" \
    && echo "pid $p: has fix" || echo "pid $p: MISSING"
done
```

A reconnect is enough to pick up config changes — a full restart isn't required —
but only for the session that reconnects. Other open sessions keep their stale
processes until they reconnect or close.

## 8. Build the property snapshot and verify

```bash
"<venv_python>" <skill>/scripts/refresh_properties.py
"<venv_python>" <skill>/scripts/lookup_property.py <some known domain>
```

## Errors in Google's README, as of analytics-mcp 0.7.0

- It sets `GOOGLE_PROJECT_ID` in the MCP config. **Nothing reads that.** The
  server calls `google.auth.default()` and discards the returned project. The
  variable google-auth actually consults for quota attribution is
  `GOOGLE_CLOUD_QUOTA_PROJECT`; the prose mentions `GOOGLE_CLOUD_PROJECT`, which
  sets the default project and is likewise discarded. Embedding
  `quota_project_id` in the ADC file sidesteps all of this.
- It documents 7 tools. There are 9 — `list_property_annotations` and
  `run_conversions_report` are undocumented.

## If weekly renewal becomes annoying

Two durable options:

1. **Publish the app to Production** — removes the 7-day expiry, at the cost of
   a possible verification requirement (see above).
2. **Use a service account** — no consent screen, no publishing status, no
   expiry. The tradeoff: a service account starts with zero GA access, so its
   email must be granted read access in GA admin. Permissions granted at the GA
   *account* level cascade to that account's properties, so covering many
   properties may only mean a few grants. It also places a long-lived key file on
   disk, which is its own risk profile — a non-expiring credential is more
   convenient and more dangerous than a weekly one.
