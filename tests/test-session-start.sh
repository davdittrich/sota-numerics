#!/usr/bin/env bash
# Stdlib-only smoke test (N5): no framework, no fixtures dir. Every config case
# runs against a scratch project dir under mktemp -d, with HOME and GSD_HOME
# redirected into it -- neither this repo's project config nor the developer's
# real ~/.gsd is written to (ponytail-everywhere precedent, review finding 2).
#
# The HOME redirect is load-bearing, not hygiene: session-start.sh:6 invokes
# capability-auto-install.sh, which on a clean published checkout writes the
# real ${GSD_HOME:-$HOME}/.gsd/capabilities/sota-numerics mirror and its hash
# sidecar. Running this suite must never perform a real global install
# (a suite that installs for real would mutate the developer's own machine).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/hooks/session-start.sh"
PLUGIN_DIR="$REPO_ROOT"

# Record and continue rather than exit, so one broken case does not mask the
# rest of the run. The two cd failures below stay fatal: they are the harness
# itself failing, not a case, and continuing would run the remaining cases in
# the wrong directory.
FAILURES=0
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }
pass() { echo "PASS: $1"; }

# Snapshot the real global GSD state before any redirect, so the last assertion
# can prove the suite did not touch it. Contents, not existence: the failure
# being guarded against is capability-auto-install.sh mirroring this worktree's
# uncommitted bundle over the developer's global copy, which overwrites the
# mirror's files and rewrites the sidecar without adding or removing either
# path. The digest is the one 23-01-PLAN.md quotes for this directory.
#
# Two walks, not one, because a leaked __pycache__ needs to move this digest
# and its own content churn must not (gsd-beads-25vc.21.3 item 2). The first
# walk lists every path -- directories included, names only -- so a new
# `__pycache__` directory or a new `.pyc` inside an existing one changes the
# digest. The second is the original content walk, still pruning
# `__pycache__` from hashing: a `.pyc` embeds its source's mtime, so a mirror
# merely re-read by python would churn the baseline and turn this containment
# check flaky-red for a reason that is not a leak. Names in, contents out: a
# leak that ADDS bytecode is now caught, a leak that rewrites an existing
# `.pyc` byte-for-byte in place is not, and that residual is recorded here
# rather than left implied. Every non-bytecode file in the mirror stays
# covered by content, as before.
if command -v sha256sum >/dev/null 2>&1; then HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then HASH_CMD=(shasum -a 256)
else echo "FAIL: no sha256 tool, so case5 could not tell whether the real mirror changed"; exit 1
fi
REAL_GSD="${GSD_HOME:-$HOME}/.gsd"
real_gsd_state() {
  ( cd "$REAL_GSD/capabilities/sota-numerics" 2>/dev/null && {
      find . -print | LC_ALL=C sort
      find . -name __pycache__ -prune -o -type f -print |
        LC_ALL=C sort | xargs "${HASH_CMD[@]}"
    } | "${HASH_CMD[@]}"
  ) 2>&1
  cat "$REAL_GSD/capability-auto-install-sota-numerics.hash" 2>&1
}
REAL_GSD_BEFORE="$(real_gsd_state)"
REAL_HOME="$HOME"

trap 'HOME="$REAL_HOME"; rm -rf "${SCRATCH:-}" "${STUB_DIR:-}" 2>/dev/null' EXIT

