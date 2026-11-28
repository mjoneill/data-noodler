"""The upgrade rehearsal's own logic, without installing anything (#2108).

tests/dry_run_upgrade.sh builds an old install and upgrades it for real, with
real downloads, so it runs outside this suite. It failed before it began,
three ways: it found no Python unless one was named, its default old commit
was missing from this repository, and it installed pins written into the
script instead of the old commit's own. And piped through `tail` its failure
could read as a pass.

What can be checked without a download lives in tests/dry_run_lib.sh, and is
checked here: which Python it picks, whether the old commit exists, where the
old pins come from, and that the last line and the exit status always agree.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))

import upgrade  # noqa: E402

TESTS = os.path.join(ROOT, "tests")
SCRIPT = os.path.join(TESTS, "dry_run_upgrade.sh")
LIB = os.path.join(TESTS, "dry_run_lib.sh")
BASH = shutil.which("bash")
PACKAGE_FILE = "data-noodler/installer/constraints.txt"


def setUpModule():
    # The rehearsal builds a POSIX install (launchers, a bin/ venv) and
    # nothing on Windows runs it.
    if sys.platform.startswith("win"):
        raise unittest.SkipTest("the rehearsal is a POSIX shell script")
    if not BASH:
        raise unittest.SkipTest("needs bash")


def _lib(code, *args, env=None):
    """Run shell `code` with the library loaded, the way the script loads it.

    `args` arrive as "$1", "$2"...; `env` is added to a bare environment."""
    full = {"PATH": os.environ.get("PATH", ""), "DRY_RUN_LIB": LIB}
    full.update(env or {})
    return subprocess.run(
        [BASH, "-c", 'set -euo pipefail; . "$DRY_RUN_LIB"; ' + code, "sh",
         *args], env=full, capture_output=True, text=True, timeout=60)


def _fake_python(path, output, status=0):
    """An executable that answers every question with `output`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".out", "w") as f:
        f.write(output)
    with open(path, "w") as f:
        f.write('#!/bin/sh\n/bin/cat "$0.out"\nexit %d\n' % status)
    os.chmod(path, 0o755)
    return path


def _last_line(text):
    lines = text.splitlines()
    return lines[-1] if lines else ""


