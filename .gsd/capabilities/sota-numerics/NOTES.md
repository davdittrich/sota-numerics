# sota-numerics capability — deliberate divergences and anti-regression rules

This capability ships with a few choices that look wrong at a glance and will attract a
"fix" from a future contributor who reads only the surrounding code. Read this first.

## 1. `gates[0].onError` is `"halt"`, deliberately

`onError` routes a *thrown* evaluator error, and gsd-core's predicate
evaluator throws on exactly two things: a malformed predicate declaration and an unknown
`predicate.kind`. Every runtime outcome of the check command itself is mapped to a block
verdict instead — a missing `python3` (exit 127), a crash (exit 1) and the 30s timeout all
yield `block: true`, and only exit 0 yields `block: false`. So `"halt"` here does not cover a
broken interpreter; it covers this manifest being wrong about its own predicate, which a
blocking gate must never pass over in silence.

`contributions[].onError` on this capability's four advisory fragments correctly stays
`"skip"` — those are non-blocking steering text, and a rendering failure there should never
halt planning. The two `onError` values differ (`halt` on the one blocking gate, `skip` on
every advisory contribution) because they govern differently-consequential failures, not
because one of them is a mistake. Do not "fix" `gates[0].onError` back to `"skip"` to match
the contributions.

## 2. The `plan:post` gate fires late — after the plan is already committed

`plan-phase.md`'s own §13e code comment notes the branch was written for `gap-analysis`,
which "is always `blocking: false`" — this capability is the first to actually exercise the
`blocking: true` branch.

## 3. Script path resolution and the missing-script guard

The gate command resolves the script through `$(git rev-parse --show-toplevel)` rather than
`${CLAUDE_PLUGIN_ROOT}`: gsd-core runs the check command at the runtime project root with the
parent process's environment inherited, which makes the project root a reliable anchor and
leaves the plugin root dependent on a variable this capability does not set. The command then
falls back to `${GSD_HOME:-$HOME}/.gsd/capabilities/sota-numerics/`, so a global-scope-only
install resolves too. `README.md` states the full resolution order and its precedence rule;
this note records only why the project root is found the way it is.

The gate command carries a `test -f` guard (REVIEWS finding 3). This fails closed
deliberately — removing the guard, or softening it to exit 0, would let an uninstalled
capability silently stop gating every plan in every phase.

## 4. D-08's route: mechanical heuristics only, LLM layer deferred

D-08 asked for a layered check: a structural predicate for presence/well-formedness, plus
`gsd-plan-checker` getting a contribution fragment to spot-check citation plausibility before
the gate passes. RESEARCH verified that no workflow call site renders `into: "checker"`
contributions anywhere in the installed gsd-core — a fragment declared for that channel today
would be schema-valid, installed, and silently inert, the same failure mode `beads`'s own
`plan:post` step already exhibits in this repo. Two routes existed: patch
`~/.claude/gsd-core/workflows/plan-phase.md` step 10 to add that render call (a machine-local
edit, RESEARCH's own N2-constraint-override category), or defer the LLM-mediated layer and
let the deterministic heuristics already in `check-alternatives.py` stand in for it.

**Decided at this plan's Task 1 checkpoint: mechanical.** Rationale given: ship Phase 11
patch-free with zero core-repo risk and no new machine-local maintenance surface, consistent
with this repo's own ladder discipline (reach for a deterministic check before an
LLM-mediated one) and matching RESEARCH's own first-move recommendation (Pattern 2). This
satisfies D-08's *intent* — a plausibility spot-check runs before the gate can pass — through
a different mechanism than the literal wording ("gets a contribution fragment"): the
deterministic layer (`entry_placeholder_violation` in `check-alternatives.py`) already rejects
example.com-class placeholder hosts and bare TODO/TBD citations, D-08's own mechanical half,
shipped in Plan 01. No fragment, no fifth `contributions[]` entry, and no
`GSD-CORE-PATCH.md` exist in this capability as a result — their absence is the route, not an
oversight.

**Dogfood signal that would trigger revisiting (D-04):** a plan passes this gate on a
citation that a human later discovers was hallucinated — a syntactically well-formed URL or
date that the deterministic regex cannot distinguish from a real one. If that happens during
this repo's own future phase planning, escalate to the patch route (Pattern 2(a) in
RESEARCH.md) rather than tightening the regex further; a well-formed hallucination is exactly
what regex cannot catch and genuine LLM judgment can.

## 5. The recency rule is at-least-one-in-window, never none-outside-window

`check-alternatives.py`'s recency check accepts an alternative if AT LEAST ONE cited year
falls within the last 6 years — not if every cited year does. This is deliberate (REVIEWS
finding 2): an alternative citing Kahan summation, IEEE 754, or a classic BLAS paper alongside
a current doc or benchmark passes, because only one in-window year is required and the
canonical year is simply ignored when computing whether an in-window date exists. It is never
rejected on its own merits — it only fails to count toward the in-window requirement by
itself.

**Warning:** "tightening" this to reject any out-of-window year — the obvious-looking reading
of D-07 ("citations require a recency marker") — would make every foundational citation fail
the gate. Two things guard against it. `tests/test_check_alternatives.py` in the plugin
repository carries a `TestFoundationalCitationPairing` class that fails on exactly that
regression — it lives outside this bundle, so a reader of an installed copy will not find it
here. `planner-sota.md`, which does ship here, teaches the planner the same pairing rule. If
either is edited, update the other — they teach and enforce one rule from two seats.
