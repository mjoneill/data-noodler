"""The skill's fallback scripts must fail as gracefully as the server (#2007 R2, R3).

The skill ships its own copies of two things the server also does: loading
config.json (scripts/ga_config.py vs server/config.py) and rendering property
matches (scripts/lookup_property.py vs server/matching.py). The scripts are
what an agent falls back on when the MCP tools are unavailable -- usually in a
terminal, during setup, exactly when a config is most likely to be half
written. An outside review (2026-11-20) found the server copies had been
hardened and the script copies had not: a malformed config.json or a short
snapshot row gave the server a sentence and the scripts a traceback.

These tests run the scripts as a user would, as subprocesses, and require a
plain message and no traceback. The malformed-config cases run against BOTH
loaders, so the two copies cannot drift apart on this again without a test
failing.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "marketplace", "plugins", "data-noodler",
                       "skills", "data-noodler", "scripts")
sys.path.insert(0, os.path.join(ROOT, "server"))
import config as server_config  # noqa: E402

# Each case: (name, file contents as text). Every one is a config.json a real
# user could end up with -- a half-saved edit, a wrong paste, a hand edit.
MALFORMED = [
    ("not json", "{ this is not json"),
    ("a list", '["oauth_client_file", "adc_file"]'),
    ("a string", '"just a string"'),
    ("a non-string path", json.dumps({
        "oauth_client_file": "~/a.json", "adc_file": 7,
        "venv_python": "~/v/bin/python", "properties_csv": "~/p.csv"})),
    ("not utf-8", None),  # written as raw bytes below
]


def _write_config(directory, text):
    path = os.path.join(directory, "config.json")
    with open(path, "wb") as f:
        f.write(b"\xff\xfe{\x00" if text is None else text.encode("utf-8"))
    return path


def _run(script, args, config_path):
    env = dict(os.environ, DATA_NOODLER_CONFIG=config_path)
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)


class TestBothLoadersRefuseAMalformedConfigPlainly(unittest.TestCase):

    def test_the_server_loader_raises_config_error(self):
        for name, text in MALFORMED:
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(server_config.ConfigError):
                    server_config.load(_write_config(d, text))

    def test_the_skill_loader_exits_with_a_message_not_a_traceback(self):
        for name, text in MALFORMED:
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                r = _run("lookup_property.py", ["anything"], _write_config(d, text))
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("config.json", r.stderr)


class TestLookupSurvivesADamagedSnapshot(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv = os.path.join(self.tmp.name, "properties.csv")
        self.config = os.path.join(self.tmp.name, "config.json")
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump({"oauth_client_file": "~/c.json", "adc_file": "~/a.json",
                       "venv_python": sys.executable,
                       "properties_csv": self.csv}, f)

    def _snapshot(self, text):
        with open(self.csv, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def test_a_short_row_is_shown_with_a_rebuild_hint_not_a_type_error(self):
        # The row the review named: the name matches, the id is missing.
        self._snapshot("property_name,account_name,property_id\n"
                       "example.edu,Example\n")
        r = _run("lookup_property.py", ["example.edu"], self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("properties/?", r.stdout)
        self.assertIn("refresh_properties.py", r.stdout)
        # An unusable id must never be offered as the answer.
        self.assertNotIn("Unambiguous: use properties/None", r.stdout)
        self.assertNotIn("Unambiguous: use properties/?", r.stdout)

    def test_a_wrong_header_is_a_message_not_a_key_error(self):
        self._snapshot("name,account,id\nexample.edu,Example,123\n")
        r = _run("lookup_property.py", ["example.edu"], self.config)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("refresh_properties.py", r.stderr)

    def test_a_non_ascii_name_is_read_as_utf8_whatever_the_locale(self):
        self._snapshot("property_name,account_name,property_id\n"
                       "café.example,Exämple,123456\n")
        env_locale = dict(os.environ, DATA_NOODLER_CONFIG=self.config,
                          PYTHONUTF8="0", LC_ALL="C", LANG="C",
                          PYTHONCOERCECLOCALE="0")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "lookup_property.py"),
             "café.example"],
            capture_output=True, env=env_locale, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("properties/123456", out)

    def test_a_healthy_snapshot_still_answers_unambiguously(self):
        self._snapshot("property_name,account_name,property_id\n"
                       "example.edu,Example,123456\n"
                       "news.example.edu,Example,234567\n")
        r = _run("lookup_property.py", ["example.edu"], self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Unambiguous: use properties/123456", r.stdout)


if __name__ == "__main__":
    unittest.main()
