# Changelog

## 0.2.0

**The gate changed in three narrow ways.** No rule about plan content moved:
same checks, same literals, and `capability.json` still declares exactly one
gate. Running this release's 55-test suite against the 0.1.3 checker, 52 pass
unchanged and 3 fail: the two empty-argument cases below, and one message.

An empty `${PHASE_DIR}` now prints a reason and exits `2`, which blocks. Under
0.1.3 the same call read the process working directory instead: run from a
phase directory holding one passing plan, it exited `0` on a phase nobody had
named.

The gate command now single-quotes the interpolated phase directory. gsd-core
splices `${PHASE_DIR}` in as text before handing the command to `sh -c`, so
under 0.1.3 a phase directory named with `$(...)` or a backtick ran that text
as a command; it no longer does. The trade is that a name containing `'` now
breaks the command as a shell syntax error and blocks, where 0.1.3 accepted
it. `NOTES.md` §6 records the measurements and why this is the better failure.

A plan file that is not valid UTF-8 still exits `2`, but the message changed.
0.1.3 printed the codec's own text — a byte offset and no path — so a phase
holding twenty plans named none of them. It now reads
`<plan_path>: not valid UTF-8 (<reason> at byte <n>); re-save the plan as UTF-8`.
No verdict changes; only the message.

Any plan the gate read under 0.1.3 it still judges the same way. Only a caller
that named no phase directory, or named one carrying shell metacharacters,
gets a different verdict.

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
A marketplace install is unaffected. Claude Code caches plugins both as depth-1
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
