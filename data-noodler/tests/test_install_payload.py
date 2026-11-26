"""The payload copy: what it does today, and what it must never do.

install_payload() was the most destructive function in the package and the
only one with no tests at all. It called shutil.rmtree() on three directories
under an unvalidated --ga-home before copying, so `--ga-home ~` would have
recursively deleted ~/companion, ~/bin and ~/marketplace.

The first class below is characterization: it pins the behaviour that already
existed, written before the rewrite so the rewrite could not quietly change
it. The rest are the guarantees the rewrite adds.
"""

import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "installer"))

import install


def make_repo(root=None, extra=None):
    """A minimal repo_root containing a data-noodler/ payload."""
    root = root or tempfile.mkdtemp()
    dist = os.path.join(root, "data-noodler")
    for name in install.PAYLOAD:
        d = os.path.join(dist, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(name)
    # #2106: the analytics skill, which the install places inside the plugin.
    skill = os.path.join(dist, *install.SKILL_SRC)
    os.makedirs(skill, exist_ok=True)
    with open(os.path.join(skill, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("skill")
    bindir = os.path.join(dist, "bin")
    for launcher in ("launch-analytics-mcp", "launch-data-noodler"):
        p = os.path.join(bindir, launcher)
        with open(p, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)
    # noise that must not be copied
    junk = os.path.join(dist, "server", "__pycache__")
    os.makedirs(junk, exist_ok=True)
    with open(os.path.join(junk, "x.pyc"), "w", encoding="utf-8") as f:
        f.write("junk")
    with open(os.path.join(dist, "server", "stale.pyc"), "w",
              encoding="utf-8") as f:
        f.write("junk")
    for rel, body in (extra or {}).items():
        p = os.path.join(dist, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
    return root


class TestPayloadCopyCharacterization(unittest.TestCase):
    """Behaviour that predates the rewrite and must survive it."""

    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "data-noodler")

    def test_copies_every_payload_directory(self):
        written = install.install_payload(self.repo, self.ga_home)
        self.assertEqual(sorted(os.path.basename(p) for p in written),
                         sorted(install.PAYLOAD))
        for name in install.PAYLOAD:
            self.assertTrue(
                os.path.isfile(os.path.join(self.ga_home, name, f"{name}.txt")))

    def test_does_not_copy_bytecode(self):
        install.install_payload(self.repo, self.ga_home)
        server = os.path.join(self.ga_home, "server")
        self.assertFalse(os.path.exists(os.path.join(server, "__pycache__")))
        self.assertFalse(os.path.exists(os.path.join(server, "stale.pyc")))

    @unittest.skipIf(sys.platform.startswith("win"), "Windows has no executable bit")
    def test_launchers_are_executable_afterwards(self):
        install.install_payload(self.repo, self.ga_home)
        for launcher in ("launch-analytics-mcp", "launch-data-noodler"):
            p = os.path.join(self.ga_home, "bin", launcher)
            self.assertTrue(os.stat(p).st_mode & stat.S_IXUSR, launcher)

    def test_a_missing_payload_directory_is_refused_by_name(self):
        import shutil
        shutil.rmtree(os.path.join(self.repo, "data-noodler", "marketplace"))
        with self.assertRaises(install.InstallError) as caught:
            install.install_payload(self.repo, self.ga_home)
        self.assertIn("marketplace", str(caught.exception))

    def test_reinstalling_replaces_rather_than_merges(self):
        install.install_payload(self.repo, self.ga_home)
        orphan = os.path.join(self.ga_home, "server", "removed_upstream.py")
        with open(orphan, "w", encoding="utf-8") as f:
            f.write("x")
        install.install_payload(self.repo, self.ga_home)
        self.assertFalse(
            os.path.exists(orphan),
            "a file deleted upstream must not survive a reinstall, or the "
            "installed tree drifts from the repo it claims to mirror")

    def test_reinstalling_is_idempotent(self):
        install.install_payload(self.repo, self.ga_home)
        first = sorted(os.listdir(os.path.join(self.ga_home, "server")))
        install.install_payload(self.repo, self.ga_home)
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.ga_home, "server"))), first)


