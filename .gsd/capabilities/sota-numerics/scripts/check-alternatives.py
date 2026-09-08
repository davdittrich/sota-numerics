#!/usr/bin/env python3
"""Gate script for the sota-numerics `command-exit-zero` plan:post gate.

Validates that every `*-PLAN.md` file directly inside a phase directory
carries a compliant "## Alternatives Considered" section: at least two named
mechanism alternatives, each cited with a URL or doc-ref and a date within the
last 6 years, plus a `Decided by:` line naming a ranked criterion -- or an
exemption line for a plan where no mechanism choice exists. Internal entries
are excluded from the count and evidence validation.

Exit 0 = every discovered plan passes. Exit 1 = one or more violations,
printed to stderr as `<plan_path>:<line>: <reason>` (D-08), followed by
exactly one `remediation: ...` line; a plan-shaped file whose name no plan
reader matches is itself such a violation, reported against line 1 because
the violation is about its filename, not any line inside it, since skipping
it silently is indistinguishable from a clean pass. Every document-derived
span in a diagnostic is bounded and, when truncated, carries an explicit
`...[truncated]` marker; no printed stderr line exceeds 200 characters,
whatever the plan document contains (D-07).

Exit 2 = usage/IO error. Any of five conditions raises it. The phase_dir
argument is empty, missing, or not a directory. The phase_dir has no
`.planning/` ancestor within 10 levels. A discovered plan file is not valid
UTF-8. A discovered plan file could not be read at all; a plan-shaped name
that names a directory is the usual cause. No phase_dir was given, and the
STATE.md the phase resolves from carries a frontmatter `current_phase` and a
`## Current Position` `Phase:` line that do not corroborate each other.

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

# Diagnostic-bounding widths (D-07, D-08). No earlier decision fixes these
# three numbers -- they are this plan's own choice of width, not inherited
# from the review that reported the defect (D-24 discretion):
#   - QUOTED_SPAN_WIDTH: a document-derived excerpt (an entry name, or the
#     heading text that ended a section) shown inside a message, in
#     characters of the excerpt's own content.
#   - FOUND_VALUES_LIMIT: how many distinct values a "found: ..." list
#     names before eliding the rest.
#   - STDERR_LINE_WIDTH: the hard ceiling on one printed stderr line,
#     whatever the plan document contains -- the backstop behind the two
#     bounds above, not a replacement for them.
QUOTED_SPAN_WIDTH = 80
FOUND_VALUES_LIMIT = 5
STDERR_LINE_WIDTH = 200
ELISION_MARKER = "...[truncated]"

# Phase segment is `\d+(?:\.\d+)?` rather than a fixed `\d{2}`, so a
# sub-numbered phase directory matches: both `11-01-PLAN.md` and
# `10.1-02-PLAN.md` are plan files.
PLAN_FILE_RE = re.compile(r"^\d+(?:\.\d+)?-\d+-PLAN\.md$")

# A file a human reader would call a plan: the last hyphen-separated token of
# the `.md` name is `PLAN`. The bound is chosen in both directions.
#
# Narrower than "any markdown file", because a phase directory also holds
# SUMMARY, CONTEXT, RESEARCH, PATTERNS, REVIEW, BEADS and VALIDATION
# artifacts; a gate that blocked a phase on a stray note would be a gate
# authors route around.
#
# Case-sensitive, and that is the load-bearing half of the bound. `PLAN` in
# capitals is GSD's artifact token, the same convention as SUMMARY and
# RESEARCH; a lowercase `plan` is ordinary English inside a filename. The
# first draft of this regex carried re.IGNORECASE and blocked a phase on
# `notes-on-the-plan.md` -- a stray note, exactly the false positive that
# would teach authors to route around the gate. The case-insensitive-
# filesystem question this raises (a lowercase `23-01-plan.md`) is verified,
# not asserted, in NOTES.md section 7 -- read it there; do not restate the
# claim here, or the two copies will drift.
#
# Wider than PLAN_FILE_RE, which additionally demands the `<phase>-<NN>-`
# prefix. Everything between the two is a file that reads as a plan to a human
# and is invisible to every plan reader, this gate included -- and silence is
# the one answer a blocking gate must not give about it. A phase holding only
# `23-PLAN.md` used to exit 0 with no output, byte-identical to a compliant
# phase, because the name missed the plan index by one field.
PLAN_SHAPED_RE = re.compile(r"(?:^|-)PLAN\.md$")
MISNAMED_PLAN_REASON = (
    "named like a plan but not `<phase>-<NN>-PLAN.md`, so no plan reader --"
    " this gate included -- will ever open it; rename it or remove it"
)

# Anchored single-line scans with no nested quantifiers, so no crafted
# PLAN.md body can trigger catastrophic regex backtracking (ReDoS). The H3
# heading scan below is intentionally uncapped but still linear.
SECTION_HEADING_RE = re.compile(
    r"^##[ \t]+Alternatives Considered\b[^\n]{0,200}$", re.IGNORECASE | re.MULTILINE
)
# H1/H2 end the section (fail-closed: bounding early only shrinks the body).
# H3 stays inside it (`### Internal design alternatives`) -- pinned by
# TestSectionBoundary.test_h3_does_not_end_the_section.
# A bare `=+` run with no preceding paragraph is a horizontal rule, not a
# setext heading -- pinned by
# TestSectionBoundary.test_bare_setext_rule_does_not_end_the_section.
# `-` underlines are never a boundary either: `---` is also a thematic break
# and a frontmatter fence -- pinned by
# TestSectionBoundary.test_thematic_break_does_not_end_the_section.
NEXT_HEADING_RE = re.compile(
    r"^[ \t]{0,3}#{1,2}[ \t]+"
    r"|^[ \t]{0,3}[^\s][^\n]*\n[ \t]{0,3}=+[ \t]*$",
    re.MULTILINE,
)
H3_HEADING_RE = re.compile(r"^###(?:[ \t]+[^\n\r]*)?\r?$", re.MULTILINE)
INTERNAL_HEADING_RE = re.compile(
    r"^### Internal design alternatives[ \t]*\r?$", re.MULTILINE
)
EXEMPTION_RE = re.compile(r"^N/A\s*[-—]\s*.{0,200}?no mechanism choice", re.IGNORECASE)
# Indentation bounded to CommonMark's zero-to-three-space top-level range
# (D-03, REVIEW-CRITICAL-FINAL P1-1(b), gsd-beads-25vc.6) -- pinned by
# TestBulletIndentationBound.
BULLET_RE = re.compile(r"^[ \t]{0,3}[-*][ \t]+\*\*(.{1,200}?)\*\*", re.MULTILINE)
TABLE_ROW_RE = re.compile(
    r"^[ \t]{0,3}\|[^\n]{0,500}?\*\*(.{1,200}?)\*\*[^\n]{0,500}\|[ \t]*$", re.MULTILINE
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
# The other construct CommonMark keeps out of the rendered page. Plain string
# search, not a regex: the delimiters are literals, so `str.find` is both
# faster and immune to the backtracking the scans above are shaped to avoid.
HTML_COMMENT_OPEN = "<!--"
HTML_COMMENT_CLOSE = "-->"
# A single-backtick, same-line, bounded inline code span. Mirrors DOC_REF_RE's
# shape (line 147) but gets its own name and comment: this one's job is
# masking-precedence detection (is a `<!--` candidate rendered as literal
# text?), not citation matching.
INLINE_CODE_SPAN_RE = re.compile(r"`[^`\n]{1,300}`")
NON_NEWLINE_RE = re.compile(r"[^\n]")

# CommonMark list markers at zero-to-three-space indentation: a bullet
# (-, +, *) or an ordered marker (1-9 digits then . or )), each followed
# by required whitespace. Matched only against single already-isolated
# lines below, so no MULTILINE flag is needed here.
LIST_MARKER_RE = re.compile(r"^[ \t]{0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
# A non-blank line at zero-to-three-space indentation -- the same shallow
# range FENCE_LINE_RE and LIST_MARKER_RE anchor to.
SHALLOW_LINE_RE = re.compile(r"^[ \t]{0,3}\S")
# A non-blank line indented four or more spaces/tabs: an indented-code-
# block candidate (https://spec.commonmark.org/0.31.2/#indented-code-blocks,
# 2024). No tab-stop expansion -- literal character count, the same
# simplicity this whole pre-pass already trades for a dependency-free scan.
INDENTED_CODE_LINE_RE = re.compile(r"^[ \t]{4,}\S")


def elide_span(s, width=QUOTED_SPAN_WIDTH):
    """Truncate a document-derived span to `width` characters of its own
    content, appending an explicit elision marker when truncated (D-08) so
    a reader can tell truncation from a value that was already short.
    """
    if len(s) <= width:
        return s
    return s[:width] + ELISION_MARKER


def elide_values(values, limit=FOUND_VALUES_LIMIT):
    """The first `limit` distinct values, sorted for a message that reads
    the same regardless of the order the document stated them in, with an
    explicit elision marker when more were found (D-08). Only how many
    values the message shows changes -- not which values were found, so
    this never affects a verdict already decided from the full list.
    """
    distinct = sorted(set(values))
    if len(distinct) <= limit:
        return ", ".join(str(v) for v in distinct)
    shown = ", ".join(str(v) for v in distinct[:limit])
    return f"{shown}, ...[+{len(distinct) - limit} more]"


def elide_line(s, width=STDERR_LINE_WIDTH):
    """Hard backstop: `s` truncated so the printed result never exceeds
    `width` characters, whatever the plan document contains (D-07). Unlike
    `elide_span`, this reserves room for its own marker so the guarantee is
    exact rather than approximate -- the two span-level bounds above keep
    an ordinary line well under this ceiling, but a long enough phase
    directory path is outside what either of them cover.
    """
    if len(s) <= width:
        return s
    if width <= len(ELISION_MARKER):
        return ELISION_MARKER[:width]
    return s[: width - len(ELISION_MARKER)] + ELISION_MARKER


def line_number(text, offset):
    """The 1-indexed line number of `offset` within `text` (D-08: every
    violation names the line it is about, not only the file)."""
    return text.count("\n", 0, offset) + 1


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
    # `findall`, not `search`: a duplicated `current_phase:` key is invalid
    # YAML (a later key silently shadows an earlier one in most parsers, but
    # this file is read with a regex, not a YAML loader), and `search` took
    # only the FIRST match -- silently steering the gate at whichever phase
    # happened to match first instead of blocking on the ambiguity (D-04,
    # REVIEW-CRITICAL-FINAL shape 2). The body witness below already demanded
    # exactly one `Phase:` line; this makes the frontmatter witness parallel.
    fm_phases = STATE_CURRENT_PHASE_RE.findall(fm.group(1))
    if len(fm_phases) == 0:
        raise ValueError(
            f"{state_path} has no `current_phase: <number>` field;"
            " pass the phase directory explicitly"
        )
    if len(fm_phases) != 1:
        raise ValueError(
            f"{state_path} frontmatter carries {len(fm_phases)}"
            f" `current_phase: <number>` fields (need exactly one); pass"
            " the phase directory explicitly"
        )
    current_phase = fm_phases[0]
    # Second witness. See STATE_POSITION_SECTION_RE for why `Current Phase:`
    # is not an accepted label and why disagreement means block, not pick-one.
    section = STATE_POSITION_SECTION_RE.search(state_text[fm.end():])
    if not section:
        raise ValueError(
            f"{state_path} has no `## Current Position` section to corroborate"
            f" `current_phase: {current_phase}`; pass the phase directory explicitly"
        )
    body_phases = STATE_BODY_PHASE_RE.findall(section.group(1))
    if len(body_phases) != 1:
        raise ValueError(
            f"{state_path} `## Current Position` carries {len(body_phases)}"
            f" `Phase: <number>` lines to corroborate `current_phase:"
            f" {current_phase}` (need exactly one); pass the phase directory"
            " explicitly"
        )
    if normalize_phase(body_phases[0]) != normalize_phase(current_phase):
        raise ValueError(
            f"{state_path} disagrees with itself: frontmatter `current_phase:"
            f" {current_phase}` but `## Current Position` says `Phase:"
            f" {body_phases[0]}`; re-run /gsd-plan-phase for the phase you mean,"
            " or pass the phase directory explicitly"
        )
    wanted = normalize_phase(current_phase)
    phases_root = root / ".planning" / "phases"
    matches = []
    if phases_root.is_dir():
        for entry in sorted(phases_root.iterdir()):
            num = PHASE_NUM_RE.match(entry.name)
            # is_dir() follows symlinks, so a symlinked entry under
            # .planning/phases/ would otherwise resolve to a directory
            # anywhere on the filesystem and have its plan filenames
            # validated -- a real traversal out of the tree this gate is
            # scoped to (gsd-beads-25vc.21.1, AGY P2). is_symlink() is
            # required alongside is_dir(); do not drop it as redundant.
            if (
                entry.is_dir()
                and not entry.is_symlink()
                and num
                and normalize_phase(num.group(1)) == wanted
            ):
                matches.append(entry)
    if len(matches) != 1:
        raise ValueError(
            f"current_phase {current_phase} matches {len(matches)} directories"
            f" under {phases_root} (expected exactly 1)"
        )
    return matches[0]


def discover_plan_files(phase_dir):
    """Plan files directly inside phase_dir, sorted for determinism.

    Returns `(plans, misnamed)`: the `*-PLAN.md` files this gate validates, and
    the plan-shaped files PLAN_FILE_RE rejects. Both lists collect every match
    rather than stopping at the first, so a phase directory holding multiple
    plan files gets every one accounted for.

    Reporting the rejects rather than dropping them is the point. Silently
    skipping them made a phase whose only plan was misnamed indistinguishable
    from a phase whose plans all passed. A directory with no plan-shaped file
    at all is a different thing and still exits 0: that is a phase with
    nothing to check, not a phase whose plan went unread.
    """
    plans, misnamed = [], []
    for candidate in sorted(Path(phase_dir).iterdir()):
        if PLAN_FILE_RE.match(candidate.name):
            plans.append(candidate)
        elif PLAN_SHAPED_RE.search(candidate.name):
            misnamed.append(candidate)
    return plans, misnamed


def next_fence_opener(text, pos):
    """The first line at or after `pos` that opens a fenced code block."""
    for m in FENCE_LINE_RE.finditer(text, pos):
        # A backtick fence's info string may not itself contain a backtick.
        if m.group(1)[0] == "`" and "`" in m.group(2):
            continue
        return m
    return None


def fence_close(text, opener):
    """The offset just past `opener`'s closing fence, or EOF if unterminated."""
    marker = opener.group(1)
    for m in FENCE_LINE_RE.finditer(text, opener.end()):
        close, info = m.group(1), m.group(2)
        if close[0] == marker[0] and len(close) >= len(marker) and not info.strip():
            return m.end()
    return len(text)


