#!/usr/bin/env python3
"""Prove a registered MCP server entry is actually launchable.

Spawns the configured command exactly as a client would and completes a real
handshake. This catches what inspecting a config file cannot: a wrong path, a
missing interpreter, a launcher that writes to stdout, an import error at
startup.

It cannot drive an application's UI, so it verifies that the entry a client
will launch does work -- confirming the tools appear in that client is a
restart plus one question.
"""

import argparse
import asyncio
import json
import os
import sys

try:
    _EXCEPTION_GROUP_TYPES = (BaseExceptionGroup,)
except NameError:  # pragma: no cover - guard for interpreters without PEP 654
    _EXCEPTION_GROUP_TYPES = ()


class VerifyError(Exception):
    """Raised with a message intended to be read by a user, not a developer.

    Each installer module keeps its own error type (InstallError,
    RegisterError, BootstrapError, VerifyError) rather than sharing a base
    class, so a caller can tell which stage failed from the type alone. This
    module needs one most of all: it is the diagnostic tool, and a traceback
    out of the thing you run to find out what is wrong is the least useful
    output it could produce.
    """


async def _handshake(command, args, env, timeout):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=list(args), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            tools = await asyncio.wait_for(session.list_tools(), timeout)
            return [t.name for t in tools.tools]


def _leaf_exceptions(exc):
    """Flatten an exception group into its leaf exceptions, recursively."""
    if _EXCEPTION_GROUP_TYPES and isinstance(exc, _EXCEPTION_GROUP_TYPES):
        leaves = []
        for sub in exc.exceptions:
            leaves.extend(_leaf_exceptions(sub))
        return leaves
    return [exc]


def _describe_exception(exc):
    """Render an exception into an error string, unpacking exception groups
    so the real cause (e.g. a launcher writing non-JSON to stdout) isn't
    hidden behind a generic "unhandled errors in a TaskGroup" summary."""
    if _EXCEPTION_GROUP_TYPES and isinstance(exc, _EXCEPTION_GROUP_TYPES):
        leaves = _leaf_exceptions(exc)
        detail = "; ".join(f"{type(e).__name__}: {e}" for e in leaves)
        return f"{type(exc).__name__}: {exc} [{detail}]"
    return f"{type(exc).__name__}: {exc}"


def probe(command, args, env=None, timeout=45.0):
    """Spawn a server and list its tools. Never raises; reports instead."""
    env = dict(os.environ) if env is None else env
    try:
        tools = asyncio.run(
            asyncio.wait_for(_handshake(command, args, env, timeout),
                             timeout + 5.0))
        return {"ok": True, "tools": tools, "error": None}
    except Exception as exc:
        return {"ok": False, "tools": [], "error": _describe_exception(exc)}


_ACCESS_DENIED = ("WinError 5", "Access is denied")

_DEFENDER_CHECK = (
    "Check: Get-WinEvent -LogName 'Microsoft-Windows-Windows "
    "Defender/Operational' | Where-Object Id -eq 1121 | Select-Object "
    "-First 5 | Format-List TimeCreated, Message")


