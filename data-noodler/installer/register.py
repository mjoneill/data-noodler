"""Write MCP server entries into each harness's configuration.

Codex is deliberately absent here: `codex plugin marketplace add` and
`codex plugin add` write ~/.codex/config.toml themselves, and that file holds
trust levels for every project the user has opened plus live plugin state.
Delegating to the CLI removes the riskiest write in this system.
"""

import datetime
import json
import ntpath
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safe_write  # noqa: E402

GRPC_RESOLVER = "native"

# mcp 2.x parses W3C trace context (traceparent/tracestate) from every inbound
# message. Nothing here exports traces, and opentelemetry-api's tracestate
# parser had an advisory (CVE-2026-114603), fixed in the pins since #1986,
# and both servers still run with the parsing off, as defence in depth.
# On POSIX the launchers export it
# too; on Windows the entry is the only place it can be set (#162).
OTEL_PROPAGATORS = "none"

# analytics-mcp 1.0+ enables its write tools, and asks Google for the edit
# scope, when ANALYTICS_MCP_ALLOW_WRITE is truthy. This package is read-only
# by design, so every entry sets it false: an inherited variable must not be
# able to turn writes on (#1986).
ANALYTICS_MCP_ALLOW_WRITE = "false"


class RegisterError(Exception):
    """Raised with a user-readable message; aborts before any write."""


def _windows_entries(ga_home, venv_python, adc_file):
    """The shape observed connecting on native Windows, not one designed here.

    Reconnaissance registered <venv>\\Scripts\\python.exe with a script
    argument through `claude mcp add` and Claude Code reported the server
    Connected. Everything below follows that observation.

    Both servers are started by python.exe, never by a pip-generated .exe.
    pip builds venv\\Scripts\\analytics-mcp.exe on each machine, so no other
    machine has ever seen it, and Defender's "block low-prevalence
    executables" ASR rule refuses it: "[WinError 5] Access is denied" on a
    managed machine, 2026-10-09 (#139). python.exe is a signed, widely seen
    program and analytics_mcp/server.py has a __main__ guard, so `-m` starts
    the same server the console script would.

    No launcher runs on Windows, so every environment variable the POSIX
    launchers export has to appear in the entry itself or it is never set at
    all. That is why both paths are required arguments rather than defaults:
    a guessed interpreter produces an entry that looks correct, a server that
    fails to start, and a symptom that points at credentials. Refusing is the
    only answer that cannot mislead.
    """
    if not venv_python:
        raise RegisterError(
            "Windows registration needs the venv interpreter path and none "
            "was given. There are no launchers on Windows to work it out at "
            "spawn time, and guessing it produces an entry that looks right "
            "and a server that never starts.")
    if not adc_file:
        raise RegisterError(
            "Windows registration needs the credential path and none was "
            "given. No launcher runs there to export "
            "GOOGLE_APPLICATION_CREDENTIALS, so an entry without it cannot "
            "authenticate.")

    # ntpath, not os.path: this branch must build Windows paths even when
    # it runs on a Mac, or it is only correct on the machine nobody here
    # can test on. os.path.dirname cannot split a backslash path on POSIX.
    # One separator, everywhere. Paths arrive mixed -- expanduser replaces only
    # the tilde, leaving "C:\\Users\\x/.config/ga-mcp" -- and a mixed entry,
    # though it works, reads as a defect to whoever opens the config later.
    ga_home = ntpath.normpath(ga_home)
    venv_python = ntpath.normpath(venv_python)
    adc_file = ntpath.normpath(adc_file)
    env = {
        "GRPC_DNS_RESOLVER": GRPC_RESOLVER,
        "OTEL_PROPAGATORS": OTEL_PROPAGATORS,
        "ANALYTICS_MCP_ALLOW_WRITE": ANALYTICS_MCP_ALLOW_WRITE,
        "GOOGLE_APPLICATION_CREDENTIALS": adc_file,
    }
    return {
        "analytics-mcp": {
            "type": "stdio",
            "command": venv_python,
            "args": ["-m", "analytics_mcp.server"],
            "env": dict(env),
        },
        "data-noodler": {
            "type": "stdio",
            "command": venv_python,
            "args": [ntpath.join(ga_home, "server", "data_noodler.py")],
            "env": dict(env),
        },
    }


