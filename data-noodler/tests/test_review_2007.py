"""Three findings from the 2026-11-20 outside review (#2007 R4, R5, R6).

R4  A pivot's filename was built from the raw dimension name. GA custom
    dimensions are named customEvent:<x> / customUser:<x>, and a colon is
    illegal in a Windows filename. The long export already survived (export
    wraps the OSError as ExportError, which _write_pivot catches), so only the
    pivot was lost -- on Windows, for exactly the dimensions people define
    themselves.

R5  security_floors.py carries an aiohttp floor, but aiohttp is not in the
    supported install: only optional extras (google-auth[aiohttp],
    google-adk[mcp], ...) ask for it, and constraints.txt does not pin it.
    minimo recommended (55952), and the PO adopted: do not add an unused
    dependency to make the floor "fire". Keep the floor -- probe.py applies it to whatever is installed --
    and make the contract explicit: if aiohttp ever enters the pins, this
    fails, and whoever re-captured them decides on purpose.

R6  analytics-mcp's version is written in seven code and workflow sites. A
    bump that missed upgrade.py would install a different analytics-mcp from
    the one the pins were captured and tested against, and nothing would fail.
"""

import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "installer"))

WINDOWS_ILLEGAL = set('<>:"/\\|?*')


class TestPivotFilenameIsSafeOnWindows(unittest.TestCase):

    def setUp(self):
        import data_noodler
        self.mod = data_noodler
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.columns = ["date", "customEvent:topic", "sessions"]
        self.rows = [["2026-08-06", "a", "4"], ["2026-08-06", "b", "5"]]
        self.meta = {"source": "ga4", "property_id": "314159265",
                     "sampled": False, "row_limit_hit": False}

    def _pivot(self, pivot_on="customEvent:topic"):
        path = os.path.join(self.d, "report.csv")
        return self.mod._write_pivot(path, self.columns, self.rows, self.meta,
                                     pivot_on, ["sessions"], False)

    def test_a_custom_dimension_makes_a_windows_legal_filename(self):
        result = self._pivot()
        self.assertNotIn("error", result, result)
        name = os.path.basename(result["path"])
        self.assertFalse(WINDOWS_ILLEGAL & set(name), name)
        self.assertIn("customEvent", name)

    def test_the_true_dimension_name_is_kept_in_the_sidecar(self):
        result = self._pivot()
        with open(result["path"][:-len(".csv")] + ".meta.json",
                  encoding="utf-8") as f:
            self.assertEqual(json.load(f)["pivot_on"], "customEvent:topic")

    def test_any_filesystem_failure_degrades_to_a_reported_pivot_error(self):
        with mock.patch.object(self.mod.export, "write_export",
                               side_effect=OSError("disk said no")):
            result = self._pivot()
        self.assertIn("error", result)


class TestAiohttpIsOutsideTheSupportedInstall(unittest.TestCase):

    def test_aiohttp_is_not_pinned_and_its_floor_stays_for_probe(self):
        from security_floors import FLOORS
        with open(os.path.join(ROOT, "installer", "constraints.txt"),
                  encoding="utf-8") as f:
            pinned = {line.split("==")[0].strip().lower()
                      for line in f if "==" in line and not line.startswith("#")}
        self.assertNotIn(
            "aiohttp", pinned,
            "aiohttp has entered the pinned set. It used to come only from "
            "optional extras. Decide on purpose: add it to the must-be-present "
            "list in test_constraints_security.py, and drop this test.")
        self.assertIn("aiohttp", FLOORS,
                      "probe.py still checks installed venvs against this floor")


class TestAnalyticsMcpVersionIsWrittenOnceInEffect(unittest.TestCase):

    SITES = [
        ("data-noodler", "installer", "upgrade.py"),
        ("data-noodler", "installer", "bootstrap_config.py"),
        ("data-noodler", "marketplace", "plugins", "data-noodler", "skills",
         "data-noodler", "scripts", "mint_adc.py"),
        (".github", "workflows", "ci.yml"),
        (".github", "workflows", "refresh-pins.yml"),
    ]

    def test_every_site_names_the_pinned_version(self):
        with open(os.path.join(ROOT, "installer", "constraints.txt"),
                  encoding="utf-8") as f:
            pins = re.findall(r"(?m)^analytics-mcp==(\S+)", f.read())
        self.assertEqual(len(pins), 1, pins)
        pinned = pins[0]
        for parts in self.SITES:
            with self.subTest(os.path.join(*parts)):
                with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
                    found = re.findall(r"analytics-mcp==([0-9][\w.]*)", f.read())
                self.assertTrue(found, "this site no longer names a version; "
                                       "update SITES if that was deliberate")
                self.assertEqual(set(found), {pinned})


if __name__ == "__main__":
    unittest.main()
