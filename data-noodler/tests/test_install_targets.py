"""Which file each registration target writes to.

This resolution used to be inline in install.main(), which meant the only way
to exercise it was to run a real install against the real home directory. It
is a function here so the Windows branch can be asserted from macOS, and so
an unknown target fails in one place rather than being handled halfway down a
loop.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "installer"))

import install

DARWIN = "darwin"
WINDOWS = "win32"


class TestConfigPathForTarget(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def test_claude_code_is_the_same_path_on_both_platforms(self):
        for platform in (DARWIN, WINDOWS):
            got = install.config_path_for("claude_code", home=self.home,
                                          env={}, platform=platform)
            self.assertEqual(got, os.path.join(self.home, ".claude.json"))

    def test_claude_desktop_resolves_under_application_support_on_macos(self):
        d = os.path.join(self.home, "Library", "Application Support", "Claude")
        os.makedirs(d)
        got = install.config_path_for("claude_desktop", home=self.home,
                                      env={}, platform=DARWIN)
        self.assertEqual(got,
                         os.path.join(d, "claude_desktop_config.json"))

    def test_claude_desktop_resolves_under_appdata_on_windows(self):
        appdata = os.path.join(self.home, "AppData", "Roaming")
        d = os.path.join(appdata, "Claude")
        os.makedirs(d)
        got = install.config_path_for("claude_desktop", home=self.home,
                                      env={"APPDATA": appdata},
                                      platform=WINDOWS)
        self.assertEqual(got,
                         os.path.join(d, "claude_desktop_config.json"))

    def test_claude_desktop_returns_none_when_not_installed(self):
        # None means "skip this target", not "error". Claude Desktop being
        # absent is an ordinary outcome -- plenty of people have only the CLI.
        got = install.config_path_for("claude_desktop", home=self.home,
                                      env={}, platform=DARWIN)
        self.assertIsNone(got)

    def test_an_unknown_target_is_refused_by_name(self):
        with self.assertRaises(install.InstallError) as caught:
            install.config_path_for("claude_deskotp", home=self.home,
                                    env={}, platform=DARWIN)
        self.assertIn("claude_deskotp", str(caught.exception),
                      "the message must name the target the user typed, so a "
                      "typo is obvious rather than mysterious")

    def test_omitting_platform_uses_the_running_one(self):
        explicit = install.config_path_for("claude_desktop", home=self.home,
                                           env={}, platform=sys.platform)
        implicit = install.config_path_for("claude_desktop", home=self.home,
                                           env={})
        self.assertEqual(explicit, implicit)


class TestRegistrationInputs(unittest.TestCase):
    """Windows entries need two paths that POSIX launchers read for themselves.

    On macOS the launchers open config.json at spawn time, so registration
    needs nothing but ga_home. On Windows there is no launcher, so those
    values have to be baked into the entry -- which means the installer has
    to go and get them, and fail clearly when it cannot.
    """

    def test_posix_needs_nothing_extra(self):
        self.assertEqual(
            install.registration_inputs(config_path="/nonexistent",
                                        platform=DARWIN), {})

    def test_windows_reads_both_paths_from_the_config(self):
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.json")
        import json
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"venv_python": "C:/v/Scripts/python.exe",
                       "adc_file": "C:/g/adc.json",
                       "properties_csv": "C:/p.csv",
                       "oauth_client_file": "C:/g/client.json",
                       "mint_script": "C:/m.py"}, f)
        got = install.registration_inputs(config_path=cfg, platform=WINDOWS)
        self.assertEqual(got["venv_python"], "C:/v/Scripts/python.exe")
        self.assertEqual(got["adc_file"], "C:/g/adc.json")

    def test_windows_without_a_config_says_which_step_was_skipped(self):
        with self.assertRaises(install.InstallError) as caught:
            install.registration_inputs(config_path="/nonexistent/config.json",
                                        platform=WINDOWS)
        msg = str(caught.exception)
        self.assertIn("bootstrap_config", msg,
                      "the error must name the step that creates the file, or "
                      "the reader has to guess what to run")


class TestDesktopSkipIsLoudWhenTheAppExists(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.local = os.path.join(self.home, "AppData", "Local")
        self.apps = tempfile.mkdtemp()

    def _explain(self, platform, env):
        return install.explain_missing_desktop(
            home=self.home, env=env, platform=platform, app_dirs=[self.apps])

    def test_no_app_means_an_ordinary_skip(self):
        self.assertIsNone(self._explain(WINDOWS, {"LOCALAPPDATA": self.local}))

    def test_an_installed_app_without_a_config_is_a_refusal(self):
        os.makedirs(os.path.join(self.local, "Packages", "Claude_pzs8sxrjxfjjc"))
        msg = self._explain(WINDOWS, {"LOCALAPPDATA": self.local})
        self.assertIsNotNone(msg)
        for needed in ("Claude_pzs8sxrjxfjjc", "CLAUDE_USER_DATA_DIR"):
            self.assertIn(needed, msg, needed)

    def test_the_refusal_tells_you_to_launch_the_app_once(self):
        # The commonest benign cause: installed, never opened, so the data
        # directory has not been created yet.
        os.makedirs(os.path.join(self.apps, "Claude.app"))
        msg = self._explain(DARWIN, {})
        self.assertIn("open", msg.lower())