class TestPayloadCopyRefusesDangerousDestinations(unittest.TestCase):
    """The guards the rewrite adds. Every one of these used to delete.

    `--ga-home` is an argparse string with no validation. The failure is not
    hypothetical: an agent that invents a plausible-looking flag value is
    exactly how it fires, and SKILL.md already carries eight warnings proving
    agents invent things at walls.
    """

    def setUp(self):
        self.repo = make_repo()

    def test_refuses_a_relative_ga_home(self):
        # Asserted from a temp cwd, and the directory is checked afterwards.
        # Before the guard existed this test created ./relative/data-noodler in the
        # repo root and it was committed by accident -- a test that litters
        # where it runs is a test nobody trusts to run twice.
        cwd = os.getcwd()
        scratch = tempfile.mkdtemp()
        try:
            os.chdir(scratch)
            with self.assertRaises(install.InstallError) as caught:
                install.install_payload(self.repo, "relative/data-noodler")
            self.assertIn("absolute", str(caught.exception).lower())
            self.assertEqual(os.listdir(scratch), [],
                             "a refused install still created something")
        finally:
            os.chdir(cwd)

    def test_refuses_the_home_directory_itself(self):
        home = tempfile.mkdtemp()
        with self.assertRaises(install.InstallError):
            install.install_payload(self.repo, home, home=home)

    def test_refuses_a_filesystem_root(self):
        with self.assertRaises(install.InstallError):
            install.install_payload(self.repo, os.path.abspath(os.sep))

    def test_refuses_to_replace_a_directory_it_did_not_create(self):
        # Someone else's ~/bin, or a mistyped --ga-home landing on real files.
        ga_home = tempfile.mkdtemp()
        foreign = os.path.join(ga_home, "server")
        os.makedirs(foreign)
        precious = os.path.join(foreign, "someone-elses-work.txt")
        with open(precious, "w", encoding="utf-8") as f:
            f.write("do not delete me")
        with self.assertRaises(install.InstallError) as caught:
            install.install_payload(self.repo, ga_home)
        self.assertTrue(os.path.exists(precious),
                        "refused the install but deleted the files anyway")
        self.assertIn("not", str(caught.exception).lower())

    def test_an_install_it_did_create_is_replaceable(self):
        # The flip side: a real previous install carries the marker, so
        # reinstalling over it is allowed and does not need a human.
        ga_home = os.path.join(tempfile.mkdtemp(), "data-noodler")
        install.install_payload(self.repo, ga_home)
        install.install_payload(self.repo, ga_home)
        self.assertTrue(os.path.isfile(
            os.path.join(ga_home, "server", "server.txt")))


class TestPayloadCopyLeavesARollback(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "data-noodler")

    def test_the_previous_install_is_kept_after_a_reinstall(self):
        install.install_payload(self.repo, self.ga_home)
        marker = os.path.join(self.ga_home, "server", "from-first-install.txt")
        with open(marker, "w", encoding="utf-8") as f:
            f.write("v1")
        install.install_payload(self.repo, self.ga_home)

        parent = self.ga_home
        kept = [n for n in os.listdir(parent) if n.startswith("server.ga-old-")]
        self.assertTrue(kept, "no rollback copy of the previous install exists")
        self.assertTrue(
            os.path.isfile(os.path.join(parent, kept[0],
                                        "from-first-install.txt")),
            "the rollback copy does not contain the previous install's files")

    def test_a_failed_copy_leaves_the_existing_install_in_place(self):
        install.install_payload(self.repo, self.ga_home)
        good = os.path.join(self.ga_home, "server", "server.txt")
        self.assertTrue(os.path.isfile(good))

        # marketplace disappears midway through a second run: server/ has
        # already been dealt with by then.
        import shutil
        shutil.rmtree(os.path.join(self.repo, "data-noodler", "marketplace"))
        with self.assertRaises(install.InstallError):
            install.install_payload(self.repo, self.ga_home)
        self.assertTrue(
            os.path.isfile(good),
            "a partial failure destroyed a working install; re-running was "
            "supposed to be safe")


