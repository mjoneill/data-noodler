"""The server must complete an MCP handshake and expose exactly the tools in EXPECTED_TOOLS.

Spawns the server as a real subprocess over stdio, the way a client does, so
this catches the class of bug that unit tests cannot: anything written to
stdout at startup corrupts the protocol stream and the client reports a broken
server with no useful error.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SERVER = os.path.join(REPO, "data-noodler", "server", "data_noodler.py")
FIXTURE_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures", "properties.csv")

EXPECTED_TOOLS = {
    "lookup_property", "credential_status", "refresh_property_snapshot",
    "reporting_guide", "start_session", "export_report",
    "gsc_list_sites", "gsc_inspect_urls", "gsc_search_analytics",
    "gsc_list_sitemaps", "check_compatibility", "property_setup",
    "export_cohort_report", "export_realtime_report", "export_funnel_report",
}


def _write_config(csv_path=FIXTURE_CSV, **extra):
    """A config pointing at the fixture snapshot, so no credential is needed."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "config.json")
    with open(path, "w") as f:
        json.dump({**extra,
            "oauth_client_file": os.path.join(d, "client.json"),
            "adc_file": os.path.join(d, "adc.json"),
            "quota_project": "test-project",
            "venv_python": sys.executable,
            "properties_csv": csv_path,
        }, f)
    return path


def _call_lookup(csv_path, query):
    """Call lookup_property over a real stdio handshake; return its text.

    A real handshake rather than an in-process call, because the failure this
    exercises is only user-visible as tool text: a raised exception inside a
    tool handler reaches the user as "Error executing tool lookup_property:
    ..." with the builtin's repr in it.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["DATA_NOODLER_CONFIG"] = _write_config(csv_path=csv_path)

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=[SERVER], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "lookup_property", {"query": query})
                return "".join(c.text for c in result.content
                               if hasattr(c, "text"))

    return asyncio.run(run())


def _schema(tool):
    """A tool's input schema: input_schema in mcp 2.x, inputSchema in 1.x."""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)