def next_comment_opener(text, pos):
    """The offset of the next real `<!--` at or after `pos`, or -1.

    A `<!--` written inside a single-backtick, same-line inline code span is
    not a comment opener on the rendered page -- CommonMark renders the whole
    span, backticks included, as literal text -- so it must not mask
    anything past it (gsd-beads-25vc.21.1, P2-1). Skip any candidate whose
    own line contains a code span that covers it, and resume the search past
    that candidate; an unrelated span elsewhere on the line must not protect
    a different, uncovered candidate.

    Residual, documented rather than fixed: CommonMark permits an inline
    code span to cross a line break. This scan only looks at the candidate's
    own line, so a `<!--` protected only by a multi-line code span is still
    masked to EOF -- the same fail-closed direction as every other
    unterminated construct this module masks.
    """
    while True:
        cand = text.find(HTML_COMMENT_OPEN, pos)
        if cand < 0:
            return -1
        line_start = text.rfind("\n", 0, cand) + 1
        line_end = text.find("\n", cand)
        if line_end < 0:
            line_end = len(text)
        line, offset_in_line = text[line_start:line_end], cand - line_start
        if not any(
            m.start() <= offset_in_line < m.end()
            for m in INLINE_CODE_SPAN_RE.finditer(line)
        ):
            return cand
        pos = cand + len(HTML_COMMENT_OPEN)


