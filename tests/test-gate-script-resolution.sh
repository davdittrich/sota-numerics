#!/usr/bin/env bash
# Regression test for the plan:post gate command: how it resolves SOTA_SCRIPT
# (github.com/davdittrich/gsd-beads/issues/1's packaging investigation --
# hooks/capability-auto-install.sh always installs at global scope, never
# project scope, so the command must find the script there too), and that it
# carries no consumer-supplied data into the shell at all (gsd-beads-cqt).
# Extracts the gate command verbatim from capability.json (not a hand-copied
# duplicate) so this test tracks the real predicate string, not a stale mirror.
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

# --- Case 0: the gate command is CONSTANT (gsd-beads-cqt) ---
# gsd-core interpolates ${PHASE_NUMBER}/${PHASE_DIR}/${PHASE_REQ_IDS} with a
# plain String.replace (gate-predicate-evaluator.cjs, INTERPOLATION_RE) and
# hands the result to execTool('sh', ['-c', cmd]) (check-command-router.cjs
# :1039-1055). There is no argv and no env channel, so any placeholder in the
# command becomes shell SOURCE.
#
# No shell quoting makes that safe. Enumerated over sh's quoting contexts, each
# has a delimiter the value can contain: unquoted ends at any metacharacter;
# "..." ends at `"`; '...' ends at `'`; a quoted heredoc ends at its delimiter
# line. A phase directory name may contain every byte except `/` and NUL, so
# every context is escapable and the class of payload differs only in which
# delimiter it spells. The fix is therefore not better quoting -- it is having
# nothing to quote. This assertion is the root-cause pin; case 3 below is the
# behavioural one.
case "$GATE_CMD" in
  *'${PHASE_DIR}'*|*'${PHASE_NUMBER}'*|*'${PHASE_REQ_IDS}'*)
    fail "case0: the gate command still interpolates a \${PHASE_*} placeholder into \`sh -c\` source" ;;
esac
pass "case0: the gate command is constant -- no \${PHASE_*} splice reaches sh -c"

trap '[ -n "${SCRATCH:-}" ] && rm -rf "$SCRATCH" 2>/dev/null; [ -n "${FAKE_HOME:-}" ] && rm -rf "$FAKE_HOME" 2>/dev/null' EXIT

# Build a project root the gate can run in: gsd-core sets the subprocess cwd to
# the PROJECT ROOT (cmdCheckPredicate(cwd,...) -> ctx.cwd -> runBoundedShell),
# and the checker resolves the phase from .planning/STATE.md there.
# $1 = project root, $2 = phase directory basename, $3 = current_phase value.
make_project() {
  mkdir -p "$1/.planning/phases/$2" || return 1
  # Both witnesses the checker requires: the frontmatter field and the
  # `## Current Position` `Phase:` line gsd-core's step 13b writes with it.
  printf -- '---\ngsd_state_version: 1.0\ncurrent_phase: %s\nstatus: planning\n---\n\n## Current Position\n\nPhase: %s (Plain) — READY TO EXECUTE\nPlan: 1 of 1\n' "$3" "$3" \
    > "$1/.planning/STATE.md"
  printf '## Alternatives Considered\n\n- **A**: prose. `doc-a` (2024).\n- **B**: prose. `doc-b` (2024).\n\nDecided by: performance.\n' \
    > "$1/.planning/phases/$2/11-01-PLAN.md"
}

# --- Case 1: global-scope-only install (no project-scope copy) -> gate finds
# the script via GSD_HOME fallback and runs it (exit 0: the discovered plan
# passes). ---
SCRATCH="$(mktemp -d)"
make_project "$SCRATCH" "11-plain" "11" || fail "case1: could not build fixture project"
FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.gsd/capabilities/sota-numerics/scripts"
cp "$REPO_ROOT/.gsd/capabilities/sota-numerics/scripts/check-alternatives.py" \
  "$FAKE_HOME/.gsd/capabilities/sota-numerics/scripts/check-alternatives.py"

