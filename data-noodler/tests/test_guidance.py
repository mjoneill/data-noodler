"""The guidance text carries the rules that keep GA answers honest.

Asserted rather than trusted because this text is the only thing steering a
harness with no skill installed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import guidance


# Some clients truncate or drop long server instructions. The one cut-off with
# a number behind it is Claude Code's: its users report that it keeps the first
# 2,048 characters and drops the rest (reported in its issue tracker; Anthropic
# does not document it, and other apps' limits have not been measured). The cap
# here stays well under that, so a rule added later fails this test before it
# is cut off in a client. It was 1,200 until #2117, a number chosen by feel.
INSTRUCTIONS_CAP = 1800


class TestGuidance(unittest.TestCase):
    def test_reporting_guide_demands_property_metric_and_range(self):
        g = guidance.REPORTING_GUIDE
        self.assertIn("property ID", g)
        self.assertIn("metric", g)
        self.assertIn("date range", g)

    def test_reporting_guide_warns_there_is_no_visitors_metric(self):
        self.assertIn("no \"visitors\" metric", guidance.REPORTING_GUIDE)

    def test_reporting_guide_covers_the_subdomain_trap(self):
        self.assertIn("subdomain", guidance.REPORTING_GUIDE.lower())

    def test_reporting_guide_separates_dns_failures_from_auth_failures(self):
        g = guidance.REPORTING_GUIDE
        self.assertIn("invalid_grant", g)
        self.assertIn("GRPC_DNS_RESOLVER", g)

    def test_server_instructions_are_short_enough_to_be_surfaced(self):
        self.assertLess(len(guidance.SERVER_INSTRUCTIONS), INSTRUCTIONS_CAP)

    def test_lookup_tool_doc_tells_the_model_to_prefer_it(self):
        self.assertIn("get_account_summaries", guidance.LOOKUP_TOOL_DOC)


class TestReportingGuideTimeouts(unittest.TestCase):
    """A timed-out call is a transport hiccup, not a crashed connector process
    -- there is no such process. This is a third named failure mode, alongside
    DNS and invalid_grant."""

    def test_there_is_a_dedicated_timeout_section(self):
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("retry", section.lower())

    def test_says_there_is_no_separate_connector_process(self):
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("no separate", section.lower())
        self.assertIn("stdio child process", section.lower())

    def test_gives_measured_timings(self):
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("0.6s", section)
        self.assertIn("1s", section)
        self.assertIn("0.2s", section)
        self.assertIn("1.5s", section)
        self.assertIn("2,300", section)

    def test_says_to_retry_once_then_check_credential_status(self):
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("retry once", section.lower())
        self.assertIn("credential_status", section)

    def test_forbids_diagnosing_a_crash_from_one_timeout(self):
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("do not tell the user to restart", section.lower())

    def test_distinguishes_genuine_restart_need_from_a_single_timeout(self):
        # A restart is sometimes the right call -- after re-minting a
        # credential or reinstalling the payload -- but that is a different
        # symptom (consistent failures) from one timeout.
        section = _section_for(guidance.REPORTING_GUIDE, "timeout")
        self.assertIn("consistent failures", section.lower())


def _bullet_for(text, marker):
    """The one bullet of `text` that mentions `marker`, unwrapped.

    Directional assertions have to read a bullet, not the whole document:
    every document here contains both "ALL subdomains" and "subdomains are
    excluded", so a document-wide search proves nothing about which rule was
    attached to which property type -- and an inverted rewrite would pass.
    """
    bullets, current = [], None
    for line in text.splitlines():
        if line.startswith("- "):
            if current is not None:
                bullets.append(current)
            current = line[2:]
        elif current is not None and line.startswith("  "):
            current += " " + line.strip()
        elif current is not None:
            bullets.append(current)
            current = None
    if current is not None:
        bullets.append(current)
    found = [b for b in bullets if marker in b]
    assert len(found) == 1, f"expected exactly one bullet naming {marker!r}"
    return found[0]


def _section_for(text, marker):
    """The one "## " section of `text` whose heading contains `marker`.

    Isolates a heading and everything up to (not including) the next "## "
    heading, so a section-level assertion cannot be satisfied by some other
    section of the same document that happens to share a word.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines)
              if line.startswith("## ") and marker in line]
    assert len(starts) == 1, f"expected exactly one section heading naming {marker!r}"
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines))
               if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


