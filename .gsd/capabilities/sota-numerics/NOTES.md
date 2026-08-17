# sota-numerics capability — deliberate divergences and anti-regression rules

This capability ships with a few choices that look wrong at a glance and will attract a
"fix" from a future contributor who reads only the surrounding code. Read this first.

## 1. `gates[0].onError` is `"halt"`, deliberately

Every other gate, step, and contribution in this repo's `beads` and `ponytail` capabilities
uses `onError: "skip"`. `onError` governs the check COMMAND itself failing to run (missing
python3, a crash, a timeout) — it is a separate field from the block decision, which
gsd-core's generic `command-exit-zero` evaluator derives purely from the check command's
exit code. A blocking gate (`blocking: true`) that silently skips when its own checker
cannot run defeats the reason it exists: an unenforceable environment (broken interpreter,
missing script) would otherwise look identical to a passing plan. See CONTEXT.md's
Established Patterns section for the same rule stated at the requirements level.

`contributions[].onError` on this capability's four advisory fragments correctly stays
`"skip"` — those are non-blocking steering text, and a rendering failure there should never
halt planning. The two `onError` values differ (`halt` on the one blocking gate, `skip` on
every advisory contribution) because they govern differently-consequential failures, not
because one of them is a mistake. Do not "fix" `gates[0].onError` back to `"skip"` to match
the contributions.

## 2. The `plan:post` gate fires late — after the plan is already committed

**Re-verified against the installed `~/.claude/gsd-core/workflows/plan-phase.md` during this
plan (Task 3), not restated from RESEARCH.md's Pitfall 1 from memory** — the cross-AI review
(11-REVIEWS.md finding 1) asked specifically whether the documented ordering was still
accurate after the replan. It is: the live step order is unchanged —
§13a Decision Coverage Gate, §13b STATE.md marked "Ready to execute", §13c ROADMAP
annotation, §13d plans committed to git (`commit_docs`), then §13e the `plan:post`
capability gate dispatch that evaluates this capability's `check-alternatives.py`. A block at
§13e therefore halts with the non-compliant `PLAN.md` already committed and `STATE.md`
already claiming the phase is ready to execute. This is expected under the current gsd-core,
not a bug in this capability.

Consequence: the `gsd-plan-checker` revision loop (steps 10-12, which run *before* §13a-13e)
is the PRIMARY enforcement point — a plan with a missing or malformed Alternatives Considered
section should already draw a checker BLOCKER, forcing a revision before anything commits.
The `plan:post` `command-exit-zero` gate documented here is a structural backstop, not the
first line of defense. `plan-phase.md`'s own §13e code comment notes the branch was written
for `gap-analysis`, which "is always `blocking: false`" — this capability is the first to
actually exercise the `blocking: true` branch of that loop.

Remediation after a §13e block is `/gsd-plan-phase <N> --force` (the closed-phase guard at
§1.5 permits re-planning a non-`Complete` phase). This is no longer documentation-only: per
REVIEWS finding 1's overlap with finding 3, `check-alternatives.py` itself prints
`remediation: fix the plans above, then re-run /gsd-plan-phase <phase> --force` to stderr on
every exit-1 run, so an operator hitting the gate sees the recovery command at the moment of
failure without opening this file. This section explains WHY that line exists; the script is
what makes it discoverable.

## 3. Script path resolution and the missing-script guard

The gate command resolves the script through `$(git rev-parse --show-toplevel)`, not
`${CLAUDE_PLUGIN_ROOT}`, because the gate-evaluation subprocess's environment was not
verified to carry that variable while its `cwd` is the project root (RESEARCH Open
Question 1). Consequence: the gate only works where the bundle is installed at the project
root under `.gsd/capabilities/sota-numerics/`, which is exactly what `gsd capability
install sota-numerics` produces (D-04's dogfood copy is this repo's own such install).

The gate command carries a `test -f` guard (REVIEWS finding 3): when the plugin exists only
in the global cache and no local install has run, the gate exits 1 with a message naming the
missing path and the `capability install` remediation, rather than a bare `python3`
file-not-found error. This fails closed deliberately — removing the guard, or softening it to
exit 0, would let an uninstalled capability silently stop gating every plan in every phase.

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
the gate, which is exactly the false-positive REVIEWS finding 2 flagged. `check-alternatives.py`'s
own `TestFoundationalCitationPairing` test class and `planner-sota.md` (the fragment that
teaches this pairing rule to the planner) both exist to catch and prevent that regression. If
either is edited, update the other — they teach and enforce the same rule from two different
seats in the pipeline.
