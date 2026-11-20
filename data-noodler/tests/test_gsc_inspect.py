"""URL inspection: the fields that distinguish different problems.

coverageState is the actionable one. "Crawled - currently not indexed" and
"Discovered - currently not indexed" demand completely different responses,
and a binary indexed flag cannot tell them apart.
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import gsc

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class _SeqSession:
    """Returns queued payloads in order; raises the queued exception if one."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self._payloads.pop(0)
        if isinstance(item, Exception):
            raise item

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return item
        return R()


def _payload():
    with open(os.path.join(FIXTURES, "gsc_url_inspection.json")) as f:
        return json.load(f)


class TestInspectRow(unittest.TestCase):
    def test_row_matches_the_declared_column_order(self):
        row = gsc.inspect_row("https://example.edu/explore/law-school",
                              _payload())
        self.assertEqual(len(row), len(gsc.INSPECT_COLUMNS))

    def test_every_column_lands_in_its_declared_position(self):
        """The header comes from INSPECT_COLUMNS and the values from a
        hand-written list in inspect_row. Reorder one without the other and
        googleCanonical values appear under the userCanonical header --
        inverting the canonical-mismatch conclusion the guidance calls
        "usually the real story", with every cell still looking plausible.
        Only a positional assertion over the whole row catches that.
        """
        row = gsc.inspect_row("https://example.edu/explore/law-school",
                              _payload())
        self.assertEqual(row, [
            "https://example.edu/explore/law-school",
            "PASS",
            "Submitted and indexed",
            "https://example.edu/explore/law-school",
            "https://example.edu/explore/law-school",
            "ALLOWED",
            "INDEXING_ALLOWED",
            "SUCCESSFUL",
            "2026-08-28T14:22:11Z",
            "MOBILE",
            "https://example.edu/sitemap.xml",
            "https://example.edu/explore",
            "https://search.google.com/search-console/inspect"
            "?resource_id=sc-domain%3Aexample.edu&id=abc",
            "", "", "",          # rich results: none on this page (#132)
        ])

    def test_a_reorder_of_one_side_only_is_visible_as_a_mismatch(self):
        # The fixture's two canonicals are identical, so the positional test
        # above cannot see them swapped. This one makes them distinct and
        # pins each to its own column.
        p = copy.deepcopy(_payload())
        status = p["inspectionResult"]["indexStatusResult"]
        status["googleCanonical"] = "https://example.edu/explore/law"
        status["userCanonical"] = "https://example.edu/explore/law-school"
        row = gsc.inspect_row("https://x", p)
        self.assertEqual(row[gsc.INSPECT_COLUMNS.index("googleCanonical")],
                         "https://example.edu/explore/law")
        self.assertEqual(row[gsc.INSPECT_COLUMNS.index("userCanonical")],
                         "https://example.edu/explore/law-school")

    def test_carries_the_actionable_coverage_state(self):
        row = gsc.inspect_row("https://x", _payload())
        self.assertIn("Submitted and indexed", row)

    def test_carries_the_inspection_link_for_a_human_to_verify(self):
        row = gsc.inspect_row("https://x", _payload())
        self.assertTrue(any("search-console/inspect" in str(v) for v in row))

    def test_lists_are_joined_not_stringified_as_python(self):
        row = gsc.inspect_row("https://x", _payload())
        joined = row[gsc.INSPECT_COLUMNS.index("sitemap")]
        self.assertEqual(joined, "https://example.edu/sitemap.xml")
        self.assertNotIn("[", joined)

    def test_a_canonical_mismatch_is_visible_in_the_row(self):
        p = copy.deepcopy(_payload())
        p["inspectionResult"]["indexStatusResult"]["googleCanonical"] = \
            "https://example.edu/explore/law"
        row = gsc.inspect_row("https://x", p)
        g = row[gsc.INSPECT_COLUMNS.index("googleCanonical")]
        u = row[gsc.INSPECT_COLUMNS.index("userCanonical")]
        self.assertNotEqual(g, u)

    def test_missing_fields_become_empty_strings_not_none(self):
        p = {"inspectionResult": {"indexStatusResult": {}}}
        row = gsc.inspect_row("https://x", p)
        self.assertTrue(all(isinstance(v, str) for v in row))


