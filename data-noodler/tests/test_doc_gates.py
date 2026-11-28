"""Doc gates 1, 2, 3 and 6 (decision ce112917, card #2123).

A fact a program can look up gets a test that fails when a doc and the code
disagree. These four cover the facts the docs state most often:

  1. a count of tools matches the server it describes;
  2. a version floor in prose equals the value the code enforces;
  3. names agree in both directions: every tool a server offers is named in
     the query skill, and every tool, script, flag and config key the docs
     name exists;
  6. each SKILL.md stays under 500 lines.

Each gate is a checker that returns its problems, and each has two tests:
one runs it over the real docs and must find nothing, and one runs it over a
planted mistake and must find exactly that mistake. The second is what keeps
the first honest: a checker that finds nothing anywhere passes every
real-docs test written for it. An empty lookup (no docs found, no counts
found, a floor or a tool list that cannot be read) is a failure, never a
pass.
"""

import ast
import glob
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # data-noodler/
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "installer"))

from test_handshake import EXPECTED_TOOLS  # noqa: E402  the server's real list, proven by its handshake test
import platform_floors  # noqa: E402
import security_floors  # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# The changelog is history: an entry may name a tool or a flag that has since
# been removed, and a count that was true on its date. These gates check what
# the docs say about the software as it is now, so the changelog is left out.
# Its own gate is tests/test_public_surface.py.
HISTORY = {"CHANGELOG.md"}


def doc_paths():
    """The 12 docs: the repo root's Markdown and everything under data-noodler/, without the changelog."""
    paths = sorted(p for p in glob.glob(os.path.join(REPO, "*.md"))
                   + glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True)
                   if os.path.basename(p) not in HISTORY)
    if len(paths) < 10:
        raise AssertionError(f"found only {len(paths)} docs; the doc set itself is not readable")
    return paths


def rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def tool_counts():
    """TOOL_COUNTS from installer/upgrade.py, read without importing it (upgrade.py does real work on import paths)."""
    tree = ast.parse(_read(os.path.join(ROOT, "installer", "upgrade.py")))
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TOOL_COUNTS":
            counts = ast.literal_eval(n.value)
            if counts:
                return counts
    raise AssertionError("TOOL_COUNTS could not be read from installer/upgrade.py")


def analytics_tools():
    """The pinned analytics-mcp's real read-only tool names, from the installed package."""
    from analytics_mcp.coordinator import _READ_ONLY_TOOL_NAMES   # a missing package or a moved name fails here, loudly
    names = set(_READ_ONLY_TOOL_NAMES)
    if not names:
        raise AssertionError("analytics_mcp reports no read-only tools")
    return names


# ── gate 1: counts of tools ─────────────────────────────────────────────

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
COUNT_RE = re.compile(r"\b(\d+|" + "|".join(WORDS) + r")\s+(?:read-only\s+|MCP\s+)?tools\b", re.I)
# A server is named by its package or its folder. The count belongs to the
# NEAREST server named before it in the same sentence or table row.
SERVER_RE = re.compile(r"`?(analytics-mcp|data-noodler|server/)`?")
SERVER_OF = {"analytics-mcp": "analytics-mcp", "data-noodler": "data-noodler", "server/": "data-noodler"}

# Counts that are deliberately not a count of one server, each with its reason.
COUNT_EXCEPTIONS = {
    ("data-noodler/BUILD-YOUR-OWN.md", "25 tools"):
        "advice to someone building their own pair of servers (\"about 25 tools across two "
        "servers is fine\"), a rough ceiling, not a count of ours",
}


def _units(text):
    """Sentences and table rows, each with its line number."""
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("|"):
            yield i, line
            continue
        # Not at ":", which is where a sentence introduces its list ("Four of them cover: `a`, `b`...").
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            yield i, sentence


# A sentence that lists tools by name and gives a count ("Four of them cover
# ...: `a`, `b`, `c` and `d`") must give the number it lists. These counts
# don't say "tools", so COUNT_RE can't see them.
ANY_COUNT_RE = re.compile(r"\b(\d+|" + "|".join(WORDS) + r")\b", re.I)