class TestGscGuide(unittest.TestCase):
    def test_carries_the_domain_versus_prefix_trap(self):
        g = guidance.GSC_GUIDE
        self.assertIn("sc-domain:", g)
        self.assertIn("subdomain", g.lower())

    def test_says_the_trap_is_inverted_from_ga(self):
        # Someone carrying GA intuition across will assume separation.
        self.assertIn("opposite", guidance.GSC_GUIDE.lower())

    def test_a_domain_property_is_said_to_INCLUDE_subdomains(self):
        # Direction, not vocabulary. The rule lives in four places and every
        # test of it was a substring search for the word "subdomain", so a
        # rewrite that inverted the rule would have passed all of them.
        bullet = _bullet_for(guidance.GSC_GUIDE, "sc-domain:").lower()
        self.assertIn("all subdomains", bullet)
        self.assertNotIn("not included", bullet)
        self.assertNotIn("excluded", bullet)

    def test_a_url_prefix_property_is_said_to_EXCLUDE_subdomains(self):
        bullet = _bullet_for(guidance.GSC_GUIDE, "`https://example.edu/`").lower()
        self.assertIn("subdomains are excluded", bullet)
        self.assertNotIn("all subdomains", bullet)

    def test_a_url_prefix_property_is_said_to_be_protocol_specific(self):
        # An https prefix property reports legacy http URLs as absent, and an
        # agent reads absent as unindexed.
        bullet = _bullet_for(guidance.GSC_GUIDE, "`https://example.edu/`")
        self.assertIn("http://", bullet)
        self.assertIn("protocol", bullet.lower())

    def test_a_domain_property_is_said_to_cover_both_protocols(self):
        bullet = _bullet_for(guidance.GSC_GUIDE, "sc-domain:").lower()
        self.assertIn("http and https", bullet)

    def test_distinguishes_the_two_not_indexed_states(self):
        g = guidance.GSC_GUIDE
        self.assertIn("Crawled", g)
        self.assertIn("Discovered", g)

    def test_coverage_states_are_spelled_with_the_apis_plain_hyphen(self):
        # The API emits U+002D. A guide written with an em dash teaches a
        # spelling that matches zero rows when an agent filters the export
        # on it -- the document manufacturing the silent failure it exists
        # to prevent. Both the guide and the tool description reach the model.
        for label, text in (("guide", guidance.GSC_GUIDE),
                            ("tool doc",
                             guidance.GSC_TOOL_DOCS["gsc_inspect_urls"])):
            with self.subTest(text=label):
                self.assertIn("Crawled - currently not indexed", text)
                self.assertIn("Discovered - currently not indexed", text)
                self.assertNotIn("Crawled — currently not indexed", text)
                self.assertNotIn("Discovered — currently not indexed", text)
                self.assertNotIn("— currently not indexed", text)

    def test_states_the_data_lag_and_what_data_state_means(self):
        g = guidance.GSC_GUIDE
        self.assertIn("data_state", g)
        self.assertIn("final", g)

    def test_covers_canonical_mismatch(self):
        self.assertIn("canonical", guidance.GSC_GUIDE.lower())

    def test_says_request_indexing_has_no_api(self):
        self.assertIn("Request Indexing", guidance.GSC_GUIDE)

    def test_warns_the_two_sources_do_not_share_identifiers(self):
        self.assertIn("page_path", guidance.GSC_GUIDE)


