"""constraints.txt must never pin back below a version known to be vulnerable.

On 2026-10-23 a security review found that the pins captured 2026-09-14 had
aged into PyJWT 2.13.0 (critical), urllib3 2.7.0, cryptography 49.0.0,
aiohttp 3.14.3 and a certifi that still trusted the compromised
eMudhra/emSign roots. constraints.txt *is* the Windows install path, so every
Windows install was forced onto them (#151).

The real check is the OSV scan named in the file's header, run before every
zip; it needs the network and finds tomorrow's advisories. This test is the
offline half: the floors below are the versions that fixed what was found,
so a regeneration from a stale interpreter -- or a hand edit -- cannot
quietly bring them back. Raise a floor whenever a scan finds something new.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSTRAINTS = os.path.join(ROOT, "installer", "constraints.txt")

sys.path.insert(0, os.path.join(ROOT, "installer"))
from security_floors import FLOORS, below_floor, version_key as _version_key  # noqa: E402

# The advisory that was accepted until google-adk 2.15.0 allowed its fix
# (#1986, 2026-11-20). It must not be ignored again.
FORMERLY_ACCEPTED = "CVE-2026-114603"

# The 2026-11-19 scan's findings and the versions that fixed them (#1986).
# opentelemetry-sdk had no advisory of its own: it moves in lockstep with
# opentelemetry-api, so it is floored with it.
FIXED_2026_11 = {"oauthlib": "4.0.1", "pyasn1": "0.6.5",
                 "opentelemetry-api": "1.45.2", "opentelemetry-sdk": "1.45.2"}


def _pins():
    pins = {}
    with open(CONSTRAINTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "==" in line:
                name, version = line.split("==", 1)
                pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


class TestNoPinBelowAKnownFix(unittest.TestCase):

    def test_no_pin_is_below_its_floor(self):
        low = below_floor(_pins())
        self.assertEqual(low, {}, "pinned below a known-vulnerable floor "
                                  "(pinned, floor): %r" % low)

    def test_the_packages_that_carried_the_worst_findings_are_still_pinned(self):
        # A floor on a package that silently dropped out of the file proves
        # nothing; these are always installed, so they must be present.
        pins = _pins()
        for name in ("pyjwt", "urllib3", "cryptography", "certifi", "pip"):
            self.assertIn(name, pins, name)

    def test_pip_is_pinned_so_the_venv_upgrade_can_use_it(self):
        # pip below 26.2.2 vendors the compromised roots; the docs upgrade it
        # with -c constraints.txt, which only works if pip is in the file.
        self.assertIn("pip", _pins())

    def test_the_floors_reject_the_set_that_was_actually_shipped(self):
        # The 2026-09-14 pins, as found 2026-10-23. If the floors ever stop
        # catching these, they are not floors.
        shipped = {"PyJWT": "2.13.0", "urllib3": "2.7.0",
                   "cryptography": "49.0.0", "certifi": "2026.7.22",
                   "aiohttp": "3.14.3", "mcp": "1.29.0"}
        self.assertEqual(set(below_floor(shipped)),
                         {"pyjwt", "urllib3", "cryptography", "certifi",
                          "aiohttp", "mcp"})
        self.assertTrue(set(below_floor(shipped)) <= set(FLOORS))


class TestTheHeaderCarriesTheScan(unittest.TestCase):

    def setUp(self):
        with open(CONSTRAINTS, encoding="utf-8") as f:
            self.text = f.read()

    def test_it_names_the_scan_to_run_before_shipping(self):
        self.assertIn("pip-audit", self.text)
        self.assertIn("-s osv", self.text)

    def test_no_advisory_is_ignored_any_more(self):
        # #1986: every finding now has a fix inside the pins, so the scan
        # line carries no exception, and a new advisory fails it.
        self.assertNotIn("--ignore-vuln", self.text)
        self.assertNotIn("ACCEPTED EXCEPTION", self.text)

    def test_the_trace_parsing_switch_off_is_still_explained(self):
        # Kept as defence in depth after the fix: nothing exports traces, so
        # parsing them buys nothing.
        self.assertIn("OTEL_PROPAGATORS=none", self.text)
        self.assertIn("switched off", self.text)

    def test_the_2026_11_findings_have_floors(self):
        for name, fixed in FIXED_2026_11.items():
            with self.subTest(package=name):
                self.assertEqual(FLOORS.get(name), fixed)

    def test_the_floors_reject_the_2026_11_set(self):
        shipped = {"oauthlib": "4.0.0", "pyasn1": "0.6.4",
                   "opentelemetry-api": "1.44.0", "opentelemetry-sdk": "1.44.0"}
        self.assertEqual(set(below_floor(shipped)), set(shipped))

    def test_the_version_comparison_orders_dates_and_releases(self):
        self.assertLess(_version_key("2026.7.22"), _version_key("2026.10.23"))
        self.assertLess(_version_key("2.13.0"), _version_key("2.15.1"))
        self.assertLess(_version_key("49.0.0"), _version_key("50.0.2"))



class TestEveryInstallPathUsesThePins(unittest.TestCase):
    """The pins only protect an install whose commands actually name them.

    Before 2026-10-23 the macOS commands did not, so a Mac got whatever was
    newest that day and kept it; and no upgrade path touched the libraries at
    all (#152).
    """

    DIST = ROOT
    REPO = os.path.dirname(ROOT)

    def _read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def _uv_install_lines(self, text):
        return [l.strip() for l in text.splitlines()
                if l.strip().startswith("uv tool install analytics-mcp")]

    def test_every_macos_install_command_names_the_constraints(self):
        for doc in (("INSTALL.md",), ("skills", "ga-mcp-setup", "SKILL.md")):
            lines = self._uv_install_lines(self._read(self.DIST, *doc))
            self.assertTrue(lines, doc)
            for line in lines:
                self.assertIn("-c ", line, f"{doc}: {line}")
                self.assertIn("constraints.txt", line, f"{doc}: {line}")

    def test_the_windows_pip_upgrade_is_pinned_too(self):
        text = self._read(self.DIST, "skills", "ga-mcp-setup", "references",
                          "windows.md")
        pip_lines = [l for l in text.splitlines() if "-m pip install" in l]
        self.assertTrue(pip_lines)
        for line in pip_lines:
            if '"pip @ ' in line:
                # pip itself is installed by exact URL and sha256 (#163) --
                # stronger than a constraint, since the starting pip cannot
                # be trusted to download anything.
                self.assertIn("#sha256=", line, line)
            else:
                self.assertIn("constraints.txt", line, line)
        self.assertTrue(any('"pip @ ' in l for l in pip_lines))

    def test_the_skill_refreshes_libraries_on_upgrade(self):
        text = self._read(self.DIST, "skills", "ga-mcp-setup", "SKILL.md")
        self.assertIn("On an upgrade: refresh the libraries", text)
        self.assertIn("below_floor", text)
        self.assertIn("installer/upgrade.py", text)
        self.assertIn("--plan", text)

    def test_the_zip_checklist_scans_before_building(self):
        path = os.path.join(self.REPO, "docs", "runbooks", "INSTALL-DAY.md")
        if not os.path.exists(path):
            self.skipTest("the install-day runbook is the maintainer's, not "
                          "the package's")
        text = self._read(path)
        scan, build = text.find("pip-audit"), text.find("zip -qr")
        self.assertNotEqual(scan, -1, "no scan in the zip checklist")
        self.assertLess(scan, build, "the scan must come before the build")


if __name__ == "__main__":
    unittest.main()
