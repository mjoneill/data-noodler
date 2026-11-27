"""Making the confirming question answerable.

"Did you mean properties/324234234?" cannot be answered by a strategist.
"15,598 sessions on admissions.example.edu" can be answered by anyone.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import enrich

CANDIDATE = {"property_id": "314159265",
             "property_name": "admissions.example.edu",
             "account_name": "Admissions"}


def _runner(sessions_value, hostnames):
    """Stand-in for ga_export.run covering both calls enrichment makes."""
    def run(property_id, start_date, end_date, metrics, dimensions, **kw):
        if dimensions:
            return (["hostName", "sessions"],
                    [[h, "1"] for h in hostnames], {})
        return (["sessions"], [[str(sessions_value)]], {})
    return run


class TestCandidateFacts(unittest.TestCase):
    def test_reports_sessions_and_hostnames(self):
        facts = enrich.candidate_facts(
            "314159265", runner=_runner(15598, ["admissions.example.edu"]))
        self.assertEqual(facts["sessions"], 15598)
        self.assertEqual(facts["hostnames"], ["admissions.example.edu"])
        self.assertIsNone(facts["error"])

    def test_zero_sessions_is_reported_not_treated_as_missing(self):
        facts = enrich.candidate_facts("1", runner=_runner(0, []))
        self.assertEqual(facts["sessions"], 0)

    def test_multiple_hostnames_are_all_returned(self):
        facts = enrich.candidate_facts(
            "1", runner=_runner(9, ["a.example.edu", "b.example.edu"]))
        self.assertEqual(facts["hostnames"], ["a.example.edu", "b.example.edu"])

    def test_an_api_failure_is_reported_not_raised(self):
        def boom(*a, **k):
            raise RuntimeError("permission denied")
        facts = enrich.candidate_facts("1", runner=boom)
        self.assertIsNone(facts["sessions"])
        self.assertEqual(facts["hostnames"], [])
        self.assertIn("permission denied", facts["error"])

    def test_a_messageless_exception_still_produces_a_nonempty_error(self):
        def boom(*a, **k):
            raise RuntimeError()
        facts = enrich.candidate_facts("1", runner=boom)
        self.assertIsNone(facts["sessions"])
        self.assertTrue(facts["error"])
        self.assertIn("RuntimeError", facts["error"])


class TestDescribe(unittest.TestCase):
    def test_leads_with_the_name_and_recognizable_numbers(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 15598, "hostnames": ["admissions.example.edu"],
            "error": None})
        self.assertIn("admissions.example.edu", line)
        self.assertIn("15,598", line)
        self.assertLess(line.index("15,598"), line.index("314159265"))

    def test_names_the_property_id_but_not_first(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 1, "hostnames": [], "error": None})
        self.assertIn("314159265", line)
        self.assertTrue(line.startswith("admissions.example.edu"))

    def test_a_dormant_property_says_so_plainly(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 0, "hostnames": [], "error": None})
        self.assertIn("no traffic", line.lower())

    def test_multiple_hostnames_are_flagged_for_the_agent_to_raise(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 100,
            "hostnames": ["a.example.edu", "b.example.edu", "c.example.edu"],
            "error": None})
        self.assertIn("3 hostnames", line)

    def test_a_full_page_of_hostnames_says_or_more_not_an_exact_count(self):
        hosts = [f"h{i}.example.edu" for i in range(enrich.HOSTNAME_LIMIT)]
        line = enrich.describe(CANDIDATE, {
            "sessions": 100, "hostnames": hosts, "error": None})
        self.assertIn("10 or more hostnames", line)

    def test_a_partial_page_of_hostnames_reports_the_exact_count(self):
        hosts = ["a.example.edu", "b.example.edu", "c.example.edu", "d.example.edu"]
        line = enrich.describe(CANDIDATE, {
            "sessions": 100, "hostnames": hosts, "error": None})
        self.assertIn("4 hostnames", line)
        self.assertNotIn("or more", line)

    def test_exactly_two_hostnames_have_no_trailing_ellipsis(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 100, "hostnames": ["a.example.edu", "b.example.edu"],
            "error": None})
        self.assertNotIn("…", line)

    def test_more_than_three_hostnames_get_a_trailing_ellipsis(self):
        hosts = ["a.example.edu", "b.example.edu", "c.example.edu", "d.example.edu",
                 "e.example.edu"]
        line = enrich.describe(CANDIDATE, {
            "sessions": 100, "hostnames": hosts, "error": None})
        self.assertIn("…", line)

    def test_an_error_is_surfaced_rather_than_hidden(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": None, "hostnames": [], "error": "permission denied"})
        self.assertIn("permission denied", line)

    def test_a_messageless_error_is_reported_not_rendered_as_no_traffic(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": None, "hostnames": [], "error": ""})
        self.assertNotIn("no traffic", line.lower())

    def test_a_genuinely_dormant_property_still_says_no_traffic(self):
        line = enrich.describe(CANDIDATE, {
            "sessions": 0, "hostnames": [], "error": None})
        self.assertIn("no traffic", line.lower())

    def test_incomplete_snapshot_row_does_not_leak_none(self):
        candidate = {"property_id": None,
                     "property_name": "admissions.example.edu",
                     "account_name": "Admissions"}
        line = enrich.describe(candidate, {
            "sessions": 15598, "hostnames": ["admissions.example.edu"],
            "error": None})
        self.assertNotIn("None", line)
        self.assertIn("admissions.example.edu", line)
        self.assertIn("rebuild", line.lower())
        self.assertIn("refresh_property_snapshot", line)


if __name__ == "__main__":
    unittest.main()
