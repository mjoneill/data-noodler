"""The leak guard's own controls: every rule is shown catching a planted bad
thing, and shown passing its harmless look-alike.

The planted values are assembled at run time ("GOC" + "SPX-"...), so this file
never contains a whole pattern itself and the guard can scan it like any
other tracked file.
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import leak_guard  # noqa: E402

# Planted values, built so no complete pattern appears in this file.
CLIENT_SECRET = "GOC" + "SPX-" + "q7Rk2LmN8vXc4TzP1wYh6JdF0sAe"
API_KEY = "AI" + "za" + "SyD3f8Kq2Lm9Np4Rs7Tv1Wx6Yz0Ab5Cd8E"
REFRESH = "1" + "//0" + "gH5kL9mN2pQ7rS4tU8vW1xY6zA3bC0dE"
PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END " + "PRIVATE KEY-----\n"
CLIENT_ID = "4071" + "93285516" + "-" + "k3j9vq2m8r1t7w4y6z0b5n8c2x4l9p3a" + ".apps.google" + "usercontent.com"
REAL_NAME = "pat" + "ricia"


def rules(files):
    return sorted({f.rule for f in leak_guard.scan_tree(files)})


class SensitiveFileNames(unittest.TestCase):
    def test_oauth_client_and_credential_files_are_refused_by_name(self):
        for path in ("data-noodler/my-data-noodler-client.json",
                     "anything/desktop-client.json",
                     "x/application_default_credentials.json",
                     "adc.json",
                     "x/data-noodler-credential.json",
                     "client_secret_12345.json",
                     "credentials.json",
                     "config.json",
                     "data-noodler/server/config.json"):
            with self.subTest(path=path):
                self.assertIn("sensitive-file", rules({path: "{}"}))

    def test_a_fixture_config_and_ordinary_json_pass(self):
        self.assertEqual(rules({"data-noodler/tests/fixtures/config.json": "{}",
                                "data-noodler/marketplace/plugins/p/.mcp.json": "{}",
                                "data-noodler/deployment.template.json": '{"maintainer": ""}'}), [])


class CredentialContent(unittest.TestCase):
    def test_a_renamed_credential_json_is_refused_by_its_content(self):
        body = '{"type": "authorized_user", "client_id": "x", "client_secret": "%s", "refresh_token": "%s"}' % (
            "s3cr3tValueThatIsLongEnough", "tokenValueThatIsLongEnough1")
        self.assertIn("credential-content", rules({"notes/backup-of-something.json": body}))

    def test_service_account_json_is_refused(self):
        body = '{"type": "service_account", "private_key": "%s"}' % "abcdefghijklmnopqrstuvwxyz"
        self.assertIn("credential-content", rules({"keys/whatever.json": body}))

    def test_google_secret_shapes_are_refused_in_any_file(self):
        for label, value in (("client secret", CLIENT_SECRET), ("api key", API_KEY),
                             ("refresh token", REFRESH), ("private key", PEM)):
            with self.subTest(label):
                self.assertIn("credential-content", rules({"docs/notes.md": "see " + value + " here\n"}))

    def test_placeholder_values_pass(self):
        body = ('{"type": "authorized_user", "client_id": "x", "client_secret": "x", '
                '"refresh_token": "x", "private_key": "<your key>"}')
        self.assertEqual(rules({"data-noodler/tests/test_credential.py": body}), [])

    def test_naming_the_keys_in_prose_passes(self):
        self.assertEqual(rules({"README.md": "The file holds a refresh_token and a client_secret.\n"}), [])


class OAuthClientIds(unittest.TestCase):
    def test_a_real_looking_client_id_is_refused(self):
        self.assertIn("oauth-client-id", rules({"docs/setup.md": "client: " + CLIENT_ID + "\n"}))

    def test_placeholder_client_ids_pass(self):
        for text in ("<client-id>.apps.googleusercontent.com",
                     "123456789012-example.apps.googleusercontent.com",
                     "000000000000-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.apps.googleusercontent.com"):
            with self.subTest(text=text):
                self.assertEqual(rules({"docs/setup.md": text + "\n"}), [])


class AnalyticsOutput(unittest.TestCase):
    def test_report_files_are_refused_outside_fixtures(self):
        for path in ("reports/traffic.csv", "out.xlsx", "summary.html", "_outputs/run-1/notes.txt",
                     "data-noodler/properties.csv"):
            with self.subTest(path=path):
                self.assertIn("analytics-output", rules({path: "a,b\n1,2\n"}))

    def test_fixture_data_passes(self):
        self.assertEqual(rules({"data-noodler/tests/fixtures/properties.csv": "a,b\n1,2\n"}), [])


class DeploymentProfile(unittest.TestCase):
    BLANK = '{"deployment_name": "", "maintainer": "", "maintainer_contact": "", "install_reports_to": ""}'

    def test_a_filled_profile_is_refused(self):
        filled = self.BLANK.replace('"maintainer": ""', '"maintainer": "Some Team"')
        self.assertIn("deployment-profile", rules({
            "data-noodler/deployment.json": filled,
            "data-noodler/deployment.template.json": self.BLANK}))

    def test_a_profile_without_its_template_is_refused(self):
        self.assertIn("deployment-profile", rules({"data-noodler/deployment.json": self.BLANK}))

    def test_an_unreadable_profile_is_refused(self):
        self.assertIn("deployment-profile", rules({
            "data-noodler/deployment.json": "{not json",
            "data-noodler/deployment.template.json": self.BLANK}))

    def test_a_blank_profile_beside_its_template_passes(self):
        self.assertEqual(rules({"data-noodler/deployment.json": self.BLANK,
                                "data-noodler/deployment.template.json": self.BLANK}), [])


class HomePaths(unittest.TestCase):
    def test_a_real_home_folder_is_refused(self):
        for text in ("/Users/" + REAL_NAME + "/Library",
                     "C:\\Users\\" + REAL_NAME + "\\AppData",
                     "C:\\\\Users\\\\" + REAL_NAME + "\\\\AppData",
                     "c:\\users\\" + REAL_NAME.upper() + "\\.SSH",   # Windows ignores case
                     "/home/" + REAL_NAME + "/.config"):
            with self.subTest(text=text):
                self.assertIn("home-path", rules({"docs/notes.md": text + "\n"}))

    def test_placeholder_home_folders_pass(self):
        for text in ("/Users/x/.config/data-noodler", "/Users/example", "/Users/Jane/Documents", "/Users/a",
                     "/Users/you", "C:\\Users\\example\\AppData", "C:\\\\Users\\\\x/.config",
                     "/Users/<you>/Library", "/Users/$USER", "C:\\Users\\%USERNAME%", "/Users/",
                     "c:\\users\\EXAMPLE\\.SSH",
                     "C:\\Users\\", "/home/x"):
            with self.subTest(text=text):
                self.assertEqual(rules({"docs/notes.md": text + "\n"}), [])


class Reporting(unittest.TestCase):
    """A CI log may become public, so a finding names the rule and the place, never the value."""

    def test_no_report_line_repeats_the_value_it_found(self):
        planted = {"a.md": CLIENT_SECRET, "b.md": API_KEY, "c.md": REFRESH, "d.md": CLIENT_ID,
                   "e.md": "/Users/" + REAL_NAME + "/x"}
        findings = leak_guard.scan_tree(planted)
        self.assertEqual(len({f.path for f in findings}), len(planted))
        report = "\n".join(leak_guard.format_finding(f) for f in findings)
        for value in (CLIENT_SECRET, API_KEY, REFRESH, CLIENT_ID, REAL_NAME):
            self.assertNotIn(value, report)
        self.assertIn("d.md:1", report)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


class CommandLine(unittest.TestCase):
    def run_guard(self, root):
        return subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "leak_guard.py"), "--root", root],
                              capture_output=True, text=True)

    def test_this_repository_is_clean(self):
        r = self.run_guard(REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_planted_file_in_a_git_tree_fails_the_run_and_names_the_rule(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            with open(os.path.join(d, "README.md"), "w") as f:
                f.write("clean\n")
            # a credential renamed to something innocent, committed with -f past any ignore file
            with open(os.path.join(d, "settings-backup.json"), "w") as f:
                f.write('{"type": "authorized_user", "refresh_token": "%s"}' % REFRESH)
            git(d, "add", "-f", ".")
            r = self.run_guard(d)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("credential-content", r.stdout)
            self.assertIn("settings-backup.json", r.stdout)
            self.assertNotIn(REFRESH, r.stdout + r.stderr)

    def test_only_tracked_files_are_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            with open(os.path.join(d, "README.md"), "w") as f:
                f.write("clean\n")
            with open(os.path.join(d, "untracked-report.csv"), "w") as f:
                f.write("a,b\n")
            git(d, "add", "README.md")
            r = self.run_guard(d)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