def _posix_entries(ga_home):
    """Both entries pointing at the launchers.

    Launchers rather than binaries because the credential path and
    GRPC_DNS_RESOLVER have to be set before the server starts, and Codex's
    plugin manifest cannot supply env *values* -- only pass-through names.
    Codex is a macOS surface here, which is why this shape stays and Windows
    does not inherit it.
    """
    return {
        "analytics-mcp": {
            "type": "stdio",
            "command": f"{ga_home}/bin/launch-analytics-mcp",
            "args": [],
            "env": {"GRPC_DNS_RESOLVER": GRPC_RESOLVER,
                    "OTEL_PROPAGATORS": OTEL_PROPAGATORS,
                    "ANALYTICS_MCP_ALLOW_WRITE": ANALYTICS_MCP_ALLOW_WRITE},
        },
        "data-noodler": {
            "type": "stdio",
            "command": f"{ga_home}/bin/launch-data-noodler",
            "args": [],
            "env": {"GRPC_DNS_RESOLVER": GRPC_RESOLVER,
                    "OTEL_PROPAGATORS": OTEL_PROPAGATORS,
                    "ANALYTICS_MCP_ALLOW_WRITE": ANALYTICS_MCP_ALLOW_WRITE},
        },
    }


def server_entries(ga_home, platform=None, venv_python=None, adc_file=None):
    """The two MCP server entries for this platform.

    A pure function of its arguments, so both platforms' output can be
    asserted from either machine. venv_python and adc_file are required on
    Windows and unused on POSIX, where the launchers read them from
    config.json at spawn time.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        return _windows_entries(ga_home, venv_python, adc_file)
    return _posix_entries(ga_home)


def _make_private(path):
    """Remove group/other access from an existing harness config."""
    if os.name == "nt":
        return  # permissions there are ACLs, inherited from the profile
    try:
        target = safe_write.resolve_target(path)
        mode = os.stat(target).st_mode & 0o777
        if mode & 0o077:
            os.chmod(target, (mode & 0o700) | 0o600)
    except OSError:
        pass


def _backup(path):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = f"{path}.ga-backup-{stamp}"
    try:
        shutil.copy2(path, dest)
    except (OSError, shutil.Error) as exc:
        raise RegisterError(
            f"Could not back up {path} to {dest} ({exc}). Refusing to write "
            "without a backup in place.")
    return dest


# #1999: names this package used to register under. Each install removes
# them, so an app never shows the old name beside the new one.
LEGACY_SERVERS = ("ga-companion",)


def register_json(config_path, servers):
    """Merge `servers` into the `mcpServers` object of a JSON config.

    Returns {changed, backup, added, updated}. Writes nothing when the
    requested state already holds, so re-running is free and leaves no backup
    litter.
    """
    existing = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RegisterError(
                f"{config_path} is not valid JSON ({exc}). Refusing to write "
                "-- fix or move the file first, so nothing is lost.")
        if not isinstance(existing, dict):
            raise RegisterError(
                f"{config_path} does not contain a JSON object. Refusing to "
                "write.")

    raw_servers = existing.get("mcpServers")
    if raw_servers and not isinstance(raw_servers, dict):
        raise RegisterError(
            f"{config_path} has an 'mcpServers' key that is a "
            f"{type(raw_servers).__name__}, not an object. Refusing to "
            "write -- fix or remove that key first, so nothing is lost.")

    current = raw_servers or {}
    added = [name for name in servers if name not in current]
    updated = [name for name in servers
               if name in current and current[name] != servers[name]]

    removed = [name for name in LEGACY_SERVERS if name in current]

    if not added and not updated and not removed:
        # Nothing to write -- but still undo what earlier versions did: their
        # plain open() left this file readable by every account (#157).
        _make_private(config_path)
        return {"changed": False, "backup": None, "added": [], "updated": [],
                "removed": []}

    backup = _backup(config_path) if os.path.exists(config_path) else None

    merged = dict(existing)
    kept = {k: v for k, v in current.items() if k not in LEGACY_SERVERS}
    merged["mcpServers"] = {**kept, **servers}

    text = json.dumps(merged, indent=2) + "\n"
    # Prove the result parses before it replaces the original.
    try:
        json.loads(text)
    except ValueError as exc:
        raise RegisterError(f"Refusing to install a config that does not "
                            f"parse ({exc}). Original left untouched"
                            + (f"; backup at {backup}." if backup else "."))
    try:
        # Keeps the original's permissions (0600 stays 0600), refuses a
        # planted symlink, and writes through a symlinked config (#157).
        safe_write.write_atomically(config_path, text, private=True)
    except safe_write.SafeWriteError as exc:
        raise RegisterError(
            str(exc) + (f" Backup at {backup}." if backup else ""))
    return {"changed": True, "backup": backup, "added": added,
            "updated": updated, "removed": removed}
