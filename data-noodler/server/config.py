"""Config loader for the data-noodler server.

Deliberately duplicates ~30 lines of the data-noodler skill's
ga_config.py. The data-noodler server has to run in Claude Desktop's normal chat, where
no skill is installed and the skill's module is not importable, so it cannot
depend on it. The two loaders read the same file and must stay compatible.
"""

import json
import os

HOME_NAME = "data-noodler"
# #1999: installs from before the product had one name live here until
# installer/migrate_home.py moves them, and keep working meanwhile.
LEGACY_HOME_NAME = "ga-" "mcp"


def default_config_path(env=None, home=None):
    """The config this server reads: DATA_NOODLER_CONFIG when set, else the
    new home's, else an old home's that exists, else the new home's.

    The same rule as installer/home.py, which this module cannot import."""
    env = os.environ if env is None else env
    if env.get("DATA_NOODLER_CONFIG"):
        return env["DATA_NOODLER_CONFIG"]
    base = os.path.join(home or os.path.expanduser("~"), ".config")
    new = os.path.join(base, HOME_NAME)
    old = os.path.join(base, LEGACY_HOME_NAME, "config.json")
    if not os.path.isfile(os.path.join(new, "config.json")) and os.path.isfile(old):
        return old
    return os.path.join(new, "config.json")

PATH_KEYS = ("oauth_client_file", "adc_file", "venv_python", "properties_csv")
REQUIRED = PATH_KEYS

SETUP_HINT = ("Run the data-noodler-setup skill from Claude Code or Codex to finish "
              "installation.")


class ConfigError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


def load(path=None):
    path = default_config_path() if path is None else path

    if not os.path.exists(path):
        raise ConfigError(f"No GA configuration at {path}. {SETUP_HINT}")

    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path} could not be parsed as JSON: {exc}")

    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} must contain a JSON object, not {type(cfg).__name__}. {SETUP_HINT}")

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        raise ConfigError(
            f"{path} is missing required keys: {', '.join(missing)}. "
            f"{SETUP_HINT}")

    for key in PATH_KEYS:
        if not isinstance(cfg[key], str):
            raise ConfigError(
                f"{path}: key '{key}' must be a string, not {type(cfg[key]).__name__}. {SETUP_HINT}")
        cfg[key] = os.path.expanduser(cfg[key])
    return cfg


# The copy of the consent script that install.py's payload creates, under
# ~/.config/data-noodler/. bootstrap_config.build_config writes this same path into
# config.json as `mint_script`; this is the fallback for a config written
# before that key existed. It deliberately does NOT name
# ~/.claude/skills/data-noodler/scripts/mint_adc.py: nothing in the
# install payload ("server", "bin", "marketplace") creates ~/.claude/skills,
# so on a clean machine that path does not exist and the renewal command --
# the highest-value string this server produces, and the only diagnostic
# channel Claude Desktop's chat has -- would point at nothing.
DEFAULT_MINT_SCRIPT = ("~/.config/data-noodler/marketplace/plugins/data-noodler"
                       "/skills/data-noodler/scripts/mint_adc.py")


def default_mint_script(home=None):
    """DEFAULT_MINT_SCRIPT under the home this machine actually has: an
    install from before the rename keeps the old one until migrate_home.py
    moves it (#1999), and a renewal command naming the new home there would
    point at nothing."""
    base = os.path.dirname(default_config_path(env={}, home=home))
    return os.path.join(base, *DEFAULT_MINT_SCRIPT.split("/")[3:])


# #1999: the plugin and skill folders' names before the product had one name.
# A config.json written then names the consent script under them; the
# reinstall renamed the folders, so the path is followed to where it is now.
_OLD_SCRIPT_DIRS = "/plugins/ga-" "analytics/skills/google-" "analytics/"
_NEW_SCRIPT_DIRS = "/plugins/data-noodler/skills/data-noodler/"


def mint_script(cfg):
    script = cfg.get("mint_script") or default_mint_script()
    return script.replace(_OLD_SCRIPT_DIRS, _NEW_SCRIPT_DIRS)


def renewal_command(cfg):
    """The exact command a user must paste into a terminal to reauthenticate.

    Both paths are quoted. The venv path contains a space on macOS
    ("Application Support"), and the script path is under the user's home
    directory, which can contain one too -- an unquoted command silently
    fails for the least technical user. Quoting is only safe because both
    paths are expanded first: a quoted "~" is a literal tilde to the shell,
    not the home directory.
    """
    script = mint_script(cfg)
    return (f'"{os.path.expanduser(cfg["venv_python"])}" '
            f'"{os.path.expanduser(script)}" --force')


def sessions_root(cfg):
    """Where session folders are created.

    Optional and defaulted rather than required: the live config on this
    machine predates this key by months, and config.load must keep working
    for every install that has not been regenerated. The import is placed
    inside the function to preserve graceful runtime failure: a module-level
    import would make config.load() unimportable if sessions.py is missing,
    converting a runtime error into an import-time one.
    """
    import sessions
    # normpath: the default is "~/Documents/analyst-sessions", and expanduser
    # alone printed C:\\Users\\x/Documents/analyst-sessions on Windows.
    return os.path.normpath(os.path.expanduser(
        cfg.get("sessions_root") or sessions.DEFAULT_SESSIONS_ROOT))


def quota_project(cfg):
    """The GCP project to bill/report GA API usage against, or None.

    Optional, not defaulted: both the GA Data API and the GA Admin API work
    with no quota project header at all, so None is a legitimate value, not
    a degraded one. A value is only correct here for someone who owns the
    named Cloud project -- sending it as any other caller makes Google
    demand serviceusage.services.use on a project they have no IAM role in,
    which is exactly the failure a shared install must not force on them.
    """
    return cfg.get("quota_project") or None


def granted_scopes(cfg):
    """Scopes the stored credential records, or [] if it records none.

    mint_adc.py writes a credential without a scopes key -- the grant is bound
    to the token server-side, not to the file -- so an empty list means
    "unknown", never "none". Callers must not treat it as a denial.
    """
    path = cfg.get("adc_file")
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    scopes = data.get("scopes")
    return list(scopes) if isinstance(scopes, list) else []
