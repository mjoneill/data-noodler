"""#2018: every documented consent line has a PowerShell form that runs.

The consent script (mint_adc.py) is the one step a person runs by hand,
at setup and again every week. The documents gave it only as a bash block:
a quoted path at the start of a line is a parse error in Windows PowerShell
5.1 and pwsh 7 (measured for #2017), and "~" is not expanded in an argument
to a native program. The Windows guide sends people to PowerShell, so each
bash consent line needs a PowerShell twin, and that twin must run.

Two kinds of row:
- the document rows run everywhere and read the text;
- the run rows run only on Windows (CI's tests-windows job), filling the
  placeholders in and executing each PowerShell line in every PowerShell
  the machine has.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

DIST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ("INSTALL.md", os.path.join("skills", "data-noodler-setup", "SKILL.md"))
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
SCRIPT_TAIL = ("marketplace", "plugins", "data-noodler", "skills",
               "data-noodler", "scripts", "mint_adc.py")
# #2106: in the repo, before anything is installed, the skill is at
# skills/data-noodler/; the install places it inside the plugin.
REPO_SCRIPT_TAIL = ("skills", "data-noodler", "scripts", "mint_adc.py")


def consent_pairs(doc):
    """(bash line, the PowerShell line that follows it) for every bash block
    that runs mint_adc.py. A bash block with no PowerShell block before the
    next bash block pairs with None."""
    with open(os.path.join(DIST, doc), encoding="utf-8") as f:
        blocks = [(m.group(1), m.group(2).strip()) for m in FENCE.finditer(f.read())]
    pairs = []
    for i, (lang, body) in enumerate(blocks):
        if lang != "bash" or "mint_adc.py" not in body:
            continue
        twin = None
        for lang2, body2 in blocks[i + 1:]:
            if lang2 == "bash":
                break
            if lang2 == "powershell" and "mint_adc.py" in body2:
                twin = body2
                break
        pairs.append((body, twin))
    return pairs


class EveryConsentLineHasAPowerShellTwin(unittest.TestCase):
    def test_the_documents_still_have_consent_lines(self):
        # Control: if the parser found nothing, every row below would pass.
        for doc in DOCS:
            self.assertTrue(consent_pairs(doc), doc)

    def test_each_bash_consent_line_is_followed_by_a_powershell_one(self):
        for doc in DOCS:
            for bash, ps in consent_pairs(doc):
                self.assertIsNotNone(ps, f"{doc}: no PowerShell twin for\n{bash}")

    def test_the_powershell_line_is_one_powershell_can_parse_and_resolve(self):
        for doc in DOCS:
            for bash, ps in consent_pairs(doc):
                if ps is None:
                    continue
                self.assertTrue(ps.startswith("& "), f"{doc}: {ps}")
                self.assertNotIn("~", ps, f"{doc}: {ps}")
                self.assertNotIn("/", ps, f"{doc}: {ps}")
                self.assertEqual("--force" in ps, "--force" in bash, f"{doc}: {ps}")


def _powershells():
    return [p for p in (shutil.which("powershell"), shutil.which("pwsh")) if p]


@unittest.skipUnless(sys.platform.startswith("win"), "runs PowerShell")
class ThePowerShellLinesRun(unittest.TestCase):
    """Each documented line, placeholders filled in, run in every PowerShell
    on the machine. The stand-in script records the arguments it got."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.tmp, "repo")
        self.out = os.path.join(self.tmp, "argv.txt")
        stand_in = ("import sys\n"
                    f"open({self.out!r}, 'w').write(' '.join(sys.argv[1:]))\n")
        for script in (
                os.path.join(self.home, ".config", "data-noodler", *SCRIPT_TAIL),
                os.path.join(self.repo, "data-noodler", *REPO_SCRIPT_TAIL)):
            os.makedirs(os.path.dirname(script))
            with open(script, "w") as f:
                f.write(stand_in)

    def _run(self, shell, line):
        if os.path.exists(self.out):
            os.remove(self.out)
        line = re.sub(r'^& "<[^>]*>"', lambda m: f'& "{sys.executable}"', line)
        line = line.replace("<repo>", self.repo)
        env = dict(os.environ, USERPROFILE=self.home)
        r = subprocess.run([shell, "-NoProfile", "-Command", line], env=env,
                           capture_output=True, text=True, timeout=120)
        return r, line

    def test_every_line_runs_in_every_powershell(self):
        shells = _powershells()
        self.assertTrue(shells, "no PowerShell found on a Windows runner")
        for doc in DOCS:
            for bash, ps in consent_pairs(doc):
                self.assertIsNotNone(ps, doc)
                for shell in shells:
                    r, line = self._run(shell, ps)
                    self.assertEqual(r.returncode, 0,
                                     f"{doc} in {shell}: {line}\n{r.stderr}")
                    with open(self.out) as f:
                        got = f.read()
                    self.assertEqual(got, "--force" if "--force" in ps else "",
                                     f"{doc} in {shell}: {line}")


if __name__ == "__main__":
    unittest.main()
