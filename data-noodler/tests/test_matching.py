"""Property matching must separate exact from partial hits.

On an account where every subdomain is its own property, a substring like
"example.edu" matches almost everything while exactly one property is named
that. Reporting a number from the wrong property is the most likely way to be
confidently wrong, so the split is asserted here rather than trusted.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "companion"))

import matching

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "properties.csv")


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.rows = matching.load_rows(FIXTURE)

    def test_loads_all_fixture_rows(self):
        self.assertEqual(len(self.rows), 6)

    def test_exact_match_is_isolated_from_prefix_match(self):
        m = matching.match_properties(self.rows, "admissions.example.edu")
        self.assertEqual([r["property_id"] for r in m["exact"]], ["314159265"])
        # "... - GA4 archive" starts with the term but is not it
        self.assertEqual([r["property_id"] for r in m["near"]], ["111111111"])

    def test_exact_match_is_case_and_space_insensitive(self):
        m = matching.match_properties(self.rows, "  ADMISSIONS.EXAMPLE.EDU ")
        self.assertEqual([r["property_id"] for r in m["exact"]], ["314159265"])

    def test_subdomain_lands_in_partial_not_exact(self):
        m = matching.match_properties(self.rows, "admissions.example.edu")
        self.assertIn("222222222", [r["property_id"] for r in m["partial"]])

    def test_parent_domain_matches_one_exactly_but_many_partially(self):
        m = matching.match_properties(self.rows, "example.edu")
        self.assertEqual([r["property_id"] for r in m["exact"]], ["333333333"])
        self.assertGreaterEqual(len(m["partial"]), 3)

    def test_account_name_is_searchable(self):
        m = matching.match_properties(self.rows, "engineering")
        ids = [r["property_id"] for r in m["exact"] + m["near"] + m["partial"]]
        self.assertIn("444444444", ids)

    def test_no_match_returns_three_empty_buckets(self):
        m = matching.match_properties(self.rows, "nosuchdomain.example")
        self.assertEqual(m, {"exact": [], "near": [], "partial": []})

    def test_decisive_only_when_one_exact_and_nothing_near(self):
        self.assertTrue(matching.is_decisive(
            matching.match_properties(self.rows, "example.edu")))
        # admissions.example.edu has a near match, so it is not decisive
        self.assertFalse(matching.is_decisive(
            matching.match_properties(self.rows, "admissions.example.edu")))


class TestFormatting(unittest.TestCase):
    def setUp(self):
        self.rows = matching.load_rows(FIXTURE)

    def test_decisive_output_names_the_property_and_suppresses_the_list(self):
        m = matching.match_properties(self.rows, "example.edu")
        out = matching.format_matches("example.edu", m)
        self.assertIn("properties/333333333", out)
        self.assertIn("Unambiguous", out)
        # the 3 subdomains are counted, not enumerated
        self.assertNotIn("engineering.example.edu", out)

    def test_include_all_expands_the_suppressed_list(self):
        m = matching.match_properties(self.rows, "example.edu")
        out = matching.format_matches("example.edu", m, include_all=True)
        self.assertIn("engineering.example.edu", out)

    def test_ambiguous_output_warns_before_reporting_numbers(self):
        m = matching.match_properties(self.rows, "admissions.example.edu")
        out = matching.format_matches("admissions.example.edu", m)
        self.assertIn("AMBIGUOUS", out)
        self.assertIn("subdomains are usually separate properties", out)

    def test_no_match_output_suggests_a_stale_snapshot(self):
        m = matching.match_properties(self.rows, "nosuchdomain.example")
        out = matching.format_matches("nosuchdomain.example", m)
        self.assertIn("refresh_property_snapshot", out)


class TestShortRows(unittest.TestCase):
    """A row with fewer fields than the header must not raise.

    csv.DictReader fills the missing fields of a short row with None -- a
    truncated final line, a hand edit, a paste that lost a column. Rendering
    None against the id's width spec used to raise TypeError, which the
    companion's guard does not catch, so the user saw "unsupported format
    string passed to NoneType.__format__" instead of an instruction.
    """

    def _rows(self, csv_text):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "properties.csv")
        with open(path, "w") as f:
            f.write(csv_text)
        return matching.load_rows(path)

    def test_dictreader_really_does_produce_none_for_a_short_row(self):
        # Guards the premise: if this ever stops being None the tests below
        # would pass for the wrong reason.
        rows = self._rows("account_name,property_name,property_id\n"
                          "Admissions,admissions.example.edu\n")
        self.assertIsNone(rows[0]["property_id"])

    def test_missing_id_renders_a_placeholder_and_names_the_rebuild(self):
        rows = self._rows(
            "account_name,property_name,property_id\n"
            "Admissions,admissions.example.edu\n"
            "Admissions,admissions.example.edu - GA4 archive\n")
        m = matching.match_properties(rows, "admissions.example.edu")
        out = matching.format_matches("admissions.example.edu", m)
        self.assertIn(f"properties/{matching.INCOMPLETE_ID}", out)
        self.assertIn("property_id missing", out)
        self.assertIn("refresh_property_snapshot", out)

    def test_decisive_match_with_no_id_reports_the_rebuild_not_none(self):
        # The decisive branch prints the id without a width spec, so it never
        # raised -- it would have printed the literal "properties/None".
        rows = self._rows("account_name,property_name,property_id\n"
                          "Main,example.edu\n")
        m = matching.match_properties(rows, "example.edu")
        self.assertTrue(matching.is_decisive(m))
        out = matching.format_matches("example.edu", m)
        self.assertNotIn("properties/None", out)
        self.assertIn("refresh_property_snapshot", out)

    def test_a_blank_id_field_counts_as_missing(self):
        rows = self._rows("account_name,property_name,property_id\n"
                          "Main,example.edu,   \n")
        self.assertIsNone(matching.property_id(rows[0]))

    def test_complete_rows_are_unaffected(self):
        rows = matching.load_rows(FIXTURE)
        m = matching.match_properties(rows, "example.edu")
        out = matching.format_matches("example.edu", m, include_all=True)
        self.assertIn("properties/333333333", out)
        self.assertNotIn(matching.INCOMPLETE_ID, out)
