"""verify.py must say WHY a server failed when the failure has a known cause.

The case that prompted this (round 4, 2026-10-09, #142): on a managed Windows
machine verify.py printed

    FAIL analytics-mcp: PermissionError: [WinError 5] Access is denied

and nothing else. The cause was Microsoft Defender's Attack Surface Reduction
rule refusing a pip-generated .exe. "Access is denied" next to a server that
reads a credential invites the one wrong diagnosis this package keeps
warning about -- renew the credential -- so the output has to name the real
cause itself.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "data-noodler", "installer"))

import verify  # noqa: E402

ASR_ERROR = "PermissionError: [WinError 5] Access is denied"
EXE = r"C:\Users\example\.config\data-noodler\venv\Scripts\analytics-mcp.exe"
PY = r"C:\Users\example\.config\data-noodler\venv\Scripts\python.exe"


class TestAccessDeniedOnWindows(unittest.TestCase):

    def test_a_denied_exe_is_attributed_to_defender_not_credentials(self):
        hint = verify.hint_for(ASR_ERROR, EXE)
        self.assertIsNotNone(hint)
        self.assertIn("Defender", hint)
        self.assertIn("not a credential problem", hint)

    def test_the_hint_names_the_event_to_check(self):
        hint = verify.hint_for(ASR_ERROR, EXE)
        self.assertIn("1121", hint)
        self.assertIn("Windows Defender/Operational", hint)

    def test_a_denied_exe_points_at_the_python_m_entry(self):
        hint = verify.hint_for(ASR_ERROR, EXE)
        self.assertIn("install.py", hint)
        self.assertIn("-m analytics_mcp.server", hint)

    def test_a_denied_interpreter_does_not_suggest_the_same_interpreter(self):
        # If python.exe itself is refused, "switch to python.exe" is no fix.
        hint = verify.hint_for(ASR_ERROR, PY)
        self.assertIsNotNone(hint)
        self.assertIn("Defender", hint)
        self.assertNotIn("-m analytics_mcp.server", hint)

    def test_the_english_message_alone_is_enough(self):
        hint = verify.hint_for("OSError: Access is denied", EXE)
        self.assertIsNotNone(hint)

    def test_unrelated_failures_get_no_hint(self):
        for err in ("FileNotFoundError: [Errno 2] No such file or directory",
                    "TimeoutError: ", "ExceptionGroup: unhandled errors"):
            self.assertIsNone(verify.hint_for(err, EXE), err)

    def test_no_error_no_hint(self):
        self.assertIsNone(verify.hint_for(None, EXE))
        self.assertIsNone(verify.hint_for("", EXE))


class TestTheHintReachesTheOutput(unittest.TestCase):

    def _config(self, command):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"analytics-mcp": {
                "command": command, "args": []}}}, f)
        return path

    def test_probe_config_attaches_the_hint_to_the_failing_entry(self):
        failing = {"ok": False, "tools": [], "error": ASR_ERROR}
        with mock.patch.object(verify, "probe", return_value=failing):
            results = verify.probe_config(self._config(EXE))
        self.assertIn("Defender", results["analytics-mcp"]["hint"])

    def test_main_prints_the_hint_under_the_fail_line(self):
        failing = {"ok": False, "tools": [], "error": ASR_ERROR}
        path = self._config(EXE)
        out = []
        with mock.patch.object(verify, "probe", return_value=failing), \
                mock.patch.object(sys, "argv", ["verify.py", "--config", path]), \
                mock.patch("builtins.print",
                           side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
            code = verify.main()
        self.assertEqual(code, 1)
        text = "\n".join(out)
        self.assertIn("FAIL  analytics-mcp", text)
        self.assertIn("Defender", text)
        fail_at = text.index("FAIL  analytics-mcp")
        self.assertGreater(text.index("Defender"), fail_at)


if __name__ == "__main__":
    unittest.main()


class TestRequireScopesTheCheckToOurServers(unittest.TestCase):
    """A broken server that belongs to someone else must not fail our install."""

    def test_an_unrelated_broken_server_does_not_change_the_exit_code(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {
                "data-noodler": {"command": "a"},
                "someone-else": {"command": "b"}}}, f)
        probed = []

        def fake_probe(command, args, env=None, timeout=45.0):
            probed.append(command)
            return {"ok": True, "tools": [f"t{i}" for i in range(15)],
                    "error": None}

        argv = ["verify.py", "--config", path, "--require", "data-noodler=15"]
        with mock.patch.object(verify, "probe", fake_probe), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch("builtins.print"):
            code = verify.main()
        self.assertEqual(code, 0)
        self.assertEqual(probed, ["a"], "the unrelated server was probed")

    def test_a_required_server_that_is_missing_still_fails(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"data-noodler": {"command": "a"}}}, f)
        ok = {"ok": True, "tools": ["t"] * 15, "error": None}
        argv = ["verify.py", "--config", path, "--require", "data-noodler=15",
                "--require", "analytics-mcp=9"]
        with mock.patch.object(verify, "probe", return_value=ok), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch("builtins.print"):
            self.assertEqual(verify.main(), 1)
