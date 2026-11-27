"""install.py must create the sessions root, or the first export ever run
fails with a confusing "does not exist. Create it first" error.

sessions.start_session deliberately refuses to create its root -- that
guard stays -- so something upstream has to. Resolution reads the same
config.sessions_root(cfg) the server itself calls, so the installer and the
server can never disagree about where the root is. install.py's
--payload-only path can run before any config.json exists on the machine,
so a missing or unreadable config must fall back to
sessions.DEFAULT_SESSIONS_ROOT rather than aborting the install, and a
failure to create the directory (bad parent, permission denied) must be
reported, never raised -- the rest of the package is fully usable without
it.

Everything here runs against a temp directory and an injected config path;
the real ~/Documents is never touched.
"""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import install
import sessions

GOOD = {
    "oauth_client_file": "~/.config/gcloud/data-noodler-client.json",
    "adc_file": "~/.config/gcloud/data-noodler-credential.json",
    "quota_project": "data-noodler-123456",
    "venv_python": "~/Library/Application Support/pipx/venvs/analytics-mcp/bin/python",
    "properties_csv": "~/.config/data-noodler/properties.csv",
}


class TempConfigMixin:
    def _write_config(self, data):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: None)  # tempdir left for inspection is fine
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path


class TestResolveSessionsRoot(TempConfigMixin, unittest.TestCase):
    def test_honors_a_configured_non_default_root(self):
        tmp = tempfile.mkdtemp()
        custom = os.path.join(tmp, "custom-sessions")
        cfg = dict(GOOD)
        cfg["sessions_root"] = custom
        path = self._write_config(cfg)

        root = install.resolve_sessions_root(ROOT, config_path=path)
        self.assertEqual(root, custom)

    def test_falls_back_to_default_when_config_is_missing(self):
        root = install.resolve_sessions_root(
            ROOT, config_path="/nonexistent/data-noodler/config.json")
        self.assertEqual(root, os.path.expanduser(sessions.DEFAULT_SESSIONS_ROOT))

    def test_falls_back_to_default_when_config_is_unreadable(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            f.write("{not json")

        root = install.resolve_sessions_root(ROOT, config_path=path)
        self.assertEqual(root, os.path.expanduser(sessions.DEFAULT_SESSIONS_ROOT))


class TestEnsureSessionsRoot(unittest.TestCase):
    def test_creates_the_root_when_absent(self):
        tmp = tempfile.mkdtemp()
        target = os.path.join(tmp, "analyst-sessions")
        self.assertFalse(os.path.isdir(target))

        with contextlib.redirect_stdout(io.StringIO()) as out:
            install.ensure_sessions_root(target)

        self.assertTrue(os.path.isdir(target))
        self.assertIn(target, out.getvalue())

    def test_an_existing_root_is_success_not_error(self):
        tmp = tempfile.mkdtemp()
        target = os.path.join(tmp, "analyst-sessions")
        os.makedirs(target)

        with contextlib.redirect_stdout(io.StringIO()):
            install.ensure_sessions_root(target)  # must not raise

        self.assertTrue(os.path.isdir(target))

    def test_uncreatable_root_reports_and_does_not_raise(self):
        tmp = tempfile.mkdtemp()
        # A file where a parent directory needs to be -- os.makedirs cannot
        # create a directory through it.
        blocker = os.path.join(tmp, "blocker")
        with open(blocker, "w") as f:
            f.write("x")
        target = os.path.join(blocker, "analyst-sessions")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            install.ensure_sessions_root(target)  # must not raise

        self.assertFalse(os.path.isdir(target))
        self.assertIn(target, out.getvalue())

    @unittest.skipIf(sys.platform.startswith("win"),
                     "a read-only folder mode does not stop mkdir on Windows")
    def test_permission_denied_reports_and_does_not_raise(self):
        tmp = tempfile.mkdtemp()
        locked = os.path.join(tmp, "locked")
        os.makedirs(locked)
        os.chmod(locked, stat.S_IREAD | stat.S_IEXEC)
        self.addCleanup(os.chmod, locked, stat.S_IRWXU)
        target = os.path.join(locked, "analyst-sessions")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            install.ensure_sessions_root(target)  # must not raise

        self.assertFalse(os.path.isdir(target))
        self.assertIn(target, out.getvalue())


if __name__ == "__main__":
    unittest.main()
