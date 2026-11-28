# Shell functions for tests/dry_run_upgrade.sh, kept apart so the suite can
# check them without installing anything (tests/test_dry_run_upgrade.py).
# The script and the tests source this file.
#
# Every function gives its answer on stdout and its verdict as its exit
# status, and stays silent otherwise: the script words the failure, so the
# reason can be the last line of output. bash switches `set -e` off inside
# $( ), so each function returns its failures explicitly.

# --- a base Python ----------------------------------------------------------
# The rehearsal makes the old venv from this Python and then runs upgrade.py
# with it, as the base Python. So it must be one upgrade.py's pre-flight
# accepts: an interpreter that runs and reports 3.10 or later. The two
# functions below ask the pre-flight's own question and read the answer the
# way it does; test_dry_run_upgrade.py holds them to upgrade.preflight.

# "3.12" for an interpreter, from the last line it prints.
python_version() (
  out=$("$1" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>&1) \
    || exit 1
  printf '%s\n' "${out##*
}"
)

usable_base_python() (
  [ -n "$1" ] && [ -x "$1" ] || exit 1
  # On a Mac without Apple's developer tools this one is a stub that opens
  # an install dialog instead of running (the setup skill's Step 4).
  if [ "$1" = /usr/bin/python3 ] && [ -x /usr/bin/xcode-select ] \
      && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    exit 1
  fi
  version=$(python_version "$1") || exit 1
  # Numbers and dots only, as int() would insist.
  case "$version" in
    "" | *[!0-9.]* | .* | *. | *..*) exit 1 ;;
  esac
  major=${version%%.*}
  if [ "$major" -gt 3 ]; then exit 0; fi
  if [ "$major" -lt 3 ]; then exit 1; fi
  case "$version" in
    *.*) ;;
    *) exit 1 ;;
  esac
  rest=${version#*.}
  [ "${rest%%.*}" -ge 10 ]
)

# Every place a base Python may be, one per line, best first.
#
# By version name before plain python3, as upgrade.py looks beside a venv:
# Homebrew's folder holds python3.14 and no python3. 3.12 first, because
# installer/constraints.txt was captured on it, then 3.14, the other version
# it has been run on. For each name: PATH, then the folders in
# DRY_RUN_PYTHON_DIRS (Homebrew's two, unless set), then the Pythons uv
# manages.
base_python_candidates() (
  dirs=${DRY_RUN_PYTHON_DIRS-/opt/homebrew/bin:/usr/local/bin}
  for minor in 12 14 13 11 10; do
    name=python3.$minor
    if found=$(command -v "$name" 2>/dev/null); then printf '%s\n' "$found"; fi
    (
      IFS=:
      for dir in $dirs; do
        printf '%s\n' "$dir/$name"
      done
    )
    for managed in \
        "$HOME"/.local/share/uv/python/cpython-3."$minor".*/bin/"$name"; do
      if [ -x "$managed" ]; then printf '%s\n' "$managed"; fi
    done
  done
  for name in python3 python; do
    if found=$(command -v "$name" 2>/dev/null); then printf '%s\n' "$found"; fi
  done
  exit 0
)

# The Python to rehearse with. One named in BASE_PYTHON (or PY312, the
# variable's earlier name) is used as given, and an unusable one fails the
# search: choosing another quietly would hide the mistake.
find_base_python() (
  given=${BASE_PYTHON:-${PY312:-}}
  if [ -n "$given" ]; then
    usable_base_python "$given" || exit 1
    printf '%s\n' "$given"
    exit 0
  fi
  candidates=$(base_python_candidates)
  # One candidate per line, taken whole: split on newlines alone, and leave
  # any * in a path as it is.
  IFS='
'
  set -f
  for candidate in $candidates; do
    if usable_base_python "$candidate"; then
      printf '%s\n' "$candidate"
      exit 0
    fi
  done
  exit 1
)

# --- the old commit ---------------------------------------------------------

# The full hash of a commit that is in the repository at $1.
resolve_commit() (
  case "$2" in
    "" | -*) exit 1 ;;
  esac
  git -C "$1" rev-parse --verify --quiet "$2^{commit}" 2>/dev/null || exit 1
)

# A copy of one commit only has no history to rehearse from.
is_shallow() {
  [ "$(git -C "$1" rev-parse --is-shallow-repository 2>/dev/null)" = true ]
}

# Whether commit $2 holds the package under the folder name it has today.
commit_has_package() {
  git -C "$1" cat-file -e "$2:data-noodler/installer/constraints.txt" \
    2>/dev/null
}

# "analytics-mcp==1.1.0": the pin constraints file $1 holds for package $2.
pinned_requirement() (
  [ -f "$1" ] || exit 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$2"==?*)
        printf '%s\n' "${line%%[!A-Za-z0-9=._+!-]*}"
        exit 0
        ;;
    esac
  done < "$1"
  exit 1
)

# --- the verdict ------------------------------------------------------------
# With `trap finish EXIT` the last line of output is always "PASS: ..." or
# "FAIL: ...", and the exit status always agrees with it. A pass has to be
# declared, at the end: leaving early with status 0 is a failure.

REHEARSAL_STEP="starting"
REHEARSAL_PASSED=""
REHEARSAL_FAILURE=""
REHEARSAL_TMP=""

step() {
  REHEARSAL_STEP=$*
  echo "== $*"
}

fail() {
  REHEARSAL_FAILURE=$*
  exit 1
}

passed() {
  REHEARSAL_PASSED=$*
}

finish() {
  status=$?
  trap - EXIT
  if [ -n "$REHEARSAL_TMP" ]; then
    rm -rf "$REHEARSAL_TMP"
  fi
  if [ "$status" -eq 0 ] && [ -n "$REHEARSAL_PASSED" ]; then
    echo "PASS: $REHEARSAL_PASSED"
    exit 0
  fi
  if [ "$status" -eq 0 ]; then
    status=1
  fi
  if [ -z "$REHEARSAL_FAILURE" ]; then
    REHEARSAL_FAILURE="step \"$REHEARSAL_STEP\" did not finish"
  fi
  echo "FAIL: $REHEARSAL_FAILURE (exit status $status)"
  exit "$status"
}