def _list_tools():
    """The tools as a client sees them, descriptions and schemas included."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["DATA_NOODLER_CONFIG"] = _write_config()

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=[SERVER], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return list(tools.tools)

    return asyncio.run(run())


class TestHandshake(unittest.TestCase):
    def test_server_handshakes_and_lists_its_tools(self):
        self.assertEqual({t.name for t in _list_tools()}, EXPECTED_TOOLS)

    def test_every_parameter_a_description_advertises_actually_exists(self):
        """A tool description saying `enrich=true` while the tool takes no
        such parameter is worse than saying nothing: Pydantic drops the
        unknown field silently, so the agent asks for the discriminator, gets
        no error, and believes it received one. gsc_list_sites shipped
        exactly that. Checked against the real schema a client receives.
        """
        for tool in _list_tools():
            advertised = set(re.findall(r"\b([a-z][a-z0-9_]*)=",
                                        tool.description or ""))
            declared = set((_schema(tool) or {}).get("properties", {}))
            with self.subTest(tool=tool.name):
                self.assertEqual(
                    advertised - declared, set(),
                    f"{tool.name} advertises parameters it does not accept")

    def test_gsc_list_sites_accepts_the_enrich_discriminator(self):
        by_name = {t.name: t for t in _list_tools()}
        props = _schema(by_name["gsc_list_sites"])["properties"]
        self.assertIn("enrich", props)

    def test_export_report_accepts_a_dimension_filter(self):
        # Without it host_scope can never return "filtered" in production and
        # every sidecar records dimension_filter: null, so the query the
        # provenance record claims to describe cannot be re-run.
        by_name = {t.name: t for t in _list_tools()}
        props = _schema(by_name["export_report"])["properties"]
        self.assertIn("dimension_filter", props)

    def test_lookup_property_returns_the_fixture_property_id(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env["DATA_NOODLER_CONFIG"] = _write_config()

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[SERVER], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "lookup_property", {"query": "admissions.example.edu"})
                    return "".join(c.text for c in result.content
                                   if hasattr(c, "text"))

        out = asyncio.run(run())
        self.assertIn("properties/314159265", out)

    def test_credential_status_is_actionable_when_credential_is_absent(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env["DATA_NOODLER_CONFIG"] = _write_config()

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[SERVER], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("credential_status", {})
                    return "".join(c.text for c in result.content
                                   if hasattr(c, "text"))

        out = asyncio.run(run())
        self.assertIn("mint_adc.py", out)
        self.assertIn("restart", out.lower())

    def test_lookup_property_names_refresh_when_snapshot_is_malformed(self):
        # Two different malformed shapes, because they take different code
        # paths. Wrong column names raise KeyError out of match_properties,
        # which the tool's guard catches. A *short row* -- a truncated final
        # line, a hand edit, a row with fewer fields than the header -- does
        # not: csv.DictReader fills the missing fields with None, and
        # formatting None against a width spec raised TypeError, which the
        # guard does not catch and which reached the user as "unsupported
        # format string passed to NoneType.__format__".
        wrong_columns = "not,the,right,columns\n1,2,3,4\n"
        short_row = (
            "account_name,property_name,property_id,property,account\n"
            "Admissions,admissions.example.edu\n")

        for label, body in (("wrong columns", wrong_columns),
                            ("short row", short_row)):
            with self.subTest(malformed=label):
                d = tempfile.mkdtemp()
                bad_csv = os.path.join(d, "properties.csv")
                with open(bad_csv, "w") as f:
                    f.write(body)

                out = _call_lookup(bad_csv, "admissions.example.edu")

                self.assertIn("refresh_property_snapshot", out)
                self.assertNotIn("KeyError", out)
                self.assertNotIn("TypeError", out)
                self.assertNotIn("__format__", out)


class TestVerify(unittest.TestCase):
    """verify.probe must distinguish a working server from a broken one."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "data-noodler", "installer"))

    def test_probe_reports_tools_for_a_working_server(self):
        import verify
        env = dict(os.environ)
        env["DATA_NOODLER_CONFIG"] = _write_config()
        result = verify.probe(sys.executable, [SERVER], env=env)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(set(result["tools"]), EXPECTED_TOOLS)
        self.assertIsNone(result["error"])

    def test_probe_reports_failure_for_a_command_that_is_not_a_server(self):
        import verify
        result = verify.probe("/bin/echo", ["hello"], timeout=15.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["tools"], [])
        self.assertTrue(result["error"])

    def test_probe_reports_failure_for_a_nonexistent_command(self):
        import verify
        result = verify.probe("/nonexistent/server", [], timeout=15.0)
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_probe_config_reports_missing_command_and_still_probes_others(self):
        import verify

        d = tempfile.mkdtemp()
        config_path = os.path.join(d, "config.json")
        with open(config_path, "w") as f:
            json.dump({
                "mcpServers": {
                    "broken": {"args": ["--foo"]},
                    "good": {
                        "command": sys.executable,
                        "args": [SERVER],
                        "env": {"DATA_NOODLER_CONFIG": _write_config()},
                    },
                }
            }, f)

        results = verify.probe_config(config_path)

        self.assertFalse(results["broken"]["ok"])
        self.assertEqual(results["broken"]["tools"], [])
        self.assertIn("command", results["broken"]["error"])

        self.assertTrue(results["good"]["ok"], results["good"]["error"])
        self.assertEqual(set(results["good"]["tools"]), EXPECTED_TOOLS)

    def test_probe_config_raises_verifyerror_for_a_missing_config(self):
        # Was a bare FileNotFoundError traceback out of the one tool a user
        # runs to find out what is wrong.
        import verify
        with self.assertRaises(verify.VerifyError) as ctx:
            verify.probe_config("/nonexistent/ga/claude.json")
        self.assertIn("nothing to verify", str(ctx.exception))

    def test_probe_config_raises_verifyerror_for_malformed_json(self):
        import verify
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(verify.VerifyError) as ctx:
            verify.probe_config(path)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_probe_config_raises_verifyerror_when_mcpservers_is_not_an_object(
            self):
        import verify
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"mcpServers": ["analytics-mcp"]}, f)
        with self.assertRaises(verify.VerifyError) as ctx:
            verify.probe_config(path)
        self.assertIn("not an object", str(ctx.exception))

    def test_probe_config_reports_a_string_entry_instead_of_raising(self):
        # A hand-edited config can hold a string where an object belongs. This
        # used to be "AttributeError: 'str' object has no attribute 'get'",
        # which describes no entry at all -- including the good one.
        import verify
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({
                "mcpServers": {
                    "stringy": "launch-data-noodler",
                    "good": {
                        "command": sys.executable,
                        "args": [SERVER],
                        "env": {"DATA_NOODLER_CONFIG": _write_config()},
                    },
                }
            }, f)

        results = verify.probe_config(path)

        self.assertFalse(results["stringy"]["ok"])
        self.assertIn("str", results["stringy"]["error"])
        self.assertIn("not an object", results["stringy"]["error"])
        self.assertTrue(results["good"]["ok"], results["good"]["error"])

    def test_probe_error_includes_real_cause_for_non_json_stdout(self):
        import verify

        generic = ("ExceptionGroup: unhandled errors in a TaskGroup "
                   "(1 sub-exception)")
        result = verify.probe("/bin/sh", ["-c", "echo not-json"],
                              timeout=15.0)

        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])
        self.assertNotEqual(result["error"], generic)
        self.assertGreater(len(result["error"]), len(generic))


