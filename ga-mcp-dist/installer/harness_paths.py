"""Locate each harness's configuration, without hardcoding a path.

The Claude Desktop resolution exists because two data directories can coexist
(`Claude` and `Claude-3p`) and writing to the inactive one fails silently:
no error, the tools simply never appear. Recency of directory contents is the
signal for which one the app actually uses.

`platform` is an argument rather than a read of `sys.platform` so both
branches can be exercised from either machine. A Windows branch that can only
be tested on Windows is a branch nobody tests: the port is being written on a
Mac, for a machine nobody here can reach. Never call `sys.platform` below the
public functions.

These functions PROBE THE FILESYSTEM -- os.path.isdir, os.listdir -- so they
must use the running machine's path semantics to find anything at all. On real
Windows os.path is ntpath, so production is correct; but a win32 resolution
computed on a Mac comes back with forward slashes. The paths here are
comparable across platforms, not byte-identical to what Windows emits.

register.server_entries is the opposite case and does use ntpath: it is pure
string construction, touches no filesystem, and so can build genuine Windows
paths from anywhere.
"""

import glob
import os
import sys

CLAUDE_DIR_CANDIDATES = ("Claude", "Claude-3p")
CONFIG_BASENAME = "claude_desktop_config.json"


def _is_windows(platform):
    return platform.startswith("win")


def _newest_mtime(directory):
    """Most recent mtime among the directory's entries, or 0 if empty."""
    newest = 0.0
    try:
        entries = os.listdir(directory)
    except OSError:
        return 0.0
    for name in entries:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(directory, name)))
        except OSError:
            continue
    return newest


def _support_dir(home, env, platform):
    """Where Claude Desktop keeps its data directories on this platform.

    Windows reads APPDATA rather than deriving the path, because a roaming
    profile can put it somewhere other than the default. The fallback covers
    a subprocess launched with a scrubbed environment, where guessing nothing
    would strand the install for no good reason.
    """
    if _is_windows(platform):
        return env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return os.path.join(home, "Library", "Application Support")


def _local_appdata(home, env):
    return env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")


def _store_roaming_dirs(home, env):
    """The real Roaming directories of any Microsoft Store Claude package.

    MSIX virtualises AppData: %APPDATA%\\Claude resolves only for processes
    inside the app container. The real directory lives under the package's
    LocalCache, and that one is visible from inside AND outside -- so it is
    the only path correct whoever runs the installer.

    The package FAMILY is globbed, not hardcoded. The full identity
    (Claude_2.19675.0.0_x64__...) changes with every version; even the family
    suffix should not be load-bearing in code.
    """
    pattern = os.path.join(_local_appdata(home, env), "Packages", "Claude_*",
                           "LocalCache", "Roaming")
    return sorted(d for d in glob.glob(pattern) if os.path.isdir(d))


def claude_desktop_config(home=None, env=None, platform=None):
    """Path to the active claude_desktop_config.json, or None if not installed.

    The file itself need not exist yet -- a path is returned as long as the
    data directory does, so a first-time registration has somewhere to write.
    """
    home = os.path.expanduser("~") if home is None else home
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform

    override = env.get("CLAUDE_USER_DATA_DIR")
    if override:
        return os.path.join(os.path.expanduser(override), CONFIG_BASENAME)

    # One candidate list for both platforms. Reconnaissance found a single
    # `Claude` directory on Windows and no -3p variant, so the recency choice
    # has nothing to decide there today -- but running the same code with a
    # different base costs nothing and stays correct if that ever changes.
    bases = [_support_dir(home, env, platform)]
    if _is_windows(platform):
        # Store packages FIRST. max() returns the first of equal values, and
        # inside the container %APPDATA%\\Claude and the package's real
        # directory are one directory under two names -- identical recency.
        # On that tie this picks the name that works from outside as well.
        # Between two genuinely different installs, recency still decides.
        bases = _store_roaming_dirs(home, env) + bases
    found = [os.path.join(base, name) for base in bases
             for name in CLAUDE_DIR_CANDIDATES
             if os.path.isdir(os.path.join(base, name))]
    if not found:
        return None

    active = max(found, key=_newest_mtime)
    return os.path.join(active, CONFIG_BASENAME)


def claude_desktop_evidence(home=None, env=None, platform=None,
                            app_dirs=None):
    """Signs that Claude Desktop is installed, as human-readable strings.

    Used only when claude_desktop_config() found nothing. Without this the
    installer said "not installed, skipping" and exited 0 -- which an agent
    reads as "fine, nothing to do" -- even with the app sitting right there.
    An installed app with no config is a contradiction, and contradictions
    should be loud.

    app_dirs is injectable so tests need not touch /Applications.
    """
    home = os.path.expanduser("~") if home is None else home
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    found = []
    if _is_windows(platform):
        local = _local_appdata(home, env)
        for d in sorted(glob.glob(os.path.join(local, "Packages", "Claude_*"))):
            if os.path.isdir(d):
                found.append(f"Microsoft Store package {d}")
        squirrel = os.path.join(local, "AnthropicClaude")
        if os.path.isdir(squirrel):
            found.append(f"installed application {squirrel}")
    else:
        if app_dirs is None:
            app_dirs = ["/Applications", os.path.join(home, "Applications")]
        for d in app_dirs:
            bundle = os.path.join(d, "Claude.app")
            if os.path.isdir(bundle):
                found.append(f"application bundle {bundle}")
    return found


def claude_code_config(home=None, platform=None):
    """Path to Claude Code's config. The same shape on every platform.

    `platform` is accepted and unused on purpose. Callers should not have to
    know which resolvers are platform-sensitive, and the argument is what lets
    a test assert this one is deliberately not -- confirmed on the Windows
    machine, where `claude mcp list` reads C:\\Users\\<user>\\.claude.json.
    """
    home = os.path.expanduser("~") if home is None else home
    return os.path.join(home, ".claude.json")
