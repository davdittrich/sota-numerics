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
publishes the bundle to every project on the machine, so the `SessionStart` and
`SubagentStart` hook now installs only bytes it can show are already published.
A marketplace install is unaffected. Claude Code caches plugins both as depth-1
git clones and as plain directories. The plain form has no repository over it,
so the check does not apply. The clone form is tracked, so the check applies and
passes: the clone is clean, and its `HEAD` is the published tip it was cloned
from. The host's own `.in_use/` and `.orphaned_at` bookkeeping sits at the
plugin root, three directories above the bundle, outside the scope of the
uncommitted-or-ignored test.

A refusal reaches you in two situations: an environment fault, or running this
plugin from a git checkout that tracks the bundle — a development clone or
worktree. There are eight, on stderr once a
session. Committing and pushing clears these three:

```text
capability-auto-install: sota-numerics bundle has uncommitted or ignored files; refusing to install it at global scope
capability-auto-install: sota-numerics bundle has no origin/HEAD or origin/main to prove it is published; refusing to install it at global scope
capability-auto-install: sota-numerics bundle HEAD is not published (not an ancestor of <ref>); refusing to install it at global scope
```

The other five are faults in the environment, the bundle's permissions, or the
index, and committing does nothing for any of them:

```text
capability-auto-install: the sota-numerics bundle directory could not be read in full, so what the global mirror would receive cannot be verified; refusing to install it at global scope
capability-auto-install: git is unusable, so sota-numerics bundle provenance cannot be verified; refusing to install it at global scope
capability-auto-install: git cannot read the repository holding the sota-numerics bundle, so its provenance cannot be verified; refusing to install it at global scope
capability-auto-install: git could not report the state of the sota-numerics bundle, so its contents cannot be verified; refusing to install it at global scope
capability-auto-install: the index marks sota-numerics bundle entries assume-unchanged or skip-worktree, so git will not report edits to them; refusing to install it at global scope
```

`could not be read in full` means the walk over the bundle hit a directory it
could not enter; make the bundle readable and searchable to the user that runs
the session. `git is unusable` means no working `git` on `PATH`; install one.
`cannot read the repository` means git found one and declined to open it — most
often a root- or service-installed plugin, a shared checkout, or a container UID
remap, where git rejects the checkout for dubious ownership; add a
`safe.directory` entry, or re-install the plugin as the user that runs the
session. `could not report the state` means `git status` failed outright, so the
worktree bytes are unknown; repair the repository with `git fsck` or re-clone
it. `the index marks` means the index was told to stop watching bundle files;
`git update-index --no-assume-unchanged` (or `--no-skip-worktree`) on the
flagged paths clears it. Of the eight, only `could not be read in full`,
`git is unusable` and `cannot read the repository` can reach an install no
repository tracks; the other five are decided inside a tracked bundle.
README's "What the Claude hooks do" tabulates all eight
with their remedies.

The hook then installs nothing and records nothing, so the next session retries.
The ignored-files case catches contributors by surprise: running the test suite
leaves `__pycache__/` inside the bundle, which `git status` reports as clean
while a directory copy would still publish it. Delete it and reopen the session.
