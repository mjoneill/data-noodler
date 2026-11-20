#!/usr/bin/env python3
"""Move an install's home from ~/.config/ga-mcp to ~/.config/data-noodler.

#1999 slice 2. Installs from before the product had one name live in the old
home. Everything keeps working there (every reader falls back to it), so this
step is never forced. It is taken once, on the person's yes, because it also
renames their Google sign-in files.

    python migrate_home.py            describe the move; change nothing
    python migrate_home.py --yes      make the move (only after the person said yes)
    python migrate_home.py --undo     put everything back as it was

What the move does, in order:
  1. Refuses if the new home already exists, if the analytics-mcp Python
     lives inside the old home (a venv holds absolute paths, so moving it
     breaks it), if a sign-in file's new name is taken, or if any of our
     servers are running (quit every app that uses them first).
  2. Renames the folder. Same parent, so it is one atomic rename.
  3. Renames the two sign-in files to their Data Noodler names, but only
     when they carry this package's old default names.
  4. Rewrites config.json so every path into the old home, and both sign-in
     paths, point at the new ones. The original is kept beside it as
     config.json.ga-backup-<stamp>.
  5. Writes migration-record.json in the new home, which --undo reads.

After a move the apps still point at the old launchers. The installing
agent re-runs install.py (re-registers every app), copy_skills.py, and
re-adds the Codex marketplace from the new path; it then runs verify.py.

Standard library only.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import home as dn_home  # noqa: E402

RECORD = "migration-record.json"
# Old default name -> new name, for the two sign-in files bootstrap_config
# names. A person's own names are left as they are.
FILE_RENAMES = {
    "adc_file": ("adc-ga-" "personal.json", "data-noodler-credential.json"),
    "oauth_client_file": ("ga-" "mcp-client.json", "data-noodler-client.json"),
}


class MigrateError(Exception):
    """A refusal or failure, worded for the person reading it."""


def _expand(value):
    return os.path.expanduser(value) if isinstance(value, str) else value


# #1999 slice 1 renamed the plugin and skill folders the consent script
# lives in; a config.json from before names the old ones.
_OLD_SCRIPT_DIRS = "/plugins/ga-" "analytics/skills/google-" "analytics/"
_NEW_SCRIPT_DIRS = "/plugins/data-noodler/skills/data-noodler/"


def _rewrite(value, old, new, tilde_old, tilde_new):
    if not isinstance(value, str):
        return value
    value = value.replace(_OLD_SCRIPT_DIRS, _NEW_SCRIPT_DIRS)
    for a, b in ((old, new), (tilde_old, tilde_new)):
        if value == a or value.startswith(a + os.sep) or value.startswith(a + "/"):
            return b + value[len(a):]
    return value


def plan(home=None):
    """What a move would do. Changes nothing.

    {"action": "move"|"nothing"|"refuse", "reason", "old", "new",
     "files": [(key, (from, to))], "config": {key: (before, after)}}
    """
    old, new = dn_home.legacy_home(home), dn_home.new_home(home)
    out = {"action": "nothing", "reason": "", "old": old, "new": new,
           "files": [], "config": {}}
    old_cfg = os.path.join(old, "config.json")
    if not os.path.isfile(old_cfg):
        out["reason"] = f"no install at {old}; nothing to move"
        return out
    if os.path.exists(new):
        out.update(action="refuse", reason=(
            f"both {old} and {new} exist. Nothing was moved. Look at both, "
            "keep the one the apps use, and move the other aside by hand."))
        return out
    try:
        with open(old_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as exc:
        out.update(action="refuse", reason=f"could not read {old_cfg} ({exc})")
        return out
    if not isinstance(cfg, dict):
        out.update(action="refuse", reason=f"{old_cfg} is not a JSON object")
        return out

    venv = _expand(cfg.get("venv_python") or "")
    if venv and os.path.abspath(venv).startswith(os.path.abspath(old) + os.sep):
        out.update(action="refuse", reason=(
            f"the analytics-mcp Python ({venv}) lives inside {old}, in a venv "
            "that holds absolute paths and would break if moved. The old home "
            "keeps working; leave it, or rebuild the venv outside it first."))
        return out

    tilde_old = "~/.config/" + dn_home.LEGACY_HOME_NAME
    tilde_new = "~/.config/" + dn_home.HOME_NAME
    for key, (old_name, new_name) in FILE_RENAMES.items():
        path = _expand(cfg.get(key) or "")
        if path and os.path.basename(path) == old_name and os.path.isfile(path):
            target = os.path.join(os.path.dirname(path), new_name)
            if os.path.exists(target):
                out.update(action="refuse", reason=(
                    f"{target} already exists, so {path} cannot take that "
                    "name. Nothing was moved."))
                return out
            out["files"].append((key, (path, target)))

    renamed = dict(out["files"])
    for key, value in cfg.items():
        if key in renamed:
            after = renamed[key][1]
        elif isinstance(value, list):
            after = [_rewrite(v, old, new, tilde_old, tilde_new) for v in value]
        else:
            after = _rewrite(value, old, new, tilde_old, tilde_new)
        if after != value:
            out["config"][key] = (value, after)
    out["action"] = "move"
    return out


def _default_running(home):
    """Our servers' command lines, as upgrade.py finds them."""
    import upgrade
    old = dn_home.legacy_home(home)
    try:
        with open(os.path.join(old, "config.json"), encoding="utf-8") as f:
            venv_python = _expand(json.load(f).get("venv_python") or "")
    except (OSError, ValueError):
        venv_python = ""
    venv_dir = os.path.dirname(os.path.dirname(venv_python)) if venv_python else old
    return upgrade.running_servers(venv_dir, old, sys.platform)


