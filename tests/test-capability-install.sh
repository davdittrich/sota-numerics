#!/usr/bin/env bash
# The repository root IS the capability: `gsd capability install <repo>.git#tag`
# (and a local path) reads <source>/capability.json and stages the whole
# directory as $GSD_HOME/.gsd/capabilities/<id>/. Install this checkout's root
# that way into a sandbox GSD_HOME, then run the installed plan:post gate
# command from a project with no vendored copy: a compliant plan must pass and a
# plan whose last alternative lacks a citation must exit 1.
#
# REAL mode uses gsd-core's own CLI (copy-only, no network for a local path) and
# also runs its validateCapability on the manifest. Without gsd-core (CI) the
# install is stubbed as the same directory copy; the mode is printed.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Resolved before HOME is redirected, or the sandbox HOME would hide it.
GSD_CLI="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs"

FAILURES=0
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }
pass() { echo "PASS: $1"; }

SB="$(mktemp -d)"
trap 'rm -rf "$SB"' EXIT
export HOME="$SB/home" GSD_HOME="$SB/home" GIT_CONFIG_GLOBAL=/dev/null
mkdir -p "$HOME"

ID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$REPO_ROOT/capability.json" 2>/dev/null)"
[ -n "$ID" ] || { fail "no capability.json with an id at the repository root"; exit 1; }
MIRROR="$GSD_HOME/.gsd/capabilities/$ID"

if command -v node >/dev/null 2>&1 && [ -f "$GSD_CLI" ]; then
  echo "MODE: REAL ($GSD_CLI)"
  node "$GSD_CLI" capability install "$REPO_ROOT" --scope global --yes >"$SB/install.out" 2>&1 ||
    fail "real install of the repository root failed: $(cat "$SB/install.out")"
  VALIDATOR="$(dirname "$GSD_CLI")/lib/capability-validator.cjs"
  ERRS="$(node -e 'const v=require(process.argv[1]);const c=require(process.argv[2]);console.log(JSON.stringify(v.validateCapability(c,c.id)))' \
    "$VALIDATOR" "$REPO_ROOT/capability.json" 2>&1)"
  [ "$ERRS" = "[]" ] || fail "validateCapability reported: $ERRS"
  pass "validateCapability: $ERRS"
else
  echo "MODE: STUB (no gsd-core at $GSD_CLI; install emulated as a directory copy)"
  mkdir -p "$(dirname "$MIRROR")" && cp -R "$REPO_ROOT" "$MIRROR"
fi
[ -f "$MIRROR/scripts/check-alternatives.py" ] ||
  fail "installed mirror has no scripts/check-alternatives.py"
pass "repository root installs as $ID"

GATE_CMD="$(python3 -I -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(next(g for g in d["gates"] if g["point"]=="plan:post")["check"]["predicate"]["command"])' "$MIRROR/capability.json")"

# $1 = project dir, $2 = last alternative's line
project() {
  mkdir -p "$1/.planning/phases/11-plain"
  printf -- '---\ngsd_state_version: 1.0\ncurrent_phase: 11\nstatus: planning\n---\n\n## Current Position\n\nPhase: 11 (Plain) — READY TO EXECUTE\nPlan: 1 of 1\n' \
    > "$1/.planning/STATE.md"
  printf '## Alternatives Considered\n\n- **A**: prose. `doc-a` (2024).\n%s\n\nDecided by: performance.\n' "$2" \
    > "$1/.planning/phases/11-plain/11-01-PLAN.md"
}

project "$SB/ok" '- **B**: prose. `doc-b` (2024).'
( cd "$SB/ok" && sh -c "$GATE_CMD" ) >"$SB/ok.out" 2>&1
S=$?
[ "$S" -eq 0 ] || fail "compliant plan: installed gate exited $S: $(cat "$SB/ok.out")"
pass "compliant plan passes the installed gate"

project "$SB/bad" '- **B**: prose, no source given.'
( cd "$SB/bad" && sh -c "$GATE_CMD" ) >"$SB/bad.out" 2>&1
S=$?
[ "$S" -eq 1 ] || fail "uncited last alternative: installed gate exited $S, want 1: $(cat "$SB/bad.out")"
pass "uncited last alternative blocks the installed gate"

[ "$FAILURES" -eq 0 ] || { echo "$FAILURES failure(s)"; exit 1; }
