"""Sitemaps a Search Console property has been sent, read-only.

Card #130. The Sitemaps API was the one read surface of Search Console this
package did not reach. It answers "did Google fetch our sitemap, and did it
choke on it" -- the question that comes right after a page turns out to be
"Discovered - currently not indexed".

Read-only on purpose. The API can also submit and delete sitemaps; this
package holds a read-only scope and does not offer either.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import gsc
from test_gsc_sites import _FakeSession

PAYLOAD = {"sitemap": [
    {"path": "https://example.edu/sitemap.xml",
     "lastSubmitted": "2026-09-01T10:00:00.000Z",
     "lastDownloaded": "2026-10-06T03:12:00.000Z",
     "isPending": False, "isSitemapsIndex": True, "type": "sitemap",
     "warnings": "2", "errors": "0",
     "contents": [{"type": "web", "submitted": "1840", "indexed": "0"},
                  {"type": "image", "submitted": "12"}]},
    {"path": "https://example.edu/news.xml", "isPending": True,
     "isSitemapsIndex": False},
]}


class TestListSitemaps(unittest.TestCase):
    def test_reads_the_sitemaps_endpoint_for_the_encoded_site(self):
        s = _FakeSession(PAYLOAD)
        gsc.list_sitemaps("sc-domain:example.edu", session=s)
        method, url, _ = s.calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith(
            "/webmasters/v3/sites/sc-domain%3Aexample.edu/sitemaps"), url)

    def test_reports_the_fields_that_answer_did_google_read_it(self):
        first = gsc.list_sitemaps("sc-domain:example.edu",
                                  session=_FakeSession(PAYLOAD))[0]
        self.assertEqual(first["path"], "https://example.edu/sitemap.xml")
        self.assertEqual(first["last_downloaded"], "2026-10-06T03:12:00.000Z")
        self.assertEqual(first["last_submitted"], "2026-09-01T10:00:00.000Z")
        self.assertIs(first["is_sitemaps_index"], True)
        self.assertIs(first["is_pending"], False)
        self.assertEqual((first["errors"], first["warnings"]), (0, 2))
        self.assertEqual(first["submitted"], {"web": 1840, "image": 12})

    def test_the_deprecated_indexed_count_is_not_passed_on(self):
        # Google stopped populating it; it reads 0 for a sitemap whose pages
        # are indexed. Passing it on invites "none of our pages are indexed".
        first = gsc.list_sitemaps("sc-domain:example.edu",
                                  session=_FakeSession(PAYLOAD))[0]
        self.assertNotIn("indexed", str(first))

    def test_a_never_downloaded_sitemap_says_so_rather_than_blank(self):
        second = gsc.list_sitemaps("sc-domain:example.edu",
                                   session=_FakeSession(PAYLOAD))[1]
        self.assertIsNone(second["last_downloaded"])
        self.assertIsNone(second["errors"])

    def test_no_sitemaps_is_an_empty_list(self):
        self.assertEqual(gsc.list_sitemaps("sc-domain:example.edu",
                                           session=_FakeSession({})), [])

    def test_there_is_no_way_to_submit_or_delete(self):
        for name in dir(gsc):
            self.assertFalse(
                "submit" in name.lower() or "delete" in name.lower(), name)


if __name__ == "__main__":
    unittest.main()


class TestSitemapsAreAFileNotAReply(unittest.TestCase):
    """Measured 2026-10-07: one domain property had 826 sitemaps.

    Every subdomain submits its own. Returned inline that is a couple of
    hundred kilobytes of JSON in the conversation, so the tool writes a CSV
    and returns a receipt, like every other Search Console export.
    """

    def test_rows_flatten_to_fixed_columns(self):
        sms = gsc.list_sitemaps("sc-domain:example.edu",
                                session=_FakeSession(PAYLOAD))
        columns, rows = gsc.sitemap_rows(sms)
        self.assertEqual(columns, gsc.SITEMAP_COLUMNS)
        first = dict(zip(columns, rows[0]))
        self.assertEqual(first["submitted_urls"], "1852")
        self.assertEqual(first["submitted_by_type"], "image=12;web=1840")
        second = dict(zip(columns, rows[1]))
        self.assertEqual(second["last_downloaded"], "")
        self.assertEqual(second["errors"], "")
