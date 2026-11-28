#!/usr/bin/env python3
"""Identity guard (#1996, #2001, #2003): refuses commits whose author or
committer email, and annotated tags whose tagger email, is not a seat identity
or a GitHub noreply address.

This repository is public, and a commit's email is published with it. A
clone with no identity set falls back to the machine's default, which can
carry the computer's name (user@machine.local); a personal mailbox is just as
public once pushed. Before this repository went public its history held both
(#1989), and neither of the other guards looks at identities.

Allowed:
  - a seat's plus-address, <name>+<seat>@<domain>: the identity the seats use
    in this project and in manyhands alike, so each can attribute its own
    work (#2001). It must have a non-empty name and tag, and a real domain:
    never .local, .localdomain, .localhost, .home.arpa, localhost or a
    bare host (a machine default).
  - any address ending @users.noreply.github.com.
  - GitHub's own noreply@github.com (the identity of its web merges).
A bare mailbox (no +<seat>) is refused.

Tags (#2003). An annotated tag is its own object, with a tagger name and
email that are published when the tag is pushed, and no commit check reads
it. Its tagger email is held to the same rule. A tag can point at another
tag; every tag object in such a chain is read. A lightweight tag has no
tagger: it is only a name for a commit, and commits are checked already. A
tag object with no tagger line at all publishes no identity and passes.

Three modes:
  pre-push (default)  reads git's pre-push lines on stdin and checks every
                      commit and every annotated tag the push would send.
                      Installed with the personal guard:
                      git config core.hooksPath tools/hooks
  --all               checks every commit reachable from HEAD, and every
                      annotated tag in the repository.
  --since <rev>       checks only the commits after <rev> (CI: what a branch
                      or pull request adds to main). Merge commits GitHub
                      makes on main are never re-checked, so a merge made on
                      GitHub can't turn main red. Earlier commits on main
                      that break the rule stay as they are, accepted. Tags
                      are not limited by <rev>: every annotated tag in the
                      repository is checked, because a release tag sits on a
                      commit main already has.

A refusal names the commit and which field, or the tag, never the address
or the name.

Exit codes: 0 every identity read is allowed; 1 refused; 2 the check could
not be made (git failed, or a tag could not be read). A failure is never a
pass: when git cannot answer, nothing was verified, and the guard says so
instead of reporting what it did manage to read.
"""
import re
import subprocess
import sys

ZERO = "0" * 40
SUFFIX = "@users.noreply.github.com"
GITHUB_ITSELF = "noreply@github.com"
FIX = ("Set this clone's identity before committing (or rebasing), as your "
       "seat:\n"
       "  git config user.name <Seat>\n"
       "  git config user.email <name>+<seat>@<domain>\n"
       "or a GitHub noreply address (<id>+<login>@users.noreply.github.com).\n"
       "Then rewrite the commits named above, make any tag named above again "
       "(git tag -d <tag>, then git tag -a <tag>), and push again.")
SEAT = re.compile(r"^[^@+\s]+\+[^@+\s]+@([a-z0-9-]+\.)+[a-z]{2,}$")
MACHINE_DOMAINS = (".local", ".localdomain", ".localhost", ".lan", ".home",
                   ".home.arpa", ".internal")
TAGGER = re.compile(r"^tagger [^<>]*<([^<>]*)>[^<>]*$")
REFUSED, FAILED = 1, 2


class GuardError(Exception):
    """The check could not be made. Never a pass, and not a refusal."""


