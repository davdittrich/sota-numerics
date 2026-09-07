# Changelog

## 0.2.0

**The gate did not change.** `scripts/check-alternatives.py` is behaviourally
identical to 0.1.3 — same checks, same literals, same control flow — and
`capability.json` still declares exactly one gate. Every plan that passed
`plan:post` under 0.1.3 still passes. Nothing to re-check, nothing to fix.

**Steering covers more ground.** All four advisory fragments changed. Between
them they now also steer toward internal and project consistency, unambiguity,
completeness, efficiency, and code that stays quiet when an agent runs it; the
table at the top of the README says which role gets which. These are advisory:
no gate enforces them, and none was added.

**The automatic global install can now refuse.** Installing at global GSD scope
publishes the bundle to every project on the machine, so the `SessionStart` and
`SubagentStart` hook now installs only bytes it can show are already published.
Whether this reaches a marketplace install depends on your host. Claude Code
has cached plugins both as depth-1 git clones and as plain directories. Only
the clone form is tracked, and only a tracked bundle is checked; on that form
the check refuses, because the plugin host's own `.in_use/` and `.orphaned_at`
bookkeeping sits inside the bundle uncommitted. README's "What the Claude
hooks do" gives the manual install that gets past it.

It applies when you run this plugin from a git checkout that tracks the bundle —
a development clone or worktree. Expect one of these on stderr each session
until you commit and push:

```text
capability-auto-install: sota-numerics bundle has uncommitted or ignored files; refusing to install it at global scope
capability-auto-install: sota-numerics bundle has no origin/HEAD or origin/main to prove it is published; refusing to install it at global scope
capability-auto-install: sota-numerics bundle HEAD is not published (not an ancestor of <ref>); refusing to install it at global scope
capability-auto-install: git is unusable, so sota-numerics bundle provenance cannot be verified; refusing to install it at global scope
```

The hook then installs nothing and records nothing, so the next session retries.
The ignored-files case catches contributors by surprise: running the test suite
leaves `__pycache__/` inside the bundle, which `git status` reports as clean
while a directory copy would still publish it. Delete it and reopen the session.
