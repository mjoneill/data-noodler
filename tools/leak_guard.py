#!/usr/bin/env python3
"""Leak guard: refuse a tree that carries credentials, real reports, a project
notebook, a filled deployment profile, or someone's home folder.

Runs in CI on every push and pull request, over every TRACKED file. The
.gitignore is advice; `git add -f` and a renamed file both get past it, so
this checks names AND contents.

Everything here is generic on purpose. This repository is meant to be public,
so it cannot hold a list of what is private. Values that belong to one
maintainer (their property ids, their institution) are checked by the local
pre-push hook instead (tools/personal_guard.py), from a list that lives on
their own machine.

A finding names the rule and the place, never the matched value: a CI log on
a public repository is public too.

Usage:  python3 tools/leak_guard.py [--root DIR]
Exit:   0 clean, 1 findings, 2 could not run.
"""

import argparse
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import namedtuple

Finding = namedtuple("Finding", "rule path line why")

FIXTURES = "tests/fixtures/"

# --- rule: sensitive-file (by name) -----------------------------------------
# The names the .gitignore lists, plus the property snapshot and a bare
# config.json, which is what the installer writes per machine.
SENSITIVE_NAMES = (
    "*data-noodler-client*.json", "*data-noodler-credential*.json", "*ga-mcp-client*.json", "*-client.json", "*adc*.json", "*client_secret*.json",
    "application_default_credentials.json", "credentials.json", "config.json",
    "*.p12", "*.pem",
)