# session-start.sh reads config through gsd_tools, and hooks/gsd-tools.sh's last
# resolution rung is ${CLAUDE_CONFIG_DIR:-$HOME/.claude} -- which the HOME
# redirect above correctly hides, so without a stub every config case would
# silently fall back to the no-gsd-tools default. Ship the stub here rather than
# in ci.yml so a laptop and a runner exercise the same path. Rung 2
# (`command -v gsd-tools`) picks it up regardless of HOME.
STUB_DIR="$(mktemp -d)"
cat > "$STUB_DIR/gsd-tools" <<'STUB'
#!/usr/bin/env bash
set -u
[ "${1:-}" = "config-get" ] || { echo "gsd-tools stub: unsupported command '${1:-}'" >&2; exit 1; }
KEY="$2"; DEFAULT=""; shift 2
while [ $# -gt 0 ]; do case "$1" in --default) DEFAULT="${2:-}"; shift 2 ;; *) shift ;; esac; done
python3 - "$KEY" "$DEFAULT" <<'PY'
import json, sys
key, value = sys.argv[1], sys.argv[2]
try:
    with open(".planning/config.json") as fh:
        node = json.load(fh)
    for part in key.split("."):
        node = node[part]
    value = str(node).lower() if isinstance(node, bool) else str(node)
except Exception:
    pass
sys.stdout.write(value)
PY
STUB
chmod +x "$STUB_DIR/gsd-tools"
PATH="$STUB_DIR:$PATH"

# mk_scratch <config-json-body-or-empty>
# Creates a scratch project dir and cds into it. Sets SCRATCH and points HOME
# and GSD_HOME at a home inside it. Passing an empty string skips writing
# config.json entirely (case 1: no config present).
mk_scratch() {
  SCRATCH="$(mktemp -d)"
  local _pdir=".planning"
  local _cfg="config.json"
  mkdir -p "$SCRATCH/$_pdir" "$SCRATCH/home"
  # The HOME redirect is what holds the install back: hooks/gsd-tools.sh's
  # first rung now anchors to CLAUDE_PLUGIN_ROOT (every call site below sets
  # it explicitly) or, failing that, to the sourced file's own location --
  # never to the scratch dir this function cd's into (D-13). Only the last
  # rung, ${CLAUDE_CONFIG_DIR:-$HOME/.claude}, can still see this scratch
  # dir's cwd, and the HOME redirect covers that.
  export HOME="$SCRATCH/home" GSD_HOME="$SCRATCH/home"
  if [ -n "$1" ]; then
    printf '%s\n' "$1" > "$SCRATCH/$_pdir/$_cfg"
  fi
  cd "$SCRATCH" || { echo "FAIL: cd to scratch dir failed"; exit 1; }
}

run_and_cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null
  export HOME="$REAL_HOME"
  unset GSD_HOME GIT_CEILING_DIRECTORIES
  cd "$REPO_ROOT" || { echo "FAIL: cd back to repo root failed"; exit 1; }
}

# --- Case 1: no .planning/config.json present at all -> banner printed, exit 0 ---
# Absent configuration means enabled: a capability nobody has switched off is on,
# so a first run in a project that has never been configured still gets steered.
mk_scratch ""
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT")"
STATUS=$?
run_and_cleanup
echo "$OUT" | grep -q 'SOTA-NUMERICS' || fail "case1: banner missing with no config present"
[ "$STATUS" -eq 0 ] || fail "case1: exited non-zero with no config present"
pass "case1: no config present defaults to enabled"

# --- Case 2: sota-numerics.enabled=false -> empty stdout, exit 0 ---
mk_scratch '{"sota-numerics": {"enabled": false}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT")"
STATUS=$?
run_and_cleanup
[ -z "$OUT" ] || fail "case2: enabled=false produced output"
[ "$STATUS" -eq 0 ] || fail "case2: enabled=false exited non-zero"
pass "case2: sota-numerics.enabled=false silent exit 0"

# --- Case 3a: ROLE=planner -> planner framing, qualifies the blocking gate ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" planner)"
run_and_cleanup
echo "$OUT" | grep -q 'ranked criterion' || fail "case3a: planner framing line missing"
echo "$OUT" | grep -q 'blocking plan:post gate' || fail "case3a: planner banner does not qualify the blocking gate"
pass "case3a: ROLE=planner framing"

# --- Case 3b: ROLE=executor -> executor framing ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" executor)"
run_and_cleanup
echo "$OUT" | grep -q 'avoid cancellation' || fail "case3b: executor framing line missing"
pass "case3b: ROLE=executor framing"

# --- Case 3c: ROLE=verifier -> verifier framing ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" verifier)"
run_and_cleanup
echo "$OUT" | grep -q 'not blockers' || fail "case3c: verifier framing line missing"
pass "case3c: ROLE=verifier framing"