class TestInspectUrls(unittest.TestCase):
    def test_one_request_per_url(self):
        s = _SeqSession([_payload(), _payload()])
        cols, rows, meta = gsc.inspect_urls(
            "sc-domain:example.edu", ["https://a", "https://b"], session=s)
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(meta["urls_requested"], 2)
        self.assertEqual(meta["rows_written"], 2)

    def test_it_posts_to_the_inspection_endpoint(self):
        s = _SeqSession([_payload()])
        gsc.inspect_urls("sc-domain:example.edu", ["https://a"], session=s)
        method, url, _ = s.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/v1/urlInspection/index:inspect"))

    def test_a_failure_partway_records_where_it_stopped(self):
        s = _SeqSession([_payload(), gsc.GscError("quota exceeded")])
        cols, rows, meta = gsc.inspect_urls(
            "sc-domain:example.edu", ["https://a", "https://b"], session=s)
        self.assertEqual(meta["urls_requested"], 2)
        self.assertEqual(meta["rows_written"], 1)
        self.assertIn("quota", meta["stopped_reason"].lower())

    def test_a_complete_run_has_no_stopped_reason(self):
        s = _SeqSession([_payload()])
        _, _, meta = gsc.inspect_urls("sc-domain:example.edu", ["https://a"],
                                      session=s)
        self.assertIsNone(meta["stopped_reason"])

    def test_stopped_reason_is_present_even_on_a_complete_run(self):
        # Present-and-null, not absent. A key that only appears on failure
        # is ambiguous when missing: the reader cannot tell a clean run from
        # a sidecar written before the field existed.
        s = _SeqSession([_payload()])
        _, _, meta = gsc.inspect_urls("sc-domain:example.edu", ["https://a"],
                                      session=s)
        self.assertIn("stopped_reason", meta)

    def test_the_module_records_site_type_not_just_the_tool_layer(self):
        # site_type used to be attached in data_noodler, so a direct caller
        # got a sidecar with no record of what the site_url covers -- while
        # search_analytics recorded it here all along.
        s = _SeqSession([_payload()])
        _, _, meta = gsc.inspect_urls("sc-domain:example.edu", ["https://a"],
                                      session=s)
        self.assertEqual(meta["site_type"], "domain")

        s = _SeqSession([_payload()])
        _, _, meta = gsc.inspect_urls("https://example.edu/", ["https://a"],
                                      session=s)
        self.assertEqual(meta["site_type"], "url_prefix")

    def test_the_day_of_the_inspection_is_recorded_as_a_date_range(self):
        # An inspection is a point-in-time snapshot, so start == end. Under
        # the same key search_analytics uses, so both sidecars read alike.
        import datetime
        s = _SeqSession([_payload()])
        _, _, meta = gsc.inspect_urls("sc-domain:example.edu", ["https://a"],
                                      session=s,
                                      today=datetime.date(2026, 9, 3))
        self.assertEqual(meta["date_range"],
                         {"start": "2026-09-03", "end": "2026-09-03"})

    def test_both_sources_agree_on_the_keys_a_reader_looks_for(self):
        """Two sidecars from the same server describing the same site under
        different keys is how a reader concludes one of them is incomplete.
        """
        s = _SeqSession([_payload()])
        _, _, inspect_meta = gsc.inspect_urls(
            "sc-domain:example.edu", ["https://a"], session=s)

        class _Rows:
            status_code = 200
            text = ""

            def json(self):
                return {"rows": []}

        class _S:
            def request(self, *a, **kw):
                return _Rows()

        _, _, analytics_meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-09-02", ["date"],
            session=_S())

        for key in ("source", "site_url", "site_type", "date_range",
                    "sampled", "row_limit_hit", "stopped_reason"):
            with self.subTest(key=key):
                self.assertIn(key, inspect_meta)
                self.assertIn(key, analytics_meta)


class TestRichResults(unittest.TestCase):
    """Card #132. inspectionResult.richResultsResult was dropped, so "why did
    our rich snippets disappear" could not be answered. Shape as returned live
    on 2026-10-07 for a video page; issues sit under each item.
    """

    PAYLOAD = {"inspectionResult": {
        "indexStatusResult": {"verdict": "PASS"},
        "richResultsResult": {"verdict": "PARTIAL", "detectedItems": [
            {"richResultType": "Videos", "items": [
                {"name": "Field testing", "issues": [
                    {"issueMessage": "Missing field \"uploadDate\"",
                     "severity": "ERROR"}]}]},
            {"richResultType": "Breadcrumbs", "items": [{"name": "Unnamed"}]},
        ]}}}

    def _row(self, payload):
        return dict(zip(gsc.INSPECT_COLUMNS,
                        gsc.inspect_row("https://x/", payload)))

    def test_new_columns_are_appended_so_old_positions_hold(self):
        self.assertEqual(gsc.INSPECT_COLUMNS[-3:], [
            "richResultsVerdict", "richResultTypes", "richResultIssues"])
        self.assertEqual(gsc.INSPECT_COLUMNS[12], "inspectionResultLink")

    def test_verdict_types_and_issues_are_reported(self):
        row = self._row(self.PAYLOAD)
        self.assertEqual(row["richResultsVerdict"], "PARTIAL")
        self.assertEqual(row["richResultTypes"], "Videos, Breadcrumbs")
        self.assertEqual(row["richResultIssues"],
                         'Videos: Missing field "uploadDate" (ERROR)')

    def test_a_page_with_no_rich_results_is_blank_not_an_error(self):
        row = self._row({"inspectionResult": {"indexStatusResult": {}}})
        self.assertEqual((row["richResultsVerdict"], row["richResultTypes"],
                          row["richResultIssues"]), ("", "", ""))
