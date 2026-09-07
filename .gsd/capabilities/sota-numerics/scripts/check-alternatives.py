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
`remediation: ...` line. Exit 2 = usage/IO error: an empty, missing or
non-directory phase_dir, a phase_dir with no `.planning/` ancestor within
10 levels, a discovered plan file that is not valid UTF-8, or -- when no
phase_dir is given -- a STATE.md whose frontmatter `current_phase` and
`## Current Position` `Phase:` line do not corroborate each other.

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

# Phase segment is `\d+(?:\.\d+)?` rather than a fixed `\d{2}`, so a
# sub-numbered phase directory matches: both `11-01-PLAN.md` and
# `10.1-02-PLAN.md` are plan files.
PLAN_FILE_RE = re.compile(r"^\d+(?:\.\d+)?-\d+-PLAN\.md$")

# Anchored single-line scans with no nested quantifiers, so no crafted
# PLAN.md body can trigger catastrophic regex backtracking (ReDoS). The H3
# heading scan below is intentionally uncapped but still linear.
SECTION_HEADING_RE = re.compile(
    r"^##[ \t]+Alternatives Considered\b[^\n]{0,200}$", re.IGNORECASE | re.MULTILINE
)
# Ends the section body. H1 as well as H2, because `^##` alone let a later
# `# Section` donate its bullets to this one: a plan with a single real
# alternative passed on an entry written somewhere else entirely. Up to the
# three leading spaces CommonMark allows on an ATX heading, matching
# FENCE_LINE_RE below -- an indented `## Later` donated for the same reason.
# Deliberately not `#{1,6}`: `### Internal design alternatives` is an
# in-section construct, so bounding on H3 would cut the body short and drop
# the `Decided by:` line that follows it. Bounding earlier only ever shrinks
# the body, which is the fail-closed direction.
# A setext H1 underline (`===`) ends the section too: the heading TEXT line
# above it is harmless (it is not an entry), but bullets below it would
# otherwise be donated into the section the way an ATX H1 once was.
# `-` underlines are deliberately NOT a boundary: `---` is equally a
# thematic break and a frontmatter fence, so treating it as one would
# false-BLOCK a plan that puts a horizontal rule inside the section. `=`
# has no such second meaning. Bounding earlier only shrinks the body, so
# every case this moves, it moves fail-closed.
NEXT_HEADING_RE = re.compile(r"^[ \t]{0,3}(?:#{1,2}[ \t]+|=+[ \t]*$)", re.MULTILINE)
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
# `current_phase` in STATE.md's YAML frontmatter. Constrained to a phase number
# at the point of reading, so nothing else can become a directory lookup.
# The leading YAML frontmatter block, and nothing after it. `current_phase` is
# read from here only.
STATE_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)

STATE_CURRENT_PHASE_RE = re.compile(
    r"^current_phase:[ \t]*[\"']?(\d+(?:\.\d+)?)[\"']?[ \t]*$", re.MULTILINE
)

# The second witness to phase identity: the `Phase:` line inside the
# `## Current Position` section. gsd-core's `plannedPhaseCore` OWNS that line
# (#3395) and the frontmatter `current_phase` is re-derived FROM it, so step
# 13b writes both or neither. Requiring them to agree is what lets this gate
# notice a half-applied transition instead of validating whatever phase the
# stale frontmatter still names.
#
# `Current Phase:` is deliberately NOT accepted as the label, even though
# gsd-core's own `completePhaseCore` reads `Current Phase` before `Phase`. A
# section spelled that way is one `plannedPhaseCore` could not rewrite --
# measured: `state.planned-phase --phase 7` exits 0 reporting only
# `Last Activity Description`, leaving both the body line and `current_phase`
# on the previous phase. Accepting the label would make the two witnesses
# agree on a value neither of them refreshed, which is the whole defect.
STATE_POSITION_SECTION_RE = re.compile(
    r"^##[ \t]+Current Position[ \t]*$(.*?)(?=^##[ \t]|\Z)",
    re.MULTILINE | re.DOTALL,
)
STATE_BODY_PHASE_RE = re.compile(
    r"^[ \t]{0,3}\*{0,2}Phase:\*{0,2}[ \t]*(\d+(?:\.\d+)?)\b", re.MULTILINE
)