# A plan's own leading YAML frontmatter block, distinct from
# STATE_FRONTMATTER_RE above: closes on either `---` or the YAML `...`
# document-end marker, matching how PyYAML and gsd-core's own frontmatter
# reader both terminate a document. Requires a closing delimiter to match
# at all -- an opening `---` with nothing that closes it is a thematic
# break or a setext H2 underline, not frontmatter, and must be left
# unmasked rather than blanked to EOF (D-01).
PLAN_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n.*?\r?\n(?:---|\.\.\.)[ \t]*\r?\n", re.DOTALL
)


def mask_leading_frontmatter(text):
    """Blank a plan's leading YAML frontmatter block, preserving offsets.

    A `## Alternatives Considered` heading declared only inside frontmatter
    -- alongside `phase:`, `plan:`, `must_haves:` and the like -- is
    CommonMark-invisible on the rendered page, exactly like a fence or an
    indented code block, but SECTION_HEADING_RE matched it anyway: a plan
    that never wrote a real body section still passed the gate (D-01,
    REVIEW-AGY-FINAL blocking item 2).

    Run first, before fence/comment/indented-code masking: frontmatter is
    a document-level construct bounded by literal `---`/`...` lines, not
    by CommonMark block syntax, so a fenced example or an indented block
    nested inside it must not be allowed to move or hide that boundary.
    """
    m = PLAN_FRONTMATTER_RE.match(text)
    if not m:
        return text
    start, end = m.span()
    return NON_NEWLINE_RE.sub(" ", text[start:end]) + text[end:]


