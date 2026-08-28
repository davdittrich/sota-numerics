# sota-numerics

Make GSD compare mechanisms before execution, then keep numerical precision and measured performance visible through shipping.

`sota-numerics` is an installable [gsd-core](https://github.com/open-gsd/gsd-core) capability, not a fork. It adds four advisory prompts and one blocking plan gate.

## What it changes

| GSD point | Target | Behavior |
| --- | --- | --- |
| `plan:pre` | planner | Research current mechanisms, compare real alternatives, cite them, and rank the decision by performance, simplicity/LOC, ecosystem support, then maintenance cost. |
| `plan:post` | gate | Block when an eligible plan lacks the required `Alternatives Considered` structure. |
| `execute:wave:pre` | executor | Derive numeric parameters from the problem, avoid cancellation and silent error growth, and name the ceiling of any precision tradeoff. |
| `execute:wave:post` | verifier | Flag drift from the chosen mechanism, dropped edge cases, unstable substitutions, unexplained constants, and unsupported performance claims. |
| `ship:pre` | orchestrator | Check that precision and efficiency claims have measurements or sources and that accepted simplifications state where they break. |

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

The marketplace remains in `davdittrich/gsd-beads`; its entry points to this repository.

The GSD capability itself declares support for every GSD runtime. Automatic startup installation and role banners come from Claude's `SessionStart` and `SubagentStart` hooks, so other hosts must not assume those hooks ran. On any host, the gate can use a capability bundle at either of these locations:

1. `<project>/.gsd/capabilities/sota-numerics`
2. `${GSD_HOME:-$HOME}/.gsd/capabilities/sota-numerics`

The project copy wins when both exist.

### What the Claude hooks do

At startup, resume, clear, or compaction, the plugin checks the whole capability bundle's hash. It installs the bundle at global GSD scope only when that hash changed. The same hook prints a short steering banner when the capability is enabled and its config lookup succeeds.

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

`-` and `*` bullets both work. The parser requires the bold name; a colon after it is conventional but optional. A bullet's evidence runs until the next recognized bullet or the end of the section.

A framed Markdown table also works when it has a header, a separator row, and bold-named body rows:

```markdown
## Alternatives Considered (REQ-10)

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Householder QR** | `NumPy QR docs` (2026) |
| 2 | **Pivoted LU** | https://docs.scipy.org/ (2025) |

Decided by: performance — QR is the stable first choice.
```

Table evidence is confined to its row. The header and separator never count as alternatives. Bullets and table rows are fallback formats, not additive: two recognized bullets take precedence; otherwise the checker tries the table and does not combine the two forms to reach the minimum.

Each parsed entry must contain:

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
- `2`: the phase path is missing, is not a directory, has no `.planning` ancestor within ten levels, or resolves outside that project root.

Unexpected filesystem errors are not converted to `2`; they escape as Python errors and the blocking gate halts. Plan discovery matches names without a separate file-type check, so a directory with a plan-shaped name can take this path.

You can run the checker directly:

```bash
python3 .gsd/capabilities/sota-numerics/scripts/check-alternatives.py .planning/phases/11-example
```

Under the current gsd-core plan workflow, `plan:post` runs after the plan commit. The plan checker should catch a bad section earlier; this gate is the fail-closed backstop. If the gate fires, fix the plans and rerun the phase with `--force` as printed.

If the gate script is absent from both project and global scope, the gate exits with a direct installation error instead of silently passing.

## Requirements

- Bash. The hooks use Bash arrays and `[[ ... ]]`; they are not POSIX `sh` scripts.
- Python 3. The checker uses only the standard library and launches no child processes.
- gsd-core 1.10.0 or newer.
- Git for project-scope gate lookup. A global-only install still works when Git lookup fails.
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

Coding agents commit to early choices. Once a plan says “use X,” later steps tend to defend X instead of reopening the decision. Requiring two named options and a decision criterion forces the comparison to happen while changing course is still cheap.

More candidates alone do not fix the problem. The useful step is comparing them against the job. Meta's CWM results moved from 58.4% resolved with majority selection to 65.8% with test-based candidate selection. Work on sycophancy and position bias points to the same practical rule: put competing choices in front of the planner before one becomes inherited fact.

References:

1. [CWM: An Open-Weights LLM for Research on Code Generation with World Models](https://arxiv.org/pdf/2510.02387) (Meta, 2025)
2. [The DARS paper](https://arxiv.org/pdf/2503.14269) (2025)
3. [Towards Understanding Sycophancy in Language Models](https://arxiv.org/abs/2310.13548) (2023)
4. [Large Language Models are not Fair Evaluators](https://arxiv.org/abs/2305.17926) (2023)
5. [Is Self-Repair a Silver Bullet for Code Generation?](https://proceedings.iclr.cc/paper_files/paper/2024/file/9ddc141bdbf9d1db510cefff56c586ad-Paper-Conference.pdf) (ICLR 2024)

## License

MIT. See [LICENSE](LICENSE).
