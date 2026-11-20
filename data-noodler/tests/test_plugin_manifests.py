"""The plugin manifests must match the shape Codex actually expects.

Shape confirmed by inspecting OpenAI's own bundled plugins on this machine:
.mcp.json takes env_vars as a pass-through list of NAMES, not values, which is
why the servers are launched through scripts that set the values themselves.
The entries run the installed launchers under ~/.config/ga-mcp/bin by
absolute path, with no "cwd", so Codex starts them in the project (#165).
"""

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MKT = os.path.join(ROOT, "marketplace")
PLUGIN = os.path.join(MKT, "plugins", "data-noodler")


class TestMarketplaceIndex(unittest.TestCase):
    def test_index_exists_at_the_path_codex_reads(self):
        self.assertTrue(os.path.exists(
            os.path.join(MKT, ".agents", "plugins", "marketplace.json")))

    def test_index_lists_the_plugin_with_a_local_source(self):
        with open(os.path.join(MKT, ".agents", "plugins",
                               "marketplace.json")) as f:
            data = json.load(f)
        names = [p["name"] for p in data["plugins"]]
        self.assertIn("data-noodler", names)
        entry = next(p for p in data["plugins"] if p["name"] == "data-noodler")
        self.assertEqual(entry["source"]["source"], "local")
        self.assertEqual(entry["source"]["path"], "./plugins/data-noodler")
        # Verify the path it names actually exists on disk relative to marketplace
        resolved_path = os.path.join(MKT, entry["source"]["path"])
        self.assertTrue(os.path.isdir(resolved_path),
                       f"Plugin path {resolved_path} does not exist")


class TestPluginManifest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(PLUGIN, ".codex-plugin",
                               "plugin.json")) as f:
            self.manifest = json.load(f)

    def test_name_matches_the_marketplace_entry(self):
        # Cross-check: plugin.json["name"] must match what the marketplace lists
        with open(os.path.join(MKT, ".agents", "plugins",
                               "marketplace.json")) as f:
            marketplace = json.load(f)
        entry = next(p for p in marketplace["plugins"] if p["name"] == "data-noodler")
        self.assertEqual(self.manifest["name"], entry["name"])

    def test_declares_a_skills_directory(self):
        self.assertEqual(self.manifest["skills"], "./skills/")

    def test_has_a_version_and_description(self):
        self.assertTrue(self.manifest["version"])
        self.assertTrue(self.manifest["description"])

    def test_mcpServers_field_points_to_existing_mcp_json(self):
        # Verify plugin.json declares mcpServers and the file it names exists
        self.assertIn("mcpServers", self.manifest,
                     "plugin.json must declare mcpServers field")
        mcp_path = self.manifest["mcpServers"]
        resolved = os.path.join(PLUGIN, mcp_path)
        self.assertTrue(os.path.isfile(resolved),
                       f"mcpServers points to {mcp_path} which does not exist at {resolved}")


class TestMcpManifest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(PLUGIN, ".mcp.json")) as f:
            self.mcp = json.load(f)

    def test_declares_both_servers(self):
        self.assertEqual(set(self.mcp["mcpServers"]),
                         {"analytics-mcp", "data-noodler"})

    def test_servers_start_in_the_project_not_the_plugin_folder(self):
        # With "cwd": "." Codex started our servers in its plugin cache, so
        # data-noodler could never see the project (#165, measured
        # 2026-10-25). A plugin server WITHOUT cwd starts in the folder Codex
        # was opened in -- measured with a probe plugin the same day.
        for name, entry in self.mcp["mcpServers"].items():
            with self.subTest(server=name):
                self.assertNotIn("cwd", entry)
                self.assertFalse(entry["command"].startswith("./"), name)
                self.assertFalse(any(a.startswith("./") for a in entry["args"]))

    def test_servers_run_the_installed_launchers(self):
        launchers = {"analytics-mcp": "launch-analytics-mcp",
                     "data-noodler": "launch-data-noodler"}
        for name, entry in self.mcp["mcpServers"].items():
            with self.subTest(server=name):
                self.assertEqual(entry["command"], "/bin/sh")
                self.assertIn("$HOME/.config/ga-mcp}/bin/" + launchers[name],
                              entry["args"][1])
                self.assertIn("HOME", entry["env_vars"])

    def test_env_vars_is_a_list_of_names_not_a_mapping(self):
        # Codex passes through named vars; it cannot set values here.
        for entry in self.mcp["mcpServers"].values():
            self.assertIsInstance(entry.get("env_vars", []), list)
            for item in entry.get("env_vars", []):
                self.assertIsInstance(item, str)


