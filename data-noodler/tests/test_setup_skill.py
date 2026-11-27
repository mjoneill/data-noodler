"""The setup skill must be complete enough to run unattended by a model.

Asserts the structure a skill needs and the specific traps it must warn
about -- each one cost real debugging time and would otherwise be rediscovered
by every colleague.
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skills", "data-noodler-setup")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")

# Repo-relative paths the document's commands reference, e.g.
# "data-noodler/installer/verify.py". Deliberately simple: it does not try to
# parse shell, only to pull out path-shaped tokens rooted at data-noodler/ so
# that a stale or wrong path (like the bug this test was added to catch) is
# caught mechanically rather than by a human re-reading the prose.
# A repo path starts the token or follows "<repo>/". Since #1999 the skill is
# also called data-noodler, so ".../skills/data-noodler/scripts/x.py" and
# "~/.claude/skills/data-noodler/..." are installed paths, not repo paths.
REPO_PATH_RE = re.compile(
    r"(?:(?<=<repo>/)|(?<![\w/.~-]))data-noodler/[A-Za-z0-9_./-]+\.(?:py|md|sh)")


class TestSetupSkillStructure(unittest.TestCase):
    def setUp(self):
        with open(SKILL_MD) as f:
            self.text = f.read()

    def test_has_frontmatter_with_name_and_description(self):
        self.assertTrue(self.text.startswith("---"))
        head = self.text.split("---")[1]
        self.assertIn("name:", head)
        self.assertIn("description:", head)

    def test_description_mentions_the_harnesses_it_installs_into(self):
        head = self.text.split("---")[1].lower()
        self.assertIn("claude desktop", head)
        self.assertIn("codex", head)

    def test_documents_every_install_step(self):
        # bootstrap_config.py belongs in this list: every step after it
        # substitutes <venv_python> or reads adc_file out of
        # ~/.config/data-noodler/config.json, and nothing else in the flow creates
        # that file. Without it the skill stalls on a colleague's machine with
        # no interpreter path to put in the command.
        for step in ("uv tool install", "bootstrap_config.py", "mint_adc.py",
                     "install.py", "verify.py", "codex plugin"):
            self.assertIn(step, self.text, step)

    def test_every_step_cross_reference_resolves_to_a_real_step(self):
        # The document steers a model by step number ("Skip to Step 6"), so a
        # reference to a step that does not exist -- or that moved when a step
        # was inserted -- silently sends it to the wrong place.
        headings = set(int(m.group(1)) for m in
                       re.finditer(r"^## Step (\d+):", self.text, re.M))
        self.assertTrue(headings, "no '## Step N:' headings found")
        self.assertEqual(sorted(headings),
                         list(range(1, len(headings) + 1)),
                         "step headings are not consecutive from 1")
        referenced = set(int(n) for n in
                         re.findall(r"\bStep (\d+)\b", self.text))
        dangling = sorted(referenced - headings)
        self.assertEqual(dangling, [],
                          "SKILL.md references steps that do not exist: %r"
                          % dangling)

    def test_warns_not_to_re_mint_a_working_credential(self):
        lowered = self.text.lower()
        self.assertIn("credential_status", self.text)
        self.assertTrue("do not re-mint" in lowered
                        or "never re-mint" in lowered)

    def test_warns_about_the_restart_requirement(self):
        self.assertIn("restart", self.text.lower())

    def test_warns_about_the_two_claude_directories(self):
        self.assertIn("Claude-3p", self.text)

    def test_states_that_cloud_and_web_chat_are_out_of_scope(self):
        lowered = self.text.lower()
        self.assertIn("cloud", lowered)

    def test_troubleshooting_reference_exists_and_covers_the_traps(self):
        with open(os.path.join(SKILL_DIR, "references",
                               "troubleshooting.md")) as f:
            body = f.read()
        # access_denied belongs here with the rest: it is the one failure a
        # colleague cannot fix on their own machine, so a reader who does not
        # find it will keep re-running consent and reinstalling instead of
        # asking the maintainer for the one thing that works.
        for trap in ("invalid_grant", "GRPC_DNS_RESOLVER", "stdout",
                     "access_denied", "Test users"):
            self.assertIn(trap, body, trap)

    def test_warns_about_the_test_user_prerequisite_before_consent(self):
        # The OAuth client is in Testing publishing status, so Google blocks
        # consent for anyone the Cloud project has not listed. The skill must
        # say so at the consent step -- a model that does not know this will
        # debug the config instead of naming the real blocker.
        self.assertIn("access_denied", self.text)
        self.assertIn("Test users", self.text)

    def test_referenced_repo_paths_exist_on_disk(self):
        # ROOT is .../data-noodler; the paths in the doc (e.g.
        # "data-noodler/installer/verify.py") are relative to its parent, the
        # repo root the doc tells the reader to run commands from.
        repo_root = os.path.dirname(ROOT)
        paths = sorted(set(m.group(0) for m in REPO_PATH_RE.finditer(self.text)))
        self.assertTrue(paths, "expected at least one data-noodler/... path "
                                "referenced in SKILL.md")
        missing = [p for p in paths
                   if not os.path.exists(os.path.join(repo_root, p))]
        self.assertEqual(missing, [],
                          "SKILL.md references paths that do not exist on "
                          "disk: %r" % missing)


class TestOAuthClientFileStep(unittest.TestCase):
    """The agent path must not assume the OAuth client file is already there.

    INSTALL.md carries this as a full step. SKILL.md had none, so an
    agent-driven install silently assumed the file was present. It usually is
    on the author's machine, which is why the gap survived two installs.

    On a machine where it is absent the failure lands late and points nowhere
    useful: bootstrap_config writes an `oauth_client_file` key naming a path
    that does not exist, and the consent step then fails. Nothing before that
    says the file was ever needed.
    """

    def setUp(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            self.text = f.read()

    def test_names_the_shared_oauth_client_file(self):
        self.assertIn("data-noodler-client.json", self.text,
                      "SKILL.md never names the OAuth client file, so an agent "
                      "following it has no way to know the file is required")

    def test_says_where_the_file_has_to_be_obtained_from(self):
        lowered = self.text.lower()
        self.assertTrue(
            "deployment.json" in lowered or "whoever gave you" in lowered,
            "SKILL.md does not say how the client file reaches the user. "
            "Delivery is the deployment's business (deployment.json), so the "
            "agent has to hand this to a human rather than attempt it.")


class TestWindowsReference(unittest.TestCase):
    """As prose takes over more of the install, this file becomes its tests.

    Nothing can assert that prose is true. What can be asserted is that it
    exists, that it names the things a reader will need, that the paths it
    cites are real, and that it does not tell a Windows reader to run a
    command that cannot work there. That is the whole of the safety net on
    this half of the install, so it has to be tight.
    """

    WINDOWS_MD = os.path.join(SKILL_DIR, "references", "windows.md")

    def setUp(self):
        with open(self.WINDOWS_MD, encoding="utf-8") as f:
            self.text = f.read()
        with open(SKILL_MD, encoding="utf-8") as f:
            self.skill = f.read()

    def test_the_reference_exists_and_is_not_a_stub(self):
        self.assertGreater(len(self.text), 2000,
                           "a Windows page that says nothing is worse than "
                           "none: it implies the platform is handled")

    def test_the_skill_sends_windows_readers_to_it(self):
        self.assertIn("references/windows.md", self.skill,
                      "nothing in SKILL.md points at the Windows page, so a "
                      "reader follows the macOS path into a wall")

    def test_it_names_the_paths_a_reader_actually_needs(self):
        for needed in (r"%APPDATA%\Claude", r"Scripts\python.exe",
                       ".claude.json"):
            self.assertIn(needed, self.text, needed)

    def test_it_names_the_escape_hatch(self):
        self.assertIn("--venv-python", self.text,
                      "without the flag named here, an agent that cannot "
                      "discover the interpreter has nothing to reach for "
                      "except invention")

    def test_it_does_not_tell_a_windows_reader_to_install_with_uv(self):
        # uv may be discussed -- explaining why it is absent is useful. What
        # must not appear is a runnable uv install command, because on the
        # machine measured uv is absent and needs an administrator to install.
        self.assertNotIn("uv tool install", self.text)
        self.assertIn("python -m venv", self.text)

    def test_it_states_what_is_still_unproven(self):
        lowered = self.text.lower()
        self.assertIn("unproven", lowered)
        for unproven in ("consent", "desktop", "spaces"):
            self.assertIn(unproven, lowered, unproven)

    def test_it_keeps_the_git_bash_trap_visible(self):
        # The most expensive available mistake: Git Bash runs the POSIX
        # launchers, so testing one there looks like success while telling
        # you nothing about whether Claude Desktop can spawn it.
        self.assertIn("Git Bash", self.text)

    def test_it_does_not_hide_the_credential_permissions_gap(self):
        self.assertIn("icacls", self.text,
                      "the Windows credential-permissions gap is real and "
                      "unclosed; a page that omits it misleads by silence")

    def test_referenced_repo_paths_exist_on_disk(self):
        repo_root = os.path.dirname(ROOT)
        paths = sorted(set(m.group(0) for m in REPO_PATH_RE.finditer(self.text)))
        missing = [p for p in paths
                   if not os.path.exists(os.path.join(repo_root, p))]
        self.assertEqual(missing, [], f"windows.md cites paths that do not "
                                      f"exist: {missing!r}")


class TestSkillUsesTheToolsItShips(unittest.TestCase):
    def setUp(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            self.text = f.read()

    def test_step_one_runs_the_probe_rather_than_shell_to_translate(self):
        self.assertIn("probe.py", self.text)
        self.assertNotIn('2>/dev/null || true', self.text)

    def test_verification_demands_an_exit_code_not_a_reading(self):
        self.assertIn("--require analytics-mcp=10", self.text)
        # The number itself is checked against the server by the test below.
        self.assertIn("--require data-noodler=", self.text)

    def test_every_documented_tool_count_matches_the_server(self):
        # Card #130 added a tenth tool. A verify command still demanding nine
        # fails a correct install, and the person running it is told the
        # install is broken. So the count in every document must follow the
        # server, not be updated by hand and hoped for.
        import ast
        import glob
        handshake = os.path.join(ROOT, "tests", "test_handshake.py")
        with open(handshake, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        expected = next(
            len(ast.literal_eval(n.value)) for n in tree.body
            if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "") == "EXPECTED_TOOLS")
        repo = os.path.dirname(ROOT)
        docs = (glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True)
                + glob.glob(os.path.join(repo, "docs", "runbooks", "*.md")))
        for path in docs:
            with open(path, encoding="utf-8") as f:
                for n in re.findall(r"--require data-noodler=(\d+)", f.read()):
                    self.assertEqual(int(n), expected,
                                     f"{path} demands {n} data-noodler tools")


class TestConstraintsFile(unittest.TestCase):
    """Pins are data. Data still gets asserted."""

    CONSTRAINTS = os.path.join(ROOT, "installer", "constraints.txt")

    def setUp(self):
        with open(self.CONSTRAINTS, encoding="utf-8") as f:
            self.text = f.read()
        self.pins = [l.strip() for l in self.text.splitlines()
                     if l.strip() and not l.startswith("#")]

    def test_it_pins_the_package_the_documents_name(self):
        self.assertIn("analytics-mcp==1.1.0", self.pins,
                      "the constraints file and the install command disagree "
                      "about which version is being installed")

    def test_it_pins_the_consent_dependency_too(self):
        # google-auth-oauthlib is not a dependency of the server; it rides
        # along for mint_adc.py and would otherwise float free.
        self.assertTrue(any(p.startswith("google-auth-oauthlib==")
                            for p in self.pins))

    def test_every_line_is_an_exact_pin(self):
        # A range in a constraints file is a pin that does not pin, which is
        # worse than none because it looks like determinism.
        loose = [p for p in self.pins if "==" not in p]
        self.assertEqual(loose, [], f"not exact pins: {loose!r}")

    def test_it_explains_itself_to_whoever_finds_it_next(self):
        lowered = self.text.lower()
        self.assertIn("regenerate", lowered)
        self.assertIn("freeze_constraints.py", self.text)

    def test_the_regenerator_it_names_exists(self):
        self.assertTrue(os.path.exists(
            os.path.join(ROOT, "installer", "freeze_constraints.py")))


class TestClientFileIsAnnouncedNotShipped(unittest.TestCase):
    """The OAuth client file is kept out of the repo, and that must be SAID.

    Decided 2026-10-01: out of band, from the maintainer directly. Out of the
    repo must not mean out of sight -- a required file nobody is told about
    produces an install that stops at sign-in and reads as a local fault.

    So two properties are asserted together: the file is announced where a
    cloner looks first, and the file is not actually here.
    """

    REPO = os.path.dirname(ROOT)
    # START-HERE.md is the first thing a reader of the package opens; the
    # repository README is the maintainer's and is not shipped.
    README = os.path.join(ROOT, "START-HERE.md")

    def setUp(self):
        with open(self.README, encoding="utf-8") as f:
            self.readme = f.read()

    def test_the_readme_names_the_file(self):
        self.assertIn("data-noodler-client.json", self.readme)

    def test_the_readme_says_it_is_not_in_the_repo(self):
        self.assertIn("not in this package", self.readme,
                      "START-HERE must say plainly that the file is absent on "
                      "purpose, or a reader assumes the package is incomplete")

    def test_the_readme_says_who_it_comes_from(self):
        # Two sources, by situation: the deployment's maintainer, or your
        # own Cloud project.
        self.assertIn("deployment.json", self.readme)
        self.assertIn("GOOGLE-CLOUD-SETUP.md", self.readme,
                      "a notice that a file is missing, with no source for it, "
                      "only moves the confusion one step later")

    def test_the_readme_pairs_it_with_the_test_user_step(self):
        # The other thing only the maintainer can do. Asking for one without
        # the other costs a second round trip and a propagation wait.
        self.assertIn("test user", self.readme)

    def test_the_file_itself_is_not_in_the_tree(self):
        found = [os.path.join(d, f) for d, _, fs in os.walk(self.REPO)
                 if ".git" not in d.split(os.sep)
                 for f in fs if "data-noodler-client" in f and f.endswith(".json")]
        self.assertEqual(found, [], "the client file is in the working tree; "
                                    "it was decided it must not be")

    def test_gitignore_actually_excludes_the_real_filename(self):
        # The original pattern, *client_secret*.json, never matched this
        # name. Assert against the real filename, not the expected one.
        import subprocess
        if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=self.REPO,
                          capture_output=True).returncode != 0:
            self.skipTest("not a git checkout (a shared zip)")
        proc = subprocess.run(["git", "check-ignore", "-q", "data-noodler-client.json"],
                              cwd=self.REPO, capture_output=True)
        self.assertEqual(proc.returncode, 0,
                         ".gitignore does not exclude data-noodler-client.json")


class TestDocumentedVerifyChecksTheSkill(unittest.TestCase):
    """Issue #5's fix only works if the documented command uses it.

    A --require-skill flag nobody's verify line passes would leave exactly the
    gap the report described: every check green, the skill never installed.
    """

    def _text(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def test_skill_md_verifies_the_claude_code_skill(self):
        self.assertIn("--require-skill data-noodler", self._text(SKILL_MD))

    def test_install_md_verifies_the_claude_code_skill(self):
        self.assertIn("--require-skill data-noodler",
                      self._text(ROOT, "INSTALL.md"))

    def test_install_md_verify_uses_require_at_all(self):
        # It predated --require entirely, so a passing run proved only that
        # each server started -- not that it served the expected tools.
        self.assertIn("--require analytics-mcp=10", self._text(ROOT, "INSTALL.md"))


class TestSecondWindowsInstallLessons(unittest.TestCase):
    """What the 2026-10-09 install taught, pinned so it cannot quietly go.

    That install worked only because its agent improvised four times: it
    copied the skills from INSTALL.md, handed the Python installer and the
    Desktop registration to the user, and repointed analytics-mcp past
    Defender. Each improvisation is now an instruction. These tests check the
    instructions are still there -- and that the report which surfaced all of
    it is now a step, not something the user has to remember to ask for.
    """

    REFS = os.path.join(SKILL_DIR, "references")

    def setUp(self):
        def read(*parts):
            with open(os.path.join(*parts), encoding="utf-8") as f:
                return f.read()
        self.skill = read(SKILL_MD)
        self.windows = read(self.REFS, "windows.md")
        self.trouble = read(self.REFS, "troubleshooting.md")
        self.install_md = read(ROOT, "INSTALL.md")

    def _step(self, n):
        m = re.search(r"^## Step %d:.*?(?=^## )" % n, self.skill, re.M | re.S)
        self.assertIsNotNone(m, "no Step %d" % n)
        return m.group(0)

    # -- the install report (#145) ---------------------------------------

    def test_the_last_step_is_the_install_report_and_it_is_required(self):
        steps = [int(n) for n in re.findall(r"^## Step (\d+):", self.skill, re.M)]
        last = self._step(max(steps))
        self.assertIn("install report", last.lower())
        self.assertIn("required", last.lower())
        self.assertIn("fresh", last.lower())
        self.assertIn("upgrade", last.lower())

    def test_the_report_template_exists_and_the_step_names_it(self):
        self.assertIn("references/install-report.md", self.skill)
        self.assertTrue(os.path.exists(
            os.path.join(self.REFS, "install-report.md")))

    def test_the_template_keeps_secrets_and_data_out(self):
        with open(os.path.join(self.REFS, "install-report.md"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn("data-noodler-client.json", text)
        self.assertIn("never", text.lower())
        self.assertIn("<user>", text)
        self.assertIn("workaround", text.lower())

    def test_notes_start_before_step_one(self):
        before = self.skill.split("## Step 1:")[0]
        self.assertIn("Keep notes", before)

    # -- clean-up with consent (#139 upgrades, #144) ---------------------

    def test_cleanup_never_removes_without_asking(self):
        step = self._step(9).lower()
        self.assertIn("without asking", step)
        self.assertIn("only on a yes", step)

    def test_cleanup_names_the_known_leftover_and_what_to_leave(self):
        step = self._step(9)
        self.assertIn("fix_asr_entry.py", step)
        self.assertIn("analytics-mcp.exe", step)
        self.assertIn("ga-backup", step)

    def test_client_file_is_looked_for_where_people_save_things(self):
        step = self._step(3)
        for place in ("Downloads", "Desktop", "Documents"):
            self.assertIn(place, step, place)
        self.assertIn("Never print", step)

    def test_the_by_hand_path_says_to_delete_the_downloaded_copy(self):
        self.assertIn("delete that copy", self.install_md)

    # -- skills are installed by the flow that verifies them -------------

    def test_the_skill_installs_the_skill_its_verify_step_requires(self):
        # Step 8 runs --require-skill data-noodler; until 2026-10-09
        # nothing in SKILL.md put it there, and the agent borrowed the step
        # from INSTALL.md.
        self.assertIn("--require-skill data-noodler", self.skill)
        step6 = self._step(6)
        self.assertIn(".claude/skills", step6)
        self.assertIn("data-noodler", step6)

    # -- the Desktop container (#140, #141) ------------------------------

    def test_desktop_registration_is_handed_over_from_inside_desktop(self):
        step = self._step(7)
        self.assertIn("running inside Claude Desktop", step)
        self.assertIn("--targets claude_desktop", step)
        self.assertIn("--require data-noodler=", step)

    def test_windows_page_checks_for_the_store_stub(self):
        self.assertIn("WindowsApps", self.windows)
        self.assertIn("ordinary PowerShell", self.windows)
        self.assertIn("2203", self.windows)

    # -- Defender (#139, #142) -------------------------------------------

    def test_windows_page_explains_the_python_m_entry(self):
        self.assertIn("-m analytics_mcp.server", self.windows)
        self.assertIn("01443614-CD74-433A-B99E-2ECDC07BFC25", self.windows)

    def test_verify_points_at_a_troubleshooting_section_that_exists(self):
        sys.path.insert(0, os.path.join(ROOT, "installer"))
        import verify
        hint = verify.hint_for("PermissionError: [WinError 5] Access is denied",
                               r"C:\v\Scripts\analytics-mcp.exe")
        named = re.search(r'"([^"]+)"', hint).group(1)
        self.assertIn("## " + named, self.trouble)


class TestUpgradeIsSupervisedNotImprovised(unittest.TestCase):
    """The agent supervises upgrade.py; it never re-creates its steps (#33)."""

    def setUp(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            self.skill = f.read()
        with open(os.path.join(ROOT, "INSTALL.md"), encoding="utf-8") as f:
            self.install_md = f.read()

    def test_the_skill_says_run_the_code_not_a_hand_copy_of_it(self):
        self.assertIn("do not re-create its steps by hand", self.skill)
        flat = " ".join(self.skill.split())
        self.assertIn("Read `installer/upgrade.py` before you use it", flat)

    def test_the_plan_comes_first_and_is_checked(self):
        up = self.skill[self.skill.index("### On an upgrade"):]
        self.assertLess(up.index("--plan"), up.index("The run -- the user"))
        self.assertIn("Check it against the machine", up)

    def test_app_specific_steps_belong_to_the_agent_after_the_run(self):
        after = self.skill[self.skill.index("**After -- you"):]
        self.assertIn("codex plugin add data-noodler@data-noodler", after)
        self.assertIn("copy_skills.py", after)
        self.assertIn("--replace", after)

    def test_the_by_hand_document_starts_with_upgrade_instead(self):
        self.assertLess(self.install_md.index("Upgrade instead"),
                        self.install_md.index("## 1."))
        self.assertIn("upgrade.py --plan", self.install_md)

    def test_no_document_copies_skills_with_cp_any_more(self):
        for text in (self.skill, self.install_md):
            self.assertNotIn("cp -R ~/.config/data-noodler/marketplace", text)
            self.assertNotIn("Copy-Item -Recurse -Force", text)


class TestTheGoogleCloudGuideMatchesTheCode(unittest.TestCase):
    """GOOGLE-CLOUD-SETUP.md must ask for exactly what the code needs (#171)."""

    GUIDE = os.path.join(ROOT, "GOOGLE-CLOUD-SETUP.md")

    def setUp(self):
        with open(self.GUIDE, encoding="utf-8") as f:
            self.guide = f.read()

    def test_it_names_every_google_service_the_code_calls(self):
        import glob
        hosts = set()
        for path in glob.glob(os.path.join(ROOT, "server", "*.py")):
            with open(path, encoding="utf-8") as f:
                hosts |= set(re.findall(r"https://([a-z]+)\.googleapis\.com",
                                        f.read()))
        hosts.discard("www")  # scope URLs, not services
        needed = hosts | {"analyticsdata", "analyticsadmin"}  # via client libs
        for host in needed:
            self.assertIn(f"{host}.googleapis.com", self.guide, host)

    def test_the_scopes_it_mentions_are_the_ones_consent_requests(self):
        mint = os.path.join(ROOT, "skills", "data-noodler", "scripts",
                            "mint_adc.py")
        with open(mint, encoding="utf-8") as f:
            scopes = set(re.findall(r"auth/([a-z.]+)\"", f.read()))
        self.assertEqual(scopes, {"analytics.readonly", "webmasters.readonly"})
        for scope in scopes:
            self.assertIn(scope, self.guide)

    def test_it_explains_both_files_not_just_the_client(self):
        # A deployer has to understand the per-person credential too: what
        # it is, how it comes to exist, that it never moves, how to revoke.
        for must in ("data-noodler-credential.json", "mint_adc.py", "credential_status",
                     "myaccount.google.com/permissions", "never"):
            self.assertIn(must, self.guide, must)

    def test_it_insists_on_a_desktop_client(self):
        self.assertIn("Desktop app", self.guide)
        self.assertIn('"installed"', self.guide)

    def test_it_is_reachable_from_both_install_paths(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            self.assertIn("GOOGLE-CLOUD-SETUP.md", f.read())
        with open(os.path.join(ROOT, "INSTALL.md"), encoding="utf-8") as f:
            self.assertIn("GOOGLE-CLOUD-SETUP.md", f.read())

    def test_it_names_no_one_and_no_real_project(self):
        # Institution specifics are covered by test_no_institution_specifics;
        # this guide must also name no particular maintainer.
        self.assertNotIn("Michael", self.guide)


class TestChatGPTSurfacesAreStatedHonestly(unittest.TestCase):
    """2026-10-29: the ChatGPT desktop app uses the Codex plugin; ChatGPT in a
    browser is hosted and cannot. 2026-11-26: the app's separate Chat and Work
    modes have merged, so the docs name the app, not a mode. They must say both."""

    def test_the_skill_says_desktop_yes_browser_no(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| ChatGPT desktop app | yes", text)
        self.assertIn("| ChatGPT or claude.ai in a browser | **no**", text)
        self.assertIn("Browser surfaces cannot be served", text)

    def test_a_chatgpt_only_mac_is_told_where_codex_is(self):
        for path in (SKILL_MD, os.path.join(ROOT, "INSTALL.md")):
            with open(path, encoding="utf-8") as f:
                self.assertIn("ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
                              f.read(), path)

    def test_install_md_says_the_same(self):
        with open(os.path.join(ROOT, "INSTALL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| ChatGPT desktop app | **Confirmed working**", text)
        self.assertIn("| claude.ai / ChatGPT web (browser) | **Cannot work, by design.**", text)


class TestEveryCommandBlockStandsOnItsOwn(unittest.TestCase):
    """Review, 2026-11-09. An agent runs each step as its own shell call, so
    a variable set in one fenced block is empty in the next: Step 5 ran
    `"$PY3"` that only Step 4 had set. And Step 1 said `python3`, which a
    python.org install on Windows does not have."""

    def _blocks(self, path):
        with open(path, encoding="utf-8") as f:
            return re.findall(r"```(?:bash)?\n(.*?)```", f.read(), re.S)

    def test_a_block_that_runs_py3_sets_it(self):
        for path in (SKILL_MD, os.path.join(ROOT, "INSTALL.md")):
            using = [b for b in self._blocks(path) if '"$PY3"' in b]
            self.assertTrue(using, path)
            for block in using:
                self.assertIn("PY3=/usr/bin/python3", block, path)
                self.assertIn("uv python find", block, path)
                # and says so, rather than running an empty command name
                self.assertIn('[ -x "$PY3" ]', block, path)

    def test_step_1_names_the_windows_command(self):
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        step1 = skill[skill.index("## Step 1"):skill.index("## Step 2")]
        self.assertIn("On Windows, use `python`.", step1)

    def test_the_minimum_macos_is_stated(self):
        with open(os.path.join(ROOT, "INSTALL.md"), encoding="utf-8") as f:
            self.assertIn("macOS 12", f.read())
