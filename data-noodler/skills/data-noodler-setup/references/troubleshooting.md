# Troubleshooting GA MCP installs

Match the error text first. Credentials are the most documented failure here,
which makes them the default suspect for every breakage — and often the wrong
one.

## "Could not contact DNS servers" / 503 resolving a host

**A resolver problem, not a credential problem.** The tell: the message names
DNS and never says `invalid_grant`.

gRPC's default c-ares resolver reads `/etc/resolv.conf`, which macOS itself
ignores. On a split-DNS network they disagree, so `nslookup` and `curl` to the
same host both succeed while every API call fails — meaning ordinary
connectivity checks will tell you the network is fine.

Fix: `GRPC_DNS_RESOLVER=native` in the server's environment. Both launchers set
it. If a server was registered without going through a launcher, that is the
cause.

Re-minting the credential cannot help, and has been mistaken for the fix
before.

## `invalid_grant` / "Token has been expired or revoked"

The refresh token expired. Google issues 7-day refresh tokens to OAuth apps in
Testing publishing status. This is expected weekly, not a fault.

Fix: have the user run the `mint_adc.py --force` command, then **restart the
application**. The server reads the credential file when it spawns, so a
running client keeps the expired token in memory and keeps failing in a way
that looks exactly like the renewal did not work.

## `Error 403: access_denied` at the Google consent screen

**Neither a credential problem nor a config problem, and nothing on this
machine can fix it.** The shared OAuth client is in Google's "Testing"
publishing status, and Google refuses consent to any Google account the Cloud
project has not listed as a **test user**. Having GA access to the properties
is not enough. Being the project owner is not enough either.

Do not confuse it with the warning that *is* expected: "Google hasn't verified
this app" is a screen to click through (Advanced → Continue). `access_denied`
is a wall — the flow ends there and no credential file is written.

Fix: the user asks the project's maintainer for exactly this — *"please add
`<the Google account address I sign in with>` to the Test users list for the
ga-mcp Cloud project, under Google Auth Platform → Audience → Test users."*
The address must be the same account that holds the GA access they want to
read. It is one action per person, ever: not per install, not per machine, not
per weekly renewal. Once it is done, re-run the consent command.

Re-running `mint_adc.py`, regenerating `config.json`, reinstalling the payload
and re-registering the harnesses all cannot help, and each one costs time that
looks like progress. The list caps at **100 test users**, which is also the
ceiling on how many colleagues this setup can serve in Testing status.

## Access is denied on Windows

`verify.py` prints `FAIL analytics-mcp: PermissionError: [WinError 5] Access
is denied`, usually followed by a `why:` line. The file's ACL gives the user
full control, and even reading it fails.

**Neither a credential problem nor a permissions problem you can fix with
icacls.** It is Microsoft Defender's Attack Surface Reduction rule
`01443614-CD74-433A-B99E-2ECDC07BFC25`, which blocks programs that have not
been seen on enough other machines. pip generates
`venv\Scripts\analytics-mcp.exe` on each machine, so it always fails that
check where IT enforces the rule. Measured on a managed machine 2026-10-09;
the 2026-10-05 machine connected through the same `.exe`, so it varies by
machine and can change when IT pushes policy.

Confirm (PowerShell):

```powershell
Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' |
  Where-Object Id -eq 1121 | Select-Object -First 5 | Format-List TimeCreated, Message
```

Event 1121 naming the `.exe` is the proof.

Fix: re-run `install.py` from a current package. It registers
`<venv>\Scripts\python.exe -m analytics_mcp.server` on Windows, which starts
the same server through the interpreter data-noodler already uses. An older
install whose entry names the `.exe` gets the new entry on that re-run. Then
re-run `verify.py`.

If the denied program is `python.exe` itself, there is no workaround on this
side: IT has to allow it. Do not copy the interpreter somewhere else to get
around the rule.

## `upgrade.py` says UPGRADE FAILED (or UPGRADE INTERRUPTED)

Any failure after the venv moved -- an error, a missing file, Ctrl-C -- is
undone automatically: the old venv, the previous payload and the Claude app
configs are put back, and the apps work as they did before. "Restored" at
the end confirms it. Do not try to finish the upgrade by hand. Send the whole
output to the maintainer.

If it ends "MOST of it was put back, but not all of it", each line after that
says exactly what is left -- usually a folder a locked file (Windows) kept in
place. Once nothing is using it, run `upgrade.py --recover`: it finishes the
undo from the record the run left in `~/.config/ga-mcp`. Then `verify.py`
before reopening the apps.

**The window closed, the machine restarted, or the run was killed mid-way**
(nothing printed "Restored"): run `upgrade.py --recover` with the same base
Python. It reads the record the run kept and puts the venv, payload and our
app entries back. A new upgrade refuses to start until that is done.
`--recover` itself refuses, changing nothing, while our servers are running
or while the upgrade that wrote the record is still going.

**`--recover` keeps reporting the same problem** (for example a config file
that stays unreadable): sort that item out by hand -- the message says what
it is -- then run `upgrade.py --forget`. That removes only the record, so
upgrades can start again; it changes nothing else. Run `verify.py` on each
app's config before reopening the apps.

"NOT READY -- nothing was changed", or a failure at the very first step
("Could not move ... aside"): nothing was touched at all. Usually something
still has a server running from the venv. Fully quit Claude Desktop (from its
icon by the clock on Windows, Cmd-Q on a Mac), every Claude Code window,
Codex and the ChatGPT app, then run it again.

## Certificate or TLS questions (eMudhra / emSign, October 2026)

