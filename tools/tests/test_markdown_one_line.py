"""#2107: every Markdown file keeps each paragraph on one source line.

The convention: a paragraph, a list item or a quoted paragraph is ONE line in
the file. Don't wrap prose at 75 or 80 characters; the reader's window decides
where lines break. Tables, code blocks, headings and hard line breaks (two
trailing spaces) keep their own lines.

Why: hard-wrapped files read badly in editors that wrap to the window, and
every edit reflows the neighboring lines, so a diff shows changes nobody made.

If this test fails, join the lines it names into one line each. Changing only
whitespace is enough.
"""

import os
import re
import subprocess
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
FENCE = re.compile(r"^\s*(```|~~~)")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _standalone(line):
    s = line.lstrip()
    return (s.startswith(("#", "|", "<")) or RULE.match(line) is not None
            or FENCE.match(line) is not None)


def _hard_break(line):
    return line.endswith("  ") or line.endswith("\\")


def wrapped_lines(text):
    """Line numbers (1-based) of prose lines that continue the line above."""
    lines = text.split("\n")
    found = []
    start = 0
    if lines and lines[0] == "---" and "---" in lines[1:]:
        start = lines.index("---", 1) + 1          # YAML frontmatter
    in_fence = False
    joinable = False
    prev_blank = True
    in_list = False
    for n in range(start, len(lines)):
        line = lines[n]
        if in_fence:
            if FENCE.match(line):
                in_fence = False
            continue
        if FENCE.match(line):
            in_fence, joinable, prev_blank = True, False, False
            continue
        if not line.strip():
            joinable, prev_blank = False, True
            continue
        if _standalone(line):
            if line.lstrip().startswith("#"):
                in_list = False
            joinable, prev_blank = False, False
            continue
        if LIST.match(line):
            joinable, prev_blank, in_list = not _hard_break(line), False, True
            continue
        indent = len(line) - len(line.lstrip(" "))
        if prev_blank and indent >= 4 and not in_list:
            joinable, prev_blank = False, False      # indented code
            continue
        body = line.lstrip()
        if body.startswith(">"):
            inner = body[1:].lstrip()
            if joinable and inner and not _standalone(inner) and not LIST.match(inner):
                found.append(n + 1)
            joinable = bool(inner) and not _hard_break(line) and not _standalone(inner)
            prev_blank = False
            continue
        if joinable:
            found.append(n + 1)
        elif prev_blank and indent == 0:
            in_list = False
        joinable, prev_blank = not _hard_break(line), False
    return found


def tracked_markdown():
    proc = subprocess.run(["git", "-C", TOP, "ls-files", "*.md"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed ({proc.returncode}): {proc.stderr}")
    return [p for p in proc.stdout.splitlines() if p]


class DetectorControls(unittest.TestCase):
    """The detector must catch a wrapped paragraph and leave structure alone."""

    def test_wrapped_paragraph_is_caught(self):
        self.assertEqual(wrapped_lines("One sentence that\nwraps here.\n"), [2])

    def test_wrapped_list_item_is_caught(self):
        self.assertEqual(wrapped_lines("- an item that\n  wraps here\n"), [2])

    def test_wrapped_quote_is_caught(self):
        self.assertEqual(wrapped_lines("> a quote that\n> wraps here\n"), [2])

    def test_structure_is_not_flagged(self):
        text = "\n".join([
            "---", "name: x", "description: y", "---",
            "# Title", "One line paragraph.", "",
            "- item one", "- item two", "  1. nested", "",
            "| a | b |", "|---|---|", "| 1 | 2 |", "",
            "```", "code line one", "code line two", "```", "",
            "Ends with a hard break  ", "next line", "",
            "    indented code", "    more code", "",
        ])
        self.assertEqual(wrapped_lines(text), [])


class EveryFileIsOneLinePerParagraph(unittest.TestCase):

    def test_tracked_markdown_is_not_hard_wrapped(self):
        files = tracked_markdown()
        self.assertGreater(len(files), 5, "found too few Markdown files; is this a git checkout?")
        bad = {}
        for rel in files:
            with open(os.path.join(TOP, rel), encoding="utf-8") as f:
                hits = wrapped_lines(f.read())
            if hits:
                bad[rel] = hits[:5]
        self.assertEqual(bad, {}, "these lines continue the paragraph above; "
                                  "join each paragraph onto one line (#2107)")


if __name__ == "__main__":
    unittest.main()
