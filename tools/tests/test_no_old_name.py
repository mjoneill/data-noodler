"""#1998 and #1999: one name for everything that is ours.

The package folder was renamed from its working name to data-noodler/ (#1998),
then every product name followed (#1999). Michael, 2026-11-20: "we can't have
multiple different names for the same thing. Google names their piece...we
won't touch that." So analytics-mcp, Google's server, keeps its name, and
nothing tracked may use one of our old names, except where it names them to
retire them from an existing install.
"""

import os
import re
import subprocess
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Built from parts so this file does not match its own check.
OLD_FOLDER = "ga-mcp" + "-dist"
OLD_NAMES = [
    "ga-" + "companion", "ga_" + "companion", "com" + "panion",
    "ga-mcp" + "-setup", "ga-" + "analytics", "ga-" + "tools",
    "launch-" + "ga-",
    # google-analytics, except Google's own packages of that name.
    r"google-" + r"analytics(?!-(?:admin|data))",
    # #1999 slice 2: the install home, its env vars and the sign-in files.
    "ga-" + "mcp", "(?-i:GA_" + "MCP_)", r"(?-i:\bGA_" + r"HOME\b)",
    "adc-ga-" + "personal",
]

# The only places an old name may appear: the code that retires it from an
# existing install, the tests of that code, and the history notes beside them.
RETIREMENT = {
    "data-noodler/installer/install.py",
    "data-noodler/installer/register.py",
    "data-noodler/installer/copy_skills.py",
    "data-noodler/skills/data-noodler-setup/SKILL.md",
    "data-noodler/INSTALL.md",
    "data-noodler/tests/test_one_name.py",
    "data-noodler/tests/test_install_payload.py",
    "data-noodler/tests/test_upgrade.py",
    "data-noodler/tests/test_register.py",
    # slice 2: finding and moving an install whose home has the old name.
    "data-noodler/installer/home.py",
    "data-noodler/installer/migrate_home.py",
    "data-noodler/installer/bootstrap_config.py",
    "data-noodler/installer/probe.py",
    "data-noodler/server/config.py",
    "data-noodler/server/sessions.py",
    "data-noodler/marketplace/plugins/data-noodler/.mcp.json",
    "data-noodler/marketplace/plugins/data-noodler/skills/data-noodler/scripts/ga_config.py",
    "data-noodler/tests/test_home_migration.py",
    "data-noodler/tests/test_bootstrap_config.py",
    "data-noodler/tests/test_config.py",
    "data-noodler/tests/test_plugin_manifests.py",
    "tools/personal_guard.py",
    "tools/leak_guard.py",
    ".gitignore",
    "data-noodler/.gitignore",
    "tools/tests/test_no_old_name.py",  # this check names what it forbids
}


def _grep(pattern):
    r = subprocess.run(["git", "grep", "-n", "-I", "-P", pattern], cwd=TOP,
                       capture_output=True, text=True)
    # 0 = matches, 1 = no matches. Anything else means the search did not run,
    # and an empty result from a search that did not run proves nothing (#2014).
    if r.returncode not in (0, 1):
        raise RuntimeError("git grep failed (exit %d) for %r: %s"
                           % (r.returncode, pattern, r.stderr.strip()[:200]))
    return [line for line in r.stdout.splitlines() if line]


def _ls_files(*args):
    r = subprocess.run(["git", "ls-files", *args], cwd=TOP, capture_output=True,
                       text=True)
    # A failed ls-files prints nothing, and an empty list of tracked paths
    # would pass every check below (#2015).
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed (exit %d): %s"
                           % (r.returncode, r.stderr.strip()[:200]))
    return r.stdout.splitlines()


class TestTheOldNamesAreGone(unittest.TestCase):
    def test_a_grep_that_errors_is_a_failure_not_a_clean_result(self):
        # An unbalanced pattern makes git grep exit 128 with no output. Read
        # as "no matches", a broken grep would report every old name gone.
        with self.assertRaises(RuntimeError):
            _grep("(")

    def test_a_path_listing_that_errors_is_a_failure_not_an_empty_tree(self):
        # An unknown option makes git ls-files exit 129 with no output.
        with self.assertRaises(RuntimeError):
            _ls_files("--no-such-option")

    def test_the_package_folder_is_data_noodler(self):
        self.assertTrue(os.path.isfile(os.path.join(TOP, "data-noodler", "START-HERE.md")))
        self.assertFalse(os.path.exists(os.path.join(TOP, OLD_FOLDER)))

    def test_no_tracked_file_names_the_old_folder(self):
        self.assertEqual(_grep(re.escape(OLD_FOLDER)), [])

    def test_old_product_names_appear_only_where_they_are_retired(self):
        stray = []
        for pattern in OLD_NAMES:
            for line in _grep("(?i)" + pattern):
                path = line.split(":", 1)[0]
                if path not in RETIREMENT:
                    stray.append(line[:160])
        self.assertEqual(stray, [], "an old name outside the retirement code:\n"
                         + "\n".join(stray))

    def test_no_tracked_path_uses_an_old_name(self):
        stray = [p for p in _ls_files()
                 if any(re.search("(?i)" + n, p) for n in OLD_NAMES
                        if not n.startswith("(?-i"))]
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