def listed_count_problems(path, line, unit, known):
    named = {t for t in re.findall(r"`([a-z_]+)`", unit) if t in known}
    if len(named) < 2:
        return []
    prose = re.sub(r"`[^`]*`|\([^)]*\)", "", unit)   # counts inside code or an aside are not about the list
    return [(path, line, m.group(0), f"this sentence names {len(named)} tools")
            for m in ANY_COUNT_RE.finditer(prose)
            if (int(m.group(1)) if m.group(1).isdigit() else WORDS[m.group(1).lower()]) != len(named)]


def count_problems(docs, counts, known=frozenset()):
    """[(doc, line, phrase, problem)] for every tool count that doesn't match its server or its list."""
    problems, seen = [], 0
    for path, text in docs:
        for line, unit in _units(text):
            problems += listed_count_problems(path, line, unit, known)
            for m in COUNT_RE.finditer(unit):
                seen += 1
                phrase = m.group(0)
                n = int(m.group(1)) if m.group(1).isdigit() else WORDS[m.group(1).lower()]
                if (path, phrase) in COUNT_EXCEPTIONS:
                    continue
                before = list(SERVER_RE.finditer(unit[:m.start()]))
                if not before:
                    problems.append((path, line, phrase, "names no server before it, so it can't be checked; "
                                     "name the server, delete the count, or add an exception with a reason"))
                    continue
                server = SERVER_OF[before[-1].group(1)]
                if n != counts[server]:
                    problems.append((path, line, phrase, f"{server} has {counts[server]} tools"))
    return problems, seen


# ── gate 2: version floors ──────────────────────────────────────────────

def floor_claims(text):
    """Every stated floor: ("macos", 12), ("python", (3, 10)), ("uv", "0.13.4")."""
    out = []
    for m in re.finditer(r"macOS\s+(\d+)(?:\s*\([A-Za-z]+\))?\s*(?:\+|or later|or newer)", text):
        out.append(("macos", int(m.group(1)), m.group(0)))
    for m in re.finditer(r"(?:Python\s+|Anything\s+)(3)\.(\d+)\s*(?:\+|or later|or newer)", text):
        out.append(("python", (int(m.group(1)), int(m.group(2))), m.group(0)))
    # One pattern, so "**uv must be 0.13.4 or later**" is one claim, not two.
    for m in re.finditer(r"\buv[`*\s]+(?:must be\s+)?(\d+\.\d+\.\d+)\s+or later|must be (\d+\.\d+\.\d+) or later", text):
        out.append(("uv", m.group(1) or m.group(2), m.group(0)))
    return out


def floor_problems(docs, floors):
    problems, seen = [], 0
    for path, text in docs:
        for kind, value, phrase in floor_claims(text):
            seen += 1
            if value != floors[kind]:
                problems.append((path, phrase, f"the code's {kind} floor is {floors[kind]}"))
    return problems, seen


def declared_floors():
    return {"macos": platform_floors.MACOS_MAJOR, "python": platform_floors.PYTHON,
            "uv": security_floors.UV_FLOOR}


# ── gate 3: names, both ways ────────────────────────────────────────────

CODE_GLOBS = ("**/*.py", "**/*.sh", "**/*.ps1", "**/*.cmd", "**/*.json", "**/*.toml", "bin/*")
SNAKE_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
SCRIPT_RE = re.compile(r"[\w./-]*\w\.(?:py|sh|ps1)")
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")

# Names the docs use that are deliberately not ours, each with its reason.
NAME_EXCEPTIONS = {
    "access_denied": "an OAuth error Google returns; quoted so the reader can match it",
    "redirect_uri_mismatch": "an OAuth error Google returns; quoted so the reader can match it",
    "win_amd64": "a wheel platform tag (PyPI's naming), not ours",
    "analytics_mcp/server.py": "a file inside the pinned analytics-mcp package, not this repo",
    "fix_asr_entry.py": "a helper an OLD install wrote on the user's machine; the setup skill names it so it can be cleaned up",
    "--model": "ollama's flag, in a command that launches Codex on a local model; not ours",
}


def code_text():
    chunks = []
    for pattern in CODE_GLOBS:
        for p in glob.glob(os.path.join(REPO, pattern), recursive=True):
            if os.path.isfile(p) and os.sep + "tests" + os.sep not in p and os.sep + ".git" + os.sep not in p:
                try:
                    chunks.append(_read(p))
                except UnicodeDecodeError:
                    pass
    if not chunks:
        raise AssertionError("no code files found to check names against")
    return "\n".join(chunks)


