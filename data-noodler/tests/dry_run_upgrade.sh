#!/usr/bin/env bash
# Rehearse a real upgrade end to end in a throwaway home (#164, #2108).
#
# Builds an install from an older release of this repository -- a venv on the
# pins that release's own installer/constraints.txt names, with its payload
# and its Claude Code registration -- then runs this package's upgrade.py for
# real, with real downloads, and checks the result: the venv is on the new
# pins with nothing below its security floors, both servers verify, the
# user's other MCP server survives, the old venv is left in place (only the
# user removes it), and the agent's skill step refreshes the skills
# afterwards.
#
# Needs network, a Python 3.10 or later, and the repository's history (a
# checkout of one commit holds no older release to build). Slow: a few
# minutes. Outside the unit suite; part of the release gate.
#
#   bash data-noodler/tests/dry_run_upgrade.sh [old-commit]
#   INTERRUPT=INT  bash data-noodler/tests/dry_run_upgrade.sh
#       a real Ctrl-C (SIGINT to the process group) while pip is installing:
#       the run must undo itself and the old install must verify
#   INTERRUPT=KILL bash data-noodler/tests/dry_run_upgrade.sh
#       SIGKILL instead -- nothing in-process can run -- then
#       `upgrade.py --recover` must put the old install back
#
# READING THE RESULT
# The last line of output is always "PASS: ..." or "FAIL: ...", and the exit
# status is 0 for a pass alone. A pipeline reports the status of its LAST
# command, so `dry_run_upgrade.sh | tail` exits 0 whatever happened here.
# Take the exit status from the script itself:
#
#   bash data-noodler/tests/dry_run_upgrade.sh; echo "exit status: $?"
#
# and to keep only the end of a long run, send the output to a file first:
#
#   bash data-noodler/tests/dry_run_upgrade.sh > rehearsal.log 2>&1
#   echo "exit status: $?"; tail -20 rehearsal.log
#
# THE BASE PYTHON
# The one named in BASE_PYTHON, or else the first Python 3.10 or later found
# by version name on PATH, in Homebrew's folders and among the Pythons uv
# manages -- 3.12 first, the version constraints.txt was captured on. The
# run prints which one it chose.
#
# The functions this uses are in dry_run_lib.sh, and test_dry_run_upgrade.py
# checks them in the unit suite, where nothing is installed.
set -euo pipefail

