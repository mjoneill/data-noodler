"""The one-visit upgrade: finish verified, or leave the machine as it was (#164).

A fake home holds a previous install: config.json, an old venv, a previous
payload, and a Claude Code config. upgrade.py runs for real -- real
install.py, real verify.py handshakes against the servers -- with only the
network-bound commands (venv creation, pip installs) replaced: the "new venv"
is a thin wrapper around this test's own interpreter, which has the pinned
packages.
"""

import json
import os
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

try:
    import mcp.server.mcpserver  # noqa: F401
    import analytics_mcp  # noqa: F401
    RUNNABLE = True
except ImportError:
    RUNNABLE = False

POSIX = not sys.platform.startswith("win")


def _write_wrapper(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


def _make_venv(venv_dir, marker):
    """A venv this test can run: python and analytics-mcp wrap sys.executable."""
    os.makedirs(os.path.join(venv_dir, "bin"))
    with open(os.path.join(venv_dir, "pyvenv.cfg"), "w") as f:
        f.write(f"home = {os.path.dirname(sys.executable)}\n")
    _write_wrapper(os.path.join(venv_dir, "bin", "python"),
                   f'exec "{sys.executable}" "$@"')
    _write_wrapper(os.path.join(venv_dir, "bin", "analytics-mcp"),
                   f'exec "{sys.executable}" -m analytics_mcp.server "$@"')
    with open(os.path.join(venv_dir, "MARKER"), "w") as f:
        f.write(marker)


@unittest.skipUnless(RUNNABLE and POSIX, "needs mcp 2.x, analytics_mcp, POSIX")
class TestUpgrade(unittest.TestCase):

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.ga_home = os.path.join(self.home, ".config", "data-noodler")
        self.venv = os.path.join(self.ga_home, "venv")
        _make_venv(self.venv, "old")
        adc = os.path.join(self.home, ".config", "gcloud", "adc.json")
        os.makedirs(os.path.dirname(adc))
        with open(adc, "w") as f:
            f.write("{}")
        self.config = os.path.join(self.ga_home, "config.json")
        with open(self.config, "w") as f:
            json.dump({
                "oauth_client_file": os.path.join(self.home, "client.json"),
                "adc_file": adc,
                "venv_python": os.path.join(self.venv, "bin", "python"),
                "analytics_mcp_bin": os.path.join(self.venv, "bin",
                                                  "analytics-mcp"),
                "properties_csv": os.path.join(self.ga_home, "p.csv"),
                "sessions_root": os.path.join(self.home, "sessions"),
            }, f)
        os.makedirs(os.path.join(self.home, "sessions"))
        os.makedirs(os.path.join(self.home, ".claude"))
        self.claude_json = os.path.join(self.home, ".claude.json")
        with open(self.claude_json, "w") as f:
            json.dump({"mcpServers": {"someone-else": {"command": "x"}}}, f)
        os.chmod(self.claude_json, 0o600)
        self.env = dict(os.environ, HOME=self.home)
        self.env.pop("DATA_NOODLER_HOME", None)
        self.env.pop("DATA_NOODLER_CONFIG", None)
        self.log = []
        self.fail_on = None

    # The fake runner: real subprocesses, except venv creation and pip.
    def _run(self, cmd, env=None):
        joined = " ".join(cmd)
        if self.fail_on and self.fail_on in joined:
            return 1, f"simulated failure at {self.fail_on}"
        if cmd[1:3] == ["-m", "venv"]:
            _make_venv(cmd[3], "new")
            return 0, ""
        if cmd[1:4] == ["-m", "pip", "install"]:
            return 0, ""
        p = subprocess.run(cmd, capture_output=True, text=True, env=self.env,
                           timeout=180)
        return p.returncode, p.stdout + p.stderr

    def _upgrade(self, configs=None, running=()):
        plan = upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                                 config_path=self.config,
                                 targets="claude_code")
        configs = [self.claude_json] if configs is None else configs
        with mock.patch.object(upgrade, "run", self._run):
            ok = upgrade.upgrade(plan, configs, log=self.log.append,
                                 running=list(running))
        return plan, ok

    def _marker(self, venv):
        with open(os.path.join(venv, "MARKER")) as f:
            return f.read()

    def test_a_good_upgrade_finishes_verified(self):
        plan, ok = self._upgrade()
        self.assertTrue(ok, "\n".join(self.log))
        self.assertEqual(self._marker(self.venv), "new")
        with open(self.claude_json) as f:
            servers = json.load(f)["mcpServers"]
        self.assertIn("data-noodler", servers)
        self.assertIn("someone-else", servers, "an unrelated server was lost")
        self.assertTrue(os.path.isdir(os.path.join(self.ga_home, "server")))
        self.assertEqual(os.stat(self.claude_json).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.config).st_mode & 0o777, 0o600)

    def test_it_never_deletes_the_old_venv(self):
        # Removing anything that existed before the run is the user's call,
        # offered by the agent in Step 9 -- never the script's.
        plan, ok = self._upgrade()
        self.assertTrue(ok, "\n".join(self.log))
        self.assertTrue(os.path.isdir(plan.old_venv))
        self.assertTrue(any(plan.old_venv in line for line in self.log))

    def test_it_leaves_the_claude_code_skills_alone(self):
        # Skills are the agent's step (copy_skills.py), which protects a
        # master copy; the script must not overwrite them.
        skills = os.path.join(self.home, ".claude", "skills")
        mine = os.path.join(skills, "data-noodler")
        os.makedirs(mine)
        with open(os.path.join(mine, "SKILL.md"), "w") as f:
            f.write("my unbuilt edits")
        plan, ok = self._upgrade()
        self.assertTrue(ok, "\n".join(self.log))
        with open(os.path.join(mine, "SKILL.md")) as f:
            self.assertEqual(f.read(), "my unbuilt edits")

    def test_a_machine_with_no_claude_config_is_still_verified(self):
        # ChatGPT/Codex-only: nothing Claude to verify, but the shared
        # servers -- what Codex runs -- must still be proven.
        os.remove(self.claude_json)
        plan, ok = self._upgrade(configs=[])
        self.assertTrue(ok, "\n".join(self.log))
        self.assertTrue(any("as the apps start them" in line
                            for line in self.log))

    def test_a_running_app_stops_it_before_anything_changes(self):
        plan, ok = self._upgrade(running=["python .../data-noodler/server/x"])
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertFalse(os.path.exists(plan.old_venv))
        self.assertTrue(any("NOT READY" in line for line in self.log))

    def test_a_failed_shared_verify_restores_everything(self):
        self.fail_on = "entries.json"
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertFalse(os.path.exists(plan.old_venv))

    def test_a_failed_package_install_puts_the_old_venv_back(self):
        self.fail_on = "google-auth-oauthlib"
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertFalse(os.path.exists(plan.old_venv))
        self.assertFalse(os.path.exists(os.path.join(self.ga_home,
                                                     "server")))

    def test_a_failed_verify_restores_venv_and_previous_payload(self):
        # A previous payload, made by a real install, with a sentinel in it.
        p = subprocess.run([sys.executable,
                            os.path.join(ROOT, "installer", "install.py"),
                            "--repo-root", REPO, "--ga-home", self.ga_home,
                            "--payload-only"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        sentinel = os.path.join(self.ga_home, "server", "PREVIOUS")
        with open(sentinel, "w") as f:
            f.write("previous payload")
        self.fail_on = "claude.json"
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertTrue(os.path.exists(sentinel), "previous payload not back")

    def test_a_venv_still_in_use_changes_nothing(self):
        def busy(src, dst):
            raise PermissionError("[WinError 32] in use")
        with mock.patch.object(upgrade.os, "rename", busy):
            plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertTrue(any("quit" in line for line in self.log))
        self.assertFalse(any("Putting everything back" in line
                             for line in self.log))

    # -- code review 2026-10-25: every failure after the move must undo ----

    def _raise_on(self, needle, exc):
        real = self._run

        def run(cmd, env=None):
            if needle in " ".join(cmd):
                raise exc
            return real(cmd, env)
        return run

    def _upgrade_with(self, runner):
        plan = upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                                 config_path=self.config,
                                 targets="claude_code")
        with mock.patch.object(upgrade, "run", runner):
            ok = upgrade.upgrade(plan, [self.claude_json],
                                 log=self.log.append, running=[])
        return plan, ok

    def test_ctrl_c_during_the_install_puts_everything_back(self):
        plan, ok = self._upgrade_with(self._raise_on(
            "google-auth-oauthlib", KeyboardInterrupt()))
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertFalse(os.path.exists(plan.old_venv))
        self.assertTrue(any("INTERRUPTED" in line for line in self.log))

    def test_a_missing_interpreter_puts_everything_back(self):
        # run() raises FileNotFoundError, not UpgradeError.
        plan, ok = self._upgrade_with(self._raise_on(
            "sha256", FileNotFoundError(2, "x")))
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertTrue(any("FileNotFoundError" in line for line in self.log))

    def test_a_locked_file_does_not_break_the_rollback(self):
        # On Windows rmtree can silently leave a locked file behind; the
        # rename back used to crash inside the error handler.
        self.fail_on = "google-auth-oauthlib"
        with mock.patch.object(upgrade.shutil, "rmtree",
                               lambda *a, **k: None):
            plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertTrue(any(".failed-" in line for line in self.log))
        self.assertFalse(any("MOST of it" in line for line in self.log))

    def test_the_claude_configs_are_put_back_too(self):
        with open(self.claude_json) as f:
            before = json.load(f)
        self.fail_on = "claude.json"  # fails at verify, after registration
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        # Same content; only our entries were touched, so formatting may
        # differ from the original bytes.
        with open(self.claude_json) as f:
            self.assertEqual(json.load(f), before)
        self.assertEqual(os.stat(self.claude_json).st_mode & 0o777, 0o600)

    def test_only_this_runs_payload_backup_is_restored(self):
        p = subprocess.run([sys.executable,
                            os.path.join(ROOT, "installer", "install.py"),
                            "--repo-root", REPO, "--ga-home", self.ga_home,
                            "--payload-only"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        ancient = os.path.join(self.ga_home, "companion.ga-old-20200101-000000")
        os.makedirs(ancient)
        open(os.path.join(ancient, "ANCIENT"), "w").close()
        open(os.path.join(self.ga_home, "server", "PREVIOUS"), "w").close()
        self.fail_on = "claude.json"
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertTrue(os.path.exists(os.path.join(self.ga_home, "server",
                                                    "PREVIOUS")))
        self.assertTrue(os.path.exists(os.path.join(ancient, "ANCIENT")),
                        "an older backup was used or touched")

    def test_the_kept_venv_lives_under_ga_home_not_the_tool_manager(self):
        # A pipx-style venv outside ga_home.
        venvs = os.path.join(self.home, "pipx", "venvs")
        os.makedirs(venvs)
        shutil.move(self.venv, os.path.join(venvs, "analytics-mcp"))
        self.venv = os.path.join(venvs, "analytics-mcp")
        with open(self.config) as f:
            cfg = json.load(f)
        cfg["venv_python"] = os.path.join(self.venv, "bin", "python")
        cfg["analytics_mcp_bin"] = os.path.join(self.venv, "bin",
                                                "analytics-mcp")
        with open(self.config, "w") as f:
            json.dump(cfg, f)
        plan, ok = self._upgrade()
        self.assertTrue(ok, "\n".join(self.log))
        self.assertEqual(os.path.dirname(plan.old_venv), self.ga_home)
        self.assertEqual(os.listdir(venvs), ["analytics-mcp"])

    # -- code review round 2 ----------------------------------------------

    def test_only_our_entries_are_put_back_not_the_whole_file(self):
        # Something (a Claude Code window left open) writes to the config
        # during the run; the undo must not throw that away.
        real = self._run

        def run(cmd, env=None):
            if "verify.py" in " ".join(cmd) and "claude.json" in " ".join(cmd):
                with open(self.claude_json) as f:
                    data = json.load(f)
                data["projects"] = {"/x": {"saved": "by the app"}}
                with open(self.claude_json, "w") as f:
                    json.dump(data, f)
                return 1, "simulated verify failure"
            return real(cmd, env)
        plan, ok = self._upgrade_with(run)
        self.assertFalse(ok)
        with open(self.claude_json) as f:
            data = json.load(f)
        self.assertEqual(data["projects"], {"/x": {"saved": "by the app"}})
        self.assertNotIn("data-noodler", data["mcpServers"])
        self.assertIn("someone-else", data["mcpServers"])

    def test_the_undo_never_loosens_a_config_back_to_0644(self):
        os.chmod(self.claude_json, 0o644)
        self.fail_on = "claude.json"
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(os.stat(self.claude_json).st_mode & 0o777, 0o600)

    def test_sigterm_is_undone_like_ctrl_c(self):
        plan, ok = self._upgrade_with(self._raise_on(
            "google-auth-oauthlib", upgrade.UpgradeTerminated(15)))
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertTrue(any("INTERRUPTED" in line for line in self.log))

    def test_the_undo_ignores_a_second_ctrl_c(self):
        seen = []
        real_signal = upgrade.signal.signal

        def record(sig, handler):
            seen.append((sig, handler))
            return real_signal(sig, handler)
        self.fail_on = "google-auth-oauthlib"
        with mock.patch.object(upgrade.signal, "signal", record):
            self._upgrade()
        self.assertIn((upgrade.signal.SIGINT, upgrade.signal.SIG_IGN), seen)

    def test_payload_folders_the_run_created_are_removed(self):
        self.fail_on = "claude.json"   # after install.py made the payload
        plan, ok = self._upgrade()
        self.assertFalse(ok)
        for name in upgrade.PAYLOAD:
            self.assertFalse(os.path.exists(os.path.join(self.ga_home, name)),
                             name)

    def test_a_config_the_run_created_is_removed(self):
        os.remove(self.claude_json)
        self.fail_on = "entries.json"   # shared verify, after registration
        plan = upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                                 config_path=self.config,
                                 targets="claude_code")
        with mock.patch.object(upgrade, "run", self._run):
            ok = upgrade.upgrade(plan, [], log=self.log.append, running=[],
                                 candidate_configs=[self.claude_json])
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.claude_json))

    def test_a_killed_run_is_finished_by_recover(self):
        # Simulate dying before the in-process undo could run.
        self.fail_on = "google-auth-oauthlib"
        with mock.patch.object(upgrade, "restore",
                               lambda state, log: ([], [])), \
                mock.patch.object(upgrade, "_report_restore",
                                  lambda *a: None):
            plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "new")  # left broken
        # A new upgrade refuses until it is recovered.
        plan2, ok2 = self._upgrade()
        self.assertFalse(ok2)
        self.assertTrue(any("--recover" in line for line in self.log))
        self.assertTrue(upgrade.recover(self.ga_home, log=self.log.append,
                                        running=[]))
        self.assertEqual(self._marker(self.venv), "old")
        self.assertIsNone(upgrade.load_state(self.ga_home))

    def test_a_clean_run_leaves_no_state_file(self):
        plan, ok = self._upgrade()
        self.assertTrue(ok, "\n".join(self.log))
        self.assertIsNone(upgrade.load_state(self.ga_home))

    # -- code review round 3 ----------------------------------------------

    def _pipx_style_venv(self):
        venvs = os.path.join(self.home, "pipx", "venvs")
        os.makedirs(venvs)
        shutil.move(self.venv, os.path.join(venvs, "analytics-mcp"))
        self.venv = os.path.join(venvs, "analytics-mcp")
        with open(self.config) as f:
            cfg = json.load(f)
        cfg["venv_python"] = os.path.join(self.venv, "bin", "python")
        with open(self.config, "w") as f:
            json.dump(cfg, f)

    def test_a_cross_device_fallback_is_found_by_the_undo(self):
        self._pipx_style_venv()
        real_rename = os.rename

        def rename(src, dst):
            if dst.startswith(self.ga_home + os.sep) and ".old-" in dst:
                raise OSError(upgrade.errno.EXDEV, "cross-device")
            return real_rename(src, dst)
        self.fail_on = "google-auth-oauthlib"   # fails inside the rebuild
        with mock.patch.object(upgrade.os, "rename", rename):
            plan, ok = self._upgrade()
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        self.assertFalse(any("MOST of it" in line for line in self.log))

    def test_a_dead_terminal_does_not_stop_the_undo(self):
        # SIGHUP: every write to the closed terminal raises.
        def dead(message):
            raise OSError(5, "Input/output error")
        plan = upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                                 config_path=self.config,
                                 targets="claude_code")
        self.fail_on = "claude.json"   # after registration
        with mock.patch.object(upgrade, "run", self._run):
            ok = upgrade.upgrade(plan, [self.claude_json], log=dead,
                                 running=[])
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")
        with open(self.claude_json) as f:
            self.assertNotIn("data-noodler", json.load(f)["mcpServers"])
        self.assertIsNone(upgrade.load_state(self.ga_home))

    def test_a_second_ctrl_c_while_reporting_does_not_stop_the_undo(self):
        def log(message):
            if "INTERRUPTED" in message:
                raise KeyboardInterrupt
            self.log.append(message)
        plan = upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                                 config_path=self.config,
                                 targets="claude_code")
        with mock.patch.object(upgrade, "run", self._raise_on(
                "google-auth-oauthlib", KeyboardInterrupt())):
            ok = upgrade.upgrade(plan, [self.claude_json], log=log,
                                 running=[])
        self.assertFalse(ok)
        self.assertEqual(self._marker(self.venv), "old")

    def test_recover_refuses_while_servers_run(self):
        upgrade.save_state(upgrade.new_state(
            upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                              config_path=self.config), []))
        ok = upgrade.recover(self.ga_home, log=self.log.append,
                             running=["python /x/data-noodler/server/y"])
        self.assertFalse(ok)
        self.assertIsNotNone(upgrade.load_state(self.ga_home))

    def _record(self, pid):
        state = upgrade.new_state(
            upgrade.make_plan(repo_root=REPO, ga_home=self.ga_home,
                              config_path=self.config), [])
        state["pid"] = pid
        upgrade.save_state(state)

    def test_recover_refuses_while_the_upgrade_itself_is_alive(self):
        self._record(4312)
        ok = upgrade.recover(self.ga_home, log=self.log.append, running=[],
                             run_query=lambda pid: "python3 upgrade.py")
        self.assertFalse(ok)
        self.assertTrue(any("still running" in line for line in self.log))

    def test_a_reused_pid_does_not_block_recover(self):
        # After a reboot the recorded pid belongs to something unrelated.
        self._record(4312)
        ok = upgrade.recover(self.ga_home, log=self.log.append, running=[],
                             run_query=lambda pid: "/usr/libexec/something")
        self.assertTrue(ok, "\n".join(self.log))
        self.assertIsNone(upgrade.load_state(self.ga_home))

    def test_forget_drops_only_the_record(self):
        self._record(4312)
        before = sorted(os.listdir(self.ga_home))
        self.assertTrue(upgrade.forget(self.ga_home, log=self.log.append))
        self.assertIsNone(upgrade.load_state(self.ga_home))
        after = sorted(os.listdir(self.ga_home))
        self.assertEqual(set(before) - set(after), {upgrade.STATE_FILE})

    def test_an_unreadable_config_is_retryable_not_a_false_restore(self):
        real = self._run

        def run(cmd, env=None):
            if "verify.py" in " ".join(cmd) and "claude.json" in " ".join(cmd):
                with open(self.claude_json, "w") as f:
                    f.write("{half-writ")   # a transient bad read
                return 1, "simulated"
            return real(cmd, env)
        plan, ok = self._upgrade_with(run)
        self.assertFalse(ok)
        self.assertTrue(any("MOST of it" in line for line in self.log))
        self.assertIsNotNone(upgrade.load_state(self.ga_home),
                             "the record must stay for --recover")

    def test_an_unfixable_config_is_a_warning_not_a_stuck_record(self):
        real = self._run

        def run(cmd, env=None):
            if "verify.py" in " ".join(cmd) and "claude.json" in " ".join(cmd):
                with open(self.claude_json, "w") as f:
                    f.write("[1, 2, 3]")   # no longer a JSON object
                return 1, "simulated"
            return real(cmd, env)
        plan, ok = self._upgrade_with(run)
        self.assertFalse(ok)
        self.assertTrue(any("not a JSON object" in line for line in self.log))
        self.assertIsNone(upgrade.load_state(self.ga_home),
                          "the record would block every later upgrade")

    def test_install_staging_and_a_new_empty_sessions_folder_are_removed(self):
        shutil.rmtree(os.path.join(self.home, "sessions"))
        real = self._run

        def run(cmd, env=None):
            if "verify.py" in " ".join(cmd) and "claude.json" in " ".join(cmd):
                os.makedirs(os.path.join(self.ga_home, "bin.ga-new"))
                return 1, "simulated"
            return real(cmd, env)
        plan, ok = self._upgrade_with(run)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(os.path.join(self.ga_home,
                                                     "bin.ga-new")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "sessions")))

    def test_the_recover_hint_carries_a_custom_ga_home(self):
        self.assertIn("--home", upgrade._recover_command("/opt/ga"))
        self.assertNotIn("--ga-home", upgrade._recover_command(
            os.path.expanduser("~/.config/data-noodler")))


