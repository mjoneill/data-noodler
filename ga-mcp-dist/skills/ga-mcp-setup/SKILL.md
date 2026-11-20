---
name: ga-mcp-setup
description: Install or repair Google Analytics MCP access across local LLM harnesses — Claude Code, Claude Desktop, Codex TUI, and the ChatGPT desktop app's Work and Codex modes. Use when the user wants to set up GA access, add GA to another app, says GA tools are missing or a connector is broken, or when analytics tools fail in a way that is not a simple credential expiry. Also use for first-time setup on a new machine.
---

# Installing GA access into local harnesses

Nothing here needs administrator privilege. Every path written is under the
user's home directory. An MCP stdio server is a child process of the LLM
application, not a service — "installing" it is a program on disk plus a
config entry naming a command to launch.

## Before you start

**Read `deployment.json` first** (beside this package's `INSTALL.md`). It
names this deployment's maintainer and says where the OAuth client file comes
from. If its `maintainer` is blank, nobody has set this package up for this
user yet, whether just for themselves or for a team, organization or
institution: stop, and follow `START-HERE.md`, which walks the user through
that, before installing anything. Blank `maintainer_contact` and
`install_reports_to` with a filled `maintainer` is a finished
just-for-yourself setup: carry on.

Run the whole flow from Claude Code or Codex -- these instructions are for
whichever agent is installing, and where a step applies to only one app
(Claude Code skills, the Codex plugin) it says so. Claude Desktop's normal
chat has no shell, so it cannot install anything -- but it is a valid
*target*, and this session will configure it.

**The division of labour.** You read the machine and decide; tested code in
`installer/` makes every change; `verify.py` decides "done". Run the code --
do not re-create its steps by hand, even when they look simple: the code's
order, refusals and undo are the point, and an improvised version is a
different install nobody can support afterwards. When the code's view of the
machine is wrong, correct it with its flags (`--venv-python`,
`--base-python`, `CLAUDE_USER_DATA_DIR`), and if no flag fits, stop and
report rather than working around it.

**Cloud and web chat surfaces cannot be served.** ChatGPT's Chat mode (in the
desktop app as well as the browser) and claude.ai in a browser execute tools
on the vendor's servers and cannot reach a local process. Do not attempt it;
say so plainly if asked. The ChatGPT desktop app's **Work** mode is different:
it runs on the app's local Codex runtime, so the Codex plugin serves it
(confirmed 2026-10-29). Tell a ChatGPT user to use Work, not Chat.

**On Windows, read `references/windows.md` before Step 2 and keep it open.**
The steps and their order are the same there; the differences each have a
measured reason. In short: Python itself may be missing and has to be
installed by the user, not by you; no `uv` (stock `python -m venv` instead);
no launchers (the entry names the interpreter directly, and analytics-mcp
runs as `python.exe -m analytics_mcp.server` because Defender can block the
`.exe`); no `.ps1` (execution policy blocks unsigned scripts); and quitting
the application before registering is a hard requirement rather than
prudence.

**If you are running inside the Claude Desktop app** -- its Code tab, which is
how Claude Code is usually used on Windows -- two things must be handed to the
user rather than run by you:

- **Anything that runs a system installer**, such as the Python installer.
  The Desktop app is a packaged (MSIX) app on Windows, and an installer
  launched from inside it fails: measured 2026-10-09, the python.org installer
  exited 3 (MSI error 2203) because the container redirected the files the
  Windows Installer service needed. The same installer run by the user from
  an ordinary PowerShell window worked. Give them the command; do not retry it
  yourself.
- **Registering Claude Desktop** (Step 7). Desktop has to be fully quit for
  that, and quitting Desktop ends this session.

**Fresh install or upgrade.** Step 1 tells you which. An upgrade is Step 1,
then Step 2's "On an upgrade" (`upgrade.py`, which replaces Steps 2 and 4-8
for an existing install), then Steps 9 and 10. Do Steps 3 and 5 only where
Step 1 shows the client file or credential missing. Never upgrade by copying
the payload alone: that leaves the old libraries in place, which is how
vulnerable versions survived the September-to-October upgrades. Say at the start which one this is, because the report in
Step 10 records it.

