# Installing GA access by hand

## Already installed? Upgrade instead -- don't follow the steps below

If these tools are already on your machine, the numbered steps below are not
how you upgrade: copying a new payload leaves the old libraries in place,
which is how September installs were still running a critical security
advisory in October. An upgrade is one command that replaces everything and
puts it all back if anything fails. The release notes that came with the
new package say what changes.

1. Find the Python your install was built from, and check you're ready
   (read-only; any Python 3 will run it):

   ```bash
   python3 <repo>/data-noodler/installer/upgrade.py --plan
   ```

   (On a Mac where `xcode-select -p` errors, `python3` is only Apple's stub:
   use `"$(uv python find)"` instead. No developer tools are needed. On
   Windows the command is `python`, not `python3`.)

   It ends with READY, "READY once every app is quit", or NOT READY with what
   to fix. Note the `base python` line.
2. **Fully quit** Claude Desktop, every Claude Code window, Codex and the
   ChatGPT app. Then run, with that base Python:

   ```bash
   "<base python>" <repo>/data-noodler/installer/upgrade.py
   ```

   On Windows, in an ordinary PowerShell window, put `& ` in front and use
   backslashes. "Upgrade complete" means every check passed; "UPGRADE
   FAILED" means it already put everything back -- send the output to
   your maintainer (named in `deployment.json`).
3. Reopen your apps. If you use Codex: `codex plugin add ga-analytics@ga-tools`.
   If you use Claude Code: `"<venv_python>" <repo>/data-noodler/installer/copy_skills.py`.
4. The previous setup is left in place as the undo, at the path the upgrade
   printed. Delete it once you've used the upgraded tools.

For someone who would rather run these commands themselves than have an
agent do it. Every command below is meant to be copy-pasted into a terminal
and run in order. Nothing here needs administrator privilege — every file
written lives under your home directory.

**Platform: the commands below are macOS.** They assume `sh`,
`~/Library/Application Support`, and the paths pipx/uv use there.

**On Windows, read `skills/ga-mcp-setup/references/windows.md` first.** The
steps and their order are the same; the differences were each measured on a
real Windows machine: you may need to install Python first (from an ordinary
PowerShell window); stock `python -m venv` instead of `uv`; no launchers (the
registered entry names the interpreter directly, and analytics-mcp runs as
`python.exe -m analytics_mcp.server` because Defender can block its `.exe`);
no `.ps1` (execution policy blocks unsigned scripts); and fully quitting the
application before registering is a hard requirement rather than prudence.

Windows has been installed end to end on two IT-managed machines (2026-10-05
and 2026-10-09), with Claude Code and Claude Desktop both answering real GA
questions. Paths containing spaces, and Codex on Windows, are still unproven;
that page says which is which.

**If you'd rather have an agent do this instead:** Claude Code or Codex can
run the `ga-mcp-setup` skill for you once the plugin/skill is installed. This
document is for the case where you don't want that, or want to understand
what the agent-driven path actually does.

## What you get, and what you don't

Needs macOS 12 (Monterey) or later, or Windows 11. The Mac launchers read
the config with a `plutil` feature that older macOS does not have, and say
so if they find one.

| Surface | Status |
|---|---|
| Claude Code | **Confirmed working.** Verified with a real question and a real answer. |
| Claude Desktop, normal chat | **Confirmed working**, after a full quit and reopen, on **two** machines — the second an install completed and run entirely by someone other than the author. |
| Codex TUI | Installed and reachable, but not exercised with a real GA question on this machine (the account was usage-throttled when this was last tried). Treat as "should work, not yet proven." |
| ChatGPT app — **Work** | **Confirmed working** (macOS, ChatGPT 26.1021, 2026-10-29): a real question answered with a GA tool. Work runs on the app's local Codex runtime, so the Codex plugin serves it; nothing extra to install. |
| ChatGPT app — **Codex** view | Served by the same plugin; same runtime as Work. |
| ChatGPT app — **Chat** | **Does not see the local servers, by design.** Chat is hosted: OpenAI's docs say it reaches only remote MCP servers, or local ones through Secure MCP Tunnel (Business/Enterprise workspaces, plus a hosted connection this package does not provide). Use Work instead. |
| claude.ai / ChatGPT web (browser) | **Cannot work, by design.** Browser-based chat runs tools on the vendor's servers and cannot reach a process on your machine. This is not a bug to file. |