def git(*args):
    """git's output, or GuardError when git did not succeed. Empty output
    from a git that failed must never be read as "nothing to check"."""
    try:
        r = subprocess.run(["git", *args], capture_output=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        raise GuardError("git %s could not be run" % args[0])
    if r.returncode != 0:
        raise GuardError("git %s exited %d" % (" ".join(args), r.returncode))
    return r.stdout


def allowed(email):
    e = email.strip().lower()
    if e.endswith(SUFFIX) or e == GITHUB_ITSELF:
        return True
    return bool(SEAT.match(e)) and not e.endswith(MACHINE_DOMAINS)


def pushed(lines):
    """(local sha, remote ref, remote sha) for each ref a push would write.
    git's line is <local ref> <local sha> <remote ref> <remote sha>. Only the
    first field can hold spaces (a source typed as main@{1 hour ago}), so
    the line is read from the right. A line that is not blank and still
    cannot be read is an error: skipping it would skip what it pushes."""
    for line in lines:
        if not line.strip():
            continue
        parts = line.rsplit(None, 3)
        if len(parts) != 4:
            raise GuardError("a pre-push line could not be read")
        if parts[1] != ZERO:    # a deletion sends nothing
            yield parts[1], parts[2], parts[3]


def commits_to_push(lines, remote):
    shas = []
    for local_sha, _, remote_sha in pushed(lines):
        if remote_sha == ZERO:
            rng = git("rev-list", local_sha, "--not",
                      "--remotes=%s" % remote).split()
        else:
            rng = git("rev-list", "%s..%s" % (remote_sha, local_sha)).split()
        shas.extend(s for s in rng if s not in shas)
    return shas


def tag_name(ref):
    return ref[len("refs/tags/"):] if ref.startswith("refs/tags/") else ref


def tag_chain(sha, name, into):
    """Adds (tag object sha, tag name) to `into` for the annotated tag at
    `sha` and for every tag object it wraps. A commit adds nothing."""
    while sha not in into and git("cat-file", "-t", sha).strip() == "tag":
        into[sha] = name
        target = [line.split(" ", 1)[1] for line in tag_headers(sha)
                  if line.startswith("object ")]
        if len(target) != 1:
            raise GuardError("tag object %s names no single target" % sha[:10])
        sha = target[0]


def tags_to_push(lines):
    tags = {}
    for local_sha, remote_ref, _ in pushed(lines):
        tag_chain(local_sha, tag_name(remote_ref), tags)
    return tags


def all_tags():
    tags = {}
    refs = git("for-each-ref", "--format=%(objecttype) %(objectname) %(refname)")
    for line in refs.splitlines():
        kind, sha, ref = line.split(" ", 2)
        if kind == "tag":
            tag_chain(sha, tag_name(ref), tags)
    return tags


def tag_headers(sha):
    """The header lines of a tag object: everything before its message."""
    return git("cat-file", "tag", sha).split("\n\n", 1)[0].splitlines()


def tagger_emails(sha):
    """The email of each tagger line of a tag object: one for a tag git
    made, none for a tag object written without a tagger. A tagger line that
    cannot be parsed is an error, because the guard cannot say what it would
    publish."""
    emails = []
    for line in tag_headers(sha):
        if line.startswith("tagger"):
            m = TAGGER.match(line)
            if not m:
                raise GuardError("the tagger line of tag object %s could not "
                                 "be read" % sha[:10])
            emails.append(m.group(1))
    return emails


def findings(shas):
    found = []
    for sha in shas:
        author, committer = git("log", "-1", "--format=%ae%n%ce",
                                sha).splitlines()[:2]
        for field, email in (("author", author), ("committer", committer)):
            if not allowed(email):
                found.append((sha[:10], field))
    return found


def tag_findings(tags):
    """(tag name, tag object sha) for each tag whose tagger is not allowed."""
    return [(name, sha[:10]) for sha, name in tags.items()
            if not all(allowed(e) for e in tagger_emails(sha))]


def check(argv):
    if "--all" in argv:
        shas = git("rev-list", "HEAD").split()
        tags = all_tags()
    elif "--since" in argv:
        base = argv[argv.index("--since") + 1]
        shas = git("rev-list", "%s..HEAD" % base).split()
        tags = all_tags()
    else:
        remote = argv[0] if argv else "origin"
        lines = sys.stdin.read().splitlines()
        shas = commits_to_push(lines, remote)
        tags = tags_to_push(lines)
    found = findings(shas)
    bad_tags = tag_findings(tags)
    for sha, field in found:
        print("IDENTITY-GUARD %s: the %s email is not a seat or noreply address"
              % (sha, field), file=sys.stderr)
    for name, sha in bad_tags:
        print("IDENTITY-GUARD tag %s (%s): the tagger email is not a seat or "
              "noreply address" % (name, sha), file=sys.stderr)
    if found or bad_tags:
        print("IDENTITY-GUARD refused: %d of %d commit(s) and %d of %d "
              "annotated tag(s) would publish a machine-default or bare "
              "mailbox address.\n%s"
              % (len({s for s, _ in found}), len(shas), len(bad_tags),
                 len(tags), FIX), file=sys.stderr)
        return REFUSED
    print("identity guard: %d commit(s) and %d annotated tag(s), all seat or "
          "noreply identities" % (len(shas), len(tags)), file=sys.stderr)
    return 0


def main(argv):
    try:
        return check(argv)
    except GuardError as e:
        print("IDENTITY-GUARD error: %s. The check could not be made, so "
              "nothing was verified: this is a failure, not a pass."
              % e, file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
