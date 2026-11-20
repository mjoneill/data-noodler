"""Lowest safe versions of the packages a 2026-10-23 scan found vulnerable.

One list, read by two things: tests/test_constraints_security.py, which keeps
constraints.txt from pinning back below any of them, and probe.py, which
reports when an installed venv is below them -- the state every install made
before about 2026-10-19 was found in (#151, #152).

Each floor is the version that fixed what that scan found. Raise a floor
whenever a later scan finds something new; never lower one. Standard library
only: probe.py runs this under whatever Python is at hand.
"""

import re

FLOORS = {
    "pyjwt": "2.15.1",
    "urllib3": "2.8.0",
    "cryptography": "50.0.2",
    "certifi": "2026.10.23",
    "aiohttp": "3.14.4",
    "mcp": "1.30.0",
    "pip": "26.2.2",
    # 2026-11-19 OSV scan (#1986)
    "oauthlib": "4.0.1",
    "pyasn1": "0.6.5",
    "opentelemetry-api": "1.45.2",
    "opentelemetry-sdk": "1.45.2",  # no advisory; lockstep with api
}


def version_key(version):
    """Numeric release tuple: "2026.10.23" -> (2026, 10, 23).

    Enough for these packages, all plain numeric releases. A pre-release
    suffix is ignored rather than parsed, which only ever makes a version
    look older than it is -- the safe direction for a floor.
    """
    return tuple(int(n) for n in
                 re.findall(r"\d+", str(version).split("+")[0])[:4])


def normalise(name):
    return name.strip().lower().replace("_", "-")


def below_floor(versions):
    """{name: (installed, floor)} for every package below its floor.

    `versions` maps package name to installed version; packages absent from
    it (not installed) are not reported -- a floor on a package nothing
    installs constrains nothing.
    """
    found = {normalise(k): v for k, v in versions.items() if v}
    return {name: (found[name], floor) for name, floor in FLOORS.items()
            if name in found and version_key(found[name]) < version_key(floor)}


# The pip every new venv must be upgraded to FIRST, by URL and sha256 (#163).
#
# eMudhra/emSign, 2026-10: eight intermediate CA keys were compromised, and
# pip always trusts its vendored certifi -- so a venv's starting pip (from
# ensurepip; 25.0.1 on Python 3.12.13, measured) cannot safely download
# anything, including a newer pip. With the hash, a tampered wheel is
# rejected even if TLS is intercepted. The URL and hash are the ones the
# Python security thread published (discuss.python.org/t/109576), checked
# against PyPI's own JSON API on 2026-10-25.
PIP_BOOTSTRAP_URL = (
    "https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl")
PIP_BOOTSTRAP_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
PIP_BOOTSTRAP_REQUIREMENT = (
    f"pip @ {PIP_BOOTSTRAP_URL}#sha256={PIP_BOOTSTRAP_SHA256}")

# uv downloads packages itself; below this it trusts the compromised CAs.
UV_FLOOR = "0.13.4"
