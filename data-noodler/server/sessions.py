"""Where files may be written, and the one place directories are created.

Two rules carry most of the safety. Directories are created in exactly one
function, one level deep under a root that must already exist -- so a typo
cannot build a tree. And no component of a destination may be a symlink: on
2026-09-02 an agent redirected output through a scratch symlink and truncated
Homebrew's python3.14, breaking every MCP server on the machine.
"""

import datetime
import os
import re

DEFAULT_SESSIONS_ROOT = "~/Documents/analyst-sessions"

# Home-relative prefixes. These expand correctly on every platform: on
# Windows "~/.claude" becomes C:\Users\<user>\.claude, which is where Claude
# Code really keeps its state. The two Library paths are macOS-only and simply
# never match elsewhere, which costs nothing.
_HOME_RELATIVE_DENYLIST = (
    "~/.ssh",
    "~/.config/gcloud",
    "~/.claude",
    "~/.codex",
    "~/.config/data-noodler",
    # #1999: an install from before the rename keeps its home, and the
    # sign-in it names, here until migrate_home.py moves it.
    "~/.config/ga-" "mcp",
    "~/Library/Application Support/Claude",
    "~/Library/Application Support/Claude-3p",
)


def build_denylist(env=None, pathmod=None, home=None):
    """Directories no export may ever be written into, for this machine.

    The home-relative entries alone leave Windows underprotected: Claude
    Desktop's data lives under %APPDATA%, which is not derivable from "~" and
    so was not covered at all. An export aimed there would have been permitted
    -- the same class of mistake that gave this module its reason to exist,
    just on the platform nobody had run it on.

    Takes env, pathmod and home so both platforms' lists are assertable from
    either machine.

    Every entry is normpath'd. On Windows os.path.expanduser("~/.ssh") gives
    C:\\Users\\x/.ssh -- only the tilde is replaced -- while realpath() of a
    destination is all backslashes, so the home-relative entries never
    matched anything there: exports could be written into ~/.ssh, ~/.claude
    and the credential's folder (#158, found by the 2026-10-25 audit).
    """
    env = os.environ if env is None else env
    pathmod = os.path if pathmod is None else pathmod
    home = os.path.expanduser("~") if home is None else home
    out = [pathmod.normpath(pathmod.join(home, *p[2:].split("/")))
           for p in _HOME_RELATIVE_DENYLIST]
    for var in ("APPDATA", "LOCALAPPDATA"):
        base = env.get(var)
        if not base:
            continue
        for name in ("Claude", "Claude-3p", "data-noodler", "ga-" "mcp"):
            out.append(pathmod.normpath(pathmod.join(base, name)))
    return tuple(out)


def denylist_match(real, denylist, pathmod=None):
    """The entry of `denylist` that the resolved path `real` falls under.

    Pure: no filesystem access, so the Windows comparison can be tested from
    a Mac by passing ntpath. Case-folded on purpose -- see _denylisted.
    """
    pathmod = os.path if pathmod is None else pathmod
    real = pathmod.normpath(real).casefold()
    for bad in denylist:
        folded = pathmod.normpath(bad).casefold()
        if real == folded or real.startswith(folded.rstrip(pathmod.sep)
                                             + pathmod.sep):
            return bad
    return None


# Expanded at import; every destination is checked against these prefixes.
DENYLIST = build_denylist()

# macOS ships these as symlinks (/var -> /private/var, /tmp -> /private/tmp).
# They are part of the OS rather than anything a caller controls, and
# refusing them would reject every temp directory on the system -- which is
# exactly what the realpath-vs-abspath check this replaced got wrong.
SYSTEM_SYMLINKS = frozenset(("/var", "/tmp", "/etc"))


class SessionError(Exception):
    """Raised with a message intended to be read by a user, not a developer."""


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    return s.strip("-")