**Keep notes as you go.** Step 10 asks you to write an install report, and it
is required. For every step, note who ran it (you or the user), what
happened, and anything you did that this document did not tell you to do.
Workarounds are the most valuable thing in that report: a workaround nobody
reports is a fix nobody makes, and the next install hits the same wall.

Do not translate the `bash` in this document into PowerShell by eye. Where a
command differs by platform it is given for both, and Step 1 replaces the
guesswork entirely.

## Step 1: Check what already works

Run this first, before deciding anything. It is read-only — it opens files
and reports what it finds, and writes nothing anywhere:

```
python3 <repo>/ga-mcp-dist/installer/probe.py
```

Any Python 3 will do; this one only reads. Add `--json` for compact output.

**On Windows the command is `python`, not `python3`** -- a python.org install
has no `python3.exe`, and the name may instead be the Microsoft Store stub,
which prints nothing. `references/windows.md` has the rest.

**On a Mac with no usable Python yet** -- `xcode-select -p` errors, so
`/usr/bin/python3` is only a stub that offers to install Apple's developer
tools (common on a ChatGPT-only Mac, measured 2026-10-29) -- do Step 2 first:
it installs uv, which brings its own Python. Then run this step with
`"$(uv python find)"` in place of `python3`. You do not need Apple's
developer tools for anything here.

It replaces the shell this step used to carry. That shell was `bash`, and on
Windows the agent's shell is PowerShell, so every line was something to
translate by eye — and a translation is an improvisation. One command with the
same keys on every platform removes the opportunity.

What to read in the output:

- `analytics_mcp.binary` — null means Step 2 has not run.
- `analytics_mcp.imports_ok` — **false is the dangerous one.** The program is
  there and the interpreter cannot import what it needs, which later presents
  as "the tools are missing" and gets misdiagnosed as credentials.
- `config.exists` and `config.error` — an error here means the file is present
  but unreadable; say so rather than regenerating it.
- `credential.days_remaining` — the credential expires weekly by design. If
  there is time left, **leave it alone** (see Step 5).
- `harnesses.*.ga_servers_registered` — what is already installed where.
- `harnesses.*.other_servers` — MCP servers that are not ours. You are writing
  into a config someone else's tools also live in; mention it.

`installer/` is never copied to `~/.config/ga-mcp/` — only `companion/`, `bin/`
and `marketplace/` are (see Step 6) — so this and Step 8 both run from the repo
checkout. A path under `~/.config/ga-mcp/` will never exist and would silently
prove nothing.

If GA tools already work in this harness, the user probably wants a *different*
harness added. Skip to Step 7.

## Step 2: Put the program on disk

Only if `analytics-mcp` is absent. Check first:

```bash
ls ~/.local/bin/analytics-mcp 2>/dev/null || command -v analytics-mcp
```

If missing:

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh

