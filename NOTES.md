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

Write `_SN` for `.gsd/capabilities/sota-numerics`. The gate
command keys on the global manifest: if `${GSD_HOME:-$HOME}/$_SN/capability.json` exists it
runs the global script and blocks if that script is missing; otherwise it runs `./$_SN`'s
script. gsd-core runs the check command at the runtime project root with the parent process's
environment inherited, so the project rung needs no Git at all. The version comparison that
used to let a project copy with an equal or higher `capability.json` version outrank the
global one is gone: a hostile repository could claim version 99.0.0 and the blocking gate
passed while running its code.

A third rung used to sit between these two, asking Git for the top level of the repository
enclosing the working directory and appending the script path to it, meant to widen the
project lookup to working directories below the project root. It is gone: that top
level is whatever repository encloses the *current working directory*, which is a directory
an attacker chooses, not the project gsd-core dispatches the gate from — a checker script
planted at the top of that enclosing repository would run in the project's place.
`tests/test-gate-script-resolution.sh` pins a repository enclosing the working directory,
carrying a hostile copy at the same relative path, and proves the gate never reaches it.

The project rung runs `./.gsd/capabilities/sota-numerics/scripts/check-alternatives.py` only when no global install exists. In that case any gate that runs at all came from the repository's own manifest, which the repository already controls, so the project script adds no new trust. With a global install present, gsd-core's own rule applies: a repo-dropped project capability is untrusted until consented (#1459), and the gate's direct script path does not bypass that.

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
regression -- it is in the repository checkout, which is the whole bundle. `planner-sota.md`, which does ship here, teaches the planner the same pairing rule. If
either is edited, update the other — they teach and enforce one rule from two seats.

## 6. The gate command is constant; the phase comes from STATE.md

`capability.json` interpolates nothing. `grep -c PHASE_DIR capability.json` is `0`, and the
command ends `python3 -I "$SOTA_SCRIPT"` with no argument. `check-alternatives.py` takes the
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
| `11-t'>canary.txt;:'u` | 0 | none; `canary.txt` intact |
| `11-o'brien` | 0 | none |

The `$(...)`, backtick and `|`-pipe variants also exit `0` with no side effect.

`11-o'brien` exiting `0` is a behaviour change: it exited `2` before. The apostrophe
limitation is fixed, not documented away. A hostile name with a non-compliant plan still
exits `1`, so the name change did not cost the verdict.

### Residual: the gate now depends on gsd-core's workflow ordering

Phase identity comes from STATE.md rather than from the caller, which couples this gate to
the order in which gsd-core writes that file. In `plan-phase.md` (gsd-core 1.16.0), step 13b,
"Record Planning Completion in STATE.md", precedes step 13e, the `plan:post` gate dispatch.
`current_phase` is therefore written before the gate runs, and at gate time it names the
phase just planned.

Every failure path is fail-closed, and `main()` maps each raise to exit `2`. Measured:

Each of these exits `2`: no `.planning/STATE.md`; STATE.md with no `current_phase`; a
`current_phase` not matching `^\d+(\.\d+)?$` (traversal, metacharacters); a `current_phase`
matching zero or two directories.

Fail-closed covers the cases where the phase cannot be identified. It
does not cover the case where it is identified *wrongly*: if that 13b/13e ordering ever
changed, `current_phase` would name a different phase and the gate would check that one and
pass, with nothing to notice. The upstream fix is unchanged — pass the phase directory as an
argv element. Until then the coupling is real and this is where
it is written down.

### Residual: `workflow.post_planning_gaps` does not gate this capability

Verified against gsd-core 1.16.0. Step 13e (`plan:post`) dispatches every registered
`plan:post` hook. The `workflow.post_planning_gaps` key (default `true`) is a `when`
condition on the first-party `gap-analysis` gate only, so setting it to `false` skips that
gate and leaves this one running. gsd-core states the rule in step 13e: an empty
`activeHooks` list is the only reason to skip the step silently.

Earlier gsd-core releases tied the skip to the gap-analysis toggle (upstream #3606), so
the capability's `engines.gsd` floor is `>=1.16.0`, the only release verified.

## 6a. Known limits and their rationale

The gate checks structure, not meaning, and stays a line-oriented scan rather than a Markdown parser. Hidden HTML blocks are read as text because modelling every CommonMark HTML block kind buys nothing against an author who wants to hide text from a reviewer in plain sight. NFKC folding covers compatibility forms (full-width, ligatures) and not cross-script lookalikes, which need a confusables table; the effect is two entries counted where a reader sees one. A symlinked phase directory is refused so the gate never validates a tree outside `.planning/phases/`. Setext section headings are unsupported because the section must be found by one anchored line scan. A zero-plan phase resolved from STATE.md blocks with exit `2`: `plan:post` runs after planning, so an empty phase means STATE.md named the wrong phase (see §6) or the planner wrote nothing.

## 7. Case-insensitive filesystems: no divergence between this gate and gsd-core

`PLAN_FILE_RE` is case-sensitive, and so is gsd-core's plan discovery. `PLAN_SHAPED_RE`
adds one case-insensitive exception: a phase-numbered name such as `23-01-plan.md` is
reported as misnamed instead of ignored.

Verified against gsd-core 1.16.0. Two workflows discover plans, `plan-phase.md` and
`execute-plan.md`, and both use a bare shell glob (`ls .../*-PLAN.md`). `ls` matches the
pattern against the name `readdir` returns, byte for byte, so `23-01-plan.md` does not match
`*-PLAN.md` on any platform GSD's bash workflows run on. This is the same answer
`PLAN_FILE_RE` gives. Later reads of `{phase}-{plan}-PLAN.md` use values taken from the
same glob, so they never name a file the glob excluded. `gsd-tools.cjs` has no plan
discovery of its own.

**Decision (accepted risk):** no macOS or Windows CI leg. There is no divergence for a second
runner to catch.

**Reopens if:** a lowercase plan-named file is observed in a phase directory, or gsd-core
adds an explicit case-fold or an independently built plan path to its discovery. Re-check
the two glob sites first.
