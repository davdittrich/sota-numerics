# sota-numerics

Make GSD compare mechanisms before execution, then keep numerical precision and measured performance visible through shipping.

`sota-numerics` is an installable [gsd-core](https://github.com/open-gsd/gsd-core) capability, not a fork. It adds four advisory prompts and one blocking plan gate.

## What it changes

| GSD point | Target | Behavior |
| --- | --- | --- |
| `plan:pre` | planner | Research current mechanisms, compare real alternatives, cite them, rank the decision by performance, simplicity/LOC, ecosystem support, then maintenance cost, write code that goes with the grain of the project's existing conventions, and give every task a bound the executor can check. |
| `plan:post` | gate | Block when an eligible plan lacks the required `Alternatives Considered` structure. |
| `execute:wave:pre` | executor | Derive numeric parameters from the problem, keep the arithmetic stable, name the ceiling of any precision tradeoff, and hold agent-run code and agent-facing prose to the **quiet** and **legible** bars the executor fragment defines. |
| `execute:wave:post` | verifier | Flag:<br>- drift from the chosen mechanism;<br>- dropped edge cases;<br>- unstable substitutions;<br>- unexplained constants;<br>- unsupported performance claims;<br>- an unreachable or unwritten branch;<br>- an argument whose accepted values are undocumented at its definition;<br>- agent-invoked code that is not quiet;<br>- prose that is not legible;<br>- code that does not go with the grain of the project's conventions. |
| `ship:pre` | orchestrator | Check that precision, efficiency, quiet-output, and legibility claims have measurements or sources, that claims of going with the grain of project convention name the convention followed, and that accepted simplifications state where they break. |

The four prompts are advice. A rendering failure skips that prompt and does not stop the workflow. The `plan:post` check is different: it is blocking, and a missing interpreter, missing script, crash, or 30-second timeout halts planning.

## Install

### Claude Code

```bash
claude plugin marketplace add davdittrich/gsd-beads
claude plugin install sota-numerics@gsd-beads -y
```

### Codex

```bash
codex plugin marketplace add davdittrich/gsd-beads
codex plugin add sota-numerics@gsd-beads
```

The marketplace is `davdittrich/gsd-beads`; its `sota-numerics` entry points at this repository.

The GSD capability itself declares support for every GSD runtime. Automatic startup installation and role banners come from Claude's `SessionStart` and `SubagentStart` hooks. On any host, including one where those hooks never ran, the gate can use a capability bundle at either of these locations:

1. `<project>/.gsd/capabilities/sota-numerics`
2. `${GSD_HOME:-$HOME}/.gsd/capabilities/sota-numerics`

The project copy wins when both exist.

### What the Claude hooks do

At startup, resume, clear, or compaction, the plugin checks the whole capability bundle's hash. It installs the bundle at global GSD scope only when that hash changed. The same hook prints a short steering banner when the capability is enabled and its config lookup succeeds.

A global install publishes those bytes to every project on the machine, so the hook installs only bytes the bundle's own repository records as published. It reads that from the local `origin/HEAD` or `origin/main` ref; it does not contact the remote, so a session start never waits on the network and never fails offline. Anyone who can write that ref can therefore satisfy the check — the guard is aimed at running a plugin out of a development worktree by accident, not at an adversary with write access to your own repository. Every refusal names its reason on stderr, installs nothing, and leaves the recorded hash unwritten, so a later session retries. There are eight. The first is a precondition on reading the bundle at all and applies to every install; the rest are the publication check, which applies only to a tracked bundle.

| It refuses when | stderr says | What clears it |
| --- | --- | --- |
| The bundle directory cannot be walked in full, so the bytes a global mirror would receive are unknown. | `the sota-numerics bundle directory could not be read in full, so what the global mirror would receive cannot be verified` | Make the bundle readable and searchable to the user that runs the session. |
| No working `git` is on `PATH`. | `git is unusable, so sota-numerics bundle provenance cannot be verified` | Install `git`. |
| Git finds the repository holding the bundle and declines to open it — a root- or service-installed plugin, a shared checkout, a container UID remap. | `git cannot read the repository holding the sota-numerics bundle, so its provenance cannot be verified` | Add a `safe.directory` entry for the checkout, or re-install the plugin as the user that runs the session. |
| `git status` itself fails, so nothing can be said about the worktree bytes. A repository missing the object behind `HEAD`'s tree does this: `status` exits non-zero having printed nothing, while `ls-files` and `merge-base` still answer from the index and the commit objects. | `git could not report the state of the sota-numerics bundle, so its contents cannot be verified` | Repair the repository — `git fsck`, or re-clone it. |
| The index is marked `assume-unchanged` or `skip-worktree` for bundle entries, so git will not report edits to them. | `the index marks sota-numerics bundle entries assume-unchanged or skip-worktree, so git will not report edits to them` | Clear the bit: `git update-index --no-assume-unchanged <paths>`, or `--no-skip-worktree`. |
| The bundle holds uncommitted or gitignored files. | `sota-numerics bundle has uncommitted or ignored files` | Commit them. Running the test suite trips this: it leaves `__pycache__/` inside the bundle, which `git status` calls clean but a directory copy would still publish. Delete it. |
| Neither `origin/HEAD` nor `origin/main` exists to prove publication. | `sota-numerics bundle has no origin/HEAD or origin/main to prove it is published` | Add the remote and fetch it. |
| The bundle's `HEAD` is not an ancestor of that ref. | `sota-numerics bundle HEAD is not published (not an ancestor of <ref>)` | Push. |

The check consults only a repository that *tracks* the bundle; one that merely encloses it says nothing about these bytes. Whether a marketplace install is tracked depends on the host. Claude Code has materialised plugin caches both as depth-1 git clones and as plain directories, and both forms exist side by side in a single cache today. A plain directory has no repository over it, so the check does not apply and the install proceeds. A clone is tracked, so the check applies — and it passes: the clone is clean, and its `HEAD` is the published tip it was cloned from. The plugin host's own `.in_use/` and `.orphaned_at` bookkeeping sits at the plugin root, three directories above the bundle, and the uncommitted-or-ignored test is scoped to the bundle, so it never sees them. Either way the capability installs; a marketplace consumer installs nothing by hand.

Planner, executor, and verifier subagents receive role-specific banners. A normal session start uses the generic SOTA/numerics banner; calling the script directly with an unknown role falls back to that same text. Other subagent roles do not trigger this plugin's `SubagentStart` hook.

Auto-install runs before the plugin reads `sota-numerics.enabled`. Disabling the capability silences its banners and turns off its GSD contributions and gate; it does not stop the startup install check.

The installer needs either `sha256sum` or `shasum` and a resolvable `gsd-tools` provider. Resolution checks the current repository's `gsd-core/bin/gsd-tools.cjs`, a `gsd-tools` command on `PATH`, then `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs`. If no hash tool exists, installation exits quietly. If no provider resolves or installation fails, the hook reports the error and leaves the hash state unwritten so a later session can retry. A missing provider defaults the banner setting to `true`; any other config-read failure prints a warning and suppresses the banner for that invocation.

## Configure

One project setting controls the capability:

```json
{
  "sota-numerics": {
    "enabled": false
  }
}
```

The default is `true`. GSD reads the setting from `.planning/config.json`.

## The plan gate

The checker reads direct child files whose names match these shapes:

```text
11-01-PLAN.md
10.1-02-PLAN.md
```

Both numeric segments are required; the phase segment may contain one decimal point. Nested plans and names such as `draft-PLAN.md` are ignored. Every matching plan is checked in sorted order. A directory with no matching plans passes.

Each matching plan needs a level-two heading named `Alternatives Considered`. Matching is case-insensitive. The heading may carry a suffix such as `(REQ-10)`, but another word cannot be joined directly to `Considered`. The section ends at the next level-two heading or at end of file.

### Accepted entries

Use at least two bold-named bullets:

```markdown
## Alternatives Considered

- **Householder QR**: avoids normal-equation amplification. `NumPy QR docs` (2026).
- **Pivoted LU**: fast dense-system baseline. https://docs.scipy.org/ (2025).

Decided by: performance — QR is the stable first choice.
```

`-` and `*` bullets both work. The parser requires the bold name; a colon after it is conventional but optional. A bullet's evidence normally runs until the next recognized bullet or the end of the section. The exact internal marker also ends a preceding mechanism span, and a peer level-three heading ends a span only after that marker activated internal scope; unrelated level-three headings on a no-marker path do not truncate evidence.

A framed Markdown table also works when it has a header, a separator row, and bold-named body rows:

```markdown
## Alternatives Considered (REQ-10)

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Householder QR** | `NumPy QR docs` (2026) |
| 2 | **Pivoted LU** | https://docs.scipy.org/ (2025) |

Decided by: performance — QR is the stable first choice.
```

Table evidence is confined to its row. The header and separator never count as alternatives. Bullets and table rows are fallback formats, not additive: two recognized mechanism bullets take precedence; internal bullets do not affect this choice. Otherwise the checker tries the table and does not combine the two forms to reach the minimum.

### Internal design alternatives

Project-local design reasoning may follow the exact third-level heading `### Internal design alternatives` while mechanism alternatives remain in the surrounding level-two section. The spelling is case-sensitive and requires exactly one ordinary space after `###`; trailing spaces or tabs are allowed.

```markdown
## Alternatives Considered

- **Householder QR**: avoids normal-equation amplification. `NumPy QR docs` (2026).
- **Pivoted LU**: fast dense-system baseline. https://docs.scipy.org/ (2025).

### Internal design alternatives

- **Flat helper layout**: keeps the existing parser cohesive.
- **Separate helper module**: isolates local structure at the cost of another file.

Decided by: performance — QR is the stable first choice.
```

Internal entries need no external citation or date, do not count toward the two mechanism alternatives, and cannot lend evidence to a mechanism entry. They may use the same bold-named bullet or framed-table shapes. A peer level-three heading, including a bare `###`, ends internal scope. Mechanism entries outside the exact subsection retain every citation, date, count, and `Decided by:` requirement above.

Each parsed mechanism entry must contain:

- an `http://` or `https://` URL, or a single-line backticked reference; the parser accepts 1–300 characters after the URL scheme or inside the backticks;
- at least one four-digit year from the current year through six years earlier, counting both endpoints.

An older foundational year is allowed when the same entry also carries an in-window year. The checker rejects the exact URL authority strings `example.com`, `example.org`, `example.net`, and `localhost`, plus backticked references containing only `TODO` or `TBD`. The authority check includes a port, so `example.com:443` does not match `example.com`; this is a narrow placeholder filter, not URL verification.

The section also needs `Decided by:` followed by text beginning with one of these tokens:

- `performance`
- `simplicity`
- `LOC`
- `ecosystem`
- `maintenance`

The criterion matcher has no trailing word boundary, so a longer string such as `performanceXYZ` also passes. The check is structural. It does not open URLs, prove that a source exists, link a year to a specific citation, judge the comparison, or confirm that the stated criterion really decided the choice.

### No mechanism choice

When a plan makes no mechanism choice, the first nonblank section line can be:

```markdown
N/A — no mechanism choice
```

The checker accepts a hyphen or em dash and stops validating that section once this first line matches. Keep the section to that line unless extra text serves a clear purpose.

### Failures and recovery

The checker reports one reason per failing plan, but it checks every matching plan in the directory. It then prints one recovery command:

```text
remediation: fix the plans above, then re-run /gsd-plan-phase <phase> --force
```

Handled outcomes use these exit codes:

- `0`: all matching plans pass, or no matching plans exist;
- `1`: one or more plans violate the gate;
- `2`: the phase path argument is empty, is not an existing directory, has no `.planning`
  ancestor within ten levels, or a matching plan file is not valid UTF-8. The decode
  failure names the offending plan, the decode reason, the byte offset, and the remedy:
  `<plan_path>: not valid UTF-8 (invalid start byte at byte 36); re-save the plan as UTF-8`.

Other unexpected filesystem errors are not converted to `2`; they escape as Python errors, exit `1`, and the gate blocks without printing the `remediation:` line. Plan discovery matches names without a separate file-type check, so a directory with a plan-shaped name takes this path, as does a plan file the process cannot read.

You can run the checker directly:

```bash
python3 .gsd/capabilities/sota-numerics/scripts/check-alternatives.py .planning/phases/11-example
```

Under the current gsd-core plan workflow, `plan:post` runs after the plan commit. The plan checker should catch a bad section earlier; this gate is the fail-closed backstop.

If the gate script is absent from both project and global scope, the gate exits with a direct installation error instead of silently passing.

## Requirements

- Bash. The hooks use Bash arrays and `[[ ... ]]`; they are not POSIX `sh` scripts.
- Python 3. The checker uses only the standard library and launches no child processes.
- gsd-core 1.10.0 or newer.
- Git. The project-scope gate lookup uses it, and a global-only install still works when that lookup fails. Claude's automatic global install also uses it to show the bundle is already published, and refuses to install when Git cannot answer.
- `sha256sum` or `shasum`, plus one of the three `gsd-tools` resolution paths described above, for Claude's automatic global install.

## Update or remove

Claude Code:

```bash
claude plugin marketplace update gsd-beads
claude plugin update sota-numerics@gsd-beads --scope user -y
claude plugin uninstall sota-numerics@gsd-beads --scope user -y
```

Codex:

```bash
codex plugin marketplace upgrade gsd-beads
codex plugin add sota-numerics@gsd-beads
codex plugin remove sota-numerics@gsd-beads
```

## Why block the plan

This gate exists because of how coding agents fail, not how humans do. The plans it checks are usually written by an LLM, and an LLM's failure mode when picking a mechanism is architecturally different from a person's.

Autoregressive decoding commits early. Once a model has written “I'll use X,” every later token conditions on that choice. There is no backtracking without an explicit scaffold that forces it to generate and weigh other candidates first. On SWE-bench Verified, Meta's CWM resolved 58.4 percent of tasks by taking the majority answer across sampled patches and 65.8 percent by selecting among candidates with generated tests: same model, same problems, different selection method (FAIR CodeGen team et al. 2025). DARS likewise improves coding-agent performance by branching from earlier states, generating alternatives, and selecting among them instead of accepting a single trajectory (Aggarwal et al. 2025).

Coding agents also exhibit sycophancy, a documented tendency to follow the prompt's framing instead of pushing back on it; human-feedback training may help produce that behavior (Sharma et al. 2023). Agentic systems turn model outputs into later inputs, so a planner's early choice can become downstream context; this is an inference from the multi-step architecture surveyed by Zhang et al. (2025), not a result established by that survey. A model asked to judge or pick between options can also be swayed by which one it sees first, as Wang et al. (2023) demonstrate in LLM evaluation. Naming and comparing alternatives up front counters both risks. It forces the search that autoregressive generation skips by default and puts competing options in front of the model before it starts defending one.

More candidates do not always win. Sampling solutions without comparing them well can hurt. In one ICLR 2024 study, drawing two initial programs and ten repair candidates for each produced a pass rate below plain sampling at the same budget; diverse initial samples worked better than spending the budget on repeated repair (Olausson et al. 2024). That is the argument for a gate instead of a suggestion. The failure mode is not “the agent did not generate enough options.” It is “the agent generated one option and moved on.” A structural check that a plan names at least two real alternatives and states why one won closes that gap without pretending more sampling is free.

One piece of the older framing holds regardless of who does the planning: Boehm's cost-of-change curve. A wrong mechanism caught at plan time is far cheaper to fix than the same mistake found after the code ships. That is a property of software delivery, not of the reasoner making the choice (Boehm 1981).

### References

Aggarwal, Vaibhav, Ojasv Kamal, Abhinav Japesh, Zhijing Jin, and Bernhard Schölkopf. 2025. “DARS: Dynamic Action Re-Sampling to Enhance Coding Agent Performance by Adaptive Tree Traversal.” arXiv preprint arXiv:2503.14269. https://arxiv.org/abs/2503.14269.

Boehm, Barry W. 1981. *Software Engineering Economics*. Prentice-Hall.

FAIR CodeGen team, Jade Copet, Quentin Carbonneaux, et al. 2025. “CWM: An Open-Weights LLM for Research on Code Generation with World Models.” arXiv preprint arXiv:2510.02387. https://arxiv.org/abs/2510.02387.

Olausson, Theo X., Jeevana Priya Inala, Chenglong Wang, Jianfeng Gao, and Armando Solar-Lezama. 2024. “Is Self-Repair a Silver Bullet for Code Generation?” In *The Twelfth International Conference on Learning Representations*. https://proceedings.iclr.cc/paper_files/paper/2024/hash/9ddc141bdbf9d1db510cefff56c586ad-Abstract-Conference.html.

Sharma, Mrinank, Meg Tong, Tomasz Korbak, et al. 2023. “Towards Understanding Sycophancy in Language Models.” arXiv preprint arXiv:2310.13548. https://arxiv.org/abs/2310.13548.

Wang, Peiyi, Lei Li, Liang Chen, et al. 2023. “Large Language Models Are Not Fair Evaluators.” arXiv preprint arXiv:2305.17926. https://arxiv.org/abs/2305.17926.

Zhang, Guibin, Hejia Geng, Xiaohang Yu, et al. 2025. “The Landscape of Agentic Reinforcement Learning for LLMs: A Survey.” arXiv preprint arXiv:2509.02547. https://arxiv.org/abs/2509.02547.

## License

MIT. See [LICENSE](LICENSE).
