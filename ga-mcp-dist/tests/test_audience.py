"""Data Noodler is for an individual, a team, an organization or an institution.

The package was first written for one institution deploying to its team, so
its setup assumed a maintainer handing a sign-in file to colleagues. A person
setting it up just for themselves is both maintainer and user: they make their
own Google app, add only themselves as a test user, and hand nothing to anyone.
These rows hold the docs to both paths, so neither reader meets instructions
that are not theirs.
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# Files a first-time reader is sent through. Each may mention "institution"
# as one audience among several, never as the only one.
FIRST_RUN_DOCS = (
    ("START-HERE.md",),
    ("README.md",),
    ("INSTALL.md",),
    ("GOOGLE-CLOUD-SETUP.md",),
    ("skills", "ga-mcp-setup", "SKILL.md"),
)

AUDIENCE_ALTERNATIVES = re.compile(r"individual|just (?:you|me|for yourself)|yourself", re.I)


class TestStartHereOffersBothPaths(unittest.TestCase):

    def setUp(self):
        self.text = read("START-HERE.md")

    def test_it_offers_a_just_me_path(self):
        self.assertRegex(self.text, r"(?i)just (?:you|for yourself)",
                         "a person setting this up for themselves needs a path "
                         "that does not assume colleagues")

    def test_the_hand_off_is_marked_as_only_for_others(self):
        m = re.search(r"(?ms)^### \d+\. Prepare the hand-off.*?(?=^### |^## |\Z)", self.text)
        self.assertIsNotNone(m, "the hand-off section must still exist for teams")
        self.assertRegex(m.group(0), r"(?i)skip this step|only if (?:others|other people)",
                         "a just-me reader must be told the hand-off is not theirs")

    def test_the_first_time_section_is_not_institution_only(self):
        self.assertNotRegex(self.text, r"(?m)^## Porting it to a new institution",
                            "the first-time section heading names one audience")


class TestNoFirstRunDocAssumesOnlyInstitutions(unittest.TestCase):

    def test_institution_is_never_the_only_audience_named(self):
        for parts in FIRST_RUN_DOCS:
            text = read(*parts)
            for m in re.finditer(r"(?i)institution", text):
                # the surrounding sentence-ish window
                window = text[max(0, m.start() - 160): m.end() + 160]
                with self.subTest(file="/".join(parts), at=m.start()):
                    self.assertRegex(
                        window,
                        r"(?i)organi[sz]ation|team|individual|yourself|just (?:you|me)|workspace",
                        "'institution' appears with no other audience nearby")


class TestTheTemplateAcceptsJustMe(unittest.TestCase):

    def setUp(self):
        self.template = json.loads(read("deployment.template.json"))

    def test_the_comment_speaks_to_individuals_too(self):
        self.assertRegex(self.template["_comment"], AUDIENCE_ALTERNATIVES)

    def test_team_only_fields_are_said_to_be_optional_for_one_person(self):
        self.assertRegex(self.template["_comment"], r"(?i)leave .*blank|optional",
                         "a just-me reader must know the team fields can stay blank")



class TestTheInstallerAcceptsBlankTeamFields(unittest.TestCase):
    """A just-me deployment.json leaves maintainer_contact and
    install_reports_to blank. The installer must install anyway.

    Honest note: this row was green before the docs change too. No installer
    code reads deployment.json, so blank fields could never stop it. The row
    exists so that stays true: if someone later makes the installer read a
    team field, a just-me install must still pass.
    """

    def test_no_installer_code_requires_the_team_fields(self):
        for sub in ("installer", "companion", "bin"):
            for base, _, files in os.walk(os.path.join(ROOT, sub)):
                for name in files:
                    if not name.endswith(".py") and sub != "bin":
                        continue
                    path = os.path.join(base, name)
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    with self.subTest(file=os.path.relpath(path, ROOT)):
                        self.assertNotRegex(
                            text, r"\[\s*['\"](maintainer_contact|install_reports_to)['\"]\s*\]",
                            "indexing a team-only field would raise on a just-me deployment")

    def test_a_payload_install_succeeds_with_the_team_fields_blank(self):
        import shutil
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            shutil.copytree(ROOT, os.path.join(repo, "ga-mcp-dist"),
                            ignore=shutil.ignore_patterns("__pycache__", "tests"))
            profile = os.path.join(repo, "ga-mcp-dist", "deployment.json")
            with open(profile, encoding="utf-8") as f:
                d = json.load(f)
            d.update({"deployment_name": "Pat's sites", "maintainer": "Pat Example",
                      "maintainer_contact": "", "install_reports_to": ""})
            with open(profile, "w", encoding="utf-8") as f:
                json.dump(d, f)
            home = os.path.join(tmp, "home")
            ga_home = os.path.join(tmp, "ga")
            os.makedirs(home)
            env = dict(os.environ, HOME=home, USERPROFILE=home)
            r = subprocess.run(
                [sys.executable, "-I", os.path.join(repo, "ga-mcp-dist", "installer", "install.py"),
                 "--repo-root", repo, "--ga-home", ga_home, "--payload-only"],
                env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for part in ("companion", "bin", "marketplace"):
                self.assertTrue(os.path.isdir(os.path.join(ga_home, part)),
                                f"{part} was not installed")


class TestBlankTeamFieldsAreAFinishedSetup(unittest.TestCase):
    """Review of a3a95e3 (minimo): docs that route on "blank" or say "fill every
    blank" make an intentionally blank just-me profile look unfinished, and the
    report step must not ask a just-me user to send a report to nobody."""

    def test_start_here_routes_on_the_maintainer_field(self):
        text = read("START-HERE.md")
        self.assertRegex(text, r"(?i)decide by the \*\*`maintainer`\*\* field")
        self.assertNotIn("fill every blank", text)

    def test_the_skill_routes_on_the_maintainer_field(self):
        text = read("skills", "ga-mcp-setup", "SKILL.md")
        self.assertIn("If its `maintainer` is blank", text)
        self.assertNotIn("If its values are blank", text)

    def test_the_skill_skips_sending_the_report_when_no_one_receives_it(self):
        text = read("skills", "ga-mcp-setup", "SKILL.md")
        self.assertRegex(text, r"(?is)if `install_reports_to` is blank.{0,200}skip sending")

    def test_the_manual_install_skips_sending_when_just_you(self):
        text = read("INSTALL.md")
        m = re.search(r"(?ms)^## 11\. Tell your maintainer.*?(?=^## )", text)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(0), r"(?is)just for yourself.{0,200}skip sending")

if __name__ == "__main__":
    unittest.main()
