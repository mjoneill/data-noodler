#!/usr/bin/env python3
"""Report what is true of this machine. Change nothing.

Written to replace the shell snippets the setup skill used to carry. Those
were bash -- `ls ... 2>/dev/null || command -v ...`, `if [ -f ... ]`, a
sixteen-line inline python heredoc -- and the target machine's agent runs
PowerShell. Prose that is shell is not portable prose; it is unportable code
with no tests. Every snippet an agent has to translate is a chance to
improvise, and improvisation at a wall is this package's documented failure
mode.

So: one command, the same output on every platform, stable keys to branch on.
Counter-intuitively the safest way to make a prose-driven install reliable is
MORE code, not less -- as long as the code only looks.

Read-only by construction. It opens files, runs `--version`-style probes, and
writes nothing anywhere. That is what makes it free to run before deciding
anything, and what makes it safe for an agent to run unsupervised.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import subprocess

import bootstrap_config
import harness_paths
import security_floors

GA_SERVERS = ("analytics-mcp", "data-noodler")


def _read_json(path):
    """(parsed, error). Never raises -- an unreadable config is a fact."""
    if not path or not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def probe_python():
    return {
        "running": sys.executable,
        "version": ".".join(str(n) for n in sys.version_info[:3]),
    }


def probe_analytics_mcp(platform=None, check_imports=True):
    """Where analytics-mcp is, which interpreter runs it, and whether it works.

    The interpreter question is the one that matters. A wrong answer is
    silent: the config is written, the entry looks correct, the server never
    starts, and the symptom gets diagnosed as credentials.
    """
    platform = sys.platform if platform is None else platform
    binary = bootstrap_config.detect_analytics_mcp()
    out = {"binary": binary, "interpreter": None, "interpreter_source": None,
           "imports_ok": None}
    if not binary:
        return out
    interpreter = bootstrap_config.venv_python_for(binary, platform=platform)
    out["interpreter"] = interpreter
    out["interpreter_source"] = (
        "sibling python.exe in Scripts/" if platform.startswith("win")
        else "console script shebang")
    if interpreter and check_imports:
        out["imports_ok"] = bootstrap_config.interpreter_can_run_the_servers(
            interpreter)
    return out


_VERSIONS_SCRIPT = (
    "import importlib.metadata as m, json, sys\n"
    "out = {}\n"
    "for n in sys.argv[1:]:\n"
    "    try: out[n] = m.version(n)\n"
    "    except m.PackageNotFoundError: out[n] = None\n"
    "print(json.dumps(out))\n")


def probe_dependencies(interpreter, timeout=60):
    """Installed versions of the packages with security floors, and which
    are below them.

    The venv is the one part of an install that an upgrade never touched:
    copying a new payload leaves the libraries underneath exactly as old as
    they were. On 2026-10-23 that meant PyJWT 2.13.0 (critical) and a
    certifi still trusting compromised roots on machines that had been
    "upgraded" (#152). A non-empty below_floor means refresh the venv.

    Runs the interpreter once to read package metadata; imports nothing from
    the packages themselves and writes nothing.
    """
    out = {"interpreter": interpreter, "versions": {}, "below_floor": {},
           "error": None}
    if not interpreter:
        out["error"] = "no interpreter to ask"
        return out
    names = sorted(security_floors.FLOORS)
    try:
        proc = subprocess.run([interpreter, "-c", _VERSIONS_SCRIPT, *names],
                              capture_output=True, text=True, timeout=timeout)
        versions = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if versions is None:
        out["error"] = (proc.stderr or "").strip()[-300:] or "exit %d" % proc.returncode
        return out
    out["versions"] = versions
    out["below_floor"] = {k: {"installed": v[0], "floor": v[1]} for k, v in
                          security_floors.below_floor(versions).items()}
    return out


def probe_uv(which=None, run=None):
    """uv's version against its security floor, when uv is installed.

    uv downloads packages itself, so below 0.13.4 it trusts the compromised
    eMudhra/emSign CA keys (#163). Windows installs don't use uv; there it is
    simply reported absent.
    """
    import shutil
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    path = which("uv")
    out = {"path": path, "version": None, "floor": security_floors.UV_FLOOR,
           "below_floor": None}
    if not path:
        return out
    try:
        proc = run([path, "--version"], capture_output=True, text=True,
                   timeout=20)
    except (OSError, subprocess.SubprocessError):
        return out
    words = (proc.stdout or "").split()
    if len(words) >= 2:
        out["version"] = words[1]
        out["below_floor"] = (security_floors.version_key(words[1])
                              < security_floors.version_key(
                                  security_floors.UV_FLOOR))
    return out


def probe_config(home=None):
    home = os.path.expanduser("~") if home is None else home
    path = os.path.join(home, ".config", "ga-mcp", "config.json")
    parsed, error = _read_json(path)
    out = {"path": path, "exists": os.path.exists(path), "error": error,
           "keys": sorted(parsed) if isinstance(parsed, dict) else None,
           "venv_python": None, "adc_file": None}
    if isinstance(parsed, dict):
        for key in ("venv_python", "adc_file"):
            value = parsed.get(key)
            out[key] = os.path.expanduser(value) if value else None
    return out


def probe_credential(adc_file):
    """Days remaining, without interpreting what should be done about it.

    Reuses data-noodler's own reader so the installer and the running server
    can never disagree about whether a credential is alive.
    """
    out = {"path": adc_file, "exists": bool(adc_file)
           and os.path.exists(adc_file), "days_remaining": None}
    if not out["exists"]:
        return out
    try:
        import credential
        report = credential.credential_report(adc_file, renewal_command="")
        out["days_remaining"] = report.get("days_remaining")
    except Exception as exc:                      # a probe never fails a run
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def probe_harnesses(home=None, env=None, platform=None):
    """Every config we might register into, and what is already in it."""
    out = {}
    for target, resolver in (
        ("claude_code", lambda: harness_paths.claude_code_config(
            home=home, platform=platform)),
        ("claude_desktop", lambda: harness_paths.claude_desktop_config(
            home=home, env=env, platform=platform)),
    ):
        path = resolver()
        parsed, error = _read_json(path)
        servers = {}
        if isinstance(parsed, dict) and isinstance(parsed.get("mcpServers"), dict):
            servers = parsed["mcpServers"]
        out[target] = {
            "path": path,
            "installed": path is not None,
            "config_exists": bool(path) and os.path.exists(path),
            "parses": error is None,
            "error": error,
            "ga_servers_registered": sorted(
                n for n in GA_SERVERS if n in servers),
            "other_servers": sorted(n for n in servers if n not in GA_SERVERS),
        }
    return out


def probe_payload(home=None):
    home = os.path.expanduser("~") if home is None else home
    ga_home = os.path.join(home, ".config", "ga-mcp")
    out = {"ga_home": ga_home, "directories": {}}
    for name in ("server", "bin", "marketplace"):
        d = os.path.join(ga_home, name)
        out["directories"][name] = {
            "present": os.path.isdir(d),
            "marker": os.path.exists(os.path.join(d, ".ga-mcp-payload")),
        }
    return out


def collect(home=None, env=None, platform=None, check_imports=True):
    home = os.path.expanduser("~") if home is None else home
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    config = probe_config(home=home)
    analytics_mcp = probe_analytics_mcp(platform=platform,
                                        check_imports=check_imports)
    # The interpreter the servers actually run on: config.json's, when there
    # is one, because on Windows nothing else names it reliably.
    interpreter = config.get("venv_python") or analytics_mcp["interpreter"]
    return {
        "platform": platform,
        "home": home,
        "python": probe_python(),
        "analytics_mcp": analytics_mcp,
        "dependencies": (probe_dependencies(interpreter) if check_imports
                         else {"skipped": "--skip-import-check"}),
        "uv": probe_uv(),
        "config": config,
        "credential": probe_credential(config.get("adc_file")),
        "harnesses": probe_harnesses(home=home, env=env, platform=platform),
        "payload": probe_payload(home=home),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output (the default is the same "
                         "data, indented for a person)")
    ap.add_argument("--home", default=None)
    ap.add_argument("--skip-import-check", action="store_true",
                    help="do not spawn the interpreter to test its imports")
    args = ap.parse_args()
    facts = collect(home=args.home, check_imports=not args.skip_import_check)
    print(json.dumps(facts, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
