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

Write `_SN` for `.gsd/capabilities/sota-numerics/scripts/check-alternatives.py`. The gate
command tries two paths in order: `./$_SN`, then `${GSD_HOME:-$HOME}/$_SN`. gsd-core runs the
check command at the runtime project root with the parent process's environment inherited, so
the first rung reaches the project copy with no Git at all, and the second resolves a
global-scope-only install. `README.md` lists the two locations and the rule that the project
copy wins; the order above is how that rule is met.

A third rung used to sit between these two, asking Git for the top level of the repository
enclosing the working directory and appending the script path to it, meant to widen the
project lookup to working directories below the project root. It is gone (D-14): that top
level is whatever repository encloses the *current working directory*, which is a directory
an attacker chooses, not the project gsd-core dispatches the gate from — a checker script
planted at the top of that enclosing repository would run in the project's place.
`tests/test-gate-script-resolution.sh` pins a repository enclosing the working directory,
carrying a hostile copy at the same relative path, and proves the gate never reaches it.

`${CLAUDE_PLUGIN_ROOT}` is used at no rung: it is a variable this capability does not set, so
it would leave the lookup dependent on the host, where the project root is an anchor gsd-core
itself establishes.

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

## 6. The gate command is constant; the phase comes from STATE.md

`capability.json` interpolates nothing. `grep -c PHASE_DIR capability.json` is `0`, and the
command ends `python3 "$SOTA_SCRIPT"` with no argument. `check-alternatives.py` takes the
phase directory as an optional positional and, given none, resolves it from
`.planning/STATE.md`'s `current_phase` (`resolve_current_phase_dir`), then globs
`.planning/phases/` for the single directory carrying that number. The directory name is
read from the filesystem into Python and never reaches a shell.

That is the whole fix. The injection seam is gone because there is nothing left to quote,
not because the quoting improved.

**Do not reintroduce a splice.** gsd-core interpolates `${PHASE_DIR}` with a plain string
`replace` and hands the result to `sh -c`, so the manifest's quoting would again be the only
protection, and no quoting is sufficient. Every `sh` quoting context terminates on a
delimiter the value may contain, and a directory name may hold every byte but `/` and NUL:

- unquoted — any metacharacter;
- `"..."` — a double quote, and `$` and a backtick expand inside it anyway;
- `'...'` — an apostrophe. It does not end the literal into a syntax error; it ends it into
  code. Measured: `sh -c "python3 -c 'pass' '11-a'; touch PWNED; :'b'"` exits 127 having
  created `PWNED`. A previous version of this section claimed the opposite and was wrong.
- a quoted-delimiter heredoc — a line equal to the delimiter. It survives the apostrophe,
  which is why it looked like the way out, but a name containing a newline plus that
  delimiter line closes it early and the rest is parsed as commands. Pinned as
  `test-gate-script-resolution.sh` case3b.

Measured against the current constant command, with a compliant plan in each directory. The
control matters: the same gate exits `1` on `plan-missing-section.md`, so these `0`s are
verdicts, not a gate that failed to find anything.

| phase directory name | exit | side effect |
| --- | --- | --- |
| `11-a'; touch PWNED; :'b` | 0 | none |
| `11-o'$(touch PWNED)'brien` | 0 | none |
| ``11-x'`touch PWNED`'y`` | 0 | none |
| `11-r'\|touch PWNED\|\|:'s` | 0 | none |
| `11-t'>canary.txt;:'u` | 0 | none; `canary.txt` intact |
| `11-o'brien` | 0 | none |

`11-o'brien` exiting `0` is a behaviour change: it exited `2` before. The apostrophe
limitation is fixed, not documented away. A hostile name with a non-compliant plan still
exits `1`, so the name change did not cost the verdict.

### Residual: the gate now depends on gsd-core's workflow ordering

Phase identity comes from STATE.md rather than from the caller, which couples this gate to
the order in which gsd-core writes that file. `plan-phase.md:1524` is step 13b, "Record
Planning Completion in STATE.md"; the `plan:post` gate dispatch is step 13e at
`plan-phase.md:1558`. `current_phase` is therefore written before the gate runs, and at gate
time it names the phase just planned.

Every failure path is fail-closed, and `main()` maps each raise to exit `2`. Measured:

| condition | exit |
| --- | --- |
| no `.planning/STATE.md` | 2 |
| STATE.md with no `current_phase` | 2 |
| `current_phase` not matching `^\d+(\.\d+)?$` (traversal, metacharacters) | 2 |
| `current_phase` matching 0 directories | 2 |
| `current_phase` matching 2 directories | 2 |

Do not oversell that. Fail-closed covers the cases where the phase cannot be identified. It
does not cover the case where it is identified *wrongly*: if that 13b/13e ordering ever
changed, `current_phase` would name a different phase and the gate would check that one and
pass, with nothing to notice. The upstream fix is unchanged — pass the phase directory as an
argv element, tracked as `gsd-beads-g72`. Until then the coupling is real and this is where
it is written down.