# --- Case 3d: bogus role argument -> generic framing ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" bogus-role)"
run_and_cleanup
echo "$OUT" | grep -q 'SOTA/efficiency/numerical-stability steering' || fail "case3d: bogus role did not fall back to generic framing"
pass "case3d: bogus role falls back to generic"

# --- Case 4: injection-shaped role argument -> falls through to generic, no side effect ---
# The payload target lives inside the per-run scratch dir, not at a fixed /tmp
# path: a fixed name in a world-writable shared namespace can be pre-created by
# another user, which turns this assertion into a false failure, or symlinked,
# which turns a passing run into a write somewhere else.
mk_scratch '{"sota-numerics": {"enabled": true}}'
PWNED="$SCRATCH/pwned"
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" "x; touch $PWNED")"
[ -e "$PWNED" ] && PWNED_CREATED=yes || PWNED_CREATED=no
run_and_cleanup
echo "$OUT" | grep -q 'SOTA/efficiency/numerical-stability steering' || fail "case4: injection payload did not fall back to generic framing"
[ "$PWNED_CREATED" = no ] || fail "case4: injection payload created $PWNED"
pass "case4: role-argument injection guarded"

# --- Case 6: a hostile repository at the working directory never supplies
# the node entry point (D-13, T-24-17) ---
# hooks/gsd-tools.sh's first rung used to run `git rev-parse --show-toplevel`
# at the caller's cwd; a hostile repository placed there, carrying its own
# gsd-core/bin/gsd-tools.cjs, would win that rung and get sourced as node
# code. The rung is gone now: the anchor is CLAUDE_PLUGIN_ROOT, or the
# sourced file's own location when that is unset -- neither is something a
# working directory can influence. Prove it with a repository that IS a real
# git repo (so it would have won the old rung) and carries a script that
# leaves evidence if node ever runs it.
HOSTILE="$(mktemp -d)"
mkdir -p "$HOSTILE/gsd-core/bin"
CANARY="$HOSTILE/canary"
cat > "$HOSTILE/gsd-core/bin/gsd-tools.cjs" <<CJS
require('fs').writeFileSync('$CANARY', 'pwned');
CJS
git init -q "$HOSTILE" >/dev/null 2>&1

FAKE_HOME6="$(mktemp -d)"
OUT6="$(
  cd "$HOSTILE" && HOME="$FAKE_HOME6" bash -c '
    unset CLAUDE_PLUGIN_ROOT
    . "'"$REPO_ROOT"'/hooks/gsd-tools.sh"
    gsd_tools config-get sota-numerics.enabled --default true
  '
)"
rm -rf "$FAKE_HOME6"
if [ -e "$CANARY" ]; then
  fail "case6: hostile repository's gsd-core/bin/gsd-tools.cjs was executed"
else
  pass "case6: hostile repository's node entry point never runs, even though it is a real git repository"
fi
[ "$OUT6" = "true" ] || fail "case6: legitimate resolution (PATH) still did not succeed despite the hostile cwd (got '$OUT6')"
rm -rf "$HOSTILE"

# --- Case 7: an unresolvable provider still exits 127 (T-24-21) ---
# Removing the working-directory rung must not change what happens when NO
# rung resolves: the fix must not silently disable the hook path it touches.
EMPTY_CWD="$(mktemp -d)"
FAKE_HOME7="$(mktemp -d)"
bash -c '
  cd "'"$EMPTY_CWD"'" || exit 99
  export HOME="'"$FAKE_HOME7"'"
  export PATH="/usr/bin:/bin"
  unset CLAUDE_PLUGIN_ROOT
  . "'"$REPO_ROOT"'/hooks/gsd-tools.sh"
  gsd_tools config-get x --default y
'
STATUS7=$?
rm -rf "$EMPTY_CWD" "$FAKE_HOME7"
[ "$STATUS7" -eq 127 ] || fail "case7: an unresolvable provider did not exit 127 (got $STATUS7)"
pass "case7: an unresolvable provider still exits 127"

# --- Case 5: the suite itself performed no real global install ---
[ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ] ||
  fail "case5: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
pass "case5: real GSD_HOME untouched by the suite"

[ "$FAILURES" -eq 0 ] || { echo "$FAILURES FAILED"; exit 1; }
echo "ALL PASS"
exit 0
