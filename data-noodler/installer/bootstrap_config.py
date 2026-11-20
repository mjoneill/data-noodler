#!/usr/bin/env python3
"""Generate a machine's ~/.config/data-noodler/config.json.

Every other module in this package reads its paths from that file, which is
what makes them portable. Nothing until now created it — the author's was
written by hand months ago, so a colleague had no way to get one.

The interpreter is discovered by reading the console script's shebang rather
than searching a list of known locations. pipx and uv both put the binary at
~/.local/bin/analytics-mcp but keep their virtualenvs in completely different
trees, and on macOS the pipx path contains a space. The shebang is the one
place that always names the interpreter that will actually run the program.
"""

import argparse
import datetime
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import home as home_mod  # noqa: E402
import safe_write  # noqa: E402
import security_floors  # noqa: E402

# One command, and it must stay byte-identical to the one in SKILL.md and
# INSTALL.md -- test_bootstrap_config.TestInstallHintIsRunnable asserts that.
# This previously named `uv tool inject`, which does not exist: inject is
# pipx's verb and uv rejects it. The documents were corrected in 8f47d00 and
# this string was not, so anyone who hit this wall was handed a command that
# could not work. google-auth-oauthlib rides along via --with because the
# consent script needs it and the server itself does not depend on it.
# -c pins the libraries underneath to the tested, scanned set (#151).
INSTALL_HINT = (
    "Install it first:\n"
    "  uv tool install analytics-mcp==1.1.0 --with google-auth-oauthlib "
    "-c <repo>/data-noodler/installer/constraints.txt")

# Windows has its own, because the macOS advice is wrong there: windows.md opens
# with "No uv", and on the machine measured uv was absent and gated behind an
# IT-managed Software Center. Telling a Windows user to install uv sent them
# away from the documented path. Each command here must stay byte-identical to
# windows.md -- TestWindowsVenvIsFound asserts that.
INSTALL_HINT_WINDOWS = (
    "Install it into a virtual environment first -- on Windows that is stock "
    "Python, not uv (see references/windows.md):\n"
    '  python -m venv "$env:USERPROFILE\\.config\\data-noodler\\venv"\n'
    '  & "$env:USERPROFILE\\.config\\data-noodler\\venv\\Scripts\\python.exe" -m pip '
    'install "' + security_floors.PIP_BOOTSTRAP_REQUIREMENT + '"\n'
    '  & "$env:USERPROFILE\\.config\\data-noodler\\venv\\Scripts\\python.exe" -m pip '
    "install -c <repo>\\data-noodler\\installer\\constraints.txt "
    "--upgrade analytics-mcp==1.1.0 google-auth-oauthlib\n"
    "If it IS installed somewhere this did not look, name it rather than let "
    "anything guess:\n"
    '  --venv-python "<venv>\\Scripts\\python.exe"   (or --analytics-mcp-bin)')


def install_hint(platform=None):
    platform = sys.platform if platform is None else platform
    return INSTALL_HINT_WINDOWS if platform.startswith("win") else INSTALL_HINT


class BootstrapError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


def _normalise_exe(path):
    """...\\analytics-mcp.EXE -> ...\\analytics-mcp.exe.

    shutil.which appends PATHEXT's own spelling, which is uppercase. Harmless --
    register.py builds its own lowercase path -- but it makes config.json look
    inconsistent to anyone reading it.
    """
    return path[:-4] + ".exe" if path.lower().endswith(".exe") else path


