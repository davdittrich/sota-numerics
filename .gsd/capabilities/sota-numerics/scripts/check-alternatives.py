#!/usr/bin/env python3
"""Gate script for the sota-numerics `command-exit-zero` plan:post gate.

Validates that every `*-PLAN.md` file directly inside a phase directory
carries a compliant "## Alternatives Considered" section: at least two named
mechanism alternatives, each cited with a URL or doc-ref and a date within the
last 6 years, plus a `Decided by:` line naming a ranked criterion -- or an
exemption line for a plan where no mechanism choice exists. Internal entries
are excluded from the count and evidence validation.

Exit 0 = every discovered plan passes. Exit 1 = one or more violations,
printed to stderr as `<plan_path>: <reason>`, followed by exactly one
`remediation: ...` line. Exit 2 = usage/IO error (missing/non-directory
phase_dir, or a phase_dir that resolves outside the project root).

stdlib-only, no child-process invocations anywhere in this module: PLAN.md
text is authored by a different principal (the planner agent), so it is
treated as untrusted input throughout -- never eval'd, never shelled out.
`evaluateCommandExitZero` (gsd-core's generic `command-exit-zero` evaluator)
derives `block` purely from this script's process exit code -- no JSON
`GATE_RESULT` is printed here.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

RECENCY_WINDOW_YEARS = 6
MIN_ALTERNATIVES = 2

# Phase segment widened to `\d+(?:\.\d+)?` because beads' own
# `^(\d{2}-\d{2})-PLAN\.md$` pattern is too narrow to match a sub-numbered
# phase directory -- both `11-01-PLAN.md` and `10.1-02-PLAN.md` must match.
PLAN_FILE_RE = re.compile(r"^\d+(?:\.\d+)?-\d+-PLAN\.md$")

# Anchored single-line scans with no nested quantifiers, so no crafted
# PLAN.md body can trigger catastrophic regex backtracking (ReDoS). The H3
# heading scan below is intentionally uncapped but still linear.
SECTION_HEADING_RE = re.compile(
    r"^##[ \t]+Alternatives Considered\b[^\n]{0,200}$", re.IGNORECASE | re.MULTILINE
)
NEXT_HEADING_RE = re.compile(r"^##[ \t]+", re.MULTILINE)
H3_HEADING_RE = re.compile(r"^###(?:[ \t]+[^\n\r]*)?\r?$", re.MULTILINE)
INTERNAL_HEADING_RE = re.compile(
    r"^### Internal design alternatives[ \t]*\r?$", re.MULTILINE
)
EXEMPTION_RE = re.compile(r"^N/A\s*[-—]\s*.{0,200}?no mechanism choice", re.IGNORECASE)
BULLET_RE = re.compile(r"^[ \t]*[-*][ \t]+\*\*(.{1,200}?)\*\*", re.MULTILINE)
TABLE_ROW_RE = re.compile(
    r"^[ \t]*\|[^\n]{0,500}?\*\*(.{1,200}?)\*\*[^\n]{0,500}\|[ \t]*$", re.MULTILINE
)
TABLE_SEPARATOR_RE = re.compile(
    r"[ \t]*\|?[ \t]*:?-{3,}:?(?:[ \t]*\|[ \t]*:?-{3,}:?)*[ \t]*\|?[ \t]*"
)
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
    """Walk up from `start` to the nearest ancestor containing `.planning/`."""
    current = start.resolve()
    for _ in range(10):
        if (current / ".planning").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise ValueError(f"could not locate a .planning/ ancestor above {start}")


def confined(root, candidate):
    """Resolve `candidate` and reject any escape from `root`.

    A `..`-laden phase_dir argument could otherwise resolve to a path
    outside the project tree; `relative_to()` raises here if that happens.
    """
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes project root: {resolved} not under {root}")
    return resolved


def discover_plan_files(phase_dir):
    """Every `*-PLAN.md` directly inside phase_dir, sorted for determinism.

    Collects every match rather than stopping at the first, so a phase
    directory holding multiple plan files gets every one validated.
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
    """True when body's first non-blank line reads `N/A - ... no mechanism
    choice`, exempting a plan with no mechanism decision to justify."""
    stripped = body.strip()
    if not stripped:
        return False
    first_line = stripped.splitlines()[0]
    return bool(EXEMPTION_RE.match(first_line))


