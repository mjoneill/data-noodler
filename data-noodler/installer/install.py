#!/usr/bin/env python3
"""Copy the package into ~/.config/ga-mcp and register the local harnesses.

Kept separate from the setup skill so the copy step is testable and repeatable
on its own. Idempotent: safe to re-run after editing the source.
"""

import argparse
import glob
import datetime
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness_paths
import register

PAYLOAD = ("server", "bin", "marketplace")
# #1999: the server folder's name before the product had one name. An install
# of ours under that name is moved aside (never deleted) by install_payload.
LEGACY_PAYLOAD = ("companion",)
# Entries an install of ours may hold that the current source no longer
# ships: the pre-#1999 launcher and server-file names, and the bytecode cache
# Python writes beside the server at run time. A marker-less (pre-2026-09-14)
# install is "ours" when it holds only shipped entries and these (#1999,
# Indigo's review of PR #4).
LEGACY_ENTRIES = frozenset({"launch-ga-mcp", "launch-ga-companion",
                            "ga_companion.py", "__pycache__"})


class InstallError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


MARKER = ".ga-mcp-payload"


def _validated_ga_home(ga_home, home=None):
    """Refuse a destination that recursive replacement must never be pointed at.

    --ga-home is an argparse string with no validation, and this function
    replaces whole directories under it. The three refusals below are the
    ones where a typo or an invented flag value destroys something.
    """
    home = os.path.expanduser("~") if home is None else home
    if not os.path.isabs(ga_home):
        raise InstallError(
            f"--ga-home must be an absolute path, got {ga_home!r}. A relative "
            "path resolves against whatever directory this happens to run "
            "from, which is not something to replace directories under.")
    ga_home = os.path.abspath(ga_home)
    if ga_home == os.path.abspath(os.sep) or os.path.dirname(ga_home) == ga_home:
        raise InstallError(
            f"refusing to install into the filesystem root ({ga_home}).")
    if ga_home == os.path.abspath(os.path.expanduser(home)):
        raise InstallError(
            f"refusing to install into the home directory itself ({ga_home}). "
            "That would put server/, bin/ and marketplace/ directly in "
            "your home and replace anything already using those names.")
    return ga_home


def _is_previous_payload(dest, src):
    """Whether `dest` looks like an install of ours, and so may be replaced.

    Two ways to qualify. A marker file, written by every install from
    2026-09-14 on. Or -- for installs that predate the marker, which includes
    every one in use today -- every entry in dest is also an entry in src, so
    the directory holds nothing this package did not put there.

    Anything else is someone else's directory and is refused rather than
    deleted. The old code called shutil.rmtree() here with no test of any kind.
    """
    if os.path.exists(os.path.join(dest, MARKER)):
        return True
    try:
        existing = set(os.listdir(dest))
        shipped = set(os.listdir(src))
    except OSError:
        return False
    return bool(existing) and existing <= shipped | LEGACY_ENTRIES


_BACKUP_STAMP = re.compile(r"\.ga-(?:old|backup)-(\d{8}-\d{6})$")


def _made_at(path):
    """When a backup was MADE, from the timestamp in its name.

    Not mtime. A directory's mtime is when its contents last changed, and a
    rename does not touch it -- so a rollback made this morning reported the
    date its code was first installed, a month earlier. The name is written
    at the moment of backing up, so it is the true time. mtime is only the
    fallback for a name that carries no stamp.
    """
    m = _BACKUP_STAMP.search(path)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def find_backups(ga_home, config_paths):
    """Every backup this package has left, oldest first. Read-only.

    Payload rollbacks (<dir>.ga-old-<stamp>, made by install_payload), the
    registration backups register.py writes beside each harness config, and
    the config.json backups bootstrap_config.py writes on --force.

    This only LOOKS. Michael, 2026-10-06: "I just don't want to be in the
    business of removing something like that via script." The installer used
    to prune payload rollbacks to the three most recent; that code is gone.
    """
    patterns = [os.path.join(ga_home, f"{name}.ga-old-*")
                for name in PAYLOAD + LEGACY_PAYLOAD]
    patterns.append(os.path.join(ga_home, "config.json.ga-backup-*"))
    for path in config_paths or []:
        if path:
            patterns.append(path + ".ga-backup-*")
    found = set()
    for pattern in patterns:
        found.update(glob.glob(pattern))
    return sorted(found, key=lambda p: (_made_at(p), p))