def mask_fenced_regions(text):
    """Blank fenced code blocks and HTML comments, preserving offsets.

    Without this, the first `## Alternatives Considered` anywhere in the file
    won -- including one inside a ```markdown fence. README ships four fenced
    examples for authors to copy, so a plan that pasted an example (an `N/A --
    no mechanism choice` exemption, say) without writing a real section
    satisfied the blocking gate on the example's own text. Bullets and table
    rows inside a fence counted as real entries for the same reason.

    HTML comments are the same defect in the other syntax CommonMark hides
    from the rendered page, and the more reachable one: an author who drops
    two candidates late tends to comment them out "to keep the history"
    rather than delete them. Measured against the unmasked checker, a real
    heading whose only entries were commented out exited 0, and a section
    written entirely inside a comment exited 1 for the wrong reason --
    counting a commented bullet as an alternative. What the rendered plan
    does not say, the gate must not read.

    Replacing fenced bytes with spaces rather than deleting them keeps every
    offset intact, so the scans below stay one pass and slices still line up.
    An unterminated fence or comment blanks to EOF: it reads as a missing
    section and the gate blocks, the fail-closed direction.

    Openers are consumed left to right and whichever opens first wins, so a
    `<!--` inside a fence is code and a fence inside a comment is comment --
    matching CommonMark, where neither construct nests inside the other.

    CommonMark's other invisible-on-the-page construct is the indented code
    block: four or more leading spaces, no delimiter at all (D-02). Fences
    above are masked by explicit open/close bytes; an indented block is
    masked per line instead, by `mask_indented_code_blocks` below, run last
    so a fenced or commented interior -- already blank -- cannot forge the
    blank-line-before or list-marker state that scan reads.

    Leading YAML frontmatter is masked first of all, by
    `mask_leading_frontmatter`, since it is a document-level boundary that
    fence/comment/indented-code syntax must not be able to move or hide.

    A `<!--` written inside a same-line inline code span is not a comment
    opener either -- CommonMark renders the span, backticks and all, as
    literal text -- so `next_comment_opener` skips those candidates
    (gsd-beads-25vc.21.1, P2-1). Residual: a code span that crosses a line
    break is not detected, so a `<!--` protected only by one still masks to
    EOF -- the same fail-closed direction as every other unterminated
    construct here.
    """
    text = mask_leading_frontmatter(text)
    spans = []
    pos = 0
    while True:
        fence = next_fence_opener(text, pos)
        comment = next_comment_opener(text, pos)
        if fence is None and comment < 0:
            break
        if comment >= 0 and (fence is None or comment < fence.start()):
            close = text.find(HTML_COMMENT_CLOSE, comment + len(HTML_COMMENT_OPEN))
            pos = len(text) if close < 0 else close + len(HTML_COMMENT_CLOSE)
            spans.append((comment, pos))
        else:
            pos = fence_close(text, fence)
            spans.append((fence.start(), pos))
    if not spans:
        return mask_indented_code_blocks(text)
    out = []
    prev = 0
    for span_start, span_end in spans:
        out.append(text[prev:span_start])
        out.append(NON_NEWLINE_RE.sub(" ", text[span_start:span_end]))
        prev = span_end
    out.append(text[prev:])
    return mask_indented_code_blocks("".join(out))


