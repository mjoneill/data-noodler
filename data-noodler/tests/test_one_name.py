"""#1999: one name for everything that is ours.

Michael, 2026-11-20: "we can't have multiple different names for the same
thing. Google names their piece...we won't touch that. but we need internal
consistency for the product we're shipping."

An existing install carries the old names: a companion/ payload folder, a
"ga-companion" entry in each app's config, and the google-analytics and
ga-mcp-setup skills. Renaming without retiring them would leave every app
showing BOTH names, so each installer step that writes a new name also
retires the old one -- moved aside, never deleted, and only where this
package put it.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import copy_skills  # noqa: E402
import install  # noqa: E402
import register  # noqa: E402
import verify  # noqa: E402

from test_install_payload import make_repo  # noqa: E402


class TestTheOldServerFolderIsRetired(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "ga-mcp")

    def _old_companion(self, marked=True):
        d = os.path.join(self.ga_home, "companion")
        os.makedirs(d)
        with open(os.path.join(d, "ga_companion.py"), "w") as f:
            f.write("# old\n")
        if marked:
            with open(os.path.join(d, install.MARKER), "w") as f:
                f.write("ours\n")
        return d

    def test_an_old_companion_folder_of_ours_is_moved_aside(self):
        old = self._old_companion()
        install.install_payload(self.repo, self.ga_home)
        self.assertFalse(os.path.exists(old))
        kept = [n for n in os.listdir(self.ga_home)
                if n.startswith("companion.ga-old-")]
        self.assertEqual(len(kept), 1, os.listdir(self.ga_home))
        self.assertTrue(os.path.isfile(
            os.path.join(self.ga_home, kept[0], "ga_companion.py")))

    def test_a_companion_folder_that_is_not_ours_is_left_alone(self):
        old = self._old_companion(marked=False)
        with open(os.path.join(old, "someone-elses.txt"), "w") as f:
            f.write("mine\n")
        install.install_payload(self.repo, self.ga_home)
        self.assertTrue(os.path.isfile(os.path.join(old, "someone-elses.txt")))

    def test_its_rollback_is_listed_with_the_other_backups(self):
        self._old_companion()
        install.install_payload(self.repo, self.ga_home)
        found = install.find_backups(self.ga_home, [])
        self.assertTrue(any(os.path.basename(p).startswith("companion.ga-old-")
                            for p in found), found)


class TestAnInstallFromBeforeTheMarkerIsStillOurs(unittest.TestCase):
    """Indigo's review of PR #4: installs from before 2026-09-14 carry no
    marker, so ownership is "every entry is one we ship". The old launcher
    and server-file names are not shipped any more, so they must still count
    as ours -- or the install refuses bin/ after it has already written
    server/."""

    def setUp(self):
        self.repo = make_repo()
        self.ga_home = os.path.join(tempfile.mkdtemp(), "ga-mcp")
        for d, names in {"bin": ["launch-ga-mcp", "launch-ga-companion"],
                         "marketplace": ["marketplace.txt"],
                         "companion": ["ga_companion.py", "server.txt",
                                       "__pycache__"]}.items():
            os.makedirs(os.path.join(self.ga_home, d))
            for n in names:
                path = os.path.join(self.ga_home, d, n)
                if n == "__pycache__":
                    os.makedirs(path)
                else:
                    with open(path, "w") as f:
                        f.write("old\n")

    def test_every_folder_is_replaced_and_the_old_server_retired(self):
        install.install_payload(self.repo, self.ga_home)
        names = sorted(os.listdir(self.ga_home))
        for d in ("server", "bin", "marketplace"):
            self.assertIn(d, names)
            self.assertTrue(any(n.startswith(d + ".ga-old-") for n in names)
                            or d == "server", names)
        self.assertNotIn("companion", names)
        self.assertTrue(any(n.startswith("companion.ga-old-") for n in names))
        self.assertTrue(os.path.isfile(os.path.join(
            self.ga_home, "bin", "launch-data-noodler")))

    def test_a_refusal_comes_before_anything_is_written(self):
        with open(os.path.join(self.ga_home, "bin", "someone-elses"), "w") as f:
            f.write("mine\n")
        with self.assertRaises(install.InstallError):
            install.install_payload(self.repo, self.ga_home)
        self.assertFalse(os.path.exists(os.path.join(self.ga_home, "server")),
                         "server/ was written before bin/ was refused")
        self.assertTrue(os.path.isdir(os.path.join(self.ga_home, "companion")))


class TestTheOldServerEntryIsRetired(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "config.json")
        self.entries = register.server_entries("/x/ga-mcp", platform="darwin")

    def _write(self, servers):
        with open(self.path, "w") as f:
            json.dump({"mcpServers": servers, "theirs": 1}, f)

    def _servers(self):
        with open(self.path) as f:
            return json.load(f)["mcpServers"]

    def test_the_new_names_replace_the_old_one(self):
        self._write({"ga-companion": {"command": "/old"},
                     "someone-else": {"command": "/keep"}})
        result = register.register_json(self.path, self.entries)
        servers = self._servers()
        self.assertNotIn("ga-companion", servers)
        self.assertIn("data-noodler", servers)
        self.assertIn("analytics-mcp", servers)
        self.assertEqual(servers["someone-else"], {"command": "/keep"})
        self.assertEqual(result["removed"], ["ga-companion"])
        self.assertTrue(result["backup"])

    def test_the_old_entry_goes_even_when_the_new_ones_are_current(self):
        self._write({**self.entries, "ga-companion": {"command": "/old"}})
        result = register.register_json(self.path, self.entries)
        self.assertNotIn("ga-companion", self._servers())
        self.assertTrue(result["changed"])

    def test_nothing_to_retire_reports_nothing(self):
        self._write(dict(self.entries))
        result = register.register_json(self.path, self.entries)
        self.assertFalse(result["changed"])
        self.assertEqual(result["removed"], [])

    def test_verify_calls_a_leftover_old_entry_a_problem(self):
        self._write({**self.entries, "ga-companion": {"command": "/old"}})
        problems = verify.legacy_entries(self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn("ga-companion", problems[0])

    def test_verify_is_quiet_when_only_the_new_names_are_there(self):
        self._write(dict(self.entries))
        self.assertEqual(verify.legacy_entries(self.path), [])


class TestTheOldSkillsAreRetired(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp()
        self.skills = os.path.join(base, "skills")
        self.ga_home = os.path.join(base, "ga-mcp")
        os.makedirs(self.skills)

    def _skill(self, name, marked):
        d = os.path.join(self.skills, name)
        os.makedirs(d)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {name}\n---\n")
        if marked:
            with open(os.path.join(d, copy_skills.MARKER), "w") as f:
                f.write("ours\n")
        return d

    def test_an_old_skill_of_ours_leaves_the_skills_folder(self):
        # Moved OUT of the skills folder: a copy left beside it would still
        # register as a second skill (INSTALL.md, the .backup trap).
        old = self._skill("google-analytics", marked=True)
        results = copy_skills.retire_legacy(self.skills, self.ga_home)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(os.listdir(self.skills), [])
        retired = os.path.join(self.ga_home, "retired-skills")
        self.assertEqual(len(os.listdir(retired)), 1)
        self.assertEqual(results[0][0], "retired")

    def test_an_old_skill_that_is_not_ours_is_reported_not_touched(self):
        old = self._skill("ga-mcp-setup", marked=False)
        results = copy_skills.retire_legacy(self.skills, self.ga_home)
        self.assertTrue(os.path.isfile(os.path.join(old, "SKILL.md")))
        self.assertEqual(results[0][0], "legacy-not-ours")
        self.assertIn("legacy-not-ours", copy_skills.DECIDE)

    def test_no_old_skills_means_nothing_to_report(self):
        self.assertEqual(copy_skills.retire_legacy(self.skills, self.ga_home),
                         [])


if __name__ == "__main__":
    unittest.main()
