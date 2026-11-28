"""The identity guard's controls (#1996), against real git pushes to a local
bare remote and against the CI mode. Every identity here is invented.

The tag controls (#2003) are written against one trap: a refusal can
masquerade as coverage. A push that fails because git itself failed looks,
to a test that only asks for "non-zero", exactly like a guard that refused.
So each refusal here is pinned to the guard's own sentence and its own exit
code (1), each pass to the count of tags the guard says it read, and a git
failure to a third outcome (exit 2) that is neither."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
GUARD = os.path.join(TOOLS, "identity_guard.py")
HOOKS = os.path.join(TOOLS, "hooks")

NOREPLY = "12345+someone@users.noreply.github.com"
MACHINE = "someone@someones-Mac-mini.local"
# #2001: a seat's plus-address is the project's identity (as in manyhands);
# a bare mailbox is not.
SEAT = "someone+seat@" + "example.com"
MAILBOX = "someone@" + "example.com"
MACHINE_TAGGED = "someone+seat@someones-Mac-mini.local"
ZERO = "0" * 40

# The guard's own words (#2003). A test that only sees a non-zero exit cannot
# tell these three outcomes apart; these strings and the exit codes can.
TAGGER_REFUSAL = "the tagger email is not a seat or noreply address"
ERROR = "IDENTITY-GUARD error"
CLEAN = "all seat or noreply identities"
REFUSED, FAILED = 1, 2


def git(cwd, *args, check=True, env=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check, env=env)


class Repo:
    """A work clone with a bare 'origin' and the real pre-push hook."""

    def __init__(self, root):
        self.bare = os.path.join(root, "origin.git")
        self.work = os.path.join(root, "work")
        git(root, "init", "-q", "--bare", self.bare)
        git(root, "init", "-q", "-b", "main", self.work)
        git(self.work, "config", "commit.gpgsign", "false")
        git(self.work, "remote", "add", "origin", self.bare)
        os.makedirs(os.path.join(self.work, "tools", "hooks"))
        for name in ("identity_guard.py", "personal_guard.py"):
            shutil.copy(os.path.join(TOOLS, name),
                        os.path.join(self.work, "tools", name))
        shutil.copy(os.path.join(HOOKS, "pre-push"),
                    os.path.join(self.work, "tools", "hooks", "pre-push"))
        git(self.work, "config", "core.hooksPath", "tools/hooks")
        # An empty personal-guard config folder: that guard warns and passes.
        self.env = dict(os.environ,
                        DATA_NOODLER_PERSONAL_GUARD_CONFIG_DIR=os.path.join(root, "cfg"))
        self.commit("README.md", "hello\n", "first", NOREPLY)
        r = self.push()
        assert r.returncode == 0, r.stderr

    def commit(self, path, text, message, author, committer=None):
        with open(os.path.join(self.work, path), "w") as f:
            f.write(text)
        git(self.work, "add", "-A")
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="Seat", GIT_AUTHOR_EMAIL=author,
                   GIT_COMMITTER_NAME="Seat",
                   GIT_COMMITTER_EMAIL=committer or author)
        git(self.work, "commit", "-q", "-m", message, env=env)

    def push(self):
        return git(self.work, "push", "-q", "origin", "HEAD:main",
                   check=False, env=self.env)

    def tag(self, name, tagger=None, target="HEAD", tagger_name="Seat"):
        """An annotated tag made by `tagger`, or a lightweight one when
        `tagger` is None. Returns the sha the tag's ref holds."""
        git(self.work, "config", "tag.gpgsign", "false")
        if tagger is None:
            git(self.work, "tag", name, target)
        else:
            env = dict(os.environ, GIT_COMMITTER_NAME=tagger_name,
                       GIT_COMMITTER_EMAIL=tagger)
            git(self.work, "tag", "-a", "-m", "a release", name, target,
                env=env)
        return self.rev("refs/tags/" + name)

    def rev(self, name):
        return git(self.work, "rev-parse", "--verify", name).stdout.strip()

    def push_tag(self, name):
        return git(self.work, "push", "-q", "origin", "refs/tags/" + name,
                   check=False, env=self.env)

    def type_on_remote(self, name):
        """What the remote holds under this tag name: 'tag' (annotated),
        'commit' (lightweight), or '' when it has no such tag."""
        return git(self.bare, "for-each-ref", "--format=%(objecttype)",
                   "refs/tags/" + name).stdout.strip()

    def tagger_of(self, name):
        """(object type, tagger email) of the local tag, read back from git
        so a fixture that did not come out as intended fails the test."""
        out = git(self.work, "for-each-ref",
                  "--format=%(objecttype) %(taggeremail)",
                  "refs/tags/" + name).stdout.strip()
        kind, _, email = out.partition(" ")
        return kind, email.strip("<>")

    def guard(self, *args, stdin="", env=None):
        """The guard run directly, so its own exit code is visible (git push
        reports 1 for any hook failure)."""
        return subprocess.run([sys.executable, "-I", GUARD, *args],
                              cwd=self.work, input=stdin,
                              capture_output=True, text=True,
                              env=env or self.env)

    def pre_push_line(self, name):
        """The line git hands the pre-push hook for a new tag."""
        ref = "refs/tags/" + name
        return "%s %s %s %s\n" % (ref, self.rev(ref), ref, ZERO)

    def lose_object(self, sha):
        """Deletes one loose object, so git can no longer read it."""
        path = os.path.join(self.work, ".git", "objects", sha[:2], sha[2:])
        assert os.path.isfile(path), "not a loose object: the fixture is wrong"
        os.remove(path)


