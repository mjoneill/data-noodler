"""Skills are refreshed only where this package put them (2026-10-25).

On the maintainer's machine ~/.claude/skills/data-noodler is the MASTER
copy the plugin is built from; an upgrade that overwrote it would silently
replace unbuilt edits. A marker file inside each folder the package installs
is what permits a later refresh. Nothing is ever deleted.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import copy_skills  # noqa: E402

SHIPPED_SKILLS = (
    os.path.join(ROOT, "marketplace", "plugins", "data-noodler", "skills",
                 "data-noodler"),
    os.path.join(ROOT, "skills", "data-noodler-setup"),
)


class TestInstallSkill(unittest.TestCase):

    def setUp(self):
        self.src = tempfile.mkdtemp()
        with open(os.path.join(self.src, "SKILL.md"), "w") as f:
            f.write("new version")
        with open(os.path.join(self.src, copy_skills.MARKER), "w") as f:
            f.write(copy_skills.MARKER_TEXT)
        self.skills = tempfile.mkdtemp()
        self.dest = os.path.join(self.skills, "data-noodler")

    def _install(self, **kw):
        return copy_skills.install_skill("data-noodler", self.src,
                                         self.skills, **kw)

    def _read(self):
        with open(os.path.join(self.dest, "SKILL.md")) as f:
            return f.read()

    def test_a_new_skill_is_installed_with_the_marker(self):
        status, _ = self._install()
        self.assertEqual(status, "installed")
        self.assertTrue(os.path.exists(os.path.join(self.dest,
                                                    copy_skills.MARKER)))

    def test_a_marked_copy_is_refreshed(self):
        self._install()
        with open(os.path.join(self.src, "SKILL.md"), "w") as f:
            f.write("newer version")
        status, _ = self._install()
        self.assertEqual(status, "refreshed")
        self.assertEqual(self._read(), "newer version")

    def test_an_unmarked_folder_is_never_overwritten(self):
        # The maintainer's master copy, or someone's own edits.
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "SKILL.md"), "w") as f:
            f.write("my unbuilt edits")
        status, detail = self._install()
        self.assertEqual(status, "not-ours-differs")
        self.assertEqual(self._read(), "my unbuilt edits")

    def test_replace_after_a_yes_refreshes_it(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "SKILL.md"), "w") as f:
            f.write("old copy from an earlier install")
        status, _ = self._install(replace=True)
        self.assertEqual(status, "refreshed")
        self.assertEqual(self._read(), "new version")

    def test_files_no_longer_shipped_are_reported_not_deleted(self):
        self._install()
        stale = os.path.join(self.dest, "old-note.md")
        with open(stale, "w") as f:
            f.write("x")
        with open(os.path.join(self.src, "SKILL.md"), "w") as f:
            f.write("changed")
        status, detail = self._install()
        self.assertTrue(os.path.exists(stale))
        self.assertIn("old-note.md", detail)

    def test_the_command_exits_2_when_a_decision_is_needed(self):
        ga_home = ROOT  # holds marketplace/..., like an installed payload
        os.makedirs(os.path.join(self.skills, "data-noodler-setup"))
        with open(os.path.join(self.skills, "data-noodler-setup", "SKILL.md"),
                  "w") as f:
            f.write("someone's own")
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "installer", "copy_skills.py"),
             "--ga-home", ga_home, "--dist", ROOT,
             "--skills-dir", self.skills],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("not-ours-differs", p.stdout)


class TestExitCodesNeverSayDoneWhenItIsNot(unittest.TestCase):
    """Code review #6: a skill that was not installed exited 0 ('done')."""

    def _run(self, skills, ga_home):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "installer", "copy_skills.py"),
             "--ga-home", ga_home, "--dist", ROOT, "--skills-dir", skills],
            capture_output=True, text=True)

    def test_a_file_in_the_way_is_a_failure(self):
        skills = tempfile.mkdtemp()
        open(os.path.join(skills, "data-noodler-setup"), "w").close()
        p = self._run(skills, tempfile.mkdtemp())
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("blocked", p.stdout)

    def test_a_missing_source_is_a_failure(self):
        # ga_home without a payload: the data-noodler source is absent.
        p = self._run(tempfile.mkdtemp(), tempfile.mkdtemp())
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("missing-source", p.stdout)

    def test_an_identical_unmarked_folder_is_fine(self):
        skills = tempfile.mkdtemp()
        import shutil
        shutil.copytree(os.path.join(ROOT, "skills", "data-noodler-setup"),
                        os.path.join(skills, "data-noodler-setup"))
        os.remove(os.path.join(skills, "data-noodler-setup", copy_skills.MARKER))
        status, _ = copy_skills.install_skill(
            "data-noodler-setup", os.path.join(ROOT, "skills", "data-noodler-setup"),
            skills)
        self.assertEqual(status, "not-ours-same")
        self.assertIn(status, copy_skills.DONE)


class TestTheShippedSkillsCarryTheMarker(unittest.TestCase):

    def test_every_shipped_skill_folder_is_marked(self):
        for path in SHIPPED_SKILLS:
            self.assertTrue(os.path.exists(os.path.join(path,
                                                        copy_skills.MARKER)),
                            path)

    def test_the_build_marks_the_built_copy_never_the_master(self):
        import build_plugin_skill as b
        self.assertNotEqual(os.path.realpath(b.SOURCE), os.path.realpath(b.DEST))
        with open(b.__file__, encoding="utf-8") as f:
            code = f.read()
        self.assertIn("os.path.join(DEST, copy_skills.MARKER)", code)
        self.assertNotIn("os.path.join(SOURCE, copy_skills.MARKER)", code)

if __name__ == "__main__":
    unittest.main()
