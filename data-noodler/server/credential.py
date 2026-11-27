"""Credential expiry reporting.

Google issues 7-day refresh tokens to OAuth apps whose publishing status is
"Testing" when they request anything beyond basic profile scopes. Nothing in
the credential file records that deadline, so the file's mtime -- the moment
consent was granted -- is the only clock available.
"""

import os
import time

WINDOW_DAYS = 7
WARN_DAYS = 2
DAY = 86400.0


def credential_report(adc_path, renewal_command, now=None, shell="a terminal"):
    """Describe the credential's remaining life and what to do about it.

    `shell` names where `renewal_command` runs ("PowerShell" on Windows,
    where the line only runs there -- #2017)."""
    now = time.time() if now is None else now

    if not os.path.exists(adc_path):
        return {
            "exists": False,
            "days_remaining": None,
            "expired": True,
            "renewal_command": renewal_command,
            "summary": (
                f"No credential found at {adc_path}.\n"
                f"Mint one by running this in {shell} (it opens a browser "
                f"for Google consent):\n  {renewal_command}\n"
                "Then restart this application -- the server reads the "
                "credential only when it starts."
            ),
        }

    try:
        mtime = os.path.getmtime(adc_path)
    except OSError:
        return {
            "exists": False,
            "days_remaining": None,
            "expired": True,
            "renewal_command": renewal_command,
            "summary": (
                f"Credential file exists at {adc_path} but cannot be read "
                "(permission denied, transient I/O error, or cloud-sync placeholder).\n"
                f"Try renewing the credential, in {shell}:\n  {renewal_command}\n"
                "Then restart this application -- the server reads the "
                "credential only when it starts."
            ),
        }

    remaining = WINDOW_DAYS - (now - mtime) / DAY
    expired = remaining <= 0

    if expired:
        summary = (
            f"Credential expired about {abs(remaining):.1f} days ago "
            f"(7-day Testing-mode window).\n"
            "GA calls will fail with invalid_grant until it is renewed. Run "
            f"this in {shell}:\n  {renewal_command}\n"
            "Then restart this application -- the server holds the old token "
            "in memory until it respawns, which otherwise looks like the "
            "renewal did not work."
        )
    elif remaining <= WARN_DAYS:
        summary = (
            f"Credential is valid for about {remaining:.1f} more days, then "
            "GA calls will start failing with invalid_grant.\n"
            f"Renew when convenient, in {shell}:\n  {renewal_command}\n"
            "A restart of this application is needed afterward."
        )
    else:
        summary = (f"Credential is healthy -- about {remaining:.1f} days "
                   f"remaining in the 7-day window.")

    return {
        "exists": True,
        "days_remaining": remaining,
        "expired": expired,
        "renewal_command": renewal_command,
        "summary": summary,
    }


GA_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def scope_line(scopes):
    """What this credential can reach, in words rather than URLs.

    An empty list means the credential file records no scopes -- which is the
    normal case, because mint_adc.py writes none and the grant lives with the
    token server-side. Absence is "unknown", never "denied", so it must not
    prompt a re-mint.
    """
    if not scopes:
        return ("Granted scopes are not recorded in the credential file, so "
                "what it can reach is not known from here. A Search Console "
                "permission error has two causes and they need opposite "
                "responses: either the credential predates the "
                "webmasters.readonly scope, which re-minting fixes, or this "
                "Google account is not a verified owner or user on that "
                "specific site, which no re-mint can fix -- someone with "
                "access has to add the account in Search Console. Check the "
                "site list with gsc_list_sites first: a site that appears "
                "there is one this account already has access to, so a 403 "
                "on it points at the scope, and a site that does not appear "
                "points at access. Re-consent is the most destructive action "
                "in this package; do not reach for it first.")

    has_ga = GA_SCOPE in scopes
    has_gsc = GSC_SCOPE in scopes
    parts = []
    if has_ga:
        parts.append("Google Analytics (read-only)")
    if has_gsc:
        parts.append("Search Console (read-only)")
    reach = " and ".join(parts) if parts else "nothing recognized"

    line = f"This credential can reach: {reach}."
    if not has_gsc:
        line += (" Search Console is NOT included — re-mint the credential to "
                 "add it.")
    return line
