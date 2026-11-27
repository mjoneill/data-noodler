"""Shared config loader for the data-noodler skill scripts.

All machine-specific values (paths, GCP project, venv location) live in
~/.config/data-noodler/config.json so the skill itself stays portable and carries no
account identity. Scripts import from here rather than hardcoding anything.
"""

import json
import os
import sys



def _config_path():
    """DATA_NOODLER_CONFIG, else the new home's, else an old home's that
    exists (#1999: installs from before the rename keep working until
    migrate_home.py moves them). The same rule as the server's config.py."""
    if os.environ.get("DATA_NOODLER_CONFIG"):
        return os.environ["DATA_NOODLER_CONFIG"]
    base = os.path.expanduser("~/.config")
    new = os.path.join(base, "data-noodler")
    old = os.path.join(base, "ga-" "mcp", "config.json")
    if not os.path.isfile(os.path.join(new, "config.json")) and os.path.isfile(old):
        return old
    return os.path.join(new, "config.json")


CONFIG_PATH = _config_path()

SETUP_HINT = ("Run the data-noodler-setup skill from Claude Code or Codex to "
              "finish or repair installation.")

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
    # so its registration must set the variable too (the installer's launchers and
    # Windows entries do).
    os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            f"No config at {CONFIG_PATH}.\n"
            "This machine has not been set up yet -- run the data-noodler-setup "
            "skill (an agent runs it, or follow its steps yourself)."
        )
    # The same checks, in the same order, as the server's config.py (#2007 R3):
    # a terminal user with a half-written file deserves at least the guidance
    # the server gives. tests/test_fallback_copies.py runs one set of
    # malformed files through both loaders.
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        sys.exit(f"{CONFIG_PATH} could not be parsed as JSON: {exc}\n{SETUP_HINT}")

    if not isinstance(cfg, dict):
        sys.exit(f"{CONFIG_PATH} must contain a JSON object, not "
                 f"{type(cfg).__name__}.\n{SETUP_HINT}")

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        sys.exit(f"Config {CONFIG_PATH} is missing keys: {', '.join(missing)}\n"
                 f"{SETUP_HINT}")

    for key in ("oauth_client_file", "adc_file", "venv_python", "properties_csv"):
        if not isinstance(cfg[key], str):
            sys.exit(f"{CONFIG_PATH}: key '{key}' must be a string, not "
                     f"{type(cfg[key]).__name__}.\n{SETUP_HINT}")
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
