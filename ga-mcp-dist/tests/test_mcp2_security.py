"""Security properties of the mcp 2.x port (#162, 2026-10-25).

- Tool annotations tell an app honestly what each tool may do.
- W3C trace-context parsing is off in both servers: mcp 2.x parses
  traceparent/tracestate from every inbound message, and opentelemetry-api's
  tracestate parser carries CVE-2026-114603, whose fix google-adk does not
  yet allow.
- analytics-mcp 0.8.0's write tool stays off: no entry ever passes
  --allow-write.
- A probe leaves no server process behind.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
COMPANION = os.path.join(ROOT, "companion")
SERVER = os.path.join(COMPANION, "ga_companion.py")
sys.path.insert(0, os.path.join(ROOT, "installer"))

import register  # noqa: E402

try:
    import mcp.server.mcpserver  # noqa: F401
    MCP2 = True
except ImportError:
    MCP2 = False

WRITE_PARAMS = {"out_file", "session_dir", "overwrite", "root"}


def _tools():
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        env = dict(os.environ, GA_MCP_CONFIG="/nonexistent/config.json")
        params = StdioServerParameters(command=sys.executable, args=[SERVER],
                                       env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return (await session.list_tools()).tools
    return asyncio.run(run())


def _ann(tool, field):
    ann = tool.annotations
    return getattr(ann, field, None) if ann else None


@unittest.skipUnless(MCP2, "the shipped server targets mcp 2.x")
class TestToolAnnotations(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tools = {t.name: t for t in _tools()}

    def test_every_tool_is_annotated(self):
        for name, tool in self.tools.items():
            self.assertIsNotNone(tool.annotations, name)
            self.assertIsNotNone(_ann(tool, "read_only_hint"), name)

    def test_a_tool_marked_read_only_cannot_write_a_file(self):
        for name, tool in self.tools.items():
            if _ann(tool, "read_only_hint"):
                params = set((tool.input_schema or {}).get("properties", {}))
                self.assertFalse(params & WRITE_PARAMS,
                                 f"{name} is marked read-only but takes "
                                 f"{params & WRITE_PARAMS}")

    def test_a_tool_that_can_overwrite_says_it_may_be_destructive(self):
        for name, tool in self.tools.items():
            params = set((tool.input_schema or {}).get("properties", {}))
            if "overwrite" in params:
                self.assertFalse(_ann(tool, "read_only_hint"), name)
                self.assertTrue(_ann(tool, "destructive_hint"), name)

    def test_the_server_reports_a_version(self):
        import ga_companion  # noqa: F401  (imported for SERVER_VERSION)
        self.assertTrue(ga_companion.SERVER_VERSION)


@unittest.skipUnless(MCP2, "the shipped server targets mcp 2.x")
class TestTraceContextParsingIsOff(unittest.TestCase):

    def test_the_server_drops_the_tracing_middleware_and_propagators(self):
        code = ("import os,sys; os.environ.pop('OTEL_PROPAGATORS', None);"
                f"sys.path.insert(0, {COMPANION!r}); import ga_companion as g;"
                "from opentelemetry.propagate import get_global_textmap as t;"
                "print([type(m).__name__ for m in g.mcp._lowlevel_server.middleware]);"
                "print(len(t()._propagators))")
        env = dict(os.environ, GA_MCP_CONFIG="/nonexistent/config.json")
        env.pop("OTEL_PROPAGATORS", None)
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        middleware, propagators = out.stdout.strip().splitlines()
        self.assertNotIn("OpenTelemetryMiddleware", middleware)
        self.assertEqual(propagators, "0")


class TestEntriesAndLaunchers(unittest.TestCase):

    def _all_entries(self):
        win = register.server_entries(
            r"C:\Users\x\.config\ga-mcp", platform="win32",
            venv_python=r"C:\Users\x\.config\ga-mcp\venv\Scripts\python.exe",
            adc_file=r"C:\Users\x\.config\gcloud\adc-ga-personal.json")
        posix = register.server_entries("/Users/x/.config/ga-mcp",
                                        platform="darwin")
        return list(win.items()) + list(posix.items())

    def test_every_entry_switches_trace_parsing_off(self):
        for name, entry in self._all_entries():
            self.assertEqual(entry["env"].get("OTEL_PROPAGATORS"), "none", name)

    def test_both_launchers_switch_trace_parsing_off(self):
        for name in ("launch-ga-mcp", "launch-ga-companion"):
            with open(os.path.join(ROOT, "bin", name), encoding="utf-8") as f:
                self.assertIn("export OTEL_PROPAGATORS=none", f.read(), name)

    def test_no_entry_enables_analytics_mcp_writes(self):
        # analytics-mcp 0.8.0 adds create_property_annotation behind
        # --allow-write. This package is read-only by design.
        for name, entry in self._all_entries():
            self.assertNotIn("--allow-write", entry.get("args", []), name)
        for name in ("launch-ga-mcp",):
            with open(os.path.join(ROOT, "bin", name), encoding="utf-8") as f:
                code = [l for l in f if not l.lstrip().startswith("#")]
            self.assertFalse([l for l in code if "allow-write" in l])


@unittest.skipUnless(MCP2, "the shipped server targets mcp 2.x")
class TestAProbeLeavesNoServerBehind(unittest.TestCase):
    """mcp 2.x reworked stdio_client shutdown; its migration notes say a
    gracefully exited server's children are left alive on POSIX."""

    def _alive_with_marker(self, marker):
        out = subprocess.run(["ps", "eww", "-ax", "-o", "pid=,command="],
                             capture_output=True, text=True).stdout
        return [l for l in out.splitlines()
                if marker in l and "ps eww" not in l]

    @unittest.skipIf(sys.platform.startswith("win"), "uses ps")
    def test_verify_probe_leaves_no_companion_process(self):
        import time
        import verify
        marker = "GA_PROBE_MARKER=" + uuid.uuid4().hex
        env = dict(os.environ, GA_MCP_CONFIG="/nonexistent/config.json")
        env["GA_PROBE_MARKER"] = marker.split("=", 1)[1]
        result = verify.probe(sys.executable, [SERVER], env=env)
        self.assertTrue(result["ok"], result["error"])
        for _ in range(20):
            if not self._alive_with_marker(marker):
                break
            time.sleep(0.25)
        self.assertEqual(self._alive_with_marker(marker), [])


if __name__ == "__main__":
    unittest.main()
