#!/bin/sh
# Rehearse a real upgrade end to end in a throwaway home (#164).
#
# Builds the install a partner has today -- a venv from the 2026-10-23 pins
# (analytics-mcp 0.7.0 on mcp 1.x), the payload and Claude Code registration
# from that release -- then runs this package's upgrade.py for real, with
# real downloads, and checks the result: the venv is on the new pins with
# nothing below its security floors, both servers verify, the user's other
# MCP server survives, the old venv is left in place (only the user removes
# it), and the agent's skill step refreshes the skills afterwards.
#
# Needs network and a Python 3.12 (uv's is found automatically). Slow: a few
# minutes. Not part of the unit suite; part of the release gate.
#
#   sh data-noodler/tests/dry_run_upgrade.sh [old-commit]
#   INTERRUPT=INT  sh data-noodler/tests/dry_run_upgrade.sh
#       a real Ctrl-C (SIGINT to the process group) while pip is installing:
#       the run must undo itself and the old install must verify
#   INTERRUPT=KILL sh data-noodler/tests/dry_run_upgrade.sh
#       SIGKILL instead -- nothing in-process can run -- then
#       `upgrade.py --recover` must put the old install back
set -eu

REPO=$(cd "$(dirname "$0")/../.." && pwd)
OLD_COMMIT=${1:-be5bc78}
PY=${PY312:-$(ls "$HOME"/.local/share/uv/python/cpython-3.12.*/bin/python3.12 2>/dev/null | tail -1)}
[ -x "$PY" ] || { echo "need a Python 3.12 (set PY312)" >&2; exit 2; }

T=$(mktemp -d)
H="$T/home"
GA="$H/.config/ga-mcp"
mkdir -p "$H/.claude" "$H/.config/gcloud" "$H/Documents/analyst-sessions" "$T/old"
trap 'rm -rf "$T"' EXIT
export HOME="$H"
unset GA_HOME GA_MCP_CONFIG || true

echo "== 1. the install a partner has today ($OLD_COMMIT)"
git -C "$REPO" archive "$OLD_COMMIT" data-noodler | tar -x -C "$T/old"
"$PY" -m venv "$GA/venv"
"$GA/venv/bin/python" -m pip install -q --disable-pip-version-check \
  -c "$T/old/data-noodler/installer/constraints.txt" \
  analytics-mcp==0.7.0 google-auth-oauthlib
echo '{}' > "$H/.config/gcloud/adc-ga-personal.json"
cat > "$GA/config.json" <<EOF
{"oauth_client_file": "$H/.config/gcloud/ga-mcp-client.json",
 "adc_file": "$H/.config/gcloud/adc-ga-personal.json",
 "venv_python": "$GA/venv/bin/python",
 "analytics_mcp_bin": "$GA/venv/bin/analytics-mcp",
 "properties_csv": "$GA/properties.csv",
 "sessions_root": "$H/Documents/analyst-sessions"}
EOF
echo '{"mcpServers": {"someone-else": {"command": "/nonexistent/server"}}}' > "$H/.claude.json"
chmod 600 "$H/.claude.json"
"$GA/venv/bin/python" "$T/old/data-noodler/installer/install.py" \
  --repo-root "$T/old" --ga-home "$GA" --targets claude_code >/dev/null
BEFORE=$("$GA/venv/bin/python" -c "import importlib.metadata as m; print(m.version('mcp'), m.version('analytics-mcp'), m.version('pip'))")
echo "   before: mcp/analytics-mcp/pip = $BEFORE"

if [ -n "${INTERRUPT:-}" ]; then
  echo "== 2. upgrade.py, sent SIG$INTERRUPT during the package install"
  OUT="$T/upgrade.out"
  # Like Ctrl-C at a terminal: SIGINT to the whole foreground process group
  # (upgrade.py and the pip it is running), with SIGINT at its default --
  # a shell background job would start with it ignored.
  "$PY" - "$PY" "$REPO" "$GA" "$OUT" "$INTERRUPT" <<'DRIVER'