def backup_report(ga_home, config_paths):
    """A message listing every backup, or None when there are none."""
    found = find_backups(ga_home, config_paths)
    if not found:
        return None
    lines = ["", "Backups from earlier installs -- nothing here was deleted:"]
    for path in found:
        day = _made_at(path).strftime("%Y-%m-%d")
        lines.append(f"  {day}  {path}")
    lines += [
        "The newest are your undo for this install. Once you are confident it",
        "works, older ones are safe to remove -- by hand, whenever you choose.",
        "Copy the paths above into a note so you can find them later: this",
        "installer will never remove a backup for you.",
    ]
    return "\n".join(lines)


def describe_payload_plan(repo_root, ga_home, home=None):
    """Every path a real run would touch, as lines, touching nothing itself.

    Runs the same validation and the same "is this ours to replace?" check as
    install_payload, so a plan that prints is a plan that would run, and a
    plan that refuses is a run that would refuse. A dry run that validates
    less than the real thing is worse than none, because it grants confidence
    it has not earned.
    """
    ga_home = _validated_ga_home(ga_home, home=home)
    src_root = os.path.join(repo_root, "data-noodler")
    lines = [f"plan for {ga_home} (nothing below has been done)"]
    for name in PAYLOAD:
        src = os.path.join(src_root, name)
        dest = os.path.join(ga_home, name)
        if not os.path.isdir(src):
            raise InstallError(f"missing payload directory: {src}")
        if os.path.exists(dest):
            if not _is_previous_payload(dest, src):
                raise InstallError(
                    f"{dest} exists and does not look like a previous install "
                    "of this package -- it holds files this package never put "
                    "there. Refusing to replace it. Check whether --ga-home is "
                    "what you meant, then move or remove that directory by "
                    "hand.")
            lines.append(f"  keep     {dest} -> {dest}.ga-old-<timestamp>")
            lines.append(f"  replace  {dest}  (copied from {src})")
        else:
            lines.append(f"  create   {dest}  (copied from {src})")
    lines.append("  keep every earlier copy -- the installer never removes a "
                 "backup")
    return lines