## Before you start: get yourself onto the test-user list

**This is a prerequisite, not a step, and there is no way around it locally.**
The shared OAuth client is in Google's "Testing" publishing status, so Google
refuses consent to any Google account the Cloud project has not explicitly
listed as a **test user**. Already having Google Analytics access to the
properties does not help; neither does owning the project. What you would see
at Step 4, after signing in, is:

```
Error 403: access_denied
```

So before you begin, ask whoever gave you this repo to add the Google account
you will sign in with at Step 4 — the same account that holds the GA access you
want to read, which may be a personal Gmail rather than your organization's
address (`deployment.json` says which is usual in your deployment). Set up
just for yourself? Then you add your own account, once. They add it under the Cloud project's **Google Auth
Platform → Audience → Test users**. That is a one-time action per person: not
per install, not per machine, and not per weekly renewal.

Nothing you run on your own machine can grant this, so it is worth asking for
it first — the wait is the only part of this install you cannot do yourself.

The list holds **100 test users**, which is the real ceiling on how many people
this can serve while the client stays in Testing status.

## 1. Install the program

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh

# The installer puts uv at ~/.local/bin and edits shell rc files only, which
# does nothing for the shell you are already in. Set PATH here or the next
# line fails with "command not found: uv". This also covers the analytics-mcp
# console script, which lands in the same directory.
export PATH="$HOME/.local/bin:$PATH"
command -v uv    # must print a path before continuing
uv --version     # must be 0.13.4 or later (eMudhra/emSign); if not:
                 #   brew upgrade uv, or UV_SYSTEM_CERTS=true uv self update
