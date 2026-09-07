# Changelog

## 0.2.0

**The gate changed in four narrow ways.** `capability.json` still declares
exactly one gate, and the rules about what a plan must contain are unchanged --
with one exception, the fenced-code-block fix below, which changes verdicts.
Running this release's full 78-test suite against the 0.1.3 checker, 59 pass
unchanged and 19 fail: 7 phase-resolution cases, 9 section-boundary cases
(fenced regions, HTML comments, and the ATX, indented and setext heading
boundaries), the two empty-argument cases, and one error-message case. Those 19
are the behaviour this release changes; every other test passes against both.

An empty phase-directory argument now prints a reason and exits `2`, which
blocks. Under 0.1.3 the same call read the process working directory instead:
run from a phase directory holding one passing plan, it exited `0` on a phase
nobody had named.

The gate command no longer carries the phase directory at all. gsd-core
splices `${PHASE_DIR}` in as text before handing the command to `sh -c`, so
under 0.1.3 a phase directory named with `$(...)`, a backtick, or an apostrophe
could run that text as a command -- and a payload could exit `0` while doing
it, so the blocking gate reported success on a phase that had just executed
arbitrary code. The command is now constant, and `check-alternatives.py`
resolves the phase from `.planning/STATE.md` itself, so the name never reaches
a shell. No quoting fix was available: every `sh` quoting context ends on a
delimiter a directory name may contain.

A directory named `11-o'brien` now exits `0`. Under 0.1.3 it exited `2`: the
apostrophe limitation is fixed, not merely documented. In exchange the gate now
depends on gsd-core writing `current_phase` before it dispatches `plan:post`.
`NOTES.md` §6 records the measurements, the fail-closed paths, and that
coupling.

Fenced code blocks no longer count as plan content. Under 0.1.3 an
`## Alternatives Considered` section that existed only inside a ```` ```markdown ````
fence satisfied the gate, and bullets or table rows inside a fence counted as
real mechanism entries. A plan quoting an example in its README-style prose
could therefore pass on the example's own text. **This changes verdicts: a plan
that passed under 0.1.3 may now fail.** That is the intended direction for a
blocking gate, and it matters more on this release than before it, because the
README now ships four fenced examples for authors to copy.

A plan file that is not valid UTF-8 still exits `2`, but the message changed.
0.1.3 printed the codec's own text — a byte offset and no path — so a phase
holding twenty plans named none of them. It now reads
`<plan_path>: not valid UTF-8 (<reason> at byte <n>); re-save the plan as UTF-8`.
No verdict changes; only the message.

Plans whose `Alternatives Considered` content sits outside code fences are
judged exactly as before. A plan that relied on fenced text to satisfy the
gate now fails, and a caller that named no phase directory, or named one
carrying shell metacharacters, gets a different verdict.

**Steering covers more ground.** All four advisory fragments changed. Between
them they now also steer toward internal and project consistency, unambiguity,
completeness, efficiency, and code that stays quiet when an agent runs it; the
table at the top of the README says which role gets which. These are advisory:
no gate enforces them, and none was added.

**The automatic global install can now refuse.** Installing at global GSD scope
publishes the bundle to every project on the machine, so where a repository
tracks the bundle, the `SessionStart` and `SubagentStart` hook now installs only
bytes it can show are already published. Where no repository tracks the bundle
there is nothing to check against, and those bytes install unverified.
A marketplace install is not protected by it in every form. Claude Code caches plugins both as depth-1
git clones and as plain directories. The plain form has no repository over it,
so the check does not apply. The clone form is tracked, so the check applies and
passes: the clone is clean, and its `HEAD` is the published tip it was cloned
from. The host's own `.in_use/` and `.orphaned_at` bookkeeping sits at the
plugin root, three directories above the bundle, outside the scope of the
uncommitted-or-ignored test.

A refusal reaches you in two situations: an environment fault, or running this
plugin from a git checkout that tracks the bundle — a development clone or
worktree. It goes to stderr once per hook run — and the hook runs on session
start and again on each `gsd-planner`, `gsd-executor` and `gsd-verifier`
subagent spawn. No refusal records the bundle hash, so a refusal repeats on
every one of those until you clear it. README's "What the Claude hooks do"
tabulates every refusal, the stderr it prints, and what clears it.

The hook then installs nothing and records nothing, so the next session retries.
The ignored-files case catches contributors by surprise: running the test suite
leaves `__pycache__/` inside the bundle, which `git status` reports as clean
while a directory copy would still publish it. Delete it and reopen the session.
