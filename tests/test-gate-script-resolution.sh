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

# gsd-core substitutes ${PHASE_DIR} TEXTUALLY into the command string and only
# then hands the result to `sh -c` (gate-predicate-evaluator.cjs:41 builds the
# literal /\$\{(PHASE_NUMBER|PHASE_DIR|PHASE_REQ_IDS)\}/g and replaces against
# it; :47 supplies the PHASE_DIR value). The shell therefore never expands the
# placeholder, which is why the command quotes it in single quotes -- a
# consumer-supplied path must reach argv as data, not as shell source.
#
# Emulate that splice here. Exporting PHASE_DIR and letting `bash -c` expand it
# tests a substitution that never happens in production: it passed only while
# the command double-quoted the placeholder, and went red the moment the
# quoting was hardened, reporting a defect in the fix rather than in itself.
gate_cmd_for() {
  local phase_dir="$1"
  printf '%s' "${GATE_CMD//\$\{PHASE_DIR\}/$phase_dir}"
}

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

( cd "$SCRATCH" && GSD_HOME="$FAKE_HOME" bash -c "$(gate_cmd_for "$SCRATCH/phase")" )
STATUS=$?
[ "$STATUS" -eq 0 ] || fail "case1: global-scope-only install did not resolve the gate script (exit $STATUS)"
pass "case1: global-scope-only install resolves SOTA_SCRIPT via GSD_HOME fallback"

# --- Case 2: neither scope has the script -> exit 1 with a clear message on stderr. ---
EMPTY_HOME="$(mktemp -d)"
ERR="$(cd "$SCRATCH" && GSD_HOME="$EMPTY_HOME" bash -c "$(gate_cmd_for "$SCRATCH/phase")" 2>&1 >/dev/null)"
STATUS=$?
rm -rf "$EMPTY_HOME"
[ "$STATUS" -eq 1 ] || fail "case2: missing-everywhere install did not exit 1 (exit $STATUS)"
echo "$ERR" | grep -q "gate script not found at project or global scope" || fail "case2: missing message text"
pass "case2: script missing at both scopes exits 1 with clear message"

# --- Case 3: a hostile phase directory name reaches the checker as data ---
# gsd-core substitutes ${PHASE_DIR} textually and hands the result to `sh -c`
# (gate-predicate-evaluator.cjs:41-53, check-command-router.cjs:985-987), so the
# quoting in capability.json is the only thing between a directory name and the
# shell. There is no argv or env channel to use instead.
#
# Every shape below must leave PWNED uncreated. The apostrophe case additionally
# pins a KNOWN LIMITATION rather than a desired behaviour: a single quote in the
# name terminates the literal, `sh` fails to parse the command before any of it
# runs, and the blocking gate rejects an otherwise valid phase with exit 2. That
# is a fail-CLOSED availability bug. It is recorded because the alternatives are
# worse -- double quotes restore command substitution, and a quoted-delimiter
# heredoc is terminated by a newline in the name, which executes. The real fix is
# upstream: pass the phase directory as an argv element, or escape it at the
# interpolation site.
for spec in 'plain:11-plain' \
            'cmdsub:11-$(touch PWNED)-x' \
            'backtick:11-`touch PWNED`-x' \
            'semicolon:11-semi;touch PWNED' \
            'dquote:11-quote"x' \
            'apostrophe:11-o'"'"'brien'; do
  label="${spec%%:*}"; name="${spec#*:}"
  H="$(mktemp -d)"; mkdir -p "$H/.planning" "$H/$name" 2>/dev/null || { rm -rf "$H"; continue; }
  printf '## Alternatives Considered\n\n- A vs B. Decided by: speed.\n\nSeen 2024.\n' \
    > "$H/$name/01-01-PLAN.md"
  ( cd "$H" && GSD_HOME="$FAKE_HOME" sh -c "$(gate_cmd_for "$H/$name")" ) >/dev/null 2>&1
  rc=$?
  if [ -e "$H/PWNED" ] || [ -e "$H/$name/PWNED" ]; then
    rm -rf "$H"; fail "case3/$label: the phase directory name was executed as shell source"
  fi
  if [ "$label" = apostrophe ] && [ "$rc" -ne 2 ]; then
    rm -rf "$H"
    fail "case3/apostrophe: expected the documented exit 2; got $rc -- if upstream now escapes the splice, delete this arm and the NOTES.md section 6 entry"
  fi
  rm -rf "$H"
done
pass "case3: hostile phase directory names reach the checker as data, not shell source"

echo "ALL PASS"
exit 0