uv tool install analytics-mcp==1.1.0 --with google-auth-oauthlib -c <repo>/data-noodler/installer/constraints.txt
uv tool update-shell    # puts the tool dir on PATH permanently
```

`uv` provisions its own Python, which matters because stock macOS Python is
too old for `analytics-mcp` (it needs 3.10+, macOS ships 3.9.6). Pin the
version — the alternative some docs suggest, `pipx run analytics-mcp`,
re-resolves from PyPI on every launch, which is an auto-updating dependency
reading your credential file. `google-auth-oauthlib` is needed by the consent script below and is not
a dependency of the server itself, so it rides along via `--with`. There
is no `uv tool inject` -- that is pipx's verb, and uv rejects it. On a
machine where analytics-mcp is already installed, add `--force` to make
the install replace it rather than skip.

`-c constraints.txt` pins every library underneath to a set that was tested
together and scanned for known vulnerabilities. Without it, `uv` takes
whatever is newest on the day, and an install then keeps those versions
until someone refreshes it. That is how installs from September were still
running a critical PyJWT advisory in October. (Already installed? See
"Upgrade instead" at the top.)

If you already have `analytics-mcp` installed via `pipx` instead of `uv`,
that's fine — the rest of this document works with either, and Step 3 below
detects which one you have automatically.

## 2. Get the shared OAuth client file

*Setting this up just for yourself, or for your own team, organization or
institution, with no maintainer to get the file from?* Make your own first:
[`GOOGLE-CLOUD-SETUP.md`](GOOGLE-CLOUD-SETUP.md) (about 20 minutes, once).

This file is **deliberately not in the repo**. Get the shared OAuth client
JSON — `ga-mcp-client.json` — from your deployment's maintainer (named in
`deployment.json`, with how they hand it over) directly: by password manager,
AirDrop, or in person. Not Slack, and not email to a list. `START-HERE.md`
explains what the file is and why it is kept out of version control.

Ask them to add your Google account to the test-user list in the same message
(see "Before you start" above) — that step cannot be done from your machine.

Put it somewhere under your home directory, for example:

```bash
mkdir -p ~/.config/gcloud
# move or copy the file you were given to:
#   ~/.config/gcloud/ga-mcp-client.json
```

A correct file has a top-level `"installed"` key (not `"web"`) and
`"redirect_uris": ["http://localhost"]`. This is a "Desktop app" OAuth
client — it is not a secret in the traditional sense (installed apps can't
hold a confidential secret, per RFC 8252), but keep it out of any git repo
and out of anywhere world-readable anyway.

If your browser saved it to Downloads, Desktop or a synced Documents folder,
delete that copy once consent (step 4) has worked. The copy in
`~/.config/gcloud/` is the only one you need.

## 3. Generate your machine's config

This is the step most by-hand instructions skip, which is why they don't
actually work — every other script here reads its paths from
`~/.config/ga-mcp/config.json`, and nothing creates that file for you until
now.

```bash
# A Python 3 for the installer's stdlib-only scripts. /usr/bin/python3 is a
# stub on a Mac without Apple's command-line tools (`xcode-select -p` errors);
# then use the Python uv brought in step 1.
PY3=/usr/bin/python3
xcode-select -p >/dev/null 2>&1 || PY3="$(uv python find)"
[ -x "$PY3" ] || echo "no usable Python 3: install uv first (step 1), then re-run"
"$PY3" <repo>/data-noodler/installer/bootstrap_config.py
```

A plain system Python is deliberate and correct here, not a shortcut. You do
not need Apple's developer tools: if `xcode-select -p` errors, the lines above
use the Python that uv installed in step 1 instead — `bootstrap_config.py` only uses the standard library,
and its whole job is to go *find* the interpreter that `analytics-mcp` runs
under (by reading the console script's shebang) so nothing later has to
guess it. It doesn't need to run inside that interpreter itself.

This writes `~/.config/ga-mcp/config.json` naming:

- where your OAuth client file and credential live,
- the exact Python interpreter that runs `analytics-mcp` (found by reading
  the console script's shebang — this is what lets the same instructions
  work whether you used `pipx` or `uv`),
- where your property-name lookup cache will live,
- the copy of `mint_adc.py` that the weekly-renewal command should point at —
  the one Step 5 installs under `~/.config/ga-mcp/`. This is what the
  `credential_status` tool reads to build the command it hands you, so the
  command it prints names a file that is actually on your machine.

By default it sets no Google Cloud quota project — both the GA Data API and
the GA Admin API work fine with no `x-goog-user-project` header at all, and
defaulting to someone else's project would require you to hold
`serviceusage.services.use` there, which you don't. Pass
`--quota-project YOUR_PROJECT_ID` only if you own a Cloud project yourself
and want usage billed/reported against it.

**It refuses to overwrite an existing `config.json`.** If you already have
one — from a previous install, or because you're re-running this — it prints
`already exists; left unchanged` and does nothing. That is intentional: your
existing config names a working credential you don't want silently
replaced. Pass `--force` only if you're sure (it writes a timestamped backup
of the old file before replacing it):

```bash
# PY3 again, in case this is a new Terminal window.
PY3=/usr/bin/python3
xcode-select -p >/dev/null 2>&1 || PY3="$(uv python find)"
[ -x "$PY3" ] || echo "no usable Python 3: install uv first (step 1), then re-run"
"$PY3" <repo>/data-noodler/installer/bootstrap_config.py --force
```

If it instead prints an error naming `analytics-mcp` and `uv tool install`,
Step 1 didn't finish — the program isn't on your `PATH` or at
`~/.local/bin/analytics-mcp`. If it names "interpreter", the console script
it found isn't a normal Python script (rare) — reinstall with `uv` or
`pipx`.

## 4. Run consent

This is the one step that needs your input: it opens a browser and asks you
to sign in with your own Google account.

```bash
"<venv_python from config.json>" <repo>/data-noodler/marketplace/plugins/ga-analytics/skills/google-analytics/scripts/mint_adc.py
```

Read `venv_python` out of the `config.json` step 3 just wrote (it's the
interpreter path that Step 3 discovered — no need to guess it). Quote it:
on macOS with `pipx` it contains a space
(`.../Library/Application Support/pipx/...`), and an unquoted path silently
fails.

This runs the copy of `mint_adc.py` inside your repo clone, not one under
`~/.config/ga-mcp/` — that copy doesn't exist until Step 5 installs the
payload, and there's no reason to wait for it since the script works
identically from either location. Once Step 5 has run, the weekly-renewal
command later in this document points at the installed copy instead, since
by then your repo clone may not still be nearby.

Expect a "Google hasn't verified this app" warning — that's expected; it's
the shared OAuth client in Testing status, not a sign anything is wrong.
Continue through it (Advanced → Continue). The consent screen now lists
**two** permissions, not one. The script prints the scopes it actually got —
confirm it says `analytics.readonly` and `webmasters.readonly`, and nothing
wider.

**If you get `Error 403: access_denied` instead**, you are not on the project's
test-user list — see "Before you start" above. That is a wall, not a warning:
re-running this command, regenerating `config.json` or reinstalling anything
will not change it. Ask the maintainer to add your account, then run this step
again.

## 5. Install the payload

```bash
"<venv_python>" <repo>/data-noodler/installer/install.py --payload-only
```

Copies the companion server, launcher scripts, and the Codex plugin
directory into `~/.config/ga-mcp/`. Safe to re-run any time you update the
repo.

## 6. Install the skills for Claude Code

Codex gets the `google-analytics` skill automatically — it travels inside the
plugin you install in step 8. Claude Code reads skills from your home
directory instead, so it needs its own copy:

```bash
"<venv_python>" <repo>/data-noodler/installer/copy_skills.py
```

That installs the `google-analytics` skill and the `ga-mcp-setup` skill (so a
later upgrade can be driven by asking an agent) into `~/.claude/skills/`,
marked so a later upgrade can refresh them. It never overwrites a skill
folder it didn't install, and never deletes anything. It prints a line per
skill: `not-ours-differs` (exit 2) means one exists and differs -- add
`--replace <name>` if you want it replaced; `blocked` or `missing-source`
(exit 1) means that skill was not installed, and the line says why.

Skip this and Claude Code still gets all twenty-four tools and still answers GA
questions correctly — the reporting discipline rides in the tool descriptions,
which is the half that does the real steering. What you lose is the fuller
guidance document and the command-line scripts (`lookup_property.py`,
`refresh_properties.py`), which are useful in a terminal and unavailable
otherwise.

**One trap worth naming.** `~/.claude/skills/` is scanned, so anything you put
there becomes a live skill. Do not park a backup copy inside it — a
`google-analytics.backup/` directory gets registered as a second skill with an
identical description, and the two then compete. Keep backups somewhere else,
such as `~/.claude/skill-backups/`.

Claude Desktop's normal chat appears nowhere in this step: it has no skill
mechanism at all. That absence is the reason the companion server exists.

## 7. Register Claude Code and Claude Desktop

**Open Claude Desktop once first -- sign in, then fully quit it.** Its data
directory does not exist until the app has run, and since 2026-10-05 the
installer refuses (exit 1) rather than silently skipping when Claude Desktop is
installed but that directory is missing. Most likely on a brand-new machine.

```bash
"<venv_python>" <repo>/data-noodler/installer/install.py --targets claude_code,claude_desktop
```

**Quit Claude Desktop first if it's running.** Both Claude Desktop and
ChatGPT.app periodically flush their own settings back to their config
files, and if that happens after this step writes the file but before you
restart, your new entry can be silently overwritten by the older
in-memory copy. The safe order is: **quit, register, reopen, verify** — not
register-then-quit.

This step also resolves *which* Claude Desktop config is actually active.
Two data directories can exist on the same machine (`Claude` and
`Claude-3p`), and writing to the inactive one produces no error at all — the
tools simply never show up. `install.py` prints the path it chose; read
that line. If it looks wrong, set `CLAUDE_USER_DATA_DIR` to override it.

## 8. Register Codex (also covers the ChatGPT app's Work and Codex)

One install serves all three, because the ChatGPT app runs its own `codex`
runtime sharing the same `~/.codex` state -- for its Codex view and its Work
mode alike. Not its Chat mode, which is hosted (see the table at the top):

**No `codex` command?** On a Mac with only the ChatGPT app (no separate Codex
install), `codex` may not be on the PATH. The app carries its own copy, which
reads the same `~/.codex` settings (checked 2026-10-29: it lists the same
plugins and marketplaces). Use it in place of `codex` in the commands below:
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`.

