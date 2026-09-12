#!/usr/bin/env bash
# Self-check for .githooks/pre-commit.
#
# WHY THIS EXISTS. The hook is the compensating control for GitHub Advanced
# Security being unavailable (ADR-0004), and for a while it did not work. It
# read "$LOCALAPPDATA/..." unguarded under `set -u`, so on any machine without
# that variable it aborted before scanning anything; and when gitleaks was
# merely absent it printed a yellow WARNING and let the commit through. Both
# failures are invisible in normal use - the commit succeeds either way - so
# the control could be absent for months with nobody noticing.
#
# A control nobody tests is a control nobody has. Run:
#     bash scripts/test-pre-commit-hook.sh
#
# Each case builds a throwaway git repository in a temp directory, stages
# content into it, and runs the REAL hook from .githooks/pre-commit against a
# controlled environment. Nothing here touches the working repository.

set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/.githooks/pre-commit"
[ -f "$HOOK" ] || { echo "cannot find the hook at $HOOK"; exit 1; }

pass=0; failed=0; skipped=0

ok()   { echo "  PASS  $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; failed=$((failed+1)); }
skip() { echo "  SKIP  $1"; skipped=$((skipped+1)); }

# A scratch repo on a branch that is not main, with the config the hook reads.
new_repo() {
  local dir
  dir=$(mktemp -d)
  git -C "$dir" init -q
  git -C "$dir" config user.email t@example.test
  git -C "$dir" config user.name Test
  git -C "$dir" checkout -q -b feat/test-branch
  : > "$dir/.gitleaks.toml"
  # An initial commit, so HEAD is BORN. Without one, the hook's
  # `git rev-parse --abbrev-ref HEAD` fails, its `|| echo ""` yields an empty
  # branch name, and the "never commit to main" check silently matches
  # nothing - which is how a green suite can be testing a control that is not
  # running at all.
  git -C "$dir" commit -q --allow-empty -m "root"
  echo "$dir"
}

# The real PATH minus any directory that holds a gitleaks.
#
# Emptying PATH outright is the obvious move and it is wrong: the hook itself
# needs git, grep and sed, so a bare PATH makes every case fail at exec and
# the suite reports a broken hook it never actually ran. Removing only the
# directories that contain a gitleaks keeps the hook working while making
# `command -v gitleaks` genuinely find nothing - which is the condition under
# test.
path_without_gitleaks() {
  local out="" d
  local IFS=:
  for d in $PATH; do
    [ -n "$d" ] || continue
    if [ -x "$d/gitleaks" ] || [ -x "$d/gitleaks.exe" ]; then continue; fi
    out="${out:+$out:}$d"
  done
  printf '%s' "$out"
}

# Run the hook inside $1 with no gitleaks reachable by any of the paths the
# hook searches: none on PATH, and HOME/LOCALAPPDATA pointed at empty temp
# dirs. Extra NAME=value arguments are exported for the run.
run_hook() {
  local dir="$1"; shift
  local empty
  empty=$(mktemp -d)
  ( cd "$dir" && env "PATH=$(path_without_gitleaks)" "HOME=$empty" \
      "LOCALAPPDATA=$empty" "$@" bash "$HOOK" 2>&1 )
}

# A stand-in gitleaks that exits with the code we want to observe.
stub_gitleaks() {
  printf '#!/usr/bin/env bash\nexit %s\n' "$2" > "$1"
  chmod +x "$1"
}

echo "Testing $HOOK"

# ---------------------------------------------------------------------------
# 1. FAILS CLOSED: gitleaks cannot be found -> the commit is BLOCKED.
# ---------------------------------------------------------------------------
# This is the regression that matters most. The old hook printed a WARNING
# here and exited 0.
if [ -x /usr/local/bin/gitleaks ] || [ -x /opt/homebrew/bin/gitleaks ]; then
  # The hook checks those absolute paths on purpose, and this script will not
  # move a real binary to make an assertion convenient. Reported rather than
  # quietly passed: a skipped test that looks green is the same class of
  # defect as the warning this whole file exists because of.
  skip "missing gitleaks blocks (a real gitleaks sits at an absolute fallback path)"
else
  repo=$(new_repo)
  echo hello > "$repo/a.txt"
  git -C "$repo" add a.txt
  out=$(run_hook "$repo" "GITLEAKS_PATH=/nonexistent/gitleaks"); rc=$?
  if [ "$rc" -eq 0 ]; then
    bad "missing gitleaks must BLOCK, but the hook exited 0 (failing open)"
  elif ! printf '%s' "$out" | grep -q "BLOCKED: gitleaks not found"; then
    bad "missing gitleaks blocked without the expected message: $out"
  elif ! printf '%s' "$out" | grep -q -- "--no-verify"; then
    bad "the block message must name --no-verify as the audited bypass"
  elif ! printf '%s' "$out" | grep -q "install-git-hooks.sh"; then
    bad "the block message must say how to install gitleaks"
  else
    ok "missing gitleaks BLOCKS, and says how to install and how to bypass"
  fi
  rm -rf "$repo"
fi

# ---------------------------------------------------------------------------
# 2. No unbound-variable abort when LOCALAPPDATA is unset.
# ---------------------------------------------------------------------------
# `set -u` plus a bare "$LOCALAPPDATA" aborted the hook on every machine that
# does not export it. The hook must reach its own checks and report them
# rather than die in the resolution step.
repo=$(new_repo)
echo hello > "$repo/a.txt"
git -C "$repo" add a.txt
empty=$(mktemp -d)
stub_gitleaks "$empty/gitleaks" 0
out=$( cd "$repo" && env -u LOCALAPPDATA \
        "PATH=$empty:$(path_without_gitleaks)" "HOME=$empty" \
        bash "$HOOK" 2>&1 ); rc=$?
if printf '%s' "$out" | grep -qi "unbound variable"; then
  bad "the hook aborted on an unset variable: $out"
elif [ "$rc" -ne 0 ]; then
  bad "clean content with a working gitleaks should pass, got rc=$rc: $out"
else
  ok "an unset LOCALAPPDATA does not abort the hook"
fi
rm -rf "$repo" "$empty"

# ---------------------------------------------------------------------------
# 3. GITLEAKS_PATH is honoured, and a clean scan passes.
# ---------------------------------------------------------------------------
repo=$(new_repo)
echo hello > "$repo/a.txt"
git -C "$repo" add a.txt
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 0
out=$(run_hook "$repo" "GITLEAKS_PATH=$bin/gitleaks"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "pre-commit checks passed"; then
  ok "an explicit GITLEAKS_PATH is used and clean content passes"
else
  bad "clean content with an explicit GITLEAKS_PATH should pass, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

# ---------------------------------------------------------------------------
# 4. gitleaks on PATH is found when GITLEAKS_PATH is unset.
# ---------------------------------------------------------------------------
repo=$(new_repo)
echo hello > "$repo/a.txt"
git -C "$repo" add a.txt
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 0
out=$( cd "$repo" && env "PATH=$bin:/usr/bin:/bin" "HOME=$bin" \
        "LOCALAPPDATA=$bin" bash "$HOOK" 2>&1 ); rc=$?
if [ "$rc" -eq 0 ]; then
  ok "a gitleaks on PATH is resolved without GITLEAKS_PATH"
else
  bad "a gitleaks on PATH should be resolved, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

# ---------------------------------------------------------------------------
# 5. A secret found by gitleaks BLOCKS.
# ---------------------------------------------------------------------------
repo=$(new_repo)
echo hello > "$repo/a.txt"
git -C "$repo" add a.txt
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 1
out=$(run_hook "$repo" "GITLEAKS_PATH=$bin/gitleaks"); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "found a secret"; then
  ok "a non-zero gitleaks exit BLOCKS the commit"
else
  bad "a gitleaks failure should block, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

# ---------------------------------------------------------------------------
# 6. The other controls still work: forbidden file types, .env, and main.
# ---------------------------------------------------------------------------
repo=$(new_repo)
printf 'PDF-1.4\n' > "$repo/client.pdf"
git -C "$repo" add client.pdf
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 0
out=$(run_hook "$repo" "GITLEAKS_PATH=$bin/gitleaks"); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "forbidden file type"; then
  ok "a staged PDF still BLOCKS"
else
  bad "a staged PDF should block, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

repo=$(new_repo)
echo "SECRET=x" > "$repo/.env"
git -C "$repo" add -f .env
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 0
out=$(run_hook "$repo" "GITLEAKS_PATH=$bin/gitleaks"); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "env file staged"; then
  ok "a staged .env still BLOCKS"
else
  bad "a staged .env should block, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

repo=$(new_repo)
git -C "$repo" checkout -q -b main
echo hello > "$repo/a.txt"
git -C "$repo" add a.txt
bin=$(mktemp -d); stub_gitleaks "$bin/gitleaks" 0
out=$(run_hook "$repo" "GITLEAKS_PATH=$bin/gitleaks"); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "direct commit to main"; then
  ok "a commit on main still BLOCKS"
else
  bad "a commit on main should block, got rc=$rc: $out"
fi
rm -rf "$repo" "$bin"

echo ""
echo "$pass passed, $failed failed, $skipped skipped"
[ "$failed" -eq 0 ] || exit 1