def mask_indented_code_blocks(text):
    """Blank indented code blocks the same way the fence scan above blanks
    fences: same-length spaces for every non-newline byte, so offsets and
    line numbers survive (D-02, REVIEW-CRITICAL-FINAL P1-1a).

    A run starts at a non-blank line indented four or more spaces that
    follows a blank line, and continues -- through blank lines and further
    indented lines -- until the next non-blank line at zero to three spaces
    (https://spec.commonmark.org/0.31.2/#indented-code-blocks, 2024).

    Guarded by list context so an ordinary continuation paragraph under a
    bullet is never masked: a top-level list marker (0-3 spaces) sets the
    flag, any other non-blank 0-3-space line clears it, and a run may only
    start while the flag is clear. A 4+-space line never touches the flag,
    so it cannot change mid-run.
    """
    lines = text.splitlines(keepends=True)
    in_list = False
    prev_blank = True
    run_start = None
    for i, line in enumerate(lines):
        body = line[:-1] if line.endswith("\n") else line
        blank = body.strip() == ""
        if run_start is not None and not (blank or INDENTED_CODE_LINE_RE.match(body)):
            for j in range(run_start, i):
                lines[j] = NON_NEWLINE_RE.sub(" ", lines[j])
            run_start = None
        if run_start is None:
            if LIST_MARKER_RE.match(body):
                in_list = True
            elif not blank and SHALLOW_LINE_RE.match(body):
                in_list = False
            if not blank and prev_blank and not in_list and INDENTED_CODE_LINE_RE.match(body):
                run_start = i
        prev_blank = blank
    if run_start is not None:
        for j in range(run_start, len(lines)):
            lines[j] = NON_NEWLINE_RE.sub(" ", lines[j])
    return "".join(lines)


