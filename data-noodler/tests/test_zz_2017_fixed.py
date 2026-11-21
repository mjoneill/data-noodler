"""TRIAL ONLY (#2017): paste the FIXED renewal line, as produced on this
platform, into Windows PowerShell 5.1 and pwsh 7. Never merged."""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "server"))

import config  # noqa: E402


@unittest.skipUnless(sys.platform.startswith("win"), "Windows probe")
class Fixed2017(unittest.TestCase):
    def test_the_fixed_line_runs_in_both_powershells(self):
        d = os.path.join(tempfile.mkdtemp(), "dn probe dir")
        os.makedirs(d)
        script = os.path.join(d, "mint probe.py")
        with open(script, "w") as f:
            f.write("import sys\nprint('RAN', sys.argv[1:])\n")
        line = config.renewal_command(
            {"venv_python": sys.executable, "mint_script": script})
        print("FIXED2017 line:", line, "| shell:", config.renewal_shell(),
              flush=True)
        for shell in ("powershell", "pwsh"):
            exe = shutil.which(shell)
            self.assertIsNotNone(exe, shell)
            enc = base64.b64encode(line.encode("utf-16-le")).decode()
            r = subprocess.run([exe, "-NoProfile", "-NonInteractive",
                                "-EncodedCommand", enc],
                               capture_output=True, text=True)
            print(f"FIXED2017 {shell}: rc={r.returncode} "
                  f"out={r.stdout.strip()[:80]!r}", flush=True)
            self.assertEqual(r.returncode, 0, r.stderr[:300])
            self.assertIn("RAN ['--force']", r.stdout)