def file_names():
    names = set()
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            names.add(f)
            names.add(rel(os.path.join(dirpath, f)))
            names.add(os.path.relpath(os.path.join(dirpath, f), ROOT).replace(os.sep, "/"))
    return names


def named_in(text):
    """(kind, name) for every tool, config key, script and flag a doc names.

    Inline code spans carry names in prose. Fenced blocks carry commands: in
    those, only a script of ours and the flags that follow it on the same
    line count, because a fenced block also runs other people's programs
    (brew, uv, git), whose flags are theirs.
    """
    found = set()
    text = re.sub(r"https?://\S+", "", text)   # a URL's path is not a script of ours
    fenced = re.findall(r"```.*?```", text, flags=re.S)
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    for span in re.findall(r"`([^`\n]+)`", prose):
        t = span.strip()
        if SNAKE_RE.fullmatch(t):
            found.add(("name", t))
        elif SCRIPT_RE.fullmatch(t):
            found.add(("script", t))
        elif FLAG_RE.fullmatch(t.split("=")[0]):
            found.add(("flag", t.split("=")[0]))
    for block in fenced:
        for line in block.splitlines():
            scripts = SCRIPT_RE.findall(line)
            if not scripts:
                continue
            for s in scripts:
                found.add(("script", s))
            after = line[line.find(scripts[0]) + len(scripts[0]):]
            for f in FLAG_RE.findall(after):
                found.add(("flag", f))
    return found


def name_problems(docs, code, files, external_tools):
    problems, seen = [], 0
    for path, text in docs:
        for kind, name in sorted(named_in(text)):
            seen += 1
            if name in NAME_EXCEPTIONS or name in external_tools:
                continue
            if kind == "script":
                ok = name in files or os.path.basename(name) in files
            else:
                ok = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", code) is not None
            if not ok:
                problems.append((path, kind, name))
    return problems, seen


# ── the tests ───────────────────────────────────────────────────────────

def real_docs():
    return [(rel(p), _read(p)) for p in doc_paths()]


class TestGate1ToolCounts(unittest.TestCase):

    def test_the_declared_counts_are_the_servers_real_counts(self):
        counts = tool_counts()
        self.assertEqual(counts["data-noodler"], len(EXPECTED_TOOLS),
                         "installer/upgrade.py's TOOL_COUNTS disagrees with the data-noodler server")
        self.assertEqual(counts["analytics-mcp"], len(analytics_tools()),
                         "installer/upgrade.py's TOOL_COUNTS disagrees with the installed analytics-mcp")

    def test_every_count_in_the_docs_matches_its_server(self):
        problems, seen = count_problems(real_docs(), tool_counts(), EXPECTED_TOOLS | analytics_tools())
        self.assertGreater(seen, 0, "found no tool counts at all, so the scan itself is broken")
        self.assertEqual(problems, [])

    def test_control_a_listed_count_that_disagrees_with_its_list_is_caught(self):
        known = {"a_one", "b_two", "c_three"}
        good = "Two of them are checks: `a_one` (run it first) and `b_two`.\n"
        self.assertEqual(count_problems([("x.md", good)], {}, known)[0], [], "control: a true listed count passes")
        bad = good.replace("Two of them", "Three of them")
        self.assertEqual([p[2] for p in count_problems([("x.md", bad)], {}, known)[0]], ["Three"])
        added = good.replace("and `b_two`", "`b_two` and `c_three`")
        self.assertEqual([p[2] for p in count_problems([("x.md", added)], {}, known)[0]], ["Two"],
                         "a tool added to the list without the count is caught")

    def test_control_a_planted_wrong_count_is_caught(self):
        counts = {"analytics-mcp": 10, "data-noodler": 15}
        good = [("x.md", "| `analytics-mcp` | Google's server. 10 tools. |\n"
                         "Alongside `analytics-mcp` there is a second server, `data-noodler`, which exposes fifteen tools.\n")]
        self.assertEqual(count_problems(good, counts)[0], [], "control: the correct text passes")
        bad = [("x.md", good[0][1].replace("fifteen tools", "fourteen tools"))]
        problems = count_problems(bad, counts)[0]
        self.assertEqual([p[2] for p in problems], ["fourteen tools"])

    def test_control_a_count_that_names_no_server_is_caught(self):
        problems = count_problems([("x.md", "It has 9 tools for this.\n")], {"analytics-mcp": 10, "data-noodler": 15})[0]
        self.assertEqual(len(problems), 1)
        self.assertIn("names no server", problems[0][3])


