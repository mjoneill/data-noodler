"""Where files may be written, and where directories may be created.

The symlink rule is not hypothetical: on 2026-09-02 an agent wrote through a
scratch-directory symlink and truncated Homebrew's python3.14, breaking every
MCP server on the machine until a reinstall.
"""

import datetime
import ntpath
import posixpath
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "companion"))

import sessions

FIXED = datetime.datetime(2026, 9, 3, 14, 30, 0)


class TestStartSession(unittest.TestCase):
    def test_creates_a_dated_folder_under_the_given_root(self):
        root = tempfile.mkdtemp()
        path = sessions.start_session("law-pillar", root=root, now=FIXED)
        self.assertEqual(path, os.path.join(root, "2026-09-03-law-pillar"))
        self.assertTrue(os.path.isdir(path))

    def test_returns_an_absolute_path(self):
        root = tempfile.mkdtemp()
        self.assertTrue(os.path.isabs(
            sessions.start_session("x", root=root, now=FIXED)))

    def test_refuses_when_the_root_does_not_exist(self):
        missing = os.path.join(tempfile.mkdtemp(), "nope")
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.start_session("x", root=missing, now=FIXED)
        self.assertIn(missing, str(ctx.exception))

    def test_creates_only_one_level(self):
        # The root must exist; the tool must not build a whole tree.
        root = tempfile.mkdtemp()
        deep = os.path.join(root, "a", "b", "c")
        with self.assertRaises(sessions.SessionError):
            sessions.start_session("x", root=deep, now=FIXED)

    def test_reuses_an_existing_folder_of_the_same_name(self):
        root = tempfile.mkdtemp()
        a = sessions.start_session("dup", root=root, now=FIXED)
        b = sessions.start_session("dup", root=root, now=FIXED)
        self.assertEqual(a, b)

    def test_slugifies_a_messy_name(self):
        root = tempfile.mkdtemp()
        path = sessions.start_session("Law Pillar / Review!", root=root,
                                      now=FIXED)
        self.assertEqual(os.path.basename(path), "2026-09-03-law-pillar-review")

    def test_rejects_a_name_that_slugifies_to_nothing(self):
        root = tempfile.mkdtemp()
        with self.assertRaises(sessions.SessionError):
            sessions.start_session("///", root=root, now=FIXED)

    def test_refuses_a_denylisted_sessions_root(self):
        # Without this, start_session creates the folder and reports it ready,
        # and then check_writable refuses every single export into it -- an
        # announced destination nothing can be written to. Refuse while the
        # user can still choose somewhere else.
        for bad in ("~/.claude", "~/.ssh", "~/.config/ga-mcp"):
            with self.subTest(root=bad):
                with self.assertRaises(sessions.SessionError) as ctx:
                    sessions.start_session("x", root=bad, now=FIXED)
                self.assertIn("protected", str(ctx.exception).lower())

    def test_refuses_a_root_nested_inside_a_denylisted_location(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.start_session("x", root="~/.claude/skills", now=FIXED)
        self.assertIn("protected", str(ctx.exception).lower())

    def test_refuses_a_denylisted_root_before_creating_anything(self):
        root = os.path.expanduser("~/.claude")
        before = set(os.listdir(root)) if os.path.isdir(root) else set()
        with self.assertRaises(sessions.SessionError):
            sessions.start_session("law-pillar", root=root, now=FIXED)
        after = set(os.listdir(root)) if os.path.isdir(root) else set()
        self.assertEqual(before, after)

    def test_refuses_a_symlinked_sessions_root(self):
        outer = tempfile.mkdtemp()
        real_root = os.path.join(outer, "realroot")
        os.makedirs(real_root)
        link_root = os.path.join(outer, "linkroot")
        os.symlink(real_root, link_root)
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.start_session("x", root=link_root, now=FIXED)
        self.assertIn("symlink", str(ctx.exception).lower())


class TestCheckWritable(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_accepts_a_new_csv_in_an_existing_directory(self):
        sessions.check_writable(os.path.join(self.d, "out.csv"))

    def test_accepts_an_ordinary_tempdir_destination(self):
        # Regression guard for the /var -> /private/var problem: self.d
        # comes from tempfile.mkdtemp() and, on macOS, sits under a system
        # symlink (/var). It must still be accepted -- only a symlink a
        # caller controls should be refused, not the OS's own plumbing.
        sessions.check_writable(os.path.join(self.d, "ordinary.csv"))

    def test_rejects_a_relative_path(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable("out.csv")
        self.assertIn("absolute", str(ctx.exception).lower())

    def test_rejects_a_non_csv_extension(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(os.path.join(self.d, "out.txt"))
        self.assertIn(".csv", str(ctx.exception))

    def test_rejects_a_missing_parent_directory(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(os.path.join(self.d, "sub", "out.csv"))
        self.assertIn("does not exist", str(ctx.exception))

    def test_rejects_an_existing_file_without_overwrite(self):
        p = os.path.join(self.d, "out.csv")
        open(p, "w").close()
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(p)
        self.assertIn("overwrite", str(ctx.exception))

    def test_allows_an_existing_file_with_overwrite(self):
        p = os.path.join(self.d, "out.csv")
        open(p, "w").close()
        sessions.check_writable(p, overwrite=True)

    def test_rejects_a_symlinked_target(self):
        real = os.path.join(self.d, "real.csv")
        open(real, "w").close()
        link = os.path.join(self.d, "link.csv")
        os.symlink(real, link)
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(link, overwrite=True)
        self.assertIn("symlink", str(ctx.exception).lower())

    def test_rejects_a_symlinked_parent_directory(self):
        real_dir = os.path.join(self.d, "realdir")
        os.makedirs(real_dir)
        link_dir = os.path.join(self.d, "linkdir")
        os.symlink(real_dir, link_dir)
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(os.path.join(link_dir, "out.csv"))
        self.assertIn("symlink", str(ctx.exception).lower())

    def test_rejects_denylisted_locations(self):
        for bad in ("~/.ssh/out.csv",
                    "~/.config/gcloud/out.csv",
                    "~/.claude/out.csv",
                    "~/.codex/out.csv",
                    "~/.config/ga-mcp/out.csv"):
            with self.subTest(path=bad):
                with self.assertRaises(sessions.SessionError) as ctx:
                    sessions.check_writable(os.path.expanduser(bad))
                self.assertIn("protected", str(ctx.exception).lower())

    def test_rejects_denylisted_locations_regardless_of_case(self):
        # APFS is case-insensitive but case-preserving: realpath() does not
        # normalise the case of a non-symlink component, so ~/.Claude and
        # ~/.claude resolve to the same directory on disk. The denylist
        # check must fold case rather than compare the raw string.
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(os.path.expanduser("~/.Claude/pwned.csv"))
        self.assertIn("protected", str(ctx.exception).lower())

    def test_rejects_a_symlinked_grandparent_directory(self):
        real_dir = os.path.join(self.d, "realdir")
        os.makedirs(real_dir)
        link_dir = os.path.join(self.d, "linkdir")
        os.symlink(real_dir, link_dir)
        subdir = os.path.join(link_dir, "subdir")
        os.makedirs(subdir)
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.check_writable(os.path.join(subdir, "out.csv"))
        msg = str(ctx.exception)
        self.assertIn("symlink", msg.lower())
        self.assertIn(link_dir, msg)


class TestResolveDestination(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_explicit_out_file_wins(self):
        want = os.path.join(self.d, "mine.csv")
        self.assertEqual(
            sessions.resolve_destination(want, None, "generated.csv",
                                         sessions_root=self.d), want)

    def test_session_dir_gets_the_suggested_name(self):
        got = sessions.resolve_destination(None, self.d, "generated.csv",
                                               sessions_root=self.d)
        self.assertEqual(got, os.path.join(self.d, "generated.csv"))

    def test_a_collision_suffixes_rather_than_overwrites(self):
        open(os.path.join(self.d, "generated.csv"), "w").close()
        got = sessions.resolve_destination(None, self.d, "generated.csv",
                                               sessions_root=self.d)
        self.assertEqual(os.path.basename(got), "generated-2.csv")

    def test_a_second_collision_increments_again(self):
        open(os.path.join(self.d, "g.csv"), "w").close()
        open(os.path.join(self.d, "g-2.csv"), "w").close()
        got = sessions.resolve_destination(None, self.d, "g.csv",
                                               sessions_root=self.d)
        self.assertEqual(os.path.basename(got), "g-3.csv")

    def test_neither_is_an_error_naming_both_ways_out(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.resolve_destination(None, None, "generated.csv")
        msg = str(ctx.exception)
        self.assertIn("start_session", msg)
        self.assertIn("out_file", msg)


class TestDenylistCoversWindowsToo(unittest.TestCase):
    """%APPDATA% is not derivable from "~", so it was not protected at all.

    This module exists because on 2026-09-02 an export redirected through a
    symlink truncated Homebrew's python3.14. The denylist is the other half of
    that lesson -- and on Windows it named nothing that mattered, because
    Claude Desktop's data lives under %APPDATA% and every entry was
    home-relative.
    """

    APPDATA = r"C:\Users\example\AppData\Roaming"
    LOCAL = r"C:\Users\example\AppData\Local"

    def test_claude_desktop_data_is_denied_on_windows(self):
        got = sessions.build_denylist(env={"APPDATA": self.APPDATA})
        self.assertIn(os.path.join(self.APPDATA, "Claude"), got)

    def test_the_vestigial_variant_is_denied_as_well(self):
        got = sessions.build_denylist(env={"APPDATA": self.APPDATA})
        self.assertIn(os.path.join(self.APPDATA, "Claude-3p"), got)

    def test_local_appdata_is_covered_when_present(self):
        got = sessions.build_denylist(env={"LOCALAPPDATA": self.LOCAL})
        self.assertIn(os.path.join(self.LOCAL, "Claude"), got)

    def test_home_relative_entries_survive_on_every_platform(self):
        # ~/.claude is where Claude Code keeps state on Windows too, so these
        # must not be traded away for the %APPDATA% ones.
        got = sessions.build_denylist(env={})
        self.assertIn(os.path.expanduser("~/.claude"), got)
        self.assertIn(os.path.expanduser("~/.ssh"), got)
        self.assertIn(os.path.expanduser("~/.config/ga-mcp"), got)

    def test_an_absent_appdata_is_not_an_error(self):
        # A scrubbed environment must not produce a denylist entry of "Claude"
        # relative to nothing, which would deny far too much.
        got = sessions.build_denylist(env={})
        self.assertNotIn("Claude", got)
        self.assertTrue(all(os.path.isabs(p) for p in got))


class TestRelativeOutFileLandsUnderTheSessionsRoot(unittest.TestCase):
    """Issue #2: a relative out_file landed relative to the server's cwd.

    os.path.abspath resolves against the server PROCESS's working directory.
    Measured on a running ga-companion with lsof: it was the Claude Code
    session's project folder, a git working tree. The same relative path would
    have landed somewhere else entirely when launched from Desktop or Codex.

    The risk is analytics data committed into an unrelated repository -- the
    exact thing the "this project builds tooling, it does not use it" rule is
    about. Where an export lands must not depend on which app launched the
    server, and must never default into a project folder.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.elsewhere = tempfile.mkdtemp()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _resolve(self, out_file):
        return sessions.resolve_destination(out_file, None, "generated.csv",
                                            sessions_root=self.root)

    def test_a_bare_filename_lands_under_the_sessions_root(self):
        self.assertEqual(self._resolve("report.csv"),
                         os.path.join(self.root, "report.csv"))

    def test_the_result_does_not_depend_on_the_working_directory(self):
        # The heart of the report: the same call from a different launcher.
        os.chdir(self.elsewhere)
        got = self._resolve("report.csv")
        self.assertTrue(got.startswith(self.root), got)
        self.assertFalse(got.startswith(os.path.realpath(self.elsewhere)), got)

    def test_a_relative_subpath_stays_under_the_root(self):
        self.assertEqual(self._resolve(os.path.join("audit", "r.csv")),
                         os.path.join(self.root, "audit", "r.csv"))

    def test_an_escape_with_dotdot_is_refused(self):
        for sneaky in ("../escaped.csv", "a/../../escaped.csv"):
            with self.assertRaises(sessions.SessionError, msg=sneaky) as ctx:
                self._resolve(sneaky)
            self.assertIn("outside", str(ctx.exception).lower())

    def test_the_root_itself_is_not_a_file_destination(self):
        with self.assertRaises(sessions.SessionError):
            self._resolve(".")

    def test_an_absolute_path_outside_every_approved_place_is_refused(self):
        # Was "honoured as given" until 2026-10-25 (#156): a model steered by
        # text inside GA data could overwrite any CSV the user owned.
        with self.assertRaises(sessions.SessionError) as ctx:
            self._resolve(os.path.join(self.elsewhere, "mine.csv"))
        self.assertIn("approved", str(ctx.exception))

    def test_an_absolute_path_inside_the_root_is_fine(self):
        want = os.path.join(self.root, "mine.csv")
        self.assertEqual(self._resolve(want), want)

    def test_a_home_relative_path_outside_the_root_is_refused(self):
        with self.assertRaises(sessions.SessionError):
            self._resolve("~/x.csv")

    def test_no_destination_offers_the_bare_filename_way_out(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            sessions.resolve_destination(None, None, "g.csv",
                                         sessions_root=self.root)
        msg = str(ctx.exception)
        self.assertIn("start_session", msg)
        self.assertIn(self.root, msg)


class TestARelativeOutFileBelongsToTheSessionItNames(unittest.TestCase):
    """out_file="x.csv" plus session_dir must land in that session (#143).

    Seen live on Windows, 2026-10-09: the export went to the sessions root,
    not the dated session folder the call also named, because a relative
    out_file was resolved against the root before session_dir was read. The
    caller had said which session; ignoring it scatters one analysis across
    two folders.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session = os.path.join(self.root, "2026-10-09-audit")
        os.makedirs(self.session)

    def _resolve(self, out_file, session_dir="default"):
        session_dir = self.session if session_dir == "default" else session_dir
        return sessions.resolve_destination(out_file, session_dir,
                                            "generated.csv",
                                            sessions_root=self.root)

    def test_a_bare_filename_lands_in_the_named_session(self):
        self.assertEqual(self._resolve("report.csv"),
                         os.path.join(self.session, "report.csv"))

    def test_a_relative_subpath_lands_under_the_session(self):
        self.assertEqual(self._resolve(os.path.join("raw", "r.csv")),
                         os.path.join(self.session, "raw", "r.csv"))

    def test_an_escape_above_the_session_is_refused(self):
        with self.assertRaises(sessions.SessionError) as ctx:
            self._resolve("../sibling.csv")
        self.assertIn("outside", str(ctx.exception).lower())

    def test_without_a_session_a_bare_filename_still_uses_the_root(self):
        self.assertEqual(self._resolve("report.csv", session_dir=None),
                         os.path.join(self.root, "report.csv"))

    def test_an_absolute_out_file_inside_the_root_wins_over_the_session(self):
        want = os.path.join(self.root, "elsewhere.csv")
        self.assertEqual(self._resolve(want), want)

    def test_an_absolute_out_file_outside_the_root_is_refused(self):
        with self.assertRaises(sessions.SessionError):
            self._resolve(os.path.join(tempfile.mkdtemp(), "mine.csv"))

    def test_an_explicit_name_is_used_exactly_not_numbered(self):
        # Overwrite protection belongs to the caller's overwrite flag, as it
        # does for the root; only generated names get -2, -3 suffixes.
        open(os.path.join(self.session, "report.csv"), "w").close()
        self.assertEqual(self._resolve("report.csv"),
                         os.path.join(self.session, "report.csv"))


class TestTheDenylistMatchesRealWindowsPaths(unittest.TestCase):
    """#158: on Windows the home-relative entries matched nothing.

    expanduser("~/.ssh") there is C:\\Users\\x/.ssh, mixed separators, while
    realpath() of a destination is all backslashes -- so an export could be
    written into ~/.ssh, ~/.claude or the credential's own folder. The old
    tests only checked the entries were listed, never that they matched.
    """

    HOME = r"C:\Users\ali"
    ENV = {"APPDATA": r"C:\Users\ali\AppData\Roaming",
           "LOCALAPPDATA": r"C:\Users\ali\AppData\Local"}

    def setUp(self):
        self.deny = sessions.build_denylist(env=self.ENV, pathmod=ntpath,
                                            home=self.HOME)

    def _match(self, path):
        return sessions.denylist_match(path, self.deny, pathmod=ntpath)

    def test_entries_use_one_separator(self):
        for entry in self.deny:
            self.assertNotIn("/", entry, entry)

    def test_home_relative_entries_match_real_windows_paths(self):
        for inside in (r"C:\Users\ali\.ssh\x.csv",
                       r"C:\Users\ali\.claude\projects\x.csv",
                       r"C:\Users\ali\.config\gcloud\adc.csv",
                       r"C:\Users\ali\.config\ga-mcp\properties.csv",
                       r"C:\Users\ali\.codex\x.csv"):
            self.assertIsNotNone(self._match(inside), inside)

    def test_matching_ignores_case_as_windows_does(self):
        self.assertIsNotNone(self._match(r"c:\users\ALI\.SSH\x.csv"))

    def test_appdata_entries_still_match(self):
        self.assertIsNotNone(self._match(
            r"C:\Users\ali\AppData\Roaming\Claude\claude_desktop_config.csv"))

    def test_ordinary_folders_are_not_caught(self):
        for fine in (r"C:\Users\ali\Documents\analyst-sessions\r.csv",
                     r"C:\Users\ali\.sshkeys-notes\r.csv",
                     r"C:\Users\ali\.config\other\r.csv"):
            self.assertIsNone(self._match(fine), fine)

    def test_posix_matching_is_unchanged(self):
        deny = sessions.build_denylist(env={}, pathmod=posixpath,
                                       home="/Users/x")
        self.assertIsNotNone(sessions.denylist_match(
            "/Users/x/.claude/a.csv", deny, pathmod=posixpath))
        self.assertIsNone(sessions.denylist_match(
            "/Users/x/.claudette/a.csv", deny, pathmod=posixpath))
