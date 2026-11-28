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
    server's own tools and text;
  - every file in the two skill folders, which an agent follows as
    instructions (card #2127).

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
import shutil
import sys
import tempfile
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


def skill_files(skills_dir=None):
    """{path within skills/: its text} for every file in the skill folders.

    A skill folder is installed whole and its text is loaded as instructions,
    so a changed word there changes what the agent does. Line endings are read
    as LF, so a Windows checkout gives the same text. A file that isn't UTF-8
    text counts by a hash of its bytes.

    The folder is walked the way test_plugin_manifests.plugin_digest walks the
    plugin, so the gate needs no git checkout. The .data-noodler-installed
    marker is included on purpose: its text tells a user what deleting it
    does. A file git doesn't track is counted too, which is why a failure
    names the files (counted_note). The query skill is also inside the plugin's fingerprint, which
    forces a version bump. That check asks for no changelog entry, and the
    setup skill is outside it.
    """
    skills_dir = skills_dir or os.path.join(ROOT, "skills")
    found = {}
    for base, dirs, names in os.walk(skills_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".pyc") or name == ".DS_Store":
                continue                      # no install ships these
            path = os.path.join(base, name)
            rel = os.path.relpath(path, skills_dir).replace(os.sep, "/")
            with open(path, "rb") as f:
                data = f.read()
            try:
                found[rel] = data.decode("utf-8").replace("\r\n", "\n")
            except UnicodeDecodeError:
                found[rel] = "sha256:" + hashlib.sha256(data).hexdigest()
    if not found:
        raise AssertionError(f"found no skill files under {skills_dir}, so the scan itself is broken")
    return found


def surface():
    return {
        "tools": server_tools(),
        "guidance": guidance_text(),
        "installer_flags": installer_flags(),
        "analytics_mcp": analytics_mcp_pin(),
        "skills": skill_files(),
    }


def counted_note(surface_dict):
    """A line for the failure message: the skill files the fingerprint counted.

    The scan reads the folder as it is on this machine, so a file git doesn't
    track (an editor's swap file, a scratch note) moves the fingerprint here
    and nowhere else. Naming the files puts a stray one in plain sight before
    anyone copies the fingerprint into the changelog.
    """
    names = sorted(surface_dict["skills"])
    return (f"The fingerprint counts {len(names)} skill files. If one of them doesn't belong in the "
            f"repository, remove it and run again: {', '.join(names)}")


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
        s = surface()
        self.assertEqual(entry_problems(_read(CHANGELOG), fingerprint(s)), [], counted_note(s))

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
                "analytics_mcp": "analytics-mcp==1.0.0", "skills": {"one/SKILL.md": "Do this."}}
        seen = {fingerprint(base)}
        changes = [
            lambda s: s["tools"]["t"].__setitem__("description", "d2"),          # a tool's wording
            lambda s: s["tools"]["t"]["parameters"].append("b"),                  # a new parameter
            lambda s: s["tools"].__setitem__("u", {"description": "", "parameters": [], "required": []}),  # a new tool
            lambda s: s["guidance"].__setitem__("SERVER_INSTRUCTIONS", "y"),     # the server's instructions
            lambda s: s["installer_flags"]["probe.py"].append("--plan"),          # an installer flag
            lambda s: s.__setitem__("analytics_mcp", "analytics-mcp==1.1.0"),    # Google's server
            lambda s: s["skills"].__setitem__("one/SKILL.md", "Do that."),       # a skill's wording
            lambda s: s["skills"].__setitem__("one/references/new.md", ""),      # a new skill file
        ]
        for change in changes:
            moved = json.loads(json.dumps(base))
            change(moved)
            seen.add(fingerprint(moved))
        self.assertEqual(len(seen), len(changes) + 1, "some change left the fingerprint where it was")

    def test_the_real_surface_has_all_five_parts(self):
        s = surface()
        self.assertGreaterEqual(len(s["tools"]), 10)
        self.assertTrue(all(t["description"] for t in s["tools"].values()), "a tool has no description")
        self.assertIn("--plan", s["installer_flags"].get("upgrade.py", []))
        self.assertTrue(s["analytics_mcp"].startswith("analytics-mcp=="))
        for skill in ("data-noodler/SKILL.md", "data-noodler-setup/SKILL.md"):
            self.assertIn("\nname: ", s["skills"].get(skill, ""), f"{skill} is not in the surface")
        self.assertIn("data-noodler-setup/references/windows.md", s["skills"])
        self.assertIn("data-noodler/scripts/mint_adc.py", s["skills"])


class TestSkillFiles(unittest.TestCase):
    """The skills' part of the surface: every file in the skill folders, by path."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def put(self, rel, data):
        path = os.path.join(self.dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def test_it_reads_every_file_and_leaves_out_what_no_install_ships(self):
        self.put("one/SKILL.md", b"Do this.\n")
        self.put("one/references/more.md", b"More.\n")
        self.put("one/scripts/tool.py", b"print(1)\n")
        self.put("two/SKILL.md", b"Other.\n")
        self.put("one/scripts/__pycache__/tool.cpython-312.pyc", b"\x00\x01")
        self.put("one/scripts/__pycache__/notes.txt", b"left by a tool\n")
        self.put("one/.DS_Store", b"\x00")
        self.assertEqual(skill_files(self.dir), {
            "one/SKILL.md": "Do this.\n", "one/references/more.md": "More.\n",
            "one/scripts/tool.py": "print(1)\n", "two/SKILL.md": "Other.\n"})

    def test_a_changed_word_and_a_new_file_each_move_the_fingerprint(self):
        self.put("one/SKILL.md", b"Ask before merging.\n")
        before = fingerprint({"skills": skill_files(self.dir)})
        self.put("one/SKILL.md", b"Merge without asking.\n")
        reworded = fingerprint({"skills": skill_files(self.dir)})
        self.put("one/references/new.md", b"")
        added = fingerprint({"skills": skill_files(self.dir)})
        self.assertEqual(len({before, reworded, added}), 3)

    def test_windows_line_endings_do_not_move_the_fingerprint(self):
        self.put("one/SKILL.md", b"Line one.\nLine two.\n")
        unix = skill_files(self.dir)
        self.put("one/SKILL.md", b"Line one.\r\nLine two.\r\n")
        self.assertEqual(skill_files(self.dir), unix)

    def test_a_file_that_is_not_text_still_counts(self):
        self.put("one/SKILL.md", b"Do this.\n")
        self.put("one/logo.png", b"\x89PNG\xff\xfe")
        first = skill_files(self.dir)
        self.assertIn("one/logo.png", first)
        self.put("one/logo.png", b"\x89PNG\xff\xfd")
        self.assertNotEqual(skill_files(self.dir)["one/logo.png"], first["one/logo.png"])

    def test_the_failure_note_names_every_file_counted(self):
        # A stray file on one machine (an editor's swap file, say) moves the
        # fingerprint there and nowhere else. The note puts it in plain sight.
        self.put("one/SKILL.md", b"Do this.\n")
        self.put("one/.SKILL.md.swp", b"\x00swap")
        note = counted_note({"skills": skill_files(self.dir)})
        self.assertIn("2 skill files", note)
        self.assertIn("one/SKILL.md", note)
        self.assertIn("one/.SKILL.md.swp", note)

    def test_an_empty_skills_folder_is_a_broken_scan(self):
        with self.assertRaises(AssertionError):
            skill_files(self.dir)


if __name__ == "__main__":
    unittest.main()
