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
        self.assertEqual([n for n in os.listdir(self.d)
                          if n.endswith(".ga-tmp")], [])


@unittest.skipIf(sys.platform.startswith("win"), "POSIX symlinks")
class TestSymlinks(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()

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


class TestTheTempNameIsUnpredictable(unittest.TestCase):
    """Runs on every platform, Windows included: Windows is where a link at
    the old fixed name was followed (#2011)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def _symlink(self, target, link):
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here ({exc})")

    def test_a_link_planted_at_the_old_temp_name_is_never_followed(self):
        # The temp name used to be fixed (`<path>.ga-tmp`), so a link could
        # be planted there ahead of time; on Windows a dangling one was
        # followed (#2011). The name is now unpredictable, so the planted
        # link is simply never used.
        path = os.path.join(self.d, "claude.json")
        with open(path, "w") as f:
            f.write("{}")
        victim = os.path.join(self.d, "victim.txt")
        with open(victim, "w") as f:
            f.write("precious")
        self._symlink(victim, path + ".ga-tmp")
        safe_write.write_atomically(path, '{"x": 1}\n')
        with open(victim) as f:
            self.assertEqual(f.read(), "precious")
        self.assertTrue(os.path.islink(path + ".ga-tmp"))
        with open(path) as f:
            self.assertEqual(json.load(f), {"x": 1})

    def test_a_dangling_link_at_the_old_temp_name_creates_nothing(self):
        path = os.path.join(self.d, "config.json")
        target = os.path.join(self.d, "not-yet-there.txt")
        self._symlink(target, path + ".ga-tmp")
        safe_write.write_atomically(path, "{}\n")
        self.assertFalse(os.path.lexists(target))
        self.assertFalse(os.path.islink(path))
        with open(path) as f:
            self.assertEqual(f.read(), "{}\n")

    def test_a_file_left_at_the_old_temp_name_is_left_alone(self):
        path = os.path.join(self.d, "c.json")
        with open(path + ".ga-tmp", "w") as f:
            f.write("half-written")
        safe_write.write_atomically(path, "{}\n")
        with open(path) as f:
            self.assertEqual(f.read(), "{}\n")
        with open(path + ".ga-tmp") as f:
            self.assertEqual(f.read(), "half-written")

    def test_the_temp_file_is_made_in_the_target_folder(self):
        # os.replace is only atomic within one filesystem.
        from unittest import mock
        path = os.path.join(self.d, "c.json")
        with mock.patch("safe_write.tempfile.mkstemp",
                        wraps=safe_write.tempfile.mkstemp) as made:
            safe_write.write_atomically(path, "{}\n")
        self.assertEqual(os.path.realpath(made.call_args.kwargs["dir"]),
                         os.path.realpath(self.d))


def _one_second():
    """Freeze every installer module's clock to one second, so two writes
    land in it -- whichever module computes the backup stamp."""
    import contextlib
    from unittest import mock
    frozen = mock.Mock()
    frozen.datetime.now.return_value.strftime.return_value = "20261121-020000"
    stack = contextlib.ExitStack()
    for mod in ("register", "bootstrap_config", "safe_write"):
        stack.enter_context(mock.patch(mod + ".datetime", frozen,
                                       create=True))
    return stack


class TestBackupsNeverOverwriteEachOther(unittest.TestCase):
    """Backups were stamped to the second and copied over whatever was there,
    so a second write in the same second replaced the first backup -- the
    only copy of the original -- with the second (#2009)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def _start(self, name):
        path = os.path.join(self.d, name)
        with open(path, "w") as f:
            f.write('{"original": true}')
        return path

    def _backup_texts(self, name):
        out = []
        for n in sorted(os.listdir(self.d)):
            if n.startswith(name + ".ga-backup-"):
                with open(os.path.join(self.d, n)) as f:
                    out.append(f.read())
        return out

    def test_two_registrations_in_one_second_keep_the_original(self):
        path = self._start("claude.json")
        with _one_second():
            register.register_json(path, {"x": {"command": "1"}})
            register.register_json(path, {"x": {"command": "2"}})
        texts = self._backup_texts("claude.json")
        self.assertEqual(len(texts), 2, texts)
        self.assertIn('{"original": true}', texts)

    def test_two_forced_config_writes_in_one_second_keep_the_original(self):
        path = self._start("config.json")
        with _one_second():
            bootstrap_config.write_config(path, {"v": 1}, force=True)
            bootstrap_config.write_config(path, {"v": 2}, force=True)
        texts = self._backup_texts("config.json")
        self.assertEqual(len(texts), 2, texts)
        self.assertIn('{"original": true}', texts)

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX modes")
    def test_a_backup_keeps_the_original_mode(self):
        path = self._start("claude.json")
        os.chmod(path, 0o600)
        register.register_json(path, {"x": {"command": "1"}})
        name = [n for n in os.listdir(self.d) if ".ga-backup-" in n][0]
        self.assertEqual(_mode(os.path.join(self.d, name)), 0o600)

    def test_a_link_planted_at_the_backup_name_is_not_written_through(self):
        path = self._start("claude.json")
        victim = os.path.join(self.d, "victim.txt")
        with open(victim, "w") as f:
            f.write("precious")
        try:
            os.symlink(victim, path + ".ga-backup-20261121-020000")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here ({exc})")
        with _one_second():
            register.register_json(path, {"x": {"command": "1"}})
        with open(victim) as f:
            self.assertEqual(f.read(), "precious")
        self.assertIn('{"original": true}', self._backup_texts("claude.json"))


if __name__ == "__main__":
    unittest.main()
