# How this package works

For an agent or a person deciding whether to adopt it. Everything here is
checkable in the code and tests it names.

## The pieces

| Piece | Where | What it is |
|---|---|---|
| `analytics-mcp` | installed from PyPI (Google's own server) | 10 tools for GA4 reports, property details, realtime, funnels, key events. Pinned to one version. Its optional write tools are never enabled. |
| `data-noodler` | `server/` | 15 tools built here: cheap property lookup from a local snapshot, credential status, a reporting guide, exports to CSV (GA4 reports, cohorts, realtime, funnels), two GA4 read-only checks, and four Search Console tools (sites, URL inspection, search analytics, sitemaps). |
| Launchers | `bin/` (macOS) | Two `/bin/sh` scripts that set the environment and start each server. On Windows there are no launchers; the registered entry names the interpreter directly. |
| Installer | `installer/` | `probe.py` (read-only facts about the machine), `bootstrap_config.py` (writes the machine's config), `install.py` (copies the payload, registers the apps), `verify.py` (proves each registered server starts and serves the expected tools), `upgrade.py` (replaces an existing install, with rollback), `copy_skills.py`. |
| Skills | `skills/data-noodler-setup/` (the install), and `data-noodler` inside the Codex plugin | Instructions an agent follows: how to install, and how to query well. |
| Codex plugin | `marketplace/` | Packages the servers and the query skill for Codex and the ChatGPT desktop app's Work and Codex modes (its Chat mode is hosted and cannot reach local servers). |

Why a second server exists: Claude Desktop's chat has MCP tools but no shell
and no skills, so anything the query skill's scripts did had to become a
tool. The data-noodler server re-exposes that capability and extends it.

## Why the install is split the way it is

Two earlier ports to new machines taught that **everything that breaks is
discovery**: reading an unfamiliar machine (where Python is, which config
folder an app really uses, what security policy blocks). **Nothing that broke
was a write**: merging a JSON entry or copying a folder is the same
everywhere. So:

- **Discovery is the agent's job**, helped by one read-only script
  (`probe.py`). An agent re-reads reality each time; code encodes what was
  true when it was written.
- **Every write goes through tested code.** The agent runs the scripts; it
  does not re-create their steps by hand, because the scripts' order,
  refusals and undo are the point.
- **"Done" is an exit code.** `verify.py --require name=count` starts each
  registered server exactly as the app would and checks the tool count. An
  agent's claim of success is not accepted without it.
- **Walls have named flags**, so an agent that hits one has an exit it does
  not have to invent (`--venv-python`, `--base-python`,
  `CLAUDE_USER_DATA_DIR`), and the instruction is to stop and report rather
  than work around.

One deliberate exception: **`upgrade.py` is a script that does several
things**, because the venv can only be swapped with every app quit, and the
agent runs inside one of those apps. The user runs it alone. It checks
readiness first (`--plan`, read-only), proves the new servers before touching
anything else, and on any failure (including Ctrl-C, a killed terminal, or a
crash, via `--recover`) puts the previous venv, payload and app entries back.
It never deletes anything that existed before it started.

## Security posture

- **Read-only, by construction.** The sign-in requests exactly two scopes,
  `analytics.readonly` and `webmasters.readonly`, and the consent script
  prints what was actually granted. Nothing writes to Google.
- **Each person's own access.** There is no shared service account. A person
  sees what their Google account can already see.
- **Exports go only to approved places.** Tool arguments come from a model
  that text inside the data can steer, so a file's destination is never an
  arbitrary path: the project folder the app is working in (named by the
  app, not the model), the configured sessions folder, or folders listed in
  the machine's config. Network paths are refused before any filesystem
  call. Cells that a spreadsheet would run as formulas are neutralized.
- **Dependencies are pinned and scanned.** `constraints.txt` is an exact,
  tested set, checked against vulnerability databases before every release,
  with minimum safe versions enforced by a test. pip itself is installed by
  exact URL and checksum, so the install does not depend on the trust store
  of whatever pip a fresh venv starts with.
- **Config files stay private.** Writes to the apps' config files keep or
  tighten their permissions, refuse planted symlinks, and back up first.
- **No trace-context parsing.** The MCP library's OpenTelemetry propagation is
  switched off in both servers; nothing here exports traces.

## What is proven, and what is not

Proven by tests on every run (`tests/`, run in CI on every push; the count is whatever CI last reported, so it is not written here): the tool surface over a
real MCP handshake, the installer's refusals and backups, the export
confinement with Windows-style paths, the upgrade's rollback under failure,
Ctrl-C and a hard kill, and that every documented command matches the code.

Proven on real machines at the time of writing: full installs on macOS and
on Windows 11 (no administrator rights, Microsoft Store Claude
Desktop, Defender application control), with Claude Desktop and Claude Code
answering real questions.

**Reported working by users of this release:** Codex and the ChatGPT desktop
app on Windows 11.

**Not proven, and documented as such:** install paths containing spaces on Windows;
`upgrade.py` and the project-folder export logic on a real Windows machine.
`references/windows.md` keeps the current list.

## Where to look

| Question | File |
|---|---|
| How do I install by hand? | `INSTALL.md` |
| How does an agent install or upgrade? | `skills/data-noodler-setup/SKILL.md` |
| Windows differences, each with its measured reason | `skills/data-noodler-setup/references/windows.md` |
| Something failed | `skills/data-noodler-setup/references/troubleshooting.md` |
| How do I get my own Google sign-in? | `GOOGLE-CLOUD-SETUP.md` |
| What does the model get told about querying well? | `server/guidance.py` |
| Why is a dependency pinned at that version? | `installer/constraints.txt` header, `installer/security_floors.py` |
