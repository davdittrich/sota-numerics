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

# These assertions pin the pointer form each role banner now prints (gsd-beads-25vc.21.5
# row 1): each pattern must stay unique to its own role. A pattern that also matches the
# shared header line would pass for every role and stop testing role dispatch at all.
# --- Case 3a: ROLE=planner -> planner framing, qualifies the blocking gate ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" planner)"
run_and_cleanup
echo "$OUT" | grep -q 'planner fragment' || fail "case3a: planner framing line missing"
echo "$OUT" | grep -q 'blocking plan:post gate' || fail "case3a: planner banner does not qualify the blocking gate"
pass "case3a: ROLE=planner framing"

# --- Case 3b: ROLE=executor -> executor framing ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" executor)"
run_and_cleanup
echo "$OUT" | grep -q 'executor fragment' || fail "case3b: executor framing line missing"
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

# --- Case 8: hooks.json's SubagentStart wiring actually supplies the role
# tokens cases 3a-3c only prove session-start.sh honors (gsd-beads-25vc.21.3
# item 1) ---
# This pins only OUR half of the contract: the manifest, the script it
# names, and the role tokens they exchange. Whether Claude Code fires
# SubagentStart at all, and whether it matches on the subagent name, is host
# behavior no test in this repository can see; if the host renamed or
# dropped the event this case would stay green, and that is the documented
# limit of the coverage, not a claim about it. The evidence that it does
# fire is first-hand: an in-tree plugin worktree re-published its
# capability bundle on a gsd-executor subagent spawn -- the incident
# tests/test-capability-auto-install.sh's I0 comment means by "has happened
# on this project" when it says the leak it guards against has happened
# here. No alternative event name has any evidence behind it, so none is
# asserted.
HOOKS_CHECK="$(python3 - "$REPO_ROOT" <<'PY'
import json, os, re, sys

repo_root = sys.argv[1]
hooks_path = os.path.join(repo_root, "hooks", "hooks.json")
lines = []


def report(ok, msg):
    lines.append(("PASS" if ok else "FAIL") + ": " + msg)


try:
    with open(hooks_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
except Exception as exc:
    print("FAIL: case8: hooks.json does not parse as JSON (%s)" % exc)
    sys.exit(0)
report(True, "case8: hooks.json parses as JSON")

hooks = manifest.get("hooks", {})
subagent_start = hooks.get("SubagentStart", [])
matchers = [entry.get("matcher") for entry in subagent_start]
expected = {"gsd-planner", "gsd-executor", "gsd-verifier"}
report(
    len(subagent_start) == 3 and set(matchers) == expected,
    "case8: SubagentStart holds exactly the three gsd- matchers (got %r)" % (matchers,),
)

roles = {}
role_ok = True
for entry in subagent_start:
    matcher = entry.get("matcher", "")
    role = matcher[len("gsd-"):] if matcher.startswith("gsd-") else None
    entry_hooks = entry.get("hooks", [])
    command = entry_hooks[0].get("command", "") if len(entry_hooks) == 1 else None
    ok = (
        role is not None
        and len(entry_hooks) == 1
        and entry_hooks[0].get("type") == "command"
        and command is not None
        and '${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh' in command
        and command.rstrip().endswith(role)
    )
    role_ok = role_ok and ok
    if role:
        roles[role] = ok
report(
    role_ok,
    "case8: each SubagentStart entry invokes session-start.sh with its own gsd- suffix as the role token",
)

session_start = hooks.get("SessionStart", [])
session_matcher_ok = (
    len(session_start) == 1
    and session_start[0].get("matcher") == "startup|resume|clear|compact"
)
report(session_matcher_ok, "case8: SessionStart's matcher still reads startup|resume|clear|compact")

command_re = re.compile(r'\$\{CLAUDE_PLUGIN_ROOT\}/([^"\s]+)')
all_scripts_exist = True
for point_entries in hooks.values():
    for entry in point_entries:
        for hook in entry.get("hooks", []):
            for m in command_re.finditer(hook.get("command", "")):
                script_path = os.path.join(repo_root, m.group(1))
                if not os.path.isfile(script_path):
                    all_scripts_exist = False
report(
    all_scripts_exist,
    "case8: every ${CLAUDE_PLUGIN_ROOT}-relative script the manifest names exists under REPO_ROOT",
)

for expected_role in ("planner", "executor", "verifier"):
    if expected_role not in roles:
        report(False, "case8: manifest has no gsd-%s entry to exercise" % expected_role)

print("\n".join(lines))
print("ROLES=" + ",".join(sorted(roles)))
PY
)"
echo "$HOOKS_CHECK" | grep -q '^ROLES=' || fail "case8: role extraction from the manifest failed"
MANIFEST_ROLES="$(echo "$HOOKS_CHECK" | sed -n 's/^ROLES=//p')"
while IFS= read -r line; do
  case "$line" in
    PASS:*) pass "${line#PASS: }" ;;
    FAIL:*) fail "${line#FAIL: }" ;;
  esac
done < <(echo "$HOOKS_CHECK" | grep -E '^(PASS|FAIL):')