def migrate(home=None, running=None):
    """Make the move. Returns the record written. Raises MigrateError."""
    p = plan(home)
    if p["action"] == "nothing":
        return None
    if p["action"] == "refuse":
        raise MigrateError(p["reason"])
    hits = (running or (lambda: _default_running(home)))()
    if hits:
        raise MigrateError(
            "these are still running from the old home -- fully quit every "
            "app that uses them, then re-run:\n  " + "\n  ".join(hits))

    old, new = p["old"], p["new"]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.rename(old, new)
    done = []
    try:
        for _key, (src, dst) in p["files"]:
            os.rename(src, dst)
            done.append((src, dst))
        cfg_path = os.path.join(new, "config.json")
        backup = f"{cfg_path}.ga-backup-{stamp}"
        shutil.copy2(cfg_path, backup)
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        for key, (_before, after) in p["config"].items():
            cfg[key] = after
        text = json.dumps(cfg, indent=2) + "\n"
        json.loads(text)
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(text)
        record = {"stamp": stamp, "old": old, "new": new,
                  "files": done, "config_backup": backup}
        with open(os.path.join(new, RECORD), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return record
    except Exception:
        # Every step undone, config.json included: rolled back without it,
        # the old home's config named the new home and the new file names
        # (Indigo's review of PR #5).
        cfg_path = os.path.join(new, "config.json")
        backup = f"{cfg_path}.ga-backup-{stamp}"
        if os.path.exists(backup):
            shutil.copy2(backup, cfg_path)
            os.remove(backup)
        for src, dst in reversed(done):
            os.rename(dst, src)
        os.rename(new, old)
        raise


def undo(home=None):
    """Reverse a move, from the record it left. Raises MigrateError."""
    new = dn_home.new_home(home)
    path = os.path.join(new, RECORD)
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError) as exc:
        raise MigrateError(f"no readable move record at {path} ({exc}); "
                           "nothing to undo")
    old = record["old"]
    if os.path.exists(old):
        raise MigrateError(f"{old} exists again; not undoing over it")
    cfg_path = os.path.join(new, "config.json")
    shutil.copy2(record["config_backup"], cfg_path)
    for src, dst in reversed(record["files"]):
        os.rename(dst, src)
    os.remove(path)
    os.rename(new, old)
    return record


def _describe(p):
    lines = [f"Move {p['old']}\n  -> {p['new']}"]
    for key, (src, dst) in p["files"]:
        lines.append(f"Rename the {key.replace('_', ' ')}:\n  {src}\n  -> {dst}")
    for key, (before, after) in p["config"].items():
        if key not in dict(p["files"]):
            lines.append(f"config.json {key}: {before} -> {after}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--yes", action="store_true",
                   help="make the move -- only after the person said yes")
    g.add_argument("--undo", action="store_true")
    args = ap.parse_args()
    try:
        if args.undo:
            r = undo()
            print(f"Undone: {r['new']} is back at {r['old']}, with the "
                  "sign-in files' old names. Re-run install.py to point the "
                  "apps at it again.")
            return 0
        p = plan()
        if p["action"] == "nothing":
            print(p["reason"])
            return 0
        if p["action"] == "refuse":
            print(f"NOT MOVED: {p['reason']}")
            return 1
        if not args.yes:
            print("This would:\n" + _describe(p))
            print("\nNothing has been changed. It renames the person's "
                  "sign-in files, so ask them first; on a yes, re-run with "
                  "--yes.")
            return 0
        migrate()
        print("Moved:\n" + _describe(p))
        print("\nNext: re-run install.py, copy_skills.py and verify.py, and "
              "re-add the Codex marketplace from the new path. Undo with "
              "--undo.")
        return 0
    except MigrateError as exc:
        print(f"NOT MOVED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
