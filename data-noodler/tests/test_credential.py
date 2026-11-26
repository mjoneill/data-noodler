"""Expiry reporting must be actionable in a harness with no shell.

Claude Desktop's normal chat cannot run mint_adc.py, so the report has to
carry the exact command for the user to paste, and has to say that the client
must restart afterward -- the server reads the credential only at spawn.
"""

import ast
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import credential

CMD = '"/path/to/venv/python" /path/to/mint_adc.py --force'
DAY = 86400.0


class TestCredentialReport(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.unlink, self.path)

    def _report_at_age(self, age_days):
        minted = time.time() - age_days * DAY
        os.utime(self.path, (minted, minted))
        return credential.credential_report(self.path, CMD)

    def test_missing_file_is_expired_and_names_the_command(self):
        r = credential.credential_report("/nonexistent/adc.json", CMD)
        self.assertFalse(r["exists"])
        self.assertTrue(r["expired"])
        self.assertIsNone(r["days_remaining"])
        self.assertEqual(r["renewal_command"], CMD)

    def test_every_renewal_message_names_the_shell_given(self):
        # #2017: a Windows line runs only in PowerShell, so the message must
        # say so rather than "a terminal".
        for age in (None, 6.0, 9.0):
            if age is None:
                r = credential.credential_report("/nonexistent/adc.json",
                                                 CMD, shell="PowerShell")
            else:
                minted = time.time() - age * DAY
                os.utime(self.path, (minted, minted))
                r = credential.credential_report(self.path, CMD,
                                                 shell="PowerShell")
            self.assertIn("in PowerShell", r["summary"], age)
            self.assertNotIn("in a terminal", r["summary"], age)

    def test_fresh_credential_has_a_full_window(self):
        r = self._report_at_age(0)
        self.assertTrue(r["exists"])
        self.assertFalse(r["expired"])
        self.assertAlmostEqual(r["days_remaining"], 7.0, places=2)

    def test_midlife_credential_reports_remaining_days(self):
        r = self._report_at_age(4)
        self.assertFalse(r["expired"])
        self.assertAlmostEqual(r["days_remaining"], 3.0, places=2)

    def test_just_inside_the_window_is_not_expired(self):
        r = self._report_at_age(6.9)
        self.assertFalse(r["expired"])

    def test_just_outside_the_window_is_expired(self):
        r = self._report_at_age(7.1)
        self.assertTrue(r["expired"])
        self.assertLess(r["days_remaining"], 0)

    def test_expired_summary_carries_command_and_restart_warning(self):
        r = self._report_at_age(9)
        self.assertIn(CMD, r["summary"])
        self.assertIn("restart", r["summary"].lower())

    def test_near_expiry_summary_warns_without_claiming_failure(self):
        r = self._report_at_age(6.5)
        self.assertIn(CMD, r["summary"])
        self.assertNotIn("has expired", r["summary"])

    def test_healthy_summary_does_not_nag_with_a_command(self):
        r = self._report_at_age(1)
        self.assertNotIn(CMD, r["summary"])

    def test_now_is_injectable_for_deterministic_tests(self):
        minted = 1_000_000.0
        os.utime(self.path, (minted, minted))
        r = credential.credential_report(self.path, CMD,
                                         now=minted + 2 * DAY)
        self.assertAlmostEqual(r["days_remaining"], 5.0, places=6)

    def test_unreadable_credential_returns_report_not_exception(self):
        """File exists but cannot be stat'd (permission, I/O error, etc.)

        This covers TOCTOU races and permission errors. The function must
        return an actionable report, never raise, since the shell-less harness
        has no other diagnostic channel.
        """
        with patch("os.path.getmtime", side_effect=PermissionError("Permission denied")):
            r = credential.credential_report(self.path, CMD)
            self.assertFalse(r["exists"])
            self.assertTrue(r["expired"])
            self.assertIsNone(r["days_remaining"])
            self.assertEqual(r["renewal_command"], CMD)
            self.assertIn(CMD, r["summary"])
            self.assertIn("restart", r["summary"].lower())


class TestScopeLine(unittest.TestCase):
    GA = "https://www.googleapis.com/auth/analytics.readonly"
    GSC = "https://www.googleapis.com/auth/webmasters.readonly"

    def test_both_scopes_reported_plainly(self):
        line = credential.scope_line([self.GA, self.GSC])
        self.assertIn("Analytics", line)
        self.assertIn("Search Console", line)

    def test_ga_only_says_search_console_is_missing(self):
        line = credential.scope_line([self.GA])
        self.assertIn("Search Console", line)
        self.assertIn("re-mint", line.lower())

    def test_unknown_scopes_are_not_reported_as_none(self):
        # mint_adc.py writes no scopes key; the grant is bound to the token
        # server-side. Absence means unknown, never denial.
        #
        # The message may now explain that a missing scope is one of the two
        # things a permission error can mean -- it has to, because the other
        # one is unfixable by re-minting -- but it must still never send the
        # reader to re-consent on the strength of absence alone.
        line = credential.scope_line([]).lower()
        self.assertIn("not recorded", line)
        self.assertNotIn("re-mint the credential", line)
        self.assertNotIn("need re-minting", line)
        self.assertIn("do not reach for it first", line)