class TestDryRun(unittest.TestCase):
    """Show every path that would be touched, then touch nothing.

    Asked for by Michael on card #68: "I worry about any script removing
    files, overwriting anything... I am concerned about ooopsies." An install
    that can be read before it is run is the answer to that, and it is also
    what lets a Claude Code session review the plan rather than discover it.
    """

    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "data-noodler")

    def test_names_every_directory_it_would_create(self):
        plan = install.describe_payload_plan(self.repo, self.ga_home)
        text = "\n".join(plan)
        for name in install.PAYLOAD:
            self.assertIn(os.path.join(self.ga_home, name), text, name)

    def test_touches_nothing(self):
        install.describe_payload_plan(self.repo, self.ga_home)
        self.assertFalse(os.path.exists(self.ga_home),
                         "a dry run created the destination")

    def test_says_when_an_existing_install_would_be_moved_aside(self):
        install.install_payload(self.repo, self.ga_home)
        plan = "\n".join(install.describe_payload_plan(self.repo, self.ga_home))
        self.assertIn("ga-old-", plan,
                      "the plan does not say the existing install is kept")
        self.assertNotIn("delete", plan.lower(),
                         "nothing is deleted outright any more, so the plan "
                         "must not say it is")

    def test_applies_the_same_refusals_as_a_real_run(self):
        ga_home = tempfile.mkdtemp()
        foreign = os.path.join(ga_home, "server")
        os.makedirs(foreign)
        with open(os.path.join(foreign, "someone-elses.txt"), "w",
                  encoding="utf-8") as f:
            f.write("x")
        with self.assertRaises(install.InstallError):
            install.describe_payload_plan(self.repo, ga_home)

    def test_a_dry_run_of_an_impossible_install_still_refuses(self):
        with self.assertRaises(install.InstallError):
            install.describe_payload_plan(self.repo, "relative/path")


class TestTheInstallerNeverRemovesBackups(unittest.TestCase):
    """Michael, 2026-10-06: "I just don't want to be in the business of removing
    something like that via script."

    The installer used to prune payload rollbacks to the three most recent --
    shutil.rmtree of whatever was older. It now removes no backup of any kind.
    It reports them instead, with their locations, and leaves the decision to a
    person.
    """

    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "data-noodler")
        install.install_payload(self.repo, self.ga_home)

    def _old(self, stamp):
        d = os.path.join(self.ga_home, f"companion.ga-old-{stamp}")
        os.makedirs(d)
        return d

    def test_old_rollbacks_all_survive_a_reinstall(self):
        old = [self._old(f"2026010{i}-000000") for i in range(1, 6)]
        install.install_payload(self.repo, self.ga_home)
        for d in old:
            self.assertTrue(os.path.isdir(d),
                            f"{d} was removed by the installer")

    def test_there_is_no_pruning_function_left_to_call(self):
        self.assertFalse(hasattr(install, "_prune_rollbacks"))