def hint_for(error, command):
    """A known cause for a failed start, in words a user can act on, or None.

    Only for failures whose text reliably identifies the cause. "Access is
    denied" on Windows, against a file the user owns, is Microsoft Defender's
    Attack Surface Reduction refusing a program it has not seen on other
    machines -- measured on a managed machine 2026-10-09 (#142). Left bare,
    "access denied" next to a server that reads a credential gets diagnosed
    as the credential, which is the one misdiagnosis this package keeps
    warning about.
    """
    if not error or not any(s in error for s in _ACCESS_DENIED):
        return None
    base = (
        "Windows refused to run this program. On a managed machine that is "
        "usually Microsoft Defender's Attack Surface Reduction rule that "
        "blocks programs it has not seen on other machines. This is not a "
        "credential problem -- do not renew the credential for it. "
        + _DEFENDER_CHECK + ".")
    name = (command or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe") and not name.startswith("python"):
        return base + (
            " Fix: re-run install.py from a current package, which registers "
            "python.exe -m analytics_mcp.server instead of this launcher. See "
            "troubleshooting.md, \"Access is denied on Windows\".")
    return base + (
        " The blocked program is the interpreter itself, so IT has to allow "
        "it. See troubleshooting.md, \"Access is denied on Windows\".")


def probe_config(config_path, names=None):
    """Probe every mcpServers entry in a JSON config (or just `names`).

    Reads the file with the same care register_json does when it writes one:
    these are the harnesses' live config files, and a reader that dies with a
    JSONDecodeError or a FileNotFoundError tells the user less than the plain
    fact that the file is missing or unparseable -- which is itself the answer
    in both cases.
    """
    if not os.path.exists(config_path):
        raise VerifyError(
            f"No config at {config_path}, so there is nothing to verify. "
            "Either registration has not run yet, or this is not the path "
            "the client actually reads (Claude Desktop has two possible data "
            "directories -- see CLAUDE_USER_DATA_DIR).")
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VerifyError(
            f"{config_path} is not valid JSON ({exc}). That alone is enough "
            "to make a client show no servers at all -- fix or move the file "
            "before looking any further.")
    except OSError as exc:
        raise VerifyError(f"Could not read {config_path} ({exc}).")

    if not isinstance(data, dict):
        raise VerifyError(
            f"{config_path} contains a {type(data).__name__}, not a JSON "
            "object, so it has no 'mcpServers' to probe.")

    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise VerifyError(
            f"{config_path} has an 'mcpServers' key that is a "
            f"{type(servers).__name__}, not an object. Fix that key first.")
    if names:
        servers = {k: v for k, v in servers.items() if k in names}

    results = {}
    for name, entry in servers.items():
        # A hand-edited config can hold a string here instead of an object.
        # Report it as this entry's failure and keep probing the others: the
        # point of a diagnostic is to describe every entry, and an
        # AttributeError on the first bad one describes none of them.
        if not isinstance(entry, dict):
            results[name] = {
                "ok": False, "tools": [],
                "error": (f"entry is a {type(entry).__name__}, not an object "
                          "with a 'command'")}
            continue
        command = entry.get("command")
        if not command:
            results[name] = {"ok": False, "tools": [],
                              "error": "entry has no 'command'"}
            continue
        env = dict(os.environ)
        env.update(entry.get("env") or {})
        result = probe(command, entry.get("args") or [], env)
        if not result["ok"]:
            result["hint"] = hint_for(result["error"], command)
        results[name] = result
    return results


def legacy_entries(config_path):
    """#1999: a server still registered under a name this package retired.

    An app would show it beside the new name, and it may run old code."""
    import register
    try:
        with open(config_path, encoding="utf-8") as f:
            servers = (json.load(f) or {}).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        return []
    return [f"{name}: an old name for data-noodler is still registered in "
            f"{config_path}. Re-run install.py to retire it."
            for name in register.LEGACY_SERVERS if name in servers]


def parse_requirements(specs):
    """["data-noodler=9", ...] -> {"data-noodler": 9}.

    Refuses anything it cannot read rather than silently ignoring it. A
    requirement that is quietly dropped turns the strictest check in the
    package into a no-op that still exits 0, which is worse than not having
    asked for it.
    """
    out = {}
    for spec in specs or []:
        name, sep, count = str(spec).partition("=")
        if not sep or not name.strip() or not count.strip().isdigit():
            raise VerifyError(
                f"could not read the requirement {spec!r}. Expected "
                "name=count, for example: --require data-noodler=9")
        out[name.strip()] = int(count.strip())
    return out


def unmet_requirements(results, requirements):
    """Human-readable lines for each requirement not met. Empty means done.

    Three distinct failures, deliberately not collapsed: a required server
    that is not registered at all, one that is registered but did not start,
    and -- the case this function exists for -- one that started perfectly
    and is serving fewer tools than it should. That last is invisible to any
    check that stops at "did it connect", and is exactly what a half-applied
    payload update looks like.
    """
    problems = []
    for name, expected in sorted(requirements.items()):
        result = results.get(name)
        if result is None:
            problems.append(
                f"{name}: required but not registered in this config")
            continue
        if not result.get("ok"):
            problems.append(f"{name}: required but did not start "
                            f"({result.get('error')})")
            continue
        actual = len(result.get("tools") or [])
        if actual != expected:
            problems.append(
                f"{name}: serving {actual} tools, expected {expected}. The "
                "server started, so this is not a credential or a path "
                "problem -- the payload on disk is not the one expected.")
    return problems


DEFAULT_SKILLS_DIR = os.path.expanduser("~/.claude/skills")


def _frontmatter_name(text):
    """The name: field of a SKILL.md's YAML frontmatter, or None."""
    if not text.startswith("---"):
        return None
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip().strip("\"'") or None
    return None


def missing_skills(names, skills_dir=None):
    """Lines describing each requested Claude Code skill that is not installed.

    Issue #5. verify.py only counted MCP tools, so an install that skipped the
    skill step exited 0 and left Claude Code with the tools but not the guidance
    on which one to use. "Installed" means SKILL.md exists, is not empty, and
    its frontmatter names the skill -- a directory named right holding the wrong
    skill would otherwise pass.
    """
    skills_dir = skills_dir or DEFAULT_SKILLS_DIR
    problems = []
    for name in names or []:
        path = os.path.join(skills_dir, name, "SKILL.md")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            problems.append(
                f"skill {name}: not installed -- expected {path}. Copy it from "
                "the package's marketplace/plugins/data-noodler/skills/ "
                "(INSTALL.md, the Claude Code skills step).")
            continue
        if not text.strip():
            problems.append(f"skill {name}: {path} is empty")
            continue
        declared = _frontmatter_name(text)
        if declared != name:
            problems.append(
                f"skill {name}: {path} declares name {declared!r}, not "
                f"{name!r} -- the wrong skill is installed under this name")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True,
                    help="path to a JSON config containing mcpServers")
    ap.add_argument("--name", action="append", dest="names",
                    help="probe only this server (repeatable)")
    ap.add_argument("--require", action="append", dest="requirements",
                    metavar="NAME=COUNT",
                    help="fail unless this server is registered, starts, and "
                         "serves exactly COUNT tools (repeatable). This is "
                         "what makes 'installed' an exit code rather than a "
                         "sentence somebody has to read and agree with.")
    ap.add_argument("--require-skill", action="append", dest="skills",
                    metavar="NAME",
                    help="fail unless this Claude Code skill is installed "
                         "(repeatable). Claude Code installs only: the other "
                         "clients do not read ~/.claude/skills.")
    ap.add_argument("--skills-dir", default=None,
                    help="where to look for skills (default ~/.claude/skills)")
    args = ap.parse_args()

    try:
        requirements = parse_requirements(args.requirements)
        # With --require and no --name, probe only what is required. A config
        # also holds the user's other MCP servers, and one of those being
        # broken says nothing about this install -- it used to turn a good
        # install's exit code into a failure (found 2026-10-25).
        names = args.names or (sorted(requirements) if requirements else None)
        results = probe_config(args.config, names)
    except VerifyError as exc:
        raise SystemExit(str(exc))

    if not results:
        print(f"No matching mcpServers entries in {args.config}")
        return 1

    unmet = unmet_requirements(results, requirements)
    unmet += missing_skills(args.skills, args.skills_dir)
    unmet += legacy_entries(args.config)

    failed = 0
    for name, r in sorted(results.items()):
        if r["ok"]:
            print(f"OK    {name}: {len(r['tools'])} tools "
                  f"({', '.join(sorted(r['tools'])[:4])}"
                  f"{'...' if len(r['tools']) > 4 else ''})")
        else:
            failed += 1
            print(f"FAIL  {name}: {r['error']}")
            if r.get("hint"):
                print(f"      why: {r['hint']}")

    for line in unmet:
        print(f"UNMET {line}")
    if unmet:
        print(f"{len(unmet)} requirement(s) not met -- not installed.")
    return 1 if (failed or unmet) else 0


if __name__ == "__main__":
    sys.exit(main())
