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

### Why a gate, not just guidance

This gate exists because of how coding agents fail, not how humans do. The plans it checks
are usually written by an LLM, and an LLM's failure mode when picking a mechanism is
architecturally different from a person's.

Autoregressive decoding commits early. Once a model has written "I'll use X," every later
token conditions on that choice — there's no backtracking without an explicit scaffold
forcing it to generate and weigh other candidates first. This isn't a hypothesis: on
SWE-bench Verified, Meta's CWM went from 58.4% resolved picking the majority answer across
sampled patches to 65.8% resolved by generating multiple candidates and selecting the best
one with test-based verification — same model, same problems, the only difference is whether
it compared options before committing.¹ The wider pass@k literature for coding agents shows
the same shape: more candidates, compared rather than accepted on the first try, solve more
problems.²

Coding agents also inherit sycophancy from RLHF training — a documented tendency to run with
whatever framing the prompt already contains instead of pushing back on it.³ In an agentic
pipeline, that compounds: a planner that locks onto the first mechanism it considered hands
that choice downstream as settled fact, and nothing later in the chain re-opens it.⁴ A model
asked to judge or pick between options on its own is also measurably swayed by which one it
sees first — position bias in LLM-as-judge setups is well replicated.⁵ Naming and comparing
alternatives up front is a direct counter to both: it forces the search that autoregressive
generation skips by default, and it puts competing options in front of the model instead of
one option it's already inclined to defend.

None of this means more candidates always win. Sampling more solutions without comparing them
well can hurt: one ICLR 2024 study found that adding self-repair attempts on top of extra
initial samples dropped the pass rate below the plain sampling baseline — quantity without a
real comparison step made results worse, not better.⁶ That's the actual argument for a gate
over a suggestion: the failure mode isn't "the agent didn't generate enough options," it's
"the agent generated one option and moved on." A structural check that a plan names ≥2 real
alternatives and states why one won closes exactly that gap, without pretending more sampling
is free.

One piece of the older framing still holds regardless of who's doing the planning: Boehm's
cost-of-change curve. A wrong mechanism caught at plan time is far cheaper to fix than the
same mistake found after the code ships — that's a property of the software delivery
process, not of the reasoner making the choice.

---

¹ CWM: An Open-Weights LLM for Research on Code Generation with World Models (Meta, 2025) — https://arxiv.org/pdf/2510.02387
² e.g. DARS: Dynamic Action Re-Sampling to Enhance Coding Agent Performance (2025) — https://arxiv.org/pdf/2503.14269
³ Sharma et al., Towards Understanding Sycophancy in Language Models (2023) — https://arxiv.org/abs/2310.13548
⁴ The Landscape of Agentic Reinforcement Learning for LLMs: A Survey (2025) — https://arxiv.org/pdf/2509.02547
⁵ Wang et al., Large Language Models are not Fair Evaluators (2023) — https://arxiv.org/abs/2305.17926
⁶ Is Self-Repair a Silver Bullet for Code Generation? (ICLR 2024) — https://proceedings.iclr.cc/paper_files/paper/2024/file/9ddc141bdbf9d1db510cefff56c586ad-Paper-Conference.pdf

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