class TestPlan(unittest.TestCase):

    def test_the_base_python_comes_from_pyvenv_cfg(self):
        venv = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        open(os.path.join(home, "python.exe"), "w").close()
        with open(os.path.join(venv, "pyvenv.cfg"), "w") as f:
            f.write(f"home = {home}\nversion = 3.12.10\n")
        self.assertEqual(upgrade.base_python_for(venv, platform="win32"),
                         os.path.join(home, "python.exe"))

    def test_a_homebrew_base_is_found_by_its_versioned_name(self):
        # Homebrew's bin has python3.14 and no python3 (this Mac, measured).
        venv = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        open(os.path.join(home, "python3.14"), "w").close()
        with open(os.path.join(venv, "pyvenv.cfg"), "w") as f:
            f.write(f"home = {home}\nversion_info = 3.14.9\n")
        self.assertEqual(upgrade.base_python_for(venv, platform="darwin"),
                         os.path.join(home, "python3.14"))

    def test_something_that_is_not_a_venv_is_refused(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "bin"))
        py = os.path.join(d, "bin", "python")
        open(py, "w").close()
        cfg = os.path.join(d, "config.json")
        with open(cfg, "w") as f:
            json.dump({"venv_python": py}, f)
        with self.assertRaises(upgrade.UpgradeError) as ctx:
            upgrade.make_plan(repo_root=REPO, ga_home=d, config_path=cfg)
        self.assertIn("pyvenv.cfg", str(ctx.exception))

    def test_pip_is_installed_by_hash_before_anything_else(self):
        calls = []
        plan = mock.Mock(venv_dir="/v", old_venv="/v.old", venv_python="/v/py",
                         base_python="/base", constraints="/c.txt")
        with mock.patch.object(upgrade.os, "rename"), \
                mock.patch.object(upgrade.os.path, "exists",
                                  lambda p: p == "/v/py"), \
                mock.patch.object(upgrade, "run",
                                  lambda cmd, env=None: calls.append(cmd) or (0, "")):
            upgrade.rebuild_venv(plan, lambda _: None)
        pip_calls = [c for c in calls if c[1:4] == ["-m", "pip", "install"]]
        self.assertIn("#sha256=", pip_calls[0][-1])
        self.assertIn("-c", pip_calls[1])



