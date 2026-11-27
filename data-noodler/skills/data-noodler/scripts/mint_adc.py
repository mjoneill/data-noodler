#!/usr/bin/env python3
"""Mint (or renew) an ADC credential scoped to Google Analytics and Search Console, read-only.

Why this exists instead of `gcloud auth application-default login`:
gcloud's ADC login path contains an unconditional check that refuses to
proceed unless the cloud-platform scope is requested
(lib/surface/auth/application_default/login.py). cloud-platform authorizes
Cloud actions as you across *every project your account can reach* -- far more
than an analytics reader needs, and a much worse credential to leak.

That check is gcloud's own policy, not a Google API restriction. This runs the
same OAuth installed-app loopback flow gcloud would, requests only the two
narrow read-only scopes it needs, and writes the standard `authorized_user`
ADC JSON that google-auth reads natively. It prints the scopes Google actually
granted so the result is verifiable rather than assumed.

Usage:
    <venv_python> mint_adc.py            # first run
    <venv_python> mint_adc.py --force    # renew, replacing the existing file
"""

import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga_config

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]

def oauthlib_install_hint(executable):
    """The command that adds google-auth-oauthlib to THIS interpreter.

    This used to say `pipx inject` unconditionally. That is a real command and
    correct for a pipx install -- but uv has no inject verb, and a Windows
    venv has no pipx at all. A wall message is what the next reader runs, so it
    has to match how this interpreter was actually installed. Round 3 found it;
    the same drift was fixed once before in bootstrap_config and this string
    was missed.
    """
    path = executable.replace("\\", "/")
    if "/pipx/venvs/" in path:
        return "  pipx inject analytics-mcp google-auth-oauthlib"
    if "/uv/tools/" in path:
        return ("  uv tool install analytics-mcp==1.1.0 "
                "--with google-auth-oauthlib --force")
    return f'  "{executable}" -m pip install google-auth-oauthlib'


try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit(
        "Missing google-auth-oauthlib. Add it to the interpreter running this "
        "script:\n" + oauthlib_install_hint(sys.executable)
    )

cfg = ga_config.load()
force = "--force" in sys.argv
out_file = cfg["adc_file"]
client_file = cfg["oauth_client_file"]

if os.path.exists(out_file) and not force:
    sys.exit(
        f"{out_file} already exists.\n"
        "Pass --force to replace it (the normal renewal path)."
    )

if not os.path.exists(client_file):
    sys.exit(
        f"Missing OAuth client file: {client_file}\n"
        "Get the OAuth client file from your maintainer, or create your own -- "
        "see GOOGLE-CLOUD-SETUP.md in the Data Noodler package."
    )

print("Requesting exactly these scopes:")
for s in SCOPES:
    print(f"  {s}")
print()
print("A browser window will open for consent. If the OAuth app is still in")
print('"Testing" status you will see "Google hasn\'t verified this app" -- that')
print("is your own client; continue via Advanced. Confirm the consent screen")
print("asks only to see and download Google Analytics data, and to see")
print("Search Console data and sites -- nothing broader.\n")

flow = InstalledAppFlow.from_client_secrets_file(client_file, scopes=SCOPES)
creds = flow.run_local_server(
    port=0,
    access_type="offline",
    prompt="consent",
    open_browser=True,
)

if not creds.refresh_token:
    sys.exit("No refresh token returned; cannot write a durable credential.")

granted = set(creds.scopes or [])
print("\nScopes actually granted by Google:")
for scope in sorted(granted):
    print(f"  {scope}")
unexpected = granted - set(SCOPES)
if unexpected:
    print("\nWARNING: broader than requested:", ", ".join(sorted(unexpected)))

adc = {
    "type": "authorized_user",
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "refresh_token": creds.refresh_token,
}
# Only set when the config actually names a project. Both the GA Data API
# and the GA Admin API work with no quota project at all, and setting one
# makes google-auth send x-goog-user-project on every call -- which Google
# then requires the caller to hold serviceusage.services.use on. That is
# correct for someone who owns the named Cloud project, but wrong to default
# for everyone else: a colleague authorized as an OAuth test user has consent,
# not IAM, on the author's project, and would see every GA call fail.
if cfg.get("quota_project"):
    adc["quota_project_id"] = cfg["quota_project"]

# Write to a temp file with owner-only permissions, then atomically replace, so
# an interrupted renewal can never leave a truncated credential behind.
os.makedirs(os.path.dirname(out_file), exist_ok=True)
tmp = out_file + ".tmp"
if os.path.exists(tmp):
    os.unlink(tmp)
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
with os.fdopen(fd, "w") as f:
    json.dump(adc, f, indent=2)
os.replace(tmp, out_file)


def restrict_windows_acl(path):
    """Grant this user alone full control; drop every inherited permission.

    The mode bits above are POSIX. On Windows they are close to meaningless:
    the file inherits whatever the parent directory grants, which in a default
    profile includes SYSTEM and Administrators. That is not a catastrophe --
    profile isolation is real -- but it is materially weaker than the 0600
    this code appears to promise, and appearing to promise it is the problem.

    Returns a human-readable outcome. NEVER raises, and never fails the mint:
    the credential is already written and valid by this point, and refusing to
    report success because a hardening step did not run would send the user
    back through a browser consent flow for nothing.
    """
    if os.name != "nt":
        return None
    user = os.environ.get("USERNAME")
    if not user:
        return "could not tighten ACL: USERNAME is not set"
    try:
        proc = subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run icacls ({exc}); relying on profile isolation"
    if proc.returncode != 0:
        return (f"icacls exited {proc.returncode}; relying on profile "
                f"isolation. {proc.stdout.strip() or proc.stderr.strip()}")
    return f"ACL restricted to {user} (inherited permissions removed)"


acl_note = restrict_windows_acl(out_file)

print(f"\nCredentials saved to file: [{out_file}]")
if os.name == "nt":
    print(f"Permissions: {acl_note}")
else:
    print(f"Permissions: {oct(os.stat(out_file).st_mode & 0o777)}")
print("\nRestart any running MCP client session -- it holds the old token in memory.")
