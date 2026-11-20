#!/usr/bin/env python3
"""Copy the live google-analytics skill into the plugin before distribution.

The skill is authored once, at ~/.claude/skills/google-analytics, and copied
here so the plugin is self-contained for Codex. Copying rather than
symlinking because the plugin may be installed from a git checkout on another
machine, where a symlink would dangle.

__pycache__ is excluded: it contains absolute paths from this machine.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = os.path.expanduser("~/.claude/skills/google-analytics")
DEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "marketplace", "plugins", "ga-analytics", "skills", "google-analytics")


def main():
    if not os.path.isdir(SOURCE):
        sys.exit(f"No skill at {SOURCE} to copy.")
    if os.path.exists(DEST):
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The built copy is what installs hand out, so it carries the marker that
    # lets copy_skills.py refresh it later. The master never does: a skill
    # folder without the marker is never overwritten.
    import copy_skills
    with open(os.path.join(DEST, copy_skills.MARKER), "w",
              encoding="utf-8") as f:
        f.write(copy_skills.MARKER_TEXT)
    files = sum(len(f) for _, _, f in os.walk(DEST))
    print(f"copied {files} files to {DEST}")
    # Codex caches plugins by version, so a change shipped at an unchanged
    # version never reaches an existing install. test_plugin_manifests fails
    # until the version is bumped and the new fingerprint recorded; saying so
    # here puts the reminder at the moment the change is made.
    print("If that changed anything, bump the version in "
          "marketplace/plugins/ga-analytics/.codex-plugin/plugin.json -- "
          "the test suite will insist.")


if __name__ == "__main__":
    main()
