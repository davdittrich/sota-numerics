#!/usr/bin/env python3
"""Gate script for the sota-numerics `command-exit-zero` plan:post gate (D-01,
D-02, D-06, D-07, D-09; RESEARCH.md Pattern 1/3, REVIEWS findings 1-3).

Validates that every `*-PLAN.md` file directly inside a phase directory
carries a compliant "## Alternatives Considered" section: >=2 named
alternatives, each cited with a URL or doc-ref and a date within the last
6 years, plus a `Decided by:` line naming a ranked criterion -- or the D-03
exemption text.

Exit 0 = every discovered plan passes. Exit 1 = one or more violations,
printed to stderr as `<plan_path>: <reason>`, followed by exactly one
`remediation: ...` line. Exit 2 = usage/IO error (missing/non-directory
phase_dir, or a phase_dir that resolves outside the project root).

stdlib-only, no child-process invocations anywhere in this module: PLAN.md
text is authored by a different principal (the planner agent) and is
treated as untrusted input throughout -- never eval'd, never shelled out,
exactly as `.gsd/capabilities/beads/scripts/sync.py`'s module docstring
states for `bd` argv construction (T-01-01/T-11-02). `evaluateCommandExitZero`
(gsd-core's generic `command-exit-zero` evaluator) derives `block` purely
from this script's process exit code -- no JSON `GATE_RESULT` is printed
here.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

RECENCY_WINDOW_YEARS = 6
MIN_ALTERNATIVES = 2

# Phase segment widened to `\d+(?:\.\d+)?` (RESEARCH: beads' own
# `^(\d{2}-\d{2})-PLAN\.md$` is too narrow) so both `11-01-PLAN.md` and
# `10.1-02-PLAN.md` match.
PLAN_FILE_RE = re.compile(r"^\d+(?:\.\d+)?-\d+-PLAN\.md$")

# Anchored, bounded, no nested quantifiers (ReDoS mitigation, RESEARCH
# Security Domain) -- every regex below follows this discipline.
SECTION_HEADING_RE = re.compile(r"^##[ \t]+Alternatives Considered[ \t]*$", re.IGNORECASE | re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##[ \t]+", re.MULTILINE)
EXEMPTION_RE = re.compile(r"^N/A\s*[-—]\s*.{0,200}?no mechanism choice", re.IGNORECASE)
BULLET_RE = re.compile(r"^[ \t]*[-*][ \t]+\*\*(.{1,200}?)\*\*", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s)>\]]{1,300}")
DOC_REF_RE = re.compile(r"`[^`\n]{1,300}`")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DECIDED_BY_RE = re.compile(
    r"(?:^|\n)[ \t]*[-*]?[ \t]*\*{0,2}Decided by:\*{0,2}[ \t]*"
    r"(?:performance|simplicity|LOC|ecosystem|maintenance)",
    re.IGNORECASE,
)
HOST_RE = re.compile(r"^https?://([^/\s]{1,255})")
PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "localhost"}
PLACEHOLDER_TEXT_RE = re.compile(r"^\s*(?:TODO|TBD)\s*$", re.IGNORECASE)
PHASE_NUM_RE = re.compile(r"^(\d+(?:\.\d+)?)")


def find_project_root(start):
    """Walk up from `start` to the nearest ancestor containing `.planning/`.

    Mirrors sync.py's `find_project_root` (T-11-02).
    """
    current = start.resolve()
    for _ in range(10):
        if (current / ".planning").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise ValueError(f"could not locate a .planning/ ancestor above {start}")


def confined(root, candidate):
    """Resolve `candidate` and reject any escape from `root` (T-11-02).

    Same relative_to()-escape-check idiom as sync.py's `confined()`, applied
    to an already-supplied path rather than parts joined fresh onto root.
    """
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes project root: {resolved} not under {root}")
    return resolved


def discover_plan_files(phase_dir):
    """Every `*-PLAN.md` directly inside phase_dir, sorted for determinism.

    Collects ALL matches (RESEARCH Pattern 3) -- never returns on the first.
    """
    return sorted(
        candidate
        for candidate in Path(phase_dir).iterdir()
        if PLAN_FILE_RE.match(candidate.name)
    )


def extract_section_body(text):
    """Text from just after the heading line to the next `## ` heading or EOF.
    Returns None if the heading is absent."""
    m = SECTION_HEADING_RE.search(text)
    if not m:
        return None
    start = m.end()
    next_m = NEXT_HEADING_RE.search(text, start)
    end = next_m.start() if next_m else len(text)
    return text[start:end]


def is_exempt(body):
    """D-03: body's first non-blank content is `N/A [-—] ... no mechanism choice`."""
    stripped = body.strip()
    if not stripped:
        return False
    first_line = stripped.splitlines()[0]
    return bool(EXEMPTION_RE.match(first_line))


