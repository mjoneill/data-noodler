#!/usr/bin/env python3
"""Install or refresh the Claude Code skills, without touching anyone's own.

The installing agent runs this (Step 6 of a fresh install; after an upgrade),
not upgrade.py: skills are per app, and only Claude Code reads
~/.claude/skills. Codex gets its skill inside the plugin.

The rule (decided 2026-10-25): a skill folder is refreshed only when this
package put it there, which the marker file inside it records. A folder
without the marker is someone's own -- on the maintainer's machine,
~/.claude/skills/data-noodler is the MASTER copy everything is built
from, and an upgrade that overwrote it would silently replace unbuilt edits.
Those are reported, never touched; the agent tells the user and, only on a
yes, re-runs with --replace NAME.

Nothing is ever deleted. Files the new version no longer ships are reported,
not removed.

    python copy_skills.py   exit 0: done
                            exit 2: a folder this package did not install
                                    differs -- the user decides (--replace)
                            exit 1: a skill could not be installed at all
    python copy_skills.py --replace data-noodler

Standard library only.
"""

import argparse
import filecmp
import os
import shutil
import sys

MARKER = ".ga-mcp-installed"
MARKER_TEXT = ("Installed by the ga-mcp package. Its presence lets a later "
               "install refresh this folder. Delete this file to keep your "
               "own changes from being refreshed.\n")


def sources(ga_home, dist):
    return {
        "data-noodler": os.path.join(
            ga_home, "marketplace", "plugins", "data-noodler", "skills",
            "data-noodler"),
        "data-noodler-setup": os.path.join(dist, "skills", "data-noodler-setup"),
    }


def _same_tree(a, b):
    cmp = filecmp.dircmp(a, b, ignore=[MARKER, "__pycache__"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(_same_tree(os.path.join(a, d), os.path.join(b, d))
               for d in cmp.common_dirs)


def _extra_files(src, dest):
    extra = []
    for root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, dest)
        for f in files:
            if f == MARKER:
                continue
            if not os.path.exists(os.path.join(src, rel, f)):
                extra.append(os.path.normpath(os.path.join(rel, f)))
    return extra


# Statuses, and what each means for the exit code. Structured rather than
# read out of the message text (code review #6).
DONE = ("installed", "refreshed", "unchanged", "not-ours-same")
DECIDE = ("not-ours-differs", "legacy-not-ours")
FAILED = ("missing-source", "blocked")


def install_skill(name, src, skills_dir, replace=False):
    """(status, detail); status is one of DONE, DECIDE or FAILED."""
    dest = os.path.join(skills_dir, name)
    if not os.path.isdir(src):
        return "missing-source", f"nothing to install from {src}"
    if os.path.lexists(dest) and not os.path.isdir(dest):
        return "blocked", (f"{dest} exists and is not a folder (a file or a "
                           "broken link). Left untouched; the skill is NOT "
                           "installed.")
    if not os.path.exists(dest):
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc"))
        _mark(dest)
        return "installed", dest
    marked = os.path.exists(os.path.join(dest, MARKER))
    if not marked and not replace:
        if _same_tree(src, dest):
            return "not-ours-same", (
                f"{dest} was not installed by this package (no {MARKER}), "
                "but its files match the new version. Left untouched.")
        return "not-ours-differs", (
            f"{dest} was not installed by this package (no {MARKER}) and "
            "its files differ from the new version. Left untouched.")
    if _same_tree(src, dest):
        _mark(dest)
        return "unchanged", dest
    shutil.copytree(src, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _mark(dest)
    extra = _extra_files(src, dest)
    return "refreshed", dest + (
        f" (not removed, no longer shipped: {', '.join(extra)})" if extra
        else "")


# #1999: skill names this package used before the product had one name.
LEGACY_SKILLS = ("google-analytics", "ga-mcp-setup")


def retire_legacy(skills_dir, ga_home):
    """Move this package's old-named skills out of the skills folder.

    [(status, detail)]. Moved to <ga_home>/retired-skills/, never deleted,
    and never beside the skills: any folder there registers as a skill, so a
    renamed copy would still show up. A folder without the marker is
    someone's own and is only reported (status legacy-not-ours, a DECIDE).
    """
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    results = []
    for name in LEGACY_SKILLS:
        old = os.path.join(skills_dir, name)
        if not os.path.isdir(old):
            continue
        if not os.path.exists(os.path.join(old, MARKER)):
            results.append(("legacy-not-ours", (
                f"{old} has an old name of this package's skill but was not "
                f"installed by it (no {MARKER}). Left in place; it now "
                "duplicates the data-noodler skill. Ask the user whether to "
                "remove it.")))
            continue
        retired = os.path.join(ga_home, "retired-skills")
        os.makedirs(retired, exist_ok=True)
        dest = os.path.join(retired, f"{name}.ga-old-{stamp}")
        shutil.move(old, dest)
        results.append(("retired", f"{old} -> {dest}"))
    return results


def _mark(dest):
    with open(os.path.join(dest, MARKER), "w", encoding="utf-8") as f:
        f.write(MARKER_TEXT)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--ga-home",
                    default=os.path.expanduser("~/.config/ga-mcp"))
    ap.add_argument("--dist", default=os.path.dirname(here))
    ap.add_argument("--skills-dir",
                    default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--replace", action="append", default=[],
                    metavar="NAME",
                    help="refresh this skill even though this package did "
                         "not install it -- only after the user said yes")
    args = ap.parse_args()
    os.makedirs(args.skills_dir, exist_ok=True)
    statuses = []
    for name, src in sources(os.path.normpath(args.ga_home),
                             args.dist).items():
        status, detail = install_skill(name, src, args.skills_dir,
                                       replace=name in args.replace)
        print(f"{status:<16} {name}: {detail}")
        statuses.append(status)
    for status, detail in retire_legacy(args.skills_dir,
                                        os.path.normpath(args.ga_home)):
        print(f"{status:<16} {detail}")
        statuses.append(status)
    if any(s in FAILED for s in statuses):
        return 1
    if any(s in DECIDE for s in statuses):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
