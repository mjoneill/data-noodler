#!/usr/bin/env python3
"""Identity guard (#1996): refuses commits whose author or committer email is
not a GitHub noreply address.

This repository is public, and a commit's email is published with it. A
clone with no identity set falls back to the machine's default, which can
carry the computer's name (user@machine.local); a personal mailbox is just as
public once pushed. Before this repository went public its history held both
(#1989), and neither of the other guards looks at identities.

Allowed: any address ending @users.noreply.github.com, and GitHub's own
noreply@github.com (the identity of its web merges).

Two modes:
  pre-push (default)  reads git's pre-push lines on stdin and checks every
                      commit the push would send. Installed with the personal
                      guard: git config core.hooksPath tools/hooks
  --all               checks every commit reachable from HEAD (CI).

A refusal names the commit and which field, never the address.
"""
import subprocess
import sys

ZERO = "0" * 40
SUFFIX = "@users.noreply.github.com"
GITHUB_ITSELF = "noreply@github.com"
FIX = ("Set this clone's identity before committing (or rebasing):\n"
       "  git config user.email <id>+<login>@users.noreply.github.com\n"
       "GitHub shows yours under Settings > Emails. Then rewrite the commits "
       "named above and push again.")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def allowed(email):
    e = email.strip().lower()
    return e.endswith(SUFFIX) or e == GITHUB_ITSELF


def commits_to_push(lines, remote):
    shas = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if remote_sha == ZERO:
            rng = git("rev-list", local_sha, "--not",
                      "--remotes=%s" % remote).split()
        else:
            rng = git("rev-list", "%s..%s" % (remote_sha, local_sha)).split()
        shas.extend(s for s in rng if s not in shas)
    return shas


def findings(shas):
    found = []
    for sha in shas:
        author, committer = git("log", "-1", "--format=%ae%n%ce",
                                sha).splitlines()[:2]
        for field, email in (("author", author), ("committer", committer)):
            if not allowed(email):
                found.append((sha[:10], field))
    return found


def main(argv):
    if "--all" in argv:
        shas = git("rev-list", "HEAD").split()
    else:
        remote = argv[0] if argv else "origin"
        shas = commits_to_push(sys.stdin.read().splitlines(), remote)
    found = findings(shas)
    for sha, field in found:
        print("IDENTITY-GUARD %s: the %s email is not a GitHub noreply address"
              % (sha, field), file=sys.stderr)
    if found:
        print("IDENTITY-GUARD refused: %d of %d commit(s) would publish a "
              "non-noreply address.\n%s" % (len({s for s, _ in found}),
                                            len(shas), FIX), file=sys.stderr)
        return 1
    print("identity guard: %d commit(s), all noreply" % len(shas),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