# The installer puts uv at ~/.local/bin and edits shell rc files only, which
# does nothing for the shell you are already in. Set PATH here or the next
# line fails with "command not found: uv". This also covers the analytics-mcp
# console script, which lands in the same directory.
export PATH="$HOME/.local/bin:$PATH"
command -v uv    # must print a path before continuing
uv --version     # must be 0.13.4 or later (eMudhra/emSign); see below
uv tool install analytics-mcp==1.1.0 --with google-auth-oauthlib -c <repo>/ga-mcp-dist/installer/constraints.txt
uv tool update-shell    # puts the tool dir on PATH permanently
```

`uv` provisions its own Python. This matters: stock macOS ships Python 3.9.6
and `analytics-mcp` requires 3.10+. Do not try to use the system Python.

**uv must be 0.13.4 or later** (Step 1's `uv.below_floor`). Older uv trusts
the compromised eMudhra/emSign certificate keys and downloads packages itself.
If it is older: `brew upgrade uv` for a Homebrew uv, otherwise
`UV_SYSTEM_CERTS=true uv self update`.

`-c constraints.txt` pins every library underneath to a tested, scanned
set. Without it `uv` takes whatever is newest that day, and the install keeps
it until something refreshes it.

### On an upgrade: refresh the libraries too -- one command, which you supervise

**Copying a new payload never touches the libraries underneath.** That is how
installs made in September were found, on 2026-10-23, still running PyJWT
2.13.0 (a critical advisory) and a certifi that trusted compromised
certificate authorities, after "upgrades". So an upgrade replaces the whole
venv, with `installer/upgrade.py`.

**Why that one part is a script.** The venv can only be swapped with every app
that runs our servers fully quit -- and you run inside one of them. So it is a
transaction the user runs alone, and it is kept to exactly that. Read
`installer/upgrade.py` before you use it; it says what it does at the top.
It renames the venv aside, builds a fresh one (pip by URL and sha256, then the
pins), proves both servers from the new package, re-installs and registers,
verifies the servers the way the apps start them plus each Claude config, and
on any failure removes only what it built and puts the originals back. It
never deletes anything that existed before it started.

**Before -- you:**

1. Step 1's `probe.py`. Note `dependencies.below_floor`: that is what the
   upgrade removes.
2. `upgrade.py --plan` (read-only, any Python 3: `python` on Windows, and
   `"$(uv python find)"` on a Mac where `xcode-select -p` errors). It prints what it found --
   the venv, the base Python it will build from, the package, the Claude
   configs, whether Codex is installed, and whether anything is still
   running from the venv -- then READY, "READY once every app is quit", or
   NOT READY. **Check it against the machine and probe's output.** Wrong base
   Python? Re-run with `--base-python <path>`. Anything marked FIX that a flag
   cannot fix: stop and report.

**The run -- the user, alone.** Hand them this, with the real paths from
`--plan`, for Terminal (macOS) or an ordinary PowerShell window (Windows;
put `& ` in front and use backslashes):

```
"<base python>" "<package>/ga-mcp-dist/installer/upgrade.py"
```

They fully quit Claude Desktop (from its icon by the clock on Windows, Cmd-Q
on a Mac), every Claude Code window, Codex and the ChatGPT app first. It
checks again and refuses -- changing nothing -- if anything is still running.
"Upgrade complete" means every check passed. "UPGRADE FAILED" or
"INTERRUPTED" followed by "Restored" means it already put everything back:
send the output to the maintainer and stop. If the run was killed, the
window closed, or it ends "MOST of it was put back", the user runs the same
command with `--recover` (troubleshooting.md has the details). Do not finish
or undo an upgrade by hand.

**After -- you, in a reopened app:**

1. `probe.py` again: `dependencies.below_floor` must be empty.
2. **Codex installed?** `codex plugin add ga-analytics@ga-tools`. Codex caches
   plugins by version; without this it keeps the old plugin.
3. **Claude Code used?** `<venv_python> <package>/ga-mcp-dist/installer/copy_skills.py`.
   It refreshes only skill folders this package installed (they carry a
   `.ga-mcp-installed` marker). It prints one line per skill; read every
   line, whatever the exit code. Exit 0: done. Exit 2: a folder exists that
   this package did not put there (`not-ours-differs`) -- an earlier hand
   copy, or the maintainer's own master; tell the user, and only on a yes
   re-run with `--replace <name>`. Exit 1: a skill could not be installed
   (`blocked`: a file or broken link where the folder should be;
   `missing-source`: the payload is missing) -- say so, and do not report
   the skills as installed. Exit 1 wins over 2, so check the lines for a
   `not-ours-differs` decision too.
4. Step 9 (offer to remove the old venv and older backups), then Step 10.

**On Windows** none of the above applies. Follow `references/windows.md`
instead: first check that a real Python exists (the `python.exe` in
`WindowsApps` is a Store stub, not an interpreter), have the user install one
from an ordinary PowerShell window if not, then create the venv with
`python -m venv` and the pinned `constraints.txt`.

## Step 3: Make sure the shared OAuth client file is present

This is the one prerequisite you cannot satisfy yourself, and the one most
likely to be missing on a machine that is not the author's. Check before
going further:

```bash
ls -l ~/.config/gcloud/ga-mcp-client.json
```

If it is there, say so and move to Step 4.

If it is not, **look for it where people actually save things** before asking.
People download what they are sent wherever their browser puts it, so check
the Downloads, Desktop and Documents folders, the folder the package was
unzipped into, and the current working folder. Look for `ga-mcp-client.json`
and browser renames of it, such as `ga-mcp-client (1).json`. **Never print
the file's contents.** To check that a candidate is the right kind of file,
read only its top-level key (`"installed"`) and its `client_id`. A
`client_secret_*.json` may belong to something else entirely, so ask the user
before using one.

If you find it, **copy** it into place (create `~/.config/gcloud` first; on
Windows `%USERPROFILE%\.config\gcloud`) and tell the user where it came from.
Copy, not move: the loose original is dealt with in Step 9, with the user's
say-so, once you know the installed copy works.

If it is nowhere, **stop and ask the user for it** -- do not try to generate,
download or reconstruct one. If they have no maintainer to get it from
(they are setting this up just for themselves, or for their own team,
organization or institution), point them to
`ga-mcp-dist/GOOGLE-CLOUD-SETUP.md`: they create their own client once, then
come back to this step. It is deliberately not in the repo, and there is
nowhere you can fetch it from.

What to tell them: `deployment.json` names the maintainer and says how the
file is handed over -- directly, by password manager, AirDrop, or in person,
never over Slack or a mailing list. Save it as `ga-mcp-client.json` at
`~/.config/gcloud/ga-mcp-client.json` (`mkdir -p ~/.config/gcloud` first).
`START-HERE.md` says what it is and why it is kept out of the package.

Tell them to ask, in the same message, to be added to the test-user list. It is
the other thing only the maintainer can do, and without it Step 5 fails with
`access_denied` -- which reads like a local fault and is not one.

A correct file has a top-level `"installed"` key, not `"web"`, and
`"redirect_uris": ["http://localhost"]`. It is a Desktop-app OAuth client, so
it cannot hold a confidential secret (RFC 8252), but it still belongs outside
any git repo and anywhere world-readable.

Checking this here rather than later is the whole point of the step. Step 4
writes an `oauth_client_file` key naming this path whether or not anything is
at it, and the failure does not surface until consent in Step 5 -- by which
point nothing on screen suggests a file was ever missing.

## Step 4: Generate this machine's config

Every step after this one reads its paths from `~/.config/ga-mcp/config.json`,
which is what makes them portable. **Nothing else in this flow creates that
file.** On a machine that has had GA access before it is already there; on a
colleague's machine it is not, and without it Step 5 has no `adc_file` to check
and Steps 5–7 have no `<venv_python>` to substitute — the flow would stall with
nothing to put in the command.

```bash
# A Python 3 for the installer's stdlib-only scripts. /usr/bin/python3 is a
# stub on a Mac without Apple's command-line tools (`xcode-select -p` errors);
# then use the Python uv brought in Step 2.
PY3=/usr/bin/python3
xcode-select -p >/dev/null 2>&1 || PY3="$(uv python find)"
[ -x "$PY3" ] || echo "no usable Python 3: install uv first (Step 2), then re-run"
if [ -f ~/.config/ga-mcp/config.json ]; then
  echo "config already present; leaving it alone"