```bash
codex plugin marketplace add ~/.config/ga-mcp/marketplace
codex plugin add ga-analytics@ga-tools
```

Use the marketplace-qualified name, `ga-analytics@ga-tools`, not the bare
`ga-analytics` — the bare form is rejected by the Codex CLI once a
marketplace is registered. (You may see this documented elsewhere as just
`ga-analytics`; on this install, the bare form failed and the qualified
form is what worked.)

Do not edit `~/.codex/config.toml` by hand — it holds trust levels for
every project you've opened, plus live plugin state. Let the `codex` CLI
own that file.

## 9. Verify

```bash
"<venv_python>" <repo>/data-noodler/installer/verify.py --config ~/.claude.json \
    --require analytics-mcp=10 --require ga-companion=15 \
    --require-skill google-analytics
"<venv_python>" <repo>/data-noodler/installer/verify.py --config "<claude desktop config path from step 7>" \
    --require analytics-mcp=10 --require ga-companion=15
codex plugin list   # expect ga-analytics@ga-tools: installed, enabled
```

Expect `analytics-mcp` with 9 tools and `ga-companion` with 15 tools. This
proves each entry actually launches and answers the MCP handshake — it
cannot prove the tools show up in an app's UI.

**Nothing is "downloaded."** When you ask for an export, the server is
running locally and writes the file straight to disk — there is no browser
involved, so it never lands in `~/Downloads`. Exports go into
`~/Documents/analyst-sessions/` (one dated folder per session, or wherever
`sessions_root` in `~/.config/ga-mcp/config.json` points, if it was
changed). The chat receipt always names the full path it wrote to; that
path is the answer to "where did my file go?", not your Downloads folder.

