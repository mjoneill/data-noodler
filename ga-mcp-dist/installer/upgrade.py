#!/usr/bin/env python3
"""Upgrade an existing install in one go, or put it back exactly as it was.

Why this is a script when the rest of the install is an agent following
instructions (decided 2026-10-25, #164; see docs/superpowers/BUILD-LOG.md):
the venv can only be swapped with every app that runs our servers fully
quit, and the agent always runs inside one of those apps. So this is the
one part no agent can be present for -- a transaction the user runs alone,
in a plain terminal. It is kept to exactly that, and the agent supervises
before and after:

    agent, before:  probe.py, then `upgrade.py --plan` -- a read-only
                    pre-flight that reports what it found and READY or
                    NOT READY; the agent checks it against the machine and
                    corrects discovery with flags (--base-python ...)
    user, alone:    `upgrade.py`, everything quit
    agent, after:   Codex plugin refresh, skills (copy_skills.py), Step 9
                    clean-up offers, Step 10 report

What the run does:
    0. Re-runs the pre-flight and refuses unless READY. Nothing changed.
    1. Renames the venv to <venv>.old-<stamp>.
    2. Builds a fresh venv at the SAME path: pip by exact URL and sha256
       (eMudhra/emSign, #163), then the pins from constraints.txt.
    3. Proves it before touching anything else: imports, and both servers
       from THIS package answering with the right tool counts.
    4. Copies the payload and registers the Claude apps present
       (install.py).
    5. Verifies the shared part every app runs -- both servers started the
       way the apps start them -- whatever apps the machine has, then each
       registered Claude config.
    6. Any failure: removes only what this run built and renames the
       originals back.

It never deletes anything that existed before it started. The old venv is
left where it is and its path printed; the agent offers to delete it, and
only the user's yes removes it.

Run it with the BASE Python (the one the venv was made from), never the
venv's own -- that venv is what gets replaced:

    <base python> <package>/installer/upgrade.py --plan    (read-only)
    <base python> <package>/installer/upgrade.py

Standard library only. Commands go through run(), which tests replace.
"""

import argparse
import datetime
import errno
import glob
import json
import ntpath
import os
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import safe_write  # noqa: E402
import security_floors  # noqa: E402

PAYLOAD = ("companion", "bin", "marketplace")
ANALYTICS_MCP = "analytics-mcp==1.1.0"
TOOL_COUNTS = {"analytics-mcp": 9, "ga-companion": 15}
# Tool-manager bookkeeping a rebuilt venv should keep, so `uv tool list` or
# `pipx list` still recognise it.
TOOL_RECEIPTS = ("uv-receipt.toml", "pipx_metadata.json")


class UpgradeError(Exception):
    """Raised with a message intended to be read by a user."""

    def __init__(self, message, nothing_changed=False):
        super().__init__(message)
        self.nothing_changed = nothing_changed


def run(cmd, env=None):
    """Run a command; (returncode, combined output). Tests replace this."""
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def venv_dir_for(venv_python):
    """<venv> from <venv>/bin/python or <venv>\\Scripts\\python.exe."""
    return os.path.dirname(os.path.dirname(os.path.abspath(venv_python)))