class TestGscToolDocs(unittest.TestCase):
    """The tool descriptions reach the model on every listing, whether or not
    a client surfaces server instructions -- so the rule has to be right in
    them too, and right in the same direction."""

    def test_list_sites_doc_attaches_inclusion_to_the_domain_property(self):
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        domain_at = doc.index("sc-domain:example.edu")
        prefix_at = doc.index("URL-prefix")
        self.assertLess(domain_at, prefix_at)
        self.assertIn("includes every subdomain",
                      " ".join(doc[domain_at:prefix_at].split()))
        self.assertIn("includes none", " ".join(doc[prefix_at:].split()))

    def test_list_sites_doc_says_the_rule_is_inverted_from_ga(self):
        self.assertIn("opposite",
                      guidance.GSC_TOOL_DOCS["gsc_list_sites"].lower())

    def test_list_sites_doc_advertises_enrichment_and_what_it_is_for(self):
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        self.assertIn("enrich=true", doc)
        self.assertIn("impressions", doc)

    def test_list_sites_doc_says_skip_enrich_for_a_named_site(self):
        # The actual failure: a named site does not need enrich at all --
        # one bare call to find the exact identifier, then straight to
        # gsc_search_analytics. That is one request instead of hundreds.
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        self.assertIn("gsc_search_analytics", doc)
        self.assertIn("named", doc.lower())
        self.assertIn("do not call", doc.lower())

    def test_list_sites_doc_names_the_per_site_request_cost(self):
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        self.assertIn("one", doc.lower())
        self.assertIn("request per site", doc.lower())
        # The concrete, felt cost -- not just an abstract "expensive".
        self.assertIn("spinner", doc.lower())

    def test_list_sites_doc_tells_the_model_to_scope_with_contains(self):
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        self.assertIn("contains=", doc)
        self.assertIn("filtered subset", doc.lower())

    def test_list_sites_doc_says_enrich_is_for_genuine_ambiguity(self):
        doc = guidance.GSC_TOOL_DOCS["gsc_list_sites"]
        self.assertIn("ambiguous", doc.lower())
        self.assertIn("not the default", doc.lower())

    def test_export_report_doc_documents_the_hostnames_parameter(self):
        # hostnames was undocumented, and its only effect is to write
        # single_host into a permanent provenance record. An agent passing
        # the one host it wants labels a 40-host export as single-host.
        doc = guidance.GSC_TOOL_DOCS["export_report"]
        self.assertIn("hostnames", doc)
        self.assertIn("hostnames_observed", doc)
        self.assertIn("not the one you want", doc)

    def test_export_report_doc_documents_the_dimension_filter(self):
        doc = guidance.GSC_TOOL_DOCS["export_report"]
        self.assertIn("dimension_filter", doc)
        self.assertIn("hostName", doc)

    def test_export_report_doc_points_at_preview_rows_not_a_row_limit(self):
        # The mechanism for "show me a few" is preview_rows (capped at 20),
        # not a smaller export -- the file always gets the complete result.
        doc = guidance.GSC_TOOL_DOCS["export_report"]
        paragraphs = doc.split("\n\n")
        found = [p for p in paragraphs if "preview_rows" in p]
        self.assertEqual(len(found), 1)
        para = " ".join(found[0].split()).lower()
        self.assertIn("20", para)
        self.assertIn("complete", para)

    def test_gsc_search_analytics_doc_says_what_row_limit_is_for(self):
        # row_limit guards against an unbounded query on a large property; it
        # is not how you choose what to report -- that is the file, sorted
        # (#1992 review: no longer preview_rows, which is in export order).
        doc = guidance.GSC_TOOL_DOCS["gsc_search_analytics"]
        self.assertIn("row_limit", doc)
        self.assertIn("from the file", " ".join(doc.split()))
        self.assertIn("unbounded", doc.lower())


