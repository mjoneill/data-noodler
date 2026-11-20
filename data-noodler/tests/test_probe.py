"""The machine fact sheet: stable keys, no writes, no opinions.

probe.py exists so the setup skill does not have to carry shell snippets an
agent must translate into PowerShell. Its value depends on three properties,
each asserted here: it never writes, its keys are stable enough to branch on,
and it reports an unreadable file as a fact rather than dying on it.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import probe

DARWIN = "darwin"
WINDOWS = "win32"


def _snapshot(root):
    out = {}
    for base, dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            try:
                out[p] = os.stat(p).st_mtime_ns
            except OSError:
                pass
    return out


class TestProbeNeverWrites(unittest.TestCase):
    """The whole safety argument for running this unsupervised."""

    def test_collect_changes_nothing_under_home(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".config", "ga-mcp"))
        cfg = os.path.join(home, ".config", "ga-mcp", "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"venv_python": "/x/py", "adc_file": "/x/adc.json"}, f)

        before = _snapshot(home)
        probe.collect(home=home, env={}, platform=DARWIN, check_imports=False)
        self.assertEqual(_snapshot(home), before)

    def test_it_does_not_create_a_missing_home_tree(self):
        home = os.path.join(tempfile.mkdtemp(), "not-created-yet")
        probe.collect(home=home, env={}, platform=DARWIN, check_imports=False)
        self.assertFalse(os.path.exists(home))


class TestProbeShape(unittest.TestCase):
    """Keys an agent is told to branch on must exist even when nothing does."""

    TOP = ("platform", "home", "python", "analytics_mcp", "config",
           "credential", "harnesses", "payload")

    def test_every_section_is_present_on_a_bare_machine(self):
        home = tempfile.mkdtemp()
        facts = probe.collect(home=home, env={}, platform=DARWIN,
                              check_imports=False)
        for key in self.TOP:
            self.assertIn(key, facts, key)

    def test_both_harnesses_are_always_reported(self):
        home = tempfile.mkdtemp()
        facts = probe.collect(home=home, env={}, platform=DARWIN,
                              check_imports=False)
        self.assertEqual(sorted(facts["harnesses"]),
                         ["claude_code", "claude_desktop"])

    def test_the_platform_it_was_asked_about_is_the_one_reported(self):
        home = tempfile.mkdtemp()
        facts = probe.collect(home=home, env={}, platform=WINDOWS,
                              check_imports=False)
        self.assertEqual(facts["platform"], WINDOWS)


class TestProbeReportsRatherThanFails(unittest.TestCase):
    def test_an_unparseable_config_is_a_fact_not_a_crash(self):
        home = tempfile.mkdtemp()
        d = os.path.join(home, ".config", "ga-mcp")
        os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        facts = probe.collect(home=home, env={}, platform=DARWIN,
                              check_imports=False)
        self.assertTrue(facts["config"]["exists"])
        self.assertIsNotNone(facts["config"]["error"])

    def test_an_unparseable_harness_config_is_reported_per_harness(self):
        home = tempfile.mkdtemp()
        with open(os.path.join(home, ".claude.json"), "w",
                  encoding="utf-8") as f:
            f.write("{ truncated")
        facts = probe.collect(home=home, env={}, platform=DARWIN,
                              check_imports=False)
        code = facts["harnesses"]["claude_code"]
        self.assertTrue(code["config_exists"])
        self.assertFalse(code["parses"])
        self.assertIsNotNone(code["error"])

    def test_existing_unrelated_servers_are_listed_separately(self):
        # So an agent can see it is writing into a populated config and say
        # so, rather than discovering it by overwriting something.
        home = tempfile.mkdtemp()
        with open(os.path.join(home, ".claude.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"mcpServers": {"data-noodler": {}, "some-other": {}}}, f)
        facts = probe.collect(home=home, env={}, platform=DARWIN,
                              check_imports=False)
        code = facts["harnesses"]["claude_code"]
        self.assertEqual(code["ga_servers_registered"], ["data-noodler"])
        self.assertEqual(code["other_servers"], ["some-other"])


class TestProbeCommandLine(unittest.TestCase):
    def test_it_runs_and_emits_parseable_json(self):
        home = tempfile.mkdtemp()
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "installer", "probe.py"),
             "--json", "--home", home, "--skip-import-check"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        facts = json.loads(proc.stdout)
        self.assertIn("harnesses", facts)

    def test_stdout_is_json_and_nothing_else(self):
        # An agent parses this. A stray print would break it the same way a
        # stray print breaks an MCP server's stdio channel.
        home = tempfile.mkdtemp()
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "installer", "probe.py"),
             "--json", "--home", home, "--skip-import-check"],
            capture_output=True, text=True, timeout=120)
        json.loads(proc.stdout)      # raises if anything else was printed


class TestProbeReportsVulnerableDependencies(unittest.TestCase):
    """An upgrade copies the payload and never touches the venv, so the venv
    is where old, vulnerable libraries survive (#152, 2026-10-23)."""

    def _fake_interpreter(self, versions):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "python")
        with open(path, "w") as f:
            f.write("#!/bin/sh\necho '%s'\n" % json.dumps(versions))
        os.chmod(path, 0o755)
        return path

    def test_an_old_venv_is_reported_below_its_floors(self):
        fake = self._fake_interpreter({"pyjwt": "2.13.0", "certifi": "2026.7.22",
                                       "urllib3": "2.8.0", "pip": None})
        out = probe.probe_dependencies(fake)
        self.assertIsNone(out["error"])
        self.assertEqual(set(out["below_floor"]), {"pyjwt", "certifi"})
        self.assertEqual(out["below_floor"]["pyjwt"],
                         {"installed": "2.13.0", "floor": "2.15.1"})

    def test_a_current_venv_reports_nothing_below(self):
        fake = self._fake_interpreter({"pyjwt": "2.15.1", "certifi": "2026.10.23"})
        self.assertEqual(probe.probe_dependencies(fake)["below_floor"], {})

    def test_a_real_interpreter_answers_for_every_floor_package(self):
        out = probe.probe_dependencies(sys.executable)
        self.assertIsNone(out["error"], out["error"])
        self.assertEqual(set(out["versions"]),
                         set(probe.security_floors.FLOORS))

    def test_no_interpreter_is_a_fact_not_a_crash(self):
        self.assertTrue(probe.probe_dependencies(None)["error"])
        self.assertTrue(probe.probe_dependencies("/nonexistent/python")["error"])

    def test_skipping_the_import_check_skips_this_too(self):
        facts = probe.collect(home=tempfile.mkdtemp(), check_imports=False)
        self.assertIn("skipped", facts["dependencies"])
