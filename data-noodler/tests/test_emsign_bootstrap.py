"""eMudhra/emSign (October 2026): no venv step may trust its starting pip (#163).

A new venv's pip comes from the Python installer (pip 25.0.1 on 3.12.13,
measured) and still trusts the compromised CA keys, so it must not download
anything -- not even a newer pip -- except by exact URL and SHA-256. Tested
2026-10-25: from pip 25.0.1 a wrong hash is refused and the pinned wheel
installs 26.2.2.
"""

import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))

import bootstrap_config  # noqa: E402
import probe  # noqa: E402
import security_floors  # noqa: E402

DOCS = (
    os.path.join(ROOT, "skills", "ga-mcp-setup", "references", "windows.md"),
    os.path.join(ROOT, "skills", "ga-mcp-setup", "SKILL.md"),
    os.path.join(ROOT, "INSTALL.md"),
    os.path.join(REPO, "docs", "runbooks", "INSTALL-DAY.md"),
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _present(paths):
    """The runbook is the maintainer's, not the package's: absent in a share."""
    return [p for p in paths if os.path.exists(p)]


class TestThePinnedPip(unittest.TestCase):

    def test_the_constant_is_a_full_hash_pinned_wheel(self):
        req = security_floors.PIP_BOOTSTRAP_REQUIREMENT
        self.assertTrue(req.startswith("pip @ https://files.pythonhosted.org/"))
        self.assertRegex(security_floors.PIP_BOOTSTRAP_SHA256, r"^[0-9a-f]{64}$")
        self.assertIn("pip-26.2.2-", req)
        self.assertEqual(security_floors.FLOORS["pip"], "26.2.2")

    def test_every_windows_venv_step_installs_pip_by_hash(self):
        for path in _present((DOCS[0], DOCS[3])):
            text = _read(path)
            if "-m venv" not in text:
                continue
            self.assertIn(security_floors.PIP_BOOTSTRAP_REQUIREMENT, text, path)

    def test_no_document_tells_anyone_to_upgrade_pip_unpinned(self):
        for path in _present(DOCS):
            for line in _read(path).splitlines():
                if "--upgrade pip" in line and "never" not in line.lower():
                    self.fail(f"{os.path.basename(path)}: {line.strip()}")

    def test_the_windows_wall_text_matches(self):
        self.assertIn(security_floors.PIP_BOOTSTRAP_REQUIREMENT,
                      bootstrap_config.INSTALL_HINT_WINDOWS)


class TestUvFloor(unittest.TestCase):

    def _probe(self, version_line):
        run = mock.Mock(return_value=mock.Mock(stdout=version_line))
        return probe.probe_uv(which=lambda _: "/x/uv", run=run)

    def test_an_old_uv_is_reported_below_floor(self):
        self.assertTrue(self._probe("uv 0.13.3 (abc 2026-10-01)")["below_floor"])

    def test_a_fixed_uv_is_not(self):
        self.assertFalse(self._probe("uv 0.13.5 (Homebrew 2026-10-22)")["below_floor"])

    def test_no_uv_is_reported_absent_not_below(self):
        out = probe.probe_uv(which=lambda _: None)
        self.assertIsNone(out["path"])
        self.assertIsNone(out["below_floor"])

    def test_the_mac_install_docs_check_the_uv_version(self):
        for path in _present((DOCS[1], DOCS[2], DOCS[3])):
            self.assertIn("0.13.4", _read(path), path)


if __name__ == "__main__":
    unittest.main()
