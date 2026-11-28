"""Doc gate 5 (decision ce112917, card #2124): a change to what users and
agents can see needs a changelog entry that names the docs checked.

The other doc gates compare a fact in a doc with the code. None of them can
tell whether a CHANGE in behavior reached every doc that describes it. This
one asks. It takes a fingerprint of the public surface:

  - the data-noodler server's tools as a client sees them: each name, its
    description, and its parameters;
  - the text the server gives the model (its instructions and guides);
  - the installer scripts' command-line flags;
  - the pinned version of Google's analytics-mcp, which stands in for that
    server's own tools and text.

The newest entry in CHANGELOG.md must carry that fingerprint and a "Docs
checked" line naming documents that exist. So when the surface changes, this
test fails until someone writes an entry saying what changed and which docs
they checked.

Its limit, on purpose: it proves a doc check was declared. It can't prove the
check was right. A read-through at each release is what catches a wrong one.

When this fails after a deliberate change: add a NEW entry at the top of
CHANGELOG.md (copy the shape of the one below it), say what changed in plain
language, list the docs you checked, and put the fingerprint this test prints
on its "Surface" line.
"""

import ast
import glob
import hashlib
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # data-noodler/
REPO = os.path.dirname(ROOT)
CHANGELOG = os.path.join(REPO, "CHANGELOG.md")
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "server"))

ENTRY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}): (.+)$", re.M)
SURFACE_RE = re.compile(r"^\*\*Surface:\*\* `([0-9a-f]{12})`\s*$", re.M)
DOCS_RE = re.compile(r"^\*\*Docs checked:\*\* (.+)$", re.M)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── the surface ──────────────────────────────────────────────────────────

def server_tools():
    """Each tool's name, description and parameters, from a real handshake.

    Parameter TYPES are left out: the schema's wording for a type varies with
    the library and Python version, and a fingerprint that differs between two
    machines running the same code would be noise.
    """
    import test_handshake
    tools = {}
    for tool in test_handshake._list_tools():
        schema = test_handshake._schema(tool) or {}
        tools[tool.name] = {
            "description": (tool.description or "").strip(),
            "parameters": sorted((schema.get("properties") or {}).keys()),
            "required": sorted(schema.get("required") or []),
        }
    if not tools:
        raise AssertionError("the server listed no tools, so there is no surface to fingerprint")
    return tools


def guidance_text():
    """Every piece of text the server hands the model: the module's constants."""
    import guidance
    out = {}
    for name in sorted(dir(guidance)):
        value = getattr(guidance, name)
        if name.isupper() and isinstance(value, (str, dict)):
            out[name] = value
    if "SERVER_INSTRUCTIONS" not in out:
        raise AssertionError("guidance.SERVER_INSTRUCTIONS was not found")
    return out


