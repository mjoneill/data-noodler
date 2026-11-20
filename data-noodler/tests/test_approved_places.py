"""Exports go only to places the user approved (#156, 2026-10-25).

Before this, an absolute out_file went anywhere the user could write. Tool
arguments come from a model that GA and Search Console text can steer, so a
page title could have it overwrite the user's own CSVs or write into any git
tree; on Windows, merely resolving \\\\host\\share leaks the NTLM hash.

Now there are three kinds of place: the project folder (named by the APP --
its declared roots, else the folder it started the server in), the sessions
folder from config.json, and extra folders listed in config.json. The model
picks among them; it cannot invent one.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(ROOT, "companion")
SERVER = os.path.join(COMPANION, "ga_companion.py")
sys.path.insert(0, COMPANION)

import sessions  # noqa: E402

try:
    import mcp.server.mcpserver  # noqa: F401
    MCP2 = True
except ImportError:
    MCP2 = False


class TestNetworkAndDevicePathsAreRefusedOnTextAlone(unittest.TestCase):

    BAD = (r"\\evil.example\share\x.csv", "//evil.example/share/x.csv",
           r"\\?\C:\x.csv", r"\\.\pipe\x", r"\\evil@SSL\DavWWWRoot\x.csv",
           "C:x.csv", "a\x00b.csv")
    FINE = ("report.csv", "raw/report.csv", r"C:\Users\a\x.csv",
            "/Users/a/x.csv")

    def test_each_bad_form_is_refused(self):
        for text in self.BAD:
            self.assertIsNotNone(sessions.unsafe_path_reason(text), text)

    def test_ordinary_paths_pass_the_text_check(self):
        for text in self.FINE:
            self.assertIsNone(sessions.unsafe_path_reason(text), text)

    def test_a_unc_path_never_reaches_the_filesystem(self):
        # The check itself would be the leak on Windows.
        places = {"sessions": tempfile.mkdtemp()}
        boom = mock.Mock(side_effect=AssertionError("filesystem touched"))
        for arg in ("out_file", "session_dir"):
            kwargs = {"out_file": None, "session_dir": None}
            kwargs[arg] = r"\\evil.example\share\x.csv"
            with mock.patch.object(sessions.os.path, "realpath", boom), \
                    mock.patch.object(sessions.os.path, "isdir", boom), \
                    mock.patch.object(sessions.os.path, "islink", boom):
                with self.assertRaises(sessions.SessionError) as ctx:
                    sessions.resolve(kwargs["out_file"], kwargs["session_dir"],
                                     "g.csv", places)
            self.assertIn("network", str(ctx.exception))


class TestWhatCountsAsAProject(unittest.TestCase):

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.project = os.path.join(self.home, "work", "site-audit")
        os.makedirs(self.project)

    def _why(self, path):
        return sessions.project_reason(path, home=self.home)

    def test_an_ordinary_folder_under_home_is_a_project(self):
        self.assertIsNone(self._why(self.project))

    def test_the_root_and_the_home_folder_are_not(self):
        self.assertIsNotNone(self._why("/"))
        self.assertIsNotNone(self._why(self.home))
        self.assertIsNotNone(self._why(os.path.dirname(self.home)))

    def test_settings_and_app_folders_are_not(self):
        for name in ("Library", ".config", ".codex", ".claude", ".ssh"):
            d = os.path.join(self.home, name, "x")
            os.makedirs(d)
            self.assertIsNotNone(self._why(d), name)

    def test_a_missing_folder_is_not(self):
        self.assertIsNotNone(self._why(os.path.join(self.home, "nope")))

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX system folders")
    def test_system_folders_outside_home_are_not(self):
        for d in ("/usr", "/etc", "/private", "/System"):
            if os.path.isdir(d):
                self.assertIsNotNone(self._why(d), d)

    def test_declared_roots_win_over_the_launch_folder(self):
        other = os.path.join(self.home, "other")
        os.makedirs(other)
        got, how = sessions.find_project([self.project], other, home=self.home)
        self.assertEqual(got, os.path.realpath(self.project))
        self.assertIn("declared", how)

    def test_an_unusable_root_falls_through_to_the_launch_folder(self):
        got, how = sessions.find_project(["/"], self.project, home=self.home)
        self.assertEqual(got, os.path.realpath(self.project))
        self.assertIn("started", how)

    def test_desktop_chat_started_in_root_has_no_project(self):
        got, why = sessions.find_project([], "/", home=self.home)
        self.assertIsNone(got)
        self.assertIn("/", why)


class TestResolveInsideApprovedPlaces(unittest.TestCase):

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.project = os.path.join(self.home, "proj")
        self.sessions_root = os.path.join(self.home, "Documents", "sessions")
        self.shared = os.path.join(self.home, "shared")
        for d in (self.project, self.sessions_root, self.shared):
            os.makedirs(d)
        self.places = sessions.build_places(
            sessions_root=self.sessions_root, project=self.project,
            extra={"shared": self.shared, "bad": r"\\evil\s"})

    def test_the_project_comes_first_and_is_the_default(self):
        self.assertEqual(list(self.places)[0], "project")
        path, where = sessions.resolve("r.csv", None, "g.csv", self.places)
        self.assertEqual(path, os.path.join(self.project, "_outputs", "r.csv"))
        self.assertEqual(where["place"], "project")

    def test_save_to_picks_another_approved_place(self):
        path, where = sessions.resolve("r.csv", None, "g.csv", self.places,
                                       save_to="sessions")
        self.assertEqual(path, os.path.join(self.sessions_root, "r.csv"))
        path, _ = sessions.resolve("r.csv", None, "g.csv", self.places,
                                   save_to="shared")
        self.assertEqual(path, os.path.join(self.shared, "r.csv"))

    def test_a_network_share_in_config_is_not_approved(self):
        self.assertNotIn("bad", self.places)

    def test_an_unknown_place_is_refused_and_the_real_ones_named(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.resolve("r.csv", None, "g.csv", self.places,
                             save_to="/etc")
        self.assertIn("project", str(ctx.exception))
        self.assertIn("sessions", str(ctx.exception))

    def test_without_a_project_the_default_is_the_sessions_folder(self):
        places = sessions.build_places(sessions_root=self.sessions_root)
        path, where = sessions.resolve("r.csv", None, "g.csv", places)
        self.assertEqual(where["place"], "sessions")
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.resolve("r.csv", None, "g.csv", places, save_to="project")
        self.assertIn("no project folder", str(ctx.exception))

    def test_a_session_dir_outside_every_place_is_refused(self):
        with self.assertRaises(sessions.SessionError):
            sessions.resolve(None, tempfile.mkdtemp(), "g.csv", self.places)

    def test_a_session_dir_must_match_save_to(self):
        sd = os.path.join(self.sessions_root, "2026-10-25-x")
        os.makedirs(sd)
        with self.assertRaises(sessions.SessionError):
            sessions.resolve(None, sd, "g.csv", self.places, save_to="project")
        path, where = sessions.resolve(None, sd, "g.csv", self.places)
        self.assertEqual(path, os.path.join(sd, "g.csv"))
        self.assertEqual(where["place"], "sessions")

    def test_relative_escapes_are_refused(self):
        for sneaky in ("../x.csv", "a/../../x.csv"):
            with self.assertRaises(sessions.SessionError, msg=sneaky):
                sessions.resolve(sneaky, None, "g.csv", self.places)

    def test_an_absolute_path_is_accepted_only_inside_a_place(self):
        inside = os.path.join(self.shared, "x.csv")
        self.assertEqual(sessions.resolve(inside, None, "g.csv",
                                          self.places)[0], inside)
        with self.assertRaises(sessions.SessionError):
            sessions.resolve(os.path.join(self.home, "Documents", "budget.csv"),
                             None, "g.csv", self.places)


@unittest.skipUnless(MCP2, "the shipped server targets mcp 2.x")
class TestTheToolsSayWhereTheyWrote(unittest.TestCase):

    def setUp(self):
        import ga_companion
        self.mod = ga_companion
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.project = os.path.join(self.home, "proj")
        os.makedirs(os.path.join(self.project, "_outputs"))
        places = sessions.build_places(
            sessions_root=os.path.join(self.home, "s"), project=self.project)
        p = mock.patch.object(ga_companion, "_places", return_value=(
            places, "the folder the app started this server in"))
        p.start()
        self.addCleanup(p.stop)

    def test_the_receipt_records_place_and_reason(self):
        path, where = self.mod._destination("r.csv", "", "g.csv", "")
        self.assertEqual(where["place"], "project")
        self.assertIn("started", where["chosen_by"])
        self.assertNotIn("warning", where)  # not a git repo

    def _git(self, *args):
        subprocess.run(["git", "-C", self.project, *args], check=True,
                       capture_output=True)

    def test_a_git_project_without_the_ignore_rule_gets_a_warning(self):
        self._git("init", "-q")
        _, where = self.mod._destination("r.csv", "", "g.csv", "")
        self.assertIn(".gitignore", where.get("warning", ""))

    def test_a_git_project_that_ignores_outputs_gets_none(self):
        self._git("init", "-q")
        with open(os.path.join(self.project, ".gitignore"), "w") as f:
            f.write("_outputs/\n")
        _, where = self.mod._destination("r.csv", "", "g.csv", "")
        self.assertNotIn("warning", where)

    def test_no_tool_takes_a_root_path_any_more(self):
        import inspect
        params = inspect.signature(self.mod.start_session).parameters
        self.assertNotIn("root", params)
        self.assertIn("save_to", params)


@unittest.skipUnless(MCP2, "the shipped server targets mcp 2.x")
class TestStartSessionUsesTheRootsTheClientDeclares(unittest.TestCase):
    """End to end over stdio: the client declares a root, as Claude Code
    does, and the session folder lands in <that root>/_outputs."""

    def test_a_declared_root_becomes_the_project(self):
        from mcp import ClientSession, StdioServerParameters, types
        from mcp.client.stdio import stdio_client

        home = os.path.realpath(tempfile.mkdtemp())
        project = os.path.join(home, "site-audit")
        os.makedirs(project)
        cfg = os.path.join(home, "config.json")
        with open(cfg, "w") as f:
            json.dump({"oauth_client_file": "/x", "adc_file": "/x",
                       "venv_python": sys.executable,
                       "properties_csv": "/x",
                       "sessions_root": os.path.join(home, "s")}, f)
        env = dict(os.environ, GA_MCP_CONFIG=cfg, HOME=home)

        async def roots(context):
            return types.ListRootsResult(roots=[types.Root(
                uri="file://" + project)])

        async def run():
            params = StdioServerParameters(command=sys.executable,
                                           args=[SERVER], env=env, cwd="/")
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w,
                                         list_roots_callback=roots) as s:
                    await s.initialize()
                    res = await s.call_tool("start_session", {"name": "smoke"})
                    return "".join(getattr(c, "text", "") for c in res.content)

        out = asyncio.run(run())
        self.assertIn(os.path.join(project, "_outputs"), out)
        self.assertIn("declared", out)
        made = os.listdir(os.path.join(project, "_outputs"))
        self.assertTrue(any(n.endswith("-smoke") for n in made), made)


if __name__ == "__main__":
    unittest.main()
