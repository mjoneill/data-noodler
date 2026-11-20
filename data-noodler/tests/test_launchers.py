"""Launchers must fail loudly on stderr and stay silent on stdout.

stdout is the MCP protocol channel. A launcher that prints a friendly error
there corrupts the stream, and the client reports an unexplained broken
server instead of the actual problem.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BIN = os.path.join(REPO, "data-noodler", "bin")
LAUNCHERS = ["launch-data-noodler", "launch-analytics-mcp"]


class TestLaunchers(unittest.TestCase):
    def test_both_launchers_exist_and_are_executable(self):
        for name in LAUNCHERS:
            path = os.path.join(BIN, name)
            self.assertTrue(os.path.exists(path), path)
            self.assertTrue(os.access(path, os.X_OK), f"{path} not executable")

    def test_missing_config_exits_nonzero_with_nothing_on_stdout(self):
        empty = tempfile.mkdtemp()
        for name in LAUNCHERS:
            with self.subTest(launcher=name):
                p = subprocess.run(
                    [os.path.join(BIN, name)],
                    env={**os.environ, "GA_HOME": empty},
                    capture_output=True, text=True, timeout=30)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, "")
                self.assertIn("data-noodler-setup", p.stderr)

    def test_absent_credential_is_not_fatal_for_the_data_noodler_server(self):
        """credential_status must stay callable so it can explain the fix.

        A launcher that aborts when the credential is missing turns an
        explainable problem into an unexplained broken server.
        """
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "server"))
        open(os.path.join(home, "server", "data_noodler.py"), "w").close()
        with open(os.path.join(home, "config.json"), "w") as f:
            json.dump({
                "oauth_client_file": "/tmp/client.json",
                "adc_file": "/nonexistent/adc.json",
                "quota_project": "p",
                "venv_python": sys.executable,
                "properties_csv": "/tmp/properties.csv",
            }, f)
        p = subprocess.run(
            [os.path.join(BIN, "launch-data-noodler")],
            env={**os.environ, "GA_HOME": home, "GA_LAUNCH_CHECK": "1"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "")

    def test_missing_interpreter_is_reported_not_silently_ignored(self):
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "config.json"), "w") as f:
            json.dump({
                "oauth_client_file": "/tmp/client.json",
                "adc_file": "/tmp/adc.json",
                "quota_project": "p",
                "venv_python": "/nonexistent/python",
                "properties_csv": "/tmp/properties.csv",
            }, f)
        p = subprocess.run(
            [os.path.join(BIN, "launch-data-noodler")],
            env={**os.environ, "GA_HOME": home},
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("/nonexistent/python", p.stderr)


class TestNoUnpinnedFallback(unittest.TestCase):
    """launch-analytics-mcp must never run whatever analytics-mcp PyPI has today.

    Its last resort used to be `uv tool run analytics-mcp`: unpinned, so a
    machine that reached it resolved the newest release at every launch -- a
    supply-chain exposure, and a version nobody had tested (#153, 2026-10-23
    security review). An install that reaches that point is not one the docs
    describe, so the launcher now fails with the setup hint instead.
    """

    def _home_with_config_but_no_program(self):
        ga_home = tempfile.mkdtemp()
        adc = os.path.join(ga_home, "adc.json")
        open(adc, "w").close()
        with open(os.path.join(ga_home, "config.json"), "w") as f:
            json.dump({"adc_file": adc}, f)
        return ga_home

    def test_it_fails_with_the_hint_rather_than_fetching_from_pypi(self):
        ga_home = self._home_with_config_but_no_program()
        fake_home = tempfile.mkdtemp()
        # A uv on PATH that records being called: the old fallback would
        # have exec'd it.
        bindir = tempfile.mkdtemp()
        marker = os.path.join(bindir, "uv-was-called")
        uv = os.path.join(bindir, "uv")
        with open(uv, "w") as f:
            f.write("#!/bin/sh\ntouch '%s'\n" % marker)
        os.chmod(uv, 0o755)
        p = subprocess.run(
            [os.path.join(BIN, "launch-analytics-mcp")],
            env={**os.environ, "GA_HOME": ga_home, "HOME": fake_home,
                 "PATH": bindir + os.pathsep + "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertFalse(os.path.exists(marker), "launcher ran uv")
        self.assertIn("data-noodler-setup", p.stderr)

    def test_the_script_no_longer_contains_the_fallback(self):
        # Code lines only: the comment explaining why it is gone may name it.
        with open(os.path.join(BIN, "launch-analytics-mcp"), encoding="utf-8") as f:
            code = [l for l in f if not l.lstrip().startswith("#")]
        self.assertFalse([l for l in code if "uv tool run" in l or "uvx" in l])


class TestNoPythonNeededToReadTheConfig(unittest.TestCase):
    """#154, measured 2026-10-29 on a ChatGPT-only partner Mac: without
    Apple's command-line tools /usr/bin/python3 is a stub that pops an
    install dialog and fails, so launchers that read config.json with it
    never started a server there. They now use /usr/bin/plutil."""

    def _code_lines(self, name):
        with open(os.path.join(BIN, name), encoding="utf-8") as f:
            return [l for l in f if not l.lstrip().startswith("#")]

    def test_neither_launcher_runs_the_system_python(self):
        for name in LAUNCHERS:
            self.assertFalse([l for l in self._code_lines(name)
                              if "/usr/bin/python3" in l], name)
            self.assertTrue([l for l in self._code_lines(name)
                             if "/usr/bin/plutil" in l], name)

    @unittest.skipUnless(sys.platform == "darwin", "plutil is macOS")
    def test_tilde_paths_and_spaces_resolve_like_expanduser(self):
        home = tempfile.mkdtemp()
        ga = os.path.join(home, "my ga")
        os.makedirs(os.path.join(ga, "server"))
        open(os.path.join(ga, "server", "data_noodler.py"), "w").close()
        # A real "~/..." path, with a space in it, to the interpreter.
        os.makedirs(os.path.join(home, "py dir"))
        os.symlink(sys.executable, os.path.join(home, "py dir", "python"))
        with open(os.path.join(ga, "config.json"), "w") as f:
            json.dump({"venv_python": "~/py dir/python",
                       "adc_file": "~/nope/adc.json"}, f)
        p = subprocess.run(
            [os.path.join(BIN, "launch-data-noodler")],
            env={**os.environ, "HOME": home, "GA_HOME": ga,
                 "GA_LAUNCH_CHECK": "1", "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "")

    @unittest.skipUnless(sys.platform == "darwin", "plutil is macOS")
    def test_a_tilde_credential_path_resolves_in_launch_ga_mcp(self):
        # launch-analytics-mcp exits 1 without a credential, so exit 0 under
        # GA_LAUNCH_CHECK proves its own copy of read_key expanded the path.
        home = tempfile.mkdtemp()
        ga = os.path.join(home, "ga")
        os.makedirs(ga)
        os.makedirs(os.path.join(home, "cred dir"))
        open(os.path.join(home, "cred dir", "adc.json"), "w").close()
        with open(os.path.join(ga, "config.json"), "w") as f:
            json.dump({"adc_file": "~/cred dir/adc.json"}, f)
        p = subprocess.run(
            [os.path.join(BIN, "launch-analytics-mcp")],
            env={**os.environ, "HOME": home, "GA_HOME": ga,
                 "GA_LAUNCH_CHECK": "1", "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "")

    def test_both_launchers_carry_the_same_read_key(self):
        # It is duplicated so each launcher stays one self-contained file;
        # this keeps a fix to one from missing the other.
        bodies = []
        for name in LAUNCHERS:
            with open(os.path.join(BIN, name), encoding="utf-8") as f:
                text = f.read()
            start = text.index("read_key() {")
            bodies.append(text[start:text.index("\n}\n", start)])
        self.assertEqual(bodies[0], bodies[1])


class TestTheLauncherSaysWhatIsActuallyWrong(unittest.TestCase):
    """Review, 2026-11-09: read_key maps every plutil failure to an empty
    string, so a damaged config.json, or a macOS without `plutil -extract
    ... raw`, was reported as a missing interpreter or credential with a
    blank path -- which sends people to reinstall or re-mint."""

    def _run(self, name, config_text, **env):
        ga = tempfile.mkdtemp()
        with open(os.path.join(ga, "config.json"), "w") as f:
            f.write(config_text)
        p = subprocess.run(
            [os.path.join(BIN, name)],
            env={**os.environ, "GA_HOME": ga, "GA_LAUNCH_CHECK": "1",
                 "PATH": "/usr/bin:/bin", **env},
            capture_output=True, text=True, timeout=30)
        return ga, p

    @unittest.skipUnless(sys.platform == "darwin", "plutil is macOS")
    def test_a_damaged_config_is_named_as_such(self):
        for name in LAUNCHERS:
            ga, p = self._run(name, '{"venv_python": "/x", ')
            self.assertEqual(p.returncode, 1, name)
            self.assertEqual(p.stdout, "", name)
            self.assertIn("not valid JSON", p.stderr, name)
            self.assertIn(os.path.join(ga, "config.json"), p.stderr, name)
            self.assertNotIn("interpreter not found", p.stderr, name)
            self.assertNotIn("no credential", p.stderr, name)

    def test_an_old_macos_is_named_as_such(self):
        for name in LAUNCHERS:
            _, p = self._run(name, "{}", GA_TEST_OS_MAJOR="11")
            self.assertEqual(p.returncode, 1, name)
            self.assertEqual(p.stdout, "", name)
            self.assertIn("macOS 12 or later", p.stderr, name)


if __name__ == "__main__":
    unittest.main()
