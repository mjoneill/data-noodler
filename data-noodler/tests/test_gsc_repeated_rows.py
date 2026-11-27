"""#1994: a Search Console export that repeats rows says so.

#1993 taught GA exports to count rows that repeat a full key, because a
server that ignores or resets its paging offset writes a doubled file whose
sums are inflated, and the receipt read all-clear. Search Console pages with
its own startRow loop, which had neither that count nor a way out: a server
that ignored startRow and kept sending the same full page would be asked
again forever.

A Search Console report never repeats a full key (the requested dimensions),
so any repeat means paging went wrong.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import export  # noqa: E402
import gsc  # noqa: E402

DIMS = ["date", "page"]


def _rows(start, n):
    return [{"keys": ["2026-11-01", f"https://example.com/p{start + i}"],
             "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1.0}
            for i in range(n)]


class _Session:
    """Serves pages in order; stops the test instead of looping forever."""

    BUDGET = 6

    def __init__(self, serve):
        self.serve = serve
        self.calls = 0

    def request(self, method, url, **kw):
        self.calls += 1
        if self.calls > self.BUDGET:
            raise AssertionError(
                f"asked the server {self.calls} times; paging never stopped")
        payload = {"rows": self.serve(kw["json"]["startRow"], self.calls)}

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return payload
        return R()


def _run(serve):
    s = _Session(serve)
    _, rows, meta = gsc.search_analytics(
        "sc-domain:example.com", "2026-11-01", "2026-11-07", DIMS, session=s)
    return rows, meta, s


class AServerThatIgnoresStartRow(unittest.TestCase):
    def setUp(self):
        # Every request gets the first page, whatever startRow says.
        self.rows, self.meta, self.s = _run(
            lambda start, n: _rows(0, gsc.PAGE_SIZE))

    def test_paging_stops(self):
        self.assertLessEqual(self.s.calls, 2)

    def test_the_repeated_page_is_not_written(self):
        self.assertEqual(len(self.rows), gsc.PAGE_SIZE)

    def test_the_receipt_says_the_file_is_incomplete(self):
        self.assertTrue(self.meta["stopped_reason"])
        step = export.next_step(self.meta, len(self.rows))
        self.assertTrue(step.startswith("INCOMPLETE"), step)


class AServerThatResetsPartWay(unittest.TestCase):
    def setUp(self):
        # The second page starts five rows early: five repeats, two new.
        def serve(start, n):
            if start == 0:
                return _rows(0, gsc.PAGE_SIZE)
            return _rows(start - 5, 7)
        self.rows, self.meta, _ = _run(serve)

    def test_the_repeats_are_counted(self):
        self.assertEqual(self.meta["duplicate_rows"], 5)

    def test_the_receipt_says_do_not_analyze(self):
        step = export.next_step(self.meta, len(self.rows))
        self.assertTrue(step.startswith("REPEATED ROWS"), step)


class ACorrectServer(unittest.TestCase):
    def test_no_repeats_and_no_warning(self):
        def serve(start, n):
            return _rows(start, gsc.PAGE_SIZE if start == 0 else 3)
        rows, meta, _ = _run(serve)
        self.assertEqual(len(rows), gsc.PAGE_SIZE + 3)
        self.assertEqual(meta["duplicate_rows"], 0)
        self.assertIsNone(meta["stopped_reason"])

    def test_the_count_is_always_present(self):
        _, meta, _ = _run(lambda start, n: _rows(0, 2))
        self.assertEqual(meta["duplicate_rows"], 0)


if __name__ == "__main__":
    unittest.main()