else
  "$PY3" <repo>/ga-mcp-dist/installer/bootstrap_config.py
fi
```

A plain system Python -- the same one Step 2 says not to run the server on --
is deliberate and correct here, not a shortcut.
`bootstrap_config.py` uses only the standard library, and its whole job is to
go *find* the interpreter `analytics-mcp` runs under, by reading the console
script's shebang: the one place that always names it, whether the install came
from `uv` or from `pipx`, and the reason nothing later has to guess. It does
not need to run inside that interpreter. (The launchers themselves no
longer need Python to read the config: they use `plutil`, which every Mac
has.)

It writes `oauth_client_file`, `adc_file`, `venv_python`, `properties_csv`,
`analytics_mcp_bin` and `mint_script`. Read `venv_python` out of it
afterwards: that is the `<venv_python>` every later step substitutes.

It does **not** write a `quota_project` unless `--quota-project
YOUR_PROJECT_ID` is passed explicitly — both GA APIs work with no quota
project header, and defaulting to a project the installing user doesn't own
would require them to hold IAM there just to make GA calls succeed. Only
pass the flag if the user says they own a Cloud project and want usage
billed/reported against it.

It **refuses to overwrite an existing `config.json`**, printing
`already exists; left unchanged`. That is intentional — an existing config
names a credential and a property snapshot someone is relying on. Pass
`--force` (which writes a timestamped backup first) only if the user has said
the existing config is wrong.

If it errors naming `analytics-mcp` and `uv tool install`, Step 2 did not
finish — the program is not on `PATH` or at `~/.local/bin/analytics-mcp`. If it
errors naming "interpreter", the console script it found is not a normal Python
script (rare); reinstall with `uv` or `pipx`.

## Step 5: Credential

**Never re-mint a working credential.** Check first:

```bash
# Set PY3 again here: a new shell does not remember Step 4's.
PY3=/usr/bin/python3
xcode-select -p >/dev/null 2>&1 || PY3="$(uv python find)"
[ -x "$PY3" ] || echo "no usable Python 3: install uv first (Step 2), then re-run"
"$PY3" -c "
import json, os, time
# Any Python 3 will do; this reads stdlib json only.
cfg_path = os.path.expanduser('~/.config/ga-mcp/config.json')
if not os.path.exists(cfg_path):
    print('no ~/.config/ga-mcp/config.json -- Step 4 did not run or failed')
