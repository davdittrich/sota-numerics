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
# (gsd-beads-fma).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/hooks/session-start.sh"
PLUGIN_DIR="$REPO_ROOT"

fail() { echo "FAIL: $1"; exit 1; }
pass() { echo "PASS: $1"; }

# Snapshot the real global GSD state before any redirect, so the last assertion
# can prove the suite did not touch it.
REAL_GSD="${GSD_HOME:-$HOME}/.gsd"
real_gsd_state() {
  ls -d "$REAL_GSD/capabilities/sota-numerics" \
        "$REAL_GSD/capability-auto-install-sota-numerics.hash" 2>&1
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
  export HOME="$SCRATCH/home" GSD_HOME="$SCRATCH/home"
  if [ -n "$1" ]; then
    printf '%s\n' "$1" > "$SCRATCH/$_pdir/$_cfg"
  fi
  cd "$SCRATCH" || { echo "FAIL: cd to scratch dir failed"; exit 1; }
}

run_and_cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null
  export HOME="$REAL_HOME"
  unset GSD_HOME
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
# The payload target lives inside the per-run scratch dir, not at a fixed /tmp
# path: a fixed name in a world-writable shared namespace can be pre-created by
# another user, which turns this assertion into a false failure, or symlinked,
# which turns a passing run into a write somewhere else (gsd-beads-91q).
mk_scratch '{"sota-numerics": {"enabled": true}}'
PWNED="$SCRATCH/pwned"
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" "x; touch $PWNED")"
[ -e "$PWNED" ] && PWNED_CREATED=yes || PWNED_CREATED=no
run_and_cleanup
echo "$OUT" | grep -q 'SOTA/efficiency/numerical-stability steering' || fail "case4: injection payload did not fall back to generic framing"
[ "$PWNED_CREATED" = no ] || fail "case4: injection payload created $PWNED"
pass "case4: role-argument injection guarded"

# --- Case 5: the suite itself performed no real global install (gsd-beads-fma) ---
[ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ] ||
  fail "case5: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
pass "case5: real GSD_HOME untouched by the suite"

echo "ALL PASS"
exit 0
