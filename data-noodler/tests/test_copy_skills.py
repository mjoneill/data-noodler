"""Skills are refreshed only where this package put them (2026-10-25).

On the maintainer's machine ~/.claude/skills/data-noodler is the MASTER
copy the plugin is built from; an upgrade that overwrote it would silently
replace unbuilt edits. A marker file inside each folder the package installs
is what permits a later refresh. Nothing is ever deleted.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import copy_skills  # noqa: E402

SHIPPED_SKILLS = (
    os.path.join(ROOT, "skills", "data-noodler"),
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


class TestTheCompareReadsContentAndLinksAreNotFollowed(unittest.TestCase):
    """#2009: _same_tree used filecmp's shallow compare, so a file with the
    same size and mtime read as unchanged whatever it held; and a symlinked
    skill folder was followed, so a refresh or an approved replace wrote
    into whatever it pointed at."""

    def setUp(self):
        self.src = tempfile.mkdtemp()
        self.skills = tempfile.mkdtemp()
        self.dest = os.path.join(self.skills, "data-noodler")

    def _write(self, folder, text):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "SKILL.md")
        with open(path, "w") as f:
            f.write(text)
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return path

    def test_same_size_and_mtime_with_different_content_is_refreshed(self):
        self._write(self.src, "version A")
        copy_skills.install_skill("data-noodler", self.src, self.skills)
        self._write(self.src, "version B")  # same length, same mtime
        status, _ = copy_skills.install_skill("data-noodler", self.src,
                                              self.skills)
        self.assertEqual(status, "refreshed")
        with open(os.path.join(self.dest, "SKILL.md")) as f:
            self.assertEqual(f.read(), "version B")

    def test_a_symlinked_skill_folder_is_left_untouched(self):
        self._write(self.src, "new version")
        elsewhere = tempfile.mkdtemp()
        self._write(elsewhere, "someone's own work")
        with open(os.path.join(elsewhere, copy_skills.MARKER), "w") as f:
            f.write(copy_skills.MARKER_TEXT)
        try:
            os.symlink(elsewhere, self.dest)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here ({exc})")
        for replace in (False, True):
            status, detail = copy_skills.install_skill(
                "data-noodler", self.src, self.skills, replace=replace)
            self.assertEqual(status, "blocked", detail)
            self.assertIn("link", detail)
        with open(os.path.join(elsewhere, "SKILL.md")) as f:
            self.assertEqual(f.read(), "someone's own work")
        self.assertTrue(os.path.islink(self.dest))

    def _link_inside(self, kind):
        # Installed, then a subfolder or a file inside it replaced by a link
        # to someone's own copy (review of PR #22).
        os.makedirs(os.path.join(self.src, "scripts"))
        self._write(self.src, "v1")
        with open(os.path.join(self.src, "scripts", "a.py"), "w") as f:
            f.write("v1")
        copy_skills.install_skill("data-noodler", self.src, self.skills)
        outside = tempfile.mkdtemp()
        with open(os.path.join(outside, "a.py"), "w") as f:
            f.write("precious")
        try:
            if kind == "folder":
                import shutil
                shutil.rmtree(os.path.join(self.dest, "scripts"))
                os.symlink(outside, os.path.join(self.dest, "scripts"))
            else:
                os.remove(os.path.join(self.dest, "scripts", "a.py"))
                os.symlink(os.path.join(outside, "a.py"),
                           os.path.join(self.dest, "scripts", "a.py"))
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here ({exc})")
        with open(os.path.join(self.src, "scripts", "a.py"), "w") as f:
            f.write("v2-newer")
        return outside

    def _assert_blocked_and_outside_untouched(self, outside):
        for replace in (False, True):
            status, detail = copy_skills.install_skill(
                "data-noodler", self.src, self.skills, replace=replace)
            self.assertEqual(status, "blocked", detail)
            self.assertIn("link", detail)
        with open(os.path.join(outside, "a.py")) as f:
            self.assertEqual(f.read(), "precious")

    def test_a_linked_subfolder_inside_the_skill_is_never_written_through(self):
        self._assert_blocked_and_outside_untouched(self._link_inside("folder"))

    def test_a_linked_file_inside_the_skill_is_never_written_through(self):
        self._assert_blocked_and_outside_untouched(self._link_inside("file"))

class TestExitCodesNeverSayDoneWhenItIsNot(unittest.TestCase):
    """Code review #6: a skill that was not installed exited 0 ('done')."""

    def _run(self, skills, ga_home, dist=ROOT):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "installer", "copy_skills.py"),
             "--ga-home", ga_home, "--dist", dist, "--skills-dir", skills],
            capture_output=True, text=True)

    def test_a_file_in_the_way_is_a_failure(self):
        skills = tempfile.mkdtemp()
        open(os.path.join(skills, "data-noodler-setup"), "w").close()
        p = self._run(skills, tempfile.mkdtemp())
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("blocked", p.stdout)

    def test_a_missing_source_is_a_failure(self):
        # A package with no skills/ folder: the sources are absent (#2106:
        # both skills now come from the package, not from ga_home).
        p = self._run(tempfile.mkdtemp(), tempfile.mkdtemp(),
                      dist=tempfile.mkdtemp())
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

    def test_the_install_places_the_marked_skill_inside_the_plugin(self):
        # #2106: the repo holds one copy, skills/data-noodler/. Codex needs it
        # inside the plugin, so the install puts it there, marker included, so
        # copy_skills.py can refresh Claude Code's copy from it later.
        import install
        mkt = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, mkt, True)
        install.place_plugin_skill(ROOT, mkt)
        placed = os.path.join(mkt, *install.SKILL_IN_PLUGIN)
        self.assertTrue(os.path.exists(os.path.join(placed, "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(placed, copy_skills.MARKER)))

    def test_the_repo_has_no_second_copy_of_the_analytics_skill(self):
        self.assertFalse(os.path.exists(os.path.join(
            ROOT, "marketplace", "plugins", "data-noodler", "skills")))

if __name__ == "__main__":
    unittest.main()
