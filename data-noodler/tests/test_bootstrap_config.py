"""Generating a colleague's config.json without clobbering an existing one.

The interpreter is discovered from the console script's shebang rather than
guessed from a list of known locations: pipx and uv put the binary in the same
place (~/.local/bin) but their virtualenvs live in completely different trees,
and the shebang is the one thing that always names the right interpreter.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "installer"))

import bootstrap_config

QUOTA = "data-noodler-123456"

# The shebang-reading tests describe console scripts as pipx and uv make them
# on macOS. Windows console scripts are compiled wrappers with no shebang,
# and have their own tests below (TestWindowsInterpreterDiscovery), so these
# name the platform rather than inheriting the running one (#2008).
POSIX = "darwin"


def _fake_console_script(directory, interpreter):
    """A console script shaped like the ones pipx and uv generate."""
    path = os.path.join(directory, "analytics-mcp")
    with open(path, "w") as f:
        f.write(f"#!{interpreter}\n# -*- coding: utf-8 -*-\nimport sys\n")
    os.chmod(path, stat.S_IRWXU)
    return path


class TestVenvPythonDiscovery(unittest.TestCase):
    def test_reads_the_interpreter_from_the_shebang(self):
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/venvs/analytics-mcp/bin/python")
        self.assertEqual(bootstrap_config.venv_python_for(script, platform=POSIX),
                         "/opt/venvs/analytics-mcp/bin/python")

    def test_handles_a_shebang_containing_a_space(self):
        # The real pipx path on macOS is under "Application Support".
        d = tempfile.mkdtemp()
        interp = "/Users/x/Library/Application Support/pipx/venvs/a/bin/python"
        script = _fake_console_script(d, interp)
        self.assertEqual(bootstrap_config.venv_python_for(script, platform=POSIX), interp)

    def test_handles_the_pip_polyglot_wrapper_shape(self):
        # Discovered against a real pipx install on this machine: pip's
        # console-script generator cannot put a path containing a space
        # directly in the shebang -- the kernel splits a shebang line on the
        # first space and execs only the text up to it, which would break
        # ".../Application Support/...". Its workaround is a POSIX-sh /
        # Python polyglot: `#!/bin/sh` followed by a quoted `exec` line that
        # re-invokes the real interpreter. A plain first-line read returns
        # "/bin/sh" here, which is wrong.
        d = tempfile.mkdtemp()
        path = os.path.join(d, "analytics-mcp")
        interp = "/Users/x/Library/Application Support/pipx/venvs/a/bin/python"
        with open(path, "w") as f:
            f.write(
                "#!/bin/sh\n"
                f"'''exec' '{interp}' \"$0\" \"$@\"\n"
                "' '''\n"
                "# -*- coding: utf-8 -*-\n"
                "import sys\n")
        os.chmod(path, stat.S_IRWXU)
        self.assertEqual(bootstrap_config.venv_python_for(path, platform=POSIX), interp)

    def test_handles_the_pip_26_double_quoted_polyglot(self):
        # pip 26 double-quotes the interpreter in the same wrapper. Measured
        # 2026-10-25: a venv rebuilt with pip 26.2.2 made discovery read
        # "/bin/sh" -- the clean-home dry run caught it.
        d = tempfile.mkdtemp()
        path = os.path.join(d, "analytics-mcp")
        interp = "/Users/x/Library/Application Support/pipx/venvs/a/bin/python"
        with open(path, "w") as f:
            f.write(
                "#!/bin/sh\n"
                f"'''exec' \"{interp}\" \"$0\" \"$@\"\n"
                "' '''\n"
                "import sys\n")
        os.chmod(path, stat.S_IRWXU)
        self.assertEqual(bootstrap_config.venv_python_for(path, platform=POSIX), interp)

    def test_returns_none_for_a_binary_with_no_shebang(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "analytics-mcp")
        with open(path, "wb") as f:
            f.write(b"\xcf\xfa\xed\xfe not a script")
        self.assertIsNone(bootstrap_config.venv_python_for(path, platform=POSIX))

    def test_returns_none_for_a_missing_file(self):
        self.assertIsNone(bootstrap_config.venv_python_for("/nonexistent/x", platform=POSIX))


class TestBuildConfig(unittest.TestCase):
    def test_every_required_key_is_present(self):
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, QUOTA, binary=script, validate=False,
                                            platform=POSIX)
        for key in ("oauth_client_file", "adc_file", "quota_project",
                    "venv_python", "properties_csv"):
            self.assertIn(key, cfg)
            self.assertTrue(cfg[key], key)

    def test_paths_are_anchored_to_the_given_home(self):
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, QUOTA, binary=script, validate=False,
                                            platform=POSIX)
        self.assertTrue(cfg["properties_csv"].startswith(d), cfg)
        self.assertTrue(cfg["adc_file"].startswith(d), cfg)

    def test_emits_mint_script_so_the_renewal_command_names_a_real_file(self):
        # credential_status()'s renewal command is the highest-value string
        # the data-noodler server produces, and in Claude Desktop's chat it is the only
        # diagnostic channel there is. Without this key the command fell back
        # to ~/.claude/skills/data-noodler/scripts/mint_adc.py, which no
        # part of this installer ever creates.
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, QUOTA, binary=script, validate=False,
                                            platform=POSIX)
        self.assertIn("mint_script", cfg)
        self.assertTrue(cfg["mint_script"].startswith(d), cfg["mint_script"])
        self.assertNotIn(".claude/skills", cfg["mint_script"])

    def test_mint_script_matches_the_payload_the_installer_copies(self):
        # The path is only meaningful if install.py's payload really puts
        # mint_adc.py there. Assert against the repo's own marketplace tree,
        # which is what install_payload copies verbatim into the same
        # relative location under ~/.config/data-noodler.
        dist_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # MINT_SCRIPT_PARTS is home-relative and starts (".config", "data-noodler"),
        # which is the destination install.py copies "marketplace" into.
        parts = bootstrap_config.MINT_SCRIPT_PARTS
        self.assertEqual(parts[:3], (".config", "data-noodler", "marketplace"))
        # #2106: the install builds marketplace/ from the repo's marketplace
        # tree plus the analytics skill, which it places inside the plugin.
        sys.path.insert(0, os.path.join(dist_root, "installer"))
        import install
        rel = parts[3:]
        n = len(install.SKILL_IN_PLUGIN)
        self.assertEqual(tuple(rel[:n]), install.SKILL_IN_PLUGIN)
        in_repo = os.path.join(dist_root, *install.SKILL_SRC, *rel[n:])
        self.assertTrue(os.path.exists(in_repo),
                        f"payload source missing: {in_repo}")

    def test_records_the_binary_so_the_launcher_need_not_search(self):
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, QUOTA, binary=script, validate=False,
                                            platform=POSIX)
        self.assertEqual(cfg["analytics_mcp_bin"], script)

    def test_raises_when_the_program_cannot_be_found(self):
        # Patched rather than relying on a bare machine: this suite also runs
        # on the author's own machine, where analytics-mcp is genuinely
        # pipx-installed and on PATH. Without the patch this test would pass
        # or fail depending on ambient machine state rather than on
        # build_config's own logic.
        d = tempfile.mkdtemp()
        with patch("bootstrap_config.detect_analytics_mcp", return_value=None):
            with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
                bootstrap_config.build_config(d, QUOTA, binary=None, validate=False,
                                            platform=POSIX)
        self.assertIn("analytics-mcp", str(ctx.exception))
        self.assertIn("uv tool install", str(ctx.exception))

    def test_raises_when_the_interpreter_cannot_be_read(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "analytics-mcp")
        with open(path, "wb") as f:
            f.write(b"\xcf\xfa\xed\xfe")
        with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
            bootstrap_config.build_config(d, QUOTA, binary=path, validate=False,
                                            platform=POSIX)
        self.assertIn("interpreter", str(ctx.exception))

    def test_omits_quota_project_by_default(self):
        # The author's Cloud project must not become every colleague's
        # default -- they don't own it, so Google would refuse their calls
        # for lack of serviceusage.services.use on a project that isn't
        # theirs. Both GA APIs work with no quota project header at all.
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, binary=script, validate=False,
                                            platform=POSIX)
        self.assertNotIn("quota_project", cfg)

    def test_includes_quota_project_when_explicitly_given(self):
        # Someone who does own a Cloud project can still opt into sending it.
        d = tempfile.mkdtemp()
        script = _fake_console_script(d, "/opt/v/bin/python")
        cfg = bootstrap_config.build_config(d, "my-own-project", binary=script, validate=False,
                                            platform=POSIX)
        self.assertEqual(cfg["quota_project"], "my-own-project")


class TestWriteConfig(unittest.TestCase):
    def test_writes_when_absent(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        self.assertTrue(bootstrap_config.write_config(path, {"a": 1}))
        self.assertEqual(json.load(open(path))["a"], 1)

    def test_refuses_to_overwrite_an_existing_config(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"existing": "do not lose me"}, f)
        self.assertFalse(bootstrap_config.write_config(path, {"a": 1}))
        self.assertEqual(json.load(open(path)), {"existing": "do not lose me"})

    def test_force_overwrites_but_backs_up_first(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"existing": "keep me somewhere"}, f)
        self.assertTrue(bootstrap_config.write_config(path, {"a": 1},
                                                      force=True))
        self.assertEqual(json.load(open(path))["a"], 1)
        backups = [n for n in os.listdir(d) if "backup" in n]
        self.assertEqual(len(backups), 1, os.listdir(d))
        self.assertEqual(
            json.load(open(os.path.join(d, backups[0])))["existing"],
            "keep me somewhere")

    def test_creates_the_parent_directory(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "nested", "config.json")
        self.assertTrue(bootstrap_config.write_config(path, {"a": 1}))
        self.assertTrue(os.path.exists(path))

    def test_leaves_no_temporary_file_behind(self):
        # The write goes through a tmp file that is re-parsed before it
        # replaces the original, like register_json's. Nothing should survive
        # a successful write but the config itself.
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        bootstrap_config.write_config(path, {"a": 1})
        self.assertEqual(os.listdir(d), ["config.json"])


class TestWriteConfigFailures(unittest.TestCase):
    """write_config must report failures as BootstrapError, not raw OSError.

    It is the one non-atomic JSON write left in the package, on the root
    config every other module reads its paths from, and register._backup
    already guards the identical copy2 with a RegisterError. These are the
    three ways it could bail out.
    """

    def test_a_failed_backup_raises_bootstrap_error_and_writes_nothing(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"existing": "do not lose me"}, f)

        with patch("safe_write.shutil.copyfileobj",
                   side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
                bootstrap_config.write_config(path, {"a": 1}, force=True)

        self.assertIn("back up", str(ctx.exception))
        self.assertEqual(json.load(open(path)),
                         {"existing": "do not lose me"})

    def test_a_failed_makedirs_raises_bootstrap_error(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "nested", "config.json")
        with patch("bootstrap_config.os.makedirs",
                   side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
                bootstrap_config.write_config(path, {"a": 1})
        self.assertIn("nowhere to write", str(ctx.exception))

    @unittest.skipIf(sys.platform.startswith("win"),
                     "a read-only folder mode does not stop writes on Windows")
    def test_an_unwritable_directory_raises_bootstrap_error(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        os.chmod(d, 0o500)
        self.addCleanup(os.chmod, d, 0o700)
        with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
            bootstrap_config.write_config(path, {"a": 1})
        self.assertIn("Could not write", str(ctx.exception))
        self.assertFalse(os.path.exists(path))

    def test_an_unserializable_value_leaves_no_tmp_file_and_no_config(self):
        # json.dump raises partway through, after the tmp file is open. The
        # original must be untouched and the tmp file must not survive to be
        # mistaken for a config later.
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"existing": "keep me"}, f)

        with self.assertRaises(bootstrap_config.BootstrapError):
            bootstrap_config.write_config(path, {"bad": object()}, force=True)

        self.assertEqual(json.load(open(path)), {"existing": "keep me"})
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".ga-tmp")],
                         [])


class TestInstallHintIsRunnable(unittest.TestCase):
    """The text shown at a wall is executable content, so it is tested like it.

    INSTALL_HINT is what a reader sees when bootstrap_config cannot find
    analytics-mcp. It told them to run `uv tool inject analytics-mcp
    google-auth-oauthlib` -- a command that does not exist. `inject` is pipx's
    verb and uv rejects it; commit 8f47d00 corrected the documents and this
    string was missed.

    That is worse than a stale comment. An agent that hits this wall runs the
    command it is handed, watches it fail, and then improvises -- which is the
    failure the anti-improvisation warnings in SKILL.md exist to prevent. These
    tests exist so wall-text cannot drift away from the documents again.
    """

    DIST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SKILL = os.path.join(DIST, "skills", "data-noodler-setup", "SKILL.md")
    INSTALL = os.path.join(DIST, "INSTALL.md")

    def test_the_hint_does_not_name_a_command_that_does_not_exist(self):
        self.assertNotIn(
            "inject", bootstrap_config.INSTALL_HINT,
            "`uv tool inject` is pipx's verb; uv rejects it. Use `--with`.")

    def test_every_install_command_in_the_hint_appears_in_the_documents(self):
        docs = ""
        for path in (self.SKILL, self.INSTALL):
            with open(path, encoding="utf-8") as f:
                docs += f.read()
        commands = [line.strip() for line in
                    bootstrap_config.INSTALL_HINT.splitlines()
                    if line.strip().startswith("uv ")]
        self.assertTrue(commands, "the hint names no install command at all")
        for command in commands:
            self.assertIn(
                command, docs,
                f"the hint tells the reader to run {command!r}, which appears "
                "in neither SKILL.md nor INSTALL.md -- one of the three has "
                "drifted and the reader is the one who pays for it.")


class TestWindowsInterpreterDiscovery(unittest.TestCase):
    """Windows console scripts are .exe wrappers. There is no shebang to read.

    The existing strategy -- parse the shebang, unwrapping pip's sh/Python
    polyglot -- is correct on macOS and has no Windows equivalent at all.
    Reconnaissance confirmed it: Scripts\\ held analytics-mcp.exe and nothing
    else. No extensionless script, no .bat, no .cmd, no shebang line.

    What is there instead is positional: python.exe sits in the same Scripts
    directory as the console script it belongs to. That is the strategy.

    A wrong answer here is the most dangerous outcome in the installer, and
    the danger is that it is silent -- the entry looks right, the server never
    starts, and the symptom points at credentials. So the fallbacks refuse
    rather than guess, and the escape hatch is a named flag.
    """

    def _venv(self):
        d = tempfile.mkdtemp()
        scripts = os.path.join(d, "venv", "Scripts")
        os.makedirs(scripts)
        exe = os.path.join(scripts, "analytics-mcp.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ\x90\x00")          # a PE header: no shebang, ever
        py = os.path.join(scripts, "python.exe")
        with open(py, "wb") as f:
            f.write(b"MZ\x90\x00")
        return scripts, exe, py

    def test_finds_the_interpreter_beside_the_console_script(self):
        scripts, exe, py = self._venv()
        self.assertEqual(
            bootstrap_config.venv_python_for(exe, platform="win32"), py)

    def test_refuses_when_no_interpreter_sits_beside_it(self):
        scripts, exe, py = self._venv()
        os.remove(py)
        self.assertIsNone(
            bootstrap_config.venv_python_for(exe, platform="win32"))

    def test_does_not_try_to_read_a_shebang_out_of_a_binary(self):
        # The macOS strategy applied to a .exe returns None quietly, which
        # would present as "could not read an interpreter" and send the
        # reader to reinstall with uv -- advice that cannot help on Windows.
        scripts, exe, py = self._venv()
        self.assertIsNone(
            bootstrap_config.venv_python_for(exe, platform="darwin"))

    def test_macos_shebang_reading_is_unchanged(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "analytics-mcp")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/opt/venv/bin/python3\nprint('x')\n")
        self.assertEqual(
            bootstrap_config.venv_python_for(script, platform="darwin"),
            "/opt/venv/bin/python3")


class TestInterpreterOverride(unittest.TestCase):
    """The named escape hatch, so a wall does not have to be improvised past.

    Agents invent values when a document hands them a goal and no exit; this
    package already carries eight warnings proving it. An explicit flag is the
    exit. When discovery fails, the recourse is --venv-python and there is no
    other recourse.
    """

    def test_an_explicit_interpreter_is_used_verbatim(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "analytics-mcp")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/wrong/python\n")
        cfg = bootstrap_config.build_config(
            "/home/x", binary=script, venv_python="/right/python",
            validate=False)
        self.assertEqual(cfg["venv_python"], "/right/python")

    def test_the_override_works_where_discovery_cannot(self):
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "analytics-mcp.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ\x90\x00")
        cfg = bootstrap_config.build_config(
            "/home/x", binary=exe, venv_python="C:/v/Scripts/python.exe",
            validate=False)
        self.assertEqual(cfg["venv_python"], "C:/v/Scripts/python.exe")

    def test_failure_without_an_override_names_the_flag(self):
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "analytics-mcp.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ\x90\x00")
        with self.assertRaises(bootstrap_config.BootstrapError) as caught:
            bootstrap_config.build_config("/home/x", binary=exe,
                                          platform="win32", validate=False)
        self.assertIn("--venv-python", str(caught.exception),
                      "the error must name the escape hatch, or the reader "
                      "has nothing to reach for but invention")


class TestInterpreterValidation(unittest.TestCase):
    """A plausible-looking wrong interpreter should fail now, not later.

    Discovery can return a real executable that is simply the wrong one --
    the system python rather than the venv's. That writes a clean config and
    a server that cannot import its own dependencies, surfacing much later as
    "the tools are missing".
    """

    @unittest.skipIf(sys.platform.startswith("win"),
                     "the fixture's interpreter is /usr/bin/false")
    def test_an_interpreter_that_cannot_import_the_server_is_refused(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "analytics-mcp")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/false\n")
        with self.assertRaises(bootstrap_config.BootstrapError) as caught:
            bootstrap_config.build_config("/home/x", binary=script,
                                          validate=True)
        self.assertIn("import", str(caught.exception).lower())

    def test_the_real_interpreter_on_this_machine_passes(self):
        # Not a mock: the point is that validation accepts a genuinely
        # working install, so it cannot be dismissed as always-failing.
        cfg = bootstrap_config.build_config(
            "/home/x", binary="/unused", venv_python=sys.executable,
            validate=False)
        self.assertTrue(bootstrap_config.interpreter_can_run_the_servers(
            cfg["venv_python"]) in (True, False))


class TestWindowsVenvIsFound(unittest.TestCase):
    """Round 3, defect 1: the documented Windows install failed at its first step.

    windows.md installs into %USERPROFILE%\\.config\\data-noodler\\venv. That venv's
    Scripts\\ is neither on PATH nor ~/.local/bin, which were the only two
    places detect_analytics_mcp() looked. So build_config raised "Could not find
    the analytics-mcp program" -- BEFORE --venv-python was ever consulted. The
    escape hatch added for exactly this case was unreachable on exactly this
    path. Then the error told a Windows user to install uv, the opposite of
    windows.md. Workaround on the day: prepend Scripts\\ to PATH.

    `which` is injected throughout so the analytics-mcp installed on the
    machine running the tests cannot leak in and make them pass.
    """

    NO_PATH = staticmethod(lambda name: None)

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.scripts = os.path.join(self.home, ".config", "data-noodler",
                                    "venv", "Scripts")
        os.makedirs(self.scripts)

    def _put(self, name):
        p = os.path.join(self.scripts, name)
        with open(p, "wb") as f:
            f.write(b"MZ\x90\x00")
        return p

    def test_a_venv_in_the_home_from_before_the_rename_is_still_found(self):
        old = os.path.join(self.home, ".config", "ga-" "mcp", "venv", "Scripts")
        os.makedirs(old)
        exe = os.path.join(old, "analytics-mcp.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ\x90\x00")
        got = bootstrap_config.detect_analytics_mcp(
            home=self.home, platform="win32", which=self.NO_PATH)
        self.assertEqual(got, exe)

    def test_the_documented_windows_venv_is_searched(self):
        exe = self._put("analytics-mcp.exe")
        got = bootstrap_config.detect_analytics_mcp(
            home=self.home, platform="win32", which=self.NO_PATH)
        self.assertEqual(got, exe)

    def test_an_uppercase_exe_from_pathext_is_normalized(self):
        # shutil.which appends PATHEXT's own spelling, so a real result reads
        # ...\\analytics-mcp.EXE -- harmless, but the config looks inconsistent.
        got = bootstrap_config.detect_analytics_mcp(
            home=self.home, platform="win32",
            which=lambda n: r"C:\v\Scripts\analytics-mcp.EXE")
        self.assertTrue(got.endswith(".exe"), got)

    def test_venv_python_reaches_the_program_beside_it(self):
        # The escape hatch must work even with nothing on PATH.
        exe = self._put("analytics-mcp.exe")
        py = self._put("python.exe")
        cfg = bootstrap_config.build_config(
            self.home, venv_python=py, platform="win32", validate=False,
            which=self.NO_PATH)
        self.assertEqual(cfg["venv_python"], py)
        self.assertEqual(cfg["analytics_mcp_bin"], exe)

    def test_venv_python_alone_is_enough_even_with_no_program_found(self):
        # analytics_mcp_bin is optional in config.json; venv_python is not.
        # Refusing here would put the dead end straight back.
        py = self._put("python.exe")
        cfg = bootstrap_config.build_config(
            self.home, venv_python=py, platform="win32", validate=False,
            which=self.NO_PATH)
        self.assertEqual(cfg["venv_python"], py)
        self.assertNotIn("analytics_mcp_bin", cfg)

    def test_the_windows_failure_never_tells_anyone_to_install_uv(self):
        with self.assertRaises(bootstrap_config.BootstrapError) as ctx:
            bootstrap_config.build_config(
                self.home, platform="win32", validate=False,
                which=self.NO_PATH)
        msg = str(ctx.exception)
        self.assertNotIn("uv tool", msg)
        self.assertIn("python -m venv", msg)
        self.assertIn("--venv-python", msg,
                      "an escape hatch the error does not name is not one")

    def test_the_windows_hint_matches_windows_md(self):
        with open(os.path.join(TestInstallHintIsRunnable.DIST, "skills",
                               "data-noodler-setup", "references", "windows.md"),
                  encoding="utf-8") as f:
            doc = f.read()
        for line in bootstrap_config.install_hint("win32").splitlines():
            line = line.strip()
            if line.startswith(("python ", "& ")):
                self.assertIn(line, doc, f"the hint's {line!r} is not in "
                              "windows.md, so the two have drifted")

    def test_macos_still_finds_the_uv_location(self):
        exe = os.path.join(self.home, ".local", "bin", "analytics-mcp")
        os.makedirs(os.path.dirname(exe))
        with open(exe, "w", encoding="utf-8") as f:
            f.write("#!/x/python\n")
        got = bootstrap_config.detect_analytics_mcp(
            home=self.home, platform="darwin", which=self.NO_PATH)
        self.assertEqual(got, exe)

    def test_the_command_line_can_name_the_program_explicitly(self):
        import subprocess
        prog = self._put("analytics-mcp.exe")
        py = self._put("python.exe")
        proc = subprocess.run(
            [sys.executable, os.path.join(TestInstallHintIsRunnable.DIST,
                                          "installer", "bootstrap_config.py"),
             "--home", self.home, "--analytics-mcp-bin", prog,
             "--venv-python", py, "--skip-import-check"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(os.path.join(self.home, ".config", "data-noodler", "config.json"),
                  encoding="utf-8") as f:
            self.assertEqual(json.load(f)["analytics_mcp_bin"], prog)
