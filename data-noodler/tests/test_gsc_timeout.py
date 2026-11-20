"""Search Console's time limit is ours, explicit, and explained (#2007 R1).

An outside review said Search Console requests had no timeout and could hang
forever. That was wrong: google-auth's AuthorizedSession.request defaults to
120 seconds. But that limit was invisible here, one library default away
from changing, and measured against real traffic it was tight: on
2026-11-20 a healthy 25,000-row page (16 months, date x page x query) took
61.7 s. On a slow Google day, 120 s could cut off a page that was working.

So call() now sets its own limit: a short one for connecting (a host that
can't be reached is never merely slow) and a generous one for the answer.
When the limit trips, the message says what happened and what to try.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))
import gsc  # noqa: E402
import requests  # noqa: E402


class _Recorder:
    def __init__(self, raise_=None):
        self.kw, self.raise_ = None, raise_

    def request(self, method, url, **kw):
        self.kw = kw
        if self.raise_:
            raise self.raise_

        class R:
            status_code = 200

            def json(self):
                return {}
        return R()


class TestTheLimitIsExplicit(unittest.TestCase):

    def test_every_call_carries_our_connect_and_read_limits(self):
        s = _Recorder()
        gsc.call("GET", "https://example.invalid/", session=s)
        self.assertEqual(s.kw["timeout"], (gsc.CONNECT_TIMEOUT, gsc.READ_TIMEOUT))

    def test_the_read_limit_clears_the_slowest_healthy_page_measured(self):
        # 61.7 s, measured 2026-11-20. Keep at least 4x headroom.
        self.assertGreaterEqual(gsc.READ_TIMEOUT, 4 * 61.7)
        self.assertLessEqual(gsc.CONNECT_TIMEOUT, 30)

    def test_a_caller_can_still_choose_its_own(self):
        s = _Recorder()
        gsc.call("GET", "https://example.invalid/", session=s, timeout=5)
        self.assertEqual(s.kw["timeout"], 5)


class TestATimeoutIsExplainedNotJustNamed(unittest.TestCase):

    def test_a_read_timeout_says_google_did_not_answer_and_what_to_try(self):
        with self.assertRaises(gsc.GscError) as cm:
            gsc.call("POST", "https://example.invalid/",
                     session=_Recorder(requests.exceptions.ReadTimeout()))
        msg = str(cm.exception)
        self.assertIn("did not answer within 5 minutes", msg)
        self.assertIn("narrow", msg)
        self.assertNotIn("(no message)", msg)

    def test_a_connect_timeout_says_google_could_not_be_reached(self):
        with self.assertRaises(gsc.GscError) as cm:
            gsc.call("GET", "https://example.invalid/",
                     session=_Recorder(requests.exceptions.ConnectTimeout()))
        self.assertIn("could not be reached", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
