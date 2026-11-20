"""GA4 property setup and field compatibility, read-only. Cards #133, #134.

Fakes stand in for upstream's clients. The shapes were taken from live
responses on 2026-10-07; so was the one thing these tools cannot do -- change
history, which Google gates behind the analytics.edit scope even to read.
"""

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "companion"))

import ga_admin

NS = types.SimpleNamespace


def _enum(name):
    return NS(name=name)


def _compat(api, verdict, ui=None):
    return NS(dimension_metadata=NS(api_name=api, ui_name=ui or api),
              metric_metadata=NS(api_name=api, ui_name=ui or api),
              compatibility=_enum(verdict))


class _DataClient:
    def __init__(self, dims, mets):
        self.dims, self.mets, self.request = dims, mets, None

    def check_compatibility(self, request):
        self.request = request
        return NS(dimension_compatibilities=self.dims,
                  metric_compatibilities=self.mets)


class TestCompatibility(unittest.TestCase):
    def _client(self):
        return _DataClient(
            [_compat("pagePath", "COMPATIBLE"),
             _compat("firstUserSource", "INCOMPATIBLE", "First user source"),
             _compat("sessionSource", "COMPATIBLE", "Session source"),
             _compat("date", "COMPATIBLE")],
            [_compat("sessions", "COMPATIBLE"),
             _compat("itemRevenue", "INCOMPATIBLE")])

    def test_only_the_requested_fields_are_reported(self):
        # The live response rates every field on the property: 168 KB.
        out = ga_admin.check_compatibility(
            "1", ["pagePath", "firstUserSource"], ["sessions", "itemRevenue"],
            client=self._client())
        self.assertEqual(out["requested"], {
            "pagePath": "COMPATIBLE", "firstUserSource": "INCOMPATIBLE",
            "sessions": "COMPATIBLE", "itemRevenue": "INCOMPATIBLE"})
        self.assertFalse(out["all_compatible"])
        self.assertNotIn("date", json.dumps(out["requested"]))

    def test_a_differently_cased_field_gets_its_verdict_and_spelling(self):
        # Measured: GA4 rated "pagepath" under pagePath.
        out = ga_admin.check_compatibility("1", ["pagepath"], ["sessions"],
                                           client=self._client())
        self.assertEqual(out["requested"]["pagepath"],
                         "COMPATIBLE (GA4 spells it pagePath)")
        self.assertTrue(out["all_compatible"])

    def test_a_field_google_did_not_rate_is_called_unknown(self):
        out = ga_admin.check_compatibility(
            "1", ["customEvent:thing"], ["sessions"], client=self._client())
        self.assertIn("UNKNOWN", out["requested"]["customEvent:thing"])

    def test_suggest_lists_compatible_fields_matching_a_substring(self):
        out = ga_admin.check_compatibility(
            "1", ["pagePath"], ["sessions"], suggest="source",
            client=self._client())
        self.assertEqual(out["compatible_matching"]["dimensions"],
                         ["sessionSource"])

    def test_no_suggestions_unless_asked(self):
        out = ga_admin.check_compatibility("1", ["pagePath"], ["sessions"],
                                           client=self._client())
        self.assertNotIn("compatible_matching", out)

    def test_the_request_carries_the_fields_and_filter(self):
        c = self._client()
        ga_admin.check_compatibility(
            "1", ["pagePath"], ["sessions"], client=c,
            dimension_filter={"filter": {"fieldName": "hostName",
                                         "stringFilter": {"value": "x"}}})
        self.assertEqual(c.request.property, "properties/1")
        self.assertEqual([d.name for d in c.request.dimensions], ["pagePath"])
        self.assertEqual(c.request.dimension_filter.filter.field_name,
                         "hostName")


class _ClashingClient:
    """Models the live API: a request whose own fields clash is refused.

    Measured 2026-10-07 -- pagePath with itemRevenue and purchaseRevenue:
    "400 The dimensions and metrics are incompatible." Asked about one field
    alone, it rates every other field against that one.
    """

    CLASH = {frozenset({"pagePath", "itemRevenue"})}
    FIELDS = (["pagePath", "date"], ["itemRevenue", "purchaseRevenue"])

    def __init__(self):
        self.calls = 0

    def _ok(self, a, b):
        return frozenset({a, b}) not in self.CLASH

    def check_compatibility(self, request):
        self.calls += 1
        asked = ([d.name for d in request.dimensions]
                 + [m.name for m in request.metrics])
        if any(not self._ok(a, b) for a in asked for b in asked):
            raise RuntimeError(
                "400 The dimensions and metrics are incompatible.")

        def rate(name):
            ok = all(self._ok(name, a) for a in asked)
            return _compat(name, "COMPATIBLE" if ok else "INCOMPATIBLE")
        dims, mets = self.FIELDS
        return NS(dimension_compatibilities=[rate(d) for d in dims],
                  metric_compatibilities=[rate(m) for m in mets])