def installer_flags(installer_dir=None):
    """{script: its command-line flags}, read from each add_argument call."""
    installer_dir = installer_dir or os.path.join(ROOT, "installer")
    flags = {}
    for path in sorted(glob.glob(os.path.join(installer_dir, "*.py"))):
        found = set()
        for node in ast.walk(ast.parse(_read(path))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
        if found:
            flags[os.path.basename(path)] = sorted(found)
    if not flags:
        raise AssertionError("found no installer flags, so the scan itself is broken")
    return flags


def analytics_mcp_pin():
    pins = re.findall(r"^analytics-mcp==\S+$", _read(os.path.join(ROOT, "installer", "constraints.txt")), re.M)
    if len(pins) != 1:
        raise AssertionError(f"expected one analytics-mcp pin in constraints.txt, found {pins}")
    return pins[0]


def surface():
    return {
        "tools": server_tools(),
        "guidance": guidance_text(),
        "installer_flags": installer_flags(),
        "analytics_mcp": analytics_mcp_pin(),
    }


def fingerprint(surface_dict):
    canonical = json.dumps(surface_dict, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ── the changelog ────────────────────────────────────────────────────────

def top_entry(text):
    """(date, title, body) of the newest entry: the first "## YYYY-MM-DD: title"."""
    entries = list(ENTRY_RE.finditer(text))
    if not entries:
        return None
    first = entries[0]
    end = entries[1].start() if len(entries) > 1 else len(text)
    return first.group(1), first.group(2), text[first.end():end]


def entry_problems(text, want, repo=REPO):
    """What is wrong with the newest changelog entry for a surface whose fingerprint is `want`."""
    entry = top_entry(text)
    if entry is None:
        return ['CHANGELOG.md has no entry (a heading like "## 2026-01-31: What changed")']
    date, title, body = entry
    problems = []
    surfaces = SURFACE_RE.findall(body)
    if surfaces != [want]:
        problems.append(
            f'the newest entry ("{date}: {title}") carries Surface {surfaces or "none"}, and the software\'s is '
            f'`{want}`. If the change was deliberate, add a NEW entry above it with **Surface:** `{want}`')
    docs = DOCS_RE.findall(body)
    if len(docs) != 1:
        problems.append(f'the newest entry needs exactly one "**Docs checked:**" line, found {len(docs)}')
    else:
        named = re.findall(r"`([^`]+\.md)`", docs[0])
        if not named:
            problems.append('the "Docs checked" line names no document (write each as `path/to/file.md`)')
        missing = [d for d in named if not os.path.isfile(os.path.join(repo, d))]
        if missing:
            problems.append(f'the "Docs checked" line names documents that do not exist: {missing}')
    return problems


# ── the tests ────────────────────────────────────────────────────────────

class TestTheChangelogCoversTheSurface(unittest.TestCase):

    def test_the_newest_entry_carries_the_softwares_fingerprint_and_names_docs(self):
        want = fingerprint(surface())
        self.assertEqual(entry_problems(_read(CHANGELOG), want), [])

    def test_entries_are_newest_first(self):
        dates = [m.group(1) for m in ENTRY_RE.finditer(_read(CHANGELOG))]
        self.assertTrue(dates, "CHANGELOG.md has no entries")
        self.assertEqual(dates, sorted(dates, reverse=True))


class TestControls(unittest.TestCase):
    """The gate must fail when the surface moves, and say what to do."""

    GOOD = ("# Changelog\n\nIntro.\n\n## 2026-02-02: Second\n\nText.\n\n**Surface:** `aaaaaaaaaaaa`\n\n"
            "**Docs checked:** `README.md` (changed).\n\n## 2026-01-01: First\n\n**Surface:** `bbbbbbbbbbbb`\n\n"
            "**Docs checked:** `README.md`.\n")

    def test_a_matching_entry_passes(self):
        self.assertEqual(entry_problems(self.GOOD, "aaaaaaaaaaaa"), [])

    def test_a_changed_surface_fails_and_names_the_new_fingerprint(self):
        problems = entry_problems(self.GOOD, "cccccccccccc")
        self.assertEqual(len(problems), 1)
        self.assertIn("cccccccccccc", problems[0])
        self.assertIn("NEW entry", problems[0])

    def test_only_the_newest_entry_counts(self):
        # The surface matches an OLDER entry: still a failure, the newest must carry it.
        self.assertEqual(len(entry_problems(self.GOOD, "bbbbbbbbbbbb")), 1)

    def test_an_entry_without_docs_checked_fails(self):
        text = self.GOOD.replace("**Docs checked:** `README.md` (changed).\n\n", "")
        self.assertTrue(any("Docs checked" in p for p in entry_problems(text, "aaaaaaaaaaaa")))

    def test_docs_checked_must_name_documents_that_exist(self):
        text = self.GOOD.replace("`README.md` (changed)", "`NO-SUCH-DOC.md` (changed)")
        self.assertTrue(any("do not exist" in p for p in entry_problems(text, "aaaaaaaaaaaa")))
        text = self.GOOD.replace("`README.md` (changed)", "everything")
        self.assertTrue(any("names no document" in p for p in entry_problems(text, "aaaaaaaaaaaa")))

    def test_a_changelog_with_no_entry_fails(self):
        self.assertEqual(len(entry_problems("# Changelog\n\nIntro only.\n", "aaaaaaaaaaaa")), 1)

    def test_every_part_of_the_surface_moves_the_fingerprint(self):
        base = {"tools": {"t": {"description": "d", "parameters": ["a"], "required": []}},
                "guidance": {"SERVER_INSTRUCTIONS": "x"}, "installer_flags": {"probe.py": ["--json"]},
                "analytics_mcp": "analytics-mcp==1.0.0"}
        seen = {fingerprint(base)}
        changes = [
            lambda s: s["tools"]["t"].__setitem__("description", "d2"),          # a tool's wording
            lambda s: s["tools"]["t"]["parameters"].append("b"),                  # a new parameter
            lambda s: s["tools"].__setitem__("u", {"description": "", "parameters": [], "required": []}),  # a new tool
            lambda s: s["guidance"].__setitem__("SERVER_INSTRUCTIONS", "y"),     # the server's instructions
            lambda s: s["installer_flags"]["probe.py"].append("--plan"),          # an installer flag
            lambda s: s.__setitem__("analytics_mcp", "analytics-mcp==1.1.0"),    # Google's server
        ]
        for change in changes:
            moved = json.loads(json.dumps(base))
            change(moved)
            seen.add(fingerprint(moved))
        self.assertEqual(len(seen), len(changes) + 1, "some change left the fingerprint where it was")

    def test_the_real_surface_has_all_four_parts(self):
        s = surface()
        self.assertGreaterEqual(len(s["tools"]), 10)
        self.assertTrue(all(t["description"] for t in s["tools"].values()), "a tool has no description")
        self.assertIn("--plan", s["installer_flags"].get("upgrade.py", []))
        self.assertTrue(s["analytics_mcp"].startswith("analytics-mcp=="))


if __name__ == "__main__":
    unittest.main()