def install_payload(repo_root, ga_home, home=None, platform=None):
    """Copy server/, bin/ and marketplace/ into ga_home. Returns paths.

    Staged rather than destructive. Each directory is built alongside the
    live one, the live one is RENAMED aside rather than deleted, and only
    then does the new copy take its place. So an interrupted or failed run
    leaves the previous install intact, and a completed one leaves it
    recoverable.

    This replaced a shutil.rmtree() of the destination. That call was the
    most dangerous line in the package and had no tests at all: with
    --ga-home ~ it removed ~/companion, ~/bin and ~/marketplace.
    """
    platform = sys.platform if platform is None else platform
    ga_home = _validated_ga_home(ga_home, home=home)
    src_root = os.path.join(repo_root, "data-noodler")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    written = []

    # Every refusal before any write: checked one folder at a time, a
    # refusal of bin/ came after server/ was already replaced, leaving a
    # half-old, half-new install (Indigo's review of PR #4).
    for name in PAYLOAD:
        src = os.path.join(src_root, name)
        dest = os.path.join(ga_home, name)
        if not os.path.isdir(src):
            raise InstallError(f"missing payload directory: {src}")
        if os.path.exists(dest) and not _is_previous_payload(dest, src):
            raise InstallError(
                f"{dest} exists and does not look like a previous install of "
                "this package -- it holds files this package never put there. "
                "Refusing to replace it, and nothing was changed. Check "
                "whether --ga-home is what you meant, then move or remove "
                "that directory by hand.")

    for name in PAYLOAD:
        src = os.path.join(src_root, name)
        dest = os.path.join(ga_home, name)
        staging = f"{dest}.ga-new"

        # Leftover staging from an interrupted run: ours by name, not a
        # destination anyone else writes to.
        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)
        try:
            os.makedirs(ga_home, exist_ok=True)
            shutil.copytree(src, staging,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            with open(os.path.join(staging, MARKER), "w", encoding="utf-8") as f:
                f.write("Written by ga-mcp install.py. Its presence is what "
                        "permits this directory to be replaced by a reinstall.\n")
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise InstallError(
                f"could not copy {src} to {staging} ({exc}). Nothing was "
                "changed; the existing install is untouched.")

        rolled = None
        if os.path.exists(dest):
            rolled = f"{dest}.ga-old-{stamp}"
            try:
                os.replace(dest, rolled)
            except OSError as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise InstallError(
                    f"could not move the existing {dest} aside ({exc}). On "
                    "Windows this usually means an application still has a "
                    "file open -- fully quit it and re-run. Nothing was "
                    "changed.")
        try:
            os.replace(staging, dest)
        except OSError as exc:
            if rolled:
                os.replace(rolled, dest)  # put the working install back
            shutil.rmtree(staging, ignore_errors=True)
            raise InstallError(
                f"could not move the new payload into place at {dest} "
                f"({exc}). The previous install was restored.")

        written.append(dest)

    # #1999: retire the payload folders this package used to install under
    # old names, so nothing is left running from them. Ours only (the marker,
    # or every entry also in the folder that replaced it); renamed aside with
    # the same .ga-old-<stamp> suffix, so backups and upgrade's undo find it.
    for name in LEGACY_PAYLOAD:
        old = os.path.join(ga_home, name)
        if os.path.isdir(old) and _is_previous_payload(
                old, os.path.join(src_root, "server")):
            try:
                os.replace(old, f"{old}.ga-old-{stamp}")
            except OSError as exc:
                raise InstallError(
                    f"installed, but could not move the old {old} aside "
                    f"({exc}). Quit every app using it and re-run.")

    # copytree preserves mode, but check it rather than trust it: a
    # non-executable launcher presents as an unexplained broken server.
    # A real raised exception rather than `assert`, so the check cannot be
    # stripped by running python with -O / PYTHONOPTIMIZE.
    #
    # Skipped on Windows, where there are no shell launchers to run and
    # os.access(X_OK) returns True for any existing file -- a check that
    # always passes is worse than none, because it reads as verification.
    if not platform.startswith("win"):
        for name in ("launch-analytics-mcp", "launch-data-noodler"):
            path = os.path.join(ga_home, "bin", name)
            try:
                os.chmod(path, 0o755)
            except OSError as exc:
                raise InstallError(
                    f"could not make {path} executable ({exc}). {path} may now "
                    "be partially installed; re-running is safe once the "
                    "problem is fixed.")
            if not os.access(path, os.X_OK):
                raise InstallError(f"{path} is not executable after chmod.")

    return written


def resolve_sessions_root(repo_root, config_path=None):
    """Where install.py should ensure the sessions root exists.

    Reads it the same way the server does -- config.sessions_root(cfg) --
    so the installer and the running server can never disagree about the
    path. install.py's --payload-only mode can run before any config.json
    exists on the machine (or against one that is malformed), so a missing
    or unreadable config falls back to sessions.DEFAULT_SESSIONS_ROOT rather
    than failing the install: this function always returns a path, never
    raises.
    """
    server_dir = os.path.join(repo_root, "data-noodler", "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    import config as server_config
    import sessions

    try:
        cfg = server_config.load(config_path)
    except server_config.ConfigError:
        return os.path.expanduser(sessions.DEFAULT_SESSIONS_ROOT)
    return server_config.sessions_root(cfg)


def registration_inputs(config_path=None, platform=None):
    """Extra arguments server_entries needs on this platform.

    Empty on POSIX: the launchers read config.json themselves at spawn time.
    On Windows there is no launcher, so the interpreter and credential paths
    have to be baked into the registered entry, and a missing config is a
    stop rather than something to guess around.
    """
    platform = sys.platform if platform is None else platform
    if not platform.startswith("win"):
        return {}
    import config as server_config
    try:
        cfg = server_config.load(config_path)
    except server_config.ConfigError as exc:
        raise InstallError(
            f"cannot register on Windows without the machine config ({exc}). "
            "Run bootstrap_config.py first -- it writes the interpreter and "
            "credential paths that a Windows registration has to embed, "
            "because no launcher runs there to look them up later.")
    return {"venv_python": cfg["venv_python"], "adc_file": cfg["adc_file"]}


def ensure_sessions_root(root):
    """Create the sessions root so the very first export doesn't fail.

    This is the one exception to sessions.start_session's rule that a
    session folder is created one level inside an *existing* root, never
    the root itself -- that guard stays, and is what keeps a mistyped root
    from building a directory tree. Creating the root once, here, at
    install time is different: it runs once, against a known-good path,
    not per-export against arbitrary user input.

    os.makedirs(..., exist_ok=True): an already-existing root is success,
    not an error. A failure (missing parent, permission denied) must not
    fail the install -- everything else the package does still works
    without this directory, and the user can create it by hand or point
    sessions_root elsewhere -- so it is reported and swallowed, never
    raised.
    """
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as exc:
        print(f"could not create sessions root {root}: {exc}")
        return
    print(f"installed {root}")


TARGETS = ("claude_code", "claude_desktop")


def config_path_for(target, home=None, env=None, platform=None):
    """The config file `target` registers into, or None if it is not installed.

    Extracted from main() so the Windows branch is reachable from a test on
    macOS. An unknown target raises rather than being handled partway down the
    registration loop, so a typo cannot half-run an install.

    None is an ordinary answer, not an error: Claude Desktop being absent is
    common -- plenty of people have only the CLI -- and the caller skips it.
    """
    if target == "claude_code":
        return harness_paths.claude_code_config(home=home, platform=platform)
    if target == "claude_desktop":
        return harness_paths.claude_desktop_config(
            home=home, env=env, platform=platform)
    raise InstallError(
        f"unknown target: {target}. Known targets are "
        + ", ".join(TARGETS) + ".")


def explain_missing_desktop(home=None, env=None, platform=None,
                            app_dirs=None):
    """A refusal message if Claude Desktop is installed but its config is not
    found, or None when it genuinely is not installed.

    Round 3, defect 2: on a Microsoft Store install, run from ordinary
    PowerShell, this used to print "not installed, skipping" and exit 0 while
    the app sat right there. A skip reads to an agent as success.
    """
    evidence = harness_paths.claude_desktop_evidence(
        home=home, env=env, platform=platform, app_dirs=app_dirs)
    if not evidence:
        return None
    return (
        "claude_desktop: the app appears to be installed, but its data "
        "directory was not found -- refusing rather than skipping.\n"
        "  Found: " + "; ".join(evidence) + "\n"
        "  Most likely it has never been opened, so the directory does not "
        "exist yet: open Claude Desktop once, fully quit it, and re-run.\n"
        "  If it has been opened, point at the directory explicitly with "
        "CLAUDE_USER_DATA_DIR. On a Microsoft Store install that is\n"
        "  %LOCALAPPDATA%\\Packages\\Claude_<family>\\LocalCache\\Roaming\\Claude.")


def _print_backup_report(ga_home, targets):
    paths = []
    for target in targets:
        try:
            paths.append(config_path_for(target))
        except InstallError:
            pass
    report = backup_report(ga_home, paths)
    if report:
        print(report)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--ga-home",
                    default=os.path.expanduser("~/.config/ga-mcp"))
    ap.add_argument("--targets", default="claude_code,claude_desktop",
                    help="comma-separated: claude_code, claude_desktop")
    ap.add_argument("--payload-only", action="store_true",
                    help="copy files but register nothing")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every path that would be touched, change "
                         "nothing, and exit")
    args = ap.parse_args()
    # expanduser replaces only the tilde, so on Windows the default came out as
    # C:\\Users\\x/.config/ga-mcp. normpath settles it on every platform.
    args.ga_home = os.path.normpath(os.path.expanduser(args.ga_home))
    report_targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    if args.dry_run:
        try:
            for line in describe_payload_plan(args.repo_root, args.ga_home):
                print(line)
        except InstallError as exc:
            raise SystemExit(str(exc))
        if not args.payload_only:
            targets = [t.strip() for t in args.targets.split(",") if t.strip()]
            for target in targets:
                try:
                    path = config_path_for(target)
                except InstallError as exc:
                    print(str(exc))
                    return 1
                if path is None:
                    print(f"  skip     {target}: not installed")
                else:
                    print(f"  register {target}: {path} "
                          "(backed up first, merged, never rewritten wholesale)")
        _print_backup_report(args.ga_home, report_targets)
        return 0

    try:
        written = install_payload(args.repo_root, args.ga_home)
    except InstallError as exc:
        raise SystemExit(str(exc))

    for path in written:
        print(f"installed {path}")

    ensure_sessions_root(resolve_sessions_root(args.repo_root))

    if args.payload_only:
        _print_backup_report(args.ga_home, report_targets)
        return 0

    try:
        extra = registration_inputs()
    except InstallError as exc:
        raise SystemExit(str(exc))
    entries = register.server_entries(args.ga_home, **extra)
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    for target in targets:
        try:
            path = config_path_for(target)
        except InstallError as exc:
            print(str(exc))
            return 1
        if path is None:
            refusal = (explain_missing_desktop()
                       if target == "claude_desktop" else None)
            if refusal:
                print(refusal)
                return 1
            print(f"{target}: not installed, skipping")
            continue

        print(f"{target}: using {path}")
        # register_json raises RegisterError at us by design -- it aborts
        # before touching a file it cannot safely write, and its messages say
        # what to fix. Letting it escape as a traceback would throw away that
        # wording and imply a bug in the installer rather than a config the
        # user needs to look at. Earlier targets that already succeeded stay
        # registered; each register_json call is all-or-nothing on its own
        # file, so nothing is left half-written.
        try:
            result = register.register_json(path, entries)
        except register.RegisterError as exc:
            raise SystemExit(f"{target}: {exc}")
        if result["changed"]:
            print(f"{target}: added={result['added']} "
                  f"updated={result['updated']} "
                  f"removed_old_names={result['removed']} "
                  f"backup={result['backup']}")
        else:
            print(f"{target}: already registered, no change")

    _print_backup_report(args.ga_home, report_targets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
