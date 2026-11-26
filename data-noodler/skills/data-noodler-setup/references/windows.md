# Installing on Windows

Read this alongside SKILL.md, not instead of it. The step numbering and the
order are the same; this page says what differs and why.

Everything below was measured on real machines -- first on 2026-09-14, then
on full installs on 2026-10-05 and 2026-10-09 -- all Windows 11, no
administrator rights. Where something was
measured, it says so. Where it was not, it says that too.

## The short version

- **Python first, installed by the user.** Check that it is real, not the
  Store stub. The user runs any installer from an ordinary PowerShell window,
  never from inside the Claude app.
- **No `uv`.** Use stock `python -m venv`.
- **No launchers.** The MCP entries name the interpreter directly.
- **analytics-mcp runs as `python.exe -m analytics_mcp.server`.** Defender
  can block the pip-generated `.exe`.
- **No `.ps1`.** Execution policy blocks unsigned scripts.
- **Quit the app before registering.** On Windows this is a hard requirement,
  not prudence. If you are running inside Claude Desktop, hand that step to
  the user.

## Before Step 2: a real Python

Measured 2026-10-09: a managed machine with **no Python at all**. The only
`python.exe` was the Microsoft Store stub in `WindowsApps`, which opens the
Store instead of running anything. There was no `py`, `uv`, `pipx` or `conda`.

Check:

```powershell
Get-Command python, py -All -ErrorAction SilentlyContinue | Select-Object Source
```

If the only answer is under `...\AppData\Local\Microsoft\WindowsApps\`,
there is no Python. Anything 3.10 or later works; 3.12 is what has been
measured.

**The user installs it, not you, when you run inside Claude Desktop.** Claude
Desktop from the Microsoft Store is a packaged (MSIX) app, and its container
redirects writes under `AppData`. Measured 2026-10-09: the python.org
installer run by the agent from Desktop's Code tab exited 3. Its log shows
MSI error 2203, path not found, for a file under
`AppData\Local\Package Cache`: the container had put the file in its private
copy of that folder, and the Windows Installer service, which runs outside
the container, could not see it. The user ran the same installer from an
ordinary PowerShell window and it worked.

Tell the user to do one of these from an **ordinary PowerShell window or by
double-clicking in File Explorer**:

- **python.org installer (measured).** Download the 64-bit Windows installer
  for 3.12 and install for the current user only. "Install Now" does that
  and needs no administrator rights. The silent form that worked:
  `& "$env:USERPROFILE\Downloads\python-3.12.10-amd64.exe" /quiet InstallAllUsers=0`
- **An app catalog**, if whoever manages the machine offers Python there.
  Not measured.

Then **name the new interpreter by its full path** when creating the venv. A
per-user install goes to `%LOCALAPPDATA%\Programs\Python\Python312\`, and a
bare `python` can still resolve to the Store stub:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv "$env:USERPROFILE\.config\data-noodler\venv"
```

## Why there is no uv here

`uv` exists in the macOS path for exactly one reason: macOS ships Python
3.9.6 and `analytics-mcp` needs 3.10+. That reason does not apply to a
Windows machine with a modern Python already installed.

On the machine measured, `uv` was absent, `pipx` was absent, and software
installs needed an administrator. Python 3.12 and
`pip` were present. So:

```powershell
python -m venv "$env:USERPROFILE\.config\data-noodler\venv"
& "$env:USERPROFILE\.config\data-noodler\venv\Scripts\python.exe" -m pip install "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
& "$env:USERPROFILE\.config\data-noodler\venv\Scripts\python.exe" -m pip install -c <repo>\data-noodler\installer\constraints.txt --upgrade analytics-mcp==1.1.0 google-auth-oauthlib
```

**Why pip is installed by URL and hash, before anything else.** In October
2026 eight eMudhra/emSign intermediate certificate keys were compromised.
pip always trusts the certificate list it carries inside itself, and a new
venv starts with whatever pip the Python installer bundled -- measured: pip
25.0.1 on Python 3.12.13, which still trusts the compromised keys. So that
first pip must not be trusted to download anything, not even a newer pip.
Naming the exact wheel with its SHA-256 means a tampered download is
rejected even if the connection is intercepted. The URL and hash come from
the Python security team's advisory (discuss.python.org/t/109576) and were
checked against PyPI's own records; `installer/security_floors.py` holds
them, and a test keeps every document in step.
Never swap that line for `pip install --upgrade pip`.

