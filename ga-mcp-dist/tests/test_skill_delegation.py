"""The skill must document the companion tools and not duplicate their logic.

One implementation of property lookup and snapshot refresh, or the two drift
and a colleague gets different answers depending on which harness they used.
"""

import os
import unittest

SKILL = os.path.expanduser("~/.claude/skills/google-analytics")


class TestSkillDocumentsCompanion(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL, "SKILL.md")) as f:
            self.text = f.read()

    def test_mentions_each_companion_tool(self):
        for tool in ("lookup_property", "credential_status",
                     "refresh_property_snapshot", "reporting_guide"):
            self.assertIn(tool, self.text, tool)

    def test_explains_that_shell_less_harnesses_use_the_tools(self):
        lowered = self.text.lower()
        self.assertIn("no shell", lowered)

    def test_still_documents_the_dns_versus_auth_distinction(self):
        self.assertIn("GRPC_DNS_RESOLVER", self.text)
        self.assertIn("invalid_grant", self.text)


class TestRefreshDelegates(unittest.TestCase):
    def test_refresh_script_calls_the_shared_rebuild(self):
        with open(os.path.join(SKILL, "scripts",
                               "refresh_properties.py")) as f:
            body = f.read()
        self.assertIn("snapshot", body)
        # A bare mention of "rebuild" (e.g. in a docstring) isn't enough --
        # the script must actually call the shared function.
        self.assertIn("snapshot.rebuild(", body)
        # The Admin API enumeration must exist in exactly one place now: the
        # companion's snapshot module. Any independent enumeration here would
        # have to import analytics_mcp to talk to the Admin API at all, under
        # whatever method name, so ruling out the import -- not just the one
        # method name -- catches a differently-named duplicate too.
        self.assertNotIn("list_account_summaries", body)
        self.assertNotIn("analytics_mcp", body)
        self.assertNotIn("create_admin_api_client", body)

    def test_companion_tool_calls_the_same_shared_rebuild(self):
        # Makes the "one implementation, two front ends" property explicit:
        # the companion's own MCP tool handler goes through snapshot.rebuild
        # too, not a second copy of the enumeration.
        companion_source = os.path.expanduser(
            "~/.config/ga-mcp/companion/ga_companion.py")
        with open(companion_source) as f:
            body = f.read()
        self.assertIn("snapshot.rebuild(", body)


class TestSkillCoversSearchConsole(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL, "SKILL.md")) as f:
            self.text = f.read()
        self.frontmatter = self.text.split("---")[1]

    def test_description_carries_search_console_triggers(self):
        d = self.frontmatter.lower()
        for word in ("indexed", "impressions", "search console"):
            self.assertIn(word, d, word)

    def test_description_keeps_its_analytics_triggers(self):
        d = self.frontmatter.lower()
        for word in ("sessions", "pageviews", "traffic"):
            self.assertIn(word, d, word)

    def test_body_documents_every_new_tool(self):
        for tool in ("start_session", "export_report", "gsc_list_sites",
                     "gsc_inspect_urls", "gsc_search_analytics"):
            self.assertIn(tool, self.text, tool)

    def test_body_carries_the_domain_versus_prefix_trap(self):
        self.assertIn("sc-domain:", self.text)

    def test_the_trap_is_documented_in_the_right_direction(self):
        # The rule lives in four places (this file, guidance.GSC_GUIDE, the
        # gsc_list_sites tool doc, and gsc._covers) and every test of it was
        # a substring search for "subdomain", so a rewrite that inverted the
        # rule would have passed. Read each bullet on its own: the document
        # as a whole contains both directions by design.
        domain = self._bullet("`sc-domain:example.edu`").lower()
        self.assertIn("covers every subdomain", domain)
        self.assertNotIn("excluded", domain)

        prefix = self._bullet("`https://example.edu/`").lower()
        self.assertIn("subdomains are excluded", prefix)
        self.assertNotIn("covers every subdomain", prefix)

    def test_the_body_documents_the_real_tool_count(self):
        # It said "exposes four tools" and then documented nine two
        # paragraphs later. A reader who believes the first sentence never
        # looks for the export tools at all. Ten since card #130 added
        # gsc_list_sitemaps; every tool the server has must be named.
        self.assertIn("fifteen tools", self.text)
        for stale in ("four tools", "nine tools", "ten tools"):
            self.assertNotIn(stale, self.text)
        from test_handshake import EXPECTED_TOOLS
        for tool in EXPECTED_TOOLS:
            self.assertIn(f"`{tool}`", self.text, tool)

    def _bullet(self, marker):
        """The single markdown bullet naming `marker`, unwrapped."""
        bullets, current = [], None
        for line in self.text.splitlines():
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
        self.assertEqual(len(found), 1,
                         f"expected exactly one bullet naming {marker}")
        return found[0]

    def test_body_says_export_rather_than_reading_large_results(self):
        self.assertIn("export", self.text.lower())
