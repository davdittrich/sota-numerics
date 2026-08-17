# sota-numerics

SOTA-research/numerical-stability advisory steering across gsd's plan/execute/verify/ship lifecycle, plus a blocking plan:post gate that mechanically enforces a compliant Alternatives Considered section on every plan in a phase

## What it does

`sota-numerics` is a [gsd-core](https://github.com/open-gsd/gsd-core) capability — an
installable overlay, not a fork — with two distinct halves.

The first half is advisory: it injects SOTA-research, efficiency, and numerical-stability
steering fragments at four gsd lifecycle points — the planner at `plan:pre`, the executor at
`execute:wave:pre`, the verifier at `execute:wave:post`, and the orchestrator at `ship:pre`.

The second half is not advisory, and is not buried here: a **blocking `plan:post` gate** runs
the bundled Alternatives-Considered checker over every `*-PLAN.md` file directly inside a phase
directory and fails the plan step when a plan is non-compliant. A compliant plan needs a
`## Alternatives Considered` heading, at least two bold-named alternatives (`- **Name**: ...`)
each carrying a URL or backticked doc-ref citation with a year inside the recency window, and a
`Decided by:` line naming one of performance, simplicity, LOC, ecosystem, or maintenance as the
ranked criterion that decided the pick. A plan making no real mechanism choice may instead write
the exemption line `N/A — no mechanism choice` as the whole section body.

## Requirements

- Bash (POSIX shell)
- Python 3 (standard library only)
- git — the `plan:post` gate resolves its own script path via `git rev-parse --show-toplevel` in
  the consuming project
- gsd-core >= 1.10.0

## Install

```bash
claude plugin marketplace add davdittrich/gsd-beads
claude plugin install sota-numerics@gsd-beads -y
```

The marketplace stays hosted at `davdittrich/gsd-beads` even though this plugin lives in its own
repo — the marketplace entry just points here.

## Uninstall

```bash
claude plugin uninstall sota-numerics -y
```

## Caveats

- **The `plan:post` gate is blocking, and its `onError` disposition is `halt`** — deliberately
  unlike the `skip` used by all four advisory contributions. A gate whose own checker cannot run
  must not silently pass.
- **The gate resolves its script from the CONSUMING project's git root**, under
  `.gsd/capabilities/sota-numerics/scripts/check-alternatives.py`, so the capability bundle has
  to be installed into that project — the `SessionStart` hook re-grants it at user scope on every
  session start — or the gate halts with the explicit message the gate command itself prints.
- **One config key**, `sota-numerics.enabled` (boolean, default `true`), read from a project's
  `.planning/config.json`, toggles BOTH the four advisory fragments and the blocking gate.
- **The checker reports only the first offending alternative per plan**, by design — it is a
  structural backstop, not a linter.
- **Installing through the marketplace copies the cloned repo into the installer's local plugin
  cache** under `~/.claude/plugins/cache/` — documented Claude Code behavior this repo does not
  control.

## License

MIT — see [LICENSE](LICENSE).

## gsd-core

`sota-numerics` is a capability for [gsd-core](https://github.com/open-gsd/gsd-core).