## Upgrading an existing install

One command, run by the user from an ordinary PowerShell window with Claude
Desktop, every Claude Code window and Codex fully quit:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" "<package>\data-noodler\installer\upgrade.py"
```

Run `upgrade.py --plan` first (read-only) and use the `base python` it
prints if it differs. The run builds a fresh venv at the same path the same
way as above, proves both servers, re-registers, verifies, and on any failure
puts everything back; it never deletes the old venv (Step 9 offers that). Its
pre-flight lists running processes with `Get-CimInstance Win32_Process` and
refuses while any runs from the venv -- unmeasured on Windows until the first
real upgrade, so if it misses one, the venv rename fails instead and nothing
is changed. Afterwards the agent runs `copy_skills.py`. Details in SKILL.md
Step 2, "On an upgrade".

The `-c constraints.txt` is what stops the slow resolve described below. It is
data, not a program: a set of versions observed working together. It only
bounds packages that get installed, so Windows-only dependencies like pywin32
go unconstrained rather than conflicting.

`venv` is in the standard library, so this needs no administrator rights and
nothing from an app catalog.

**Measured, and worth knowing before you worry:** every binary dependency
resolved to a prebuilt `win_amd64` wheel — grpcio, cryptography, pydantic_core,
rpds-py, cffi, pywin32. Nothing compiled from source, so **no MSVC Build Tools
are required.** That would have been fatal given no admin rights.

**Also measured, and the reason for the constraints file:** the install pulled
66 packages and pip backtracked through roughly 30 versions of `google-adk`
before settling, taking several minutes and emitting "This is taking longer
than usual". It succeeds. It is slow, and two people running the identical
command can end up with different trees.

## Why there is no launcher

`bin/launch-analytics-mcp` and `bin/launch-data-noodler` are `/bin/sh` scripts that
use `/usr/bin/plutil` to read config.json. Neither exists on Windows.

They were not ported, and the alternatives were rejected for measured reasons:

- **A `.ps1` launcher** — execution policy on the machine measured is
  `RemoteSigned`, which blocks an unsigned script that arrived in a zip.
- **A `.cmd` launcher** — batch is poor at reading JSON, and quoting gets
  hazardous with real paths on that machine, e.g.
  `C:\Users\<user>\OneDrive - Example Org\Documents\...`.
- **Git Bash** — present on the machine, and a trap. It would run the existing
  `/bin/sh` launchers, so testing one there appears to work. But Claude Desktop
  spawns MCP servers **natively through Windows, not through Git Bash**, so a
  launcher that runs under Git Bash tells you nothing about whether Desktop can
  start it. Do not let a passing test in Claude Code be read as proof.

Instead the registered entry names the interpreter directly. This shape was
**observed connecting**, not designed: reconnaissance registered it through
`claude mcp add` and Claude Code reported ✓ Connected.

```json
"data-noodler": {
  "type": "stdio",
  "command": "C:\\Users\\<user>\\.config\\data-noodler\\venv\\Scripts\\python.exe",
  "args": ["C:\\Users\\<user>\\.config\\data-noodler\\server\\data_noodler.py"],
  "env": {
    "GRPC_DNS_RESOLVER": "native",
    "GOOGLE_APPLICATION_CREDENTIALS": "C:\\Users\\<user>\\.config\\gcloud\\data-noodler-credential.json"
  }
}
```

`install.py` generates this. Do not hand-write it.

## Why analytics-mcp runs as `python -m`, not as its `.exe`

`pip` writes `venv\Scripts\analytics-mcp.exe`, a small launcher it generates
on each machine. On 2026-10-09 Microsoft Defender's Attack Surface Reduction
rule `01443614-CD74-433A-B99E-2ECDC07BFC25` ("block executable files unless
they meet a prevalence, age, or trusted list criterion") refused it. A
launcher generated on one machine has, by construction, been seen on no
other machine. `verify.py` reported `PermissionError: [WinError 5] Access is
denied`, and the Defender Operational log held event 1121 naming the file.
On the 2026-10-05 machine the same `.exe` ran, so the rule varies by machine
and can arrive later with a policy update.

So `install.py` registers analytics-mcp the way data-noodler already ran:

```json
"analytics-mcp": {
  "type": "stdio",
  "command": "C:\\Users\\<user>\\.config\\data-noodler\\venv\\Scripts\\python.exe",
  "args": ["-m", "analytics_mcp.server"],
  "env": {
    "GRPC_DNS_RESOLVER": "native",
    "OTEL_PROPAGATORS": "none",
    "ANALYTICS_MCP_ALLOW_WRITE": "false",
    "GOOGLE_APPLICATION_CREDENTIALS": "..."
  }
}
```

`python.exe` is signed and widely seen, and `analytics_mcp/server.py` starts
the same server when run as a module. Do not switch the entry back to the
`.exe`, and do not delete the `.exe`: it belongs to the pip package, does
nothing while unused, and pip recreates it on the next install.

An install made before this change has the `.exe` entry. Re-running
`install.py` from a current package replaces it.

**The consequence that catches people:** with no launcher running, every
environment variable the POSIX launchers used to export must be *in the entry*
or it is never set at all. That is why `install.py` refuses to register on
Windows unless `config.json` exists — it has to read `venv_python` and
`adc_file` out of it, and guessing either produces an entry that looks correct
and a server that never starts.

## There is no shebang to read

The macOS install finds the interpreter by reading the console script's
shebang, unwrapping pip's `sh`/Python polyglot. Windows console scripts are
compiled `.exe` wrappers. Measured: `Scripts\` contained `analytics-mcp.exe`
and nothing else — no extensionless script, no `.bat`, no `.cmd`, no shebang.

What is there instead is positional: `python.exe` sits in the same `Scripts\`
directory. `bootstrap_config.py` uses that.

When it cannot, **the recourse is a flag, not an inference**:

```powershell
python bootstrap_config.py --venv-python "C:\Users\<user>\.config\data-noodler\venv\Scripts\python.exe"
```

`bootstrap_config.py` also runs one import probe against whichever interpreter
it ends up with, and refuses to write a path that cannot import the servers'
dependencies. A real executable that is the wrong one — the system Python
rather than the venv's — writes a clean config and servers that never start,
and that gets diagnosed as a credential problem. It is the most expensive
wrong turn available here.

## Quit the application before registering

On macOS this is advice. On Windows it is a requirement, for a mechanical
reason: `os.replace()` fails with a permission error when another process
holds the destination file open. Claude Desktop holds its config open.

The failure lands *after* the backup has been written. The original config
is untouched and nothing is lost, but the message will be about permissions
and the cause is the running app. (An older version could leave a
`<name>.ga-tmp` file beside the config; it is safe to delete.)

Fully quit — not just close the window — then register, then reopen.

**If you are running inside Claude Desktop** (its Code tab), quitting Desktop
ends your session. Register Claude Code yourself, then hand the Desktop
registration to the user as a block to paste into an ordinary PowerShell
window. SKILL.md Step 7 has the block. This is what happened on 2026-10-09,
and it worked: run from ordinary PowerShell, `install.py` found the Microsoft
Store config path on its own.

## Character encoding

Anything writing JSON here must write UTF-8 **without a BOM**. PowerShell
5.1's `Set-Content -Encoding UTF8` writes a BOM; measured on the machine, the
first three bytes came back `EF BB BF`. Many JSON parsers reject that.

Python's `json.dump` through this package is fine — every file it opens now
names its encoding explicitly. If you write config by hand from PowerShell,
use `[System.IO.File]::WriteAllText`, or PowerShell 7's `-Encoding utf8NoBOM`.

## Where things go

| | |
|---|---|
| Claude Desktop config | `%APPDATA%\Claude\claude_desktop_config.json`; for a Microsoft Store install, `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json`. `install.py` prints the one it used (`claude_desktop: using ...`). |
| Claude Code config | `%USERPROFILE%\.claude.json` |
| Package config | `%USERPROFILE%\.config\data-noodler\config.json` |
| Credential | `%USERPROFILE%\.config\gcloud\data-noodler-credential.json` |
| OAuth client | `%USERPROFILE%\.config\gcloud\data-noodler-client.json` — **not in the package**; get it from your maintainer directly (`deployment.json`), or make your own: `GOOGLE-CLOUD-SETUP.md` |

`~/.config/data-noodler` is not idiomatic Windows — `%LOCALAPPDATA%` would be — but
it is deliberate. data-noodler's config loader and the export denylist both
encode that path already, and one fewer divergence between platforms is worth
more than matching convention. Do not "fix" it.

Only one Claude data directory was found on the machine measured, with no
`Claude-3p` variant. The macOS ambiguity does not appear to exist there, though
the code still handles it.

## Confirmed on a real machine, 2026-10-05

The first end-to-end install, on a Windows 11 machine with no
administrator rights.

- **Claude Desktop surfaces the tools in chat.** A real GA question asked in
  Desktop chat got a real answer. This is the strongest claim available --
  stronger than `verify.py`, which proves an entry launches but cannot see a UI.
- **Claude Code** loads both servers and reports them Connected.
- **The OAuth consent flow works on a managed machine.** Browser opened,
  consent completed, both scopes granted and nothing wider.
- **The `icacls` hardening works.** The credential's ACL came out as the
  current user alone: no SYSTEM, no Administrators, no inherited entries.
- **`constraints.txt` works.** The resolve was immediate and matched the pins
  exactly, where unconstrained it had taken several minutes.

## Confirmed again, 2026-10-09, on a machine that started with no Python

- `verify.py` exit 0 in both Claude Code and Claude Desktop, with all the
  tools present.
- The 2026-10-05 Microsoft Store fix held. `install.py` found the
  `Packages\Claude_*` config with no `CLAUDE_USER_DATA_DIR`.
- Consent and the `icacls` hardening worked on a second managed machine.
- `constraints.txt` resolved quickly to prebuilt wheels.

Three things on that install needed workarounds; all are now in these docs:
Python had to be installed by the user, outside the app; the analytics-mcp
`.exe` was blocked by Defender; and the Desktop registration was handed to
the user.

## Two defects found on the first install -- fixed 2026-10-05

Both blocked the documented path and both were invisible from macOS. If your
copy of this package predates 2026-10-05, the workarounds below still apply.

- **`bootstrap_config.py` could not find a venv-local `analytics-mcp.exe`.**
  It searched only `PATH` and `~/.local/bin`, and refused before it ever read
  `--venv-python`. It now searches the venv this page creates, and
  `--venv-python` is enough on its own.
  *Old workaround:* `$env:PATH = "$env:USERPROFILE\.config\data-noodler\venv\Scripts;$env:PATH"`
- **A Microsoft Store (MSIX) Claude Desktop hid its config.** `%APPDATA%\Claude`
  resolves only *inside* the app container, so an install run from ordinary
  PowerShell said `claude_desktop: not installed, skipping` and exited 0. The
  installer now also searches the real directory,
  `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`, and refuses
  loudly instead of skipping if the app is installed but no config is found.
  *Old workaround, and still the override if detection ever misses:* set
  `CLAUDE_USER_DATA_DIR` to that directory, with Claude Desktop fully quit.

The lesson that outlasts both: **an agent running the install from inside
Claude Code would never have hit the second one** -- it inherits the app
container. A person following INSTALL.md by hand does. Test the path people
actually take, not only the one an agent takes.

## Still unproven

- **Paths containing spaces.** Everything installed so far sits under
  space-free paths, though real machines have projects under paths like
  `OneDrive - Example Org`.
- **Why Codex and the ChatGPT desktop app work on Windows.** Users of this
  release confirm both working on Windows 11. The Codex plugin starts its
  servers through `/bin/sh` (so that Codex runs them in the project folder,
  #165), which native Windows does not provide, and how that resolves on the
  machines where it works hasn't been recorded yet. If the plugin fails to
  start on your machine, that launcher is the first place to look, and an
  issue saying what you found would help.

## Credential file permissions

`mint_adc.py` creates the credential with POSIX bits (`S_IRUSR | S_IWUSR`).
On Windows those are close to meaningless: the file inherits whatever the
parent directory grants, which in a default profile includes SYSTEM and
Administrators. Profile isolation is real, so this was never a catastrophe —
but it is materially weaker than the `0600` the code appeared to promise, and
appearing to promise it was the problem.

The script now runs, on Windows only:

```
icacls <credential> /inheritance:r /grant:r %USERNAME%:F
```

That drops inherited permissions and grants the current user alone. It prints
what it did, so the outcome is visible rather than assumed.

**It never fails the mint.** By the time it runs the credential is written and
valid; refusing to report success because a hardening step did not run would
send someone back through a browser consent flow for nothing. If `icacls` is
missing, fails, or `%USERNAME%` is unset, it says so and falls back to profile
isolation.

**Confirmed on two real machines** (2026-10-05 and 2026-10-09): the ACL came
out as the current user alone. It still prints what it did, so read the line
after "Permissions:" on every run rather than assuming.
