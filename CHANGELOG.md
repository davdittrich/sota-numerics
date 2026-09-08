# Changelog

## 0.2.0

**The gate's rules for what a plan must contain are unchanged; how it finds and
reads that plan changed a good deal.** `capability.json` still declares exactly
one gate, and no check, threshold or regex about plan CONTENT was added or
relaxed. What changed is where the section is considered to start and stop
(fenced regions, HTML comments, and ATX, indented and setext headings), which
phase gets inspected at all, which files count as plans, and what the failure
messages say. Those do change verdicts, and the sections below give each one.
Measured at `253bbdc` against the 0.1.3 checker: the phase-resolution cases
(`current_phase`, the two-witness agreement, and the apostrophe path), the
section-boundary cases (fenced regions and the ATX, indented and setext
heading boundaries), the HTML-comment cases, the rejected-plan-name cases,
the empty-argument cases, and the error-message case all change verdict
between the two checkers. Every other test in the suite passes against both.

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

**The SubagentStart banners now point at their fragment instead of copying it.**
The planner, executor, and verifier banners named their fragment's contributions
verbatim, in the same context window the fragment is already injected into; they
now name the fragment instead. This gives up a failsafe: each contribution
declares `onError: skip`, so a contribution that fails to render fails silently,
and on such a failure the subagent now learns only that the capability is active
and the step carries a blocking gate, not what the gate wants.

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
The ignored-files case catches contributors by surprise: running
`python3 -m check-alternatives` instead of running the script directly leaves
a bytecode-cached `__pycache__/` inside the bundle, and the guard's
`git status --ignored` flag is exactly why it catches this. Delete it and
reopen the session.

The bundle digest's record format changed: each walk entry now emits a
kind-tagged, escaped line instead of the old `path -> target` and raw
`sha256sum`/`shasum` output, closing a collision where a symlink's target
could carry bytes indistinguishable from another entry's line. The first
session after upgrading therefore sees a hash mismatch against the old-format
sidecar and reinstalls once; that reinstall is expected, not drift.

The install itself now runs under a 60-second bound (`timeout`, falling back
to `gtimeout`), rather than inline and unbounded in the `SessionStart` and
`SubagentStart` hooks. A killed install is reported on stderr and leaves the
hash state unwritten, so a later session retries; a host with neither binary
runs the install unbounded, the prior behaviour.

The recorded-hash sidecar file is now unlinked and recreated on a successful
install rather than written through, so a symlink planted at its path is
replaced instead of followed -- a planted link could previously redirect the
write to overwrite whatever file the link pointed at.

A plan discussing the `<!--` HTML-comment syntax in its own prose (for
example, inside a backtick-delimited code span) no longer has the rest of the
plan blanked to EOF. Under the previous scan a single unprotected `<!--`
candidate, however it appeared on the page, masked everything after it, so a
compliant `## Alternatives Considered` section written below such a mention
was invisible to the gate and the plan blocked on a false "missing section".
A `<!--` that genuinely opens a comment -- including one sharing a line with
an unrelated code span -- still masks exactly as before; only a candidate
that CommonMark itself renders as literal text is now skipped.

A symlinked entry under `.planning/phases/` is no longer matched during
phase-directory discovery. `entry.is_dir()` follows symlinks, so a symlinked
phase directory used to resolve to a directory anywhere on the filesystem and
have its plan filenames validated against `current_phase` -- a real traversal
out of the tree this gate is scoped to, though low impact: only names are
matched and validated, never file content. A real (non-symlink) phase
directory at the same number is unaffected.

A plan-shaped path that cannot be read as a file -- most commonly a directory
named like a plan, such as `mkdir 01-01-PLAN.md` -- now exits `2` with the
same `check-alternatives.py: <path>: <reason>` message every other exit-`2`
case uses, instead of an uncaught `IsADirectoryError` traceback on stderr.
**This changes a verdict, not just a message**: the previous behavior was
exit `1` with no `remediation:` line, byte-identical in blocking effect
(non-zero always blocks) but reached through a raw Python traceback rather
than the module's own diagnostic contract. A permission failure on an
otherwise-valid plan file reports through the same path.