class TestBehavioralContract(unittest.TestCase):
    def test_tells_the_agent_to_propose_a_session_path(self):
        self.assertIn("start_session", guidance.BEHAVIORAL_CONTRACT)

    def test_forbids_confirming_by_property_id_alone(self):
        c = guidance.BEHAVIORAL_CONTRACT.lower()
        self.assertIn("never", c)
        self.assertIn("property id", c)

    def test_requires_asking_about_multi_host_properties(self):
        self.assertIn("hostname", guidance.BEHAVIORAL_CONTRACT.lower())

    def test_requires_exporting_rather_than_reading_large_results(self):
        self.assertIn("export", guidance.BEHAVIORAL_CONTRACT.lower())

    def test_extends_export_discipline_to_listing_tools(self):
        # gsc_list_sites with enrich=true on a large account is itself a
        # large result -- the same discipline that governs exporting rows
        # applies to listing them.
        c = guidance.BEHAVIORAL_CONTRACT.lower()
        self.assertIn("gsc_list_sites", c)
        self.assertIn("resolve", c)

    def test_forbids_truncating_a_result_before_exporting_it(self):
        # An agent that pulls the data and writes only the top 20 of N rows
        # has paid the context cost export_report exists to avoid, and
        # produced a file that looks authoritative and silently isn't.
        bullet = _bullet_for(guidance.BEHAVIORAL_CONTRACT, "top N")
        self.assertIn("complete", bullet.lower())
        self.assertIn("preview", bullet.lower())


class TestGuideFor(unittest.TestCase):
    # #1992: each single-source topic also carries the working rules, so
    # reporting_guide("ga") can't skip "export the full data".
    def test_ga_returns_the_ga_guide_and_the_working_rules(self):
        ga = guidance.guide_for("ga")
        self.assertTrue(ga.startswith(guidance.REPORTING_GUIDE))
        self.assertIn(guidance.BEHAVIORAL_CONTRACT, ga)

    def test_gsc_returns_the_gsc_guide_and_the_working_rules(self):
        gsc = guidance.guide_for("gsc")
        self.assertTrue(gsc.startswith(guidance.GSC_GUIDE))
        self.assertIn(guidance.BEHAVIORAL_CONTRACT, gsc)

    def test_both_contains_each_of_them(self):
        both = guidance.guide_for("both")
        self.assertIn(guidance.REPORTING_GUIDE, both)
        self.assertIn(guidance.GSC_GUIDE, both)

    def test_an_unknown_topic_returns_both_rather_than_failing(self):
        self.assertEqual(guidance.guide_for("nonsense"),
                         guidance.guide_for("both"))


class TestRoutingRuleIsWhereClaudeCodeLooks(unittest.TestCase):
    """Issue #1: the advice to use export_report was in the wrong channel.

    This module assumed tool descriptions always reach the model and server
    instructions might not. In Claude Code it is the reverse. Tools are
    DEFERRED: at session start the model sees only tool names, and a tool's
    description loads once the tool has been chosen. Server instructions are in
    context all session.

    So the advice "use export_report, not run_report" lived only in
    export_report's own description -- text a model reads after it has already
    picked a tool by name, and "run_report" reads as "run a query". A field
    agent did exactly that, got 200 of 354 rows, and nearly reported from it.

    Corroborated independently: the agent that fixed this saw the same thing in
    its own session -- data-noodler's full server instructions at start-up, and
    its tools listed as names only.
    """

    def setUp(self):
        self.s = guidance.SERVER_INSTRUCTIONS

    def test_server_instructions_name_the_safe_tool(self):
        self.assertIn("export_report", self.s)

    def test_server_instructions_warn_that_run_report_truncates(self):
        self.assertIn("run_report", self.s)
        self.assertIn("row_count", self.s,
                      "the check that reveals truncation must be named, not "
                      "just the fact that it can happen")
        self.assertIn("TRUNCATED", self.s)

    def test_server_instructions_cover_search_console_too(self):
        # The server serves both; a header naming only GA4 undersells half.
        self.assertIn("Search Console", self.s)

    def test_still_short_enough_to_survive_a_truncating_client(self):
        self.assertLess(len(self.s), INSTRUCTIONS_CAP)

    def test_the_module_no_longer_claims_descriptions_always_arrive(self):
        # The assumption that produced #1. Leaving it in the docstring would
        # invite the next change to move rules back out of the instructions.
        self.assertNotIn("which always reaches the", guidance.__doc__)


