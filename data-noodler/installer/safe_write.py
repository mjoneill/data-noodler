"""Replace a file's contents without loosening its permissions or following
a planted symlink.

register.py and bootstrap_config.py used to write `<path>.ga-tmp` with a
plain open(tmp, "w") and os.replace() it over the original. The temp file
got the umask's 0644, so a 0600 ~/.claude.json -- which can hold API keys
and other MCP servers' secrets -- came out readable by every account on the
machine (reproduced 2026-10-25, #157). A plain open() also follows a symlink
planted at the temp name, and replacing a symlinked config (dotfile
managers do this) swapped the link for a plain file.

Standard library only: bootstrap_config runs under whatever Python is at
hand.
"""

import datetime
import os
import shutil
import stat
import tempfile

# The temp file gets an unpredictable name from mkstemp, in the target's own
# folder. It used to be the fixed `<target>.ga-tmp`, opened with O_EXCL (and
# O_NOFOLLOW where it exists), and on Windows a DANGLING link planted at that
# name was followed: the write created the link's target (#2011). With no
# fixed name there is nothing to plant a link at ahead of time.
TEMP_SUFFIX = ".ga-tmp"

DEFAULT_MODE = 0o600


class SafeWriteError(Exception):
    """Raised with a message intended to be read by a user."""


def resolve_target(path):
    """The file to actually write: a symlinked config's target, not the link.

    Writing through the link keeps the user's dotfile arrangement intact;
    replacing the link would silently fork their config.
    """
    return os.path.realpath(path) if os.path.islink(path) else path


def write_atomically(path, text, default_mode=DEFAULT_MODE, private=False):
    """Write `text` to `path` via a private temp file and an atomic replace.

    The new file keeps the original's permission bits; a file that did not
    exist gets `default_mode` (0600). Returns the path actually written.

    private=True also removes group and other access from an existing file.
    That repairs the damage earlier versions did: their plain open() left
    ~/.claude.json 0644 after every registration, so on machines already
    installed the "original" mode is the loosened one (found by the upgrade
    rehearsal, 2026-10-25).
    """
    target = resolve_target(path)
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        mode = default_mode
    if private:
        mode = (mode & 0o700) | 0o600
    folder, name = os.path.split(target)
    try:
        # Binary mode on Windows, created 0600, exclusive by construction.
        fd, tmp = tempfile.mkstemp(dir=folder, prefix="." + name + ".",
                                   suffix=TEMP_SUFFIX)
    except OSError as exc:
        raise SafeWriteError(f"Could not write {target}: could not create "
                             f"a temporary file beside it ({exc}). The "
                             "original is untouched.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # The mode passed to os.open is filtered by the umask; set it
        # explicitly so 0600 stays 0600 whatever the umask is.
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError as exc:
        # tmp is ours: mkstemp created it, so removing it is always safe.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise SafeWriteError(f"Could not write {target} ({exc}). The "
                             "original is untouched.")
    return target


def backup_copy(path):
    """Copy `path` to a new `<path>.ga-backup-<stamp>` and return its name.

    Never overwrites an earlier backup: stamps are to the second, and a
    second write in the same second used to replace the first backup -- the
    only copy of the original -- with the second (#2009). A taken name gets
    a -2, -3, ... suffix.

    The bytes go to a mkstemp temp file first, then os.link gives it the
    backup name. os.link refuses a name that exists -- a file, or a planted
    link, which is never followed -- in one atomic step, so there is no
    window between "is this name free?" and "take it". Where the filesystem
    cannot hard-link (FAT, some network shares), it falls back to a
    free-name check and os.replace, which is atomic but not race-free. The
    backup keeps the original's mode and times, as shutil.copy2 did. Raises
    OSError; callers word the refusal.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{path}.ga-backup-{stamp}"
    folder, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=folder or os.curdir,
                               prefix="." + name + ".", suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
            shutil.copyfileobj(src, out)
        shutil.copystat(path, tmp)
        n = 1
        while True:
            dest = base if n == 1 else f"{base}-{n}"
            try:
                os.link(tmp, dest)
            except FileExistsError:
                n += 1
                continue
            except OSError:
                # No hard links here: take the first free name instead.
                while os.path.lexists(dest):
                    n += 1
                    dest = f"{base}-{n}"
                os.replace(tmp, dest)
                return dest
            os.unlink(tmp)
            return dest
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
