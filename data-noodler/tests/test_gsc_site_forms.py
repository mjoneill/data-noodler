"""#2000: one site in several Search Console forms is the user's choice.

Michael, 2026-11-20: "when working in GSC to always double-check whether the
user wants the domain data or the property data (if both a domain and a
property exist). This should be extended to disambiguate between domain and
http and https versions of a propoerty if all three exist."

What happened: asked about a site listed as sc-domain:, https:// and http://,
the agent picked the domain itself and reported from it. The three cover
different URLs, so each is a different answer. lookup_property already says
AMBIGUOUS for GA; Search Console said nothing, and its tool doc told the
agent the forms' `type` and `covers` "tell you which form ... is the one
they mean" -- an invitation to infer.
"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import gsc  # noqa: E402
import guidance  # noqa: E402
import data_noodler  # noqa: E402

SKILL_MD = os.path.join(ROOT, "marketplace", "plugins", "data-noodler",
                        "skills", "data-noodler", "SKILL.md")


def _site(url):
    return {"site_url": url, "permission_level": "siteOwner",
            "type": gsc.property_type(url), "covers": gsc._covers(url)}


THREE = ["https://example.com/", "sc-domain:example.com", "http://example.com/"]


class TheFormsOfOneSiteAreGrouped(unittest.TestCase):
    def test_domain_https_and_http_are_one_site(self):
        groups = gsc.site_form_groups([_site(u) for u in THREE])
        self.assertEqual(list(groups), ["example.com"])
        self.assertEqual(sorted(groups["example.com"]), sorted(THREE))

    def test_domain_and_one_prefix_are_one_site(self):
        groups = gsc.site_form_groups(
            [_site("sc-domain:example.com"), _site("https://example.com/")])
        self.assertEqual(list(groups), ["example.com"])

    def test_http_and_https_without_a_domain_are_one_site(self):
        groups = gsc.site_form_groups(
            [_site("http://example.com/"), _site("https://example.com/")])
        self.assertEqual(list(groups), ["example.com"])

    def test_www_folds_into_the_bare_host(self):
        groups = gsc.site_form_groups(
            [_site("sc-domain:example.com"), _site("https://www.example.com/")])
        self.assertEqual(sorted(groups["example.com"]),
                         ["https://www.example.com/", "sc-domain:example.com"])

    def test_an_institution_is_many_sites_not_one(self):
        # Indigo's shape A. Keyed on the covering domain, all five landed in
        # one "example.edu" group, though admissions does not cover the
        # homepage. Each host is its own question.
        groups = gsc.site_form_groups([_site(u) for u in (
            "sc-domain:example.edu", "https://example.edu/",
            "https://journalism.example.edu/",
            "https://admissions.example.edu/", "http://admissions.example.edu/")])
        self.assertEqual(sorted(groups), ["admissions.example.edu",
                                          "example.edu", "journalism.example.edu"])
        self.assertEqual(sorted(groups["example.edu"]),
                         ["https://example.edu/", "sc-domain:example.edu"])
        self.assertEqual(sorted(groups["admissions.example.edu"]),
                         ["http://admissions.example.edu/",
                          "https://admissions.example.edu/",
                          "sc-domain:example.edu"])

    def test_nested_domain_properties_meet_on_the_inner_host(self):
        # Indigo's shape B: both cover journalism.example.edu.
        groups = gsc.site_form_groups(
            [_site("sc-domain:example.edu"),
             _site("sc-domain:journalism.example.edu")])
        self.assertEqual(list(groups), ["journalism.example.edu"])
        self.assertEqual(len(groups["journalism.example.edu"]), 2)

    def test_a_path_prefix_is_another_form_of_its_host(self):
        # Indigo's shape C: for the blog they give different answers.
        groups = gsc.site_form_groups(
            [_site("https://example.com/"), _site("https://example.com/blog/")])
        self.assertEqual(len(groups["example.com"]), 2)

    def test_one_form_is_not_ambiguous(self):
        self.assertEqual(gsc.site_form_groups(
            [_site("sc-domain:example.com"), _site("https://other.org/")]), {})

    def test_unrelated_sites_never_group(self):
        self.assertEqual(gsc.site_form_groups(
            [_site("https://example.com/"), _site("https://example.org/")]), {})


class TheListingSaysAsk(unittest.TestCase):
    def _listing(self, urls):
        with mock.patch.object(gsc, "list_sites",
                               return_value=[_site(u) for u in urls]):
            return data_noodler.gsc_list_sites(contains="example")

    def test_three_forms_print_ambiguous_and_ask(self):
        out = self._listing(THREE)
        self.assertIn("AMBIGUOUS", out)
        self.assertIn("example.com", out)
        self.assertIn("ask the user which", out)
        for url in THREE:
            self.assertIn(url, out)

    def test_one_form_prints_no_ambiguity(self):
        out = self._listing(["sc-domain:example.com"])
        self.assertNotIn("AMBIGUOUS", out)

    def test_a_large_account_gets_one_line_not_hundreds(self):
        urls = ["sc-domain:example.edu"] + [
            f"https://dept{i}.example.edu/" for i in range(40)]
        out = self._listing(urls)
        self.assertEqual(out.count("AMBIGUOUS"), 1)
        self.assertIn("40 sites", out)
        self.assertIn("contains=", out)
        self.assertIn("ask the user which", out)


class EveryChannelSaysAsk(unittest.TestCase):
    """The rule reaches the agent through several texts; any one may be the
    only one a given app shows, so each must carry it."""

    def _texts(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        texts = {"instructions": guidance.SERVER_INSTRUCTIONS,
                 "reporting_guide('gsc')": guidance.guide_for("gsc"),
                 "gsc_list_sites doc": guidance.GSC_TOOL_DOCS["gsc_list_sites"],
                 "gsc_search_analytics doc":
                     guidance.GSC_TOOL_DOCS["gsc_search_analytics"],
                 "skill": skill}
        return {k: " ".join(v.split()) for k, v in texts.items()}

    def test_each_says_ask_which_form(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("ask the user which", t)

    def test_the_invitation_to_infer_is_gone(self):
        doc = " ".join(guidance.GSC_TOOL_DOCS["gsc_list_sites"].split())
        self.assertNotIn("is the one they mean", doc)


if __name__ == "__main__":
    unittest.main()
