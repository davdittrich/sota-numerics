#!/usr/bin/env bash
# Regression test for the plan:post gate's SOTA_SCRIPT resolution
# (github.com/davdittrich/gsd-beads/issues/1's packaging investigation):
# hooks/capability-auto-install.sh always installs at global scope
# (--scope global), never project scope, so the gate command must find the
# script there too, not only under a project's own git root. Extracts the
# gate command verbatim from capability.json (not a hand-copied duplicate)
# so this test tracks the real predicate string, not a stale mirror of it.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAP_JSON="$REPO_ROOT/.gsd/capabilities/sota-numerics/capability.json"

fail() { echo "FAIL: $1"; exit 1; }
pass() { echo "PASS: $1"; }

GATE_CMD="$(python3 - "$CAP_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d["gates"][0]["check"]["predicate"]["command"])
PY
)"
[ -n "$GATE_CMD" ] || fail "could not extract gate command from capability.json"

trap '[ -n "${SCRATCH:-}" ] && rm -rf "$SCRATCH" 2>/dev/null; [ -n "${FAKE_HOME:-}" ] && rm -rf "$FAKE_HOME" 2>/dev/null' EXIT

# --- Case 1: global-scope-only install (no project-scope copy) -> gate finds
# the script via GSD_HOME fallback and runs it (exit reflects the checker's
# own verdict on an empty phase dir: 0, no plans to check). ---
SCRATCH="$(mktemp -d)"
mkdir -p "$SCRATCH/.planning" "$SCRATCH/phase"
FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.gsd/capabilities/sota-numerics/scripts"
cp "$REPO_ROOT/.gsd/capabilities/sota-numerics/scripts/check-alternatives.py" \
  "$FAKE_HOME/.gsd/capabilities/sota-numerics/scripts/check-alternatives.py"

( cd "$SCRATCH" && PHASE_DIR="$SCRATCH/phase" GSD_HOME="$FAKE_HOME" bash -c "$GATE_CMD" )
STATUS=$?
[ "$STATUS" -eq 0 ] || fail "case1: global-scope-only install did not resolve the gate script (exit $STATUS)"
pass "case1: global-scope-only install resolves SOTA_SCRIPT via GSD_HOME fallback"

# --- Case 2: neither scope has the script -> exit 1 with a clear message on stderr. ---
EMPTY_HOME="$(mktemp -d)"
ERR="$(cd "$SCRATCH" && PHASE_DIR="$SCRATCH/phase" GSD_HOME="$EMPTY_HOME" bash -c "$GATE_CMD" 2>&1 >/dev/null)"
STATUS=$?
rm -rf "$EMPTY_HOME"
[ "$STATUS" -eq 1 ] || fail "case2: missing-everywhere install did not exit 1 (exit $STATUS)"
echo "$ERR" | grep -q "gate script not found at project or global scope" || fail "case2: missing message text"
pass "case2: script missing at both scopes exits 1 with clear message"

echo "ALL PASS"
exit 0