def split_entries(body):
    """Parse bullet or table-row entries, tagging each as internal or a
    mechanism alternative according to which `### Internal design
    alternatives` H3 section (if any) it falls under."""
    transitions = []
    internal = False
    for heading in H3_HEADING_RE.finditer(body):
        if INTERNAL_HEADING_RE.fullmatch(heading.group(0)):
            internal = True
            transitions.append((heading.start(), internal))
        elif internal:
            internal = False
            transitions.append((heading.start(), internal))

    matches = list(BULLET_RE.finditer(body))
    bullet_entries = []
    transition_i = 0
    internal = False
    for i, match in enumerate(matches):
        while transition_i < len(transitions) and transitions[transition_i][0] < match.start():
            internal = transitions[transition_i][1]
            transition_i += 1
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if transition_i < len(transitions):
            end = min(end, transitions[transition_i][0])
        bullet_entries.append(
            (match.group(1).strip(), body[match.start():end], internal)
        )
    mechanism_bullets = [entry for entry in bullet_entries if not entry[2]]
    if len(mechanism_bullets) >= MIN_ALTERNATIVES:
        return bullet_entries

    entries = []
    raw_lines = body.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in raw_lines]
    line_starts = []
    offset = 0
    for raw_line in raw_lines:
        line_starts.append(offset)
        offset += len(raw_line)
    transition_i = 0
    internal = False
    for i, line in enumerate(lines):
        framed = line.strip().startswith("|") and line.strip().endswith("|")
        if not framed or not TABLE_SEPARATOR_RE.fullmatch(line):
            continue
        if i == 0:
            continue
        header = lines[i - 1].strip()
        if not (header.startswith("|") and header.endswith("|")):
            continue
        for row_i, row in enumerate(lines[i + 1:], i + 1):
            if not (row.strip().startswith("|") and row.strip().endswith("|")):
                break
            m = TABLE_ROW_RE.fullmatch(row)
            if m:
                while (
                    transition_i < len(transitions)
                    and transitions[transition_i][0] < line_starts[row_i]
                ):
                    internal = transitions[transition_i][1]
                    transition_i += 1
                entries.append((m.group(1).strip(), row, internal))
    return entries or bullet_entries


def entry_has_citation(entry_text):
    return bool(URL_RE.search(entry_text) or DOC_REF_RE.search(entry_text))


def entry_years(entry_text):
    return [int(m.group(0)) for m in YEAR_RE.finditer(entry_text)]


def entry_placeholder_violation(entry_text):
    """True when an entry cites a known placeholder host (e.g. example.com)
    or a bare TODO/TBD doc-ref instead of a real citation."""
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
    a plan missing both a citation and a date reports both issues at once.
    """
    issues = []
    if not entry_has_citation(entry_text):
        issues.append("missing URL or doc-ref citation")
    years = entry_years(entry_text)
    if not years:
        issues.append("no citation date")
    elif not any(today_year - RECENCY_WINDOW_YEARS <= y <= today_year for y in years):
        # At-least-one-in-window rule: a foundational citation year paired
        # with an in-window year already passes the `years` truthiness check
        # above -- this branch only fires when every year found is out of
        # window.
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
    if not entries:
        return "section found but no alternatives parsed; entries must be '- **Name**' bullets or bold-name table rows"
    mechanism_entries = [
        (name, entry_text)
        for name, entry_text, internal in entries
        if not internal
    ]
    if len(mechanism_entries) < MIN_ALTERNATIVES:
        return f"fewer than 2 named alternatives (found {len(mechanism_entries)})"
    today_year = datetime.date.today().year
    for name, entry_text in mechanism_entries:
        issues = validate_entry(name, entry_text, today_year)
        if issues:
            return issues[0]
    if not DECIDED_BY_RE.search(body):
        return "no 'Decided by:' line naming a ranked criterion"
    return None


def phase_label_from_dirname(phase_dir_arg):
    """Phase number parsed from the leading `\\d+(?:\\.\\d+)?` of the
    phase_dir basename, or the literal `<phase>` placeholder when the
    basename doesn't start with a phase number."""
    m = PHASE_NUM_RE.match(Path(phase_dir_arg).name)
    return m.group(1) if m else "<phase>"


def check_alternatives(phase_dir_arg):
    """Validate every discovered plan; return the list of violations.

    Each violation is a (plan_path, reason) tuple; the list is empty when
    every discovered plan passes. Raises ValueError when phase_dir resolves
    outside the project root (caller maps this to exit 2).
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