def _symlinked_ancestor(directory):
    """The first symlinked component at or above `directory`, else None."""
    d = os.path.abspath(directory)
    while True:
        if d in SYSTEM_SYMLINKS:
            return None
        if os.path.islink(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _denylisted(directory):
    """The DENYLIST prefix `directory` falls under, else None.

    Compared case-folded: APFS is case-insensitive but case-preserving, so
    realpath() does not normalise case for a non-symlink component, and a
    case-variant like ~/.Claude resolves to the very same directory as
    ~/.claude. Folding here deliberately fails closed -- on a genuinely
    case-sensitive filesystem a distinct ~/.Claude would also be refused,
    which is the safe direction for a denylist to err in.
    """
    return denylist_match(os.path.realpath(directory), DENYLIST)


def start_session(name, root=None, now=None):
    """Create (or reuse) one dated session folder and return its path."""
    now = now or datetime.datetime.now()
    root = os.path.expanduser(root or DEFAULT_SESSIONS_ROOT)

    # The same denylist check check_writable applies to every export. Without
    # it start_session happily creates a folder inside a protected location
    # and reports it as ready, and then every single export into that folder
    # is refused -- an agent announcing success on a directory nothing can be
    # written to. Refuse at the point the user can still choose elsewhere.
    #
    # Checked before the existence test on purpose: a protected root deserves
    # the protected answer whether or not it happens to exist on this machine,
    # and "create it first" would be actively bad advice for ~/.ssh.
    bad = _denylisted(root)
    if bad is not None:
        raise SessionError(
            f"The sessions root {root} is inside a protected location "
            f"({bad}). Nothing can be exported there, so a session folder "
            "would be useless. Choose another root.")

    if not os.path.isdir(root):
        raise SessionError(
            f"The sessions root {root} does not exist. Create it first, or "
            "pass a root that does -- this tool creates the session folder "
            "inside a root, never the root itself.")

    found = _symlinked_ancestor(root)
    if found is not None:
        raise SessionError(
            f"The sessions root {root} passes through a symlink ({found}). "
            "Refusing to create session folders through it -- it can point "
            "anywhere, including at a system directory.")

    slug = _slug(name)
    if not slug:
        raise SessionError(
            f"{name!r} has no usable characters for a folder name. Give the "
            "session a short name like 'law-pillar-review'.")

    path = os.path.join(root, f"{now:%Y-%m-%d}-{slug}")
    os.makedirs(path, exist_ok=True)
    return path


def check_writable(path, overwrite=False):
    """Raise SessionError unless `path` is a safe destination to write."""
    if not os.path.isabs(path):
        raise SessionError(
            f"{path} is not an absolute path. Destinations must be absolute: "
            "this server runs as a child of whichever application launched "
            "it, so its working directory is unpredictable.")

    if not path.endswith(".csv"):
        raise SessionError(f"{path} does not end in .csv.")

    bad = _denylisted(os.path.dirname(path))
    if bad is not None:
        raise SessionError(
            f"{path} is inside a protected location ({bad}). Choose a "
            "session folder or another directory.")

    if os.path.islink(path):
        raise SessionError(
            f"{path} is a symlink. Refusing to write through it -- a symlinked "
            "destination can point anywhere, including at a system file.")

    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise SessionError(
            f"The directory {parent} does not exist. Create it, or call "
            "start_session to make a session folder.")

    # No component of the parent chain may be a symlink -- not just the
    # immediate parent. Checked with islink (walking up from `parent`)
    # rather than by comparing realpath to abspath: on macOS every
    # tempfile.mkdtemp() sits under /var, which is itself a symlink to
    # /private/var, so that comparison fires on ordinary directories and
    # would reject almost every legitimate destination. SYSTEM_SYMLINKS
    # carves out exactly that OS-owned exception.
    found = _symlinked_ancestor(parent)
    if found is not None:
        raise SessionError(
            f"The path to {path} passes through a symlink ({found}). "
            "Refusing to write through it -- it can point anywhere, "
            "including at a system directory.")

    if os.path.exists(path) and not overwrite:
        raise SessionError(
            f"{path} already exists. Pass overwrite=true to replace it, or "
            "choose another name.")


# ---------------------------------------------------------------------------
# Approved places (#156, 2026-10-25)
#
# Every export goes to one of a few places the USER approved, never to a path
# the model makes up. Tool arguments come from a model that GA and Search
# Console text can steer (page titles, queries, URL lists reach it
# unfiltered), and before this an absolute out_file went anywhere the user
# could write: over their own CSVs, into any git tree, or -- on Windows -- to
# \\host\share, where merely resolving the path leaks the user's NTLM hash.
#
# The places:
#   project   <project>/_outputs, where the project is what the APP says it
#             is -- the client's declared roots, else the folder the app
#             started the server in. Never a tool argument.
#   sessions  sessions_root from config.json.
#   <name>    extra folders the user listed in config.json "export_roots".
# The model picks among them with save_to, and may name a file -- or a
# subfolder -- inside the chosen place. That is all.
# ---------------------------------------------------------------------------

OUTPUTS_DIR = "_outputs"

# Folders that are never a project even when an app starts the server there.
_NOT_PROJECT_POSIX = ("/", "/System", "/Library", "/usr", "/bin", "/sbin",
                      "/etc", "/var", "/private", "/opt", "/Applications",
                      "/tmp", "/dev", "/cores")
_NOT_PROJECT_HOME = ("Library", ".config", ".codex", ".claude", ".ssh",
                     ".local", "AppData")


def unsafe_path_reason(text):
    r"""Why a path string must be refused before any filesystem call, or None.

    UNC and device paths are refused on text alone: on Windows, realpath(),
    isdir() or islink() on \\host\share opens an SMB connection, which
    hands the user's NTLMv2 hash to whoever runs that host -- the check
    itself would be the leak. Drive-relative paths (C:foo) depend on hidden
    per-drive state, so they are refused too.
    """
    if not text:
        return None
    t = str(text)
    if t.startswith(("\\\\", "//", "\\/", "/\\")):
        return ("is a network or device path (\\\\host\\share, \\\\?\\, "
                "\\\\.\\). Exports never go to network shares named in a "
                "request; list a shared folder under export_roots in "
                "config.json if one is really wanted.")
    if len(t) >= 2 and t[1] == ":" and t[0].isalpha() and (
            len(t) == 2 or t[2] not in "\\/"):
        return "is a drive-relative Windows path (like C:file.csv)."
    if "\x00" in t:
        return "contains a NUL character."
    return None


def project_reason(path, home=None):
    """Why `path` cannot be a project folder, or None if it can be one."""
    if not path:
        return "no folder"
    if unsafe_path_reason(path):
        return "a network or device path"
    home = os.path.realpath(home or os.path.expanduser("~"))
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        return "not a directory"
    if real == home or os.path.commonpath([real, home]) == real:
        return "the home folder itself, or above it"
    if os.name != "nt":
        for bad in _NOT_PROJECT_POSIX:
            if real == bad or (bad not in ("/",) and
                               real.startswith(bad.rstrip("/") + "/")
                               and not real.startswith(home + os.sep)):
                return f"a system folder ({bad})"
    else:
        drive, rest = os.path.splitdrive(real)
        if rest in ("", "\\"):
            return "a drive root"
        low = real.casefold()
        for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)",
                    "ProgramData"):
            base = os.environ.get(var)
            if base and (low == base.casefold() or
                         low.startswith(base.casefold().rstrip("\\") + "\\")):
                return f"a system folder ({base})"
    if real.startswith(home + os.sep):
        first = real[len(home) + 1:].split(os.sep, 1)[0]
        if first in _NOT_PROJECT_HOME:
            return f"an application or settings folder (~/{first})"
    if _denylisted(real) is not None:
        return "a protected location"
    if not os.access(real, os.W_OK):
        return "not writable"
    return None