( cd "$SCRATCH" && GSD_HOME="$FAKE_HOME" bash -c "$GATE_CMD" )
STATUS=$?
[ "$STATUS" -eq 0 ] || fail "case1: global-scope-only install did not resolve and run the gate script (exit $STATUS)"
pass "case1: global-scope-only install resolves SOTA_SCRIPT via GSD_HOME fallback"

# --- Case 2: neither scope has the script -> exit 1 with a clear message. ---
EMPTY_HOME="$(mktemp -d)"
ERR="$(cd "$SCRATCH" && GSD_HOME="$EMPTY_HOME" bash -c "$GATE_CMD" 2>&1 >/dev/null)"
STATUS=$?
rm -rf "$EMPTY_HOME"
[ "$STATUS" -eq 1 ] || fail "case2: missing-everywhere install did not exit 1 (exit $STATUS)"
echo "$ERR" | grep -q "gate script not found at project or global scope" || fail "case2: missing message text"
pass "case2: script missing at both scopes exits 1 with clear message"

# --- Case 2b: HOME and GSD_HOME both unset -> ${GSD_HOME:-$HOME} expands to
# the empty string, so the third rung becomes the root-anchored
# /.gsd/capabilities/sota-numerics/scripts/check-alternatives.py
# (REVIEW-CRITICAL-FINAL P2-3). `sh -c` has no `set -u`, so this is
# unexercised elsewhere; still fail-closed (exit 1), but pin it so a future
# rewrite that assumes one of the two is always set stays honest. ---
ERR2B="$(cd "$SCRATCH" && env -u HOME -u GSD_HOME bash -c "$GATE_CMD" 2>&1 >/dev/null)"
STATUS2B=$?
[ "$STATUS2B" -eq 1 ] || fail "case2b: HOME and GSD_HOME both unset did not exit 1 (exit $STATUS2B)"
echo "$ERR2B" | grep -q "gate script not found at project or global scope" || fail "case2b: missing message text"
pass "case2b: HOME and GSD_HOME both unset still fails closed with the same message"

# --- Case 6: a checker copy inside a repository enclosing the working
# directory is never executed (D-14, T-24-18) ---
# The gate command used to append its script path to `git rev-parse
# --show-toplevel`, so a repository enclosing the working directory -- not
# the project itself -- could supply a checker copy that rung would reach.
# Build exactly that shape: a git repository at "outer", a project with no
# local copy of its own nested inside it at "outer/inner", and a hostile
# script at outer's own copy of the relative path that leaves evidence if
# it ever runs. Prove the gate never reaches it -- it falls straight
# through to the global copy under GSD_HOME instead.
REL6=".gsd/capabilities/sota-numerics/scripts/check-alternatives.py"
P6="$(mktemp -d)"
git init -q "$P6/outer" 2>/dev/null || mkdir -p "$P6/outer"
mkdir -p "$P6/outer/inner"
make_project "$P6/outer/inner" "11-plain" "11" || { rm -rf "$P6"; fail "case6: could not build fixture project"; }
mkdir -p "$P6/outer/$(dirname "$REL6")"
CANARY6="$P6/outer/canary"
cat > "$P6/outer/$REL6" <<PY
import sys
open(r"$CANARY6", "w").write("pwned")
sys.exit(0)
PY

OUT6="$(cd "$P6/outer/inner" && GSD_HOME="$FAKE_HOME" sh -c "$GATE_CMD" 2>&1)"
STATUS6=$?
if [ -e "$CANARY6" ]; then
  rm -rf "$P6"; fail "case6: the checker copy in the enclosing repository was executed"
else
  pass "case6: a checker copy in an enclosing repository is never executed"
fi
if [ "$STATUS6" -ne 0 ]; then
  rm -rf "$P6"; fail "case6: the gate did not fall through to the global copy under GSD_HOME (exit $STATUS6): $OUT6"
