"""Where this package lives on a machine (#1999 slice 2).

The home is ~/.config/data-noodler. Installs made before the product had one
name live in ~/.config/ga-mcp until migrate_home.py moves them, and keep
working there: every reader takes the new home when it exists, else an old
home that holds a config, else the new one.

The server (server/config.py), the skill's scripts (ga_config.py), the
launchers and tools/personal_guard.py repeat this rule because none of them
can import the installer; tests hold them to the same answers.
"""

import os

HOME_NAME = "data-noodler"
LEGACY_HOME_NAME = "ga-" "mcp"


def new_home(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".config", HOME_NAME)


def legacy_home(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".config",
                        LEGACY_HOME_NAME)


def default_home(home=None):
    new, old = new_home(home), legacy_home(home)
    if os.path.isdir(new):
        return new
    if os.path.isfile(os.path.join(old, "config.json")):
        return old
    return new
