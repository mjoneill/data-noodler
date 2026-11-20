"""#1998: the package folder was renamed from its working name to
data-noodler/ before strangers started installing. Nothing tracked may
send a reader or a script to the old folder."""

import os
import subprocess
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OLD = "ga-mcp" + "-dist"


class TestTheOldFolderNameIsGone(unittest.TestCase):
    def test_the_package_folder_is_data_noodler(self):
        self.assertTrue(os.path.isfile(os.path.join(TOP, "data-noodler", "START-HERE.md")))
        self.assertFalse(os.path.exists(os.path.join(TOP, OLD)))

    def test_no_tracked_file_names_the_old_folder(self):
        r = subprocess.run(["git", "grep", "-l", OLD], cwd=TOP, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "", "still names the old folder:\n" + r.stdout)


if __name__ == "__main__":
    unittest.main()