class TestNoInventedCutoffs(unittest.TestCase):
    """The policy, in the channel Claude Code and Desktop both show up front."""

    def setUp(self):
        self.s = guidance.SERVER_INSTRUCTIONS

    def test_says_analysts_want_complete_data(self):
        self.assertIn("complete data", self.s)

    def test_forbids_choosing_a_limit(self):
        self.assertIn("Never choose a row limit", self.s)

    def test_says_ask_above_the_threshold_and_that_the_file_keeps_it_all(self):
        self.assertIn("2,500", self.s)
        self.assertIn("ask", self.s)


SKILL_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "data-noodler",
    "SKILL.md")


class TestExportFirstAnalyzeFromTheFile(unittest.TestCase):
    """#1992, Michael 2026-11-20: export the full data unless explicitly told
    not to, and never analyze truncated data unless the user specifically
    asks. The old text allowed run_report "only for a few rows", and an
    agent judged 78 rows to be a few and analyzed them in the conversation.
    Each channel fails differently (module docstring), so the rule is
    asserted in all three."""

    def _texts(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        texts = {"instructions": guidance.SERVER_INSTRUCTIONS,
                 "reporting_guide('ga')": guidance.guide_for("ga"),
                 "reporting_guide('gsc')": guidance.guide_for("gsc"),
                 "reporting_guide('both')": guidance.guide_for("both"),
                 "skill": skill}
        # Line wrapping must not decide whether a phrase is present.
        return {k: " ".join(v.split()) for k, v in texts.items()}

    def test_export_the_full_data_by_default(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("Export the full data", t)
                self.assertIn("unless the user explicitly asks", t)

    def test_analyze_from_the_exported_file(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("Analyze only from the exported file", t)

    def test_never_analyze_truncated_data(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("Never analyze truncated", t)
                self.assertIn("unless the user specifically asks", t)

    def test_in_conversation_reports_are_for_single_figures_only(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("single figure", t)

    def test_the_few_rows_permission_is_gone(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertNotIn("only for a few rows", t)


class TestThePreviewIsNeverTheAnswer(unittest.TestCase):
    """Review of #1992: three texts still offered the receipt's
    preview as the source of a top ten or "a few" rows. The preview is up to
    20 rows read INTO the conversation, in export order, so its first ten
    are a top ten only by accident. It checks the file's shape; answers come
    from the file."""

    def _texts(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        texts = {"contract": guidance.BEHAVIORAL_CONTRACT, "skill": skill}
        texts.update({f"tool {k}": v
                      for k, v in guidance.GSC_TOOL_DOCS.items()})
        return {k: " ".join(v.split()) for k, v in texts.items()}

    def test_no_text_offers_the_preview_as_an_answer(self):
        offers = ["top ten from the receipt's `preview`",
                  "To show or report only a handful, use preview_rows",
                  'mechanism for "show me a few"']
        for name, t in self._texts().items():
            for phrase in offers:
                with self.subTest(name=name, phrase=phrase):
                    self.assertNotIn(phrase, t)

    def test_the_preview_is_named_as_a_shape_check(self):
        for name in ("contract", "tool export_report",
                     "tool gsc_search_analytics"):
            with self.subTest(name):
                self.assertIn("the preview only checks the file's shape",
                              self._texts()[name].lower())


class TestFindingASitesPropertyFromThePage(unittest.TestCase):
    """#146/#147, from the 2026-10-09 install: a site was tracked only under a
    rollup property whose name did not mention it, and most sites send to
    their own property AND a rollup. Michael: find all of them, do not stop
    at the rollup."""

    def setUp(self):
        self.section = _section_for(guidance.REPORTING_GUIDE, "look at the page")

    def test_it_says_to_collect_every_measurement_id(self):
        self.assertIn("every GA4 measurement ID", self.section)
        self.assertIn("not the first one found", self.section)

    def test_it_looks_inside_tag_manager_too(self):
        self.assertIn("gtm.js", self.section)

    def test_it_names_the_tool_that_maps_ids_to_properties(self):
        self.assertIn("property_setup", self.section)
        self.assertIn("data_streams", self.section)

    def test_it_prefers_the_sites_own_property_over_the_rollup(self):
        self.assertIn("Prefer the site's own property", self.section)

    def test_sampling_has_a_remedy(self):
        section = _section_for(guidance.REPORTING_GUIDE, "Sampled")
        self.assertIn("split the", section)
        self.assertIn("filter", section)


class TestComputeWithAScript(unittest.TestCase):
    """#2117, Michael 2026-11-27: arithmetic over an export belongs in a
    script. Doing it in the model's head costs tokens and can be wrong with
    no sign of it. A script can be wrong too, so the rule comes with the
    checks that catch one. He did not want hand arithmetic excluded
    entirely, so small sums stay allowed where they are said out loud.

    Each channel fails differently (module docstring), so the rule is
    asserted in the instructions, in every reporting_guide topic and in the
    skill."""

    def _texts(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        texts = {"instructions": guidance.SERVER_INSTRUCTIONS,
                 "reporting_guide('ga')": guidance.guide_for("ga"),
                 "reporting_guide('gsc')": guidance.guide_for("gsc"),
                 "reporting_guide('both')": guidance.guide_for("both"),
                 "skill": skill}
        return {k: " ".join(v.split()) for k, v in texts.items()}

    def _long_texts(self):
        """The channels with room for the whole rule: everything but the short instructions."""
        return {k: v for k, v in self._texts().items() if k != "instructions"}

    def test_the_rule_is_in_every_channel(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("Compute with a script over the exported file", t)

    def test_plain_python_is_named_as_always_enough(self):
        # Measured for #2038: a Mac with three Pythons had no pandas, numpy,
        # scipy, duckdb or polars. Guidance that assumes them stalls there.
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("plain Python", t)

    def test_nothing_is_installed_without_asking(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("ask before installing anything", t)

    def test_never_into_data_noodlers_own_environment(self):
        for name, t in self._long_texts().items():
            with self.subTest(name):
                self.assertIn("never install into Data Noodler's own Python environment", t)

    def test_the_script_is_checked_against_the_receipt(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("row count against the receipt", t)

    def test_a_total_is_checked_against_a_figure_fetched_directly(self):
        for name, t in self._long_texts().items():
            with self.subTest(name):
                self.assertIn("one figure fetched directly", t)
                # The check only holds for metrics that add up; saying so
                # keeps an honest mismatch on user counts from looking like a bug.
                self.assertIn("User counts don't add up across rows", t)

    def test_intermediate_results_are_printed(self):
        for name, t in self._long_texts().items():
            with self.subTest(name):
                self.assertIn("intermediate totals", t)

    def test_the_script_is_saved_and_shown(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("show the script with the result", t)
        for name, t in self._long_texts().items():
            with self.subTest(name):
                self.assertIn("in the same folder as the export", t)

    def test_where_no_code_can_reach_the_file_it_says_so(self):
        for name, t in self._texts().items():
            with self.subTest(name):
                self.assertIn("say what you couldn't compute", t)

    def test_small_sums_by_hand_are_allowed_and_said(self):
        for name, t in self._long_texts().items():
            with self.subTest(name):
                self.assertIn("one figure from two or three others", t)
                self.assertIn("saying that you did", t)