def split_entries(body):
    """One entry-text string per `- **name**` / `* **name**` bullet, each
    running from its bullet to the start of the next (or EOF)."""
    matches = list(BULLET_RE.finditer(body))
    entries = []
    for i, m in enumerate(matches):
        entry_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        entries.append((m.group(1).strip(), body[m.start():entry_end]))
    return entries


def entry_has_citation(entry_text):
    return bool(URL_RE.search(entry_text) or DOC_REF_RE.search(entry_text))


def entry_years(entry_text):
    return [int(m.group(0)) for m in YEAR_RE.finditer(entry_text)]


def entry_placeholder_violation(entry_text):
    """D-08 mechanical plausibility: placeholder host or bare TODO/TBD citation."""
    for url_m in URL_RE.finditer(entry_text):
        host_m = HOST_RE.match(url_m.group(0))
        if host_m and host_m.group(1).lower() in PLACEHOLDER_HOSTS:
            return True
    for ref_m in DOC_REF_RE.finditer(entry_text):
        if PLACEHOLDER_TEXT_RE.match(ref_m.group(0).strip("`")):
            return True
    return False


def validate_entry(name, entry_text, today_year):
    """Return a list of issue strings for one alternative entry (empty = pass).

    Accumulates every applicable issue rather than stopping at the first, so
    a plan missing both a citation and a date reports both (D-06 + D-07).
    """
    issues = []
    if not entry_has_citation(entry_text):
        issues.append("missing URL or doc-ref citation")
    years = entry_years(entry_text)
    if not years:
        issues.append("no citation date")
    elif not any(today_year - RECENCY_WINDOW_YEARS <= y <= today_year for y in years):
        # D-07 at-least-one-in-window rule (REVIEWS finding 2): a foundational
        # year paired with an in-window year passes at the `years` truthiness
        # check above -- this branch only fires when EVERY year found is
        # out of window.
        found = ", ".join(str(y) for y in years)
        issues.append(
            f"no citation dated within the last {RECENCY_WINDOW_YEARS} years (found: {found})"
        )
    if entry_placeholder_violation(entry_text):
        issues.append("cites a placeholder URL or a bare TODO/TBD citation")
    if issues:
        return [f"alternative '{name}': {'; '.join(issues)}"]
    return []


def validate_plan(path):
    """Return None if `path` is compliant, else a violation reason string."""
    text = path.read_text(encoding="utf-8")
    body = extract_section_body(text)
    if body is None:
        return "missing '## Alternatives Considered' section"
    if is_exempt(body):
        return None
    entries = split_entries(body)
    if len(entries) < MIN_ALTERNATIVES:
        return f"fewer than 2 named alternatives (found {len(entries)})"
    today_year = datetime.date.today().year
    for name, entry_text in entries:
        issues = validate_entry(name, entry_text, today_year)
        if issues:
            return issues[0]
    if not DECIDED_BY_RE.search(body):
        return "no 'Decided by:' line naming a ranked criterion"
    return None


def phase_label_from_dirname(phase_dir_arg):
    """Phase number parsed from the leading `\\d+(?:\\.\\d+)?` of the
    phase_dir basename, or the literal `<phase>` placeholder (REVIEWS
    findings 1/3)."""
    m = PHASE_NUM_RE.match(Path(phase_dir_arg).name)
    return m.group(1) if m else "<phase>"


def check_alternatives(phase_dir_arg):
    """Validate every discovered plan; return (exit_code, violations).

    violations is a list of (plan_path, reason) tuples, empty on pass.
    Raises ValueError on a phase_dir that resolves outside the project root
    (caller maps this to exit 2).
    """
    phase_dir_path = Path(phase_dir_arg)
    project_root = find_project_root(phase_dir_path)
    resolved_phase_dir = confined(project_root, phase_dir_path)
    violations = []
    for plan_path in discover_plan_files(resolved_phase_dir):
        reason = validate_plan(plan_path)
        if reason is not None:
            violations.append((plan_path, reason))
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check-alternatives.py")
    parser.add_argument("phase_dir")
    args = parser.parse_args(argv)

    phase_dir_arg = Path(args.phase_dir)
    if not phase_dir_arg.is_dir():
        print(f"check-alternatives.py: not a directory: {args.phase_dir}", file=sys.stderr)
        return 2

    try:
        violations = check_alternatives(phase_dir_arg)
    except ValueError as exc:
        print(f"check-alternatives.py: {exc}", file=sys.stderr)
        return 2

    if not violations:
        return 0

    for plan_path, reason in violations:
        print(f"{plan_path}: {reason}", file=sys.stderr)
    phase_label = phase_label_from_dirname(args.phase_dir)
    print(
        f"remediation: fix the plans above, then re-run /gsd-plan-phase {phase_label} --force",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