## 10. Fully quit and reopen every app you registered

This is not optional and "closing the window" does not count. A running
client keeps its old config and its old child server processes in memory;
only a full quit (Cmd-Q on macOS, or Quit from the app menu, not the red
window button) and reopen picks up what Steps 6–7 just wrote. After
reopening, ask each surface a real question, for example: "Is my Google
Analytics credential still valid?" or "What's the property ID for
example.com?"

## 11. Tell your maintainer how it went

*Set up just for yourself?* You are your own maintainer, and there is no one
to send this to. Skip sending; if you like, keep a few lines for your own
records.

Otherwise, send your deployment's maintainer (named in `deployment.json`) a short note: your operating system, which apps you
registered, and anything that did not work exactly as written here, with the
error text if there was one. Something you had to work around is the most
useful thing you can send, because it is the next person's wall. An agent
following the `ga-mcp-setup` skill writes a fuller report for you at this
point; by hand, a few lines is plenty. Never include the contents of
`ga-mcp-client.json` or of the credential file.

## Weekly reauthentication

The shared OAuth client is in Google's "Testing" publishing status. Google
issues 7-day refresh tokens to Testing apps requesting anything beyond
basic profile scopes, so your credential will stop working about once a
week. **This is by design, not a bug** — it is the tradeoff for a shared
project needing no per-user setup on our end. When it happens, any GA tool
call will say so; ask the model, or run the renewal command yourself:

```bash
"<venv_python>" ~/.config/ga-mcp/marketplace/plugins/ga-analytics/skills/google-analytics/scripts/mint_adc.py --force
```

This is the copy of `mint_adc.py` that Step 5 installed under
`~/.config/ga-mcp/` — by now it's guaranteed to be there and kept current by
re-running Step 5, whereas your repo clone from Step 4 may no longer be on
this machine or up to date. This opens the same browser consent as Step 4.
No terminal-only fix exists because Google's consent step requires a
browser session with you signed in.

## If something goes wrong

Read `<repo>/data-noodler/skills/ga-mcp-setup/references/troubleshooting.md`.
Match the exact error text before assuming it's a credential problem — an
expired credential is the most-documented failure and therefore the easiest
wrong guess.