# A CommonMark fenced code block opener: up to three leading spaces, then three
# or more backticks or tildes, then an optional info string. Anchored per line,
# no nested quantifiers -- same ReDoS discipline as the scans above.
FENCE_LINE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})([^\n]*)$", re.MULTILINE)
NON_NEWLINE_RE = re.compile(r"[^\n]")


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


def normalize_phase(number):
    """Comparison key for a phase number: `06` equals `6`, `10.1` does not
    equal `10.10`."""
    major, _, minor = number.partition(".")
    return int(major), minor


def resolve_current_phase_dir(start):
    """The phase directory named by `.planning/STATE.md`'s `current_phase`.

    The gate command carries no `${PHASE_DIR}` splice, because no shell
    quoting survives an arbitrary directory name: a single quote in the name
    closes the literal and everything after it is parsed as shell source. So
    the phase identity travels through the project's own state file instead,
    where this function reads it directly and it never reaches a shell.

    gsd-core writes phase identity in plan-phase step 13b ("Record Planning
    Completion in STATE.md"), which runs before the plan:post gate dispatch in
    step 13e. It writes TWO places -- the `## Current Position` `Phase:` line
    and the frontmatter `current_phase` re-derived from it -- and on three
    measured `## Current Position` shapes it silently writes NEITHER while
    still exiting 0, leaving `current_phase` naming the PREVIOUS phase. Reading
    that field alone therefore does not name the phase just planned; it names
    whichever phase was last recorded successfully, and the gate would report a
    clean pass on an old compliant phase while the new one went uninspected.

    So both are read and required to agree. One witness cannot detect its own
    staleness; two witnesses written by one transaction can. Every failure
    below raises, and main() maps a raise to exit 2: a blocking gate that
    cannot identify its phase must block rather than pass vacuously.
    """
    root = find_project_root(start)
    state_path = root / ".planning" / "STATE.md"
    try:
        state_text = state_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"cannot read {state_path} to resolve the current phase ({exc.strerror})"
        ) from exc
    # Search ONLY the YAML frontmatter, which is what the comment on
    # STATE_CURRENT_PHASE_RE always claimed. Scanning the whole file let any
    # `current_phase: <n>` line in prose -- or inside a fenced example --
    # redirect phase identity, so a non-compliant phase could be waved through
    # by pointing the gate at a compliant one. Document content must not decide
    # which phase a blocking gate inspects.
    fm = STATE_FRONTMATTER_RE.match(state_text)
    if not fm:
        raise ValueError(
            f"{state_path} has no YAML frontmatter block to read"
            " `current_phase` from; pass the phase directory explicitly"
        )
    m = STATE_CURRENT_PHASE_RE.search(fm.group(1))
    if not m:
        raise ValueError(
            f"{state_path} has no `current_phase: <number>` field;"
            " pass the phase directory explicitly"
        )
    # Second witness. See STATE_POSITION_SECTION_RE for why `Current Phase:`
    # is not an accepted label and why disagreement means block, not pick-one.
    section = STATE_POSITION_SECTION_RE.search(state_text[fm.end():])
    if not section:
        raise ValueError(
            f"{state_path} has no `## Current Position` section to corroborate"
            f" `current_phase: {m.group(1)}`; pass the phase directory explicitly"
        )
    body_phases = STATE_BODY_PHASE_RE.findall(section.group(1))
    if len(body_phases) != 1:
        raise ValueError(
            f"{state_path} `## Current Position` carries {len(body_phases)}"
            f" `Phase: <number>` lines to corroborate `current_phase:"
            f" {m.group(1)}` (need exactly one); pass the phase directory"
            " explicitly"
        )
    if normalize_phase(body_phases[0]) != normalize_phase(m.group(1)):
        raise ValueError(
            f"{state_path} disagrees with itself: frontmatter `current_phase:"
            f" {m.group(1)}` but `## Current Position` says `Phase:"
            f" {body_phases[0]}`; re-run /gsd-plan-phase for the phase you mean,"
            " or pass the phase directory explicitly"
        )
    wanted = normalize_phase(m.group(1))
    phases_root = root / ".planning" / "phases"
    matches = []
    if phases_root.is_dir():
        for entry in sorted(phases_root.iterdir()):
            num = PHASE_NUM_RE.match(entry.name)
            if entry.is_dir() and num and normalize_phase(num.group(1)) == wanted:
                matches.append(entry)
    if len(matches) != 1:
        raise ValueError(
            f"current_phase {m.group(1)} matches {len(matches)} directories"
            f" under {phases_root} (expected exactly 1)"
        )
    return matches[0]


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