else:
    cfg = json.load(open(cfg_path))
    p = os.path.expanduser(cfg['adc_file'])
    print('missing' if not os.path.exists(p)
          else f'{7 - (time.time()-os.path.getmtime(p))/86400:.1f} days left')
"
```

Read `adc_file` out of `~/.config/ga-mcp/config.json` rather than assuming its
filename. That config is already the authority for `venv_python` elsewhere in
this doc; treating the credential path as fixed instead would give a false
"missing" on any colleague's machine where it is named differently, and route
them straight into an unnecessary re-mint -- the outcome this step exists to
prevent.

If a credential exists with time remaining, leave it alone. Re-running consent
would replace a working setup for no reason. You can also check via the
companion server's `credential_status` tool if it is already registered
somewhere — do not re-mint just because a different harness lacks the
credential file; the file is shared across every harness.

If it is missing or expired, give the user this command to run themselves — it
opens a browser and you cannot click through it for them:

```bash
"<venv_python from ~/.config/ga-mcp/config.json>" <repo>/ga-mcp-dist/marketplace/plugins/ga-analytics/skills/google-analytics/scripts/mint_adc.py --force
```

Run the copy in the repo checkout, because at this point in the flow the
payload step has not run yet, so no copy exists under `~/.config/ga-mcp/`.
Once the payload is installed, the equivalent installed copy is
`~/.config/ga-mcp/marketplace/plugins/ga-analytics/skills/google-analytics/scripts/mint_adc.py`
— which is what `config.json`'s `mint_script` names and what
`credential_status` hands the user for weekly renewal. Do not point anyone at
`~/.claude/skills/google-analytics/scripts/mint_adc.py`: nothing in this
install creates that path.

Expect a "Google hasn't verified this app" warning: it is the OAuth client in
Testing status. Continue via Advanced. The consent screen now lists **two**
permissions, not one — the script requests both `analytics.readonly` and
`webmasters.readonly`, and prints what it actually got; confirm both appear
before telling the user it worked. The 7-day expiry is a property of
Testing status, not a misconfiguration — it will look exactly like a broken
install every seven days, and it is not one.

**Before sending anyone into consent, check they are on the project's test-user
list.** Testing publishing status means Google refuses consent to any Google
account the Cloud project has not listed as a test user, and returns
`Error 403: access_denied` — which to the user is indistinguishable from a
broken install. Having GA access to the properties does not help. Nothing you
or they can run locally fixes it: the project's maintainer must add that
Google account under **Google Auth Platform → Audience → Test users**, once,
ever, per person. So if `access_denied` appears, say exactly that and who to
ask — do not re-run consent, and do not start debugging the config. (For the
project's own maintainer on their own machine, this is already done and will
not come up.) The list caps at 100 test users.

## Step 6: Install the payload

```bash
"<venv_python>" <repo>/ga-mcp-dist/installer/install.py --payload-only
```

Copies `companion/`, `bin/` and `marketplace/` into `~/.config/ga-mcp/`. Safe
to re-run.

Then install the `google-analytics` skill for Claude Code, plus this setup
skill so a later upgrade can be driven the same way. Step 8 checks the first
one is there. (Codex gets its skill inside the plugin in Step 7; Claude
Desktop chat has no skill mechanism.)

```bash
"<venv_python>" <repo>/ga-mcp-dist/installer/copy_skills.py
```

That installs both into `~/.claude/skills/` (on Windows
`%USERPROFILE%\.claude\skills\`) with a `.ga-mcp-installed` marker, so a
later upgrade can refresh them. It never overwrites a skill folder it did not
put there and never deletes anything. Read every line it prints: exit 2
(`not-ours-differs`) means such a folder exists and differs -- tell the user,
and only on a yes re-run with `--replace <name>`; exit 1 means a skill could
not be installed at all (`blocked` or `missing-source`) -- say so.
Codex users can skip this; their skill comes with the plugin.

Never leave a backup copy of a skill inside `~/.claude/skills/`. Anything there
is loaded as a live skill, and a backup competes with the real one.

## Step 7: Register each harness

**Claude Code and Claude Desktop:**

```bash
"<venv_python>" <repo>/ga-mcp-dist/installer/install.py --targets claude_code,claude_desktop
```

This resolves the *active* Claude Desktop data directory itself. Two can
exist — `Claude/` and `Claude-3p/` — and a config written to the inactive one
is ignored with no error at all: no error, no warning, the tools just never
appear. `install.py` prints which path it chose — read that line and confirm
it looks right; if it looks wrong, `CLAUDE_USER_DATA_DIR` overrides it.

Both Claude Desktop and ChatGPT.app persist their own settings into the same
config files this step writes. If either application is running while
registration happens, its later flush back to disk can silently drop the
entries just written. The safe order is: **quit the application first,
register, then reopen it** — and verify again after it reopens.

**If you are running inside Claude Desktop, register Claude Desktop by
handing it to the user.** Quitting Desktop ends this session, so you cannot
do it yourself. Register Claude Code yourself (`--targets claude_code`), then
give the user a block to paste into an ordinary terminal (on Windows,
PowerShell -- not this app), with the real paths filled in. Step 1's output
names the Desktop config path. On Windows:

```powershell
# 1. Fully quit Claude Desktop: right-click its icon by the clock, then Quit.
#    Closing the window is not enough.
# 2. Then run:
& "<venv_python>" "<repo>\ga-mcp-dist\installer\install.py" --targets claude_desktop
& "<venv_python>" "<repo>\ga-mcp-dist\installer\verify.py" --config "<Desktop config path>" --require analytics-mcp=10 --require ga-companion=15
# 3. Reopen Claude Desktop and paste both outputs back into this chat.
```

On macOS the same block runs in Terminal, after quitting Claude with Cmd-Q.
`verify.py` exiting 0 is what tells you it worked. Ask for the output. Do not
take "it worked" on trust.

**On Windows, the analytics-mcp entry runs
`<venv>\Scripts\python.exe -m analytics_mcp.server`, not
`analytics-mcp.exe`.** That is deliberate. Do not "fix" it back: Defender's
Attack Surface Reduction rule blocks the pip-generated `.exe` on managed
machines (see `references/troubleshooting.md`, "Access is denied on Windows").

**Codex TUI and the ChatGPT app's Work and Codex modes** — one install serves
all of them, because the ChatGPT app runs its own codex runtime sharing
`~/.codex`, for Work as well as its Codex view:

**No `codex` command?** On a Mac with only the ChatGPT app (no separate Codex
install), `codex` may not be on the PATH. The app carries its own copy, which
reads the same `~/.codex` settings (checked 2026-10-29: it lists the same
plugins and marketplaces). Use it in place of `codex` in the commands below:
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`.