if [ -n "$MANIFEST_ROLES" ]; then
  IFS=',' read -r -a ROLE_ARR <<< "$MANIFEST_ROLES"
  for role in "${ROLE_ARR[@]}"; do
    mk_scratch '{"sota-numerics": {"enabled": true}}'
    OUT="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" "$role")"
    run_and_cleanup
    case "$role" in
      planner)
        echo "$OUT" | grep -q 'planner fragment' || fail "case8: manifest's planner token did not produce the planner framing"
        echo "$OUT" | grep -q 'blocking plan:post gate' || fail "case8: manifest's planner token did not qualify the blocking gate"
        ;;
      executor)
        echo "$OUT" | grep -q 'executor fragment' || fail "case8: manifest's executor token did not produce the executor framing"
        ;;
      verifier)
        echo "$OUT" | grep -q 'not blockers' || fail "case8: manifest's verifier token did not produce the verifier framing"
        ;;
      *)
        fail "case8: manifest named an unrecognized role '$role'"
        ;;
    esac
  done
  pass "case8: hooks.json's manifest role tokens each reproduce their cases-3a-3c banner"
fi

# --- Stub plugin root: session-start.sh + gsd-tools.sh real, auto-install a recorder ---
# mk_stub_root <install-exit-status>; sets STUB_ROOT inside SCRATCH. The stub logs its
# argv to $STUB_ROOT/installs so a case can count installs and see their arguments.
mk_stub_root() {
  STUB_ROOT="$SCRATCH/plugin"
  mkdir -p "$STUB_ROOT/hooks"
  cp "$REPO_ROOT/hooks/session-start.sh" "$REPO_ROOT/hooks/gsd-tools.sh" "$STUB_ROOT/hooks/"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/installs"\nexit %s\n' "$STUB_ROOT" "${1:-0}" \
    > "$STUB_ROOT/hooks/capability-auto-install.sh"
}

# --- Case 9 (F13): enabled=false must not install anything ---
# The install is a machine-wide mutation; a user who switched the capability off
# must not get it re-installed on every session start.
mk_scratch '{"sota-numerics": {"enabled": false}}'
mk_stub_root 0
CLAUDE_PLUGIN_ROOT="$STUB_ROOT" bash "$STUB_ROOT/hooks/session-start.sh" >/dev/null 2>&1
[ ! -e "$STUB_ROOT/installs" ] || fail "case9: enabled=false still ran the auto-install"
run_and_cleanup
mk_scratch '{"sota-numerics": {"enabled": true}}'
mk_stub_root 0
CLAUDE_PLUGIN_ROOT="$STUB_ROOT" bash "$STUB_ROOT/hooks/session-start.sh" >/dev/null 2>&1
[ -e "$STUB_ROOT/installs" ] || fail "case9: enabled=true did not run the auto-install"
run_and_cleanup
pass "case9: auto-install runs only when the capability is enabled"

# --- Case 10 (F17): the global gsd-core rung beats PATH; a relative PATH entry never runs ---
# A `gsd-tools` found through PATH can be a repo-local file (PATH=./bin or "."),
# so the absolute ${CLAUDE_CONFIG_DIR:-$HOME/.claude} rung is tried first and a
# PATH hit is accepted only when it is an absolute path.
H10="$(mktemp -d)"; D10="$(mktemp -d)"
mkdir -p "$H10/.claude/gsd-core/bin"
printf 'process.stdout.write("global");\n' > "$H10/.claude/gsd-core/bin/gsd-tools.cjs"
printf '#!/usr/bin/env bash\necho path-stub\n' > "$D10/gsd-tools"; chmod +x "$D10/gsd-tools"
OUT10="$(cd "$D10" && HOME="$H10" PATH="$D10:$PATH" bash -c 'unset CLAUDE_PLUGIN_ROOT CLAUDE_CONFIG_DIR; . "'"$REPO_ROOT"'/hooks/gsd-tools.sh"; gsd_tools x')"
[ "$OUT10" = global ] || fail "case10: a PATH gsd-tools shadowed the global gsd-core rung (got '$OUT10')"
rm -rf "$H10/.claude"
OUT10="$(cd "$D10" && HOME="$H10" PATH=".:$PATH" bash -c 'unset CLAUDE_PLUGIN_ROOT CLAUDE_CONFIG_DIR; . "'"$REPO_ROOT"'/hooks/gsd-tools.sh"; gsd_tools x' 2>/dev/null)"
S10=$?
[ "$OUT10" != path-stub ] || fail "case10: a gsd-tools reached through a relative PATH entry was executed"
rm -rf "$H10" "$D10"
pass "case10: global rung first; relative PATH hits are ignored"

# mk_failing_tools <exit-status> -- a PATH-first gsd-tools whose every call fails; sets FAIL_DIR
mk_failing_tools() {
  FAIL_DIR="$(mktemp -d)"
  printf '#!/usr/bin/env bash\necho "gsd-tools: boom" >&2\nexit %s\n' "$1" > "$FAIL_DIR/gsd-tools"
  chmod +x "$FAIL_DIR/gsd-tools"
}

