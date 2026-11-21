"""#1999 slice 2: the install home is ~/.config/data-noodler.

An existing machine has ~/.config/ga-mcp, holding config.json (which names
the person's Google sign-in), the installed servers and the personal guard's
lists. Two rules:

- Every reader looks in the new home first and falls back to the old one, so
  a machine works the same before, during and after the move.
- The move is one explicit step (migrate_home.py), taken only on the
  person's yes because it renames their sign-in files, and undoable.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import home as dn_home  # noqa: E402
import migrate_home  # noqa: E402
import config as server_config  # noqa: E402

OLD = "ga-" + "mcp"


def _fake_home():
    h = tempfile.mkdtemp()
    os.makedirs(os.path.join(h, ".config", "gcloud"))
    return h


def _old_install(h, venv_inside=False):
    old = os.path.join(h, ".config", OLD)
    os.makedirs(os.path.join(old, "server"))
    gcloud = os.path.join(h, ".config", "gcloud")
    client = os.path.join(gcloud, OLD + "-client.json")
    adc = os.path.join(gcloud, "adc-ga-" + "personal.json")
    for p in (client, adc):
        with open(p, "w") as f:
            f.write("{}")
    venv = (os.path.join(old, "venv", "bin", "python") if venv_inside
            else os.path.join(h, ".local", "share", "uv", "tools",
                              "analytics-mcp", "bin", "python"))
    cfg = {"oauth_client_file": client, "adc_file": adc,
           "venv_python": venv,
           "properties_csv": os.path.join(old, "properties.csv"),
           "mint_script": ("~/.config/" + OLD + "/marketplace/plugins/ga-"
                           "analytics/skills/google-" "analytics/scripts/mint_adc.py"),
           "export_roots": ["/elsewhere"]}
    with open(os.path.join(old, "config.json"), "w") as f:
        json.dump(cfg, f)
    with open(os.path.join(old, "personal-guard.txt"), "w") as f:
        f.write("secret-pattern\n")
    return old


class TestEveryReaderFindsTheHome(unittest.TestCase):
    def test_a_fresh_machine_uses_the_new_home(self):
        h = _fake_home()
        self.assertEqual(dn_home.default_home(h),
                         os.path.join(h, ".config", "data-noodler"))

    def test_an_unmigrated_machine_keeps_its_old_home(self):
        h = _fake_home()
        old = _old_install(h)
        self.assertEqual(dn_home.default_home(h), old)

    def test_the_new_home_wins_once_it_exists(self):
        h = _fake_home()
        _old_install(h)
        new = os.path.join(h, ".config", "data-noodler")
        os.makedirs(new)
        with open(os.path.join(new, "config.json"), "w") as f:
            f.write("{}")
        self.assertEqual(dn_home.default_home(h), new)

    def test_the_server_reads_the_old_config_until_the_move(self):
        h = _fake_home()
        old = _old_install(h)
        self.assertEqual(server_config.default_config_path(env={}, home=h),
                         os.path.join(old, "config.json"))

    def test_the_server_honours_its_env_override(self):
        self.assertEqual(server_config.default_config_path(
            env={"DATA_NOODLER_CONFIG": "/x/c.json"}, home="/nowhere"),
            "/x/c.json")


class AnEmptyNewHomeChangesNothing(unittest.TestCase):
    """Indigo's review of PR #5: readers chose the new home on isdir(), so
    an empty ~/.config/data-noodler flipped them all away from the real
    install. They decide on what a home holds, not on whether it exists."""

    def setUp(self):
        self.h = _fake_home()
        self.old = _old_install(self.h)
        os.makedirs(os.path.join(self.h, ".config", "data-noodler"))

    def test_the_installer_keeps_the_old_home(self):
        self.assertEqual(dn_home.default_home(self.h), self.old)

    def test_the_server_keeps_the_old_config(self):
        self.assertEqual(server_config.default_config_path(env={}, home=self.h),
                         os.path.join(self.old, "config.json"))

    def test_the_guard_keeps_the_old_lists(self):
        self.assertEqual(TestThePersonalGuardFollowsTheHome._config_dir(
            None, self.h), self.old)


class TheGuardDiffersOnPurpose(unittest.TestCase):
    """A contributor who never installed may keep only personal-guard.txt.
    For the guard the lists are what matter, so it follows them; the
    installer and server follow config.json. Pinned so it stays deliberate."""

    def test_a_list_alone_in_the_old_home_is_still_read(self):
        h = _fake_home()
        old = os.path.join(h, ".config", OLD)
        os.makedirs(old)
        with open(os.path.join(old, "personal-guard.txt"), "w") as f:
            f.write("x\n")
        self.assertEqual(TestThePersonalGuardFollowsTheHome._config_dir(None, h), old)
        self.assertEqual(dn_home.default_home(h),
                         os.path.join(h, ".config", "data-noodler"))


class TestTheMoveIsPlannedFirst(unittest.TestCase):
    def test_the_plan_changes_nothing(self):
        h = _fake_home()
        old = _old_install(h)
        before = sorted(os.listdir(os.path.dirname(old)))
        p = migrate_home.plan(h)
        self.assertEqual(p["action"], "move")
        self.assertEqual(sorted(os.listdir(os.path.dirname(old))), before)
        self.assertIn(("adc_file", "data-noodler-credential.json"),
                      [(k, os.path.basename(v[1])) for k, v in p["files"]])

    def test_nothing_to_do_on_a_new_install(self):
        h = _fake_home()
        os.makedirs(os.path.join(h, ".config", "data-noodler"))
        self.assertEqual(migrate_home.plan(h)["action"], "nothing")

    def test_refuses_when_both_homes_exist(self):
        h = _fake_home()
        _old_install(h)
        os.makedirs(os.path.join(h, ".config", "data-noodler"))
        self.assertEqual(migrate_home.plan(h)["action"], "refuse")

    def test_refuses_when_the_python_lives_inside_the_home(self):
        # A venv's scripts hold absolute paths; moving it breaks it.
        h = _fake_home()
        _old_install(h, venv_inside=True)
        p = migrate_home.plan(h)
        self.assertEqual(p["action"], "refuse")
        self.assertIn("venv", p["reason"])

    def test_refuses_while_a_server_runs(self):
        h = _fake_home()
        _old_install(h)
        with self.assertRaises(migrate_home.MigrateError):
            migrate_home.migrate(h, running=lambda: ["python data_noodler.py"])


class TestTheMove(unittest.TestCase):
    def setUp(self):
        self.h = _fake_home()
        self.old = _old_install(self.h)
        self.new = os.path.join(self.h, ".config", "data-noodler")
        self.gcloud = os.path.join(self.h, ".config", "gcloud")
        migrate_home.migrate(self.h, running=lambda: [])
        with open(os.path.join(self.new, "config.json")) as f:
            self.cfg = json.load(f)

    def test_the_folder_moved_with_everything_in_it(self):
        self.assertFalse(os.path.exists(self.old))
        for name in ("config.json", "personal-guard.txt", "server"):
            self.assertTrue(os.path.exists(os.path.join(self.new, name)), name)

    def test_the_sign_in_files_carry_the_new_names(self):
        self.assertEqual(sorted(os.listdir(self.gcloud)),
                         ["data-noodler-client.json",
                          "data-noodler-credential.json"])
        self.assertEqual(self.cfg["adc_file"], os.path.join(
            self.gcloud, "data-noodler-credential.json"))
        self.assertEqual(self.cfg["oauth_client_file"], os.path.join(
            self.gcloud, "data-noodler-client.json"))

    def test_every_path_into_the_old_home_now_points_at_the_new(self):
        self.assertEqual(self.cfg["properties_csv"],
                         os.path.join(self.new, "properties.csv"))
        self.assertEqual(self.cfg["mint_script"],
                         "~/.config/data-noodler/marketplace/plugins/data-noodler"
                         "/skills/data-noodler/scripts/mint_adc.py")
        self.assertEqual(self.cfg["export_roots"], ["/elsewhere"])
        self.assertNotIn(OLD, json.dumps(self.cfg))

    def test_the_server_now_reads_the_new_home(self):
        self.assertEqual(server_config.default_config_path(env={}, home=self.h),
                         os.path.join(self.new, "config.json"))

    def test_undo_puts_everything_back(self):
        migrate_home.undo(self.h, running=lambda: [])
        self.assertFalse(os.path.exists(self.new))
        with open(os.path.join(self.old, "config.json")) as f:
            cfg = json.load(f)
        self.assertTrue(cfg["adc_file"].endswith("adc-ga-" + "personal.json"))
        self.assertTrue(os.path.isfile(cfg["adc_file"]))
        self.assertTrue(os.path.isfile(cfg["oauth_client_file"]))
        self.assertTrue(os.path.isfile(os.path.join(self.old, "personal-guard.txt")))


class UndoIsAsCarefulAsTheMove(unittest.TestCase):
    """#2009: undo() renames the home back out from under anything running
    from it, so it refuses for the same reason migrate() does."""

    def setUp(self):
        self.h = _fake_home()
        self.old = _old_install(self.h)
        self.new = os.path.join(self.h, ".config", "data-noodler")
        migrate_home.migrate(self.h, running=lambda: [])

    def test_undo_refuses_while_a_server_runs_from_the_new_home(self):
        with self.assertRaises(migrate_home.MigrateError) as ctx:
            migrate_home.undo(self.h,
                              running=lambda: ["python data_noodler.py"])
        self.assertIn("quit", str(ctx.exception))
        self.assertTrue(os.path.isdir(self.new))
        self.assertFalse(os.path.exists(self.old))


class TheMoveWritesAtomically(unittest.TestCase):
    """#2009: config.json and the move record were written with a plain
    open(), so a kill mid-write left a truncated file. The rollback path
    cannot help with a kill; only an atomic write can."""

    def test_config_and_record_go_through_the_atomic_writer(self):
        from unittest import mock
        h = _fake_home()
        _old_install(h)
        new = os.path.join(h, ".config", "data-noodler")
        with mock.patch.object(migrate_home.safe_write, "write_atomically",
                               wraps=migrate_home.safe_write.write_atomically
                               ) as w:
            migrate_home.migrate(h, running=lambda: [])
        written = sorted(os.path.basename(c.args[0]) for c in w.call_args_list)
        self.assertEqual(written, sorted(["config.json", migrate_home.RECORD]))
        self.assertTrue(os.path.isfile(os.path.join(new, "config.json")))

    def test_a_backup_from_the_same_second_is_neither_used_nor_removed(self):
        # Rollback restored from a name it recomputed from the stamp, so a
        # backup already sitting at that name was copied over config.json
        # and then deleted.
        from unittest import mock
        h = _fake_home()
        old = _old_install(h)
        with open(os.path.join(old, "config.json")) as f:
            before = f.read()
        stale = os.path.join(old, "config.json.ga-backup-20261121-020000")
        with open(stale, "w") as f:
            f.write("an older backup")
        frozen = mock.Mock()
        frozen.datetime.now.return_value.strftime.return_value = \
            "20261121-020000"
        real = migrate_home.json.dumps

        def failing(obj, *a, **k):
            if isinstance(obj, dict) and "config_backup" in obj:
                raise OSError("disk full")
            return real(obj, *a, **k)

        with mock.patch.object(migrate_home, "datetime", frozen), \
                mock.patch("safe_write.datetime", frozen, create=True), \
                mock.patch.object(migrate_home.json, "dumps", failing):
            with self.assertRaises(OSError):
                migrate_home.migrate(h, running=lambda: [])
        with open(os.path.join(old, "config.json")) as f:
            self.assertEqual(f.read(), before)
        with open(stale) as f:
            self.assertEqual(f.read(), "an older backup")


class AFailureLateInTheMovePutsEverythingBack(unittest.TestCase):
    def test_a_failed_record_write_restores_the_config_too(self):
        h = _fake_home()
        old = _old_install(h)
        with open(os.path.join(old, "config.json")) as f:
            before = f.read()
        real_dumps = json.dumps

        def failing_dumps(obj, *a, **k):
            if isinstance(obj, dict) and "config_backup" in obj:
                raise OSError("disk full")
            return real_dumps(obj, *a, **k)

        migrate_home.json.dumps = failing_dumps
        try:
            with self.assertRaises(OSError):
                migrate_home.migrate(h, running=lambda: [])
        finally:
            migrate_home.json.dumps = real_dumps
        self.assertFalse(os.path.exists(os.path.join(h, ".config", "data-noodler")))
        with open(os.path.join(old, "config.json")) as f:
            self.assertEqual(f.read(), before)
        cfg = json.loads(before)
        self.assertTrue(os.path.isfile(cfg["adc_file"]))
        self.assertTrue(os.path.isfile(cfg["oauth_client_file"]))
        self.assertEqual([n for n in os.listdir(old) if ".ga-backup-" in n], [])


class TestThePersonalGuardFollowsTheHome(unittest.TestCase):
    """Indigo's hazard: with neither list found the guard warns and PASSES,
    so a home it cannot find is a silent downgrade of every push."""

    def _config_dir(self, h):
        out = subprocess.run(
            [sys.executable, "-I", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "import personal_guard; print(personal_guard.config_dir())",
             os.path.join(REPO, "tools")],
            capture_output=True, text=True,
            env={"HOME": h, "PATH": os.environ.get("PATH", "")})
        return out.stdout.strip()

    def test_it_reads_the_old_home_before_the_move(self):
        h = _fake_home()
        old = _old_install(h)
        self.assertEqual(self._config_dir(h), old)

    def test_it_reads_the_new_home_after_the_move(self):
        h = _fake_home()
        _old_install(h)
        migrate_home.migrate(h, running=lambda: [])
        self.assertEqual(self._config_dir(h),
                         os.path.join(h, ".config", "data-noodler"))


if __name__ == "__main__":
    unittest.main()
