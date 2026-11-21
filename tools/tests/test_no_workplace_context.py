"""#2013: the public package carries no context from the maintainer's workplace.

Windows support was proven on machines without administrator rights, and the
docs say so. They must not describe whose machines those were: no department
that approves installs, no named software catalogue, no edition of Windows
that points at a kind of employer, no "the reports stay with the maintainer".
Advice for a locked-down machine names the mechanism ("whoever manages the
machine", "an application-control policy"), never a department.

Seats write these docs from the maintainer's own accounts, so the wording
comes back unless something refuses it. This is that something.
"""

import os
import subprocess
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Built from parts so this file does not match its own check.
FORBIDDEN = [
    r"(?-i:\b" + "I" + r"T\b)",                 # the department, any use
    "software " + "center",
    r"windows 1[01] " + "education",
    "original " + "maintainer",
]

THIS_FILE = "tools/tests/test_no_workplace_context.py"


def _grep(pattern):
    r = subprocess.run(["git", "grep", "-n", "-I", "-P", "(?i)" + pattern],
                       cwd=TOP, capture_output=True, text=True)
    return [line for line in r.stdout.splitlines()
            if line and not line.startswith(THIS_FILE + ":")]


class TestNoWorkplaceContext(unittest.TestCase):
    def test_no_tracked_file_carries_workplace_context(self):
        stray = []
        for pattern in FORBIDDEN:
            stray += [line[:160] for line in _grep(pattern)]
        self.assertEqual(stray, [], "workplace context in a tracked file:\n"
                         + "\n".join(stray))


if __name__ == "__main__":
    unittest.main()
