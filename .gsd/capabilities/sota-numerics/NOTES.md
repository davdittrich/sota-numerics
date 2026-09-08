# sota-numerics capability — deliberate divergences and anti-regression rules

This capability ships with a few choices that look wrong at a glance and will attract a
"fix" from a future contributor who reads only the surrounding code. Read this first.

## 1. `gates[0].onError` is `"halt"`, deliberately

See `capability.json`'s `gates[0].description` for the full argument: `onError` here is
deliberately `"halt"` so a malformed manifest (a bad predicate declaration or an unknown
predicate kind) can never pass silently, while every runtime outcome of the check command
itself already maps to a block verdict. By contrast, `contributions[].onError` on this
capability's four advisory fragments correctly stays `"skip"`, since those are non-blocking
steering text and a rendering failure there should never halt planning — the two values
differ because they govern differently-consequential failures, not because one is a mistake.
Do not "fix" `gates[0].onError` back to `"skip"` to match the contributions.

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
`plan-phase.md:1558`. Both positions re-derived 2026-09-08 against the installed gsd-core
1.13.0, not assumed from an earlier note. `current_phase` is therefore written before the
gate runs, and at gate time it names the phase just planned.

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

### Residual: the same step can be turned off, which silently disables this gate

This is a second, larger coupling than the ordering one above. Step 13e's own opening
sentence is: "Proactive, non-blocking coverage report gated on `workflow.post_planning_gaps`
(default `true`)." Step 13e is not only the gap-analysis capability's coverage report — it
is the *only* dispatch point for every `plan:post` gate any capability registers, this one
included. A project that sets `workflow.post_planning_gaps` to `false` never reaches step
13e at all, so this gate — declared blocking, `onError: "halt"`, sold in `plugin.json` and
`capability.json` as enforcing "on every plan in a phase" — never runs. There is no verdict,
no error, and nothing an operator turning that key off would see: `render-hooks plan:post`
still lists the gate as registered, but registration is not dispatch.

The key belongs to a different capability (`gap-analysis`), not to `sota-numerics`, so
nothing in this bundle can detect or refuse that state. The upstream fix is to decouple
`plan:post` gate/step/contribution dispatch from `gap-analysis`'s own report toggle, tracked
as `gsd-beads-h1pb`, alongside the ordering coupling above (`gsd-beads-g72`). Until then:
default is `true`, so a project that never touches `workflow.post_planning_gaps` is
unaffected, and this is where the exception is written down.

## 7. The case-insensitive-filesystem residual: verified against gsd-core 1.13.0, not a live divergence (gsd-beads-25vc.21.3 item 3)

`PLAN_FILE_RE` and `PLAN_SHAPED_RE` are both case-sensitive by design (section 3 above): a
file stored as `23-01-plan.md` matches neither, so it is invisible to this gate, not merely
misnamed. The comment above `PLAN_SHAPED_RE` used to assert, without checking, that
gsd-core's own `*-PLAN.md` glob would still read such a file on a case-insensitive
filesystem (macOS default, Windows) where this gate would not -- a real divergence, if true.
It is not true, measured against the two places in installed gsd-core 1.13.0 that actually
discover or read `.planning/phases/*/*-PLAN.md` content:

- `~/.claude/gsd-core/workflows/plan-phase.md:574` -- `ls "${PHASE_DIR}"/*-PLAN.md`
- `~/.claude/gsd-core/workflows/execute-plan.md:58` -- `(ls .planning/phases/XX-name/*-PLAN.md 2>/dev/null || true) | sort`,
  from which `$PLAN_PATH` is chosen (execute-plan.md:62, "find first PLAN without matching
  SUMMARY") and `$PHASE` derived (execute-plan.md:69), feeding every later `cat`/`grep` on
  `{phase}-{plan}-PLAN.md` (execute-plan.md:93, 98, 201, 400, 476).

Both discovery sites are a bare shell glob, not an explicit case-fold and not an
independently-constructed path. `ls`'s glob matches its pattern against the name `readdir`
returns -- the name as stored on disk -- using byte-for-byte `fnmatch`, which is
case-sensitive regardless of whether the underlying filesystem resolves `open()` calls
case-insensitively. A file stored as `23-01-plan.md` therefore does not match `*-PLAN.md` in
`ls`, on any platform GSD's bash-based workflows run on, for the same reason `PLAN_FILE_RE`
does not match it: same answer, no divergence. The later `cat {phase}-{plan}-PLAN.md` reads
look like the genuinely dangerous third category -- an open of a constructed canonical path,
which *would* case-fold a lowercase file on a case-insensitive filesystem -- but their
`{phase}`/`{plan}` values are always the ones the same glob already found in the same run;
the constructed path is never built from a source independent of that glob, so it can never
name a file the glob excluded. `~/.claude/gsd-core/bin/gsd-tools.cjs` has no plan-discovery
or plan-reading code of its own to check against either path: every `-PLAN.md` hit in it
(lines 69, 160, 173, 2624, 2639) is a doc comment or CLI help string, not executable
glob/readdir logic.

**Decision (accepted risk):** no macOS or Windows CI leg is added. Measured against gsd-core
1.13.0's source, there is no divergence for a second runner to catch -- it would exercise
only the filesystem's own case-folding half of the original claim, a half already shown
irrelevant here, buying a permanently-maintained runner for a residual with no artifact in
this repository and no review finding that has ever produced one.

**Reopens if:** a lowercase plan-named file (e.g. `23-01-plan.md`) is ever observed actually
present in a phase directory, or a future gsd-core release adds an explicit case-fold or an
independently-sourced constructed-path read to its plan discovery -- at which point this
section's citations are the ones to re-check first.