import os, signal, subprocess, sys, time
py, repo, ga, out, which = sys.argv[1:6]
with open(out, "w") as log:
    p = subprocess.Popen(
        [py, "-u", f"{repo}/data-noodler/installer/upgrade.py", "--repo-root",
         repo, "--ga-home", ga, "--targets", "claude_code"],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    deadline = time.time() + 120
    while time.time() < deadline:
        if "Installing the pinned packages" in open(out).read():
            break
        time.sleep(0.2)
    time.sleep(2)
    os.killpg(p.pid, getattr(signal, "SIG" + which))
    p.wait(timeout=300)
DRIVER
  grep -E "INTERRUPTED|Restored|MOST of it" "$OUT" || true
  fail() { echo "FAIL: $*" >&2; exit 1; }
  if [ "$INTERRUPT" = "KILL" ]; then
    [ -f "$GA/.upgrade-in-progress.json" ] || fail "no record left for --recover"
    echo "   killed; running --recover"
    "$PY" "$REPO/data-noodler/installer/upgrade.py" --ga-home "$GA" --recover || fail "--recover failed"
    [ -f "$GA/.upgrade-in-progress.json" ] && fail "record still there after recover"
  else
    grep -q "INTERRUPTED" "$OUT" || fail "no interruption reported"
    grep -q "MOST of it" "$OUT" && fail "the rollback was incomplete"
  fi
  AFTER=$("$GA/venv/bin/python" -c "import importlib.metadata as m; print(m.version('mcp'), m.version('analytics-mcp'), m.version('pip'))")
  [ "$AFTER" = "$BEFORE" ] || fail "venv not restored: $AFTER (was $BEFORE)"
  ls -d "$GA"/venv.old-* >/dev/null 2>&1 && fail "the old venv is still aside"
  # The restored install is the OLD release (15 data-noodler tools too).
  "$GA/venv/bin/python" "$REPO/data-noodler/installer/verify.py" --config "$H/.claude.json" \
    --require analytics-mcp=10 --require data-noodler=15 || fail "the restored install does not verify"
  echo "== PASS: SIG$INTERRUPT upgrade restored ($BEFORE)"
  exit 0
fi

echo "== 2. upgrade.py --plan, then the run, for real"
"$PY" "$REPO/data-noodler/installer/upgrade.py" --repo-root "$REPO" \
  --ga-home "$GA" --targets claude_code --plan
"$PY" "$REPO/data-noodler/installer/upgrade.py" --repo-root "$REPO" \
  --ga-home "$GA" --targets claude_code
echo "== 2b. the agent's step afterwards: skills"
"$GA/venv/bin/python" "$REPO/data-noodler/installer/copy_skills.py" \
  --ga-home "$GA" --dist "$REPO/data-noodler" --skills-dir "$H/.claude/skills"

echo "== 3. checks"
fail() { echo "FAIL: $*" >&2; exit 1; }
AFTER=$("$GA/venv/bin/python" -c "import importlib.metadata as m; print(m.version('mcp'), m.version('analytics-mcp'), m.version('pip'))")
echo "   after:  mcp/analytics-mcp/pip = $AFTER"
case "$AFTER" in "2."*" 1.1.0 26.2.2") ;; *) fail "unexpected versions: $AFTER" ;; esac
BELOW=$("$PY" -c "
import sys; sys.path.insert(0, '$REPO/data-noodler/installer'); import probe
print(probe.probe_dependencies('$GA/venv/bin/python')['below_floor'])")
[ "$BELOW" = "{}" ] || fail "below floor: $BELOW"
"$GA/venv/bin/python" "$REPO/data-noodler/installer/verify.py" --config "$H/.claude.json" \
  --require analytics-mcp=10 --require data-noodler=15 || fail "verify"
grep -q someone-else "$H/.claude.json" || fail "the user's other server was lost"
[ "$(stat -f %Lp "$H/.claude.json" 2>/dev/null || stat -c %a "$H/.claude.json")" = 600 ] || fail ".claude.json permissions changed"
ls -d "$GA"/venv.old-* >/dev/null 2>&1 || fail "the old venv was removed -- only the user may"
[ -f "$H/.claude/skills/data-noodler/.ga-mcp-installed" ] || fail "skills not installed with their marker"
grep -q OTEL_PROPAGATORS "$H/.claude.json" || fail "entries lack OTEL_PROPAGATORS"
echo "== PASS: upgrade rehearsal ($OLD_COMMIT -> working tree)"
