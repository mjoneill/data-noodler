"""Shared config loader for the data-noodler skill scripts.

All machine-specific values (paths, GCP project, venv location) live in
~/.config/ga-mcp/config.json so the skill itself stays portable and carries no
account identity. Scripts import from here rather than hardcoding anything.
"""

import json
import os
import sys

CONFIG_PATH = os.path.expanduser("~/.config/ga-mcp/config.json")

REQUIRED = [
    "oauth_client_file",
    "adc_file",
    "venv_python",
    "properties_csv",
]
# quota_project is deliberately absent from REQUIRED, matching the
# data-noodler's config.py: both GA APIs work with no quota-project header, and
# a colleague does not own the author's Cloud project, so requiring it here
# would fail every install that doesn't set one. mint_adc.py reads it with
# cfg.get("quota_project"), never cfg["quota_project"], for the same reason.


def load():
    """Return config with all path values expanded, or exit with guidance."""
    # gRPC's default c-ares resolver reads /etc/resolv.conf, which macOS itself
    # ignores; on split-DNS networks they disagree and every API call fails with
    # "Could not contact DNS servers" even though nslookup and curl work. Using
    # the system resolver avoids that. setdefault so an explicit env still wins.
    # This covers these scripts only -- the MCP server never imports this module,
    # so its registration must set the variable too (see references/setup.md).
    os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            f"No config at {CONFIG_PATH}.\n"
            "This machine has not been set up yet -- see references/setup.md "
            "in the data-noodler skill."
        )
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        sys.exit(f"Config {CONFIG_PATH} is missing keys: {', '.join(missing)}")

    for key in ("oauth_client_file", "adc_file", "venv_python", "properties_csv"):
        cfg[key] = os.path.expanduser(cfg[key])
    return cfg


def require_adc(cfg):
    """Exit with the renewal command if the credential is absent."""
    if not os.path.exists(cfg["adc_file"]):
        sys.exit(
            f"Missing credential: {cfg['adc_file']}\n"
            f'Mint one with:\n  "{cfg["venv_python"]}" '
            f"{os.path.dirname(os.path.abspath(__file__))}/mint_adc.py"
        )
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cfg["adc_file"]