class TestTheEntriesActuallyRun(unittest.TestCase):
    """Run each .mcp.json command the way Codex would, from a project."""

    def _run(self, name, ga_home):
        import subprocess
        import tempfile
        with open(os.path.join(PLUGIN, ".mcp.json")) as f:
            entry = json.load(f)["mcpServers"][name]
        project = tempfile.mkdtemp()
        env = {"HOME": tempfile.mkdtemp(), "PATH": "/usr/bin:/bin",
               "GA_HOME": ga_home}
        return subprocess.run([entry["command"], *entry["args"]], cwd=project,
                              env=env, capture_output=True, text=True,
                              timeout=30), project

    def test_a_missing_launcher_fails_loudly_on_stderr(self):
        import tempfile
        p, _ = self._run("data-noodler", tempfile.mkdtemp())
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("data-noodler-setup", p.stderr)

    def test_the_launcher_runs_in_the_project_folder(self):
        import tempfile
        ga_home = tempfile.mkdtemp()
        os.makedirs(os.path.join(ga_home, "bin"))
        for launcher in ("launch-analytics-mcp", "launch-data-noodler"):
            path = os.path.join(ga_home, "bin", launcher)
            with open(path, "w") as f:
                f.write("#!/bin/sh\npwd -P\n")
            os.chmod(path, 0o755)
        for name in ("analytics-mcp", "data-noodler"):
            p, project = self._run(name, ga_home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout.strip(), os.path.realpath(project))

    def test_the_old_relative_shims_are_gone(self):
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "bin")))


def plugin_digest(root):
    """A fingerprint of everything Codex installs from the plugin directory."""
    import hashlib
    h = hashlib.sha256()
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc") or name == ".DS_Store":
                continue
            p = os.path.join(base, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            h.update(rel.encode() + b"\0")
            with open(p, "rb") as f:
                h.update(f.read() + b"\0")
    return h.hexdigest()


class TestPluginVersionMovesWithItsContents(unittest.TestCase):
    """The plugin's version must change whenever what it ships changes.

    Found 2026-10-06. Codex caches an installed plugin under a directory named
    for its version -- ~/.codex/plugins/cache/data-noodler/data-noodler/0.2.0/ --
    so a reinstall at the same version has nothing telling it to look again.
    mint_adc.py, ga_config.py and setup.md had all changed since 0.2.0 shipped
    on 2026-09-04, and the version was still 0.2.0: every Codex install
    anywhere was holding the September skill with no route to anything newer.

    tests/fixtures/plugin_content.json records the fingerprint of the
    released version. When the plugin changes, this fails twice, on purpose:
    first until the version is bumped, then until the new fingerprint is
    recorded. Both steps are deliberate acts, which is the point.
    """

    PLUGIN = os.path.join(ROOT, "marketplace", "plugins", "data-noodler")
    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures", "plugin_content.json")

    def test_contents_and_version_match_the_released_record(self):
        with open(self.FIXTURE, encoding="utf-8") as f:
            recorded = json.load(f)
        with open(os.path.join(self.PLUGIN, ".codex-plugin", "plugin.json"),
                  encoding="utf-8") as f:
            version = json.load(f)["version"]
        actual = plugin_digest(self.PLUGIN)

        if actual == recorded["sha256"]:
            return
        if version == recorded["version"]:
            self.fail(
                f"The plugin's contents changed but its version is still "
                f"{version}. Codex caches by version, so no existing install "
                "will ever pick the change up. Bump the version in "
                ".codex-plugin/plugin.json, then record the new fingerprint.")
        self.fail(
            f"Version {version} is not recorded. Once the contents are final, "
            f"set tests/fixtures/plugin_content.json to version {version!r} "
            f"and sha256 {actual!r}.")
