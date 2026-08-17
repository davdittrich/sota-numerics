#!/usr/bin/env bash
# Stdlib-only smoke test (N5): no framework, no fixtures dir. Every config case
# runs against a scratch project dir under mktemp -d -- this repo's own
# project config is never written to (ponytail-everywhere precedent, review
# finding 2).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/hooks/session-start.sh"
PLUGIN_DIR="$REPO_ROOT"

fail() { echo "FAIL: $1"; exit 1; }
pass() { echo "PASS: $1"; }

trap '[ -n "${SCRATCH:-}" ] && rm -rf "$SCRATCH" 2>/dev/null' EXIT

# mk_scratch <config-json-body-or-empty>
# Creates a scratch project dir and cds into it. Sets SCRATCH. Passing an
# empty string skips writing config.json entirely (case 1: no config present).
mk_scratch() {
  SCRATCH="$(mktemp -d)"
  local _pdir=".planning"
  local _cfg="config.json"
  mkdir -p "$SCRATCH/$_pdir"
  if [ -n "$1" ]; then
    printf '%s\n' "$1" > "$SCRATCH/$_pdir/$_cfg"
  fi
  cd "$SCRATCH" || { echo "FAIL: cd to scratch dir failed"; exit 1; }
}

run_and_cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null
  cd "$REPO_ROOT" || { echo "FAIL: cd back to repo root failed"; exit 1; }
}

# --- Case 1: no .planning/config.json present at all -> banner printed, exit 0 (D-10 default-true) ---
mk_scratch ""
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT")"
STATUS=$?
run_and_cleanup
echo "$OUT" | grep -q 'SOTA-NUMERICS' || fail "case1: banner missing with no config present"
[ "$STATUS" -eq 0 ] || fail "case1: exited non-zero with no config present"
pass "case1: no-config default-true banner (D-10)"

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
rm -f /tmp/sota-numerics-pwned
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" "x; touch /tmp/sota-numerics-pwned")"
run_and_cleanup
echo "$OUT" | grep -q 'SOTA/efficiency/numerical-stability steering' || fail "case4: injection payload did not fall back to generic framing"
[ ! -e /tmp/sota-numerics-pwned ] || fail "case4: injection payload created /tmp/sota-numerics-pwned"
pass "case4: role-argument injection guarded"

echo "ALL PASS"
exit 0