Eight eMudhra/emSign intermediate certificate keys were compromised in
October 2026. Anything that trusts them can have its HTTPS connections
intercepted -- including downloads from pypi.org. What this package relies
on, and the safe versions (`installer/security_floors.py`):

- **certifi 2026.10.19 or later** -- what the GA and Search Console calls
  trust. The pins carry 2026.10.23.
- **pip 26.2.2 or later** -- pip always trusts its own bundled certificate
  list. A new venv starts with the Python installer's older pip, so every
  venv step installs pip by exact URL and SHA-256 first (see windows.md).
  Never shortcut that to `pip install --upgrade pip`.
- **uv 0.13.4 or later** on the Mac path: `brew upgrade uv`, or
  `UV_SYSTEM_CERTS=true uv self update`.
- grpcio's own root list does not contain the compromised roots.

`probe.py` reports `dependencies.below_floor` and `uv.below_floor`; both
should be empty/false. A python.org *framework* install on macOS bundles its
own certifi per Python -- not this package's path (uv provides Python), but
if someone runs scripts with it, upgrade pip and certifi there too.

## macOS offers to install "command line developer tools"

`/usr/bin/python3` on a Mac without Apple's developer tools is a stub: it pops
that dialog and fails. Nothing here needs those tools. Dismiss the dialog and
use the Python that uv installed instead: `"$(uv python find)"` wherever a
step says `python3` or `/usr/bin/python3`. The launchers themselves do not use
Python to start; they read the config with `/usr/bin/plutil`.

## The launcher says the config "is not valid JSON", or "macOS 12 or later"

Both come from `~/.config/ga-mcp/bin/launch-*` before it reads anything.
"Not valid JSON" names the file and the position: fix the file by hand, or
move it aside and re-run `bootstrap_config.py`. Do not re-mint the credential;
it is not the problem. "macOS 12 or later is required" means what it says:
the launchers cannot read the config on an older macOS.

## The server "fails to start" with no useful error

Almost always something written to **stdout**. That is the MCP protocol
channel; any stray print corrupts the JSON-RPC stream and the client reports a
broken server with no detail.

Check: run the launcher directly and confirm stdout is empty on failure.

```bash
~/.config/ga-mcp/bin/launch-data-noodler >/tmp/out 2>/tmp/err; echo "exit=$?"
wc -c /tmp/out   # must be 0 on failure
cat /tmp/err
```

## Tools do not appear in Claude Desktop, but the config looks right

Two data directories can exist: `~/Library/Application Support/Claude/` and
`.../Claude-3p/`. Writing to the inactive one fails **silently**.

Check which one the app is using — the one whose contents were modified
recently — or set `CLAUDE_USER_DATA_DIR` explicitly. `harness_paths.py`
resolves this automatically; if it chose wrong, that override is the escape
hatch.

Also: Claude Desktop must be fully quit and reopened, not just have its window
closed. A running client holds its old config and its old child server
processes, and closing a window does neither.

Also check whether Claude Desktop or ChatGPT.app was left running during
registration. Both applications persist their own settings back into the same
config files this install writes, and a running app's later flush can drop
entries that were just added. Quit first, register, then reopen — and verify
again after it reopens.

## Codex says `codex plugin add data-noodler` failed

Use the marketplace-qualified name instead:

```bash
codex plugin add data-noodler@data-noodler
```

The bare name is rejected; the qualified form is what actually works.

## `lookup_property` finds nothing for a property that exists

The local snapshot is stale. Call `refresh_property_snapshot`, or run
`refresh_properties.py` in a shell.

## Codex plugin installed but no GA tools

Confirm the plugin is enabled:

```bash
codex plugin list
grep -A2 'data-noodler' ~/.codex/config.toml
```

The plugin's `bin/` scripts are shims that exec `~/.config/ga-mcp/bin/`. If the
payload was never installed there, they exit non-zero with a message naming
this skill. Run the payload step.

## Nothing works and the credential is fine

Verify the program is still on disk. A `uv tool upgrade` or a Python change can
leave a stale path in the config:

```bash
ls -l ~/.local/bin/analytics-mcp
"<venv_python>" -c "import analytics_mcp; print('ok')"
```

## The credential expired again — is something broken?

No. Google issues 7-day refresh tokens to OAuth apps in Testing publishing
status, and this app is in Testing status by design (moving out of it requires
a Google verification review that is out of scope for a personal tool). Expect
to run `mint_adc.py --force` about once a week. This is normal operation, not
a regression.

## Codex will not start: "failed to parse model_catalog_json"

```
Error: failed to load configuration
  failed to parse model_catalog_json path `~/.codex/ollama-launch-models.json`
  as JSON: missing field `supports_parallel_tool_calls`
```

**Not this package.** Only affects machines where Ollama's Codex integration
(`ollama launch codex`) has been used to offer Ollama models inside Codex.

That integration writes a *snapshot* of Codex's own model list into
`~/.codex/ollama-launch-models.json` and points Codex's config at it. When Codex
later updates and requires a new field, the snapshotted entries lack it and
Codex refuses its whole configuration. Both Codex surfaces share that config,
so the TUI and the ChatGPT app's Codex pane fail together -- GA or not.

**Fix: let Ollama regenerate it, from a real terminal window.** It is
interactive by design and cannot be run by an agent's shell:

```bash
ollama launch codex --config --model <a local model from `ollama list`>
```

`--model` will likely become Codex's default model. If you want a different
default, set `model = "..."` in `~/.codex/config.toml` afterwards.

Do not hand-edit the missing field into the snapshot: the values are
Codex's, not yours, and Ollama overwrites the file on its next run anyway.
Found 2026-10-06 on Codex 0.147 with Ollama 0.34.2.