# --- rule: credential-content -----------------------------------------------
SECRET_SHAPES = (
    ("an OAuth client secret", re.compile(r"GOCSPX-[A-Za-z0-9_-]{10,}")),
    ("a Google API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("a Google refresh token", re.compile(r"1//0[0-9A-Za-z_-]{20,}")),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
# A credential's "type" ("authorized_user", "service_account") is not checked
# on its own: the tests hold placeholder credential JSON with that type. What
# makes a file a credential is a real-looking value under one of these keys.
SECRET_KEYS = ("refresh_token", "client_secret", "private_key")
KEY_VALUE = re.compile(r'"(%s)"\s*:\s*"([^"]*)"' % "|".join(SECRET_KEYS))

# --- rule: oauth-client-id ----------------------------------------------------
CLIENT_ID = re.compile(r"\b(\d{6,})-([a-z0-9]{8,})\.apps\.googleusercontent\.com\b")

# --- rule: analytics-output ---------------------------------------------------
REPORT_SUFFIXES = (".csv", ".xlsx", ".html", ".htm")

# --- rule: project-notebook (by name) -----------------------------------------
# The notebook the query skill keeps in a user's project. It holds findings
# about their data, so one that lands here is a leak whatever it says. The
# pattern keeps the stem, so a renamed copy ("... (1).md", "Copy of ...") is
# caught too. It is tried on every part of the path, the way the same pattern
# in .gitignore is, so a folder with that name counts as well.
NOTEBOOK_NAME = "*data-noodler-notebook*"

# --- rule: deployment-profile -------------------------------------------------
PROFILE_FIELDS = ("deployment_name", "maintainer", "maintainer_contact", "install_reports_to")

# --- rule: home-path ----------------------------------------------------------
# The folder names a document may use as an example. Anything else after
# /Users/, /home/ or C:\Users\ is treated as a real person's folder.
PLACEHOLDER_HOMES = {"x", "example", "Jane", "a", "you"}
# Case-insensitive: Windows and a default macOS volume both ignore case.
HOME = re.compile(r"(?:/Users/|/home/|[A-Za-z]:(?:\\{1,2})Users(?:\\{1,2}))([^/\\\s\"'`<>)\]},;:|*?]*)", re.I)


def _placeholder_value(value):
    v = value.strip()
    return (len(v) < 12 or v.startswith("<") or v.startswith("$")
            or any(w in v.lower() for w in ("example", "placeholder", "your", "redacted", "xxxx")))


def _placeholder_client_id(digits, tail):
    return (len(set(digits)) == 1 or "1234567890".startswith(digits[:10])
            or len(set(tail)) == 1 or "example" in tail)


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _in_fixtures(path):
    return path.startswith(FIXTURES) or ("/" + FIXTURES) in path


def scan_file(path, text):
    """Findings for one file that need only that file."""
    out = []
    name = posixpath.basename(path)
    lowered = name.lower()

    if not _in_fixtures(path) and any(fnmatch.fnmatch(lowered, p) for p in SENSITIVE_NAMES):
        out.append(Finding("sensitive-file", path, 0, "a credential or per-machine config file by its name"))

    if (lowered.endswith(REPORT_SUFFIXES) or "_outputs/" in path or path.startswith("_outputs/")) \
            and not _in_fixtures(path):
        out.append(Finding("analytics-output", path, 0, "report output outside tests/fixtures/"))

    if any(fnmatch.fnmatch(part, NOTEBOOK_NAME) for part in path.lower().split("/")) and not _in_fixtures(path):
        out.append(Finding("project-notebook", path, 0,
                           "a project notebook holds findings about someone's data; it belongs in their project"))

    if text is None:
        return out

    for why, rx in SECRET_SHAPES:
        for m in rx.finditer(text):
            out.append(Finding("credential-content", path, _line_of(text, m.start()), why))

    keyed = [m for m in KEY_VALUE.finditer(text) if not _placeholder_value(m.group(2))]
    for m in keyed:
        out.append(Finding("credential-content", path, _line_of(text, m.start()),
                           'a "%s" with a real-looking value' % m.group(1)))
    for m in CLIENT_ID.finditer(text):
        if not _placeholder_client_id(m.group(1), m.group(2)):
            out.append(Finding("oauth-client-id", path, _line_of(text, m.start()),
                               "a real-looking OAuth client id"))

    for m in HOME.finditer(text):
        folder = m.group(1)
        if not folder or folder.lower() in {p.lower() for p in PLACEHOLDER_HOMES} or folder[0] in "<$%{":
            continue
        out.append(Finding("home-path", path, _line_of(text, m.start()),
                           "a home folder that is not one of the placeholders %s" % sorted(PLACEHOLDER_HOMES)))
    return out


def _scan_profiles(files):
    out = []
    for path, text in files.items():
        if posixpath.basename(path) != "deployment.json":
            continue
        template = posixpath.join(posixpath.dirname(path), "deployment.template.json")
        if template not in files:
            out.append(Finding("deployment-profile", path, 0, "no deployment.template.json beside it"))
        try:
            profile = json.loads(text or "")
        except ValueError:
            out.append(Finding("deployment-profile", path, 0, "not readable JSON"))
            continue
        filled = [k for k in PROFILE_FIELDS if isinstance(profile, dict) and str(profile.get(k, "")).strip()]
        if not isinstance(profile, dict):
            out.append(Finding("deployment-profile", path, 0, "not a JSON object"))
        elif filled:
            out.append(Finding("deployment-profile", path, 0,
                               "a committed profile must be blank; filled: %s" % ", ".join(filled)))
    return out


def scan_tree(files):
    """files: {repo-relative posix path: text, or None for a binary file}."""
    out = []
    for path in sorted(files):
        out.extend(scan_file(path, files[path]))
    out.extend(_scan_profiles(files))
    return out


def format_finding(f):
    where = "%s:%d" % (f.path, f.line) if f.line else f.path
    return "LEAK-GUARD %s: %s (%s)" % (f.rule, where, f.why)


def tracked_files(root):
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed: %s" % r.stderr.decode(errors="replace").strip())
    files = {}
    for raw in r.stdout.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", errors="replace")
        try:
            with open(os.path.join(root, path), "rb") as fh:
                data = fh.read()
        except OSError:
            continue  # deleted in the working tree but still in the index
        files[path] = None if b"\0" in data[:8192] else data.decode("utf-8", errors="replace")
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    args = ap.parse_args(argv)
    try:
        files = tracked_files(args.root)
    except (RuntimeError, OSError) as e:
        print("LEAK-GUARD could not run: %s" % e, file=sys.stderr)
        return 2
    findings = scan_tree(files)
    for f in findings:
        print(format_finding(f))
    if findings:
        print("\n%d finding(s) in %d tracked files. Remove the file or the value; "
              "a placeholder from the rule's list passes." % (len(findings), len(files)))
        return 1
    print("leak guard: %d tracked files, no findings" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