def detect_analytics_mcp(home=None, platform=None, which=None):
    """Absolute path to the analytics-mcp console script, or None.

    Searches PATH, then where each platform's documented install puts it. On
    Windows that is the venv windows.md creates -- which is on neither PATH nor
    ~/.local/bin, the only two places this used to look, so the documented
    Windows install failed at its first real step (round 3, defect 1).

    `which` is injectable so a test is not satisfied by whatever analytics-mcp
    happens to be installed on the machine running it.
    """
    home = os.path.expanduser("~") if home is None else home
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which

    found = which("analytics-mcp")
    if found:
        if not (os.path.isabs(found) or ntpath.isabs(found)):
            found = os.path.abspath(found)
        return _normalise_exe(found)

    if platform.startswith("win"):
        candidates = [
            os.path.join(home_mod.new_home(home), "venv", "Scripts",
                         "analytics-mcp.exe"),
            # #1999: migrate_home.py never moves a venv (it holds absolute
            # paths), so an install from before the rename keeps it here.
            os.path.join(home_mod.legacy_home(home), "venv", "Scripts",
                         "analytics-mcp.exe"),
            os.path.join(home, ".local", "bin", "analytics-mcp.exe"),
        ]
    else:
        candidates = [os.path.join(home, ".local", "bin", "analytics-mcp")]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def _console_script_beside(venv_python, platform):
    """The analytics-mcp program in the same directory as an interpreter."""
    name = ("analytics-mcp.exe" if platform.startswith("win")
            else "analytics-mcp")
    candidate = os.path.join(os.path.dirname(venv_python), name)
    return candidate if os.path.exists(candidate) else None


# pip's console-script generator cannot put a path containing a space
# directly in a shebang line: the kernel splits a shebang on the first space
# and execs only the text before it, which would mangle
# ".../Application Support/...". Its workaround -- confirmed against a real
# pipx install on this machine -- is a POSIX-sh/Python polyglot: `#!/bin/sh`
# followed by a quoted `exec` line that re-invokes the real interpreter.
# Reading only the shebang line returns "/bin/sh" for scripts shaped this
# way, which is wrong, so that shape is detected and unwrapped below.
#
# pip up to 25.x single-quoted the interpreter on the exec line; pip 26
# double-quotes it. Seen 2026-10-25: a venv rebuilt with pip 26.2.2 made
# discovery read "/bin/sh" (the clean-home dry run caught it). Either quote.
_GENERIC_SHELLS = ("/bin/sh", "/bin/bash")
_POLYGLOT_EXEC_RE = re.compile(
    r"""^'''exec'\s+(?P<q>['"])(?P<path>.+?)(?P=q)\s""")


def _windows_interpreter_beside(binary_path):
    """python.exe in the same Scripts directory as the console script.

    Windows console scripts are compiled .exe wrappers with no shebang, so
    the macOS strategy has nothing to read. What is available instead is
    positional: pip and venv put python.exe alongside the scripts they
    generate. Reconnaissance confirmed the layout on the target machine --
    Scripts\\ held analytics-mcp.exe and python.exe and nothing else.

    Returns None rather than a guess when the sibling is absent. A wrong
    interpreter here is silent: the config is written, the entry looks
    correct, and the server simply never starts.
    """
    # os.path, not ntpath: this function PROBES THE FILESYSTEM, so it has to
    # use the running machine's semantics to find anything. On real Windows
    # os.path is ntpath, so production is correct either way. ntpath belongs
    # only where paths are built and never looked up -- register.server_entries.
    candidate = os.path.join(os.path.dirname(binary_path), "python.exe")
    return candidate if os.path.exists(candidate) else None