class TestRunningServers(unittest.TestCase):
    """Code review #5 and #8."""

    def _hits(self, text, venv="/h/pipx/venvs/analytics-mcp",
              ga_home="/h/.config/data-noodler", platform="darwin"):
        return upgrade.running_servers(venv, ga_home, platform,
                                       run_ps=lambda: text)

    def test_a_server_from_the_venv_is_found(self):
        hits = self._hits(
            "/h/pipx/venvs/analytics-mcp/bin/python -m analytics_mcp.server")
        self.assertEqual(len(hits), 1)

    def test_venv_creation_naming_the_bare_path_is_found(self):
        # `python -m venv <venv_dir>` has no separator after the path.
        self.assertEqual(len(self._hits(
            "/usr/bin/python3 -m venv /h/pipx/venvs/analytics-mcp")), 1)

    def test_a_similarly_named_venv_is_not(self):
        hits = self._hits(
            "/h/pipx/venvs/analytics-mcp-dev/bin/python x\n"
            "/h/.config/data-noodler/analytics-mcp.old-20261025-1/bin/python y")
        self.assertEqual(hits, [])

    def test_windows_paths_match_either_separator_and_case(self):
        hits = self._hits(
            r'"c:\users\a\.config\data-noodler\VENV\Scripts\python.exe" -m x',
            venv=r"C:\Users\a\.config\data-noodler\venv",
            ga_home=r"C:\Users\a\.config\data-noodler", platform="win32")
        self.assertEqual(len(hits), 1)

    def test_a_failed_process_listing_is_unknown_not_empty(self):
        failed = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(upgrade.subprocess, "run",
                               return_value=failed):
            self.assertIsNone(upgrade.running_servers(
                "/h/pipx/venvs/analytics-mcp", "/h/.config/data-noodler", "darwin"))