fi
pass "case6: the gate falls through past the enclosing repository straight to the global copy"
rm -rf "$P6"

# --- Case 3: hostile phase directory names (gsd-beads-cqt) ---
# One payload per ESCAPE MECHANISM the shell offers, not per example. The
# previous revision of this test enumerated examples and passed while three of
# these executed, because every payload it carried was UNBALANCED -- it never
# closed the single-quoted literal and reopened it. `apostrophe` below was the
# tell: it was pinned as a documented exit-2 limitation, which is precisely the
# statement that a name CAN terminate the literal.
#
# Each name must now reach the checker as a directory it validates: exit 0 on
# the compliant plan inside it, nothing executed, nothing clobbered.
CANARY_TEXT="do-not-truncate"
for spec in \
    'plain                 :11-plain' \
    'apostrophe            :11-o'"'"'brien' \
    'balanced+separator    :11-a'"'"'; touch PWNED; :'"'"'b' \
    'balanced+cmdsub       :11-o'"'"'$(touch PWNED)'"'"'brien' \
    'balanced+backtick     :11-x'"'"'`touch PWNED`'"'"'y' \
    'balanced+andlist      :11-p'"'"'&&touch PWNED&&:'"'"'q' \
    'balanced+pipeline     :11-r'"'"'|touch PWNED||:'"'"'s' \
    'balanced+redirect     :11-t'"'"'>canary.txt;:'"'"'u' \
    'balanced+dquote       :11-v'"'"'"$(touch PWNED)"'"'"'w' \
    'balanced+paramexp     :11-y'"'"'$HOME'"'"'z' \
    'balanced+glob         :11-g'"'"'*'"'"'h' \
    'balanced+backslash    :11-b'"'"'\'"'"'c' \
    ; do
  label="${spec%%:*}"; label="${label%"${label##*[![:space:]]}"}"
  name="${spec#*:}"
  H="$(mktemp -d)"
  # A newline in a directory name is legal on POSIX and defeats a quoted
  # heredoc, so it is covered too -- appended here because it cannot survive
  # the single-line `for` list above.
  if ! make_project "$H" "$name" "11" 2>/dev/null; then
    rm -rf "$H"; fail "case3/$label: could not create the fixture (the name must be testable)"
  fi
  printf '%s\n' "$CANARY_TEXT" > "$H/canary.txt"
  ( cd "$H" && GSD_HOME="$FAKE_HOME" sh -c "$GATE_CMD" ) >/dev/null 2>&1
  rc=$?
  if [ -n "$(find "$H" -name PWNED -print -quit 2>/dev/null)" ]; then
    rm -rf "$H"; fail "case3/$label: the phase directory name was executed as shell source"
  fi
  if [ "$(cat "$H/canary.txt" 2>/dev/null)" != "$CANARY_TEXT" ]; then
    rm -rf "$H"; fail "case3/$label: the phase directory name redirected over an existing file"
  fi
  if [ "$rc" -ne 0 ]; then
    rm -rf "$H"; fail "case3/$label: the gate did not reach the checker's own verdict on a compliant plan (exit $rc)"
  fi
  rm -rf "$H"
done
pass "case3: hostile phase directory names are never shell source; the gate still reaches its verdict"

# --- Case 3b: a newline in the phase directory name. ---
# Separate from the loop only because a literal newline cannot be carried in a
# single-line `for` list. This is the payload that defeats the quoted-heredoc
# alternative NOTES.md considered, so it is pinned explicitly.
NL_NAME="$(printf '11-n\ntouch PWNED\nm')"
H="$(mktemp -d)"
if make_project "$H" "$NL_NAME" "11" 2>/dev/null; then
  ( cd "$H" && GSD_HOME="$FAKE_HOME" sh -c "$GATE_CMD" ) >/dev/null 2>&1
  rc=$?
  [ -z "$(find "$H" -name PWNED -print -quit 2>/dev/null)" ] \
    || { rm -rf "$H"; fail "case3b/newline: the phase directory name was executed as shell source"; }
  [ "$rc" -eq 0 ] \
    || { rm -rf "$H"; fail "case3b/newline: the gate did not reach the checker's verdict (exit $rc)"; }
  pass "case3b: a newline in the phase directory name is data, not a command separator"
else
  echo "SKIP: case3b (this filesystem rejects a newline in a directory name)"
fi
rm -rf "$H"

# --- Case 4: the gate fails CLOSED when it cannot identify its phase. ---
# The phase no longer travels in the command, so an unresolvable current_phase
# is the new failure mode. A blocking gate must block, never pass vacuously.
H="$(mktemp -d)"
mkdir -p "$H/.planning/phases"
printf -- '---\ngsd_state_version: 1.0\nstatus: planning\n---\n' > "$H/.planning/STATE.md"
ERR="$(cd "$H" && GSD_HOME="$FAKE_HOME" sh -c "$GATE_CMD" 2>&1 >/dev/null)"
rc=$?
[ "$rc" -eq 2 ] || { rm -rf "$H"; fail "case4: STATE.md without current_phase did not fail closed (exit $rc)"; }
echo "$ERR" | grep -q "current_phase" || { rm -rf "$H"; fail "case4: message does not name current_phase"; }
rm -rf "$H"

H="$(mktemp -d)"
make_project "$H" "11-a" "11" >/dev/null
mkdir -p "$H/.planning/phases/11-b"
rc=0
( cd "$H" && GSD_HOME="$FAKE_HOME" sh -c "$GATE_CMD" ) >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { rm -rf "$H"; fail "case4: an ambiguous current_phase did not fail closed (exit $rc)"; }
rm -rf "$H"
pass "case4: an unresolvable or ambiguous current_phase blocks (exit 2), never passes"

# --- Case 5: the project copy wins, in every project shape ---
# The chain used `git rev-parse --show-toplevel` FIRST, so a non-Git project
# resolved to "/.gsd/..." and silently fell through to the global copy, and a
# project nested inside a monorepo got the monorepo root rather than its own
# bundle. Both violate the documented project-before-global precedence. Nothing
# caught it because no fixture here was ever a Git repo or carried a project
# copy -- the whole first clause was dead under test.
CHAIN="${GATE_CMD%%test -f*}"
resolve_in() {  # $1=cwd  $2=fake HOME
  ( cd "$1" && HOME="$2" env -u GSD_HOME bash -c "$CHAIN"' printf "%s\n" "$SOTA_SCRIPT"' )
}
REL=".gsd/capabilities/sota-numerics/scripts/check-alternatives.py"
P4="$(mktemp -d)"
mkdir -p "$P4/home/$(dirname "$REL")"; : > "$P4/home/$REL"
mkdir -p "$P4/mono/project/$(dirname "$REL")"; : > "$P4/mono/project/$REL"
git init -q "$P4/mono" 2>/dev/null
mkdir -p "$P4/plain/$(dirname "$REL")"; : > "$P4/plain/$REL"
mkdir -p "$P4/none"

case "$(resolve_in "$P4/mono/project" "$P4/home")" in
  ./"$REL") : ;;
  *) rm -rf "$P4"; fail "case5: a project nested in a monorepo did not use its own bundle" ;;
esac
case "$(resolve_in "$P4/plain" "$P4/home")" in
  ./"$REL") : ;;
  *) rm -rf "$P4"; fail "case5: a non-Git project did not use its own bundle" ;;
esac
case "$(resolve_in "$P4/none" "$P4/home")" in
  "$P4/home/$REL") : ;;
  *) rm -rf "$P4"; fail "case5: a project with no copy did not fall back to global scope" ;;
esac
rm -rf "$P4"
pass "case5: project copy precedes global scope in monorepo, non-Git, and absent-copy shapes"

echo "ALL PASS"
exit 0