class TestBackupsAreReported(unittest.TestCase):
    """Found, located, and handed to a person -- never acted on."""

    def setUp(self):
        self.repo = make_repo()
        self.home = tempfile.mkdtemp()
        self.ga_home = os.path.join(self.home, ".config", "data-noodler")
        install.install_payload(self.repo, self.ga_home)
        self.code_cfg = os.path.join(self.home, ".claude.json")
        with open(self.code_cfg, "w", encoding="utf-8") as f:
            f.write("{}")

    def _touch(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
        return path

    def test_nothing_to_report_on_a_first_install(self):
        self.assertEqual(install.find_backups(self.ga_home, [self.code_cfg]), [])
        self.assertIsNone(install.backup_report(self.ga_home, [self.code_cfg]))

    def test_payload_rollbacks_are_found(self):
        install.install_payload(self.repo, self.ga_home)  # makes .ga-old-*
        found = install.find_backups(self.ga_home, [self.code_cfg])
        self.assertTrue(any(".ga-old-" in p for p in found), found)

    def test_registration_backups_are_found(self):
        b = self._touch(self.code_cfg + ".ga-backup-20260902-122057")
        self.assertIn(b, install.find_backups(self.ga_home, [self.code_cfg]))

    def test_config_json_backups_from_bootstrap_are_found(self):
        b = self._touch(os.path.join(self.ga_home,
                                     "config.json.ga-backup-20260902-000000"))
        self.assertIn(b, install.find_backups(self.ga_home, []))

    def test_an_absent_target_config_is_simply_skipped(self):
        self.assertEqual(install.find_backups(self.ga_home, [None]), [])

    def test_finding_them_changes_nothing(self):
        self._touch(self.code_cfg + ".ga-backup-20260902-122057")
        before = sorted(os.listdir(self.home))
        install.find_backups(self.ga_home, [self.code_cfg])
        install.backup_report(self.ga_home, [self.code_cfg])
        self.assertEqual(sorted(os.listdir(self.home)), before)

    def test_the_report_names_every_path_and_promises_nothing_was_removed(self):
        b = self._touch(self.code_cfg + ".ga-backup-20260902-122057")
        report = install.backup_report(self.ga_home, [self.code_cfg])
        self.assertIn(b, report)
        lowered = report.lower()
        self.assertIn("nothing", lowered)
        self.assertIn("never", lowered,
                      "say the installer will NEVER remove them, or the next "
                      "reader assumes it might")

    def test_the_report_recommends_noting_the_paths_down(self):
        self._touch(self.code_cfg + ".ga-backup-20260902-122057")
        lowered = install.backup_report(self.ga_home, [self.code_cfg]).lower()
        self.assertIn("note", lowered)
        self.assertIn("by hand", lowered)

    def test_the_dry_run_no_longer_promises_to_discard_anything(self):
        plan = "\n".join(install.describe_payload_plan(self.repo, self.ga_home))
        self.assertNotIn("discard", plan.lower())


class TestBackupsAreDatedByWhenTheyWereMade(unittest.TestCase):
    """Found on the author's own machine, the first time the report ran.

    Three rollbacks made at 08:45 on 2026-10-06 were reported as 2026-09-03 and
    2026-09-04. A directory's mtime is when its CONTENTS last changed, and a
    rename does not touch it -- so the date shown was when that code was first
    installed, a month earlier. Ordering by it was wrong too, which made "the
    newest are your undo" point at the wrong ones. The name carries the true
    time; trust that.
    """

    def setUp(self):
        self.ga_home = tempfile.mkdtemp()

    def _backup(self, name, mtime):
        p = os.path.join(self.ga_home, name)
        os.makedirs(p)
        os.utime(p, (mtime, mtime))
        return p

    def test_the_date_comes_from_the_name_not_the_mtime(self):
        month_ago = time.time() - 33 * 86400
        p = self._backup("companion.ga-old-20261006-084557", month_ago)
        report = install.backup_report(self.ga_home, [])
        self.assertIn(f"2026-10-06  {p}", report)

    def test_order_follows_the_name_too(self):
        # Newer by name, older by mtime -- the case the bug got backwards.
        old = time.time() - 60 * 86400
        newer = self._backup("companion.ga-old-20261006-084557", old)
        older = self._backup("bin.ga-old-20260901-000000", time.time())
        found = install.find_backups(self.ga_home, [])
        self.assertLess(found.index(older), found.index(newer))

    def test_an_unstamped_name_falls_back_to_the_mtime(self):
        p = self._backup("companion.ga-old-unstamped", time.time())
        self.assertIn(p, install.backup_report(self.ga_home, []))
