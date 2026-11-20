#!/usr/bin/env python3
"""Regenerate constraints.txt from an interpreter where the servers work.

Run with the interpreter named by venv_python in ~/.config/ga-mcp/config.json,
after verify.py passes against it. The point of a pin is that somebody ran it;
capturing from a machine that has not been verified produces a guess carrying
the authority of a fact.

    <venv_python> installer/freeze_constraints.py > installer/constraints.txt
"""

import datetime
import importlib.metadata as md
import sys


def main():
    dists = sorted({d.metadata["Name"]: d.version
                    for d in md.distributions()}.items(),
                   key=lambda kv: kv[0].lower())
    version = ".".join(str(n) for n in sys.version_info[:3])
    print(f"# Regenerated {datetime.date.today().isoformat()} from Python "
          f"{version} on {sys.platform}, {len(dists)} distributions.")
    print("# See the committed constraints.txt header for what this is for.")
    for name, pinned in dists:
        print(f"{name}=={pinned}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
