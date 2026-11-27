"""Two of the outside review's nits that turned out to matter (#2007).

resolve() is the boundary that keeps exports inside approved places. Its
out_file and session_dir branches check containment; its default-name branch
did not, and relied on every caller building a safe name. The GA name is
built from property_id, start and end as given. Today nothing bad reaches
the disk only because Google refuses a malformed id before anything is
written. A boundary must not depend on someone else's input validation.

A Search Console row with fewer keys than the dimensions asked for was
guarded for the page lookup only. The short row itself was still written, and
export rejects a file whose rows don't match its columns, so the whole export
was lost to one odd row.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))
import gsc  # noqa: E402
import sessions  # noqa: E402


class TestTheDefaultNameCannotLeaveThePlace(unittest.TestCase):

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        self.root = os.path.join(self.home, "sessions")
        self.session = os.path.join(self.root, "s1")
        os.makedirs(self.session)
        self.places = sessions.build_places(sessions_root=self.root)

    def test_a_traversing_default_name_is_refused(self):
        for name in ("../../escape.csv", "a/../../../escape.csv",
                     os.path.join(self.home, "escape.csv")):
            with self.subTest(name):
                with self.assertRaises(sessions.SessionError):
                    sessions.resolve(None, self.session, name, self.places)

    def test_a_plain_name_that_is_a_symlink_out_is_refused(self):
        # The one case only _inside()'s realpath catches: no separator, so
        # basename and dirname both pass it, but base/<name> already exists as
        # a symlink pointing outside the place (from review).
        outside = os.path.join(self.home, "outside.csv")
        open(outside, "w").close()
        os.symlink(outside, os.path.join(self.session, "trap.csv"))
        with self.assertRaises(sessions.SessionError):
            sessions.resolve(None, self.session, "trap.csv", self.places)

    def test_an_empty_or_nul_name_is_a_session_error_not_a_crash(self):
        for name in ("", "x.csv\0"):
            with self.subTest(repr(name)):
                with self.assertRaises(sessions.SessionError):
                    sessions.resolve(None, self.session, name, self.places)

    def test_an_ordinary_default_name_still_lands_in_the_session(self):
        path, _ = sessions.resolve(None, self.session,
                                   "ga4-123-date-20260101-20260131.csv",
                                   self.places)
        self.assertEqual(os.path.dirname(path), self.session)


class _OnePage:
    def __init__(self, rows):
        self.rows = rows

    def request(self, method, url, **kw):
        rows = self.rows

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return {"rows": rows}
        return R()


class TestAShortRowIsPaddedNotFatal(unittest.TestCase):

    def test_every_row_has_one_cell_per_column(self):
        rows = [{"keys": ["2026-08-01", "https://x/a", "q"], "clicks": 1,
                 "impressions": 2, "ctr": 0.5, "position": 1.0},
                {"keys": ["2026-08-01"], "clicks": 1,
                 "impressions": 2, "ctr": 0.5, "position": 1.0}]
        cols, out, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-01", "2026-08-01",
            ["date", "page", "query"], session=_OnePage(rows))
        self.assertEqual({len(r) for r in out}, {len(cols)})
        self.assertEqual(out[1][:3], ["2026-08-01", "", ""])

    def test_a_long_row_is_not_cut_down_to_fit(self):
        # Padding a gap is honest; discarding an unexpected key is not. The
        # long row keeps every key, so export's row-length check refuses it.
        rows = [{"keys": ["2026-08-01", "https://x/a", "q", "surprise"],
                 "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1.0}]
        cols, out, _ = gsc.search_analytics(
            "sc-domain:example.edu", "2026-08-01", "2026-08-01",
            ["date", "page", "query"], session=_OnePage(rows))
        self.assertIn("surprise", out[0])
        self.assertGreater(len(out[0]), len(cols))


if __name__ == "__main__":
    unittest.main()