def venv_python_for(binary_path, platform=None):
    """The interpreter that actually runs a console script, or None.

    Returns None rather than raising for a compiled binary or a missing file:
    the caller composes a better message than this function could.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        return _windows_interpreter_beside(binary_path)
    try:
        with open(binary_path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.split("\n")
    # Do not split the shebang line on whitespace -- the real macOS pipx
    # path contains a space ("Application Support"), and splitting would
    # truncate it.
    shebang_interp = lines[0][2:].strip()

    if shebang_interp in _GENERIC_SHELLS and len(lines) > 1:
        match = _POLYGLOT_EXEC_RE.match(lines[1])
        if match:
            return match.group("path") or None

    return shebang_interp or None


# Where install.py's payload puts the consent script: the marketplace plugin
# copy under ~/.config/data-noodler/. This is the only copy an install of any kind
# is guaranteed to create -- install.py's payload is exactly ("server",
# "bin", "marketplace"), so nothing here ever writes ~/.claude/skills/, and a
# renewal command naming a path there is a command a clean machine cannot run.
# Kept as a relative tuple so a test can assert the same path exists inside
# the repo's own marketplace tree, which is what the payload copies from.
MINT_SCRIPT_PARTS = (".config", "data-noodler", "marketplace", "plugins",
                     "data-noodler", "skills", "data-noodler", "scripts",
                     "mint_adc.py")


IMPORT_PROBE = ("import mcp, analytics_mcp, google.auth, "
                "google.analytics.data_v1beta, google_auth_oauthlib")


def interpreter_can_run_the_servers(interpreter, timeout=60):
    """Whether `interpreter` can import what both servers need.

    Discovery can return a real executable that is simply the wrong one --
    the system python rather than the venv's. That writes a clean config and
    a server that cannot import its own dependencies, which surfaces much
    later as "the tools are missing" and gets diagnosed as credentials.

    Checking costs one subprocess at install time and converts a silent,
    late, misattributed failure into a loud one at the moment it is caused.
    """
    try:
        proc = subprocess.run([interpreter, "-c", IMPORT_PROBE],
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def mint_script_for(home):
    """Absolute path to the consent script the payload installs under home."""
    # An install from before the rename keeps its old home until
    # migrate_home.py moves it (#1999), so the script is under whichever home
    # this machine has.
    return os.path.join(home_mod.default_home(home), *MINT_SCRIPT_PARTS[2:])


def build_config(home, quota_project=None, binary=None, venv_python=None,
                 platform=None, validate=True, which=None):
    """Assemble config.json's contents for the given home directory.

    quota_project is omitted unless explicitly given. Both the GA Data API
    and the GA Admin API work with no quota-project header at all, so there
    is no project that is a correct default for everyone -- and defaulting
    to the author's own Cloud project would require every colleague to hold
    serviceusage.services.use there, which they don't and shouldn't need to.
    Pass --quota-project only if you own a Cloud project and want usage
    billed/reported against it.
    """
    platform = sys.platform if platform is None else platform

    # An explicit interpreter is consulted FIRST. This used to raise on a
    # failed program search before --venv-python was ever read, which made the
    # escape hatch unreachable on exactly the path it was added for.
    if not binary and venv_python:
        binary = _console_script_beside(venv_python, platform)
    binary = binary or detect_analytics_mcp(home=home, platform=platform,
                                            which=which)
    if not binary and not venv_python:
        raise BootstrapError(
            f"Could not find the analytics-mcp program. "
            f"{install_hint(platform)}")
    interpreter = venv_python or venv_python_for(binary, platform=platform)
    if not interpreter:
        if platform.startswith("win"):
            raise BootstrapError(
                f"Could not find python.exe beside {binary}. Windows console "
                "scripts are compiled wrappers with no shebang to read, so "
                "the interpreter is located by sitting in the same Scripts "
                "directory -- and nothing is there.\n"
                "Pass it explicitly instead of letting anything guess:\n"
                "  --venv-python <path to your venv's Scripts\\python.exe>")
        raise BootstrapError(
            f"Could not read an interpreter from {binary}'s shebang, so the "
            "skill's scripts would have nothing to run. If this is a "
            f"compiled binary rather than a console script, reinstall with "
            f"uv or pipx, or pass --venv-python explicitly.\n{INSTALL_HINT}")

    if validate and not interpreter_can_run_the_servers(interpreter):
        raise BootstrapError(
            f"{interpreter} cannot import what the servers need "
            f"({IMPORT_PROBE}). It is a real program but the wrong one -- "
            "most often the system python rather than the one analytics-mcp "
            "was installed into. Writing this path would produce a config "
            "that looks correct and servers that never start.\n"
            "Install analytics-mcp into that interpreter, or name the right "
            "one with --venv-python.")

    cfg = {
        "oauth_client_file": os.path.join(
            home, ".config", "gcloud", "data-noodler-client.json"),
        "adc_file": os.path.join(
            home, ".config", "gcloud", "data-noodler-credential.json"),
        "venv_python": interpreter,
        "properties_csv": os.path.join(
            home_mod.default_home(home), "properties.csv"),
        "mint_script": mint_script_for(home),
    }
    # Optional in config.json: the launchers fall back to searching, and on
    # Windows nothing reads it -- the entry runs venv_python -m
    # analytics_mcp.server, because Defender can refuse the .exe (#139).
    # Recorded only when actually located, never guessed.
    if binary:
        cfg["analytics_mcp_bin"] = binary
    if quota_project:
        cfg["quota_project"] = quota_project
    return cfg


def write_config(path, cfg, force=False):
    """Write cfg to path. Returns True if written, False if left alone.

    Refuses to overwrite by default. A config that already exists names a
    credential and a property snapshot someone is relying on; replacing it
    silently is worse than doing nothing.

    Written through a temporary file that is re-parsed before it replaces the
    original -- the same discipline register_json uses, and for a stronger
    reason: this is the root config every other module reads its paths from,
    so a truncated or unparseable one breaks every harness at once, with a
    symptom (no GA tools anywhere) that points nowhere near the cause.
    """
    if os.path.exists(path) and not force:
        return False

    if os.path.exists(path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = f"{path}.ga-backup-{stamp}"
        try:
            shutil.copy2(path, dest)
        except (OSError, shutil.Error) as exc:
            raise BootstrapError(
                f"Could not back up {path} to {dest} ({exc}). Refusing to "
                "replace it without a backup in place.")

    parent = os.path.dirname(path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise BootstrapError(
                f"Could not create {parent} ({exc}), so there is nowhere to "
                f"write {path}.")

    try:
        text = json.dumps(cfg, indent=2) + "\n"
        # Prove the result parses before it becomes the file every other
        # module reads its paths from.
        json.loads(text)
    except (TypeError, ValueError) as exc:
        raise BootstrapError(
            f"Refusing to install a config that does not serialise and parse "
            f"({exc}). {path} left untouched.")
    try:
        # 0600 for a new file, the original's mode otherwise; never follows
        # a planted temp symlink (#157).
        safe_write.write_atomically(path, text, private=True)
    except safe_write.SafeWriteError as exc:
        raise BootstrapError(str(exc))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", default=os.path.expanduser("~"))
    ap.add_argument(
        "--quota-project", default=None,
        help="GCP project to bill/report GA API usage against. Only set "
             "this if you own a Cloud project yourself -- omitting it is "
             "correct for everyone else, since both GA APIs work with no "
             "quota-project header at all.")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing config (a backup is written)")
    ap.add_argument("--venv-python", default=None,
                    help="interpreter that runs analytics-mcp, when it cannot "
                         "be discovered. This is the escape hatch: if "
                         "discovery fails, name it here rather than letting "
                         "anything infer it.")
    ap.add_argument("--analytics-mcp-bin", default=None,
                    help="the analytics-mcp program, when it cannot be found. "
                         "Usually unnecessary: --venv-python finds the one "
                         "beside it.")
    ap.add_argument("--skip-import-check", action="store_true",
                    help="do not verify the interpreter can import the "
                         "servers' dependencies (not recommended)")
    args = ap.parse_args()

    path = os.path.join(home_mod.default_home(args.home), "config.json")
    try:
        cfg = build_config(args.home, args.quota_project,
                           binary=args.analytics_mcp_bin,
                           venv_python=args.venv_python,
                           validate=not args.skip_import_check)
        written = write_config(path, cfg, force=args.force)
    except BootstrapError as exc:
        raise SystemExit(str(exc))

    if written:
        print(f"wrote {path}")
        for key in sorted(cfg):
            print(f"  {key}: {cfg[key]}")
    else:
        print(f"{path} already exists; left unchanged. "
              "Pass --force to replace it (a backup is written).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
