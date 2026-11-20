#!/usr/bin/env python3
"""Rebuild the local GA property snapshot.

Thin CLI wrapper. The Admin API enumeration itself lives in the data-noodler server
server's snapshot module, so the MCP tool and this command cannot drift --
they are the same code. This wrapper exists because a shell-having harness can
run it directly, which is faster than a tool round-trip.

Must run with the analytics-mcp venv's Python (see venv_python in
~/.config/ga-mcp/config.json).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga_config

cfg = ga_config.load()
ga_config.require_adc(cfg)

SERVER_DIR = os.path.expanduser("~/.config/ga-mcp/server")
if not os.path.isdir(SERVER_DIR):
    sys.exit(f"data-noodler not installed at {SERVER_DIR}. "
             "Run the data-noodler-setup skill.")
sys.path.insert(0, SERVER_DIR)

try:
    import snapshot
except ImportError as exc:
    sys.exit(f"Could not import the shared snapshot module: {exc}")

rows, accounts = snapshot.rebuild(cfg["properties_csv"])
print(f"wrote {rows} properties across {accounts} accounts "
      f"to {cfg['properties_csv']}")
