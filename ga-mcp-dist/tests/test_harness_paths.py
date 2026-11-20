"""Resolving the ACTIVE Claude data directory, not just an existing one.

The author's machine has both `Claude/` (active) and `Claude-3p/` (vestigial,
a 56-byte config untouched for months). Writing to the wrong one fails
silently -- the tools simply never appear -- so the choice is asserted here.

Every test names its platform explicitly. They used to infer it from the host,
which meant the suite asserted "whatever this laptop is" and could not say
anything about Windows at all. Platform is now an argument, so both branches
are exercised from either machine. That is the only way a Windows port gets a
safety net before anyone stands in front of a Windows machine.
"""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "installer"))

import harness_paths

DARWIN = "darwin"
WINDOWS = "win32"


def _make_mac_claude_dir(home, name, config_mtime, extra_files=0):
    return _make_claude_dir(
        os.path.join(home, "Library", "Application Support", name),
        config_mtime, extra_files)


def _make_windows_claude_dir(appdata, name, config_mtime, extra_files=0):
    return _make_claude_dir(os.path.join(appdata, name),
                            config_mtime, extra_files)


def _make_claude_dir(d, config_mtime, extra_files=0):
    os.makedirs(d, exist_ok=True)
    cfg = os.path.join(d, "claude_desktop_config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"preferences": {}}, f)
    for i in range(extra_files):
        with open(os.path.join(d, f"state{i}.json"), "w", encoding="utf-8") as f:
            f.write("{}")
    os.utime(cfg, (config_mtime, config_mtime))
    return cfg


class TestClaudeDesktopOnMacOS(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def _resolve(self, **kw):
        return harness_paths.claude_desktop_config(
            home=self.home, platform=DARWIN, **kw)

    def test_returns_none_when_claude_desktop_is_not_installed(self):
        self.assertIsNone(self._resolve())

    def test_single_directory_is_chosen(self):
        cfg = _make_mac_claude_dir(self.home, "Claude", time.time())
        self.assertEqual(self._resolve(), cfg)

    def test_prefers_the_recently_modified_directory_over_the_stale_one(self):
        old = time.time() - 200 * 86400
        _make_mac_claude_dir(self.home, "Claude-3p", old)
        active = _make_mac_claude_dir(self.home, "Claude", time.time())
        self.assertEqual(self._resolve(), active)

    def test_prefers_recent_directory_regardless_of_candidate_order(self):
        # Same scenario inverted: the -3p variant is the live one.
        old = time.time() - 200 * 86400
        _make_mac_claude_dir(self.home, "Claude", old)
        active = _make_mac_claude_dir(self.home, "Claude-3p", time.time())
        self.assertEqual(self._resolve(), active)

    def test_explicit_env_override_wins_over_recency(self):
        _make_mac_claude_dir(self.home, "Claude", time.time())
        override_dir = tempfile.mkdtemp()
        with open(os.path.join(override_dir, "claude_desktop_config.json"),
                  "w", encoding="utf-8") as f:
            f.write("{}")
        got = self._resolve(env={"CLAUDE_USER_DATA_DIR": override_dir})
        self.assertEqual(
            got, os.path.join(override_dir, "claude_desktop_config.json"))

    def test_directory_present_without_config_still_resolves_a_write_path(self):
        d = os.path.join(self.home, "Library", "Application Support", "Claude")
        os.makedirs(d)
        with open(os.path.join(d, "ant-did"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual(self._resolve(),
                         os.path.join(d, "claude_desktop_config.json"))


class TestClaudeDesktopOnWindows(unittest.TestCase):
    """%APPDATA%\\Claude, confirmed present on the target machine.

    Reconnaissance on that machine found exactly one Claude directory and no
    -3p variant, so the recency choice has nothing to choose between there
    today. The candidate list is still applied: it is the same code with a
    different base directory, which is cheaper than a second implementation
    and correct if a -3p ever appears on Windows too.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.appdata = os.path.join(self.home, "AppData", "Roaming")
        os.makedirs(self.appdata, exist_ok=True)

    def _resolve(self, env=None, **kw):
        if env is None:
            env = {"APPDATA": self.appdata}
        return harness_paths.claude_desktop_config(
            home=self.home, env=env, platform=WINDOWS, **kw)

    def test_returns_none_when_claude_desktop_is_not_installed(self):
        self.assertIsNone(self._resolve())

    def test_resolves_the_config_under_appdata(self):
        cfg = _make_windows_claude_dir(self.appdata, "Claude", time.time())
        self.assertEqual(self._resolve(), cfg)

    def test_does_not_look_under_library_application_support(self):
        # The macOS location must not be consulted on Windows: a stray
        # directory there would otherwise win and be written to silently.
        _make_mac_claude_dir(self.home, "Claude", time.time())
        self.assertIsNone(self._resolve())

    def test_falls_back_to_the_default_appdata_location_when_unset(self):
        # APPDATA is set on every real Windows session, but a subprocess
        # launched with a scrubbed environment will not have it. Guessing
        # nothing would strand the install; the conventional path is right.
        cfg = _make_windows_claude_dir(self.appdata, "Claude", time.time())
        self.assertEqual(self._resolve(env={}), cfg)

    def test_explicit_env_override_wins(self):
        _make_windows_claude_dir(self.appdata, "Claude", time.time())
        override_dir = tempfile.mkdtemp()
        got = self._resolve(env={"APPDATA": self.appdata,
                                 "CLAUDE_USER_DATA_DIR": override_dir})
        self.assertEqual(
            got, os.path.join(override_dir, "claude_desktop_config.json"))

    def test_prefers_the_recently_modified_directory_if_two_ever_exist(self):
        old = time.time() - 200 * 86400
        _make_windows_claude_dir(self.appdata, "Claude-3p", old)
        active = _make_windows_claude_dir(self.appdata, "Claude", time.time())
        self.assertEqual(self._resolve(), active)


class TestClaudeCodeConfig(unittest.TestCase):
    """~/.claude.json, and it needs no platform branch.

    Confirmed on the Windows machine during reconnaissance: the file is at
    C:\\Users\\<user>\\.claude.json and `claude mcp list` reads it. Asserted
    on both platforms so nobody "ports" a function that was already portable.
    """

    def test_path_is_the_same_shape_on_every_platform(self):
        for platform in (DARWIN, WINDOWS):
            got = harness_paths.claude_code_config(home="/tmp/h",
                                                   platform=platform)
            self.assertEqual(got, os.path.join("/tmp/h", ".claude.json"),
                             f"differs on {platform}")


class TestPlatformDefaulting(unittest.TestCase):
    def test_omitting_platform_uses_the_running_one(self):
        home = tempfile.mkdtemp()
        explicit = harness_paths.claude_desktop_config(
            home=home, env={}, platform=sys.platform)
        implicit = harness_paths.claude_desktop_config(home=home, env={})
        self.assertEqual(explicit, implicit)


class TestMicrosoftStoreClaudeDesktop(unittest.TestCase):
    """Round 3, defect 2: a Store-packaged Claude Desktop was invisible.

    MSIX virtualises AppData. %APPDATA%\\Claude resolves ONLY for processes
    inside the app container; the real directory is
    %LOCALAPPDATA%\\Packages\\Claude_<family>\\LocalCache\\Roaming\\Claude. The
    real one is visible from inside AND outside, so it is the one path that is
    correct whoever runs the installer.

    The failure depended on who ran it: an agent inside Claude Code inherited
    the container and succeeded; a person in PowerShell got "claude_desktop:
    not installed, skipping", exit 0. The silent skip this module exists to
    prevent, by a route it did not anticipate. Invisible from macOS.
    """

    FAMILY = "Claude_pzs8sxrjxfjjc"

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.roaming = os.path.join(self.home, "AppData", "Roaming")
        self.local = os.path.join(self.home, "AppData", "Local")
        os.makedirs(self.roaming)
        os.makedirs(self.local)

    def _env(self, **extra):
        env = {"APPDATA": self.roaming, "LOCALAPPDATA": self.local}
        env.update(extra)
        return env

    def _msix(self, family=None, name="Claude", mtime=None):
        d = os.path.join(self.local, "Packages", family or self.FAMILY,
                         "LocalCache", "Roaming", name)
        return _make_claude_dir(d, mtime if mtime is not None else time.time())

    def _resolve(self, env=None):
        return harness_paths.claude_desktop_config(
            home=self.home, env=env if env is not None else self._env(),
            platform=WINDOWS)

    def test_a_store_install_is_found_from_outside_the_container(self):
        # Exactly the machine in the report: nothing under %APPDATA%\Claude
        # from this shell, the real directory under Packages.
        cfg = self._msix()
        self.assertEqual(self._resolve(), cfg)

    def test_the_family_is_globbed_not_hardcoded(self):
        # The full package identity changes with every app version; even the
        # family suffix should not be load-bearing in code.
        cfg = self._msix(family="Claude_someotherfamily")
        self.assertEqual(self._resolve(), cfg)

    def test_the_store_path_wins_a_tie_with_the_redirected_one(self):
        # Inside the container both names point at ONE directory, so their
        # recency is identical. Prefer the name that works from everywhere.
        now = time.time()
        store = self._msix(mtime=now)
        _make_windows_claude_dir(self.roaming, "Claude", now)
        self.assertEqual(self._resolve(), store)

    def test_a_genuinely_newer_non_store_install_still_wins(self):
        # Recency still decides between two REAL installs, as it does for
        # Claude vs Claude-3p.
        self._msix(mtime=time.time() - 200 * 86400)
        live = _make_windows_claude_dir(self.roaming, "Claude", time.time())
        self.assertEqual(self._resolve(), live)

    def test_localappdata_falls_back_to_the_conventional_location(self):
        cfg = self._msix()
        self.assertEqual(self._resolve(env={"APPDATA": self.roaming}), cfg)

    def test_macos_never_looks_for_store_packages(self):
        self._msix()
        self.assertIsNone(harness_paths.claude_desktop_config(
            home=self.home, env=self._env(), platform=DARWIN))


class TestDesktopPresentButConfigMissing(unittest.TestCase):
    """The installed-but-unfound case must be loud, not a skip.

    "not installed, skipping" with exit 0 reads to an agent as "fine, nothing to
    do". When there is evidence the app IS installed, a missing config is a
    contradiction and deserves a refusal.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.local = os.path.join(self.home, "AppData", "Local")
        self.apps = tempfile.mkdtemp()

    def _evidence(self, platform, env=None):
        return harness_paths.claude_desktop_evidence(
            home=self.home, env=env or {"LOCALAPPDATA": self.local},
            platform=platform, app_dirs=[self.apps])

    def test_nothing_installed_is_no_evidence(self):
        self.assertEqual(self._evidence(WINDOWS), [])
        self.assertEqual(self._evidence(DARWIN), [])

    def test_a_store_package_never_launched_is_evidence(self):
        # Package directory exists, but the app has never run, so there is no
        # LocalCache\\Roaming\\Claude yet.
        os.makedirs(os.path.join(self.local, "Packages", "Claude_pzs8sxrjxfjjc"))
        found = self._evidence(WINDOWS)
        self.assertEqual(len(found), 1)
        self.assertIn("Claude_pzs8sxrjxfjjc", found[0])

    def test_a_non_store_windows_install_is_evidence(self):
        os.makedirs(os.path.join(self.local, "AnthropicClaude"))
        self.assertEqual(len(self._evidence(WINDOWS)), 1)

    def test_a_macos_app_bundle_is_evidence(self):
        os.makedirs(os.path.join(self.apps, "Claude.app"))
        self.assertEqual(len(self._evidence(DARWIN)), 1)