def find_project(roots, launch_dir, home=None):
    """(project, chosen_by) from what the app said, or (None, why_not).

    `roots` are the client's declared MCP roots (local paths), in the
    client's order; `launch_dir` is the folder the app started the server in.
    Both are set by the app, never by the model -- that is the whole reason
    they can be trusted to name a place to write.
    """
    reasons = []
    for root in roots or ():
        why = project_reason(root, home)
        if why is None:
            return os.path.realpath(root), "the app's declared project roots"
        reasons.append(f"{root}: {why}")
    if launch_dir:
        why = project_reason(launch_dir, home)
        if why is None:
            return (os.path.realpath(launch_dir),
                    "the folder the app started this server in")
        reasons.append(f"{launch_dir}: {why}")
    return None, ("; ".join(reasons) or "the app named no project folder")


def build_places(sessions_root=None, project=None, extra=None):
    """Ordered {name: root} of approved places. The first is the default."""
    places = {}
    if project:
        places["project"] = os.path.join(project, OUTPUTS_DIR)
    places["sessions"] = os.path.abspath(os.path.expanduser(
        sessions_root or DEFAULT_SESSIONS_ROOT))
    for name, root in (extra or {}).items():
        if (isinstance(name, str) and isinstance(root, str) and name
                and name not in places and not unsafe_path_reason(root)):
            places[name] = os.path.abspath(os.path.expanduser(root))
    return places


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives on Windows
        return False