def extract_section_body(text):
    """The section body, its start offset in `text`, and what ended it.

    Returns `(body, body_start, boundary)`, or `(None, None, None)` when
    absent. `body` runs from just after the `## Alternatives Considered`
    line to the next H1/H2 heading or EOF. `body_start` is `body`'s offset
    within `text`, kept so a caller can turn an offset inside `body` back
    into a line number in the original document -- every violation names
    the line it is about, not only the file (D-08). `boundary` is None when
    the section reaches EOF, else `(heading_line, tail)` -- the heading that
    ended it, and everything from that heading onward.

    The boundary is returned rather than discarded so the diagnostic can tell
    "this is absent" from "this is below the line where the section ended".
    Both produce the same exit code but ask the author to fix opposite things,
    and the second reads as a false accusation when it is reported as the
    first: the `Decided by:` line the gate says is missing is visible on
    screen, three lines down, under a heading the author had not noticed
    writing.
    """
    m = SECTION_HEADING_RE.search(text)
    if not m:
        return None, None, None
    start = m.end()
    next_m = NEXT_HEADING_RE.search(text, start)
    if next_m is None:
        return text[start:], start, None
    end = next_m.start()
    return text[start:end], start, (text[end:].split("\n", 1)[0].strip(), text[end:])


def below_the_boundary(boundary, *patterns):
    """A clause naming what the boundary section lacks, when it is below it."""
    if boundary is None:
        return ""
    heading, tail = boundary
    if not any(p.search(tail) for p in patterns):
        return ""
    return (
        f"; the section ended at the heading '{elide_span(heading)}' and what it needs is"
        " below that heading -- move the heading down, or the content up"
    )


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
    alternatives` H3 section (if any) it falls under.

    Returns a list of `(name, entry_text, internal, offset)` tuples, where
    `offset` is the entry's own start position within `body` -- kept so a
    violation on one entry can name its own line, not just the file (D-08).
    """
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
            (match.group(1).strip(), body[match.start():end], internal, match.start())
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
                entries.append((m.group(1).strip(), row, internal, line_starts[row_i]))
    return entries or bullet_entries


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
    """Return a violation reason for one alternative entry, or None if it passes.

    Accumulates every applicable issue rather than stopping at the first, so
    a plan missing both a citation and a date reports both issues at once.
    """
    issues = []
    if not (URL_RE.search(entry_text) or DOC_REF_RE.search(entry_text)):
        issues.append("missing URL or doc-ref citation")
    years = [int(m.group(0)) for m in YEAR_RE.finditer(entry_text)]
    if not years:
        issues.append("no citation date")
    elif not any(today_year - RECENCY_WINDOW_YEARS <= y <= today_year for y in years):
        # At-least-one-in-window rule: a foundational citation year paired
        # with an in-window year already passes the `years` truthiness check
        # above -- this branch only fires when every year found is out of
        # window. `elide_values` bounds the displayed list to the first 5
        # distinct years (D-08): an entry text with no length cap of its own
        # (D-07, REVIEW-PROSE-TOKENS.md P1) must not turn "found" into an
        # unbounded dump of every four-digit number in the span.
        issues.append(
            f"no citation dated within the last {RECENCY_WINDOW_YEARS} years (found: {elide_values(years)})"
        )
    if entry_placeholder_violation(entry_text):
        issues.append("cites a placeholder URL or a bare TODO/TBD citation")
    if issues:
        return f"alternative '{elide_span(name)}': {'; '.join(issues)}"
    return None


def validate_plan(path):
    """Return None if `path` is compliant, else a `(line, reason)` violation.

    `line` is 1-indexed into the plan file: the heading line for a
    section-level violation (missing section, too few alternatives, no
    `Decided by:` line), or the entry's own line for a per-entry citation
    issue (D-08 -- every violation names the line it is about, not only
    the file).
    """
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
    except OSError as exc:
        # A plan-shaped name is not always a plan: a directory named like one
        # (`mkdir 11-01-PLAN.md`), or a file this process cannot read, used to
        # escape here as a raw IsADirectoryError/PermissionError traceback --
        # still fail-closed (any uncaught exception is non-zero and blocks),
        # but not the `check-alternatives.py: <path>: <reason>` contract the
        # module docstring promises for every other exit-2 case. The two
        # except arms are disjoint -- UnicodeDecodeError subclasses
        # ValueError, not OSError -- so this ordering is cosmetic; the decode
        # arm is kept first only so its more specific message reads first
        # when both could apply (gsd-beads-25vc.21.1, AGY P2).
        raise ValueError(
            f"{path}: could not be read ({exc.strerror});"
            " a plan-shaped name must be a readable file"
        ) from exc
    masked = mask_fenced_regions(text)
    body, body_start, boundary = extract_section_body(masked)
    if body is None:
        return (1, "missing '## Alternatives Considered' section")
    if is_exempt(body):
        return None
    heading_line = line_number(masked, body_start)
    entries = split_entries(body)
    if not entries:
        return (
            heading_line,
            "section found but no alternatives parsed; entries must be '- **Name**' bullets or bold-name table rows",
        )
    mechanism_entries = [
        (name, entry_text, offset)
        for name, entry_text, internal, offset in entries
        if not internal
    ]
    if len(mechanism_entries) < MIN_ALTERNATIVES:
        return (
            heading_line,
            f"fewer than 2 named alternatives (found {len(mechanism_entries)})"
            + below_the_boundary(boundary, BULLET_RE, TABLE_ROW_RE),
        )
    today_year = datetime.date.today().year
    for name, entry_text, offset in mechanism_entries:
        reason = validate_entry(name, entry_text, today_year)
        if reason:
            return (line_number(masked, body_start + offset), reason)
    if not DECIDED_BY_RE.search(body):
        return (
            heading_line,
            "no 'Decided by:' line naming a ranked criterion"
            + below_the_boundary(boundary, DECIDED_BY_RE),
        )
    return None


def phase_label_from_dirname(phase_dir_arg):
    """Phase number parsed from the leading `\\d+(?:\\.\\d+)?` of the
    phase_dir basename, or the literal `<phase>` placeholder when the
    basename doesn't start with a phase number."""
    m = PHASE_NUM_RE.match(Path(phase_dir_arg).name)
    return m.group(1) if m else "<phase>"


def check_alternatives(phase_dir_arg):
    """Validate every discovered plan; return the list of violations.

    Each violation is a (plan_path, line, reason) tuple; the list is empty
    when every discovered plan passes. The caller is responsible for
    confirming phase_dir sits inside a GSD project before calling this.
    """
    phase_dir_path = Path(phase_dir_arg)
    resolved_phase_dir = phase_dir_path.resolve()
    violations = []
    plans, misnamed = discover_plan_files(resolved_phase_dir)
    for plan_path in plans:
        result = validate_plan(plan_path)
        if result is not None:
            line, reason = result
            violations.append((plan_path, line, reason))
    # A misnamed file's violation is about its filename, not any line inside
    # it -- line 1 is the only line every file has, misnamed or not.
    violations.extend((path, 1, MISNAMED_PLAN_REASON) for path in misnamed)
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
        # The no-argument path above already established the project root via
        # resolve_current_phase_dir; this is the only branch that has not.
        try:
            find_project_root(phase_dir_arg)
        except ValueError as exc:
            print(f"check-alternatives.py: {exc}", file=sys.stderr)
            return 2

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

    # Only these two shapes interpolate plan-document text, so only these go
    # through the hard per-line backstop (D-07): every span quoted inside a
    # violation reason is already bounded at 80 chars (D-08), but the
    # surrounding fixed prose plus a long phase-directory path can still push
    # one line past 200 on its own.
    for plan_path, line, reason in violations:
        print(elide_line(f"{plan_path}:{line}: {reason}"), file=sys.stderr)
    phase_label = phase_label_from_dirname(phase_dir_arg)
    print(
        elide_line(
            f"remediation: fix the plans above, then re-run /gsd-plan-phase {phase_label} --force"
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
