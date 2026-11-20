#!/bin/sh
# Install into a throwaway HOME to prove two independent paths work where
# nothing is set up yet: the agent-driven payload install, and the by-hand
# config-generation path someone without an agent would use.
#
# Cannot test the consent flow (that needs a browser and a human) or the real
# apps (they read the real HOME). What it does prove:
#   - the payload (server/, bin/, marketplace/) installs into a bare
#     .config/data-noodler with no prior state;
#   - launch-data-noodler exits non-zero, writes nothing to stdout, and names
#     the setup skill on stderr when no config.json exists at all -- this is
#     the "nothing installed yet" case, not a credential case: this launcher's
#     own absent-credential path is deliberately non-fatal (see below), so it
#     is never exercised here;
#   - launch-analytics-mcp's absent-credential path IS fatal, unlike
#     launch-data-noodler's -- that asymmetry gets its own check further down;
#   - registration creates Claude Code and Claude Desktop configs from
#     nothing and is idempotent;
#   - bootstrap_config.py generates a config anchored to the fake home and
#     refuses to overwrite it on a second run, proving the by-hand path;
#   - the renewal command credential_status would print names a mint_adc.py
#     that actually exists inside that home -- the check no unit test can
#     make, since a path can exist on the author's machine and nowhere else.
set -eu

REPO="${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
VENV_PY="${VENV_PY:-$HOME/Library/Application Support/pipx/venvs/analytics-mcp/bin/python}"
FAKE_HOME=$(mktemp -d)
trap 'rm -rf "$FAKE_HOME"' EXIT

echo "== fake HOME: $FAKE_HOME"
mkdir -p "$FAKE_HOME/.config/data-noodler" \
         "$FAKE_HOME/Library/Application Support/Claude"

echo "== payload installs into a clean home"
"$VENV_PY" "$REPO/data-noodler/installer/install.py" \
  --repo-root "$REPO" --home "$FAKE_HOME/.config/data-noodler" --payload-only

echo "== launch-data-noodler fails cleanly with no config at all"
set +e
DATA_NOODLER_HOME="$FAKE_HOME/.config/data-noodler" \
  "$FAKE_HOME/.config/data-noodler/bin/launch-data-noodler" \
  >"$FAKE_HOME/out" 2>"$FAKE_HOME/err"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || { echo "FAIL: launcher exited 0 with no config"; exit 1; }
[ ! -s "$FAKE_HOME/out" ] || { echo "FAIL: launcher wrote to stdout"; exit 1; }
grep -q "data-noodler-setup" "$FAKE_HOME/err" || {
  echo "FAIL: error does not name the setup skill"; exit 1; }
echo "   ok: exit=$CODE, stdout empty, stderr names the skill"

echo "== registration creates configs from nothing"
# No HOME= prefix here: harness_paths is called below with explicit home=
# kwargs, which is the real isolation mechanism -- an env var override would
# be dead weight.
"$VENV_PY" - <<PY
import os, sys
sys.path.insert(0, "$REPO/data-noodler/installer")
import harness_paths, register
ga_home = os.path.join("$FAKE_HOME", ".config", "data-noodler")
entries = register.server_entries(ga_home)
for path in (harness_paths.claude_code_config(home="$FAKE_HOME"),
             harness_paths.claude_desktop_config(home="$FAKE_HOME")):
    r = register.register_json(path, entries)
    assert r["changed"], path
    r2 = register.register_json(path, entries)
    assert not r2["changed"], f"not idempotent: {path}"
    print(f"   ok: {os.path.basename(path)} created and idempotent")
PY

echo "== bootstrap_config writes a usable config into a clean home"
"$VENV_PY" "$REPO/data-noodler/installer/bootstrap_config.py" --home "$FAKE_HOME"
CFG="$FAKE_HOME/.config/data-noodler/config.json"
[ -f "$CFG" ] || { echo "FAIL: no config written"; exit 1; }
"$VENV_PY" - <<PY
import json, os
cfg = json.load(open("$CFG"))
for key in ("oauth_client_file", "adc_file", "venv_python", "properties_csv"):
    assert os.path.isabs(cfg[key]), (key, cfg[key])
for key in ("oauth_client_file", "adc_file", "properties_csv"):
    assert cfg[key].startswith("$FAKE_HOME"), (key, cfg[key])
print("   ok: config paths absolute and anchored to the fake home")
PY

echo "== the renewal command names a file that actually exists"
# The whole point of credential_status's renewal command is that a user can
# paste it and have it work. Asserting the string is not enough -- the previous
# default named ~/.claude/skills/..., a path nothing in this installer creates,
# and it went unnoticed for fifteen reviews because it happens to exist on the
# author's machine. Checking inside the throwaway home is what catches that.
"$VENV_PY" - <<PY
import os, sys
sys.path.insert(0, "$REPO/data-noodler/server")
import config
cfg = config.load("$CFG")
script = cfg["mint_script"]
assert script.startswith("$FAKE_HOME"), script
assert os.path.exists(script), f"renewal command names a missing file: {script}"
cmd = config.renewal_command(cfg)
assert f'"{script}"' in cmd, cmd          # quoted: a home dir may contain a space
assert "~" not in cmd, cmd                # a quoted tilde is a literal directory
assert ".claude/skills" not in cmd, cmd
print("   ok: " + cmd)
PY

echo "== a second run refuses to overwrite"
"$VENV_PY" "$REPO/data-noodler/installer/bootstrap_config.py" \
  --home "$FAKE_HOME" | grep -q "left unchanged" \
  || { echo "FAIL: second run did not refuse"; exit 1; }
echo "   ok: refused to overwrite"

echo "== launch-analytics-mcp fails fatally with a config present but no credential"
# Asymmetric by design, and worth spelling out: launch-data-noodler's
# absent-credential path checked above is NOT fatal, because
# credential_status must stay callable so the model can explain the fix.
# launch-analytics-mcp execs the real upstream analytics-mcp server instead, which
# cannot do anything useful without a credential, so for launch-analytics-mcp an
# absent credential IS fatal. bootstrap_config.py above never ran consent in
# this fake home, so the config it just wrote already names an adc_file that
# does not exist -- exactly the case this exercises.
set +e
DATA_NOODLER_HOME="$FAKE_HOME/.config/data-noodler" \
  "$FAKE_HOME/.config/data-noodler/bin/launch-analytics-mcp" \
  >"$FAKE_HOME/out2" 2>"$FAKE_HOME/err2"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || {
  echo "FAIL: launch-analytics-mcp exited 0 with no credential"; exit 1; }
[ ! -s "$FAKE_HOME/out2" ] || {
  echo "FAIL: launch-analytics-mcp wrote to stdout"; exit 1; }
grep -q "data-noodler-setup" "$FAKE_HOME/err2" || {
  echo "FAIL: launch-analytics-mcp error does not name the setup skill"; exit 1; }
echo "   ok: exit=$CODE, stdout empty, stderr names the skill"

echo "== PASS: clean-home dry run"