class TestScopeLineNamesBothCausesOfA403(unittest.TestCase):
    """Re-consent is the most destructive action in this package: it opens a
    browser and replaces a working credential. A message naming only the
    missing scope sends the reader there for a problem re-minting cannot
    touch -- an account that is simply not a verified owner on that site.
    """

    def test_the_unknown_scopes_message_names_verification_too(self):
        line = credential.scope_line([]).lower()
        self.assertIn("webmasters.readonly", line)
        self.assertIn("verified owner", line)

    def test_the_unknown_scopes_message_says_re_minting_may_not_help(self):
        line = credential.scope_line([]).lower()
        self.assertIn("no re-mint", line)


class TestWindowsCredentialAclHardening(unittest.TestCase):
    """The mint must survive a hardening step that cannot run.

    mint_adc.py writes the credential with POSIX mode bits, which on Windows
    are close to meaningless -- the file inherits SYSTEM and Administrators
    from the profile directory. icacls closes that, but it is a subprocess on
    the critical credential path, and the credential is already written and
    valid by the time it runs.

    So the only property that really matters here is: it can fail in every way
    available to it and the mint still succeeds. mint_adc.py is a script, not
    an importable module, so the function is loaded out of its source.
    """

    @classmethod
    def setUpClass(cls):
        import types
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "skills", "data-noodler", "scripts",
                            "mint_adc.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        cls.source = source
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "restrict_windows_acl")
        module = types.ModuleType("mint_acl")
        module.__dict__.update(os=os, subprocess=subprocess)
        exec(compile(ast.Module([fn], []), "mint_adc.py", "exec"),
             module.__dict__)
        # staticmethod: a bare function on a class attribute would be
        # bound as a method and receive self as its first argument.
        cls.restrict = staticmethod(module.restrict_windows_acl)

    def test_it_does_nothing_at_all_off_windows(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertIsNone(self.restrict("/tmp/whatever"))

    def test_a_missing_username_is_reported_not_raised(self):
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = self.restrict(r"C:\x\adc.json")
        self.assertIn("USERNAME", result)

    def test_icacls_being_absent_is_reported_not_raised(self):
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.dict(os.environ, {"USERNAME": "example"}), \
             mock.patch.object(subprocess, "run",
                               side_effect=FileNotFoundError("icacls")):
            result = self.restrict(r"C:\x\adc.json")
        self.assertIn("profile isolation", result)

    def test_a_nonzero_exit_is_reported_not_raised(self):
        done = subprocess.CompletedProcess([], 5, stdout="denied", stderr="")
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.dict(os.environ, {"USERNAME": "example"}), \
             mock.patch.object(subprocess, "run", return_value=done):
            result = self.restrict(r"C:\x\adc.json")
        self.assertIn("5", result)
        self.assertIn("profile isolation", result)

    def test_success_names_the_user_it_restricted_to(self):
        done = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.dict(os.environ, {"USERNAME": "example"}), \
             mock.patch.object(subprocess, "run", return_value=done) as run:
            result = self.restrict(r"C:\x\adc.json")
        self.assertIn("example", result)
        args = run.call_args[0][0]
        self.assertEqual(args[0], "icacls")
        self.assertIn("/inheritance:r", args)
        self.assertIn("example:F", args)

    def test_the_mint_reports_the_outcome_rather_than_assuming_it(self):
        # The printed line is the only signal a real Windows run will give,
        # since none of this can be exercised from here.
        self.assertIn("acl_note", self.source)
        self.assertIn('print(f"Permissions: {acl_note}")', self.source)


class TestOauthlibHintMatchesTheInstaller(unittest.TestCase):
    """Wall text is executable content -- this one assumed pipx everywhere."""

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "skills", "data-noodler", "scripts",
                            "mint_adc.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "oauthlib_install_hint")
        ns = {}
        exec(compile(ast.Module([fn], []), "mint_adc.py", "exec"), ns)
        cls.hint = staticmethod(ns["oauthlib_install_hint"])

    def test_a_pipx_install_gets_pipx_inject(self):
        h = self.hint("/Users/x/Library/Application Support/pipx/venvs/"
                      "analytics-mcp/bin/python")
        self.assertIn("pipx inject", h)

    def test_a_uv_install_never_gets_inject(self):
        # uv has no inject verb; the earlier drift was exactly this.
        h = self.hint("/Users/x/.local/share/uv/tools/analytics-mcp/bin/python")
        self.assertNotIn("inject", h)
        self.assertIn("--with google-auth-oauthlib", h)

    def test_a_windows_venv_gets_pip_on_its_own_interpreter(self):
        exe = r"C:\\Users\\example\\.config\\data-noodler\\venv\\Scripts\\python.exe"
        h = self.hint(exe)
        self.assertNotIn("pipx", h)
        self.assertNotIn("uv tool", h)
        self.assertIn("-m pip install google-auth-oauthlib", h)
        self.assertIn(exe, h, "must name the interpreter that is missing it")