class TestVersionNamedInterpreter(unittest.TestCase):
    """Code review #2, and round 2's Windows names."""

    def _checks(self, venv_python, platform, version="3.12"):
        plan = mock.Mock(venv_python=venv_python, base_python="/b/py",
                         constraints=__file__, dist=ROOT, venv_dir="/v",
                         ga_home="/g", platform=platform)
        with mock.patch.object(upgrade, "run",
                               return_value=(0, version + "\n")), \
                mock.patch.object(upgrade.shutil, "which", return_value=None):
            checks, _ = upgrade.preflight(plan, [], running=[])
        return [c for c in checks if c[1] == "interpreter"]

    def test_windows_pythonw_is_fine_and_python3_exe_is_not(self):
        self.assertEqual(self._checks(r"C:\v\Scripts\pythonw.exe", "win32"), [])
        self.assertTrue(self._checks(r"C:\v\Scripts\python3.exe", "win32"))

    def test_posix_matching_version_name_is_fine(self):
        self.assertEqual(self._checks("/v/bin/python3.12", "darwin"), [])

    def test_a_version_named_interpreter_must_match_the_base(self):
        plan = mock.Mock(venv_python="/v/bin/python3.12", base_python="/b/py",
                         constraints=__file__, dist=ROOT, venv_dir="/v",
                         ga_home="/g", platform="darwin")
        with mock.patch.object(upgrade, "run", return_value=(0, "3.13\n")), \
                mock.patch.object(upgrade.shutil, "which", return_value=None):
            checks, ready = upgrade.preflight(plan, [], running=[])
        self.assertFalse(ready)
        self.assertTrue(any(label == "interpreter" and ok is False
                            for ok, label, _ in checks))


if __name__ == "__main__":
    unittest.main()
