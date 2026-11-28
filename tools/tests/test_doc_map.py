"""#2105: every document has one place in the documentation tree, and can be reached.

The rule: each Markdown file has exactly one parent. Its breadcrumb, on the
line under its title, names the path from the front-page README down to it,
and its parent has a real link down to it. The README's "Documentation map"
links every document. Links from elsewhere are welcome; they don't change a
file's parent.

Adding a document? Give it a row in TREE below, a breadcrumb under its title,
a link from its parent, and a line in the README's Documentation map. This
test names whichever of those is missing.
"""

import os
import posixpath
import re
import subprocess
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = "README.md"
SETUP = "data-noodler/skills/data-noodler-setup"

# file -> (its parent, the name it goes by in breadcrumbs)
TREE = {
    ROOT: (None, "Data Noodler"),
    "SECURITY.md": (ROOT, "Security"),
    "data-noodler/README.md": (ROOT, "Package contents"),
    "data-noodler/skills/data-noodler/SKILL.md": ("data-noodler/README.md", "Query skill"),
    "data-noodler/START-HERE.md": (ROOT, "Start here"),
    "data-noodler/GOOGLE-CLOUD-SETUP.md": ("data-noodler/START-HERE.md", "Setting up your own Google App"),
    f"{SETUP}/SKILL.md": ("data-noodler/START-HERE.md", "Setup skill"),
    f"{SETUP}/references/windows.md": (f"{SETUP}/SKILL.md", "Installing on Windows"),
    f"{SETUP}/references/troubleshooting.md": (f"{SETUP}/SKILL.md", "Troubleshooting"),
    f"{SETUP}/references/install-report.md": (f"{SETUP}/SKILL.md", "Install report template"),
    "data-noodler/ARCHITECTURE.md": (ROOT, "How this package works"),
    "data-noodler/BUILD-YOUR-OWN.md": ("data-noodler/ARCHITECTURE.md", "Build your own"),
}

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def tracked_markdown():
    proc = subprocess.run(["git", "-C", TOP, "ls-files", "*.md"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed ({proc.returncode}): {proc.stderr}")
    return sorted(p for p in proc.stdout.splitlines() if p)


def read(rel):
    with open(os.path.join(TOP, rel), encoding="utf-8") as f:
        return f.read()


def prose_lines(text):
    """The file's lines outside fenced code blocks."""
    out, fenced = [], False
    for line in text.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return out


def links(rel):
    """(target file relative to the repo, anchor or '') for every relative link in a file."""
    found = []
    for line in prose_lines(read(rel)):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue                      # a web address, mailto:, or a jump within the page
            path, _, anchor = target.partition("#")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
            found.append((resolved, anchor, target))
    return found


def slug(heading):
    """The anchor GitHub gives a heading."""
    text = re.sub(r"`", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(rel):
    return {slug(line.lstrip("#")) for line in prose_lines(read(rel)) if line.startswith("#")}


def expected_breadcrumb(rel):
    chain = []
    cur = rel
    while cur is not None:
        chain.append(cur)
        cur = TREE[cur][0]
    chain.reverse()                           # root first
    parts = []
    for ancestor in chain[:-1]:
        href = posixpath.relpath(ancestor, posixpath.dirname(rel) or ".")
        parts.append(f"[{TREE[ancestor][1]}]({href})")
    parts.append(TREE[rel][1])
    return " › ".join(parts)


class DocumentationTree(unittest.TestCase):

    def test_every_document_is_in_the_tree(self):
        self.assertEqual(tracked_markdown(), sorted(TREE),
                         "a Markdown file is missing from TREE, or TREE names one that is gone")

    def test_each_document_carries_its_breadcrumb_under_the_title(self):
        wrong = {}
        for rel in TREE:
            if rel == ROOT:
                continue
            lines = read(rel).split("\n")
            title = next(i for i, line in enumerate(lines) if line.startswith("# "))
            got = lines[title + 2] if lines[title + 1] == "" else lines[title + 1]
            want = expected_breadcrumb(rel)
            if got != want:
                wrong[rel] = {"found": got[:120], "expected": want}
        self.assertEqual(wrong, {})

    def test_each_parent_links_down_to_its_children(self):
        missing = []
        for rel, (parent, _) in TREE.items():
            if parent is None:
                continue
            if rel not in {target for target, _, _ in links(parent)}:
                missing.append(f"{parent} has no link to {rel}")
        self.assertEqual(missing, [])

    def test_the_readme_map_links_every_document(self):
        text = read(ROOT)
        self.assertIn("## Documentation map", text, "the front-page README has no Documentation map section")
        start = text.index("## Documentation map")
        end = text.index("\n## ", start + 1)
        section = text[start:end]
        linked = set(LINK.findall(section))
        missing = sorted(rel for rel in TREE if rel != ROOT and rel not in linked)
        self.assertEqual(missing, [], "the README's Documentation map doesn't link these")

    def test_every_relative_link_leads_somewhere(self):
        broken = []
        for rel in TREE:
            for target, anchor, raw in links(rel):
                if target.startswith(".."):
                    continue                  # leaves the repository (GitHub's own pages, such as issues)
                full = os.path.join(TOP, target)
                if not os.path.exists(full):
                    broken.append(f"{rel}: {raw} (no such file)")
                elif anchor and target.endswith(".md") and anchor not in anchors(target):
                    broken.append(f"{rel}: {raw} (no heading with that anchor)")
        self.assertEqual(broken, [])


class Controls(unittest.TestCase):
    """The helpers must be able to tell right from wrong."""

    def test_breadcrumb_paths_are_relative_to_the_document(self):
        self.assertEqual(expected_breadcrumb("SECURITY.md"), "[Data Noodler](README.md) › Security")
        self.assertEqual(
            expected_breadcrumb(f"{SETUP}/references/windows.md"),
            "[Data Noodler](../../../../README.md) › [Start here](../../../START-HERE.md) › "
            "[Setup skill](../SKILL.md) › Installing on Windows")

    def test_slug_matches_githubs_anchors(self):
        self.assertEqual(slug(" What this shares, and what it doesn't"), "what-this-shares-and-what-it-doesnt")
        self.assertEqual(slug(" What's tested, and where it's in use"), "whats-tested-and-where-its-in-use")

    def test_links_inside_code_blocks_are_ignored(self):
        self.assertEqual(prose_lines("a\n```\n[x](nowhere.md)\n```\nb"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
