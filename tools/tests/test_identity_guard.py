"""The identity guard's controls (#1996), against real git pushes to a local
bare remote and against the CI mode. Every identity here is invented."""

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


if __name__ == "__main__":
    unittest.main()