```bash
codex plugin marketplace add ~/.config/ga-mcp/marketplace
codex plugin add ga-analytics
```

The bare name `ga-analytics` is rejected once the marketplace is registered
more than once, or ambiguously named — Codex wants the marketplace-qualified
form:

```bash
codex plugin add ga-analytics@ga-tools
```

If the bare `codex plugin add ga-analytics` fails, use the qualified form
above; it is what actually works.

Let the codex CLI write `~/.codex/config.toml`. **Never edit that file
directly** — it holds trust levels for every project the user has opened, plus
live plugin state.

## Step 8: Verify before claiming success

```bash
"<venv_python>" <repo>/ga-mcp-dist/installer/verify.py --config ~/.claude.json \
    --require analytics-mcp=10 --require ga-companion=15 \
    --require-skill google-analytics
"<venv_python>" <repo>/ga-mcp-dist/installer/verify.py --config "<claude desktop config path>" \
    --require analytics-mcp=10 --require ga-companion=15
```

**Use `--require`, and treat the exit code as the answer.** Without it success
is a sentence you have to read and agree with, and you are the least impartial
reader of your own output there is. With it, done is exit 0 and nothing else.

A server that starts but serves the wrong number of tools is reported as
UNMET rather than OK. That case means the payload on disk is not the expected
one — it is not a credential problem, and should not be treated as one.

