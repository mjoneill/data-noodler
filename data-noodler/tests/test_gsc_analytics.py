"""Search analytics: pagination, data_state, and the path column.

data_state belongs in the receipt because it changes the numbers materially.
"final" excludes the most recent two to three days; "all" includes fresh but
incomplete data that will change under you.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "companion"))

import gsc

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class _PagingSession:
    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        payload = self._pages.pop(0) if self._pages else {"rows": []}

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return payload
        return R()


def _fixture():
    with open(os.path.join(FIXTURES, "gsc_search_analytics.json")) as f:
        return json.load(f)


def _page(n, start=0):
    return {"rows": [
        {"keys": [f"2026-08-{(start + i) % 28 + 1:02d}", "https://x/p"],
         "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1.0}
        for i in range(n)]}


class TestColumnsAndRows(unittest.TestCase):
    def test_columns_are_dimensions_then_metrics_then_path(self):
        cols, _, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07",
            ["date", "page"], session=_PagingSession([_fixture()]))
        self.assertEqual(
            cols, ["date", "page", "clicks", "impressions", "ctr",
                   "position", "page_path"])

    def test_page_path_is_split_out_so_a_later_join_is_a_lookup(self):
        _, rows, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07",
            ["date", "page"], session=_PagingSession([_fixture()]))
        self.assertEqual(rows[0][-1], "/explore/law-school")

    def test_page_path_is_empty_when_page_is_not_a_dimension(self):
        payload = {"rows": [{"keys": ["2026-08-06"], "clicks": 1,
                             "impressions": 2, "ctr": 0.5, "position": 1.0}]}
        _, rows, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session=_PagingSession([payload]))
        self.assertEqual(rows[0][-1], "")

    def test_a_short_keys_row_does_not_raise_and_path_is_empty(self):
        """The API is documented never to short a row, but if it did, an
        IndexError would lose the entire export for one bad row."""
        payload = {"rows": [{"keys": ["2026-08-06"], "clicks": 1,
                             "impressions": 2, "ctr": 0.5, "position": 1.0}]}
        _, rows, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07",
            ["date", "page"], session=_PagingSession([payload]))
        self.assertEqual(rows[0][-1], "")

    def test_null_metric_renders_as_empty_cell_not_the_string_none(self):
        payload = {"rows": [{"keys": ["2026-08-06"], "clicks": None,
                             "impressions": 2, "ctr": 0.5, "position": 1.0}]}
        _, rows, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session=_PagingSession([payload]))
        clicks_cell = rows[0][1]
        self.assertEqual(clicks_cell, "")
        self.assertNotEqual(clicks_cell, "None")


class TestPagination(unittest.TestCase):
    def test_a_short_page_ends_pagination(self):
        s = _PagingSession([_page(3)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session=s)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(meta["rows_returned"], 3)

    def test_a_full_page_triggers_another_request(self):
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(2)])
        _, rows, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session=s)
        self.assertEqual(len(rows), gsc.PAGE_SIZE + 2)
        self.assertEqual(len(s.calls), 2)

    def test_the_second_request_advances_start_row(self):
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(1)])
        gsc.search_analytics("sc-domain:example.edu", "2026-08-06",
                             "2026-08-07", ["date"], session=s)
        self.assertEqual(s.calls[1][2]["json"]["startRow"], gsc.PAGE_SIZE)

    def test_row_limit_stops_early_and_is_recorded(self):
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(gsc.PAGE_SIZE)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=10, session=s)
        self.assertEqual(len(rows), 10)
        self.assertTrue(meta["row_limit_hit"])

    def test_row_limit_matching_a_complete_short_page_is_not_truncated(self):
        """A result whose true size equals row_limit exactly is complete.

        Reporting it as truncated would tell a reader data is missing when it
        is not. This must fail against the naive `len(rows) >= row_limit`
        check, which sets limit_hit True the instant the count is reached
        regardless of whether anything is actually left unconsumed.
        """
        s = _PagingSession([_page(3)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=3, session=s)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(s.calls), 1)
        self.assertFalse(meta["row_limit_hit"])

    def test_row_limit_exactly_page_size_with_no_more_data_is_not_truncated(self):
        """The boundary the original page-fullness inference could not
        handle: a full page that happens to be the last one. Only actually
        seeing one row past row_limit proves truncation, so this page (an
        empty second page) must be fetched and must NOT flip limit_hit."""
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(0)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=gsc.PAGE_SIZE, session=s)
        self.assertEqual(len(rows), gsc.PAGE_SIZE)
        self.assertFalse(meta["row_limit_hit"])

    def test_row_limit_exactly_page_size_with_more_data_is_truncated(self):
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(gsc.PAGE_SIZE)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=gsc.PAGE_SIZE, session=s)
        self.assertEqual(len(rows), gsc.PAGE_SIZE)
        self.assertTrue(meta["row_limit_hit"])

    def test_rows_returned_reflects_the_trimmed_count(self):
        s = _PagingSession([_page(gsc.PAGE_SIZE), _page(gsc.PAGE_SIZE)])
        _, rows, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=10, session=s)
        self.assertEqual(meta["rows_returned"], len(rows))
        self.assertEqual(meta["rows_returned"], 10)


class TestRequestShape(unittest.TestCase):
    def test_data_state_defaults_to_final_and_is_recorded(self):
        s = _PagingSession([_fixture()])
        _, _, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session=s)
        self.assertEqual(s.calls[0][2]["json"]["dataState"], "final")
        self.assertEqual(meta["data_state"], "final")

    def test_data_state_all_is_passed_through_and_recorded(self):
        s = _PagingSession([_fixture()])
        _, _, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            data_state="all", session=s)
        self.assertEqual(s.calls[0][2]["json"]["dataState"], "all")
        self.assertEqual(meta["data_state"], "all")

    def test_page_contains_becomes_a_dimension_filter(self):
        s = _PagingSession([_fixture()])
        gsc.search_analytics("sc-domain:example.edu", "2026-08-06",
                             "2026-08-07", ["date"],
                             page_contains="/explore/", session=s)
        groups = s.calls[0][2]["json"]["dimensionFilterGroups"]
        f = groups[0]["filters"][0]
        self.assertEqual(f["dimension"], "page")
        self.assertEqual(f["operator"], "contains")
        self.assertEqual(f["expression"], "/explore/")

    def test_the_site_url_is_percent_encoded_in_the_path(self):
        s = _PagingSession([_fixture()])
        gsc.search_analytics("sc-domain:example.edu", "2026-08-06",
                             "2026-08-07", ["date"], session=s)
        self.assertIn("sc-domain%3Aexample.edu", s.calls[0][1])


class TestGscSearchAnalyticsToolClampsRowLimit(unittest.TestCase):
    """gsc_search_analytics's own default of row_limit=0 already means
    unlimited; a non-positive value must mean the same thing. The tool
    wrapper used to compute `row_limit or None`, which is truthy for any
    negative number, so row_limit=-5 reached gsc.search_analytics as -5,
    which turns into a negative rowLimit in the request body and earns a
    400 from Google instead of the unlimited query a caller passing an
    out-of-range value almost certainly wanted.
    """

    def setUp(self):
        import tempfile

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "companion"))
        import ga_companion
        self.mod = ga_companion
        self.d = tempfile.mkdtemp()
        # Exports only go to approved places (#156); approve this temp folder.
        from unittest import mock as _mock
        _p = _mock.patch.object(ga_companion, "_places", return_value=(
            {"sessions": self.d}, "test: sessions folder only"))
        _p.start()
        self.addCleanup(_p.stop)
        self.received = {}

        def fake_search_analytics(site_url, start_date, end_date, dimensions,
                                  page_contains=None, data_state="final",
                                  row_limit=None, session=None, **kw):
            self.received["row_limit"] = row_limit
            self.received.update(kw)
            columns = ["date", "clicks", "impressions", "ctr", "position",
                      "page_path"]
            rows = [["2026-08-06", "1", "2", "0.5", "1.0", ""]]
            meta = {"source": "gsc_search_analytics", "site_url": site_url,
                    "site_type": "domain", "dimensions": list(dimensions),
                    "date_range": {"start": start_date, "end": end_date},
                    "data_state": data_state, "page_contains": page_contains,
                    "rows_returned": 1, "row_limit_hit": False,
                    "sampled": False, "stopped_reason": None}
            return columns, rows, meta

        self._real_search_analytics = ga_companion.gsc.search_analytics
        ga_companion.gsc.search_analytics = fake_search_analytics

    def tearDown(self):
        self.mod.gsc.search_analytics = self._real_search_analytics

    def _call(self, row_limit, name):
        out = os.path.join(self.d, name)
        self.mod.gsc_search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            row_limit=row_limit, out_file=out)

    def test_a_negative_row_limit_is_clamped_to_unlimited(self):
        self._call(-5, "out1.csv")
        self.assertIsNone(self.received["row_limit"])

    def test_zero_row_limit_stays_unlimited(self):
        self._call(0, "out2.csv")
        self.assertIsNone(self.received["row_limit"])

    def test_a_positive_row_limit_passes_through_unchanged(self):
        self._call(10, "out3.csv")
        self.assertEqual(self.received["row_limit"], 10)

    def test_the_new_options_reach_the_query(self):
        flt = [{"dimension": "query", "operator": "contains",
                "expression": "apply"}]
        self.mod.gsc_search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            out_file=os.path.join(self.d, "out4.csv"), search_type="discover",
            filters=flt, aggregation_type="byProperty")
        self.assertEqual(self.received["search_type"], "discover")
        self.assertEqual(self.received["filters"], flt)
        self.assertEqual(self.received["aggregation_type"], "byProperty")

    def test_a_discover_export_is_not_named_like_a_web_one(self):
        out = self.mod.gsc_search_analytics(
            "sc-domain:example.edu", "2026-08-06", "2026-08-07", ["date"],
            session_dir=self.d, search_type="discover")
        self.assertIn("performance-discover", out)


class TestAggregationNote(unittest.TestCase):
    """Issue #3: Search Console totals depend on which dimensions were asked for.

    Same property, same twelve months, data_state final: grouped by [date] the
    impressions summed to 126,431; grouped by [page] they summed to 128,326. A
    field agent nearly computed one page's share as a by-page number over a
    by-date total, which mixes two aggregations. It is documented Google
    behaviour, and nothing in the receipt said so at the moment it mattered.

    The effect runs BOTH ways, so the note has to say which one applies:
    grouping by page counts one search once per page it showed, so totals can
    EXCEED the site total; grouping by query drops anonymised queries, so
    totals FALL SHORT of it.
    """

    def _meta(self, dims):
        _, _, meta = gsc.search_analytics(
            "sc-domain:example.edu", "2025-09-29", "2026-09-28", dims,
            session=_PagingSession([{"rows": []}]))
        return meta

    def test_the_key_is_always_present(self):
        # Same convention as stopped_reason: a key that only appears when
        # something applies is ambiguous when it is missing.
        self.assertIn("aggregation_note", self._meta(["date"]))

    def test_a_date_only_export_needs_no_note(self):
        self.assertIsNone(self._meta(["date"])["aggregation_note"])

    def test_country_and_device_need_no_note_either(self):
        self.assertIsNone(self._meta(["country", "device"])["aggregation_note"])

    def test_by_page_says_totals_can_exceed_the_site_total(self):
        note = self._meta(["page"])["aggregation_note"]
        self.assertIsNotNone(note)
        self.assertIn("page", note)
        self.assertIn("exceed", note.lower())

    def test_by_query_says_anonymised_queries_are_missing(self):
        note = self._meta(["query"])["aggregation_note"]
        self.assertIsNotNone(note)
        self.assertIn("anonymi", note.lower())
        self.assertIn("short", note.lower())

    def test_both_effects_are_named_when_both_dimensions_are_present(self):
        note = self._meta(["page", "query"])["aggregation_note"].lower()
        self.assertIn("exceed", note)
        self.assertIn("anonymi", note)

    def test_the_note_says_how_to_get_the_right_denominator(self):
        # Warning someone off a number is only half the job; say what to use.
        note = self._meta(["page"])["aggregation_note"]
        self.assertIn("date", note)


class TestTheRestOfTheSearchAnalyticsApi(unittest.TestCase):
    """Card #130: what the API offers that this tool did not.

    Found 2026-10-07 while checking whether Search Console's AI reports were
    reachable. The tool never set `type`, so every query was plain web search
    -- Discover, News, image and video were out of reach, and Discover is half
    of what Google's AI report covers. It filtered only page-contains. It did
    not offer aggregationType at all, which is the API's own answer to the
    by-page vs by-date mismatch in field report #3.

    Every refusal below happens BEFORE the request leaves, with the allowed
    values in the message: an agent handed a Google 400 has to guess, and an
    agent that guesses at a wall improvises.
    """

    SITE = "sc-domain:example.edu"

    def _run(self, dims=("date",), **kw):
        session = _PagingSession([{"rows": []}])
        _, _, meta = gsc.search_analytics(self.SITE, "2026-09-01", "2026-09-30",
                                          list(dims), session=session, **kw)
        return session.calls[0][2]["json"], meta

    def _refused(self, dims=("date",), **kw):
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.search_analytics(self.SITE, "2026-09-01", "2026-09-30",
                                 list(dims), session=_PagingSession([]), **kw)
        return str(ctx.exception)

    # --- search type -------------------------------------------------------

    def test_web_is_sent_explicitly_by_default(self):
        body, meta = self._run()
        self.assertEqual(body["type"], "web")
        self.assertEqual(meta["search_type"], "web")

    def test_discover_and_the_other_types_reach_the_api(self):
        for t in ("discover", "news", "googleNews", "image", "video"):
            body, meta = self._run(search_type=t)
            self.assertEqual(body["type"], t)
            self.assertEqual(meta["search_type"], t)

    def test_an_unknown_search_type_is_refused_with_the_choices(self):
        msg = self._refused(search_type="ai_overviews")
        self.assertIn("discover", msg)
        self.assertIn("not in the API", msg,
                      "the commonest wrong guess is an AI type; say plainly "
                      "that Google has not exposed one")

    # --- dimensions --------------------------------------------------------

    def test_search_appearance_is_a_supported_dimension(self):
        body, _ = self._run(dims=("searchAppearance",))
        self.assertEqual(body["dimensions"], ["searchAppearance"])

    def test_a_ga_dimension_name_is_refused_with_the_gsc_equivalent(self):
        # pagePath is GA4's word. An agent working both sources will reach
        # for it, and Google's answer is an unexplained 400.
        msg = self._refused(dims=("pagePath",))
        self.assertIn("page", msg)
        self.assertIn("searchAppearance", msg)

    def test_hour_requires_hourly_all(self):
        msg = self._refused(dims=("hour",))
        self.assertIn("hourly_all", msg)
        body, _ = self._run(dims=("hour",), data_state="hourly_all")
        self.assertEqual(body["dataState"], "hourly_all")

    def test_an_unknown_data_state_is_refused(self):
        self.assertIn("final", self._refused(data_state="fresh"))

    # --- filters -----------------------------------------------------------

    def test_a_query_filter_reaches_the_api(self):
        body, meta = self._run(filters=[{"dimension": "query", "operator":
                                         "contains", "expression": "admissions"}])
        f = body["dimensionFilterGroups"][0]["filters"]
        self.assertIn({"dimension": "query", "operator": "contains",
                       "expression": "admissions"}, f)
        self.assertEqual(meta["filters"][0]["expression"], "admissions")

    def test_page_contains_still_works_and_joins_the_same_group(self):
        body, _ = self._run(page_contains="/apply",
                            filters=[{"dimension": "country",
                                      "expression": "usa"}])
        groups = body["dimensionFilterGroups"]
        self.assertEqual(len(groups), 1, "two groups would be OR'd, not AND'd")
        dims = sorted(f["dimension"] for f in groups[0]["filters"])
        self.assertEqual(dims, ["country", "page"])

    def test_operator_defaults_to_equals(self):
        body, _ = self._run(filters=[{"dimension": "device",
                                      "expression": "MOBILE"}])
        self.assertEqual(
            body["dimensionFilterGroups"][0]["filters"][0]["operator"], "equals")

    def test_regex_operators_are_accepted(self):
        for op in ("includingRegex", "excludingRegex"):
            body, _ = self._run(filters=[{"dimension": "query", "operator": op,
                                          "expression": "^apply"}])
            self.assertEqual(
                body["dimensionFilterGroups"][0]["filters"][0]["operator"], op)

    def test_an_unfilterable_dimension_is_refused(self):
        msg = self._refused(filters=[{"dimension": "date",
                                      "expression": "2026-09-01"}])
        self.assertIn("query", msg)

    def test_an_unknown_operator_is_refused_with_the_choices(self):
        msg = self._refused(filters=[{"dimension": "query", "operator": "like",
                                      "expression": "x"}])
        self.assertIn("includingRegex", msg)

    def test_a_filter_with_no_expression_is_refused(self):
        self.assertIn("expression", self._refused(
            filters=[{"dimension": "query", "operator": "contains"}]))

    # --- aggregation -------------------------------------------------------

    def test_by_property_reaches_the_api(self):
        body, meta = self._run(aggregation_type="byProperty")
        self.assertEqual(body["aggregationType"], "byProperty")
        self.assertEqual(meta["aggregation_type"], "byProperty")

    def test_by_property_with_a_page_dimension_is_refused_and_explained(self):
        msg = self._refused(dims=("page",), aggregation_type="byProperty")
        self.assertIn("page", msg.lower())
        self.assertIn("byPage", msg)

    def test_by_property_with_a_page_filter_is_refused_too(self):
        self._refused(page_contains="/apply", aggregation_type="byProperty")
        self._refused(aggregation_type="byProperty",
                      filters=[{"dimension": "page", "expression": "x"}])

    def test_an_unknown_aggregation_type_is_refused(self):
        self.assertIn("byProperty", self._refused(aggregation_type="total"))

    def test_the_aggregation_note_now_offers_by_property(self):
        _, meta = self._run(dims=("query",))
        self.assertIn("byProperty", meta["aggregation_note"])


class TestDiscoverAndGoogleNewsHaveNoQueries(unittest.TestCase):
    """Measured against the live API, 2026-10-07, on a domain property.

    For discover and googleNews Google answered 400 to: grouping by query
    ("Request for DISCOVER cannot be grouped by query"), filtering by query
    ("Filtering by query with type='DISCOVER' is illegal"), and byProperty
    ("'BY_PROPERTY' is not a valid aggregation type in the context of the
    request"). Page, country and date all worked. Refusing here says WHY --
    these feeds are not searches, so there is no query to report.
    """

    SITE = "sc-domain:example.edu"

    def _refused(self, dims=("date",), **kw):
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.search_analytics(self.SITE, "2026-09-01", "2026-09-30",
                                 list(dims), session=_PagingSession([]), **kw)
        return str(ctx.exception)

    def test_no_query_dimension(self):
        for t in ("discover", "googleNews"):
            self.assertIn("no query", self._refused(dims=("query",),
                                                    search_type=t))

    def test_no_query_filter(self):
        for t in ("discover", "googleNews"):
            self._refused(search_type=t, filters=[
                {"dimension": "query", "operator": "contains",
                 "expression": "x"}])

    def test_no_by_property(self):
        for t in ("discover", "googleNews"):
            self.assertIn("byPage", self._refused(
                search_type=t, aggregation_type="byProperty"))

    def test_pages_still_work(self):
        session = _PagingSession([{"rows": []}])
        gsc.search_analytics(self.SITE, "2026-09-01", "2026-09-30", ["page"],
                             session=session, search_type="discover")
        self.assertEqual(session.calls[0][2]["json"]["type"], "discover")