class TestPrePush(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = Repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_noreply_commit_goes_through(self):
        self.repo.commit("a.txt", "a\n", "ok", NOREPLY)
        r = self.repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_machine_name_author_is_refused(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        r = self.repo.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IDENTITY-GUARD", r.stderr)

    def test_a_mailbox_committer_is_refused_even_with_a_noreply_author(self):
        # The #1989 case: a rebase restamped only the committer.
        self.repo.commit("a.txt", "a\n", "bad", NOREPLY, committer=MAILBOX)
        r = self.repo.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("committer", r.stderr)

    def test_the_refusal_never_prints_the_address(self):
        self.repo.commit("a.txt", "a\n", "bad", MAILBOX)
        r = self.repo.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(MAILBOX, r.stderr)
        self.assertNotIn("example.com", r.stderr)

    def test_the_refusal_says_how_to_fix_it(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        r = self.repo.push()
        self.assertIn("+<seat>@", r.stderr)
        self.assertIn("users.noreply.github.com", r.stderr)

    def test_a_seat_plus_address_goes_through(self):
        # #2001: the same identity the seats use in manyhands.
        self.repo.commit("a.txt", "a\n", "ok", SEAT)
        r = self.repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_bare_mailbox_author_is_refused(self):
        self.repo.commit("a.txt", "a\n", "bad", MAILBOX)
        r = self.repo.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IDENTITY-GUARD", r.stderr)

    def test_a_machine_name_is_refused_even_with_a_tag(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE_TAGGED)
        r = self.repo.push()
        self.assertNotEqual(r.returncode, 0)


class TestAllowed(unittest.TestCase):
    """The rule itself, address by address (#2001)."""

    def setUp(self):
        sys.path.insert(0, TOOLS)
        import identity_guard
        self.allowed = identity_guard.allowed

    def test_accepted(self):
        # A registrable domain passes; a single-label hostname (below) does not.
        for e in (NOREPLY, "noreply@github.com", SEAT,
                  "Someone+Seat@Example.COM", "someone+seat@host.example"):
            with self.subTest(e):
                self.assertTrue(self.allowed(e))

    def test_refused(self):
        for e in (MAILBOX, MACHINE, MACHINE_TAGGED, "someone+@example.com",
                  "+seat@example.com", "someone+seat@localhost",
                  "someone+seat@host", "someone+seat@box.localdomain",
                  "someone+seat@foo.localhost", "someone+seat@printer.home.arpa", ""):
            with self.subTest(e):
                self.assertFalse(self.allowed(e))


class TestCiMode(unittest.TestCase):
    """--all checks every commit reachable from HEAD; --since (what CI runs)
    checks only the commits a branch or pull request adds."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = Repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _ci(self):
        return subprocess.run([sys.executable, "-I", GUARD, "--all"],
                              cwd=self.repo.work, capture_output=True,
                              text=True)

    def test_a_clean_history_passes(self):
        r = self._ci()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_one_bad_commit_anywhere_fails(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        self.repo.commit("b.txt", "b\n", "ok", NOREPLY)
        r = self._ci()
        self.assertNotEqual(r.returncode, 0)

    def test_githubs_own_merge_identity_is_allowed(self):
        self.repo.commit("a.txt", "a\n", "merge button", NOREPLY,
                         committer="noreply@github.com")
        r = self._ci()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_since_checks_only_the_new_commits(self):
        self.repo.commit("a.txt", "a\n", "old, accepted", MACHINE)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo.work,
                              capture_output=True, text=True).stdout.strip()
        self.repo.commit("b.txt", "b\n", "new", NOREPLY)
        ok = subprocess.run([sys.executable, "-I", GUARD, "--since", base],
                            cwd=self.repo.work, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.repo.commit("c.txt", "c\n", "new and bad", MACHINE)
        bad = subprocess.run([sys.executable, "-I", GUARD, "--since", base],
                             cwd=self.repo.work, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)


class TestTagsPrePush(unittest.TestCase):
    """#2003: an annotated tag is its own object with its own tagger, and a
    push publishes it. Real tags, pushed to a real bare remote through the
    real hook."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = Repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def assertRefusedByTheGuard(self, r, name):
        self.assertNotEqual(r.returncode, 0,
                            "the push went through: nothing read the tagger")
        self.assertIn("IDENTITY-GUARD tag %s" % name, r.stderr)
        self.assertIn(TAGGER_REFUSAL, r.stderr)
        self.assertNotIn(ERROR, r.stderr)
        self.assertEqual(self.repo.type_on_remote(name), "",
                         "the tag reached the remote")

    def test_a_tag_made_under_a_machine_identity_is_refused(self):
        self.repo.tag("v1.0", MACHINE)
        self.assertEqual(self.repo.tagger_of("v1.0"), ("tag", MACHINE))
        self.assertRefusedByTheGuard(self.repo.push_tag("v1.0"), "v1.0")

    def test_the_refusal_is_the_guards_own_exit_code(self):
        # git push answers 1 whatever the hook did. Run on the line the hook
        # is handed, the guard itself must answer "refused", not "failed".
        self.repo.tag("v1.0", MACHINE)
        r = self.repo.guard("origin", stdin=self.repo.pre_push_line("v1.0"))
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("IDENTITY-GUARD tag v1.0", r.stderr)
        self.assertIn(TAGGER_REFUSAL, r.stderr)
        self.assertNotIn(ERROR, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_tag_made_under_a_bare_mailbox_is_refused(self):
        self.repo.tag("v1.0", MAILBOX)
        self.assertEqual(self.repo.tagger_of("v1.0"), ("tag", MAILBOX))
        self.assertRefusedByTheGuard(self.repo.push_tag("v1.0"), "v1.0")

    def test_only_the_tagger_decides(self):
        # Two tags on the same, already pushed commit. The only difference
        # between them is who made them, so that is what the guard read.
        self.repo.tag("bad", MACHINE)
        self.repo.tag("good", SEAT)
        self.assertRefusedByTheGuard(self.repo.push_tag("bad"), "bad")
        r = self.repo.push_tag("good")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.type_on_remote("good"), "tag")

    def test_an_accepted_tagger_goes_through_and_was_read(self):
        for name, tagger in (("v1.0", SEAT), ("v1.1", NOREPLY)):
            with self.subTest(tagger):
                self.repo.tag(name, tagger)
                self.assertEqual(self.repo.tagger_of(name), ("tag", tagger))
                r = self.repo.push_tag(name)
                self.assertEqual(r.returncode, 0, r.stderr)
                # The pass says how many tags it read: a guard that looked
                # at none cannot print this line.
                self.assertIn("1 annotated tag(s)", r.stderr)
                self.assertIn(CLEAN, r.stderr)
                self.assertEqual(self.repo.type_on_remote(name), "tag")

    def test_a_lightweight_tag_goes_through(self):
        # No tagger: it is only a name for a commit that is checked already.
        self.repo.tag("v1.0")
        self.assertEqual(self.repo.tagger_of("v1.0"), ("commit", ""))
        r = self.repo.push_tag("v1.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 annotated tag(s)", r.stderr)
        self.assertEqual(self.repo.type_on_remote("v1.0"), "commit")

    def test_a_lightweight_tag_on_a_bad_commit_is_refused_for_the_commit(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        self.repo.tag("v1.0")
        r = self.repo.push_tag("v1.0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("the author email is not a seat or noreply address",
                      r.stderr)
        self.assertNotIn(TAGGER_REFUSAL, r.stderr)
        self.assertEqual(self.repo.type_on_remote("v1.0"), "")

    def test_a_tag_and_its_new_commit_are_both_checked(self):
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        self.repo.tag("v1.0", MAILBOX)
        r = self.repo.guard("origin", stdin=self.repo.pre_push_line("v1.0"))
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("the author email", r.stderr)
        self.assertIn(TAGGER_REFUSAL, r.stderr)
        self.assertIn("1 of 1 commit(s) and 1 of 1 annotated tag(s)", r.stderr)

    def test_a_bad_tag_wrapped_in_a_good_one_is_refused(self):
        # A tag can point at another tag, and pushing the outer one sends
        # both objects.
        inner = self.repo.tag("inner", MACHINE)
        outer = self.repo.tag("outer", SEAT, target="refs/tags/inner")
        self.assertNotEqual(inner, outer)
        r = self.repo.guard("origin", stdin=self.repo.pre_push_line("outer"))
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("IDENTITY-GUARD tag outer (%s)" % inner[:10], r.stderr)
        self.assertIn("1 of 2 annotated tag(s)", r.stderr)
        self.assertRefusedByTheGuard(self.repo.push_tag("outer"), "outer")

    def test_the_refusal_never_prints_the_tagger(self):
        self.repo.tag("v1.0", MAILBOX, tagger_name="Somebody Particular")
        r = self.repo.push_tag("v1.0")
        self.assertIn(TAGGER_REFUSAL, r.stderr)
        self.assertNotIn(MAILBOX, r.stderr)
        self.assertNotIn("example.com", r.stderr)
        self.assertNotIn("Somebody", r.stderr)

    def test_the_refusal_says_how_to_fix_a_tag(self):
        self.repo.tag("v1.0", MACHINE)
        r = self.repo.push_tag("v1.0")
        self.assertIn("+<seat>@", r.stderr)
        self.assertIn("git tag -a", r.stderr)


class TestTagsCiMode(unittest.TestCase):
    """#2003: both CI modes read every annotated tag the checkout holds."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = Repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_all_refuses_a_bad_tagger(self):
        self.repo.tag("v1.0", MACHINE)
        r = self.repo.guard("--all")
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("IDENTITY-GUARD tag v1.0", r.stderr)
        self.assertIn(TAGGER_REFUSAL, r.stderr)

    def test_all_passes_accepted_and_lightweight_tags_and_counts_them(self):
        self.repo.tag("v1.0", SEAT)
        self.repo.tag("v1.1", NOREPLY)
        self.repo.tag("light")
        r = self.repo.guard("--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 annotated tag(s)", r.stderr)
        self.assertIn(CLEAN, r.stderr)

    def test_since_reads_every_tag_even_with_no_new_commit(self):
        # What CI runs. A release tag sits on a commit main already has, so
        # limiting tags to the new commits would miss exactly that tag.
        self.repo.tag("v1.0", MACHINE)
        r = self.repo.guard("--since", "HEAD")
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("IDENTITY-GUARD tag v1.0", r.stderr)
        self.assertIn("0 of 0 commit(s) and 1 of 1 annotated tag(s)", r.stderr)

    def test_since_passes_an_accepted_tag_and_counts_it(self):
        self.repo.tag("v1.0", SEAT)
        r = self.repo.guard("--since", "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 commit(s) and 1 annotated tag(s)", r.stderr)


class TestAFailureIsNotAPass(unittest.TestCase):
    """#2003: when git cannot answer, the guard has checked nothing. That is
    reported as an error with its own exit code (2), distinct both from a
    refusal (1) and from a clean pass (0)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = Repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def assertFailed(self, r):
        self.assertEqual(r.returncode, FAILED, r.stderr)
        self.assertIn(ERROR, r.stderr)
        self.assertNotIn(CLEAN, r.stderr)
        self.assertNotIn(TAGGER_REFUSAL, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_an_unreadable_tag_fails_the_pre_push_check(self):
        sha = self.repo.tag("v1.0", SEAT)
        line = self.repo.pre_push_line("v1.0")
        ok = self.repo.guard("origin", stdin=line)
        self.assertEqual(ok.returncode, 0, ok.stderr)   # readable: a pass
        self.repo.lose_object(sha)
        self.assertFailed(self.repo.guard("origin", stdin=line))

    def test_an_unreadable_tag_fails_the_ci_check(self):
        sha = self.repo.tag("v1.0", SEAT)
        for mode in (("--all",), ("--since", "HEAD")):
            ok = self.repo.guard(*mode)
            self.assertEqual(ok.returncode, 0, ok.stderr)
        self.repo.lose_object(sha)
        for mode in (("--all",), ("--since", "HEAD")):
            with self.subTest(mode):
                self.assertFailed(self.repo.guard(*mode))

    def test_a_push_line_naming_an_unknown_object_fails_the_check(self):
        line = "refs/tags/v1.0 %s refs/tags/v1.0 %s\n" % ("1" * 40, ZERO)
        self.assertFailed(self.repo.guard("origin", stdin=line))

    def test_a_push_line_with_spaces_in_its_source_is_still_checked(self):
        # git hands the hook the source as it was typed, and a revision such
        # as main@{1 hour ago} has spaces in it. Such a line used to be
        # skipped whole, so what it pushed was never read.
        self.repo.tag("v1.0", MACHINE)
        line = "v1.0@{0 seconds ago} %s refs/tags/v1.0 %s\n" % (
            self.repo.rev("refs/tags/v1.0"), ZERO)
        r = self.repo.guard("origin", stdin=line)
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn(TAGGER_REFUSAL, r.stderr)
        self.repo.commit("a.txt", "a\n", "bad", MACHINE)
        line = "main@{0 seconds ago} %s refs/heads/topic %s\n" % (
            self.repo.rev("HEAD"), ZERO)
        r = self.repo.guard("origin", stdin=line)
        self.assertEqual(r.returncode, REFUSED, r.stderr)
        self.assertIn("the author email", r.stderr)

    def test_a_push_line_that_cannot_be_read_fails_the_check(self):
        for line in ("not a push line\n", "refs/heads/main abc\n"):
            with self.subTest(line):
                self.assertFailed(self.repo.guard("origin", stdin=line))

    def test_nothing_to_push_is_a_pass(self):
        # The hook hands the guard one blank line when a push sends nothing.
        r = self.repo.guard("origin", stdin="\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 commit(s) and 0 annotated tag(s)", r.stderr)

    def test_every_git_call_is_checked(self):
        # A stand-in git that exits 97, printing nothing, for one named
        # subcommand and is the real git for the rest. Empty output with a
        # failing exit code must never be read as "nothing to check".
        real = shutil.which("git")
        self.assertTrue(real)
        shim = os.path.join(self.root, "shim")
        os.makedirs(shim)
        with open(os.path.join(shim, "git"), "w") as f:
            f.write('#!/bin/sh\n'
                    'if [ "$1" = "$BROKEN_GIT_SUBCOMMAND" ]; then exit 97; fi\n'
                    'exec "%s" "$@"\n' % real)
        os.chmod(os.path.join(shim, "git"), 0o755)
        self.repo.tag("v1.0", SEAT)
        line = self.repo.pre_push_line("v1.0")
        self.repo.commit("a.txt", "a\n", "ok", NOREPLY)

        def env(broken):
            return dict(self.repo.env, BROKEN_GIT_SUBCOMMAND=broken,
                        PATH=shim + os.pathsep + os.environ["PATH"])

        runs = {"--all": lambda e: self.repo.guard("--all", env=e),
                "pre-push": lambda e: self.repo.guard(
                    "origin", env=e,
                    stdin=line + "refs/heads/main %s refs/heads/main %s\n"
                    % (self.repo.rev("HEAD"), ZERO))}
        for mode, run in runs.items():
            # Through the stand-in with nothing broken: a clean pass, so the
            # failures below come from the break and not from the stand-in.
            ok = run(env("none"))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("1 annotated tag(s)", ok.stderr)
            for broken in ("rev-list", "log", "for-each-ref", "cat-file"):
                if (mode, broken) == ("pre-push", "for-each-ref"):
                    continue    # that mode lists no refs
                with self.subTest(mode=mode, broken=broken):
                    self.assertFailed(run(env(broken)))

    def test_a_tagger_line_that_cannot_be_parsed_fails_the_check(self):
        # A hand-made tag object whose tagger line has no <email>. The guard
        # cannot tell what it would publish, and says so.
        body = ("object %s\ntype commit\ntag odd\ntagger nobody at all\n"
                "\nodd\n" % self.repo.rev("HEAD"))
        sha = subprocess.run(
            ["git", "hash-object", "-t", "tag", "-w", "--stdin", "--literally"],
            cwd=self.repo.work, input=body, capture_output=True, text=True,
            check=True).stdout.strip()
        git(self.repo.work, "update-ref", "refs/tags/odd", sha)
        self.assertEqual(
            git(self.repo.work, "cat-file", "-t", sha).stdout.strip(), "tag")
        self.assertFailed(self.repo.guard("--all"))
        self.assertFailed(
            self.repo.guard("origin", stdin=self.repo.pre_push_line("odd")))

    def test_a_tag_with_no_tagger_line_publishes_no_identity(self):
        body = ("object %s\ntype commit\ntag old\n\nold\n"
                % self.repo.rev("HEAD"))
        sha = subprocess.run(
            ["git", "hash-object", "-t", "tag", "-w", "--stdin", "--literally"],
            cwd=self.repo.work, input=body, capture_output=True, text=True,
            check=True).stdout.strip()
        git(self.repo.work, "update-ref", "refs/tags/old", sha)
        r = self.repo.guard("--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 annotated tag(s)", r.stderr)


if __name__ == "__main__":
    unittest.main()