A `FAIL` with `[WinError 5] Access is denied` comes with a `why:` line. It is
Microsoft Defender, not the credential. Follow
`references/troubleshooting.md`, "Access is denied on Windows".

This proves the entry is launchable. It cannot prove the tools appear in an
app's UI, so finish by telling the user to **restart each application** and ask
one GA question. Restart is not optional: a running client holds its old
config and its old child server processes — quitting the app fully (not just
closing its window) and reopening it is required, not a nicety.

## Step 9: Clean up, with the user's say-so

Nothing in this step is removed by a script, and nothing is removed by you
without asking. For each item you find, tell the user what it is, why it is no
longer needed, and ask whether to remove it. Remove it only on a yes. If you
are unsure whether something is safe to remove, say so and leave it.

**Loose copies of the OAuth client file.** Once consent has worked, look again
in the places Step 3 searched for copies other than
`~/.config/gcloud/ga-mcp-client.json`. Identify them by `client_id` only;
never print the contents. Tell the user where each one is and why it should
not stay there: Downloads, Documents and Desktop are often synced (OneDrive,
iCloud) or shared. Offer to delete each one.

**Leftovers from an earlier install** (upgrades). Look for:

- **Helper scripts a previous install created** to work around a problem that
  this package now fixes. The known case is `fix_asr_entry.py`, written on a
  2026-10-09 install to switch the analytics-mcp entry to `python -m` after
  each re-install. `install.py` now writes that entry itself, so the helper is
  redundant. Read anything unfamiliar before describing it, and describe what
  it actually does.
- **Hand-edited entries.** Step 7 rewrote our two entries, but compare
  `verify.py`'s output with what you expect. Any other `mcpServers` entry
  belongs to the user, so leave it alone, and do not offer to remove it.
- **Old unzipped package folders**, for example an earlier `ga-mcp-src`.
  Check what is in one before calling it old.
