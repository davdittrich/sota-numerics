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

The gate command carries a `test -f` guard. This fails closed
deliberately — removing the guard, or softening it to exit 0, would let an uninstalled
capability silently stop gating every plan in every phase.

## 4. No `into: "checker"` contribution — it would install and never render

The obvious extension to this capability is a fifth `contributions[]` entry with
`into: "checker"`, so the plan checker spot-checks citation plausibility before the gate
passes. It would be schema-valid and install cleanly, and it would never run: the only
role-targeted contribution injection in gsd-core's `plan-phase.md` filters on
`into == "planner"`, and the `gsd-plan-checker` prompt that workflow builds carries no
contribution block at all. The absence of a fifth contribution is the choice, not an
oversight.

Citation quality is therefore enforced mechanically and stops there:
`entry_placeholder_violation` in `check-alternatives.py` rejects example.com-class hosts
and bare TODO/TBD references.

**What would justify revisiting:** a plan passes this gate on a citation a human later finds
was hallucinated — a well-formed URL or year the regex cannot tell from a real one.
Tightening the regex cannot catch that; only a judgment layer can, and that needs the render
call site to exist first.

## 5. The recency rule is at-least-one-in-window, never none-outside-window

`check-alternatives.py`'s recency check accepts an alternative if AT LEAST ONE cited year
falls within the last 6 years — not if every cited year does. This is deliberate: an
alternative citing Kahan summation, IEEE 754, or a classic BLAS paper alongside a current doc
or benchmark passes, because only one in-window year is required.

**Warning:** "tightening" this to reject any out-of-window year — the obvious-looking reading
of "citations require a recency marker" — would make every foundational citation fail
the gate. Two things guard against it. `tests/test_check_alternatives.py` in the plugin
repository carries a `TestFoundationalCitationPairing` class that fails on exactly that
regression — it lives outside this bundle, so a reader of an installed copy will not find it
here. `planner-sota.md`, which does ship here, teaches the planner the same pairing rule. If
either is edited, update the other — they teach and enforce one rule from two seats.

## 6. Single-quoting `${PHASE_DIR}` narrows the splice; it does not close it

gsd-core builds the gate command by replacing the literal text `${PHASE_DIR}` with the
phase directory (`gsd-core/bin/lib/gate-predicate-evaluator.cjs`, `interpolate`) and then
runs the result through `sh -c`. The value never exists as a shell variable, so the quoting
written in `capability.json` is the only protection there is.

The gate command wraps the splice in single quotes. Measured against 0.1.3's double quotes,
with the same phase directory holding the same passing plan:

| phase directory name | 0.1.3 `"${PHASE_DIR}"` | 0.2.0 `'${PHASE_DIR}'` |
| --- | --- | --- |
| `11-$(touch PWNED)-x` | ran `touch`, exit 2 | no file created, exit 0 |
| ``11-`touch PWNED2`-x`` | ran `touch`, exit 2 | no file created, exit 0 |
| `11-o'brien` | exit 0 | `sh: unexpected EOF`, exit 2 |

Command substitution is closed. A name containing `'` is not: it ends the quoted string and
the command dies as a shell syntax error, which the evaluator maps to a block verdict. That
is fail-closed rather than a bypass, but it is a regression against 0.1.3 for that one name
shape, and it is the reason this section exists.

No quoting this manifest can write removes the remaining hole, because the splice is
textual. The fix belongs upstream in gsd-core: pass the phase directory as an argv element,
or shell-escape it at interpolation time. Until that lands, single quotes are the better of
the two available failures.

Do not "simplify" these back to double quotes to make an apostrophe work. That re-opens
command substitution, which is the worse failure of the two.