# --- Case 11 (F19d): a failing config-get outside a GSD project is not noise ---
# With no .planning/ there is nothing to configure: the capability stays enabled
# and the hook says nothing on stderr.
mk_scratch ""
rmdir "$SCRATCH/.planning"
mk_failing_tools 1
mk_stub_root 0   # recorder in place of the real auto-install, whose refusals also reach stderr
ERR11="$(CLAUDE_PLUGIN_ROOT="$STUB_ROOT" PATH="$FAIL_DIR:$PATH" bash "$STUB_ROOT/hooks/session-start.sh" 2>&1 >"$SCRATCH/out11")"
OUT11="$(cat "$SCRATCH/out11")"
rm -rf "$FAIL_DIR"
run_and_cleanup
echo "$OUT11" | grep -q 'SOTA-NUMERICS' || fail "case11: banner missing outside a GSD project"
[ -z "$ERR11" ] || fail "case11: stderr noise outside a GSD project: $ERR11"
pass "case11: failing config-get without .planning/ is silent and stays enabled"

# --- Case 12 (F10b): SubagentStart (role) invocations never install ---
# Parallel subagent spawns would race gsd-core's install lock ("install failed");
# only SessionStart installs.
mk_scratch '{"sota-numerics": {"enabled": true}}'
mk_stub_root 0
for _r in planner executor verifier; do
  CLAUDE_PLUGIN_ROOT="$STUB_ROOT" bash "$STUB_ROOT/hooks/session-start.sh" "$_r" >/dev/null 2>&1
done
[ ! -e "$STUB_ROOT/installs" ] || fail "case12: a role invocation ran the auto-install"
run_and_cleanup
pass "case12: role invocations skip the auto-install"

# --- Case 13 (F20): role invocations emit SubagentStart hookSpecificOutput JSON ---
# SubagentStart only documents hookSpecificOutput.additionalContext; plain stdout is
# not injected. SessionStart (no role) keeps plain stdout.
mk_scratch '{"sota-numerics": {"enabled": true}}'
for _r in planner executor verifier; do
  OUT13="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT" "$_r")"
  echo "$OUT13" | python3 -c '
import json, sys
o = json.load(sys.stdin)["hookSpecificOutput"]
assert o["hookEventName"] == "SubagentStart", o
assert "SOTA-NUMERICS" in o["additionalContext"], o
' 2>/dev/null || fail "case13: $_r did not emit SubagentStart additionalContext JSON (got: $OUT13)"
done
OUT13="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_DIR" bash "$SCRIPT")"
case "$OUT13" in "SOTA-NUMERICS"*) ;; *) fail "case13: SessionStart output is no longer plain text (got: $OUT13)" ;; esac
run_and_cleanup
pass "case13: role invocations emit additionalContext JSON; SessionStart stays plain"

# --- Case 14 (F21b): config-get failing inside a GSD project disables the banner and says why ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
mk_failing_tools 3
mk_stub_root 0
ERR14="$(CLAUDE_PLUGIN_ROOT="$STUB_ROOT" PATH="$FAIL_DIR:$PATH" bash "$STUB_ROOT/hooks/session-start.sh" 2>&1 >"$SCRATCH/out14")"
OUT14="$(cat "$SCRATCH/out14")"
rm -rf "$FAIL_DIR"
run_and_cleanup
[ -z "$OUT14" ] || fail "case14: banner printed despite a failing config-get: $OUT14"
echo "$ERR14" | grep -qF 'config-get sota-numerics.enabled failed (exit 3)' || fail "case14: stderr does not name the failure (got: $ERR14)"
pass "case14: config-get exit 3 suppresses the banner and reports on stderr"

# --- Case 15 (R-A): a failing config-get from a subdirectory of a GSD project still disables the banner ---
mk_scratch '{"sota-numerics": {"enabled": true}}'
mkdir -p "$SCRATCH/sub/deep"
cd "$SCRATCH/sub/deep" || fail "case15: cd to subdirectory failed"
mk_failing_tools 3
mk_stub_root 0
ERR15="$(CLAUDE_PLUGIN_ROOT="$STUB_ROOT" PATH="$FAIL_DIR:$PATH" bash "$STUB_ROOT/hooks/session-start.sh" 2>&1 >"$SCRATCH/out15")"
OUT15="$(cat "$SCRATCH/out15")"
rm -rf "$FAIL_DIR"
run_and_cleanup
[ -z "$OUT15" ] || fail "case15: banner printed from a project subdirectory despite a failing config-get: $OUT15"
echo "$ERR15" | grep -qF 'config-get sota-numerics.enabled failed (exit 3)' || fail "case15: stderr does not name the failure (got: $ERR15)"
pass "case15: failing config-get in a project subdirectory suppresses the banner"

# --- Case 5: the suite itself performed no real global install ---
[ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ] ||
  fail "case5: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
pass "case5: real GSD_HOME untouched by the suite"

[ "$FAILURES" -eq 0 ] || { echo "$FAILURES FAILED"; exit 1; }
echo "ALL PASS"
exit 0