- **The previous venv** `upgrade.py` left, at the path it printed:
  `~/.config/ga-mcp/<venv name>.old-<stamp>` (beside the venv only if
  that is on another disk). Installs upgraded before 2026-10-26 may also
  have one beside the venv, e.g. in pipx's `venvs` folder. Nothing uses
  it once the upgrade verified; it is only the undo. Offer to delete it --
  after the user has used the upgraded tools once is a sensible time.
- **Older payload copies** (`~/.config/ga-mcp/{companion,bin,marketplace}.ga-old-<stamp>`).
  `install.py` keeps one per run and never removes them. Offer to delete all
  but the newest. Likewise any `*.failed-<stamp>` folder a rolled-back
  upgrade had to move aside.

Leave these alone:

- `venv\Scripts\analytics-mcp.exe` and anything else inside the venv. It
  belongs to the pip package, is harmless when nothing runs it, and pip
  recreates it on the next install.
- `*.ga-backup-*` files beside the configs. They are this installer's own
  backups, and they are the only undo there is. You may tell the user they
  exist and roughly how many; any clean-up is the user's call, made by them.

Record what you found and what the user chose in the Step 10 report.

## Step 10: Write the install report

**Required, on fresh installs and upgrades alike.** Without it, anything that
went wrong or needed a workaround on this machine never reaches the person who
can fix it.

Use the template in `references/install-report.md`, and save it as
`~/.config/ga-mcp/install-reports/<YYYY-MM-DD>-<fresh|upgrade>.md` (create the
folder; on Windows `%USERPROFILE%\.config\ga-mcp\install-reports\`). Then:

1. Show the user the report, or a short summary of it, and the path.
2. Ask them to send the file to the maintainer, the way `deployment.json`'s
   `install_reports_to` says. It contains no credentials, which is why it is
   safe to send that way. **If `install_reports_to` is blank** (set up just
   for themselves), there is no one to send it to: keep the report where it
   was saved, as their own record, and skip sending.

Write what actually happened, not what should have happened. If you deviated
from this document, that deviation is a finding: name it, along with why you
did it.

## What the user gets per surface

| Surface | GA tools | Skill |
|---|---|---|
| Claude Code | yes | yes |
| Claude Desktop, normal chat | yes | via `reporting_guide` and tool descriptions |
| Codex TUI | yes | yes, from the plugin |
| ChatGPT app, Work mode | yes (confirmed 2026-10-29) | yes, from the plugin |
| ChatGPT app, Codex view | yes | yes, from the plugin |
| ChatGPT app, Chat mode | **no** -- hosted; see below | -- |

In Claude Desktop chat there is no shell, so `lookup_property`,
`credential_status` and `refresh_property_snapshot` are the only route to that
capability. That is what the companion server is for.

A local install does not serve ChatGPT's Chat mode (desktop or browser), or
claude.ai in a browser. Those run tools on the vendor's servers and cannot reach anything on
this machine — that is a hard boundary, not a configuration gap, and no amount
of retrying closes it. For ChatGPT the only route OpenAI documents is Secure
MCP Tunnel (Business/Enterprise workspaces, with a hosted connection), which
this package does not provide.

**Where Work-mode exports land.** Each Work conversation runs in its own
folder under `~/Documents/Codex/<date>/<topic>/`, which counts as the
project, so exports go to an `_outputs` folder inside that conversation's
folder (measured 2026-10-29). The receipt names the path. A user who wants
everything in one place asks for `save_to: sessions`.

## What comes next

Nothing further for installation: Step 4 generates the config, so this skill
covers the whole path on a machine where nothing was set up before.

A colleague who would rather not run an agent through it at all can follow
`ga-mcp-dist/INSTALL.md` instead — the same path written out as
copy-pasteable steps, including the same `bootstrap_config.py` call. The two
documents are alternatives, not halves: either is sufficient on its own, and a
change to one belongs in the other.

## When something fails

Read `references/troubleshooting.md`. Match the error text before assuming it
is credentials — that is the most documented failure and therefore the default
wrong guess.
