"""#2010: on Windows a project on another drive from the home folder must not
crash start_session. ntpath.commonpath raises "Paths don't have the same
drive" for C: and D:, and project_reason called it before any other check."""
import ntpath
import os
import posixpath
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import sessions


class AProjectOnAnotherDrive(unittest.TestCase):
    def test_another_drive_is_not_home_or_above(self):
        self.assertFalse(sessions._is_home_or_above(
            r"D:\work\site", r"C:\Users\you", pathmod=ntpath))

    def test_drive_letters_differing_only_in_case_are_the_same_drive(self):
        self.assertTrue(sessions._is_home_or_above(
            r"c:\Users", r"C:\Users\you", pathmod=ntpath))

    def test_the_drive_root_above_home_is_still_refused(self):
        self.assertTrue(sessions._is_home_or_above(
            "C:\\", r"C:\Users\you", pathmod=ntpath))

    def test_home_itself_and_its_parent_are_still_refused(self):
        self.assertTrue(sessions._is_home_or_above(
            r"C:\Users\you", r"C:\Users\you", pathmod=ntpath))
        self.assertTrue(sessions._is_home_or_above(
            r"C:\Users", r"C:\Users\you", pathmod=ntpath))

    def test_a_folder_inside_home_on_the_same_drive_is_fine(self):
        self.assertFalse(sessions._is_home_or_above(
            r"C:\Users\you\site", r"C:\Users\you", pathmod=ntpath))

    def test_posix_is_unchanged(self):
        self.assertTrue(sessions._is_home_or_above(
            "/Users", "/Users/you", pathmod=posixpath))
        self.assertFalse(sessions._is_home_or_above(
            "/Users/you/site", "/Users/you", pathmod=posixpath))


if __name__ == "__main__":
    unittest.main()
