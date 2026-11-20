"""Cohort, realtime and funnel reports to file, and pivoting. Cards #135, #136.

Response shapes are from live calls on 2026-10-07, including two quirks:
a funnel table lists its metric headers twice (8 headers, 4 values per row),
and its breakdown carries a RESERVED_TOTAL row.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "companion"))

import ga_reports

NS = types.SimpleNamespace


def _table(dims, mets, rows, row_count=None):
    def row(vals):
        return NS(dimension_values=[NS(value=v) for v in vals[:len(dims)]],
                  metric_values=[NS(value=v) for v in vals[len(dims):]])
    return NS(dimension_headers=[NS(name=d) for d in dims],
              metric_headers=[NS(name=m) for m in mets],
              rows=[row(r) for r in rows],
              row_count=len(rows) if row_count is None else row_count,
              property_quota=None, metadata=None)


class _Client:
    def __init__(self, resp):
        self.resp, self.request = resp, None

    def run_report(self, request):
        self.request = request
        return self.resp

    run_realtime_report = run_report
    run_funnel_report = run_report


class TestCohort(unittest.TestCase):
    RESP = _table(["cohort", "cohortNthWeek"],
                  ["cohortActiveUsers", "cohortTotalUsers"],
                  [["aug", "0000", "10273", "10273"],
                   ["aug", "0001", "900", "10273"]])

    def _run(self, **kw):
        c = _Client(self.RESP)
        args = dict(cohorts=[{"name": "aug", "start_date": "2026-08-02",
                              "end_date": "2026-08-08"}],
                    granularity="WEEKLY", periods=4)
        args.update(kw)
        out = ga_reports.run_cohort("1", client=c, **args)
        return c.request, out

    def test_the_request_is_a_cohort_spec_with_matching_nth_dimension(self):
        req, _ = self._run()
        self.assertEqual([d.name for d in req.dimensions],
                         ["cohort", "cohortNthWeek"])
        self.assertEqual(req.cohort_spec.cohorts[0].dimension,
                         "firstSessionDate")
        self.assertEqual(req.cohort_spec.cohorts_range.end_offset, 4)
        self.assertEqual(len(req.date_ranges), 0,
                         "a cohort request carries its dates in the cohorts")

    def test_granularity_picks_the_nth_dimension(self):
        for gran, dim in (("DAILY", "cohortNthDay"),
                          ("MONTHLY", "cohortNthMonth")):
            req, _ = self._run(granularity=gran)
            self.assertEqual(req.dimensions[1].name, dim)

    def test_rows_and_meta(self):
        _, (cols, rows, meta) = self._run()
        self.assertEqual(cols[:2], ["cohort", "cohortNthWeek"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(meta["source"], "ga4_cohort")
        self.assertEqual(meta["cohorts"][0]["name"], "aug")
        self.assertIsNone(meta["incomplete_reason"])

    def test_bad_input_is_refused_before_the_request(self):
        for bad in ({"granularity": "YEARLY"}, {"cohorts": []},
                    {"cohorts": [{"name": "x"}]}, {"periods": -1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self._run(**bad)

    def test_unnamed_cohorts_get_names(self):
        req, _ = self._run(cohorts=[{"start_date": "2026-08-02",
                                     "end_date": "2026-08-08"}])
        self.assertEqual(req.cohort_spec.cohorts[0].name, "cohort_1")


class TestRealtime(unittest.TestCase):
    def test_rows_and_minute_range(self):
        c = _Client(_table(["unifiedScreenName"], ["activeUsers"],
                           [["Majors", "19"]]))
        cols, rows, meta = ga_reports.run_realtime(
            "1", ["unifiedScreenName"], ["activeUsers"], minutes_ago=10,
            client=c)
        self.assertEqual(rows, [["Majors", "19"]])
        self.assertEqual(c.request.minute_ranges[0].start_minutes_ago, 10)
        self.assertEqual(meta["source"], "ga4_realtime")
        self.assertIn("captured_at", meta)

    def test_minutes_beyond_what_ga_keeps_are_refused(self):
        with self.assertRaises(ValueError):
            ga_reports.run_realtime("1", [], ["activeUsers"], minutes_ago=90,
                                    client=_Client(None))

    def test_a_short_response_is_marked_incomplete(self):
        c = _Client(_table(["x"], ["activeUsers"], [["a", "1"]], row_count=5))
        _, _, meta = ga_reports.run_realtime("1", ["x"], ["activeUsers"],
                                             client=c)
        self.assertEqual(meta["incomplete_reason"], "server_stopped")


class TestFunnel(unittest.TestCase):
    TABLE = _table(
        ["funnelStepName", "deviceCategory"],
        ["activeUsers", "funnelStepCompletionRate", "funnelStepAbandonments",
         "funnelStepAbandonmentRate"] * 2,
        [["1. view", "RESERVED_TOTAL", "61577", "0.07", "57026", "0.93"],
         ["1. view", "desktop", "39531", "0.08", "36284", "0.92"]])

    def _run(self, **kw):
        c = _Client(NS(funnel_table=self.TABLE, property_quota=None))
        args = dict(steps=[{"name": "view", "event": "page_view"},
                           {"name": "apply", "event": "apply_click"}],
                    start_date="2026-09-01", end_date="2026-09-30",
                    breakdown_dimension="deviceCategory")
        args.update(kw)
        return c, ga_reports.run_funnel("1", client=c, **args)

    def test_duplicated_metric_headers_are_collapsed(self):
        _, (cols, rows, _) = self._run()
        self.assertEqual(cols, ["funnelStepName", "deviceCategory",
                                "activeUsers", "funnelStepCompletionRate",
                                "funnelStepAbandonments",
                                "funnelStepAbandonmentRate"])
        self.assertEqual(len(rows[0]), len(cols))

    def test_the_total_row_is_relabelled(self):
        _, (_, rows, meta) = self._run()
        self.assertEqual(rows[0][1], "(total)")
        self.assertIn("RESERVED_TOTAL", meta["notes"])

    def test_the_request_carries_steps_dates_and_breakdown(self):
        c, _ = self._run(is_open_funnel=True)
        req = c.request
        self.assertEqual([s.name for s in req.funnel.steps], ["view", "apply"])
        self.assertEqual(req.funnel.steps[0].filter_expression
                         .funnel_event_filter.event_name, "page_view")
        self.assertTrue(req.funnel.is_open_funnel)
        self.assertEqual(req.funnel_breakdown.breakdown_dimension.name,
                         "deviceCategory")
        self.assertEqual(req.date_ranges[0].start_date, "2026-09-01")

    def test_a_step_needs_an_event_or_a_filter(self):
        with self.assertRaises(ValueError):
            self._run(steps=[{"name": "x"}])


class TestPivot(unittest.TestCase):
    COLS = ["pagePath", "month", "sessions", "users"]
    ROWS = [["/a", "202608", "1", "10"], ["/a", "202609", "2", "20"],
            ["/b", "202609", "3", "30"]]

    def test_values_become_columns_per_metric_and_nothing_is_lost(self):
        cols, rows = ga_reports.pivot_wide(self.COLS, self.ROWS, "month",
                                           ["sessions", "users"])
        self.assertEqual(cols, ["pagePath", "sessions|202608",
                                "sessions|202609", "users|202608",
                                "users|202609"])
        self.assertEqual(rows, [["/a", "1", "2", "10", "20"],
                                ["/b", "", "3", "", "30"]])

    def test_blank_is_absent_not_zero(self):
        _, rows = ga_reports.pivot_wide(self.COLS, self.ROWS, "month",
                                        ["sessions", "users"])
        self.assertEqual(rows[1][1], "")

    def test_pivoting_on_a_missing_column_is_refused(self):
        with self.assertRaises(ValueError):
            ga_reports.pivot_wide(self.COLS, self.ROWS, "date", ["sessions"])

    def test_too_many_values_is_refused_with_the_count(self):
        rows = [["/a", str(i), "1", "1"] for i in range(300)]
        with self.assertRaises(ValueError) as ctx:
            ga_reports.pivot_wide(self.COLS, rows, "month",
                                  ["sessions", "users"])
        self.assertIn("300", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
