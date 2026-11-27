"""Turning a GA4 response into a file's worth of data, plus its provenance.

host_scope is the field that stops a confidently wrong report. A property
serving dozens of hostnames, exported with no host dimension and no host
filter, sums /about across every site into one row -- and the numbers look
entirely normal.
"""

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import ga_export

from google.analytics.data_v1beta.types import (
    Filter, FilterExpression, FilterExpressionList)


def _fake_response(dimension_headers, metric_headers, rows,
                   sampling_metadatas=()):
    """A stand-in shaped like RunReportResponse, without the API."""
    def hdr(name):
        return types.SimpleNamespace(name=name)

    def row(values):
        return types.SimpleNamespace(
            dimension_values=[types.SimpleNamespace(value=v)
                              for v in values[:len(dimension_headers)]],
            metric_values=[types.SimpleNamespace(value=v)
                           for v in values[len(dimension_headers):]])

    return types.SimpleNamespace(
        dimension_headers=[hdr(h) for h in dimension_headers],
        metric_headers=[hdr(h) for h in metric_headers],
        rows=[row(r) for r in rows],
        row_count=len(rows),
        metadata=types.SimpleNamespace(
            sampling_metadatas=list(sampling_metadatas)))


class _FakeClient:
    """Stands in for the client `run()` gets from upstream. No network.

    Honours offset and limit the way the real API does, so a paging loop sees
    realistic pages. page_cap models a server that returns fewer rows than were
    asked for -- GA4's default of 10,000 when no limit is sent is one such cap.
    """

    def __init__(self, response, page_cap=None):
        self._response = response
        self.page_cap = page_cap
        self.last_request = None
        self.requests = []

    def run_report(self, request):
        self.last_request = request
        self.requests.append((request.offset, request.limit))
        start = request.offset or 0
        n = request.limit or 10000          # GA4's own default when unset
        if self.page_cap:
            n = min(n, self.page_cap)
        page = types.SimpleNamespace(**vars(self._response))
        page.rows = list(self._response.rows)[start:start + n]
        return page


class TestRowsFromResponse(unittest.TestCase):
    def test_columns_are_dimensions_then_metrics(self):
        resp = _fake_response(["date", "pagePath"], ["screenPageViews"],
                              [["2026-08-06", "/apply", "412"]])
        cols, rows = ga_export.rows_from_response(resp)
        self.assertEqual(cols, ["date", "pagePath", "screenPageViews"])

    def test_every_row_is_flattened_in_order(self):
        resp = _fake_response(["date"], ["sessions"],
                              [["2026-08-06", "1"], ["2026-08-07", "2"]])
        _, rows = ga_export.rows_from_response(resp)
        self.assertEqual(rows, [["2026-08-06", "1"], ["2026-08-07", "2"]])

    def test_a_metric_only_report_has_no_dimension_columns(self):
        resp = _fake_response([], ["sessions"], [["15598"]])
        cols, rows = ga_export.rows_from_response(resp)
        self.assertEqual(cols, ["sessions"])
        self.assertEqual(rows, [["15598"]])

    def test_an_empty_response_yields_columns_and_no_rows(self):
        resp = _fake_response(["date"], ["sessions"], [])
        cols, rows = ga_export.rows_from_response(resp)
        self.assertEqual(cols, ["date", "sessions"])
        self.assertEqual(rows, [])


class TestSampling(unittest.TestCase):
    def test_absent_sampling_metadata_means_not_sampled(self):
        self.assertFalse(ga_export.was_sampled(
            _fake_response(["date"], ["sessions"], [], sampling_metadatas=())))

    def test_present_sampling_metadata_means_sampled(self):
        self.assertTrue(ga_export.was_sampled(
            _fake_response(["date"], ["sessions"], [],
                           sampling_metadatas=[object()])))


