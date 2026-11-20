"""Config rewrites must not loosen permissions or follow planted symlinks (#157).

Reproduced 2026-10-25: register_json turned a 0600 ~/.claude.json into 0644.
That file can hold API keys and other MCP servers' secrets.
"""

import json
import os
import stat
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import bootstrap_config  # noqa: E402
import register  # noqa: E402
import safe_write  # noqa: E402


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@unittest.skipIf(sys.platform.startswith("win"), "POSIX permission bits")
class TestPermissionsSurviveARewrite(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old_umask = os.umask(0o022)

    def tearDown(self):
        os.umask(self.old_umask)

    def _config(self, mode=0o600, body="{}"):
        path = os.path.join(self.d, "claude.json")
        with open(path, "w") as f:
            f.write(body)
        os.chmod(path, mode)
        return path

    def test_a_private_harness_config_stays_private(self):
        path = self._config(0o600)
        register.register_json(path, {"x": {"command": "y"}})
        self.assertEqual(_mode(path), 0o600)
        with open(path) as f:
            self.assertIn("x", json.load(f)["mcpServers"])

    def test_a_new_harness_config_is_created_private(self):
        path = os.path.join(self.d, "new.json")
        register.register_json(path, {"x": {"command": "y"}})
        self.assertEqual(_mode(path), 0o600)

    def test_a_config_an_earlier_version_loosened_is_made_private_again(self):
        # Earlier installs left ~/.claude.json 0644; every partner machine
        # installed before this release has that. Registration repairs it.
        path = self._config(0o644)
        register.register_json(path, {"x": {"command": "y"}})
        self.assertEqual(_mode(path), 0o600)

    def test_an_unchanged_registration_still_repairs_the_mode(self):
        path = self._config(0o644)
        register.register_json(path, {"x": {"command": "y"}})
        os.chmod(path, 0o644)
        result = register.register_json(path, {"x": {"command": "y"}})
        self.assertFalse(result["changed"])
        self.assertEqual(_mode(path), 0o600)

    def test_the_general_writer_still_only_promises_not_to_loosen(self):
        path = self._config(0o640)
        safe_write.write_atomically(path, "{}\n")
        self.assertEqual(_mode(path), 0o640)

    def test_config_json_is_created_private(self):
        path = os.path.join(self.d, "ga", "config.json")
        bootstrap_config.write_config(path, {"venv_python": "/x"})
        self.assertEqual(_mode(path), 0o600)

    def test_no_temp_file_is_left_behind(self):
        path = self._config()
        register.register_json(path, {"x": {"command": "y"}})
        self.assertFalse(os.path.lexists(path + ".ga-tmp"))


@unittest.skipIf(sys.platform.startswith("win"), "POSIX symlinks")
class TestSymlinks(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_a_planted_temp_symlink_is_refused_and_its_target_untouched(self):
        path = os.path.join(self.d, "claude.json")
        with open(path, "w") as f:
            f.write("{}")
        victim = os.path.join(self.d, "victim.txt")
        with open(victim, "w") as f:
            f.write("precious")
        os.symlink(victim, path + ".ga-tmp")
        with self.assertRaises(register.RegisterError):
            register.register_json(path, {"x": {"command": "y"}})
        with open(victim) as f:
            self.assertEqual(f.read(), "precious")

    def test_a_symlinked_config_is_written_through_not_replaced(self):
        real = os.path.join(self.d, "dotfiles-claude.json")
        with open(real, "w") as f:
            f.write("{}")
        link = os.path.join(self.d, "claude.json")
        os.symlink(real, link)
        register.register_json(link, {"x": {"command": "y"}})
        self.assertTrue(os.path.islink(link), "the link was replaced")
        with open(real) as f:
            self.assertIn("x", json.load(f)["mcpServers"])

    def test_a_regular_leftover_temp_file_is_cleared(self):
        path = os.path.join(self.d, "c.json")
        with open(path + ".ga-tmp", "w") as f:
            f.write("half-written")
        safe_write.write_atomically(path, "{}\n")
        with open(path) as f:
            self.assertEqual(f.read(), "{}\n")


if __name__ == "__main__":
    unittest.main()
