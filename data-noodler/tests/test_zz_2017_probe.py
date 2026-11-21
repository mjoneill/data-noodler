"""TRIAL ONLY (#2017): run the renewal line exactly as a user would paste it,
in PowerShell 5.1, pwsh 7 and cmd.exe, with and without a leading "& ".
Never merged; prints PROBE2017 lines and always passes."""

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
class Probe2017(unittest.TestCase):
    def test_probe(self):
        d = os.path.join(tempfile.mkdtemp(), "dn probe dir")
        os.makedirs(d)
        script = os.path.join(d, "mint probe.py")
        with open(script, "w") as f:
            f.write("import sys\nprint('RAN', sys.argv[1:])\n")
        line = config.renewal_command(
            {"venv_python": sys.executable, "mint_script": script})
        print("PROBE2017 line:", line, flush=True)
        for shell in ("powershell", "pwsh"):
            exe = shutil.which(shell)
            for prefix in ("", "& "):
                if not exe:
                    print(f"PROBE2017 {shell} {prefix!r}: not installed")
                    continue
                enc = base64.b64encode((prefix + line).encode("utf-16-le"))
                r = subprocess.run([exe, "-NoProfile", "-NonInteractive",
                                    "-EncodedCommand", enc.decode()],
                                   capture_output=True, text=True)
                print(f"PROBE2017 {shell} {prefix!r}: rc={r.returncode} "
                      f"out={r.stdout.strip()[:120]!r} "
                      f"err={r.stderr.strip()[:200]!r}", flush=True)
        for prefix in ("", "& "):
            cmdline = f'cmd.exe /d /s /c "{prefix}{line}"'
            r = subprocess.run(cmdline, capture_output=True, text=True)
            print(f"PROBE2017 cmd {prefix!r}: rc={r.returncode} "
                  f"out={r.stdout.strip()[:120]!r} "
                  f"err={r.stderr.strip()[:200]!r}", flush=True)
