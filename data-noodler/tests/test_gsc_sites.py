"""Search Console sites, and the property-type distinction that changes meaning.

This is the GA subdomain rule inverted. sc-domain:example.edu covers every
subdomain; https://example.edu/ covers only that exact prefix. The two look
nearly identical in a list, and getting it wrong produces real numbers for the
wrong scope.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import gsc

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload, status=200):
        self._payload, self._status = payload, status
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return _FakeResponse(self._payload, self._status)


class TestPropertyType(unittest.TestCase):
    def test_sc_domain_prefix_is_a_domain_property(self):
        self.assertEqual(gsc.property_type("sc-domain:example.edu"), "domain")

    def test_an_https_url_is_a_url_prefix_property(self):
        self.assertEqual(gsc.property_type("https://example.edu/"), "url_prefix")

    def test_an_http_url_is_also_a_url_prefix_property(self):
        self.assertEqual(gsc.property_type("http://example.edu/"), "url_prefix")


class TestListSites(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(FIXTURES, "gsc_sites.json")) as f:
            self.payload = json.load(f)

    def test_returns_every_site(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload))
        self.assertEqual(len(sites), 3)

    def test_each_site_carries_its_type(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload))
        by_url = {s["site_url"]: s for s in sites}
        self.assertEqual(by_url["sc-domain:example.edu"]["type"], "domain")
        self.assertEqual(by_url["https://example.edu/"]["type"], "url_prefix")

    def test_coverage_is_spelled_out_not_left_to_be_inferred(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload))
        by_url = {s["site_url"]: s for s in sites}
        self.assertIn("subdomain", by_url["sc-domain:example.edu"]["covers"])
        self.assertIn("only", by_url["https://example.edu/"]["covers"].lower())

    def test_a_domain_property_says_subdomains_ARE_covered(self):
        # Direction, not vocabulary. Asserting only that the word
        # "subdomain" appears would accept "no subdomains are included" for
        # an sc-domain: property -- an inverted rule passing its own test,
        # which is the most expensive way this can be wrong.
        covers = gsc._covers("sc-domain:example.edu").lower()
        self.assertIn("all subdomains", covers)
        self.assertNotIn("not included", covers)
        self.assertNotIn("excluded", covers)

    def test_a_url_prefix_property_says_subdomains_are_NOT_covered(self):
        covers = gsc._covers("https://example.edu/").lower()
        self.assertIn("not included", covers)
        self.assertNotIn("all subdomains", covers)

    def test_the_two_property_types_never_describe_the_same_coverage(self):
        self.assertNotEqual(gsc._covers("sc-domain:example.edu"),
                            gsc._covers("https://example.edu/"))

    def test_a_domain_property_says_both_protocols(self):
        self.assertIn("http and https", gsc._covers("sc-domain:example.edu"))

    def test_a_url_prefix_coverage_names_the_protocol_it_is_bound_to(self):
        # An https prefix property reports the site's http URLs as absent,
        # which an agent reads as unindexed.
        self.assertIn("https://example.edu/", gsc._covers("https://example.edu/"))

    def test_permission_level_is_preserved(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload))
        by_url = {s["site_url"]: s for s in sites}
        self.assertEqual(by_url["sc-domain:example.edu"]["permission_level"],
                         "siteOwner")

    def test_an_empty_account_returns_an_empty_list_not_an_error(self):
        self.assertEqual(gsc.list_sites(session=_FakeSession({})), [])

    def test_it_calls_the_sites_endpoint(self):
        s = _FakeSession(self.payload)
        gsc.list_sites(session=s)
        method, url, _ = s.calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("/webmasters/v3/sites"))


class TestListSitesContainsFilter(unittest.TestCase):
    """contains scopes both the listing and, critically, enrichment -- the
    request count an agent pays for must follow what the user actually named,
    not the size of the whole account.
    """

    def setUp(self):
        with open(os.path.join(FIXTURES, "gsc_sites.json")) as f:
            self.payload = json.load(f)

    def test_contains_filters_case_insensitively_on_site_url(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload),
                               contains="JOURNALISM")
        self.assertEqual([s["site_url"] for s in sites],
                         ["https://journalism.example.edu/"])

    def test_empty_contains_behaves_exactly_as_today(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload),
                               contains="")
        self.assertEqual(len(sites), 3)

    def test_a_contains_matching_nothing_returns_empty_list_without_error(self):
        sites = gsc.list_sites(session=_FakeSession(self.payload),
                               contains="nonexistent-domain")
        self.assertEqual(sites, [])

    def test_enrichment_runs_only_over_the_filtered_subset(self):
        impressions = {
            "sc-domain:example.edu": 41000,
            "https://example.edu/": 900,
            "https://journalism.example.edu/": 7,
        }
        s = _RoutingSession(self.payload, impressions)
        sites = gsc.list_sites(session=s, contains="example.edu",
                               enrich=True)
        # "example.edu" matches all three -- narrow it further so the subset
        # is smaller than the account, and prove the call count follows.
        self.assertEqual(len(s.analytics_calls), 3)

        s2 = _RoutingSession(self.payload, impressions)
        sites2 = gsc.list_sites(session=s2, contains="journalism",
                                enrich=True)
        self.assertEqual(len(sites2), 1)
        self.assertEqual(len(s2.analytics_calls), 1)

    def test_enrich_false_with_contains_makes_no_impression_calls(self):
        impressions = {
            "sc-domain:example.edu": 41000,
            "https://example.edu/": 900,
            "https://journalism.example.edu/": 7,
        }
        s = _RoutingSession(self.payload, impressions)
        sites = gsc.list_sites(session=s, contains="example.edu", enrich=False)
        self.assertEqual(s.analytics_calls, [])
        self.assertEqual(len(sites), 3)


class _RoutingSession:
    """Answers the sites listing from a fixture and each analytics query from
    a per-site impression count, so enrichment can be exercised without a
    live credential. A site mapped to an Exception raises it.
    """

    def __init__(self, sites_payload, impressions):
        self._sites = sites_payload
        self._impressions = impressions
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if url.endswith("/webmasters/v3/sites"):
            return _FakeResponse(self._sites)

        from urllib.parse import unquote
        site = unquote(url.split("/sites/")[1].split("/")[0])
        value = self._impressions.get(site, 0)
        if isinstance(value, Exception):
            raise value
        return _FakeResponse({"rows": [
            {"keys": [], "clicks": 1, "impressions": value, "ctr": 0.1,
             "position": 3.0}]})

    @property
    def analytics_calls(self):
        return [c for c in self.calls if "searchAnalytics" in c[1]]


class TestListSitesEnrichment(unittest.TestCase):
    """Impressions are the only thing that distinguishes a live property from
    one verified and forgotten -- and the two forms of the same site
    (sc-domain: against a URL prefix) look nearly identical in a listing.
    """

    def setUp(self):
        with open(os.path.join(FIXTURES, "gsc_sites.json")) as f:
            self.payload = json.load(f)
        self.impressions = {
            "sc-domain:example.edu": 41000,
            "https://example.edu/": 900,
            "https://journalism.example.edu/": 0,
        }

    def test_enrichment_adds_impressions_per_site(self):
        s = _RoutingSession(self.payload, self.impressions)
        sites = gsc.list_sites(session=s, enrich=True)
        by_url = {x["site_url"]: x for x in sites}
        self.assertEqual(by_url["sc-domain:example.edu"]["impressions"], 41000)
        self.assertEqual(by_url["https://example.edu/"]["impressions"], 900)
        self.assertEqual(
            by_url["https://journalism.example.edu/"]["impressions"], 0)

    def test_enrichment_makes_one_analytics_call_per_site(self):
        s = _RoutingSession(self.payload, self.impressions)
        gsc.list_sites(session=s, enrich=True)
        self.assertEqual(len(s.analytics_calls), 3)

    def test_enrich_false_makes_no_extra_calls(self):
        s = _RoutingSession(self.payload, self.impressions)
        sites = gsc.list_sites(session=s)
        self.assertEqual(s.analytics_calls, [])
        self.assertNotIn("impressions", sites[0])

    def test_a_failing_site_degrades_to_unknown_without_aborting(self):
        # A restricted-permission property, or one whose verification
        # lapsed, can be listed but not queried. The listing is the thing
        # the user needs most; losing it to one site's 403 would be worse
        # than losing that site's number.
        impressions = dict(self.impressions)
        impressions["https://example.edu/"] = gsc.GscError(
            "Search Console returned 403: User does not have sufficient "
            "permission for site")
        s = _RoutingSession(self.payload, impressions)
        sites = gsc.list_sites(session=s, enrich=True)
        by_url = {x["site_url"]: x for x in sites}
        self.assertEqual(len(sites), 3)
        self.assertIsNone(by_url["https://example.edu/"]["impressions"])
        self.assertIn("403", by_url["https://example.edu/"]["impressions_error"])
        # The sites either side of the failure keep their numbers.
        self.assertEqual(by_url["sc-domain:example.edu"]["impressions"], 41000)
        self.assertEqual(
            by_url["https://journalism.example.edu/"]["impressions"], 0)

    def test_an_unknown_count_is_never_reported_as_zero(self):
        # Zero is the answer this enrichment exists to detect. Rendering a
        # failure as zero would turn a permission problem into a confident
        # claim that the property is dead.
        impressions = {"sc-domain:example.edu": RuntimeError("boom")}
        s = _RoutingSession(self.payload, impressions)
        sites = gsc.list_sites(session=s, enrich=True)
        first = sites[0]
        self.assertIsNone(first["impressions"])
        self.assertNotEqual(first["impressions"], 0)
        self.assertTrue(first["impressions_error"])

    def test_a_message_less_failure_still_yields_a_showable_reason(self):
        impressions = {"sc-domain:example.edu": RuntimeError()}
        s = _RoutingSession(self.payload, impressions)
        sites = gsc.list_sites(session=s, enrich=True)
        self.assertIn("RuntimeError", sites[0]["impressions_error"])

    def test_the_window_ends_yesterday_because_the_data_lags(self):
        import datetime
        start, end = gsc.impressions_window(
            days=28, today=datetime.date(2026, 9, 3))
        self.assertEqual(end, "2026-09-02")
        self.assertEqual(start, "2026-08-06")

    def test_each_entry_records_the_window_its_number_covers(self):
        import datetime
        s = _RoutingSession(self.payload, self.impressions)
        sites = gsc.list_sites(session=s, enrich=True,
                               today=datetime.date(2026, 9, 3))
        self.assertEqual(sites[0]["impressions_range"],
                         {"start": "2026-08-06", "end": "2026-09-02"})


class TestSiteImpressions(unittest.TestCase):
    def test_it_queries_with_no_dimensions_and_a_row_limit(self):
        s = _RoutingSession({}, {"sc-domain:example.edu": 5})
        gsc.site_impressions("sc-domain:example.edu", session=s)
        _, _, kw = s.analytics_calls[0]
        self.assertEqual(kw["json"]["dimensions"], [])
        # One row of totals is all this needs; it must not paginate a
        # whole domain property to count impressions for a listing.
        self.assertEqual(kw["json"]["rowLimit"], 2)


class TestCallErrors(unittest.TestCase):
    def test_a_403_preserves_googles_message(self):
        payload = {"error": {"code": 403, "message":
                   "Search Console API has not been used in project 123 "
                   "before or it is disabled."}}
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/webmasters/v3/sites",
                     session=_FakeSession(payload, status=403))
        self.assertIn("has not been used", str(ctx.exception))

    def test_a_429_names_the_quota(self):
        payload = {"error": {"code": 429, "message": "Quota exceeded"}}
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/webmasters/v3/sites",
                     session=_FakeSession(payload, status=429))
        self.assertIn("quota", str(ctx.exception).lower())

    def test_a_non_json_error_body_still_raises_cleanly(self):
        class Broken(_FakeSession):
            def request(self, method, url, **kw):
                r = _FakeResponse({}, status=500)
                r.json = lambda: (_ for _ in ()).throw(ValueError("no json"))
                r.text = "<html>gateway error</html>"
                return r
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/x", session=Broken({}))
        self.assertIn("500", str(ctx.exception))

    def test_a_bare_json_list_raises_gsc_error_not_attribute_error(self):
        """Whatever answered returned a JSON array, not an object -- a proxy
        page, a captive portal, or an API change. call() must reject this
        itself so every caller doing data.get(...) can trust the result is
        a dict, instead of raising a bare AttributeError deep inside a
        caller that has no idea what went wrong."""
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/webmasters/v3/sites",
                     session=_FakeSession([1, 2, 3], status=200))
        self.assertNotIsInstance(ctx.exception, AttributeError)


class TestPermissionDiagnostics(unittest.TestCase):
    def test_a_403_names_both_the_scope_and_site_verification(self):
        payload = {"error": {"code": 403, "message":
                   "User does not have sufficient permission for site"}}
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/webmasters/v3/sites",
                     session=_FakeSession(payload, status=403))
        msg = str(ctx.exception).lower()
        self.assertIn("webmasters.readonly", msg)
        self.assertIn("verified owner", msg)
        # Google's own message must survive alongside the diagnosis.
        self.assertIn("sufficient permission", msg)

    def test_a_404_gets_no_permission_lecture(self):
        payload = {"error": {"code": 404, "message": "Not found"}}
        with self.assertRaises(gsc.GscError) as ctx:
            gsc.call("GET", gsc.BASE + "/x",
                     session=_FakeSession(payload, status=404))
        self.assertNotIn("verified owner", str(ctx.exception).lower())