class TestCompatibilityWhenTheRequestItselfClashes(unittest.TestCase):
    def test_the_clashing_pair_is_named(self):
        out = ga_admin.check_compatibility(
            "1", ["pagePath"], ["itemRevenue", "purchaseRevenue"],
            client=_ClashingClient())
        self.assertFalse(out["all_compatible"])
        self.assertEqual(out["requested"]["purchaseRevenue"], "COMPATIBLE")
        self.assertEqual(out["conflicts"],
                         {"pagePath": ["itemRevenue"],
                          "itemRevenue": ["pagePath"]})
        self.assertTrue(out["requested"]["pagePath"].startswith(
            "INCOMPATIBLE"))

    def test_a_compatible_request_costs_one_call(self):
        c = _ClashingClient()
        ga_admin.check_compatibility("1", ["date"], ["purchaseRevenue"],
                                     client=c)
        self.assertEqual(c.calls, 1)

    def test_other_errors_are_not_swallowed(self):
        class Denied:
            def check_compatibility(self, request):
                raise RuntimeError("403 permission denied")
        with self.assertRaises(RuntimeError):
            ga_admin.check_compatibility("1", ["date"], ["sessions"],
                                         client=Denied())


class _AdminClient:
    def get_property(self, name):
        return NS(display_name="admissions.example.edu", time_zone="America/Chicago",
                  currency_code="USD", create_time="2023-05-25",
                  industry_category=_enum("JOBS_AND_EDUCATION"))

    def get_data_retention_settings(self, name):
        return NS(event_data_retention=_enum("FOURTEEN_MONTHS"),
                  user_data_retention=_enum("FOURTEEN_MONTHS"),
                  reset_user_data_on_new_activity=True)

    def list_data_streams(self, parent):
        return [NS(type_=_enum("WEB_DATA_STREAM"), display_name="admissions",
                   web_stream_data=NS(measurement_id="G-X",
                                      default_uri="https://admissions.example.edu"),
                   android_app_stream_data=None, ios_app_stream_data=None)]

    def list_key_events(self, parent):
        return [NS(event_name="purchase",
                   counting_method=_enum("ONCE_PER_EVENT"), custom=False)]


class _AlphaClient:
    def list_audiences(self, parent):
        return [NS(display_name="All Users", membership_duration_days=540)]

    def list_channel_groups(self, parent):
        return [NS(display_name="Default channel group", system_defined=True,
                   grouping_rule=["huge"] * 1000)]


class TestPropertySetup(unittest.TestCase):
    def _setup(self, **kw):
        return ga_admin.property_setup("314159265", admin=_AdminClient(),
                                       alpha=_AlphaClient(), **kw)

    def test_every_section_is_there_by_default(self):
        out = self._setup()
        for section in ("property", "data_retention", "data_streams",
                        "key_events", "audiences", "channel_groups"):
            self.assertIn(section, out, section)
        self.assertEqual(out["data_streams"][0]["default_uri"],
                         "https://admissions.example.edu")
        self.assertEqual(out["key_events"][0]["event_name"], "purchase")
        self.assertEqual(out["data_retention"]["event_data_retention"],
                         "FOURTEEN_MONTHS")

    def test_channel_group_rules_are_left_out(self):
        self.assertNotIn("huge", json.dumps(self._setup()))

    def test_sections_can_be_chosen(self):
        out = self._setup(sections=["key_events"])
        self.assertIn("key_events", out)
        self.assertNotIn("audiences", out)

    def test_an_unknown_section_is_refused_with_the_choices(self):
        with self.assertRaises(ValueError) as ctx:
            self._setup(sections=["change_history"])
        msg = str(ctx.exception)
        self.assertIn("key_events", msg)
        self.assertIn("analytics.edit", msg,
                      "change history is the one people will ask for; say why "
                      "it is not here")

    def test_one_failing_section_does_not_lose_the_others(self):
        class Broken(_AlphaClient):
            def list_audiences(self, parent):
                raise RuntimeError("403 nope")
        out = ga_admin.property_setup("1", admin=_AdminClient(),
                                      alpha=Broken())
        self.assertIn("403", out["audiences"]["error"])
        self.assertEqual(out["key_events"][0]["event_name"], "purchase")

    def test_the_result_is_json_serialisable(self):
        json.dumps(self._setup())


if __name__ == "__main__":
    unittest.main()