case "$0" in
  */*) HERE=$(cd "${0%/*}" && pwd) ;;
  *) HERE=$(pwd) ;;
esac
REPO=$(cd "$HERE/../.." && pwd)
. "$HERE/dry_run_lib.sh"
trap finish EXIT

# The old release when none is named: plugin 0.9.0 (2026-11-19), the first
# with today's folder, install home and server names. Its pins equal today's
# (they were refreshed just before it), so from here the rehearsal exercises
# the swap itself: a fresh venv, pip by URL and hash, the payload, the
# registration. Any later commit can be named instead. Earlier commits
# install under names this package has retired and this script no longer
# builds them; test_home_migration.py and test_one_name.py cover upgrading
# those.
OLD_COMMIT=${1:-7b48865c82c14698c6cc1f530eaddfe6e1efdeb4}

case "${INTERRUPT:-}" in
  "" | INT | KILL) ;;
  *) fail "INTERRUPT must be INT or KILL, and it is '$INTERRUPT'" ;;
esac

step "0. a base Python, and the old commit"
if ! PY=$(find_base_python); then
  NAMED=${BASE_PYTHON:-${PY312:-}}
  if [ -n "$NAMED" ]; then
    fail "$NAMED did not run as Python 3.10 or later; set BASE_PYTHON to one that does"
  fi
  fail "found no Python 3.10 or later on PATH, in Homebrew's folders or among uv's; set BASE_PYTHON to one"
fi
echo "   base python: $PY (Python $(python_version "$PY"))"
if ! OLD=$(resolve_commit "$REPO" "$OLD_COMMIT"); then
  if is_shallow "$REPO"; then
    fail "old commit '$OLD_COMMIT' is missing from this checkout, which holds one commit and no history; run 'git fetch --unshallow' first"
  fi
  fail "old commit '$OLD_COMMIT' is not a commit in this repository"
fi
commit_has_package "$REPO" "$OLD" \
  || fail "old commit '$OLD_COMMIT' has no data-noodler/installer/constraints.txt; name one from plugin 0.9.0 on (see the top of this script)"
echo "   old commit:  $OLD"

T=$(mktemp -d)
REHEARSAL_TMP=$T
H="$T/home"
GA="$H/.config/data-noodler"
mkdir -p "$H/.claude" "$H/.config/gcloud" "$H/Documents/analyst-sessions" "$T/old"
export HOME="$H"
unset DATA_NOODLER_HOME DATA_NOODLER_CONFIG

step "1. the old install ($OLD_COMMIT)"
git -C "$REPO" archive "$OLD" data-noodler | tar -x -C "$T/old"
# The old release's own pins, top-level requirement included: its
# constraints.txt names the analytics-mcp it was captured with.
OLD_REQUIREMENT=$(pinned_requirement "$T/old/data-noodler/installer/constraints.txt" analytics-mcp) \
  || fail "the old commit's constraints.txt pins no analytics-mcp"
echo "   old pins:    $OLD_REQUIREMENT, under that commit's constraints.txt"
"$PY" -m venv "$GA/venv"
"$GA/venv/bin/python" -m pip install -q --disable-pip-version-check \
  -c "$T/old/data-noodler/installer/constraints.txt" \
  "$OLD_REQUIREMENT" google-auth-oauthlib
echo '{}' > "$H/.config/gcloud/data-noodler-credential.json"
cat > "$GA/config.json" <<EOF
{"oauth_client_file": "$H/.config/gcloud/data-noodler-client.json",
 "adc_file": "$H/.config/gcloud/data-noodler-credential.json",
 "venv_python": "$GA/venv/bin/python",
 "analytics_mcp_bin": "$GA/venv/bin/analytics-mcp",
 "properties_csv": "$GA/properties.csv",
 "sessions_root": "$H/Documents/analyst-sessions"}
EOF
echo '{"mcpServers": {"someone-else": {"command": "/nonexistent/server"}}}' > "$H/.claude.json"
chmod 600 "$H/.claude.json"
"$GA/venv/bin/python" "$T/old/data-noodler/installer/install.py" \
  --repo-root "$T/old" --home "$GA" --targets claude_code >/dev/null
BEFORE=$("$GA/venv/bin/python" -c "import importlib.metadata as m; print(m.version('mcp'), m.version('analytics-mcp'), m.version('pip'))")
echo "   before: mcp/analytics-mcp/pip = $BEFORE"

if [ -n "${INTERRUPT:-}" ]; then
  step "2. upgrade.py, sent SIG$INTERRUPT during the package install"
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
         repo, "--home", ga, "--targets", "claude_code"],
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
  sed 's/^/   | /' "$OUT"
  if [ "$INTERRUPT" = "KILL" ]; then
    [ -f "$GA/.upgrade-in-progress.json" ] || fail "no record left for --recover"
    echo "   killed; running --recover"
    "$PY" "$REPO/data-noodler/installer/upgrade.py" --home "$GA" --recover || fail "--recover failed"
    if [ -f "$GA/.upgrade-in-progress.json" ]; then
      fail "record still there after recover"
    fi
  else
    grep -q "INTERRUPTED" "$OUT" || fail "no interruption reported"
    if grep -q "MOST of it" "$OUT"; then
      fail "the rollback was incomplete"
    fi
  fi
  AFTER=$("$GA/venv/bin/python" -c "import importlib.metadata as m; print(m.version('mcp'), m.version('analytics-mcp'), m.version('pip'))")
  [ "$AFTER" = "$BEFORE" ] || fail "venv not restored: $AFTER (was $BEFORE)"
  if ls -d "$GA"/venv.old-* >/dev/null 2>&1; then
    fail "the old venv is still aside"
  fi
  # The restored install is the OLD release (15 data-noodler tools too).
  "$GA/venv/bin/python" "$REPO/data-noodler/installer/verify.py" --config "$H/.claude.json" \
    --require analytics-mcp=10 --require data-noodler=15 || fail "the restored install does not verify"
  passed "SIG$INTERRUPT upgrade restored ($BEFORE)"
  exit 0
fi

step "2. upgrade.py --plan, then the run, for real"
"$PY" "$REPO/data-noodler/installer/upgrade.py" --repo-root "$REPO" \
  --home "$GA" --targets claude_code --plan
"$PY" "$REPO/data-noodler/installer/upgrade.py" --repo-root "$REPO" \
  --home "$GA" --targets claude_code
step "2b. the agent's step afterwards: skills"
"$GA/venv/bin/python" "$REPO/data-noodler/installer/copy_skills.py" \
  --home "$GA" --dist "$REPO/data-noodler" --skills-dir "$H/.claude/skills"

step "3. checks"
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
[ -f "$H/.claude/skills/data-noodler/.data-noodler-installed" ] || fail "skills not installed with their marker"
grep -q OTEL_PROPAGATORS "$H/.claude.json" || fail "entries lack OTEL_PROPAGATORS"
passed "upgrade rehearsal ($OLD_COMMIT -> working tree)"