class TestHostScope(unittest.TestCase):
    def test_hostname_as_a_dimension_wins(self):
        self.assertEqual(
            ga_export.host_scope(["date", "hostName"], None,
                                 ["a.example.edu", "b.example.edu"]),
            "dimension")

    def test_one_hostname_is_single_host(self):
        self.assertEqual(
            ga_export.host_scope(["date"], None, ["admissions.example.edu"]),
            "single_host")

    def test_a_filter_mentioning_hostname_is_filtered(self):
        self.assertEqual(
            ga_export.host_scope(["date"], {"filter": {"fieldName": "hostName"}},
                                 ["a.example.edu", "b.example.edu"]),
            "filtered")

    def test_many_hostnames_with_nothing_scoping_them_is_mixed(self):
        self.assertEqual(
            ga_export.host_scope(["date", "pagePath"], None,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_filter_on_something_else_does_not_count_as_scoping(self):
        self.assertEqual(
            ga_export.host_scope(["date"], {"filter": {"fieldName": "pagePath"}},
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_unknown_hostnames_is_not_claimed_as_single_host(self):
        self.assertEqual(ga_export.host_scope(["date"], None, []),
                         "mixed_unscoped")

    def test_a_filter_value_that_merely_contains_hostname_text_is_not_filtered(self):
        # Real FilterExpression: filtering on pagePath for a value that
        # happens to spell "hostName" -- a substring test on str() would
        # wrongly call this host-scoped.
        real_filter = FilterExpression(filter=Filter(
            field_name="pagePath",
            string_filter=Filter.StringFilter(value="/hostName-report")))
        self.assertEqual(
            ga_export.host_scope(["date"], real_filter,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_dict_filter_value_that_merely_contains_hostname_text_is_not_filtered(self):
        dict_filter = {"filter": {"fieldName": "pagePath",
                                  "value": "/hostName-report"}}
        self.assertEqual(
            ga_export.host_scope(["date"], dict_filter,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_self_referential_dict_does_not_raise(self):
        cyclic = {}
        cyclic["x"] = cyclic
        self.assertEqual(
            ga_export.host_scope(["date"], cyclic,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_dict_nested_past_the_cap_does_not_raise(self):
        deep = {"fieldName": "hostName"}
        for _ in range(2000):
            deep = {"nested": deep}
        self.assertEqual(
            ga_export.host_scope(["date"], deep,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_self_referential_list_in_an_and_group_does_not_raise(self):
        cyclic_list = []
        cyclic_list.append(cyclic_list)
        dict_filter = {"and_group": {"expressions": cyclic_list}}
        self.assertEqual(
            ga_export.host_scope(["date"], dict_filter,
                                 ["a.example.edu", "b.example.edu"]),
            "mixed_unscoped")

    def test_a_hostname_filter_nested_a_few_levels_deep_is_still_filtered(self):
        # Well inside the cap -- the guard must not break real detection.
        nested = FilterExpression(
            not_expression=FilterExpression(
                and_group=FilterExpressionList(expressions=[
                    FilterExpression(
                        or_group=FilterExpressionList(expressions=[
                            FilterExpression(filter=Filter(field_name="hostName")),
                        ])),
                ])))
        self.assertEqual(
            ga_export.host_scope(["date"], nested,
                                 ["a.example.edu", "b.example.edu"]),
            "filtered")


class TestSuggestedFilename(unittest.TestCase):
    def test_names_source_property_dimensions_and_range(self):
        self.assertEqual(
            ga_export.suggested_filename("314159265", ["date", "pagePath"],
                                         "2026-08-06", "2026-09-02"),
            "ga4-314159265-date-pagepath-20260806-20260902.csv")

    def test_a_metric_only_report_is_named_totals(self):
        self.assertEqual(
            ga_export.suggested_filename("314159265", [], "2026-08-06",
                                         "2026-09-02"),
            "ga4-314159265-totals-20260806-20260902.csv")


class TestRun(unittest.TestCase):
    def test_row_limit_hit_is_false_when_row_count_matches_rows_returned(self):
        # A complete result that exactly fills the requested limit -- must
        # not be reported as truncated.
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        resp.row_count = 1
        client = _FakeClient(resp)
        _, rows, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            limit=1, client=client)
        self.assertEqual(rows, [["2026-08-06", "1"]])
        self.assertFalse(meta["row_limit_hit"])

    def test_row_limit_hit_is_true_when_row_count_exceeds_rows_returned(self):
        # The API's own signal: row_count is the total the query matched,
        # not the number of rows handed back.
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        resp.row_count = 175
        client = _FakeClient(resp)
        _, _, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            limit=50, client=client)
        self.assertTrue(meta["row_limit_hit"])

    def test_row_limit_hit_is_true_when_the_server_cannot_supply_every_row(self):
        # No limit passed, so the export pages to the end -- but this server
        # holds 1 row while claiming 12,000. Before issue #6 an unlimited query
        # was truncated at GA4's default of 10,000; it is now paged instead,
        # and this is the case that is left: a file that still cannot hold
        # every row the query matched must say so rather than look complete.
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        resp.row_count = 12000
        client = _FakeClient(resp)
        _, _, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            client=client)
        self.assertTrue(meta["row_limit_hit"])

    def test_receipts_dimension_filter_is_json_serialisable(self):
        real_filter = FilterExpression(filter=Filter(field_name="hostName"))
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        resp.row_count = 1
        client = _FakeClient(resp)
        _, _, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            dimension_filter=real_filter, client=client)
        json.dumps(meta)  # must not raise
        self.assertIsInstance(meta["dimension_filter"], str)

    def test_receipts_dimension_filter_is_none_when_none_was_passed(self):
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        resp.row_count = 1
        client = _FakeClient(resp)
        _, _, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            client=client)
        json.dumps(meta)  # must not raise
        self.assertIsNone(meta["dimension_filter"])


class TestRunAcceptsBothFilterSpellings(unittest.TestCase):
    """The finding this closes: guidance.py tells callers to send GA4's own
    REST/JSON spelling (camelCase), but proto-plus resolves dict keys
    against proto field names (snake_case) only, so following the
    documentation raised a bare ValueError and made host_scope="filtered"
    unreachable in production. These push a dict through the real run(),
    with a fake *client* rather than a fake run -- the previous tests all
    replaced run() itself, which is exactly how the bug survived.
    """

    def _run(self, dimension_filter):
        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        client = _FakeClient(resp)
        columns, rows, meta = ga_export.run(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"], ["date"],
            dimension_filter=dimension_filter, client=client)
        return client, columns, rows, meta

    def test_camel_case_rest_json_filter_succeeds(self):
        camel = {"filter": {"fieldName": "hostName",
                            "stringFilter": {"value": "admissions.example.edu"}}}
        client, _, rows, meta = self._run(camel)
        self.assertEqual(rows, [["2026-08-06", "1"]])
        self.assertEqual(
            ga_export.host_scope(["date"], camel, ["admissions.example.edu"]),
            "filtered")
        # The real client actually received a filter naming hostName, not
        # just a filter that looked plausible in the dict sent to run().
        sent = client.last_request.dimension_filter
        self.assertEqual(sent.filter.field_name, "hostName")

    def test_snake_case_filter_succeeds_identically(self):
        snake = {"filter": {"field_name": "hostName",
                            "string_filter": {"value": "admissions.example.edu"}}}
        client, _, rows, meta = self._run(snake)
        self.assertEqual(rows, [["2026-08-06", "1"]])
        sent = client.last_request.dimension_filter
        self.assertEqual(sent.filter.field_name, "hostName")

    def test_a_real_filterexpression_still_passes_through_untouched(self):
        real_filter = FilterExpression(filter=Filter(field_name="hostName"))
        client, _, rows, meta = self._run(real_filter)
        self.assertEqual(rows, [["2026-08-06", "1"]])
        self.assertEqual(client.last_request.dimension_filter, real_filter)
        # The sidecar still stringifies a real protobuf, same as before.
        self.assertIsInstance(meta["dimension_filter"], str)

    def test_a_malformed_dict_names_the_problem_as_a_filter_shape(self):
        with self.assertRaises(ValueError) as ctx:
            self._run({"filter": {"nonsense": 1}})
        message = str(ctx.exception)
        # Must actually say what's wrong -- not a bare protobuf internals
        # message with no mention of what field or concept is at fault.
        self.assertIn("dimension_filter", message)
        self.assertIn("filter", message.lower())


class TestFilterForMeta(unittest.TestCase):
    """The sidecar promises the structured filter as sent, so the query can be
    re-run exactly. A dict is already JSON and is kept as one; a protobuf
    message is not JSON-serialisable at all and must be stringified or the
    sidecar write aborts."""

    def test_a_dict_filter_is_recorded_verbatim(self):
        f = {"filter": {"fieldName": "hostName",
                        "stringFilter": {"value": "admissions.example.edu"}}}
        self.assertEqual(ga_export.filter_for_meta(f), f)
        json.dumps(ga_export.filter_for_meta(f))

    def test_a_protobuf_filter_becomes_a_string(self):
        f = FilterExpression(filter=Filter(field_name="hostName"))
        self.assertIsInstance(ga_export.filter_for_meta(f), str)

    def test_none_stays_none(self):
        self.assertIsNone(ga_export.filter_for_meta(None))


class TestExportReportToolWiring(unittest.TestCase):
    """host_scope's "filtered" branch was unreachable in production: the tool
    took no dimension_filter, so every sidecar recorded dimension_filter null
    and _filter_mentions_hostname was reachable only from tests. These go
    through the tool function itself, not the module underneath it.
    """

    def setUp(self):
        import tempfile

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "server"))
        import data_noodler
        self.mod = data_noodler
        self.d = tempfile.mkdtemp()
        # Exports only go to approved places (#156); approve this temp folder.
        from unittest import mock as _mock
        _p = _mock.patch.object(data_noodler, "_places", return_value=(
            {"sessions": self.d}, "test: sessions folder only"))
        _p.start()
        self.addCleanup(_p.stop)
        self.calls = []

        def fake_run(property_id, start, end, metrics, dimensions,
                     dimension_filter=None, limit=None, client=None, **kw):
            self.calls.append({"dimension_filter": dimension_filter,
                               "dimensions": list(dimensions or []), **kw})
            return (list(dimensions or []) + list(metrics),
                    [["2026-08-06", "4"][:len(dimensions or []) + len(metrics)]],
                    {"source": "ga4", "property_id": str(property_id),
                     "dimension_filter": ga_export.filter_for_meta(
                         dimension_filter),
                     "sampled": False, "row_limit_hit": False})

        self._real_run = data_noodler.ga_export.run
        self._real_cfg = data_noodler._cfg
        data_noodler.ga_export.run = fake_run
        data_noodler._cfg = lambda: {}

    def tearDown(self):
        self.mod.ga_export.run = self._real_run
        self.mod._cfg = self._real_cfg

    def _export(self, **kw):
        out = os.path.join(self.d, kw.pop("name", "out.csv"))
        text = self.mod.export_report(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"],
            dimensions=["date"], out_file=out, **kw)
        return json.loads(text)

    def test_the_card_131_options_reach_the_report_call(self):
        mf = {"filter": {"fieldName": "sessions", "numericFilter": {
            "operation": "GREATER_THAN", "value": {"int64Value": "1"}}}}
        ob = [{"metric": {"metricName": "sessions"}, "desc": True}]
        cmp = [{"start_date": "2025-08-06", "end_date": "2025-09-02"}]
        receipt = self._export(metric_filter=mf, order_bys=ob,
                               compare_date_ranges=cmp, currency_code="USD")
        call = self.calls[0]
        self.assertEqual(call["metric_filter"], mf)
        self.assertEqual(call["order_bys"], ob)
        self.assertEqual(call["compare_date_ranges"], cmp)
        self.assertEqual(call["currency_code"], "USD")
        self.assertTrue(receipt["path"].endswith("-compared.csv")
                        or receipt["path"].endswith("out.csv"))

    def test_pivot_on_writes_a_wide_copy_beside_the_long_file(self):
        receipt = self._export(pivot_on="date", name="piv.csv")
        self.assertTrue(receipt["pivot"]["path"].endswith("piv-by-date.csv"))
        self.assertTrue(os.path.exists(receipt["pivot"]["path"]))
        with open(receipt["pivot"]["path"][:-4] + ".meta.json") as f:
            side = json.load(f)
        self.assertIsNone(side["rows_matched"],
                          "the long file's count would make a complete "
                          "pivot look truncated")

    def test_a_pivot_that_cannot_be_made_still_leaves_the_export(self):
        receipt = self._export(pivot_on="hostName", name="piv2.csv")
        self.assertIn("error", receipt["pivot"])
        self.assertTrue(os.path.exists(receipt["path"]))

    def test_a_compared_export_says_so_in_its_default_name(self):
        text = self.mod.export_report(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"],
            dimensions=["date"], session_dir=self.d,
            compare_date_ranges=[{"start_date": "2025-08-06",
                                  "end_date": "2025-09-02"}])
        self.assertTrue(json.loads(text)["path"].endswith("-compared.csv"))

    def test_a_hostname_filter_makes_the_scope_read_filtered(self):
        receipt = self._export(dimension_filter={
            "filter": {"fieldName": "hostName",
                       "stringFilter": {"value": "admissions.example.edu"}}})
        self.assertEqual(receipt["host_scope"], "filtered")

    def test_the_filter_reaches_the_report_call_not_just_the_receipt(self):
        f = {"filter": {"fieldName": "hostName",
                        "stringFilter": {"value": "admissions.example.edu"}}}
        self._export(dimension_filter=f)
        self.assertEqual(self.calls[0]["dimension_filter"], f)

    def test_the_filter_appears_in_the_receipt_so_it_can_be_re_run(self):
        f = {"filter": {"fieldName": "hostName",
                        "stringFilter": {"value": "admissions.example.edu"}}}
        receipt = self._export(dimension_filter=f)
        self.assertEqual(receipt["dimension_filter"], f)

    def test_a_filter_on_another_field_does_not_claim_host_scoping(self):
        receipt = self._export(dimension_filter={
            "filter": {"fieldName": "pagePath",
                       "stringFilter": {"value": "/hostName-report"}}})
        self.assertEqual(receipt["host_scope"], "mixed_unscoped")

    def test_no_filter_still_records_null_and_mixed_unscoped(self):
        receipt = self._export()
        self.assertIsNone(receipt["dimension_filter"])
        self.assertEqual(receipt["host_scope"], "mixed_unscoped")

    def test_a_single_observed_hostname_is_recorded_as_single_host(self):
        receipt = self._export(hostnames=["admissions.example.edu"])
        self.assertEqual(receipt["host_scope"], "single_host")
        self.assertEqual(receipt["hostnames_observed"],
                         ["admissions.example.edu"])


class TestExportReportToolLayerWithTheRealReportCode(unittest.TestCase):
    """The end-to-end path that was actually broken: TestExportReportToolWiring
    above replaces ga_export.run itself, so it could not have caught a bug
    that lives inside run()'s handling of a camelCase dict. This goes through
    the real export_report tool, the real ga_export.run, and the real
    proto-plus message construction -- only the network client is fake.
    """

    def setUp(self):
        import tempfile

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "server"))
        import data_noodler
        self.mod = data_noodler
        self.d = tempfile.mkdtemp()
        # Exports only go to approved places (#156); approve this temp folder.
        from unittest import mock as _mock
        _p = _mock.patch.object(data_noodler, "_places", return_value=(
            {"sessions": self.d}, "test: sessions folder only"))
        _p.start()
        self.addCleanup(_p.stop)

        resp = _fake_response(["date"], ["sessions"], [["2026-08-06", "1"]])
        self.client = _FakeClient(resp)

        self._real_client_factory = ga_export._client
        self._real_cfg = data_noodler._cfg
        ga_export._client = lambda: self.client
        data_noodler._cfg = lambda: {}

    def tearDown(self):
        ga_export._client = self._real_client_factory
        self.mod._cfg = self._real_cfg

    def test_the_documented_camel_case_filter_reaches_the_receipt_as_filtered(self):
        out = os.path.join(self.d, "out.csv")
        text = self.mod.export_report(
            "314159265", "2026-08-06", "2026-09-02", ["sessions"],
            dimensions=["date"], out_file=out,
            dimension_filter={"filter": {"fieldName": "hostName",
                                         "stringFilter": {
                                             "value": "admissions.example.edu"}}})
        receipt = json.loads(text)
        self.assertEqual(receipt["host_scope"], "filtered")
        self.assertEqual(self.client.last_request.dimension_filter.filter
                         .field_name, "hostName")



def _numbered_response(total, sampled=False, other_row_loss=False):
    """A report of `total` rows, each distinguishable, for paging tests."""
    resp = _fake_response(["date"], ["sessions"],
                          [[f"d{i}", str(i)] for i in range(total)])
    resp.row_count = total
    resp.metadata = types.SimpleNamespace(
        sampling_metadatas=["sampled"] if sampled else [],
        data_loss_from_other_row=other_row_loss)
    return resp


class TestExportFetchesEveryRow(unittest.TestCase):
    """Issue #6: an export with no limit must contain every row.

    It used to make one request. With no limit GA4 applied its own default of
    10,000, so any larger report produced a CSV that looked complete and was
    not. The receipt flagged it, but a file outlives its receipt -- and the
    people this tool is given to are exactly the ones with large properties.

    This mattered more than it looked: issue #1 routes agents AWAY from the
    upstream run_report because it truncates. Routing them to an export with
    the same flaw would only have moved the problem.
    """

    def _run(self, client, **kw):
        return ga_export.run("314159265", "2025-10-01", "2026-09-30",
                             ["sessions"], ["date"], client=client, **kw)

    def test_an_unlimited_export_pages_to_the_full_total(self):
        client = _FakeClient(_numbered_response(23000), page_cap=10000)
        _, rows, meta = self._run(client)
        self.assertEqual(len(rows), 23000)
        self.assertFalse(meta["row_limit_hit"])
        self.assertEqual(meta["rows_fetched"], 23000)
        self.assertEqual(meta["rows_matched"], 23000)

    def test_pages_are_contiguous_and_none_is_fetched_twice(self):
        client = _FakeClient(_numbered_response(23000), page_cap=10000)
        _, rows, _ = self._run(client)
        self.assertEqual([o for o, _ in client.requests], [0, 10000, 20000])
        self.assertEqual(rows[0][0], "d0")
        self.assertEqual(rows[-1][0], "d22999")
        self.assertEqual(len({r[0] for r in rows}), 23000,
                         "a row was duplicated or skipped across pages")

    def test_an_explicit_limit_is_honoured_and_flagged(self):
        client = _FakeClient(_numbered_response(23000), page_cap=10000)
        _, rows, meta = self._run(client, limit=100)
        self.assertEqual(len(rows), 100)
        self.assertTrue(meta["row_limit_hit"])
        self.assertEqual(meta["limit_requested"], 100)
        self.assertEqual(meta["incomplete_reason"], "caller_limit")

    def test_an_explicit_limit_larger_than_one_page_is_still_paged(self):
        client = _FakeClient(_numbered_response(23000), page_cap=10000)
        _, rows, meta = self._run(client, limit=15000)
        self.assertEqual(len(rows), 15000)
        self.assertEqual(meta["incomplete_reason"], "caller_limit")

    def test_a_complete_export_has_no_incomplete_reason(self):
        client = _FakeClient(_numbered_response(500))
        _, _, meta = self._run(client)
        self.assertIsNone(meta["incomplete_reason"])

    def test_an_empty_report_makes_exactly_one_request(self):
        client = _FakeClient(_numbered_response(0))
        _, rows, meta = self._run(client)
        self.assertEqual(rows, [])
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(meta["row_limit_hit"])

    def test_a_server_that_stops_short_is_flagged_not_looped_on(self):
        # row_count claims 23,000 but the server only ever holds 5. The loop
        # must stop when a page comes back empty, not spin until MAX_PAGES.
        resp = _numbered_response(5)
        resp.row_count = 23000
        client = _FakeClient(resp, page_cap=10000)
        _, rows, meta = self._run(client)
        self.assertEqual(len(rows), 5)
        self.assertTrue(meta["row_limit_hit"])
        self.assertEqual(meta["incomplete_reason"], "server_stopped")
        self.assertLessEqual(len(client.requests), 2)

    def test_other_row_data_loss_is_recorded(self):
        # GA4 folds the long tail into "(other)" on high-cardinality reports.
        # That changes what the rows mean, so it belongs in the sidecar.
        client = _FakeClient(_numbered_response(10, other_row_loss=True))
        _, _, meta = self._run(client)
        self.assertTrue(meta["data_loss_from_other_row"])

    def test_sampling_on_any_page_marks_the_whole_export_sampled(self):
        client = _FakeClient(_numbered_response(30, sampled=True), page_cap=10)
        _, _, meta = self._run(client)
        self.assertTrue(meta["sampled"])


class TestExportCanDoWhatRunReportCan(unittest.TestCase):
    """Card #131. The complete-data policy sends models to export_report, but
    export_report could not filter on a metric, sort, or compare date ranges.
    run_report could. So a model asked for "pages over 100 views, this year
    against last" either broke the policy -- run_report with a row limit --
    or improvised a join of two exports. Each option is now on the request.
    """

    def _run(self, **kw):
        client = _FakeClient(_fake_response(["pagePath"], ["screenPageViews"],
                                            [["/a", "5"]]))
        _, _, meta = ga_export.run("123", "2026-01-01", "2026-01-31",
                                   ["screenPageViews"], ["pagePath"],
                                   client=client, **kw)
        return client.last_request, meta

    def test_metric_filter_reaches_the_request_in_either_spelling(self):
        for spelling in (
            {"filter": {"fieldName": "screenPageViews", "numericFilter": {
                "operation": "GREATER_THAN", "value": {"int64Value": "100"}}}},
            {"filter": {"field_name": "screenPageViews", "numeric_filter": {
                "operation": "GREATER_THAN", "value": {"int64_value": "100"}}}},
        ):
            req, meta = self._run(metric_filter=spelling)
            self.assertEqual(req.metric_filter.filter.field_name,
                             "screenPageViews")
            self.assertEqual(meta["metric_filter"], spelling)

    def test_a_bad_metric_filter_names_itself(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(metric_filter={"filter": {"nope": 1}})
        self.assertIn("metric_filter", str(ctx.exception))

    def test_order_bys_reach_the_request(self):
        req, meta = self._run(order_bys=[
            {"metric": {"metricName": "screenPageViews"}, "desc": True}])
        self.assertEqual(req.order_bys[0].metric.metric_name,
                         "screenPageViews")
        self.assertTrue(req.order_bys[0].desc)
        self.assertEqual(meta["order_bys"][0]["desc"], True)

    def test_a_bad_order_by_names_itself(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(order_bys=[{"bogus": 1}])
        self.assertIn("order_bys", str(ctx.exception))

    def test_comparison_ranges_follow_the_primary_one(self):
        req, meta = self._run(compare_date_ranges=[
            {"start_date": "2025-01-01", "end_date": "2025-01-31",
             "name": "last_year"}])
        got = [(d.start_date, d.end_date, d.name) for d in req.date_ranges]
        self.assertEqual(got, [("2026-01-01", "2026-01-31", "current"),
                               ("2025-01-01", "2025-01-31", "last_year")])
        self.assertEqual([r["name"] for r in meta["date_ranges"]],
                         ["current", "last_year"])

    def test_unnamed_comparison_ranges_get_names(self):
        req, _ = self._run(compare_date_ranges=[
            {"start_date": "2025-01-01", "end_date": "2025-01-31"}])
        self.assertEqual(req.date_ranges[1].name, "compare_1")

    def test_camel_case_comparison_dates_are_accepted(self):
        req, _ = self._run(compare_date_ranges=[
            {"startDate": "2025-01-01", "endDate": "2025-01-31"}])
        self.assertEqual(req.date_ranges[1].start_date, "2025-01-01")

    def test_more_than_four_ranges_is_refused_before_the_request(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(compare_date_ranges=[
                {"start_date": "2025-01-01", "end_date": "2025-01-31"}] * 4)
        self.assertIn("4", str(ctx.exception))

    def test_a_comparison_range_without_dates_is_refused(self):
        with self.assertRaises(ValueError):
            self._run(compare_date_ranges=[{"name": "x"}])

    def test_currency_reaches_the_request(self):
        req, meta = self._run(currency_code="EUR")
        self.assertEqual(req.currency_code, "EUR")
        self.assertEqual(meta["currency_code"], "EUR")

    def test_quota_is_always_asked_for_and_recorded(self):
        req, meta = self._run()
        self.assertTrue(req.return_property_quota)
        self.assertIn("property_quota", meta)

    def test_quota_remaining_is_read_from_the_response(self):
        resp = _fake_response(["pagePath"], ["screenPageViews"], [["/a", "5"]])
        q = types.SimpleNamespace
        resp.property_quota = q(
            tokens_per_day=q(consumed=10, remaining=199990),
            tokens_per_hour=q(consumed=10, remaining=39990),
            tokens_per_project_per_hour=q(consumed=10, remaining=13990))
        _, _, meta = ga_export.run("123", "2026-01-01", "2026-01-31",
                                   ["screenPageViews"], ["pagePath"],
                                   client=_FakeClient(resp))
        self.assertEqual(meta["property_quota"]["tokens_per_day_remaining"],
                         199990)
        self.assertEqual(meta["property_quota"]["tokens_per_hour_remaining"],
                         39990)


class _ComparingClient:
    """Models GA4 with several date ranges, as measured 2026-10-07.

    limit, offset and row_count all count dimension COMBINATIONS; each
    combination comes back as one row per range. Measured on a real property:
    row_count 1,831, rows returned 3,662; paging by rows returned fetched
    1,862 rows and silently lost the rest.
    """

    def __init__(self, combos, ranges=("current", "last_year"), page_cap=None):
        self.combos, self.ranges, self.page_cap = combos, ranges, page_cap
        self.requests = []

    def run_report(self, request):
        self.requests.append((request.offset, request.limit))
        n = request.limit or 10000
        if self.page_cap:
            n = min(n, self.page_cap)
        chosen = self.combos[request.offset:request.offset + n]
        rows = [[c, r, "1"] for c in chosen for r in self.ranges]
        resp = _fake_response(["pagePath", "dateRange"], ["sessions"], rows)
        resp.row_count = len(self.combos)
        return resp


class TestComparedExportsPageByCombination(unittest.TestCase):
    CMP = [{"start_date": "2025-01-01", "end_date": "2025-01-31",
            "name": "last_year"}]

    def _run(self, client, **kw):
        return ga_export.run("1", "2026-01-01", "2026-01-31", ["sessions"],
                             ["pagePath"], client=client,
                             compare_date_ranges=self.CMP, **kw)

    def test_every_row_arrives_across_pages(self):
        combos = [f"/p{i}" for i in range(25)]
        _, rows, meta = self._run(_ComparingClient(combos, page_cap=10))
        self.assertEqual(len(rows), 50)
        self.assertEqual(len({(r[0], r[1]) for r in rows}), 50)
        self.assertFalse(meta["row_limit_hit"])
        self.assertIsNone(meta["incomplete_reason"])

    def test_offsets_count_combinations_not_rows(self):
        client = _ComparingClient([f"/p{i}" for i in range(25)], page_cap=10)
        self._run(client)
        self.assertEqual([o for o, _ in client.requests], [0, 10, 20])

    def test_the_receipt_counts_rows_and_combinations_separately(self):
        _, rows, meta = self._run(_ComparingClient(["/a", "/b", "/c"]))
        self.assertEqual(meta["rows_matched"], 6,
                         "rows_matched is what a complete FILE holds; the "
                         "receipt's row_count is compared against it")
        self.assertEqual(meta["dimension_combinations_matched"], 3)

    def test_a_limit_counts_combinations_when_comparing(self):
        _, rows, meta = self._run(
            _ComparingClient([f"/p{i}" for i in range(25)]), limit=5)
        self.assertEqual(len(rows), 10)
        self.assertEqual(meta["incomplete_reason"], "caller_limit")


class _TotalsClient:
    """Models GA4 for a report with NO dimensions, as measured 2026-11-20.

    With several date ranges GA4 adds a dateRange column, returns one row per
    range, says row_count = the number of ranges, and hands the same rows
    back whatever the offset. The old loop counted that as one combination
    against a goal of two, fetched again, and wrote every row twice (#1993).
    """

    def __init__(self, ranges=("current", "prior30")):
        self.ranges = ranges
        self.requests = []

    def run_report(self, request):
        self.requests.append((request.offset, request.limit))
        if len(self.ranges) > 1:
            resp = _fake_response(["dateRange"], ["sessions"],
                                  [[r, "485"] for r in self.ranges])
        else:
            resp = _fake_response([], ["sessions"], [["485"]])
        resp.row_count = len(self.ranges)
        return resp


class TestATotalsExportIsOnePageAndNoDuplicates(unittest.TestCase):
    """#1993: the fleshandsyntax totals file held each range twice."""

    CMP = [{"start_date": "2026-09-20", "end_date": "2026-10-19",
            "name": "prior30"}]

    def test_two_ranges_write_two_rows_from_one_request(self):
        client = _TotalsClient()
        _, rows, meta = ga_export.run(
            "1", "2026-10-20", "2026-11-18", ["sessions"], [],
            client=client, compare_date_ranges=self.CMP)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(meta["pages_fetched"], 1)
        self.assertEqual(meta["rows_matched"], 2)
        self.assertEqual(meta["dimension_combinations_matched"], 1)
        self.assertFalse(meta["row_limit_hit"])
        self.assertIsNone(meta["incomplete_reason"])
        self.assertEqual(meta["duplicate_rows"], 0)

    def test_one_range_writes_one_row(self):
        client = _TotalsClient(ranges=("current",))
        _, rows, meta = ga_export.run(
            "1", "2026-10-20", "2026-11-18", ["sessions"], [], client=client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(client.requests), 1)
        self.assertIsNone(meta["incomplete_reason"])


class _RepeatingClient(_ComparingClient):
    """A server that ignores offset: every page repeats the first."""

    def run_report(self, request):
        request.offset = 0
        return super().run_report(request)


class TestTheReceiptSaysWhenRowsRepeat(unittest.TestCase):
    """A file the agent must analyze from must not be able to double itself
    while the receipt reads all-clear. A GA4
    report never repeats a full dimension key, so any repeat is counted."""

    def test_repeated_keys_are_counted_in_the_receipt(self):
        _, rows, meta = ga_export.run(
            "1", "2026-01-01", "2026-01-31", ["sessions"], ["pagePath"],
            client=_RepeatingClient([f"/p{i}" for i in range(4)],
                                    ranges=("current",), page_cap=2))
        self.assertGreater(meta["duplicate_rows"], 0)

    def test_a_clean_export_counts_zero(self):
        _, rows, meta = ga_export.run(
            "1", "2026-01-01", "2026-01-31", ["sessions"], ["pagePath"],
            client=_ComparingClient([f"/p{i}" for i in range(4)],
                                    ranges=("current",), page_cap=2))
        self.assertEqual(meta["duplicate_rows"], 0)


class TestTheExportToolTellsTheAgentAboutRepeats(unittest.TestCase):
    """#1993: the receipt field only helps if the agent reading it knows
    what a non-zero value means."""

    def test_the_tool_doc_names_duplicate_rows_and_forbids_analysis(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "server"))
        import guidance
        doc = " ".join(guidance.GSC_TOOL_DOCS["export_report"].split())
        self.assertIn("duplicate_rows is above 0", doc)
        self.assertIn("do not analyse it", doc)
