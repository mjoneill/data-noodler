"""The personal guard's controls, against real git pushes to a local bare
remote. Every value here is invented; the guard's own list lives only in a
temporary config folder."""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
GUARD = os.path.join(TOOLS, "personal_guard.py")
HOOKS = os.path.join(TOOLS, "hooks")

PROPERTY_ID = "987" + "654" + "321"
ACCOUNT_ID = "555" + "444" + "33"
PERSONAL = "Acme " + "Polytechnic"


def git(cwd, *args, check=True, env=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, env=env)


class Repo:
    """A work clone with a bare 'origin', the guard installed as its pre-push hook."""

    def __init__(self, root, config_dir):
        self.bare = os.path.join(root, "origin.git")
        self.work = os.path.join(root, "work")
        git(root, "init", "-q", "--bare", self.bare)
        git(root, "init", "-q", "-b", "main", self.work)
        # A noreply identity: the same pre-push hook runs the identity guard (#1996).
        for k, v in (("user.name", "t"), ("user.email", "1+t@users.noreply.github.com"),
                     ("commit.gpgsign", "false")):
            git(self.work, "config", k, v)
        git(self.work, "remote", "add", "origin", self.bare)
        os.makedirs(os.path.join(self.work, "tools", "hooks"))
        shutil.copy(GUARD, os.path.join(self.work, "tools", "personal_guard.py"))
        shutil.copy(os.path.join(TOOLS, "identity_guard.py"),
                    os.path.join(self.work, "tools", "identity_guard.py"))
        shutil.copy(os.path.join(HOOKS, "pre-push"), os.path.join(self.work, "tools", "hooks", "pre-push"))
        git(self.work, "config", "core.hooksPath", "tools/hooks")
        self.env = dict(os.environ, DATA_NOODLER_PERSONAL_GUARD_CONFIG_DIR=config_dir)
        self.commit("README.md", "hello\n", "first")
        r = self.push()
        assert r.returncode == 0, r.stderr

    def commit(self, path, text, message):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)

    def push(self, *extra):
        return git(self.work, "push", "-q", "origin", "HEAD:main", *extra, check=False, env=self.env)

    def remote_head(self):
        return git(self.bare, "rev-parse", "main").stdout.strip()

    def local_head(self):
        return git(self.work, "rev-parse", "HEAD").stdout.strip()


def write_config(d, ids=True, personal=True):
    if ids:
        snap = os.path.join(d, "properties.csv")
        with open(snap, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["account_name", "property_name", "property_id", "property", "account", "property_type"])
            w.writerow(["Some account", "Some site", PROPERTY_ID, "properties/" + PROPERTY_ID,
                        "accounts/" + ACCOUNT_ID, "PROPERTY_TYPE_ORDINARY"])
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump({"properties_csv": snap}, f)
    if personal:
        with open(os.path.join(d, "personal-guard.txt"), "w") as f:
            f.write("# one value per line\n\n" + PERSONAL + "\n")


class PersonalGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def repo(self, **cfg):
        write_config(self.config, **cfg)
        return Repo(self.tmp, self.config)

    def assertRefused(self, r, repo, before):
        self.assertNotEqual(r.returncode, 0, "the push went through: " + r.stderr)
        self.assertEqual(repo.remote_head(), before, "the remote moved")
        self.assertIn("PERSONAL-GUARD", r.stderr)
        for value in (PROPERTY_ID, ACCOUNT_ID, PERSONAL, PERSONAL.lower()):
            self.assertNotIn(value, r.stderr + r.stdout, "the refusal printed the value")

    def test_a_property_id_from_the_snapshot_is_refused(self):
        repo = self.repo()
        before = repo.remote_head()
        repo.commit("docs/notes.md", "try property %s next\n" % PROPERTY_ID, "notes")
        r = repo.push()
        self.assertRefused(r, repo, before)
        self.assertIn("docs/notes.md", r.stderr)

    def test_an_account_id_from_the_snapshot_is_refused(self):
        repo = self.repo()
        before = repo.remote_head()
        repo.commit("a.py", "ACCOUNT = 'accounts/%s'\n" % ACCOUNT_ID, "acct")
        self.assertRefused(repo.push(), repo, before)

    def test_a_value_from_the_personal_list_is_refused_whatever_its_case(self):
        repo = self.repo()
        before = repo.remote_head()
        repo.commit("docs/x.md", "Built for the %s team.\n" % PERSONAL.upper(), "x")
        self.assertRefused(repo.push(), repo, before)

    def test_a_value_added_then_removed_inside_the_push_is_still_refused(self):
        repo = self.repo()
        before = repo.remote_head()
        repo.commit("docs/x.md", "id %s\n" % PROPERTY_ID, "add")
        repo.commit("docs/x.md", "id removed\n", "remove")
        self.assertRefused(repo.push(), repo, before)

    def test_a_value_in_a_commit_message_is_refused(self):
        repo = self.repo()
        before = repo.remote_head()
        repo.commit("docs/x.md", "harmless\n", "fix for property %s" % PROPERTY_ID)
        self.assertRefused(repo.push(), repo, before)

    def test_a_new_branch_is_checked_too(self):
        repo = self.repo()
        repo.commit("docs/x.md", "id %s\n" % PROPERTY_ID, "add")
        r = git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/feature", check=False, env=repo.env)
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(git(repo.bare, "branch", "--list", "feature").stdout.strip(), "feature")

    def test_commits_another_remote_already_has_are_still_checked_for_this_one(self):
        repo = self.repo()
        other = os.path.join(self.tmp, "other.git")
        git(self.tmp, "init", "-q", "--bare", other)
        git(repo.work, "remote", "add", "other", other)
        repo.commit("docs/x.md", "id %s\n" % PROPERTY_ID, "add")
        # it reached the other remote without the hook, so a tracking ref now points at it
        git(repo.work, "push", "-q", "--no-verify", "other", "HEAD:refs/heads/main", env=repo.env)
        git(repo.work, "fetch", "-q", "other", env=repo.env)
        r = git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/feature", check=False, env=repo.env)
        self.assertNotEqual(r.returncode, 0, "a commit only the OTHER remote had went through: " + r.stderr)

    def test_a_pattern_line_is_matched_as_a_regular_expression_ignoring_case(self):
        repo = self.repo()
        with open(os.path.join(self.config, "personal-guard.txt"), "a") as f:
            f.write("re:" + r"\bwid" + r"get\s+lab\b" + "\n")
        before = repo.remote_head()
        repo.commit("docs/x.md", "Made by the WIDGET   LAB.\n", "x")
        self.assertRefused(repo.push(), repo, before)

    def test_a_pattern_keeps_its_word_boundaries(self):
        repo = self.repo()
        with open(os.path.join(self.config, "personal-guard.txt"), "a") as f:
            f.write("re:" + r"\bwid" + r"get\b" + "\n")
        repo.commit("docs/x.md", "the widgets and gadgetwidget are fine\n", "x")
        r = repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 pattern", r.stderr)

    def test_an_unreadable_pattern_refuses_the_push(self):
        repo = self.repo()
        with open(os.path.join(self.config, "personal-guard.txt"), "a") as f:
            f.write("re:(unclosed\n")
        before = repo.remote_head()
        repo.commit("docs/x.md", "nothing\n", "x")
        r = repo.push()
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.remote_head(), before)
        self.assertNotIn("unclosed", r.stderr, "the refusal printed the pattern")

    def test_a_longer_number_that_contains_an_id_passes(self):
        repo = self.repo()
        repo.commit("docs/x.md", "order 1%s0\n" % PROPERTY_ID, "x")
        r = repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.remote_head(), repo.local_head())

    def test_a_clean_push_goes_through_and_says_what_it_checked(self):
        repo = self.repo()
        repo.commit("docs/x.md", "nothing personal\n", "x")
        r = repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.remote_head(), repo.local_head())
        self.assertIn("2 snapshot ids", r.stderr)
        self.assertIn("1 personal value", r.stderr)

    def test_without_any_local_list_it_skips_loudly(self):
        repo = Repo(self.tmp, self.config)   # empty config folder
        repo.commit("docs/x.md", "id %s\n" % PROPERTY_ID, "x")
        r = repo.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("personal guard not configured", r.stderr)

    def test_a_snapshot_named_in_config_but_missing_refuses_the_push(self):
        repo = Repo(self.tmp, self.config)
        with open(os.path.join(self.config, "config.json"), "w") as f:
            json.dump({"properties_csv": os.path.join(self.config, "gone.csv")}, f)
        before = repo.remote_head()
        repo.commit("docs/x.md", "nothing\n", "x")
        r = repo.push()
        self.assertNotEqual(r.returncode, 0, "a configured guard that cannot read its list must not pass")
        self.assertEqual(repo.remote_head(), before)
        self.assertIn("PERSONAL-GUARD", r.stderr)



class TheGuardFollowsTheInstallHome(unittest.TestCase):
    """#1999, Indigo's hazard: with no list found this guard warns and PASSES.
    So when the install home moves from its old name to
    ~/.config/data-noodler, a guard looking only in one of them would quietly
    stop checking. Real pushes, located by HOME alone (no override)."""

    def _repo_with_home(self, home_folder, empty_new=False):
        tmp = tempfile.mkdtemp()
        home = os.path.join(tmp, "home")
        cfg = os.path.join(home, ".config", home_folder)
        os.makedirs(cfg)
        write_config(cfg)
        if empty_new:
            os.makedirs(os.path.join(home, ".config", "data-noodler"))
        repo = Repo(tmp, cfg)
        repo.env = {k: v for k, v in os.environ.items()
                    if k != "DATA_NOODLER_PERSONAL_GUARD_CONFIG_DIR"}
        repo.env["HOME"] = home
        return repo

    def _assert_refused(self, repo):
        before = repo.remote_head()
        repo.commit("notes.md", "see " + PERSONAL + "\n", "add notes")
        r = repo.push()
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.remote_head(), before)

    def test_a_list_in_the_home_from_before_the_rename_still_refuses(self):
        self._assert_refused(self._repo_with_home("ga-" "mcp"))

    def test_a_list_in_the_new_home_refuses(self):
        self._assert_refused(self._repo_with_home("data-noodler"))

    def test_an_empty_new_home_does_not_hide_the_lists_in_the_old(self):
        # Indigo's review of PR #5: a mkdir, an aborted move or any tool
        # creating the folder used to flip the guard to an empty home.
        self._assert_refused(self._repo_with_home("ga-" "mcp", empty_new=True))


if __name__ == "__main__":
    unittest.main()