def base_python_for(venv_dir, platform=None):
    """The interpreter the venv was created from, per its pyvenv.cfg."""
    platform = sys.platform if platform is None else platform
    cfg = os.path.join(venv_dir, "pyvenv.cfg")
    try:
        with open(cfg, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    home = version = None
    for line in lines:
        key, _, value = line.partition("=")
        key = key.strip().lower()
        if key == "home":
            home = value.strip()
        elif key in ("version_info", "version") and not version:
            version = value.strip()
    if not home:
        return None
    if platform.startswith("win"):
        names = ("python.exe",)
    else:
        # Homebrew's bin holds only python3.14, not python3.
        minor = ".".join((version or "").split(".")[:2])
        names = (("python" + minor,) if minor else ()) + ("python3", "python")
    for name in names:
        candidate = os.path.join(home, name)
        if os.path.exists(candidate):
            return candidate
    return None


class Plan:
    def __init__(self, repo_root, ga_home, config_path, venv_python,
                 base_python, targets, platform, stamp):
        self.repo_root = repo_root
        self.dist = os.path.join(repo_root, "ga-mcp-dist")
        self.ga_home = ga_home
        self.config_path = config_path
        self.venv_python = venv_python
        self.venv_dir = venv_dir_for(venv_python)
        # Kept under ga_home, not beside the venv: for a pipx- or uv-managed
        # venv the sibling folder is the tool manager's own, and `pipx list`
        # would show the kept copy as a phantom package (code review #7).
        # A venv that already lives in ga_home gets the same sibling as
        # before. Same filesystem in every layout seen; a cross-device
        # rename falls back to the sibling (rebuild_venv).
        self.old_venv = os.path.join(
            ga_home, f"{os.path.basename(self.venv_dir)}.old-{stamp}")
        self.base_python = base_python
        self.targets = targets
        self.platform = platform
        self.stamp = stamp
        self.constraints = os.path.join(self.dist, "installer",
                                        "constraints.txt")


def make_plan(repo_root=None, ga_home=None, config_path=None,
              base_python=None, targets="claude_code,claude_desktop",
              platform=None, now=None):
    platform = sys.platform if platform is None else platform
    repo_root = repo_root or os.path.dirname(os.path.dirname(HERE))
    ga_home = os.path.normpath(os.path.expanduser(
        ga_home or "~/.config/ga-mcp"))
    config_path = config_path or os.path.join(ga_home, "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as exc:
        raise UpgradeError(
            f"Could not read {config_path} ({exc}). This upgrades an existing "
            "install; for a new one, follow the ga-mcp-setup skill.")
    venv_python = os.path.expanduser(cfg.get("venv_python") or "")
    if not venv_python or not os.path.exists(venv_python):
        raise UpgradeError(
            f"config.json names no usable venv_python ({venv_python!r}).")
    venv_dir = venv_dir_for(venv_python)
    if not os.path.exists(os.path.join(venv_dir, "pyvenv.cfg")):
        raise UpgradeError(
            f"{venv_dir} is not a virtual environment (no pyvenv.cfg). "
            "Refusing to rebuild something this did not create.")
    base = base_python or base_python_for(venv_dir, platform)
    if not base:
        raise UpgradeError(
            f"Could not tell which Python {venv_dir} was made from. Pass "
            "--base-python with that interpreter's full path.")
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return Plan(repo_root, ga_home, config_path, venv_python, base,
                [t.strip() for t in targets.split(",") if t.strip()],
                platform, stamp)


def running_servers(venv_dir, ga_home, platform, run_ps=None):
    """Command lines of processes running from this venv or payload.

    Every app that hosts our servers must be fully quit before the swap.
    On Windows a running one makes the rename fail; on macOS nothing stops
    the rename, but the app keeps old code and Claude Code rewrites
    ~/.claude.json underneath the upgrade.
    """
    if run_ps is None:
        if platform.startswith("win"):
            cmd = ["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_Process | "
                   "ForEach-Object { $_.CommandLine }"]
        else:
            cmd = ["ps", "-axww", "-o", "command="]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None  # unknown -- reported as such
        # A lister that failed (PowerShell in Constrained Language mode,
        # Get-CimInstance blocked by policy) printed nothing; that is
        # "unknown", not "nothing is running" (code review #5).
        if proc.returncode != 0:
            return None
        text = proc.stdout or ""
    else:
        text = run_ps()
        if text is None:
            return None
    # Each needle ends in a separator, so .../venvs/analytics-mcp does not
    # match .../venvs/analytics-mcp-dev or a kept analytics-mcp.old-<stamp>
    # (code review #8). Either separator: Windows command lines use both.
    roots = [venv_dir, os.path.join(ga_home, "bin"),
             os.path.join(ga_home, "companion")]
    # Also the venv path itself followed by a quote, a space or the end of
    # the line: `python -m venv <venv_dir>` names it with no separator after
    # it (code review round 4).
    ends = ("/", "\\", '"', "'", " ")
    needles = [r.rstrip("/\\") + e for r in roots for e in ends]
    bare = [r.rstrip("/\\") for r in roots]
    fold = (lambda x: x.casefold()) if platform.startswith("win") else str
    hits = []
    for line in text.splitlines():
        folded = fold(line.rstrip())
        if "upgrade.py" in line:
            continue
        if any(fold(n) in folded for n in needles) or \
                any(folded.endswith(fold(b)) for b in bare):
            hits.append(line.strip()[:160])
    return hits


def preflight(plan, config_paths, running=None):
    """[(ok, label, detail)], ready. ok is True, False, or None (info)."""
    checks = []

    def add(ok, label, detail):
        checks.append((ok, label, detail))

    add(True, "venv", f"{plan.venv_dir} (a virtual environment)")

    base = plan.base_python
    version = ""
    if "WindowsApps" in base:
        add(False, "base python", f"{base} is the Microsoft Store stub, not "
            "a real Python. Pass --base-python with a real one.")
    else:
        rc, out = run([base, "-c", "import sys; print('%d.%d' % "
                       "sys.version_info[:2])"])
        version = out.strip().splitlines()[-1] if rc == 0 and out.strip() \
            else ""
        try:
            ok = tuple(int(x) for x in version.split(".")) >= (3, 10)
        except ValueError:
            ok = False
        add(ok, "base python",
            f"{base} (Python {version})" if ok else
            f"{base} did not run as Python 3.10 or later ({out.strip()[-200:]}). "
            "Pass --base-python with the right interpreter.")

    # A fresh venv has python / python3 (Scripts\\python.exe on Windows)
    # whatever the version, but a version-named interpreter only for its own
    # minor version. config.json's venv_python must survive the rebuild,
    # because config.json is not rewritten (code review #2).
    pathmod = ntpath if plan.platform.startswith("win") else os.path
    name = pathmod.basename(plan.venv_python).lower()
    if plan.platform.startswith("win"):
        # A Windows venv has python.exe and pythonw.exe -- no python3.exe.
        always = ("python.exe", "pythonw.exe")
    else:
        always = ("python", "python3")
    if name not in always:
        wanted = name[len("python"):] if name.startswith("python") else name
        if plan.platform.startswith("win") or not version or wanted != version:
            add(False, "interpreter", f"config.json names {plan.venv_python}, "
                f"which a venv built from Python {version or '?'} will not "
                "have. Use the matching --base-python, or point venv_python "
                "at <venv>/bin/python first.")

    missing = [p for p in [plan.constraints] + [
        os.path.join(plan.dist, n) for n in PAYLOAD] if not os.path.exists(p)]
    add(not missing, "package", f"{plan.dist}" if not missing else
        "missing: " + ", ".join(missing))

    for path in config_paths:
        add(None, "Claude config", f"{path} (will be re-registered and "
            "verified)")
    if not config_paths:
        add(None, "Claude config", "none found -- the shared servers are "
            "still verified")
    codex = shutil.which("codex")
    add(None, "Codex", f"installed ({codex}) -- refresh its plugin after"
        if codex else "not installed")

    hits = (running_servers(plan.venv_dir, plan.ga_home, plan.platform)
            if running is None else running)
    if hits is None:
        add(None, "apps quit", "could not list processes; make sure every "
            "app is fully quit")
    elif hits:
        add(False, "apps quit", f"{len(hits)} process(es) are running our "
            "servers -- fully quit Claude Desktop, every Claude Code window, "
            "Codex and the ChatGPT app first: " + " | ".join(hits[:3]))
    else:
        add(True, "apps quit", "nothing is running from the venv or payload")

    if load_state(plan.ga_home) is not None:
        add(False, "unfinished", "an earlier upgrade did not finish undoing "
            f"itself: run {_recover_command(plan.ga_home)} first")

    ready = all(ok is not False for ok, _, _ in checks)
    return checks, ready


def _check(step, rc_out):
    rc, out = rc_out
    if rc != 0:
        raise UpgradeError(f"{step} failed:\n{out.strip()[-1500:]}")
    return out


def rebuild_venv(plan, log):
    log(f"Moving {plan.venv_dir} aside to {plan.old_venv}")
    try:
        os.rename(plan.venv_dir, plan.old_venv)
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.EXDEV:
            # ga_home on another volume: keep it beside the venv instead.
            plan.old_venv = f"{plan.venv_dir}.old-{plan.stamp}"
            log(f"  (another volume; keeping it at {plan.old_venv})")
            try:
                os.rename(plan.venv_dir, plan.old_venv)
                exc = None
            except OSError as again:
                exc = again
        if exc is not None:
            raise UpgradeError(
                f"Could not move {plan.venv_dir} aside ({exc}). Something is "
                "still using it: fully quit Claude Desktop, every Claude Code "
                "window, Codex and the ChatGPT app, then run this again. "
                "Nothing was changed.", nothing_changed=True) from None
    py = plan.venv_python
    log("Creating a fresh venv")
    _check("Creating the venv", run([plan.base_python, "-m", "venv",
                                     plan.venv_dir]))
    if not os.path.exists(py):
        # config.json names an interpreter the new venv does not have
        # (a version-named one, and a different base version). Caught here
        # as an UpgradeError so the rollback runs (code review #2).
        raise UpgradeError(
            f"The new venv has no {py}, which config.json names. Re-run "
            "with the --base-python of the same Python version.")
    log("Installing pip by URL and sha256")
    _check("Installing pip",
           run([py, "-m", "pip", "install", "--disable-pip-version-check",
                security_floors.PIP_BOOTSTRAP_REQUIREMENT]))
    log("Installing the pinned packages")
    _check("Installing packages",
           run([py, "-m", "pip", "install", "--disable-pip-version-check",
                "-c", plan.constraints, ANALYTICS_MCP,
                "google-auth-oauthlib"]))
    for name in TOOL_RECEIPTS:
        src = os.path.join(plan.old_venv, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(plan.venv_dir, name))


def prove_venv(plan, log):
    """Import probe and both servers from THIS package, before any install."""
    import bootstrap_config
    log("Checking the new venv imports what the servers need")
    _check("Import check", run([plan.venv_python, "-c",
                                bootstrap_config.IMPORT_PROBE]))
    companion = os.path.join(plan.dist, "companion", "ga_companion.py")
    code = (
        "import json, os, sys\n"
        f"sys.path.insert(0, {os.path.join(plan.dist, 'installer')!r})\n"
        "import verify\n"
        "env = dict(os.environ, GRPC_DNS_RESOLVER='native',"
        " OTEL_PROPAGATORS='none', ANALYTICS_MCP_ALLOW_WRITE='false',"
        " GA_MCP_CONFIG=sys.argv[1])\n"
        "out = {}\n"
        "for name, args in (('analytics-mcp', ['-m', 'analytics_mcp.server']),"
        " ('ga-companion', [sys.argv[2]])):\n"
        "    r = verify.probe(sys.executable, args, env)\n"
        "    out[name] = len(r['tools']) if r['ok'] else r['error']\n"
        "print(json.dumps(out))\n")
    log("Starting both servers from the new package")
    out = _check("Server check", run([plan.venv_python, "-c", code,
                                      plan.config_path, companion]))
    # stdout and stderr arrive together; the servers log to stderr, so take
    # the one line that is the JSON result.
    counts = None
    for line in reversed(out.splitlines()):
        if line.startswith("{"):
            try:
                counts = json.loads(line)
                break
            except ValueError:
                pass
    if counts is None:
        raise UpgradeError(f"Server check printed nothing usable:\n{out}")
    if counts != TOOL_COUNTS:
        raise UpgradeError(f"Server check: expected {TOOL_COUNTS}, got "
                           f"{counts}.")


def install_and_register(plan, log):
    log("Copying the payload and registering")
    _check("install.py", run([plan.venv_python,
                              os.path.join(plan.dist, "installer",
                                           "install.py"),
                              "--repo-root", plan.repo_root,
                              "--ga-home", plan.ga_home,
                              "--targets", ",".join(plan.targets)],
                             env=dict(os.environ,
                                      GA_MCP_CONFIG=plan.config_path)))


def _verify(plan, config_path, step, names=None):
    """verify.py with every --require; --name only for a shared config.

    One builder for both callers, so a change to verify.py's flags is made
    once (code review #10). names: a config also holds the user's other MCP
    servers, and one of those being broken is not a reason to undo an
    upgrade (found by the upgrade rehearsal test).
    """
    args = [plan.venv_python, os.path.join(plan.dist, "installer", "verify.py"),
            "--config", config_path]
    for name, count in TOOL_COUNTS.items():
        if names:
            args += ["--name", name]
        args += ["--require", f"{name}={count}"]
    _check(step, run(args))


def verify_shared(plan, log):
    """Both servers, started exactly the way the apps start them.

    Independent of which apps the machine has: a ChatGPT/Codex-only machine
    has no Claude config to verify, and used to get "Upgrade complete" on
    the strength of nothing. Codex runs the same launchers (macOS) and the
    same entry shape (Windows) as these.
    """
    import register
    try:
        with open(plan.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as exc:
        raise UpgradeError(f"Could not read {plan.config_path} ({exc}).")
    entries = register.server_entries(
        plan.ga_home, platform=plan.platform, venv_python=plan.venv_python,
        adc_file=os.path.expanduser(cfg.get("adc_file") or ""))
    for entry in entries.values():
        entry.setdefault("env", {})["GA_HOME"] = plan.ga_home
    d = tempfile.mkdtemp(prefix="ga-mcp-verify-")
    path = os.path.join(d, "entries.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": entries}, f)
        log("Verifying both servers as the apps start them")
        _verify(plan, path, "Verifying the installed servers")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def verify_registered(plan, log, config_paths):
    for path in config_paths:
        log(f"Verifying {path}")
        _verify(plan, path, f"verify.py on {path}", names=True)


OUR_SERVERS = ("analytics-mcp", "ga-companion")
STATE_FILE = ".upgrade-in-progress.json"


class UpgradeTerminated(BaseException):
    """SIGTERM/SIGHUP during the run: undo, like Ctrl-C."""


def _state_path(ga_home):
    return os.path.join(ga_home, STATE_FILE)


def save_state(state):
    """Record what the undo needs, so --recover can finish it after a crash.

    The rollback runs in-process for anything Python can catch; a killed
    process (SIGKILL, power loss) cannot run it, so the facts it needs are
    on disk from the first change onwards (code review round 2).
    """
    safe_write.write_atomically(_state_path(state["ga_home"]),
                                json.dumps(state, indent=2) + "\n")


def load_state(ga_home):
    try:
        with open(_state_path(ga_home), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _clear_state(ga_home):
    try:
        os.unlink(_state_path(ga_home))  # this run's own file
    except OSError:
        pass


def _read_entries(path):
    """{name: entry or None} for our two servers in a config, if readable."""
    try:
        with open(path, encoding="utf-8") as f:
            servers = (json.load(f) or {}).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        servers = {}
    return {name: servers.get(name) for name in OUR_SERVERS}


def new_state(plan, candidate_configs):
    import install
    # Resolved exactly as install.py resolves it, from the same config that
    # install_and_register points it at (code review round 4).
    sessions_root = install.resolve_sessions_root(plan.repo_root,
                                                  plan.config_path)
    return {
        "stamp": plan.stamp, "ga_home": plan.ga_home, "pid": os.getpid(),
        "venv_dir": plan.venv_dir,
        # Both places the old venv can be moved to are recorded up front: the
        # cross-device fallback used to update the record only after the
        # rebuild, so a failure inside the rebuild looked in the wrong place
        # and reported a restore that had not happened (code review round 3).
        "old_venv_candidates": [plan.old_venv,
                                f"{plan.venv_dir}.old-{plan.stamp}"],
        "stage": "starting",
        "payload": {name: {
            "existed": os.path.exists(os.path.join(plan.ga_home, name)),
            "backups_before": sorted(glob.glob(
                os.path.join(plan.ga_home, name) + ".ga-old-*"))}
            for name in PAYLOAD},
        "sessions_root": {"path": sessions_root,
                          "existed": os.path.exists(sessions_root)},
        # Only OUR entries are recorded and put back: a config holds the
        # app's own state too, and writing back a whole stale copy would
        # throw away anything the app saved meanwhile (code review round 2).
        "configs": {path: {"existed": os.path.exists(path),
                           "entries": _read_entries(path)}
                    for path in candidate_configs},
    }


def _never_raising(log):
    """A log that cannot break the undo: a closed terminal (SIGHUP) makes
    every write raise, and that used to abort the remaining steps."""
    def safe(message):
        try:
            log(message)
        except BaseException:  # noqa: BLE001 -- the undo must go on
            pass
    return safe


def _set_signals(names, handler):
    """Point each named signal (that exists here) at handler; return the
    previous handlers, for _restore_signals."""
    previous = {}
    for name in names:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                previous[sig] = signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
    return previous


def _ignore_signals():
    """Ignore Ctrl-C, SIGTERM and SIGHUP; return what to put back."""
    return _set_signals(("SIGINT", "SIGTERM", "SIGHUP"), signal.SIG_IGN)


def _restore_signals(previous):
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _remove_created(path, stamp, log):
    """Remove something THIS run created. Never raises; problem or None."""
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.lexists(path):
        return None
    aside = f"{path}.failed-{stamp}"
    try:
        os.rename(path, aside)
        log(f"  (could not delete everything in {path}; moved it to {aside} "
            "-- safe to delete later)")
        return None
    except OSError as exc:
        return f"{path} could not be removed or moved aside ({exc})."


def _move_aside_then_restore(target, original, stamp, log):
    """Remove `target` (built by this run) and rename `original` into place.

    Never raises. A partial delete (a locked file on Windows) used to leave
    `target` in the way so the rename back crashed inside the error handler
    (code review #3); now `target` is moved aside if it cannot be deleted.
    """
    if os.path.lexists(target):
        problem = _remove_created(target, stamp, log)
        if problem:
            return (f"{problem} Then rename {original} to {target} by hand "
                    "once nothing is using it.")
    try:
        os.rename(original, target)
    except OSError as exc:
        return (f"Could not rename {original} back to {target} ({exc}). Do "
                "that by hand once nothing is using it.")
    return None


def _restore_config(path, info, stamp, log):
    """Put our two entries back as they were; touch nothing else.

    (kind, message) or None. kind "warning" is reported but does not keep
    the undo record: re-running cannot change it, and a record that can
    never clear would block every later upgrade (code review round 3).
    """
    if not os.path.exists(path):
        if info.get("existed") and any((info.get("entries") or {}).values()):
            return ("warning", f"{path} has disappeared since the upgrade "
                    "started, so our earlier entries could not be put back "
                    "in it. Re-register with the old package's install.py, "
                    "or ask the maintainer.")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        # Retryable: a Windows sharing violation, or a half-written file,
        # can clear -- so this keeps the record for --recover rather than
        # reporting a restore that did not happen (code review round 4).
        return ("problem", f"Could not read {path} to restore our entries "
                f"({exc}). If it stays unreadable, fix or move it, then run "
                "--recover again.")
    if not isinstance(data, dict):
        return ("warning", f"{path} is not a JSON object; left as it is.")
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    before = info.get("entries") or {}
    changed = False
    for name in OUR_SERVERS:
        old = before.get(name)
        if old is None and name in servers:
            del servers[name]
            changed = True
        elif old is not None and servers.get(name) != old:
            servers[name] = old
            changed = True
    if not changed:
        return None
    if not info.get("existed") and not servers and set(data) <= {"mcpServers"}:
        # The run created this file and it now holds nothing else.
        try:
            os.unlink(path)
            log(f"Removed {path} (created by this run)")
            return None
        except OSError as exc:
            return ("problem", f"Could not remove {path}, which this run "
                    f"created ({exc}).")
    data["mcpServers"] = servers
    try:
        # private=True: never loosen a config back to 0644 (#157).
        safe_write.write_atomically(path, json.dumps(data, indent=2) + "\n",
                                    private=True)
    except safe_write.SafeWriteError as exc:
        return ("problem", str(exc))
    log(f"Restored our entries in {path}")
    return None


def restore(state, log):
    """Undo a run from its recorded state. Never raises.

    Returns (problems, warnings). Problems keep the undo record so
    --recover can retry; warnings cannot be fixed by retrying. Every step is
    attempted on its own -- one failing step used to skip the rest -- and
    Ctrl-C/SIGTERM/SIGHUP are ignored throughout (code review rounds 2-3).
    """
    log = _never_raising(log)
    previous = _ignore_signals()
    problems, warnings = [], []
    broken_venv = False

    def attempt(label, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    try:
        stamp, ga_home = state["stamp"], state["ga_home"]
        venv_dir = state["venv_dir"]
        candidates = state.get("old_venv_candidates") or [state.get("old_venv")]

        def do_venv():
            nonlocal broken_venv
            for old in candidates:
                if old and os.path.lexists(old):
                    problem = _move_aside_then_restore(venv_dir, old, stamp,
                                                       log)
                    if problem:
                        broken_venv = True
                        problems.append(problem)
                    else:
                        log(f"Restored {venv_dir}")
                    return
        attempt("Restoring the venv", do_venv)

        for name, info in state["payload"].items():
            def do_payload(name=name, info=info):
                dest = os.path.join(ga_home, name)
                # install.py's own staging, left by a run killed mid-copy.
                if os.path.lexists(dest + ".ga-new"):
                    problem = _remove_created(dest + ".ga-new", stamp, log)
                    if problem:
                        problems.append(problem)
                now = set(glob.glob(dest + ".ga-old-*"))
                mine = sorted(now - set(info.get("backups_before") or []))
                if mine:
                    problem = _move_aside_then_restore(dest, mine[-1], stamp,
                                                       log)
                    if problem:
                        problems.append(problem)
                    else:
                        log(f"Restored {dest}")
                elif not info.get("existed") and os.path.lexists(dest):
                    problem = _remove_created(dest, stamp, log)
                    if problem:
                        problems.append(problem)
                    else:
                        log(f"Removed {dest} (created by this run)")
            attempt(f"Restoring {name}", do_payload)

        def do_sessions_root():
            info = state.get("sessions_root") or {}
            path = info.get("path")
            if path and not info.get("existed") and os.path.isdir(path) \
                    and not os.listdir(path):
                os.rmdir(path)  # empty, and created by this run
                log(f"Removed {path} (created by this run, still empty)")
        attempt("Removing the sessions folder", do_sessions_root)

        if state.get("stage") in ("installing", "verifying"):
            for path, info in state["configs"].items():
                def do_config(path=path, info=info):
                    result = _restore_config(path, info, stamp, log)
                    if result:
                        (problems if result[0] == "problem"
                         else warnings).append(result[1])
                attempt(f"Restoring {path}", do_config)

        if broken_venv:
            problems.insert(0, "YOUR APPS WILL NOT START until the venv step "
                            "below is done -- the configs point at that "
                            "venv path.")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"The undo itself failed: {type(exc).__name__}: {exc}")
    finally:
        _restore_signals(previous)
    return problems, warnings


def _recover_command(ga_home):
    default = os.path.normpath(os.path.expanduser("~/.config/ga-mcp"))
    return ("`upgrade.py --recover`" if os.path.normpath(ga_home) == default
            else f"`upgrade.py --recover --ga-home \"{ga_home}\"`")


def _report_restore(result, ga_home, log):
    problems, warnings = result
    log = _never_raising(log)
    for warning in warnings:
        log(f"  note: {warning}")
    if problems:
        log("\nMOST of it was put back, but not all of it:")
        for problem in problems:
            log(f"  - {problem}")
        log(f"Once that is sorted, run {_recover_command(ga_home)} to finish "
            "the undo, then send this whole output to the maintainer.")
    else:
        _clear_state(ga_home)
        log("Restored: the previous venv, payload and our app entries are "
            "back in place" + (" (see the notes above)." if warnings else ".")
            + " Send the message above to the maintainer.")


def _raise_terminated(signum, frame):
    raise UpgradeTerminated(signum)


def upgrade(plan, config_paths, log=print, running=None,
            candidate_configs=None):
    """Run the whole upgrade. Returns True on success; restores on failure.

    config_paths: Claude configs that exist now (pre-flight, verify).
    candidate_configs: every config path install.py may write, existing or
    not, so a config the run creates can be undone too.
    """
    checks, ready = preflight(plan, config_paths, running=running)
    if not ready:
        log("NOT READY -- nothing was changed:")
        for ok, label, detail in checks:
            if ok is False:
                log(f"  - {label}: {detail}")
        return False

    state = new_state(plan, list(dict.fromkeys(
        list(candidate_configs or []) + list(config_paths))))
    # The process's original handlers, put back at the very end on every
    # path -- not _raise_terminated, which a SIGTERM landing after the undo
    # finished would otherwise turn into a traceback (code review round 4).
    originals = _set_signals(("SIGTERM", "SIGHUP"), _raise_terminated)
    originals.update(_set_signals(("SIGINT",), signal.getsignal(signal.SIGINT)))
    try:
        save_state(state)
        rebuild_venv(plan, log)
        state["stage"] = "proving"
        save_state(state)
        prove_venv(plan, log)
        state["stage"] = "installing"
        save_state(state)
        install_and_register(plan, log)
        state["stage"] = "verifying"
        save_state(state)
        verify_shared(plan, log)
        verify_registered(plan, log, [p for p in state["configs"]
                                      if os.path.exists(p)])
    except BaseException as exc:  # noqa: BLE001
        # First, before anything else can be interrupted: a second Ctrl-C
        # landing here used to escape before the undo began (round 3).
        # The originals come back in the outer finally, after the undo.
        _ignore_signals()
        # Anything at all, once the venv has moved: our errors, a missing
        # interpreter (FileNotFoundError), a failed copy, Ctrl-C, SIGTERM.
        quiet = _never_raising(log)
        if isinstance(exc, UpgradeError):
            quiet(f"\nUPGRADE FAILED: {exc}\n")
            if exc.nothing_changed:
                _clear_state(plan.ga_home)
                return False
        elif isinstance(exc, (KeyboardInterrupt, UpgradeTerminated)):
            quiet("\nUPGRADE INTERRUPTED.\n")
        else:
            quiet(f"\nUPGRADE FAILED: {type(exc).__name__}: {exc}\n")
        quiet("Putting everything back as it was...")
        _report_restore(restore(state, log), plan.ga_home, log)
        return False
    finally:
        _restore_signals(originals)

    _clear_state(plan.ga_home)
    # config.json is not rewritten by an upgrade, so make it private here --
    # earlier versions created it 0644 (#157).
    if os.name != "nt":
        try:
            mode = os.stat(plan.config_path).st_mode & 0o777
            if mode & 0o077:
                os.chmod(plan.config_path, (mode & 0o700) | 0o600)
        except OSError:
            pass
    verified = [p for p in state["configs"] if os.path.exists(p)]
    log("\nUpgrade complete: both servers verified as the apps start them"
        + (", and in every registered Claude app." if verified else "."))
    log(f"The previous venv is still at {plan.old_venv}. Nothing uses it; "
        "it is only the undo. Your agent will offer to delete it.")
    log("Now reopen your apps and tell your agent the upgrade finished -- "
        "it refreshes the Codex plugin and the Claude Code skills next.")
    return True


def _upgrade_still_running(pid, platform, run_query=None):
    """Whether process `pid` is an upgrade.py run. True, False, or None.

    Checks the process's command line, not merely that the pid is alive: a
    pid recorded before a crash or reboot can belong to something unrelated
    later, and refusing on that would block --recover forever (code review
    round 4). Works on Windows too, where os.kill(pid, 0) is not a probe.
    """
    if not pid:
        return False
    if run_query is None:
        if platform.startswith("win"):
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"(Get-CimInstance Win32_Process -Filter "
                   f"'ProcessId={int(pid)}').CommandLine"]
        else:
            cmd = ["ps", "-p", str(int(pid)), "-o", "command="]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if not platform.startswith("win") and proc.returncode != 0:
            return False  # ps: no such process
        if platform.startswith("win") and proc.returncode != 0:
            return None
        line = proc.stdout or ""
    else:
        line = run_query(pid)
        if line is None:
            return None
    return "upgrade.py" in line


def recover(ga_home, log=print, running=None, platform=None,
            run_query=None):
    """Finish undoing an upgrade that was killed or could not undo itself."""
    platform = sys.platform if platform is None else platform
    state = load_state(ga_home)
    if state is None:
        log(f"Nothing to recover: no unfinished upgrade is recorded in "
            f"{ga_home}. If the upgrade ran with --ga-home, pass the same "
            "--ga-home here.")
        return True
    pid = state.get("pid")
    if pid != os.getpid():
        alive = _upgrade_still_running(pid, platform, run_query)
        if alive:
            log(f"NOT NOW: the upgrade that wrote this record (process {pid}) "
                "is still running. Let it finish, or stop it, first. Nothing "
                "was changed.")
            return False
        if alive is None:
            log(f"(Could not tell whether process {pid} is still the upgrade "
                "-- make sure no other upgrade window is open.)")
    hits = (running_servers(state["venv_dir"], ga_home, platform)
            if running is None else running)
    if hits:
        log("NOT NOW: our servers are still running from the venv or "
            "payload. Fully quit Claude Desktop, every Claude Code window, "
            "Codex and the ChatGPT app, then run this again. Nothing was "
            "changed:")
        for hit in hits[:3]:
            log(f"  {hit}")
        return False
    if hits is None:
        log("(Could not list processes -- make sure every app is fully quit.)")
    log(f"Undoing the unfinished upgrade from {state.get('stamp')}...")
    result = restore(state, log)
    _report_restore(result, ga_home, log)
    return not result[0]


def forget(ga_home, log=print):
    """Drop the undo record once the user has sorted the rest by hand.

    The explicit way out when --recover cannot finish -- for example a
    config that stays unreadable -- and nothing else: it changes no venv,
    payload or config. Run verify.py afterwards.
    """
    state = load_state(ga_home)
    if state is None:
        log(f"No unfinished upgrade is recorded in {ga_home}.")
        return True
    log(f"Forgetting the unfinished upgrade from {state.get('stamp')}. It "
        "recorded:")
    log(f"  venv: {state.get('venv_dir')} (old copy at one of "
        f"{', '.join(state.get('old_venv_candidates') or [])})")
    for path in state.get("configs") or {}:
        log(f"  config: {path}")
    _clear_state(ga_home)
    log("Record removed. Nothing else was changed. Run verify.py on each "
        "app's config before reopening the apps.")
    return True


def candidate_config_paths(targets, platform=None):
    """Every config path install.py could write for these targets."""
    import install
    paths = []
    for target in targets:
        try:
            path = install.config_path_for(target, platform=platform)
        except install.InstallError:
            continue
        if path:
            paths.append(path)
    return paths


def registered_configs(targets, platform=None):
    """The candidate configs that exist now."""
    return [p for p in candidate_config_paths(targets, platform)
            if os.path.exists(p)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--repo-root", default=None,
                    help="the unpacked package's folder (default: this one)")
    ap.add_argument("--ga-home", default=None)
    ap.add_argument("--base-python", default=None,
                    help="the Python the venv was made from (default: read "
                         "from its pyvenv.cfg)")
    ap.add_argument("--targets", default="claude_code,claude_desktop")
    ap.add_argument("--plan", action="store_true",
                    help="read-only pre-flight: report what was found and "
                         "READY / NOT READY; change nothing")
    ap.add_argument("--recover", action="store_true",
                    help="finish undoing an upgrade that was killed or could "
                         "not undo itself")
    ap.add_argument("--forget", action="store_true",
                    help="only when --recover cannot finish and you have "
                         "sorted the rest by hand: drop the undo record")
    args = ap.parse_args()
    if args.recover or args.forget:
        ga_home = os.path.normpath(os.path.expanduser(
            args.ga_home or "~/.config/ga-mcp"))
        if args.forget:
            return 0 if forget(ga_home) else 1
        return 0 if recover(ga_home) else 1
    try:
        plan = make_plan(repo_root=args.repo_root, ga_home=args.ga_home,
                         base_python=args.base_python, targets=args.targets)
    except UpgradeError as exc:
        print(f"NOT READY: {exc}")
        return 1
    configs = registered_configs(plan.targets)
    if args.plan:
        checks, ready = preflight(plan, configs)
        marks = {True: "ok  ", False: "FIX ", None: "info"}
        for ok, label, detail in checks:
            print(f"{marks[ok]} {label:<13} {detail}")
        print(f"\nWould rebuild {plan.venv_dir}, keeping the old one at "
              f"{plan.old_venv}.")
        if ready:
            print("READY")
            return 0
        only_running = all(ok is not False or label == "apps quit"
                           for ok, label, _ in checks)
        print("READY once every app is quit" if only_running else
              "NOT READY -- fix the items marked FIX first")
        return 0 if only_running else 1
    return 0 if upgrade(plan, configs, candidate_configs=
                        candidate_config_paths(plan.targets)) else 1


if __name__ == "__main__":
    sys.exit(main())