EXPECTED_TOOLS_V2 = {
    "lookup_property", "credential_status", "refresh_property_snapshot",
    "reporting_guide", "start_session", "export_report",
    "gsc_list_sites", "gsc_inspect_urls", "gsc_search_analytics",
    "gsc_list_sitemaps", "check_compatibility", "property_setup",
    "export_cohort_report", "export_realtime_report", "export_funnel_report",
}


class TestExpandedSurface(unittest.TestCase):
    def test_server_advertises_all_nine_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env["DATA_NOODLER_CONFIG"] = _write_config()

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[SERVER], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return {t.name for t in tools.tools}

        self.assertEqual(asyncio.run(run()), EXPECTED_TOOLS_V2)

    def test_ga_reporting_guide_is_gone_replaced_by_reporting_guide(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env["DATA_NOODLER_CONFIG"] = _write_config()

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[SERVER], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return {t.name for t in tools.tools}

        names = asyncio.run(run())
        self.assertNotIn("ga_reporting_guide", names)

    def test_start_session_creates_a_folder_and_returns_its_path(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        root = tempfile.mkdtemp()
        env = dict(os.environ)
        # start_session takes a place, not a path (#156): approve root as
        # the sessions folder, and ask for it explicitly -- the test runner's
        # own folder would otherwise qualify as the project.
        env["DATA_NOODLER_CONFIG"] = _write_config(sessions_root=root)

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[SERVER], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "start_session", {"name": "smoke", "save_to": "sessions"})
                    return "".join(c.text for c in result.content
                                   if hasattr(c, "text"))

        out = asyncio.run(run())
        self.assertIn(os.path.realpath(root), os.path.realpath(
            out.split("\n")[1].strip()))
        self.assertTrue(any(n.endswith("-smoke")
                            for n in os.listdir(root)), os.listdir(root))


class TestRequireContracts(unittest.TestCase):
    """"Installed" has to be an exit code, not a sentence.

    Without --require, success is "verify.py printed some OK lines" -- and a
    model reading prose output can rationalise a partial result into a
    success. An agent that has just been asked to install something is the
    least impartial reader of its own output that exists.

    With it, the definition of done is a number the agent did not choose and
    cannot argue with: both servers, the right tool counts, exit 0.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "data-noodler", "installer"))
        import verify
        self.verify = verify

    def test_a_requirement_is_parsed_into_a_name_and_a_count(self):
        self.assertEqual(self.verify.parse_requirements(["data-noodler=9"]),
                         {"data-noodler": 9})

    def test_several_requirements_accumulate(self):
        got = self.verify.parse_requirements(["analytics-mcp=9", "data-noodler=9"])
        self.assertEqual(got, {"analytics-mcp": 9, "data-noodler": 9})

    def test_a_malformed_requirement_is_refused_with_the_expected_form(self):
        for bad in ("data-noodler", "data-noodler=", "=9", "data-noodler=many"):
            with self.assertRaises(self.verify.VerifyError, msg=bad) as caught:
                self.verify.parse_requirements([bad])
            self.assertIn("name=count", str(caught.exception))

    def test_meeting_every_requirement_reports_no_failures(self):
        results = {"data-noodler": {"ok": True, "tools": [f"t{i}" for i in range(9)]}}
        problems = self.verify.unmet_requirements(results, {"data-noodler": 9})
        self.assertEqual(problems, [])

    def test_a_server_that_is_required_but_absent_is_a_failure(self):
        problems = self.verify.unmet_requirements({}, {"data-noodler": 9})
        self.assertEqual(len(problems), 1)
        self.assertIn("data-noodler", problems[0])
        self.assertIn("not", problems[0].lower())

    def test_too_few_tools_is_a_failure_even_though_the_server_started(self):
        # The case this exists for. The server connects, the handshake
        # succeeds, and half the surface is missing -- which reads as success
        # in every check that stops at "did it start".
        results = {"data-noodler": {"ok": True, "tools": ["a", "b"]}}
        problems = self.verify.unmet_requirements(results, {"data-noodler": 9})
        self.assertEqual(len(problems), 1)
        self.assertIn("2", problems[0])
        self.assertIn("9", problems[0])

    def test_a_server_that_failed_to_start_is_reported_once_not_twice(self):
        results = {"data-noodler": {"ok": False, "error": "boom", "tools": []}}
        problems = self.verify.unmet_requirements(results, {"data-noodler": 9})
        self.assertEqual(len(problems), 1)

    def test_extra_servers_beyond_the_requirements_are_not_failures(self):
        results = {"data-noodler": {"ok": True, "tools": ["x"] * 9},
                   "something-else": {"ok": True, "tools": ["y"]}}
        self.assertEqual(
            self.verify.unmet_requirements(results, {"data-noodler": 9}), [])


class TestRequireSkill(unittest.TestCase):
    """Issue #5: verify passed with the Claude Code skill missing.

    An install skipped INSTALL.md's step 6, "Install the skills for Claude
    Code". verify.py --require analytics-mcp=9 --require data-noodler=9 exited
    0, because it only counts MCP tools. Claude Code then had the tools all day
    but not the skill that says which tool to use -- which fed straight into
    the truncated-report near miss in #1.

    A skipped step should be a failed check, not something to remember.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "data-noodler", "installer"))
        import verify
        self.verify = verify
        self.skills = tempfile.mkdtemp()

    def _install(self, name, body="---\nname: {name}\ndescription: x\n---\n# x\n"):
        d = os.path.join(self.skills, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(body.format(name=name))

    def test_a_missing_skill_is_reported_with_where_it_was_expected(self):
        problems = self.verify.missing_skills(["data-noodler"], self.skills)
        self.assertEqual(len(problems), 1)
        self.assertIn("data-noodler", problems[0])
        self.assertIn(self.skills, problems[0],
                      "say where it was looked for, or the reader cannot tell "
                      "a missing skill from a wrong skills directory")

    def test_an_installed_skill_passes(self):
        self._install("data-noodler")
        self.assertEqual(
            self.verify.missing_skills(["data-noodler"], self.skills), [])

    def test_an_empty_skill_file_is_not_an_installed_skill(self):
        self._install("data-noodler", body="")
        self.assertEqual(
            len(self.verify.missing_skills(["data-noodler"], self.skills)), 1)

    def test_a_skill_whose_frontmatter_names_something_else_fails(self):
        # A directory named right holding the wrong skill would otherwise pass.
        self._install("data-noodler",
                      body="---\nname: something-else\n---\n# x\n")
        problems = self.verify.missing_skills(["data-noodler"], self.skills)
        self.assertEqual(len(problems), 1)
        self.assertIn("something-else", problems[0])

    def test_no_skills_requested_means_no_problems(self):
        self.assertEqual(self.verify.missing_skills([], self.skills), [])
