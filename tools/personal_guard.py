#!/usr/bin/env python3
"""Personal guard: a local pre-push hook that refuses a push carrying values
that belong to the person pushing.

The CI leak guard (tools/leak_guard.py) can only use generic patterns,
because this repository is public and cannot hold a list of what is private.
This hook checks the private list, and the list never leaves your machine:

  * every GA property and account id in your property snapshot (the
    properties_csv that ~/.config/data-noodler/config.json names), matched as a
    whole number;
  * every line of ~/.config/data-noodler/personal-guard.txt (your institution, team
    or colleague names, a Cloud project id...), matched anywhere, ignoring
    case. A line starting with `re:` is a regular expression instead (also
    ignoring case), for a value that needs word boundaries or variants.
    Blank lines and lines starting with # are skipped.

It reads every commit the push would send: the lines each commit adds and
the commit message. A value added in one commit and removed in the next is
still refused, because both commits are sent.

A refusal names the commit, the file and the kind of value, never the value.
With neither list present it says so loudly and lets the push through; a
list that is named but cannot be read refuses the push.

Install, once per clone:   git config core.hooksPath tools/hooks
Test location override:    DATA_NOODLER_PERSONAL_GUARD_CONFIG_DIR=<dir>
"""

import csv
import json
import os
import re
import subprocess
import sys

ZERO = "0" * 40
ID_COLUMNS = ("property_id", "property", "account")
ID_TOKEN = re.compile(r"\d{6,}")


def config_dir():
    """Where the lists live: the install home, new name first.

    #1999: an install from before the rename keeps its lists in the old home
    until migrate_home.py moves them. Falling back matters here more than
    anywhere: with no list found this guard warns and PASSES, so a home it
    cannot find would quietly stop every check."""
    override = os.environ.get("DATA_NOODLER_PERSONAL_GUARD_CONFIG_DIR")
    if override:
        return override
    base = os.path.expanduser("~/.config")
    new = os.path.join(base, "data-noodler")
    old = os.path.join(base, "ga-" "mcp")
    def has_lists(d):
        return any(os.path.isfile(os.path.join(d, n))
                   for n in ("config.json", "personal-guard.txt"))

    # Decided on the lists, not on the folder: an empty new folder must not
    # hide lists still in the old one (Indigo's review of PR #5). This
    # differs on purpose from the installer's rule, which follows
    # config.json: a contributor may keep only personal-guard.txt, and for
    # this guard the lists are what matter. A test pins the difference.
    if not has_lists(new) and has_lists(old):
        return old
    return new


class NotReadable(Exception):
    pass


def load_lists(cfg_dir):
    """(ids, personal values, patterns). Raises NotReadable when a list is named but unreadable."""
    ids, personal, patterns = set(), [], []
    cfg_path = os.path.join(cfg_dir, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                snap = json.load(f).get("properties_csv")
        except (OSError, ValueError) as e:
            raise NotReadable("config.json: %s" % e.__class__.__name__)
        if snap:
            snap = os.path.expanduser(snap)
            try:
                with open(snap, encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        for col in ID_COLUMNS:
                            ids.update(ID_TOKEN.findall(row.get(col) or ""))
            except OSError as e:
                raise NotReadable("the property snapshot config.json names: %s" % e.__class__.__name__)
            if not ids:
                raise NotReadable("the property snapshot has no ids")
    list_path = os.path.join(cfg_dir, "personal-guard.txt")
    if os.path.exists(list_path):
        try:
            with open(list_path, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        except OSError as e:
            raise NotReadable("personal-guard.txt: %s" % e.__class__.__name__)
        for n, ln in enumerate(lines, 1):
            if ln.startswith("re:"):
                try:
                    patterns.append(re.compile(ln[3:], re.I))
                except re.error:
                    raise NotReadable("personal-guard.txt: entry %d is not a valid pattern" % n)
            else:
                personal.append(ln)
    return ids, personal, patterns


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace", check=True).stdout


def commits_to_push(stdin_lines, remote_name):
    shas = []
    for line in stdin_lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha == ZERO:
            continue  # a deletion sends no content
        if remote_sha == ZERO:
            # a new branch: everything the TARGET remote is not known to have. Not
            # --remotes (every remote): a commit another remote holds is still new here.
            rng = git("rev-list", local_sha, "--not", "--remotes=%s" % remote_name).split()
        else:
            rng = git("rev-list", "%s..%s" % (remote_sha, local_sha)).split()
        shas.extend(s for s in rng if s not in shas)
    return shas


def added_lines(sha):
    """(path, line) for every line the commit adds, plus its message as path '(commit message)'."""
    out = [("(commit message)", ln) for ln in git("log", "-1", "--format=%B", sha).splitlines()]
    path = None
    for ln in git("show", "--format=", "--unified=0", "--no-color", "--no-ext-diff", sha).splitlines():
        if ln.startswith("+++ "):
            path = ln[6:] if ln.startswith("+++ b/") else None
        elif ln.startswith("+") and path:
            out.append((path, ln[1:]))
    return out


def findings(shas, ids, personal, patterns=()):
    lowered = [(p, p.lower()) for p in personal]
    found = []
    for sha in shas:
        for path, line in added_lines(sha):
            if ids and any(tok in ids for tok in ID_TOKEN.findall(line)):
                found.append((sha[:10], path, "a GA property or account id from your snapshot"))
            low = line.lower()
            if any(lp in low for _, lp in lowered) or any(rx.search(line) for rx in patterns):
                found.append((sha[:10], path, "a value from your personal-guard.txt"))
    return sorted(set(found))


def main():
    cfg = config_dir()
    try:
        ids, personal, patterns = load_lists(cfg)
    except NotReadable as e:
        print("PERSONAL-GUARD refused the push: a list is configured but could not be read (%s). "
              "Fix it, or push with --no-verify if you are sure." % e, file=sys.stderr)
        return 1
    if not ids and not personal and not patterns:
        print("*** personal guard not configured: no property snapshot and no personal-guard.txt in %s. "
              "Nothing personal was checked. ***" % cfg, file=sys.stderr)
        return 0
    remote_name = sys.argv[1] if len(sys.argv) > 1 else "origin"   # git passes the remote's name
    shas = commits_to_push(sys.stdin.read().splitlines(), remote_name)
    found = findings(shas, ids, personal, patterns)
    for sha, path, kind in found:
        print("PERSONAL-GUARD %s %s: %s" % (sha, path, kind), file=sys.stderr)
    summary = "%d commit(s) checked against %d snapshot ids, %d personal value%s and %d pattern%s" % (
        len(shas), len(ids), len(personal), "" if len(personal) == 1 else "s",
        len(patterns), "" if len(patterns) == 1 else "s")
    if found:
        print("PERSONAL-GUARD refused the push: %s. Remove the value (rewrite the commit if it is "
              "already committed) and push again." % summary, file=sys.stderr)
        return 1
    print("personal guard: %s, nothing found" % summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