class TestGate2VersionFloors(unittest.TestCase):

    def test_the_launchers_enforce_the_declared_macos_floor(self):
        for name in ("launch-analytics-mcp", "launch-data-noodler"):
            text = _read(os.path.join(ROOT, "bin", name))
            found = re.findall(r'"\$OS_MAJOR" -lt (\d+)', text)
            self.assertEqual(found, [str(platform_floors.MACOS_MAJOR)], name)
            self.assertIn(f"macOS {platform_floors.MACOS_MAJOR} or later", text, name)

    def test_upgrade_checks_the_declared_python_floor(self):
        text = _read(os.path.join(ROOT, "installer", "upgrade.py"))
        self.assertIn("platform_floors.PYTHON", text)
        self.assertNotRegex(text, r">=\s*\(3,\s*\d+\)", "a literal Python floor in upgrade.py")

    def test_every_floor_in_the_docs_equals_the_code(self):
        problems, seen = floor_problems(real_docs(), declared_floors())
        self.assertGreater(seen, 0, "found no stated floors at all, so the scan itself is broken")
        self.assertEqual(problems, [])

    def test_control_a_planted_wrong_floor_is_caught_for_each_kind(self):
        floors = {"macos": 12, "python": (3, 10), "uv": "0.13.4"}
        good = "Needs macOS 12 (Monterey) or later. Python 3.10 or later. **uv must be 0.13.4 or later**.\n"
        self.assertEqual(floor_problems([("x.md", good)], floors), ([], 3), "control: the correct text passes, all three seen")
        for planted in (good.replace("macOS 12", "macOS 13"), good.replace("3.10", "3.11"),
                        good.replace("0.13.4", "0.13.3")):
            problems, _ = floor_problems([("x.md", planted)], floors)
            self.assertEqual(len(problems), 1, planted)


class TestGate3NamesBothWays(unittest.TestCase):

    def setUp(self):
        self.skill = _read(os.path.join(ROOT, "skills", "data-noodler", "SKILL.md"))

    def test_the_query_skill_names_every_tool_both_servers_offer(self):
        missing = sorted(t for t in EXPECTED_TOOLS | analytics_tools() if f"`{t}`" not in self.skill)
        self.assertEqual(missing, [])

    def test_every_name_the_docs_use_exists(self):
        problems, seen = name_problems(real_docs(), code_text(), file_names(), analytics_tools())
        self.assertGreater(seen, 50, "found almost no names, so the scan itself is broken")
        self.assertEqual(problems, [])

    def test_control_a_planted_stale_name_is_caught_for_each_kind(self):
        code = "def lookup_property(): pass\nparser.add_argument('--require')\n"
        files = {"probe.py"}
        good = "Call `lookup_property`. Run `probe.py`.\n```\npython probe.py --require x=1\nbrew upgrade --greedy uv\n```\n"
        self.assertEqual(name_problems([("x.md", good)], code, files, set())[0], [],
                         "control: the correct text passes, and brew's own flag is not ours to check")
        for planted, expect in ((good.replace("`lookup_property`", "`lookup_properties`"), "lookup_properties"),
                                (good.replace("`probe.py`", "`prob.py`"), "prob.py"),
                                (good.replace("--require", "--requires"), "--requires")):
            problems = name_problems([("x.md", planted)], code, files, set())[0]
            self.assertEqual([p[2] for p in problems], [expect], planted)


SKILL_LINE_LIMIT = 500


def size_problems(docs, limit=SKILL_LINE_LIMIT):
    return [(path, n) for path, text in docs if (n := len(text.splitlines())) > limit]


class TestGate6SkillSize(unittest.TestCase):

    def test_each_skill_is_under_the_limit(self):
        skills = sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))
        self.assertEqual(len(skills), 2, "expected the two skills")
        self.assertEqual(size_problems([(rel(p), _read(p)) for p in skills]), [])

    def test_control_a_skill_one_line_over_is_caught_and_one_at_the_limit_is_not(self):
        at = "x\n" * SKILL_LINE_LIMIT
        self.assertEqual(size_problems([("ok.md", at)]), [])
        self.assertEqual(size_problems([("big.md", at + "x\n")]), [("big.md", SKILL_LINE_LIMIT + 1)])


if __name__ == "__main__":
    unittest.main()