def mask_fenced_regions(text):
    """Blank every fenced code block, preserving offsets and line structure.

    Without this, the first `## Alternatives Considered` anywhere in the file
    won -- including one inside a ```markdown fence. README ships four fenced
    examples for authors to copy, so a plan that pasted an example (an `N/A --
    no mechanism choice` exemption, say) without writing a real section
    satisfied the blocking gate on the example's text. Bullets and table rows
    inside a fence were counted as real entries for the same reason.

    Replacing fenced bytes with spaces rather than deleting them keeps every
    offset intact, so the scans below stay one pass and slices still line up.
    An unterminated fence blanks to EOF: the section then reads as missing and
    the gate blocks, which is the fail-closed direction.
    """
    spans = []
    open_marker = None
    start = 0
    for m in FENCE_LINE_RE.finditer(text):
        marker, info = m.group(1), m.group(2)
        if open_marker is None:
            # A backtick fence's info string may not itself contain a backtick.
            if marker[0] == "`" and "`" in info:
                continue
            open_marker = marker
            start = m.start()
        elif marker[0] == open_marker[0] and len(marker) >= len(open_marker) and not info.strip():
            spans.append((start, m.end()))
            open_marker = None
    if open_marker is not None:
        spans.append((start, len(text)))
    if not spans:
        return text
    out = []
    prev = 0
    for span_start, span_end in spans:
        out.append(text[prev:span_start])
        out.append(NON_NEWLINE_RE.sub(" ", text[span_start:span_end]))
        prev = span_end
    out.append(text[prev:])
    return "".join(out)


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
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Name the file and the remedy. UnicodeDecodeError subclasses
        # ValueError, so main() already exits 2 here -- but it printed only the
        # codec's own message, which names a byte offset and no path. A phase
        # holding twenty plans gave the author no way to tell which one to fix.
        raise ValueError(
            f"{path}: not valid UTF-8 ({exc.reason} at byte {exc.start});"
            " re-save the plan as UTF-8"
        ) from exc
    body = extract_section_body(mask_fenced_regions(text))
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
    every discovered plan passes. Raises ValueError when phase_dir has no
    `.planning/` ancestor (caller maps this to exit 2).
    """
    phase_dir_path = Path(phase_dir_arg)
    # Called for its raise, not its result: it rejects a phase_dir sitting
    # outside any GSD project.
    find_project_root(phase_dir_path)
    resolved_phase_dir = phase_dir_path.resolve()
    violations = []
    for plan_path in discover_plan_files(resolved_phase_dir):
        reason = validate_plan(plan_path)
        if reason is not None:
            violations.append((plan_path, reason))
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check-alternatives.py")
    parser.add_argument("phase_dir", nargs="?")
    args = parser.parse_args(argv)

    if args.phase_dir is None:
        # No argument is the gate's own calling convention: the gate command is
        # constant so that no consumer-supplied byte is ever spliced into the
        # `sh -c` string it becomes. Resolve the phase from the project's own
        # state instead, where a directory name never reaches a shell.
        try:
            phase_dir_arg = resolve_current_phase_dir(Path.cwd())
        except ValueError as exc:
            print(f"check-alternatives.py: {exc}", file=sys.stderr)
            return 2
    elif not args.phase_dir:
        # `Path("")` is `Path(".")`, so an empty argument would otherwise make
        # the checker inspect its own cwd and report every plan there as
        # passing. Reachable only from a hand-written invocation now that the
        # gate passes no argument at all, but still fail-closed.
        print(
            "check-alternatives.py: empty phase_dir argument"
            " (pass a phase directory, or no argument to use the project's current phase)",
            file=sys.stderr,
        )
        return 2
    else:
        phase_dir_arg = Path(args.phase_dir)

    if not phase_dir_arg.is_dir():
        print(f"check-alternatives.py: not a directory: {phase_dir_arg}", file=sys.stderr)
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
    phase_label = phase_label_from_dirname(phase_dir_arg)
    print(
        f"remediation: fix the plans above, then re-run /gsd-plan-phase {phase_label} --force",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
