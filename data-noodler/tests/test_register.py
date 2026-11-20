"""Registration must be non-destructive, idempotent, and verifiable.

These configs hold live state the user cares about -- preferences, project
trust levels, unrelated server entries. A registration that clobbers any of it
is a worse outcome than one that fails, so survival of unrelated keys is the
first thing asserted.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import install
import register

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
GA_HOME = "/Users/example/.config/ga-mcp"
REPO_ROOT = os.path.dirname(ROOT)


class TestServerEntries(unittest.TestCase):
    def test_both_servers_are_defined(self):
        e = register.server_entries(GA_HOME)
        self.assertEqual(set(e), {"analytics-mcp", "ga-companion"})

    def test_entries_point_at_the_launchers_not_the_binaries(self):
        e = register.server_entries(GA_HOME)
        self.assertEqual(e["analytics-mcp"]["command"],
                         f"{GA_HOME}/bin/launch-ga-mcp")
        self.assertEqual(e["ga-companion"]["command"],
                         f"{GA_HOME}/bin/launch-ga-companion")

    def test_entries_declare_stdio_transport(self):
        for entry in register.server_entries(GA_HOME).values():
            self.assertEqual(entry["type"], "stdio")


class TestRegisterJson(unittest.TestCase):
    def _copy(self, fixture):
        d = tempfile.mkdtemp()
        dest = os.path.join(d, "config.json")
        shutil.copy(os.path.join(FIXTURES, fixture), dest)
        return dest

    def test_adds_both_servers_to_a_config_with_no_mcpservers_key(self):
        path = self._copy("claude_desktop_config.json")
        result = register.register_json(path, register.server_entries(GA_HOME))
        self.assertTrue(result["changed"])
        self.assertEqual(sorted(result["added"]),
                         ["analytics-mcp", "ga-companion"])
        data = json.load(open(path))
        self.assertEqual(set(data["mcpServers"]),
                         {"analytics-mcp", "ga-companion"})

    def test_preserves_every_unrelated_key(self):
        path = self._copy("claude_desktop_config.json")
        before = json.load(open(path))
        register.register_json(path, register.server_entries(GA_HOME))
        after = json.load(open(path))
        self.assertEqual(before["coworkUserFilesPath"],
                         after["coworkUserFilesPath"])
        self.assertEqual(before["preferences"], after["preferences"])

    def test_preserves_unrelated_mcp_servers(self):
        path = self._copy("claude_json.json")
        register.register_json(path, {"ga-companion":
                                      register.server_entries(GA_HOME)["ga-companion"]})
        data = json.load(open(path))
        self.assertIn("someUnrelatedKey", data)
        self.assertIn("analytics-mcp", data["mcpServers"])
        self.assertIn("ga-companion", data["mcpServers"])

    def test_second_run_is_a_no_op(self):
        path = self._copy("claude_desktop_config.json")
        entries = register.server_entries(GA_HOME)
        register.register_json(path, entries)
        first = open(path).read()
        result = register.register_json(path, entries)
        self.assertFalse(result["changed"])
        self.assertEqual(open(path).read(), first)

    def test_changed_entry_is_reported_as_updated_not_added(self):
        path = self._copy("claude_json.json")
        entries = register.server_entries(GA_HOME)
        result = register.register_json(path, entries)
        self.assertIn("analytics-mcp", result["updated"])
        self.assertIn("ga-companion", result["added"])

    def test_a_backup_is_written_before_any_change(self):
        path = self._copy("claude_desktop_config.json")
        original = open(path).read()
        result = register.register_json(path, register.server_entries(GA_HOME))
        self.assertTrue(os.path.exists(result["backup"]))
        self.assertEqual(open(result["backup"]).read(), original)

    def test_no_backup_is_written_when_nothing_changes(self):
        path = self._copy("claude_desktop_config.json")
        entries = register.server_entries(GA_HOME)
        register.register_json(path, entries)
        result = register.register_json(path, entries)
        self.assertIsNone(result["backup"])

    def test_creates_the_file_when_absent(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "claude_desktop_config.json")
        result = register.register_json(path, register.server_entries(GA_HOME))
        self.assertTrue(result["changed"])
        self.assertEqual(set(json.load(open(path))["mcpServers"]),
                         {"analytics-mcp", "ga-companion"})

    def test_malformed_existing_config_aborts_without_writing(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            f.write("{ not json")
        with self.assertRaises(register.RegisterError):
            register.register_json(path, register.server_entries(GA_HOME))
        self.assertEqual(open(path).read(), "{ not json")

    def test_written_file_is_valid_json_after_registration(self):
        path = self._copy("claude_desktop_config.json")
        register.register_json(path, register.server_entries(GA_HOME))
        json.load(open(path))  # raises if the write corrupted it

    def test_mcpservers_as_a_list_aborts_without_backup_or_write(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        original = json.dumps({"mcpServers": ["not-a-dict"],
                                "otherKey": "value"})
        with open(path, "w") as f:
            f.write(original)
        with self.assertRaises(register.RegisterError) as ctx:
            register.register_json(path, register.server_entries(GA_HOME))
        self.assertIn("mcpServers", str(ctx.exception))
        self.assertIn("list", str(ctx.exception))
        self.assertEqual(open(path).read(), original)
        leftovers = [n for n in os.listdir(d) if n != "config.json"]
        self.assertEqual(leftovers, [],
                          "a malformed config must not leave a stray backup")

    def test_mcpservers_as_a_string_aborts_without_backup_or_write(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        original = json.dumps({"mcpServers": "not-a-dict"})
        with open(path, "w") as f:
            f.write(original)
        with self.assertRaises(register.RegisterError) as ctx:
            register.register_json(path, register.server_entries(GA_HOME))
        self.assertIn("mcpServers", str(ctx.exception))
        self.assertIn("str", str(ctx.exception))
        self.assertEqual(open(path).read(), original)
        leftovers = [n for n in os.listdir(d) if n != "config.json"]
        self.assertEqual(leftovers, [],
                          "a malformed config must not leave a stray backup")

    def test_backup_failure_aborts_without_writing(self):
        path = self._copy("claude_desktop_config.json")
        original = open(path).read()
        with mock.patch("register.shutil.copy2",
                         side_effect=PermissionError("denied")):
            with self.assertRaises(register.RegisterError) as ctx:
                register.register_json(path, register.server_entries(GA_HOME))
        self.assertIn("denied", str(ctx.exception))
        self.assertEqual(open(path).read(), original)
        d = os.path.dirname(path)
        leftovers = [n for n in os.listdir(d) if n != "config.json"]
        self.assertEqual(leftovers, [],
                          "a failed backup must not leave a partial write")

    def test_tmp_write_failure_leaves_no_tmp_file_behind(self):
        path = self._copy("claude_desktop_config.json")
        original = open(path).read()
        # Fails after the temp file exists -- the case that must clean up.
        with mock.patch("safe_write.os.fsync",
                         side_effect=OSError("disk full")):
            with self.assertRaises(register.RegisterError) as ctx:
                register.register_json(path, register.server_entries(GA_HOME))
        self.assertIn("disk full", str(ctx.exception))
        self.assertEqual(open(path).read(), original)
        self.assertFalse(os.path.exists(path + ".ga-tmp"))


class TestInstallMainHandlesRegisterError(unittest.TestCase):
    """install.py's main() must catch what register_json raises at it.

    register_json is written to abort with a RegisterError whose message says
    what to fix. main() caught InstallError only, so that message reached the
    user as a traceback -- implying a bug in the installer rather than a
    config file they need to look at.
    """

    def test_a_malformed_target_config_exits_with_the_register_message(self):
        d = tempfile.mkdtemp()
        broken = os.path.join(d, ".claude.json")
        with open(broken, "w") as f:
            f.write("{not json")

        argv = ["install.py", "--repo-root", REPO_ROOT,
                "--ga-home", os.path.join(d, ".config", "ga-mcp"),
                "--targets", "claude_code"]

        # main() prints its progress; swallow it so the suite's output stays
        # readable.
        with mock.patch.object(install.harness_paths, "claude_code_config",
                                return_value=broken), \
             mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                install.main()

        message = str(ctx.exception)
        self.assertIn("claude_code", message)
        self.assertIn("not valid JSON", message)
        self.assertIn("Refusing to write", message)
        # Unchanged, and no backup litter from an aborted run.
        self.assertEqual(open(broken).read(), "{not json")
        self.assertEqual([n for n in os.listdir(d) if "backup" in n], [])


class TestNonAsciiSurvivesRegistration(unittest.TestCase):
    """A config's existing non-ASCII text must survive being registered into.

    ~/.claude.json is written by Claude Code, which is Node: JSON.stringify does
    not escape non-ASCII, so the file on disk carries raw UTF-8. The real file on
    this machine is 115KB and holds 93 such bytes, mostly em dashes in project
    history.

    Python's open() without an explicit encoding uses the locale's -- UTF-8 on
    macOS, cp1252 on a typical Windows box. Every byte in that file is *defined*
    in cp1252, so the read does not raise. It silently decodes to mojibake, and
    json.dump then writes the mojibake back as \\uXXXX escapes of the wrong
    characters. The user's history is corrupted with no error at any point.

    _windows_locale_open below is how that is reproduced from macOS: it makes an
    omitted encoding mean cp1252, which is precisely what changes across the two
    platforms. Nothing else about the test is Windows-specific.
    """

    EM_DASH = "—"

    @staticmethod
    def _windows_locale_open(*args, **kwargs):
        """open() as it behaves where the locale encoding is cp1252."""
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        if kwargs.get("encoding") is None and "b" not in mode:
            kwargs["encoding"] = "cp1252"
        return io.open(*args, **kwargs)

    def _config_with_history(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "claude.json")
        note = f"fix the parser {self.EM_DASH} it drops rows"
        payload = {"projects": {"/Users/x/notes": {"history": [note]}}}
        # ensure_ascii=False so the file holds raw UTF-8, the way Node writes it.
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path, note

    def test_existing_history_is_not_mangled_under_a_cp1252_locale(self):
        path, note = self._config_with_history()

        with mock.patch("builtins.open", self._windows_locale_open):
            register.register_json(path, register.server_entries(GA_HOME))

        # Read it back the way the application that owns the file does.
        with io.open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        self.assertEqual(data["projects"]["/Users/x/notes"]["history"][0], note,
                         "registration mangled the user's existing project history")

    def test_the_backup_is_also_readable_as_utf8(self):
        path, note = self._config_with_history()

        with mock.patch("builtins.open", self._windows_locale_open):
            result = register.register_json(path, register.server_entries(GA_HOME))

        with io.open(result["backup"], "rb") as f:
            restored = json.loads(f.read().decode("utf-8"))
        self.assertEqual(restored["projects"]["/Users/x/notes"]["history"][0], note,
                         "the backup is not a faithful copy, so recovery would "
                         "reinstate corrupted text")


class TestServerEntriesOnWindows(unittest.TestCase):
    """The entry shape recon round 2 proved connects on native Windows.

    macOS keeps its /bin/sh launchers: they exist because Codex's plugin
    manifest can pass env NAMES but not VALUES, and Codex is a macOS surface
    here. Windows has neither /bin/sh nor Codex, so there is nothing to port
    and nothing to gain by porting it. A .ps1 is blocked by RemoteSigned on
    the target machine and a .cmd brings quoting hazards for paths like
    "OneDrive - Example Org".

    What is used instead was observed working, not designed: Claude Code
    spawned <venv>\\Scripts\\python.exe with a script argument and reported the
    server Connected. Prefer proven over elegant.
    """

    GA_HOME = r"C:\Users\example\.config\ga-mcp"
    VENV_PY = r"C:\Users\example\.config\ga-mcp\venv\Scripts\python.exe"
    ADC = r"C:\Users\example\.config\gcloud\adc-ga-personal.json"

    def _entries(self, **kw):
        kw.setdefault("venv_python", self.VENV_PY)
        kw.setdefault("adc_file", self.ADC)
        return register.server_entries(self.GA_HOME, platform="win32", **kw)

    def test_both_servers_are_still_defined(self):
        self.assertEqual(set(self._entries()), {"analytics-mcp", "ga-companion"})

    def test_nothing_points_at_a_posix_launcher(self):
        for name, entry in self._entries().items():
            self.assertNotIn("launch-ga", entry["command"], name)
            self.assertNotIn("/bin/sh", entry["command"], name)

    def test_the_companion_is_spawned_as_interpreter_plus_script(self):
        entry = self._entries()["ga-companion"]
        self.assertEqual(entry["command"], self.VENV_PY)
        self.assertEqual(len(entry["args"]), 1)
        self.assertTrue(entry["args"][0].endswith("ga_companion.py"),
                        entry["args"][0])
        self.assertIn(self.GA_HOME, entry["args"][0])

    def test_analytics_mcp_runs_as_a_module_of_the_venv_interpreter(self):
        # Not venv\Scripts\analytics-mcp.exe. pip generates that launcher on
        # each machine, so no other machine has ever seen it, and Defender's
        # "block low-prevalence executables" ASR rule refuses it -- measured on
        # a managed machine 2026-10-09 as "[WinError 5] Access is denied"
        # (round 4, #139). python.exe is the interpreter ga-companion already
        # runs through, and analytics_mcp/server.py has a __main__ guard, so
        # -m starts the same server.
        entry = self._entries()["analytics-mcp"]
        self.assertEqual(entry["command"], self.VENV_PY)
        self.assertEqual(entry["args"], ["-m", "analytics_mcp.server"])

    def test_no_entry_names_a_pip_generated_exe(self):
        for name, entry in self._entries().items():
            self.assertFalse(entry["command"].lower().endswith(
                "analytics-mcp.exe"), name)
            self.assertTrue(entry["command"].lower().endswith("python.exe"),
                            name)

    def test_env_carries_the_values_the_launchers_would_have_set(self):
        # No launcher runs on Windows, so anything a launcher used to export
        # has to be in the entry itself or it is simply never set.
        for name, entry in self._entries().items():
            self.assertEqual(entry["env"]["GRPC_DNS_RESOLVER"], "native", name)
            self.assertEqual(entry["env"]["GOOGLE_APPLICATION_CREDENTIALS"],
                             self.ADC, name)

    def test_transport_is_declared_stdio_like_the_macos_entries(self):
        for entry in self._entries().values():
            self.assertEqual(entry["type"], "stdio")

    def test_a_missing_interpreter_is_refused_rather_than_guessed(self):
        # The wrong interpreter here is silent: the entry looks fine, the
        # server fails to start, and the reported symptom points at
        # credentials. Refusing is the only safe answer.
        with self.assertRaises(register.RegisterError) as caught:
            self._entries(venv_python=None)
        self.assertIn("interpreter", str(caught.exception).lower())

    def test_a_missing_credential_path_is_refused_rather_than_guessed(self):
        with self.assertRaises(register.RegisterError):
            self._entries(adc_file=None)

    def test_macos_still_uses_the_launchers_and_needs_no_extra_arguments(self):
        entries = register.server_entries("/Users/x/.config/ga-mcp",
                                          platform="darwin")
        self.assertEqual(entries["analytics-mcp"]["command"],
                         "/Users/x/.config/ga-mcp/bin/launch-ga-mcp")
        self.assertEqual(entries["ga-companion"]["command"],
                         "/Users/x/.config/ga-mcp/bin/launch-ga-companion")

    def test_omitting_platform_uses_the_running_one(self):
        self.assertEqual(register.server_entries(GA_HOME),
                         register.server_entries(GA_HOME, platform=sys.platform))


class TestWindowsEntriesHaveOneSeparator(unittest.TestCase):
    """Round 3 nit: a registered entry read C:\\Users\\x/.config/ga-mcp\\companion.

    --ga-home defaulted to expanduser("~/.config/ga-mcp"), and expanduser
    replaces only the tilde -- so the forward slashes survived into the entry.
    Windows accepted it and the server connected, but it reads as a defect to
    anyone opening the config, and that is a cost: the config is what a person
    reads when something is wrong.
    """

    def test_a_mixed_ga_home_comes_out_with_backslashes_only(self):
        e = register.server_entries(
            "C:\\\\Users\\\\winuser/.config/ga-mcp", platform="win32",
            venv_python="C:\\\\Users\\\\winuser/.config/ga-mcp/venv/Scripts/python.exe",
            adc_file="C:\\\\Users\\\\winuser/.config/gcloud/adc-ga-personal.json")
        for name, entry in e.items():
            for value in [entry["command"], *entry["args"],
                          entry["env"]["GOOGLE_APPLICATION_CREDENTIALS"]]:
                self.assertNotIn("/", value, f"{name}: {value}")
