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


if __name__ == "__main__":
    unittest.main()