def _place_containing(path, places):
    for name, root in places.items():
        if _inside(path, root):
            return name, root
    return None, None


def resolve(out_file, session_dir, suggested_name, places, save_to=""):
    """Decide where to write: (absolute path, {place, root}).

    Only inside an approved place. save_to picks the place (default: the
    first, which is the project when the app named one). session_dir must
    already be inside an approved place -- it is what start_session returned.
    out_file is resolved inside session_dir when given, else inside the
    place; an absolute out_file is accepted only if it is already inside an
    approved place.

    Creates no directories: start_session remains the only thing that does.
    """
    for label, value in (("out_file", out_file), ("session_dir", session_dir)):
        why = unsafe_path_reason(value)
        if why:
            raise SessionError(f"{label} {value!r} {why}")

    names = ", ".join(places)
    if save_to:
        if save_to not in places:
            raise SessionError(
                f"save_to={save_to!r} is not one of the approved places "
                f"({names}). " + ("" if "project" in places else
                "There is no project folder here -- the app did not start "
                "this server in one (Claude Desktop chat never does)."))
        place = save_to
    else:
        place = next(iter(places))
    base = places[place]

    if session_dir:
        sd = os.path.abspath(os.path.expanduser(session_dir))
        name, root = _place_containing(sd, places)
        if name is None:
            raise SessionError(
                f"session_dir {session_dir!r} is not inside an approved place "
                f"({names}). Use the folder start_session returned.")
        if save_to and name != save_to:
            raise SessionError(
                f"session_dir {session_dir!r} is in {name!r}, not "
                f"save_to={save_to!r}. Pass one or the other.")
        place, base = name, sd

    if out_file:
        expanded = os.path.expanduser(out_file)
        if os.path.isabs(expanded):
            name, root = _place_containing(expanded, places)
            if name is None:
                raise SessionError(
                    f"out_file {out_file!r} is outside every approved place "
                    f"({names}). Pass a file NAME (or a relative path) and "
                    "choose the place with save_to; files only go where the "
                    "user has approved.")
            return os.path.abspath(expanded), {"place": name, "root": root}
        candidate = os.path.abspath(os.path.join(base, expanded))
        if candidate == os.path.abspath(base) or not _inside(candidate, base):
            raise SessionError(
                f"out_file {out_file!r} resolves outside {base}. Relative "
                "paths stay inside the chosen place.")
        return candidate, {"place": place, "root": places[place]}

    if not session_dir:
        raise SessionError(
            "No destination. Call start_session first and pass its path as "
            "session_dir, or pass out_file -- a file name, which lands in "
            f"the chosen place ({base}).")
    stem, ext = os.path.splitext(suggested_name)
    candidate = os.path.join(base, suggested_name)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(base, f"{stem}-{n}{ext}")
        n += 1
    return candidate, {"place": place, "root": places[place]}


def resolve_destination(out_file, session_dir, suggested_name,
                        sessions_root=None, places=None, save_to=""):
    """resolve() returning only the path; places default to the sessions root.

    Kept for callers that only know a sessions root.
    """
    if places is None:
        places = build_places(sessions_root=sessions_root)
    return resolve(out_file, session_dir, suggested_name, places,
                   save_to)[0]