class TestFindingABasePython(unittest.TestCase):
    """Nothing here looks at this machine: PATH, HOME and the folders
    searched are all the test's own."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "path")
        self.brew = os.path.join(self.tmp, "brew", "bin")
        self.home = os.path.join(self.tmp, "home")
        for d in (self.path, self.brew, self.home):
            os.makedirs(d)

    def _find(self, **extra):
        env = {"PATH": self.path, "HOME": self.home,
               "DRY_RUN_PYTHON_DIRS": self.brew}
        env.update(extra)
        return _lib("find_base_python", env=env)

    def test_homebrews_python_is_found_with_nothing_set(self):
        # The first failure in #2108: python3.12 in Homebrew's folder, not on
        # PATH, no variable naming it.
        brewed = _fake_python(os.path.join(self.brew, "python3.12"), "3.12\n")
        p = self._find()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), brewed)

    def test_a_python_on_the_path_is_found(self):
        on_path = _fake_python(os.path.join(self.path, "python3.12"), "3.12\n")
        p = self._find()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), on_path)

    def test_a_uv_managed_python_is_still_found(self):
        managed = _fake_python(os.path.join(
            self.home, ".local", "share", "uv", "python",
            "cpython-3.12.13-macos-aarch64-none", "bin", "python3.12"),
            "3.12\n")
        p = self._find()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), managed)

    def test_the_measured_3_12_is_preferred_to_a_newer_one(self):
        # constraints.txt was captured on 3.12; a newer Python is used only
        # when there is no 3.12.
        _fake_python(os.path.join(self.path, "python3.14"), "3.14\n")
        _fake_python(os.path.join(self.path, "python3"), "3.14\n")
        measured = _fake_python(os.path.join(self.brew, "python3.12"),
                                "3.12\n")
        self.assertEqual(self._find().stdout.strip(), measured)
        os.remove(measured)
        self.assertEqual(self._find().stdout.strip(),
                         os.path.join(self.path, "python3.14"))

    def test_a_python_older_than_the_installer_accepts_is_passed_over(self):
        # The name promises nothing; what it reports when run decides.
        _fake_python(os.path.join(self.path, "python3.12"), "3.9\n")
        _fake_python(os.path.join(self.path, "python3"), "3.9\n")
        newer = _fake_python(os.path.join(self.brew, "python3.11"), "3.11\n")
        p = self._find()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), newer)

    def test_a_plain_python3_is_used_when_it_is_new_enough(self):
        plain = _fake_python(os.path.join(self.path, "python3"), "3.15\n")
        p = self._find()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), plain)

    def test_nothing_usable_is_a_failure(self):
        _fake_python(os.path.join(self.path, "python3"), "3.9\n")
        p = self._find()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def test_a_named_python_is_used_as_given(self):
        _fake_python(os.path.join(self.brew, "python3.12"), "3.12\n")
        named = _fake_python(os.path.join(self.tmp, "mine", "py"), "3.13\n")
        for variable in ("BASE_PYTHON", "PY312"):
            with self.subTest(variable=variable):
                p = self._find(**{variable: named})
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.strip(), named)

    def test_a_named_python_that_is_too_old_fails_the_search(self):
        # Quietly using a different Python than the one asked for would hide
        # the mistake.
        _fake_python(os.path.join(self.brew, "python3.12"), "3.12\n")
        named = _fake_python(os.path.join(self.tmp, "mine", "py"), "3.9\n")
        p = self._find(BASE_PYTHON=named)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def _preflight_accepts(self, output, status):
        plan = mock.Mock(venv_python="/v/bin/python", base_python="/b/py",
                         constraints=__file__, dist=ROOT, venv_dir="/v",
                         ga_home="/g", platform="darwin")
        with mock.patch.object(upgrade, "run",
                               return_value=(status, output)), \
                mock.patch.object(upgrade.shutil, "which", return_value=None):
            checks, _ = upgrade.preflight(plan, [], running=[])
        (ok,) = [ok for ok, label, _ in checks if label == "base python"]
        return ok

    def test_it_accepts_exactly_what_the_upgrade_pre_flight_accepts(self):
        # The rehearsal hands its Python to upgrade.py as the base Python, so
        # the two must agree on what a usable one is. This holds the shell
        # copy of the rule to the installer's.
        answers = [("3.9\n", 0), ("3.10\n", 0), ("3.12\n", 0), ("3.14\n", 0),
                   ("3.12.1\n", 0), ("4.0\n", 0), ("4\n", 0), ("3\n", 0),
                   ("2.7\n", 0), ("", 0), ("garbage\n", 0), ("3.x\n", 0),
                   ("3..12\n", 0), ("3.12\n", 1), ("a warning\n3.12\n", 0),
                   ("3.12\na warning\n", 0)]
        for n, (output, status) in enumerate(answers):
            with self.subTest(output=output, status=status):
                fake = _fake_python(os.path.join(self.tmp, "p%d" % n, "py"),
                                    output, status)
                p = _lib('usable_base_python "$1"', fake,
                         env={"PATH": self.path})
                self.assertEqual(p.returncode == 0,
                                 bool(self._preflight_accepts(output, status)),
                                 p.stderr)


GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         *args], env=dict(os.environ, **GIT_ENV), check=True,
        capture_output=True, text=True).stdout.strip()


def _commit(repo, files, message):
    for name, text in files.items():
        path = os.path.join(repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class TestTheOldCommit(unittest.TestCase):
    """A repository of the test's own: a first commit from before the package
    folder had its name, then two releases with different pins."""

    @classmethod
    def setUpClass(cls):
        cls.repo = os.path.realpath(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.repo, True)
        _git(cls.repo, "init", "-q")
        cls.before = _commit(cls.repo, {"elsewhere/readme.txt": "x\n"},
                             "before the folder")
        cls.first = _commit(cls.repo, {PACKAGE_FILE: (
            "# Pinned dependency versions for analytics-mcp 0.8.0.\n"
            "#   pip install -c constraints.txt analytics-mcp==9.9.9\n"
            "aiosqlite==0.22.1\nanalytics-mcp==0.8.0\nmcp==2.3.0\n")},
            "first release")
        cls.second = _commit(cls.repo, {PACKAGE_FILE: (
            "aiosqlite==0.22.1\nanalytics-mcp==1.1.0\nmcp==2.3.0\n")},
            "second release")

    def _call(self, code, *args):
        return _lib(code, *args, env=GIT_ENV)

    def _resolve(self, commit):
        return self._call('resolve_commit "$1" "$2"', self.repo, commit)

    def test_a_commit_in_the_repository_resolves_to_its_full_hash(self):
        for given in (self.first, self.first[:7], "HEAD~1"):
            with self.subTest(given=given):
                p = self._resolve(given)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.strip(), self.first)

    def test_a_commit_that_is_not_there_is_a_failure(self):
        # The second failure in #2108: the old default named a commit this
        # repository never had.
        for given in ("be5bc78", "0" * 40, "", "--all", "no such thing"):
            with self.subTest(given=given):
                p = self._resolve(given)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, "")

    def test_something_that_is_not_a_commit_is_a_failure(self):
        blob = _git(self.repo, "rev-parse", "HEAD:" + PACKAGE_FILE)
        p = self._resolve(blob)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def test_a_commit_from_before_the_package_folder_is_told_apart(self):
        has = 'commit_has_package "$1" "$2"'
        self.assertEqual(self._call(has, self.repo, self.first).returncode, 0)
        self.assertNotEqual(
            self._call(has, self.repo, self.before).returncode, 0)

    def test_the_pin_comes_from_the_old_commits_own_constraints(self):
        # The third failure in #2108: analytics-mcp==0.7.0 was written into
        # the script. Each commit says which version it installs.
        read = ('git -C "$1" show "$2:%s" > "$3"; '
                'pinned_requirement "$3" analytics-mcp' % PACKAGE_FILE)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        out = os.path.join(d, "constraints.txt")
        for commit, pin in ((self.first, "analytics-mcp==0.8.0"),
                            (self.second, "analytics-mcp==1.1.0")):
            with self.subTest(pin=pin):
                p = self._call(read, self.repo, commit, out)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.strip(), pin)

    def test_a_pin_line_is_read_whole_and_alone(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "constraints.txt")
        with open(path, "w") as f:
            f.write("# analytics-mcp==9.9.9 in a comment\n"
                    "analytics-mcp-extras==5.0\n"
                    "analytics-mcp==1.2.3  # trailing words\r\n"
                    "mcp==2.3.0")
        for name, pin in (("analytics-mcp", "analytics-mcp==1.2.3"),
                          ("mcp", "mcp==2.3.0")):
            with self.subTest(name=name):
                p = self._call('pinned_requirement "$1" "$2"', path, name)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, pin + "\n")

    def test_a_constraints_file_without_the_pin_is_a_failure(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "constraints.txt")
        with open(path, "w") as f:
            f.write("# analytics-mcp==9.9.9\nmcp==2.3.0\n")
        for target in (path, os.path.join(d, "missing.txt")):
            with self.subTest(target=target):
                p = self._call('pinned_requirement "$1" analytics-mcp', target)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, "")


class TestTheVerdict(unittest.TestCase):
    """The last line of output says PASS or FAIL, and the exit status agrees.

    Read through `tail`, the last line is all anyone sees; the old script
    ended a failure on whatever step heading came before it.
    """

    def _run(self, body):
        return _lib("trap finish EXIT\n" + body)

    def test_a_step_that_fails_ends_the_run_with_fail_and_its_status(self):
        p = self._run('step "1. the old install"\n'
                      '(exit 7)\n'
                      'passed "never reached"\n')
        self.assertEqual(p.returncode, 7)
        last = _last_line(p.stdout)
        self.assertTrue(last.startswith("FAIL: "), p.stdout)
        self.assertIn("1. the old install", last)
        self.assertNotIn("PASS", p.stdout)

    def test_a_named_failure_is_the_last_line(self):
        p = self._run('step "3. checks"\nfail "the old venv was removed"\n')
        self.assertEqual(p.returncode, 1)
        self.assertTrue(_last_line(p.stdout).startswith(
            "FAIL: the old venv was removed"), p.stdout)

    def test_the_first_command_of_a_pipeline_cannot_fail_quietly(self):
        # `git archive <missing> | tar -x` used to be judged on tar alone.
        p = self._run('step "1. the old install"\n'
                      'false | /bin/cat\n'
                      'passed "never reached"\n')
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(_last_line(p.stdout).startswith("FAIL: "), p.stdout)

    def test_ending_early_without_a_pass_is_a_failure(self):
        # Exit status 0 is not a verdict: only reaching the end is.
        p = self._run('step "2. upgrade"\nexit 0\n')
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(_last_line(p.stdout).startswith("FAIL: "), p.stdout)

    def test_a_pass_is_the_last_line_and_exit_status_zero(self):
        p = self._run('step "3. checks"\n'
                      'passed "upgrade rehearsal (a -> b)"\n')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(_last_line(p.stdout),
                         "PASS: upgrade rehearsal (a -> b)")

    def test_a_failure_after_the_pass_is_still_a_failure(self):
        p = self._run('passed "upgrade rehearsal"\nfalse\n')
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(_last_line(p.stdout).startswith("FAIL: "), p.stdout)

    def test_the_throwaway_folder_is_removed_either_way(self):
        for ending in ('passed "done"', 'fail "broke"'):
            with self.subTest(ending=ending):
                d = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, d, True)
                self._run('REHEARSAL_TMP="%s"\n%s\n' % (d, ending))
                self.assertFalse(os.path.exists(d))


class TestTheScript(unittest.TestCase):

    def setUp(self):
        with open(SCRIPT) as f:
            self.text = f.read()
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _fake_base_python(self):
        """Answers the version question as 3.12 and refuses everything else,
        recording it: a rehearsal that got as far as building a venv with
        this would be seen, and would install nothing."""
        path = os.path.join(self.tmp, "python")
        with open(path, "w") as f:
            f.write('#!/bin/sh\n'
                    'case "$*" in *sys.version_info*) echo 3.12; exit 0 ;; '
                    'esac\n'
                    'echo "$*" >> "$0.calls"\nexit 97\n')
        os.chmod(path, 0o755)
        return path

    def _script(self, *args, **env):
        full = {"PATH": os.environ["PATH"], "HOME": self.tmp,
                "TMPDIR": self.tmp}
        full.update(env)
        return subprocess.run([BASH, SCRIPT, *args], env=full,
                              capture_output=True, text=True, timeout=120)

    def test_both_files_parse(self):
        for path in (SCRIPT, LIB):
            with self.subTest(path=os.path.basename(path)):
                p = subprocess.run([BASH, "-n", path], capture_output=True,
                                   text=True)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_failed_step_cannot_be_passed_over(self):
        self.assertRegex(self.text, r"(?m)^set -euo pipefail$")
        self.assertRegex(self.text, r"(?m)^trap finish EXIT$")
        # Nothing waves a failure through.
        self.assertNotIn("|| true", self.text)

    def test_no_old_pin_is_written_into_the_script(self):
        self.assertIsNone(re.search(r"analytics-mcp==\d", self.text))
        self.assertIn('pinned_requirement "$T/old/' + PACKAGE_FILE + '"',
                      self.text)

    def _default_commit(self):
        m = re.search(r"(?m)^OLD_COMMIT=\$\{1:-(\w+)\}$", self.text)
        self.assertIsNotNone(m, "no default old commit in the script")
        return m.group(1)

    def test_the_default_old_commit_is_in_this_repository(self):
        shallow = subprocess.run(
            ["git", "-C", REPO, "rev-parse", "--is-shallow-repository"],
            capture_output=True, text=True)
        if shallow.returncode != 0 or shallow.stdout.strip() != "false":
            self.skipTest("needs this repository's full history "
                          "(CI checks out one commit)")
        commit = self._default_commit()
        p = subprocess.run(
            ["git", "-C", REPO, "rev-parse", "--verify", "--quiet",
             commit + "^{commit}"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0,
                         commit + " is not a commit in this repository")
        # Written in full: a short hash can come to name two objects.
        self.assertEqual(p.stdout.strip(), commit)
        pins = subprocess.run(
            ["git", "-C", REPO, "show", commit + ":" + PACKAGE_FILE],
            capture_output=True, text=True)
        self.assertEqual(pins.returncode, 0, pins.stderr)
        self.assertRegex(pins.stdout, r"(?m)^analytics-mcp==\d")

    def test_an_unknown_commit_fails_before_anything_is_built(self):
        python = self._fake_base_python()
        p = self._script("0123456789abcdef", BASE_PYTHON=python, PY312=python)
        self.assertNotEqual(p.returncode, 0)
        last = _last_line(p.stdout)
        self.assertTrue(last.startswith("FAIL: "), p.stdout + p.stderr)
        self.assertIn("0123456789abcdef", last)
        self.assertFalse(os.path.exists(python + ".calls"),
                         "the rehearsal went on to use the Python")
        self.assertEqual(os.listdir(self.tmp), ["python"])

    def test_no_usable_python_fails_and_says_how_to_name_one(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        p = self._script(PATH=empty, DRY_RUN_PYTHON_DIRS=empty)
        self.assertNotEqual(p.returncode, 0)
        last = _last_line(p.stdout)
        self.assertTrue(last.startswith("FAIL: "), p.stdout + p.stderr)
        self.assertIn("BASE_PYTHON", last)

    def test_the_header_says_how_to_run_it_without_losing_the_status(self):
        header = self.text.split("\nset -euo pipefail\n")[0]
        self.assertIn("PASS", header)
        self.assertIn("FAIL", header)
        self.assertIn("exit status", header)
        self.assertIn("tail", header)


if __name__ == "__main__":
    unittest.main()
