"""The data-noodler server loads its own config so it can run with no skill installed.

Errors must be actionable strings rather than tracebacks: in a shell-less
harness the message is the only thing the user will see.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import config

GOOD = {
    "oauth_client_file": "~/.config/gcloud/data-noodler-client.json",
    "adc_file": "~/.config/gcloud/data-noodler-credential.json",
    "quota_project": "data-noodler-123456",
    "venv_python": "~/Library/Application Support/pipx/venvs/analytics-mcp/bin/python",
    "properties_csv": "~/.config/data-noodler/properties.csv",
}


class TestLoad(unittest.TestCase):
    def _write(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        self.addCleanup(os.unlink, path)
        return path

    def test_expands_tilde_in_every_path_key(self):
        cfg = config.load(self._write(GOOD))
        for key in ("oauth_client_file", "adc_file", "venv_python",
                    "properties_csv"):
            self.assertFalse(cfg[key].startswith("~"), key)
            self.assertTrue(os.path.isabs(cfg[key]), key)

    def test_preserves_non_path_values(self):
        cfg = config.load(self._write(GOOD))
        self.assertEqual(cfg["quota_project"], "data-noodler-123456")

    def test_missing_file_names_the_setup_skill(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.load("/nonexistent/data-noodler/config.json")
        self.assertIn("data-noodler-setup", str(ctx.exception))

    def test_missing_key_says_which_key(self):
        partial = {k: v for k, v in GOOD.items() if k != "adc_file"}
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(self._write(partial))
        self.assertIn("adc_file", str(ctx.exception))

    def test_malformed_json_is_reported_as_such(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{not json")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("could not be parsed", str(ctx.exception))

    def test_json_array_top_level_raises_configerror(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(self._write([1, 2, 3]))
        self.assertIn("must contain a JSON object", str(ctx.exception))

    def test_json_null_top_level_raises_configerror(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(self._write(None))
        self.assertIn("must contain a JSON object", str(ctx.exception))

    def test_json_string_top_level_raises_configerror(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(self._write("just a string"))
        self.assertIn("must contain a JSON object", str(ctx.exception))

    def test_non_string_path_value_raises_configerror(self):
        bad_config = dict(GOOD)
        bad_config["oauth_client_file"] = 42
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(self._write(bad_config))
        self.assertIn("oauth_client_file", str(ctx.exception))
        self.assertIn("must be a string", str(ctx.exception))

    def test_quota_project_is_not_required(self):
        # A colleague does not own the author's Cloud project, so a config
        # generated for them has no quota_project at all. Requiring it here
        # would make every such install fail to load.
        self.assertNotIn("quota_project", config.REQUIRED)

    def test_loads_without_quota_project(self):
        no_quota = {k: v for k, v in GOOD.items() if k != "quota_project"}
        cfg = config.load(self._write(no_quota))
        self.assertNotIn("quota_project", cfg)


class TestQuotaProject(unittest.TestCase):
    def test_returns_none_when_absent(self):
        cfg = {k: v for k, v in GOOD.items() if k != "quota_project"}
        self.assertIsNone(config.quota_project(cfg))

    def test_returns_the_value_when_present(self):
        cfg = dict(GOOD)
        self.assertEqual(config.quota_project(cfg), "data-noodler-123456")

    def test_returns_none_for_an_empty_string(self):
        cfg = dict(GOOD)
        cfg["quota_project"] = ""
        self.assertIsNone(config.quota_project(cfg))


class TestRenewalCommand(unittest.TestCase):
    def test_optional_mint_script_key_overrides_the_default_path(self):
        cfg = dict(GOOD)
        cfg["mint_script"] = "/opt/ga/mint_adc.py"
        self.assertIn("/opt/ga/mint_adc.py", config.renewal_command(cfg))

    def test_falls_back_to_the_installed_plugin_copy_when_key_absent(self):
        cfg = dict(GOOD)
        cfg.pop("mint_script", None)
        cmd = config.renewal_command(cfg)
        self.assertIn("mint_adc.py", cmd)
        # The install payload is ("server", "bin", "marketplace"), so the
        # marketplace copy under the install home is the only one any install
        # creates. ~/.claude/skills/ is never written by anything here, so a
        # command naming it would point at nothing on a clean machine.
        self.assertIn(os.sep + os.path.join(
            "marketplace", "plugins", "data-noodler", "skills",
            "data-noodler", "scripts", "mint_adc.py"), cmd)
        self.assertIn(os.path.dirname(config.default_config_path(env={})), cmd)
        self.assertNotIn(".claude/skills", cmd)

    def test_a_mint_script_under_the_old_plugin_layout_is_followed(self):
        # #1999: config.json written before the rename names the script under
        # plugins/ga-analytics/skills/google-analytics/. The reinstall renames
        # those folders, so the command must name where it now is.
        cfg = dict(GOOD)
        cfg["mint_script"] = ("/h/.config/x/marketplace/plugins/ga-" "analytics"
                              "/skills/google-" "analytics/scripts/mint_adc.py")
        cmd = config.renewal_command(cfg)
        self.assertIn("/h/.config/x/marketplace/plugins/data-noodler"
                      "/skills/data-noodler/scripts/mint_adc.py", cmd)

    def test_a_windows_mint_script_under_the_old_plugin_layout_is_followed(self):
        # #2055: the pre-rename installer built mint_script with os.path.join,
        # so a Windows config.json holds backslashes, and the reinstall keeps
        # that config. The rename must be followed in that form too.
        old = ("C:\\Users\\you\\.config\\x\\marketplace\\plugins\\ga-" "analytics"
               "\\skills\\google-" "analytics\\scripts\\mint_adc.py")
        self.assertEqual(
            config.mint_script({"mint_script": old}),
            "C:\\Users\\you\\.config\\x\\marketplace\\plugins\\data-noodler"
            "\\skills\\data-noodler\\scripts\\mint_adc.py")

    def test_an_already_renamed_mint_script_is_left_alone(self):
        # #2055: following the rename must not touch a path that has none.
        for path in ("/h/.config/data-noodler/marketplace/plugins/data-noodler"
                     "/skills/data-noodler/scripts/mint_adc.py",
                     "C:\\Users\\you\\.config\\data-noodler\\marketplace\\plugins"
                     "\\data-noodler\\skills\\data-noodler\\scripts\\mint_adc.py"):
            self.assertEqual(config.mint_script({"mint_script": path}), path)

    def test_the_fallback_follows_an_install_that_predates_the_rename(self):
        # #1999: until migrate_home.py moves it, the payload is in the old
        # home, so that is where the renewal command must point.
        h = tempfile.mkdtemp()
        old = os.path.join(h, ".config", "ga-" "mcp")
        os.makedirs(old)
        with open(os.path.join(old, "config.json"), "w") as f:
            f.write("{}")
        self.assertTrue(config.default_mint_script(home=h).startswith(
            old + os.sep), config.default_mint_script(home=h))
        new = os.path.join(h, ".config", "data-noodler")
        os.makedirs(new)
        # An empty new folder changes nothing (Indigo's review of PR #5).
        self.assertTrue(config.default_mint_script(home=h).startswith(old + os.sep))
        with open(os.path.join(new, "config.json"), "w") as f:
            f.write("{}")
        self.assertTrue(config.default_mint_script(home=h).startswith(
            os.path.join(h, ".config", "data-noodler") + os.sep))

    def test_the_fallback_path_is_the_one_bootstrap_config_writes(self):
        # The two must not drift: bootstrap_config puts mint_script in every
        # new config, and this fallback serves configs written before that key
        # existed. Different answers would mean two different renewal
        # commands depending on the config's age.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "installer"))
        import bootstrap_config
        self.assertEqual(
            config.DEFAULT_MINT_SCRIPT.removeprefix("~/"),
            "/".join(bootstrap_config.MINT_SCRIPT_PARTS))

    def test_quotes_the_venv_path_because_it_contains_a_space(self):
        cfg = dict(GOOD)
        cfg["venv_python"] = "/Users/x/Application Support/venv/bin/python"
        cmd = config.renewal_command(cfg)
        self.assertIn('"/Users/x/Application Support/venv/bin/python"', cmd)
        self.assertIn("mint_adc.py", cmd)
        self.assertIn("--force", cmd)

    def test_quotes_the_script_path_too(self):
        # Same class of bug as the venv path: a home directory containing a
        # space ("/Users/Jane Smith") would break an unquoted script path,
        # and the user would see a command that silently does nothing.
        cfg = dict(GOOD)
        cfg["mint_script"] = "/Users/Jane Smith/.config/data-noodler/mint_adc.py"
        cmd = config.renewal_command(cfg)
        self.assertIn('"/Users/Jane Smith/.config/data-noodler/mint_adc.py"', cmd)

    def test_no_tilde_survives_into_the_command(self):
        # Quoting is only safe after expansion: the shell does not expand a
        # tilde inside double quotes, so a quoted "~/..." would be a literal
        # directory named "~".
        cfg = dict(GOOD)
        cfg.pop("mint_script", None)
        cmd = config.renewal_command(cfg)
        self.assertNotIn("~", cmd)


class TestTheRenewalLineRunsInTheShellTheUserIsSentTo(unittest.TestCase):
    """#2017, measured on windows-latest (run 44884961837): the quoted line
    is a parse error in Windows PowerShell 5.1 and pwsh 7, and runs with a
    leading "& " in both; cmd.exe runs it bare and rejects the "& ". The
    Windows guide sends users to PowerShell, so that is the form given."""

    def _cfg(self):
        cfg = dict(GOOD)
        cfg["venv_python"] = r"C:\Users\Jane Smith\venv\Scripts\python.exe"
        cfg["mint_script"] = r"C:\Users\Jane Smith\mint_adc.py"
        return cfg

    def test_on_windows_the_line_starts_with_the_call_operator(self):
        cmd = config.renewal_command(self._cfg(), platform="win32")
        self.assertTrue(cmd.startswith('& "'), cmd)
        self.assertIn(r'"C:\Users\Jane Smith\mint_adc.py" --force', cmd)

    def test_elsewhere_the_line_has_no_call_operator(self):
        for platform in ("darwin", "linux"):
            cmd = config.renewal_command(dict(GOOD), platform=platform)
            self.assertFalse(cmd.startswith("&"), cmd)
            self.assertTrue(cmd.startswith('"'), cmd)

    def test_the_shell_is_named_so_a_cmd_user_is_not_misled(self):
        self.assertEqual(config.renewal_shell("win32"), "PowerShell")
        self.assertEqual(config.renewal_shell("darwin"), "a terminal")

class TestSessionsRoot(unittest.TestCase):
    def test_uses_the_configured_value_when_present(self):
        cfg = dict(GOOD)
        cfg["sessions_root"] = "~/Desktop/work"
        # normpath, as sessions_root does: expanduser alone gives
        # C:\Users\x/Desktop/work on Windows (#2008).
        self.assertEqual(config.sessions_root(cfg),
                         os.path.normpath(os.path.expanduser("~/Desktop/work")))

    def test_falls_back_to_the_default_when_absent(self):
        cfg = dict(GOOD)
        cfg.pop("sessions_root", None)
        self.assertTrue(config.sessions_root(cfg).endswith("analyst-sessions"))

    def test_sessions_root_is_not_required(self):
        # The live config on this machine has five keys and none of them is
        # sessions_root. Adding it to REQUIRED would break every existing
        # install.
        self.assertNotIn("sessions_root", config.REQUIRED)


class TestGrantedScopes(unittest.TestCase):
    def _cfg_with_adc(self, payload):
        d = tempfile.mkdtemp()
        adc = os.path.join(d, "adc.json")
        with open(adc, "w") as f:
            json.dump(payload, f)
        cfg = dict(GOOD)
        cfg["adc_file"] = adc
        return cfg

    def test_reports_scopes_when_the_credential_records_them(self):
        cfg = self._cfg_with_adc({
            "refresh_token": "x",
            "scopes": ["https://www.googleapis.com/auth/analytics.readonly"]})
        self.assertEqual(config.granted_scopes(cfg),
                         ["https://www.googleapis.com/auth/analytics.readonly"])

    def test_returns_empty_when_the_file_records_no_scopes(self):
        # The ADC file written by mint_adc.py has no scopes key -- the scope is
        # bound to the token server-side. Absence is not an error.
        cfg = self._cfg_with_adc({"refresh_token": "x"})
        self.assertEqual(config.granted_scopes(cfg), [])

    def test_returns_empty_when_the_credential_is_missing(self):
        cfg = dict(GOOD)
        cfg["adc_file"] = "/nonexistent/adc.json"
        self.assertEqual(config.granted_scopes(cfg), [])

    def test_returns_empty_for_a_malformed_credential(self):
        d = tempfile.mkdtemp()
        adc = os.path.join(d, "adc.json")
        with open(adc, "w") as f:
            f.write("{not json")
        cfg = dict(GOOD)
        cfg["adc_file"] = adc
        self.assertEqual(config.granted_scopes(cfg), [])

    def test_returns_empty_when_adc_file_contains_a_json_list(self):
        # ADC files are always objects, but defend against the type error.
        cfg = self._cfg_with_adc([1, 2, 3])
        self.assertEqual(config.granted_scopes(cfg), [])

    def test_returns_empty_when_adc_file_contains_a_json_string(self):
        # ADC files are always objects, but defend against the type error.
        cfg = self._cfg_with_adc("just a string")
        self.assertEqual(config.granted_scopes(cfg), [])

    def test_returns_empty_when_adc_file_contains_json_null(self):
        # ADC files are always objects, but defend against the type error.
        cfg = self._cfg_with_adc(None)
        self.assertEqual(config.granted_scopes(cfg), [])
