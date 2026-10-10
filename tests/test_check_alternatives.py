"""Tests for .../scripts/check-alternatives.py. Stdlib unittest only (N5).

Runs the script as a subprocess (sys.executable) rather than importing it --
several cases assert on stderr text, which subprocess.run(...,
capture_output=True) gives directly with no extra plumbing. This is the one
place a subprocess is legitimate: the test harness, not the validator itself
(check-alternatives.py performs no child-process invocations of its own).
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "check-alternatives.py"
)
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

TODAY_YEAR = datetime.date.today().year
PLAN_TMPDIR = None


def setUpModule():
    global PLAN_TMPDIR
    PLAN_TMPDIR = Path(tempfile.mkdtemp(prefix="sota-numerics-tests-"))
    (PLAN_TMPDIR / ".planning").mkdir()


def tearDownModule():
    shutil.rmtree(PLAN_TMPDIR, ignore_errors=True)


def scratch_dir():
    return tempfile.TemporaryDirectory(dir=PLAN_TMPDIR)


def run_check(phase_dir, cwd=None):
    """Run the gate script on `phase_dir`. `cwd` matters only for the empty
    argument: `Path("")` is `Path(".")`, so an unguarded empty phase_dir
    would inspect the process working directory instead."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(phase_dir)],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=cwd,
        env={**os.environ, "TMPDIR": str(PLAN_TMPDIR)},
    )


def check(text, name="01-01-PLAN.md"):
    """Write `text` as the only plan in a fresh phase dir and run the gate."""
    with scratch_dir() as tmp:
        write_plan(tmp, text, name)
        return run_check(tmp)


def write_plan(dir_path, text, name="01-01-PLAN.md"):
    """Write `text` under `dir_path` as a discoverable plan name (fixtures hold
    section content only)."""
    Path(dir_path, name).write_text(text, encoding="utf-8")


def fixture_text(name):
    """Fixture text with its checked-in recency years rebased on today, so
    fixtures do not age out of the recency window."""
    return (
        (FIXTURES_DIR / name).read_text(encoding="utf-8")
        .replace("(2024)", f"({TODAY_YEAR})")
        .replace("(2023)", f"({TODAY_YEAR - 1})")
    )


def copy_fixture_dir(name, dest):
    for src in (FIXTURES_DIR / name).iterdir():
        write_plan(dest, fixture_text(f"{name}/{src.name}"), name=src.name)


class GateCase(unittest.TestCase):
    def gate(self, text, code, *has, lacks=(), name="01-01-PLAN.md"):
        """Run the gate on `text`; assert exit `code` and stderr substrings."""
        return self.expect(check(text, name), code, *has, lacks=lacks)

    def expect(self, result, code, *has, lacks=()):
        self.assertEqual(result.returncode, code, result.stderr)
        for s in has:
            self.assertIn(s, result.stderr)
        for s in lacks:
            self.assertNotIn(s, result.stderr)
        return result


COMPLIANT_ENTRY_TEMPLATE = """## Alternatives Considered

- **NumPy `numpy.linalg.solve`**: mature, BLAS/LAPACK-backed dense linear
  solver. `https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html`
  ({year_a}).
- **SciPy `scipy.linalg.lu_solve`**: exposes the LU factorization directly.
  `https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lu_solve.html`
  ({year_b}).

Decided by: performance — first-choice avoids a manual factorization step.
"""

SHAPE_ENTRIES = (
    (
        "Stable QR",
        "Householder reflections avoid normal-equation amplification.",
        "`https://numpy.org/doc/stable/reference/generated/numpy.linalg.qr.html`",
        TODAY_YEAR,
    ),
    (
        "Pivoted LU",
        "Partial pivoting is a fast dense-system baseline.",
        "`https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lu_factor.html`",
        TODAY_YEAR - 1,
    ),
)
SHAPE_DECISION = "Decided by: performance — QR is the stable first choice."


def bullet_plan(heading="## Alternatives Considered", entries=SHAPE_ENTRIES):
    body = "\n".join(
        f"- **{name}**: {prose} {citation} ({year})."
        for name, prose, citation, year in entries
    )
    return f"{heading}\n\n{body}\n\n{SHAPE_DECISION}\n", entries


def table_plan(heading="## Alternatives Considered", entries=SHAPE_ENTRIES):
    rows = "\n".join(
        f"| {rank} | **{name}**: {prose} | {citation} ({year}). |"
        for rank, (name, prose, citation, year) in enumerate(entries, 1)
    )
    return (
        f"{heading}\n\n| Rank | Mechanism | Evidence |\n"
        f"|---:|---|---|\n{rows}\n\n{SHAPE_DECISION}\n",
        entries,
    )


def split_across_boundary(boundary):
    """One cited alternative inside the section; a second one and the `Decided by:`
    line placed after `boundary`. Compliant exactly when `boundary` fails to end
    the section."""
    first, second = SHAPE_ENTRIES
    entries = [
        f"- **{name}**: {prose} {citation} ({year})."
        for name, prose, citation, year in (first, second)
    ]
    return (
        f"## Alternatives Considered\n\n{entries[0]}\n\n"
        f"{boundary}\n\n{entries[1]}\n\n{SHAPE_DECISION}\n"
    )


DOCUMENTED_MIXED_BODY = f"""## Alternatives Considered

- **Mechanism A**: cited mechanism evidence. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited mechanism evidence. `authoritative-doc-B` ({TODAY_YEAR}).

### Internal design alternatives

- **Local layout A**: project-local reasoning; no external citation required.
- **Local layout B**: project-local reasoning; no external citation required.

{SHAPE_DECISION}
"""


class TestMixedAlternatives(GateCase):
    def test_mixed_bullets_exits_0(self):
        self.gate(DOCUMENTED_MIXED_BODY, 0)

    def test_mixed_table_exits_0(self):
        text = f"""## Alternatives Considered

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Mechanism A** | `authoritative-doc-A` ({TODAY_YEAR}) |
| 2 | **Mechanism B** | `authoritative-doc-B` ({TODAY_YEAR}) |

### Internal design alternatives

| Rank | Design | Rationale |
| ---: | --- | --- |
| 1 | **Local layout A** | project-local reasoning |
| 2 | **Local layout B** | project-local reasoning |

{SHAPE_DECISION}
"""
        self.gate(text, 0)

    def test_internal_bullets_do_not_suppress_mechanism_table(self):
        text = f"""## Alternatives Considered

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Mechanism A** | `authoritative-doc-A` ({TODAY_YEAR}) |
| 2 | **Mechanism B** | `authoritative-doc-B` ({TODAY_YEAR}) |

### Internal design alternatives

- **Local layout A**: project-local reasoning.
- **Local layout B**: project-local reasoning.

{SHAPE_DECISION}
"""
        self.gate(text, 0)

    def test_internal_bullets_do_not_increase_table_mechanism_count(self):
        text = f"""## Alternatives Considered

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Only mechanism** | `authoritative-doc` ({TODAY_YEAR}) |

### Internal design alternatives

- **Local layout A**: project-local reasoning.
- **Local layout B**: project-local reasoning.

{SHAPE_DECISION}
"""
        self.gate(text, 1, "fewer than 2 named alternatives (found 1)")

    def test_internal_entries_do_not_count(self):
        text = f"""## Alternatives Considered

- **Only mechanism**: cited mechanism evidence. `authoritative-doc` ({TODAY_YEAR}).

### Internal design alternatives

- **Local layout A**: project-local reasoning.
- **Local layout B**: project-local reasoning.

{SHAPE_DECISION}
"""
        self.gate(text, 1, "fewer than 2 named alternatives (found 1)")

    def test_exact_marker_bounds_preceding_mechanism_evidence(self):
        text = f"""## Alternatives Considered

- **Deficient mechanism**: its evidence is deliberately absent.

### Internal design alternatives

Internal prose must not lend `https://numpy.org/doc/stable/` ({TODAY_YEAR}).
- **Local layout**: project-local reasoning.

### Continued mechanism alternatives

- **Mechanism B**: cited mechanism evidence. `authoritative-doc-B` ({TODAY_YEAR}).

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Deficient mechanism'", "missing URL or doc-ref citation", "no citation date")

    def test_peer_h3_after_exact_marker_resumes_mechanism_scope(self):
        text = f"""## Alternatives Considered

- **Mechanism A**: cited mechanism evidence. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited mechanism evidence. `authoritative-doc-B` ({TODAY_YEAR}).

### Internal design alternatives

- **Local layout**: project-local reasoning.

### Continued mechanism alternatives

- **Resumed mechanism**: its evidence is deliberately absent.

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Resumed mechanism'", "missing URL or doc-ref citation", "no citation date")

    def test_long_peer_h3_resumes_mechanism_bullet_scope(self):
        peer_heading = "### " + ("X" * 201)
        text = f"""## Alternatives Considered

- **Mechanism A**: cited mechanism evidence. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited mechanism evidence. `authoritative-doc-B` ({TODAY_YEAR}).

### Internal design alternatives

- **Local layout**: project-local reasoning.

{peer_heading}

- **Resumed mechanism**: its evidence is deliberately absent.

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Resumed mechanism'")

    def test_bare_peer_h3_resumes_mechanism_table_scope(self):
        text = f"""## Alternatives Considered

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Mechanism A** | `authoritative-doc-A` ({TODAY_YEAR}) |
| 2 | **Mechanism B** | `authoritative-doc-B` ({TODAY_YEAR}) |

### Internal design alternatives

| Rank | Design | Rationale |
| ---: | --- | --- |
| 1 | **Local layout** | project-local reasoning |

###

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 3 | **Resumed mechanism** | its evidence is deliberately absent |

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Resumed mechanism'")

    def test_mixed_section_missing_decided_by_fails(self):
        text = DOCUMENTED_MIXED_BODY.replace(f"\n{SHAPE_DECISION}\n", "\n")
        self.gate(text, 1, "no 'Decided by:' line naming a ranked criterion")


class TestMixedCompatibility(GateCase):
    def test_no_marker_bullets_and_table_exit_0(self):
        for text, _ in (bullet_plan(), table_plan()):
            with self.subTest(shape=text.splitlines()[2][:1]):
                self.gate(text, 0)

    def test_uncited_mechanism_still_fails(self):
        text = f"""## Alternatives Considered

- **Mechanism A**: cited. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited. `authoritative-doc-B` ({TODAY_YEAR}).
- **Uncited mechanism**: its evidence is deliberately absent.

### Internal design alternatives

- **Local layout**: project-local reasoning.

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Uncited mechanism'", "missing URL or doc-ref citation", "no citation date")

    def test_marker_variants_remain_mechanism_scope(self):
        variants = (
            "Inline prose mentions `### Internal design alternatives`.",
            "### internal design alternatives",
            "###  Internal design alternatives",
            "###\tInternal design alternatives",
            "#### Internal design alternatives",
            "### Internal design alternatives (local)",
        )
        for marker in variants:
            with self.subTest(marker=marker):
                text = f"""## Alternatives Considered

- **Mechanism A**: cited. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited. `authoritative-doc-B` ({TODAY_YEAR}).

{marker}

- **Local choice**: its evidence is deliberately absent.

{SHAPE_DECISION}
"""
                self.gate(text, 1, "alternative 'Local choice'")

    def test_exact_marker_allows_trailing_horizontal_whitespace(self):
        text = DOCUMENTED_MIXED_BODY.replace(
            "### Internal design alternatives",
            "### Internal design alternatives \t",
        )
        self.gate(text, 0)

    def test_marker_bearing_exemption_exits_0(self):
        text = """## Alternatives Considered

N/A — no mechanism choice

### Internal design alternatives

- **Local layout**: project-local reasoning.
"""
        self.gate(text, 0)

    def test_two_bullets_override_valid_table(self):
        bullets, _ = bullet_plan()
        text = bullets.replace(
            f"\n{SHAPE_DECISION}\n",
            f"""\n
| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Uncited table row** | project-local text |

{SHAPE_DECISION}
""",
        )
        self.gate(text, 0)

    def test_one_bullet_selects_valid_table(self):
        table, _ = table_plan()
        text = table.replace(
            "## Alternatives Considered\n\n",
            "## Alternatives Considered\n\n- **Ignored bullet**: no evidence.\n\n",
        )
        self.gate(text, 0)

    def test_bullet_and_table_do_not_combine(self):
        text = f"""## Alternatives Considered

- **Bullet mechanism**: cited. `authoritative-doc-A` ({TODAY_YEAR}).

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Table mechanism** | `authoritative-doc-B` ({TODAY_YEAR}) |

{SHAPE_DECISION}
"""
        self.gate(text, 1, "fewer than 2 named alternatives (found 1)")

    def test_unrelated_h3_without_marker_does_not_extend_the_evidence_span(self):
        text = f"""## Alternatives Considered

- **Mechanism A**: evidence continues below.

### Other notes

Continuation with `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited. `authoritative-doc-B` ({TODAY_YEAR}).

{SHAPE_DECISION}
"""
        self.gate(text, 1, "alternative 'Mechanism A'", "missing URL or doc-ref citation")


class TestDocumentedSyntax(GateCase):
    def test_readme_and_planner_name_exact_mixed_contract(self):
        control, _ = bullet_plan()
        self.gate(control, 0)

        root = Path(__file__).resolve().parent.parent
        marker = "### Internal design alternatives"
        contract = (
            "Internal entries need no external citation or date, do not count toward "
            "the two mechanism alternatives, and cannot lend evidence to a mechanism entry."
        )
        paths = (
            root / "README.md",
            root / "fragments/planner-sota.md",
        )
        missing = [
            str(path)
            for path in paths
            if marker not in path.read_text(encoding="utf-8")
            or contract not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])

    def test_documented_mixed_body_exits_0(self):
        self.gate(DOCUMENTED_MIXED_BODY, 0)


class TestSectionPresence(GateCase):
    """The section heading itself."""

    def test_missing_section_exits_1(self):
        self.gate(fixture_text("plan-missing-section.md"), 1, "Alternatives Considered")

    def test_suffixed_heading_accepts_identical_bullet_body(self):
        exact, exact_entries = bullet_plan()
        suffixed, suffixed_entries = bullet_plan("## Alternatives Considered (REQ-10)")
        self.assertEqual(exact.split("\n\n", 1)[1], suffixed.split("\n\n", 1)[1])
        self.assertEqual(exact_entries, suffixed_entries)
        self.gate(suffixed, 0)

    def test_concatenated_heading_remains_missing(self):
        text, _ = bullet_plan("## Alternatives ConsideredFoo")
        self.gate(text, 1, "missing '## Alternatives Considered' section")


class TestSectionBoundary(GateCase):
    """Which heading forms end the section body.

    H1 and H2 (up to three leading spaces) end it; entries after one must not be
    donated to the section. H3 and deeper stay inside: `### Internal design
    alternatives` is a documented in-section construct. Donation cases assert the
    *reason*: an uncited donated entry also exits 1, but names the donated bullet."""

    def assert_does_not_donate(self, boundary):
        self.gate(split_across_boundary(boundary), 1, "fewer than 2 named alternatives (found 1)", lacks=(SHAPE_ENTRIES[1][0],))

    def assert_stays_inside(self, boundary):
        self.gate(split_across_boundary(boundary), 0)

    def test_a_truncating_heading_is_named_in_the_count_message(self):
        self.gate(split_across_boundary("Timing table\n============"), 1, "fewer than 2 named alternatives (found 1)", "the section ended at the heading 'Timing table'")

    def test_a_truncating_heading_is_named_rather_than_a_missing_field(self):
        # Same exit code, opposite instruction to the author. The
        # `Decided by:` line is not absent -- it is three lines down, below a
        # heading nobody noticed writing. Reported as absence, the message
        # sends the author to fix a line that is already correct, which is how
        # a correct block still wastes the round.
        entries = "\n".join(
            f"- **{name}**: {prose} {citation} ({year})."
            for name, prose, citation, year in SHAPE_ENTRIES)
        self.gate(f"## Alternatives Considered\n\n{entries}\n\n"
                            f"Timing table\n============\n\n{SHAPE_DECISION}\n", 1, "no 'Decided by:' line", "the section ended at the heading 'Timing table'")

    def test_a_boundary_is_not_blamed_when_the_field_is_simply_absent(self):
        # The note exists to stop a misdiagnosis. Firing it unconditionally
        # would be the same misdiagnosis pointing the other way: sending an
        # author to move a heading when what they owe is a line they never
        # wrote.
        entries = "\n".join(
            f"- **{name}**: {prose} {citation} ({year})."
            for name, prose, citation, year in SHAPE_ENTRIES)
        self.gate(f"## Alternatives Considered\n\n{entries}\n\n"
                            "## Approach\n\nNothing relevant here.\n", 1, "no 'Decided by:' line", lacks=("the section ended at the heading",))

    def test_h3_does_not_end_the_section(self):
        self.assert_stays_inside("### Notes")


# One generated test per boundary form, so a failure names the form.
# True: the form ends the section (a later entry must not be donated to it);
# False: it does not (the plan must still pass).
_BOUNDARIES = {
    "h2_ends_the_section": ("## Later Section", True),
    "h1_ends_the_section": ("# Later Section", True),
    "indented_h2_ends_the_section": ("   ## Later Section", True),
    "indented_h1_ends_the_section": ("   # Later Section", True),
    # A setext H1 is an H1; only its spelling differs.
    "setext_h1_ends_the_section": ("Later Section\n=============", True),
    # `---` is a setext H2 underline, a thematic break and a frontmatter fence;
    # treating it as a boundary would false-block a plan with a rule between
    # its alternatives.
    "thematic_break_does_not_end_the_section": ("---", False),
    # `===` with no paragraph above is not a heading in CommonMark.
    "bare_setext_rule_does_not_end_the_section": ("===", False),
}


def _boundary_test(boundary, ends):
    def test(self):
        (self.assert_does_not_donate if ends else self.assert_stays_inside)(boundary)
    return test


for _name, (_boundary, _ends) in _BOUNDARIES.items():
    setattr(TestSectionBoundary, f"test_{_name}", _boundary_test(_boundary, _ends))


class TestSupportedEntryShapes(GateCase):
    def test_table_accepts_same_semantics_as_bullets(self):
        bullets, _ = bullet_plan()
        table, _ = table_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, bullets)
            bullet_result = run_check(tmp)
            write_plan(tmp, table)
            table_result = run_check(tmp)
        self.assertEqual(bullet_result.returncode, 0)
        self.assertEqual(table_result.returncode, 0)

    def test_table_evidence_is_scoped_to_its_row(self):
        deficient = ("Uncited option", "Its proof is deliberately elsewhere.", "", "")
        text, _ = table_plan(entries=(deficient, SHAPE_ENTRIES[1]))
        self.gate(text, 1, "alternative 'Uncited option'", "missing URL or doc-ref citation", "no citation date")

    def test_present_section_without_supported_entries_has_distinct_message(self):
        text = f"## Alternatives Considered\n\nplain text only\n\n{SHAPE_DECISION}\n"
        self.gate(text, 1, "section found but no alternatives parsed", "bullets", "table")

    def test_one_table_row_excludes_bold_header_and_separator(self):
        only_entry = SHAPE_ENTRIES[:1]
        text, _ = table_plan(entries=only_entry)
        text = text.replace(
            "| Rank | Mechanism | Evidence |",
            f"| Rank | **Not an alternative** | `{TODAY_YEAR}` |",
        )
        self.gate(text, 1, "fewer than 2 named alternatives (found 1)")

    def test_pipe_rows_without_separator_are_not_a_markdown_table(self):
        rows = "\n".join(
            f"| **{name}**: {prose} {citation} ({year}). |"
            for name, prose, citation, year in SHAPE_ENTRIES
        )
        text = f"## Alternatives Considered\n\n{rows}\n\n{SHAPE_DECISION}\n"
        self.gate(text, 1, "section found but no alternatives parsed")

    def test_bullet_control_remains_accepted(self):
        text, _ = bullet_plan()
        self.gate(text, 0)


class TestBulletIndentationBound(GateCase):
    """`BULLET_RE` and the table-row scan bound indentation to CommonMark's
    zero-to-three-space top-level range, so four-space sub-entries under an
    organizational bullet do not satisfy "at least two named alternatives".
    `mask_indented_code_blocks` does not cover this: it never masks inside an
    open list item."""

    def test_entries_stated_only_as_four_space_sub_bullets_are_not_top_level(self):
        text = (
            "## Alternatives Considered\n\n"
            "- Candidates evaluated:\n"
            f"    - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **Pivoted LU**: baseline. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        self.gate(text, 1, "section found but no alternatives parsed")

    def test_entries_stated_only_as_four_space_table_rows_are_not_top_level(self):
        text = (
            "## Alternatives Considered\n\n"
            "- Candidates evaluated:\n\n"
            "    | Rank | Mechanism | Evidence |\n"
            "    |---:|---|---|\n"
            f"    | 1 | **Householder QR**: stable. | `https://numpy.org/doc` ({TODAY_YEAR}). |\n"
            f"    | 2 | **Pivoted LU**: baseline. | `https://scipy.org/doc` ({TODAY_YEAR}). |\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        self.gate(text, 1, "section found but no alternatives parsed")

    def test_zero_to_three_space_indented_bullets_still_count(self):
        # CommonMark's own top-level range: a bullet indented up to three
        # spaces is unaffected by the bound and must keep passing.
        text = (
            "## Alternatives Considered\n\n"
            f"   - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"   - **Pivoted LU**: baseline. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        self.gate(text, 0)

    def test_a_compliant_top_level_entry_still_draws_citation_from_a_sub_bullet(self):
        # Negative case: a compliant top-level entry that carries an
        # indented sub-bullet underneath must still count, and the
        # sub-bullet must still contribute its citation/year to the parent
        # entry -- the bound applies only to what counts as a NEW top-level
        # entry, never to a top-level entry's own continuation content.
        text = (
            "## Alternatives Considered\n\n"
            "- **Householder QR**: stable algorithm.\n"
            f"    - Citation: `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"- **Pivoted LU**: baseline. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        self.gate(text, 0)


class TestCitationAndDate(GateCase):
    """Citation and recency-date requirements."""

    def test_uncited_undated_exits_1_names_both_issues(self):
        self.gate(fixture_text("plan-uncited.md"), 1, "citation", "date")

    def test_example_com_placeholder_url_exits_1(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: a placeholder source. `https://example.com/docs` ({TODAY_YEAR}).\n"
            f"- **Option B**: a real source. `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — Option A is faster.\n"
        )
        self.gate(text, 1)

    def test_stale_only_year_exits_1(self):
        stale_year = TODAY_YEAR - 10
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: cited once, a decade stale. `https://numpy.org/doc/stable/` ({stale_year}).\n"
            f"- **Option B**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — Option A was the original pick.\n"
        )
        self.gate(text, 1, str(stale_year))


class TestRecencyEdges(GateCase):
    def _run(self, year):
        return check(
            "## Alternatives Considered\n\n"
            f"- **A**: `https://numpy.org/doc/stable/` ({year}).\n"
            f"- **B**: `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — B.\n"
        )

    def test_six_years_old_passes(self):
        self.assertEqual(self._run(TODAY_YEAR - 6).returncode, 0)

    def test_seven_years_old_fails(self):
        self.assertEqual(self._run(TODAY_YEAR - 7).returncode, 1)

    def test_future_year_fails(self):
        self.assertEqual(self._run(TODAY_YEAR + 1).returncode, 1)


class TestDecidedBy(GateCase):
    """The ranked-criterion line."""

    def test_missing_decided_by_exits_1(self):
        compliant = fixture_text("plan-compliant.md")
        stripped_lines = [
            line for line in compliant.splitlines() if "Decided by:" not in line
        ]
        self.gate("\n".join(stripped_lines) + "\n", 1, "Decided by")


class TestEntryBoundary(GateCase):
    """An entry ends where its bullet does, not at the end of the section."""

    def test_decided_by_url_year_is_not_the_last_entrys_citation(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **A**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
            "- **B**: no source here.\n\n"
            f"Decided by: performance, see https://x.dev {TODAY_YEAR}\n"
        )
        self.gate(text, 1, "alternative 'B'")


class TestNonAlternativeBullets(GateCase):
    """Reserved labels are not alternatives; duplicate names count once."""

    def test_reserved_label_bullet_is_not_an_alternative(self):
        for label in ("Rationale", "why", "Note:", "Chosen", "DECISION", "Decided by"):
            with self.subTest(label=label):
                text = (
                    "## Alternatives Considered\n\n"
                    f"- **A**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
                    f"- **{label}**: `https://x.dev/y` ({TODAY_YEAR}).\n\n"
                    "Decided by: performance — A.\n"
                )
                self.gate(text, 1, "fewer than 2 named alternatives (found 1)")

    def test_duplicate_names_count_once_case_insensitively(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Redis**: `https://redis.io/docs/` ({TODAY_YEAR}).\n"
            f"- **redis**: `https://redis.io/docs/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — Redis.\n"
        )
        self.gate(text, 1, "fewer than 2 named alternatives (found 1)")


class TestDecidedByBoundary(GateCase):
    def _run(self, decided):
        return check(
            "## Alternatives Considered\n\n"
            f"- **A**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
            f"- **B**: `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            f"{decided}\n"
        )

    def test_each_of_the_five_criteria_is_accepted(self):
        for criterion in ("performance", "simplicity", "LOC", "ecosystem", "maintenance"):
            with self.subTest(criterion=criterion):
                result = self._run(f"Decided by: {criterion} — reason.")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unlisted_criterion_is_rejected(self):
        result = self._run("Decided by: vibes — reason.")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no 'Decided by:' line", result.stderr)

    def test_criterion_must_be_a_whole_word(self):
        for value in ("LOCKED in", "performances", "ecosystems"):
            with self.subTest(value=value):
                result = self._run(f"Decided by: {value}")
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_bold_criterion_value_is_accepted(self):
        for line in ("Decided by: **performance** — fast.", "**Decided by:** **LOC** — small."):
            with self.subTest(line=line):
                result = self._run(line)
                self.assertEqual(result.returncode, 0, result.stderr)


class TestPlaceholderHostEvasion(GateCase):
    def test_port_subdomain_userinfo_and_case_do_not_evade(self):
        for url in (
            "http://localhost:8080/x",
            "https://www.example.com/docs",
            "https://user@example.org/x",
            "https://EXAMPLE.NET./x",
            "https://api.docs.example.com:443/x",
        ):
            with self.subTest(url=url):
                self.gate("## Alternatives Considered\n\n"
                    f"- **A**: {url} ({TODAY_YEAR}).\n"
                    f"- **B**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
                    "Decided by: performance — B.\n", 1, "placeholder")

    def test_lookalike_host_is_not_a_placeholder(self):
        self.gate("## Alternatives Considered\n\n"
            f"- **A**: https://notexample.com/x ({TODAY_YEAR}).\n"
            f"- **B**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — B.\n", 0)


class TestYearBelongsToCitation(GateCase):
    def _run(self, entry_a):
        return check(
            "## Alternatives Considered\n\n"
            f"{entry_a}\n"
            f"- **B**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — B.\n"
        )

    def test_year_in_unrelated_clause_does_not_date_the_citation(self):
        result = self._run(
            f"- **A**: first shipped in {TODAY_YEAR}. See `https://redis.io/docs/` for details."
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("date", result.stderr)

    def test_year_in_citation_clause_passes(self):
        for entry in (
            f"- **A**: fast. `https://redis.io/docs/` ({TODAY_YEAR}).",
            f"- **A**: fast. Accessed {TODAY_YEAR}: https://redis.io/docs/",
        ):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(entry).returncode, 0)

    def test_placeholder_tokens_are_not_doc_refs(self):
        for token in ("none", "n/a", "N/A", "TBD", "?"):
            with self.subTest(token=token):
                result = self._run(f"- **A**: fast. `{token}` ({TODAY_YEAR}).")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("alternative 'A'", result.stderr)


class TestPlaceholderCitations(GateCase):
    def test_placeholder_hosts_and_tokens_are_rejected(self):
        for cite in (
            "https://example.org/x",
            "http://localhost/x",
            "HTTPS://EXAMPLE.COM/x",
            "`TBD`",
            "`TODO`",
        ):
            with self.subTest(cite=cite):
                self.gate("## Alternatives Considered\n\n"
                    f"- **A**: {cite} ({TODAY_YEAR}).\n"
                    f"- **B**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
                    "Decided by: performance — B.\n", 1, "alternative 'A'")


class TestMinimumCount(GateCase):
    def test_one_alternative_exits_1(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Only Option**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — only one considered.\n"
        )
        self.gate(text, 1, "fewer than 2")

    def test_two_alternatives_exits_0(self):
        text = COMPLIANT_ENTRY_TEMPLATE.format(year_a=TODAY_YEAR, year_b=TODAY_YEAR - 1)
        self.gate(text, 0)


class TestExemption(GateCase):
    def test_exempt_plan_exits_0(self):
        self.gate(fixture_text("plan-exempt.md"), 0)


class TestFencedRegions(GateCase):
    """A `## Alternatives Considered` inside a code fence is illustration, not a
    decision record. A fence-only heading must NOT count, and a fence must not
    hide a real heading that follows it."""

    def test_fenced_only_heading_does_not_satisfy_the_gate(self):
        self.gate(fixture_text("plan-fenced-only.md"), 1, "missing '## Alternatives Considered' section")

    def test_fenced_example_before_a_real_section_still_passes(self):
        self.gate(fixture_text("plan-fenced-then-real.md"), 0)

    def test_fenced_entries_do_not_count_toward_the_minimum(self):
        plan = (
            "## Alternatives Considered\n\n"
            f"- **Real mechanism**: prose. `real-doc` ({TODAY_YEAR}).\n\n"
            "```markdown\n"
            f"- **Example mechanism**: prose. `example-doc` ({TODAY_YEAR}).\n"
            "```\n\n"
            "Decided by: performance.\n"
        )
        self.gate(plan, 1, "fewer than 2 named alternatives (found 1)")

    def test_tilde_fence_is_skipped_too(self):
        plan = (
            "## Approach\n\n~~~markdown\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n~~~\n"
        )
        self.gate(plan, 1, "missing '## Alternatives Considered' section")

    def test_unterminated_fence_fails_closed(self):
        # An unterminated fence blanks to EOF. The section then reads as
        # missing, which blocks -- the safe direction for a blocking gate.
        plan = (
            "## Approach\n\n```markdown\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n"
        )
        self.gate(plan, 1)

    def test_inline_backticks_are_not_mistaken_for_a_fence(self):
        # Doc-ref citations are backtick-delimited; only a line of three or
        # more opens a fence, so ordinary citations must survive untouched.
        text, _ = bullet_plan()
        self.gate(text, 0)

    # Each FENCE_LINE_RE condition (anchor, three-marker minimum, info-string rule)
    # fails the same way if dropped: a false opener blanks to EOF and a compliant
    # plan is blocked. One case each, asserting the reason.

    def test_a_backtick_run_mid_line_does_not_open_a_fence(self):
        # CommonMark: a fence opener starts its line. Without the anchor, prose
        # that ends in a marker opens a fence nothing closes.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "The marker is written ```\n\n" + SHAPE_DECISION)
        self.gate(plan, 0)

    def test_a_two_marker_run_does_not_open_a_fence(self):
        # CommonMark: three or more. Strikethrough at the start of a line is
        # two tildes, and the info-string rule below does not cover tildes, so
        # the count is the only thing keeping this from opening a fence.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "~~An earlier approach~~ is not considered.\n\n"
                            + SHAPE_DECISION)
        self.gate(plan, 0)

    def test_a_backtick_info_string_does_not_open_a_fence(self):
        # CommonMark: a backtick fence's info string may not contain a
        # backtick, which is what makes ```code``` an inline code span on its
        # own line rather than an opener.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "```code``` is how this plan writes it.\n\n"
                            + SHAPE_DECISION)
        self.gate(plan, 0)


class TestIndentedCodeBlocks(GateCase):
    """A four-space indented code block is invisible on the rendered page, like a
    fence (see `TestFencedRegions`)."""

    def test_indented_alternatives_are_not_counted_as_prose(self):
        # A real column-0 heading, but entries and Decided-by sit four spaces in:
        # CommonMark renders inert code, so this must exit 1.
        plan = (
            "## Alternatives Considered\n\n"
            "Example of the required shape:\n\n"
            f"    - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **Pivoted LU**: baseline. `https://docs.scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "    Decided by: performance -- QR is the stable first choice.\n\n"
            "That is all; this plan makes no real comparison.\n"
        )
        self.gate(plan, 1, "section found but no alternatives parsed")

    def test_a_wholly_indented_heading_and_body_is_still_a_missing_section(self):
        # SECTION_HEADING_RE is anchored `^##` at column 0, so an indented heading
        # is invisible to it; pinned so a change to that anchor cannot credit it.
        plan = (
            "Some intro paragraph, not a list.\n\n"
            "    ## Alternatives Considered\n\n"
            f"    - **NumPy**: mature. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **SciPy**: alternative. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "    Decided by: performance.\n"
        )
        self.gate(plan, 1, "missing '## Alternatives Considered' section")

    def test_a_bullet_continuation_paragraph_is_not_treated_as_code(self):
        # Negative case: an ordinary continuation paragraph under a
        # top-level bullet, indented four spaces because that is still
        # inside the list item, is prose -- not an indented code block --
        # and must never be masked.
        text, _ = bullet_plan()
        plan = text.replace(
            SHAPE_DECISION,
            "    A continuation paragraph for the entry above, indented\n"
            "    four spaces because it is still inside the list item.\n\n"
            + SHAPE_DECISION,
        )
        self.gate(plan, 0)

    def test_an_unrelated_indented_code_block_does_not_affect_a_compliant_section(self):
        text, _ = bullet_plan()
        plan = (
            "Setup note.\n\n"
            "    $ pip install numpy scipy\n"
            "    $ python solve.py\n\n"
        ) + text
        self.gate(plan, 0)


class TestFrontmatterMasking(GateCase):
    """Leading YAML frontmatter is invisible on the rendered page, so a section
    declared only inside it must not be credited."""

    def test_a_section_declared_only_in_frontmatter_is_a_missing_section(self):
        plan = (
            "---\n"
            "## Alternatives Considered\n\n"
            f"- **NumPy**: mature. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"- **SciPy**: alternative. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance.\n"
            "---\n\n"
            "Real body text with no section of its own.\n"
        )
        self.gate(plan, 1, "missing '## Alternatives Considered' section")

    def test_frontmatter_beside_a_real_body_section_still_passes(self):
        text, _ = bullet_plan()
        plan = (
            "---\n"
            "phase: 24\n"
            "plan: 01\n"
            "must_haves:\n"
            "  - a real requirement\n"
            "  - another real requirement\n"
            "---\n\n"
        ) + text
        self.gate(plan, 0)

    def test_a_document_without_frontmatter_is_unaffected(self):
        text, _ = bullet_plan()
        self.gate(text, 0)

    def test_an_unclosed_leading_dashes_line_is_not_treated_as_frontmatter(self):
        # First line is exactly `---`, but nothing that follows closes it
        # with a line that is exactly `---` or `...` -- this is a
        # thematic break (or a setext H2 underline for an empty
        # preceding paragraph), not a frontmatter opener, and must be
        # scanned exactly as it was before this task's change.
        text, _ = bullet_plan()
        plan = "---\n\n" + text
        self.gate(plan, 0)


class TestHtmlComments(GateCase):
    """An `## Alternatives Considered` inside an HTML comment renders nothing, so it
    records nothing. Every case asserts the REASON, since commented text could
    also exit non-zero for the wrong one."""

    def test_commented_only_heading_does_not_satisfy_the_gate(self):
        self.gate(fixture_text("plan-commented-only.md"), 1, "missing '## Alternatives Considered' section")

    def test_commented_entries_do_not_count_toward_the_minimum(self):
        self.gate(fixture_text("plan-commented-entries.md"), 1, "no alternatives parsed")

    def test_commented_example_before_a_real_section_still_passes(self):
        self.gate(fixture_text("plan-commented-then-real.md"), 0)

    def test_unterminated_comment_fails_closed(self):
        plan = (
            "## Approach\n\n<!--\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n"
        )
        self.gate(plan, 1, "missing '## Alternatives Considered' section")

    def test_a_comment_opener_inside_a_fence_is_code_not_a_comment(self):
        # Whichever construct opens first owns the span, as in CommonMark:
        # a lone `<!--` quoted inside a fence must not swallow the real
        # section that follows the fence.
        text, _ = bullet_plan()
        plan = "## Approach\n\n```markdown\n<!--\n```\n\n" + text
        self.gate(plan, 0)

    def test_a_fence_opener_inside_a_comment_does_not_open_a_fence(self):
        # The mirror image: a ``` inside a comment must not leave a fence open
        # across the real section and blank it to EOF.
        text, _ = bullet_plan()
        plan = "## Approach\n\n<!--\n```\n-->\n\n" + text
        self.gate(plan, 0)

    def test_a_backticked_comment_opener_does_not_open_a_comment(self):
        # A `<!--` written inside a single-backtick inline code span renders
        # as literal text on the page -- CommonMark shows the backticks and
        # the arrows, not a comment -- so it must not start a masked span.
        text, _ = bullet_plan()
        plan = "We discuss `<!--` markers here.\n\n" + text
        self.gate(plan, 0)

    def test_an_unrelated_code_span_does_not_protect_a_real_opener_on_the_same_line(
        self,
    ):
        # The backtick-span check must protect only a `<!--` that is itself
        # inside a span. An unrelated span earlier on the line must not act
        # as a blanket exemption for a real, unprotected opener later on the
        # same line -- that would turn the fix into a bypass.
        plan = f"Uses `numpy`. <!--\n{_H}{_A}{_B}-->\n"
        self.gate(plan, 1, "missing '## Alternatives Considered' section")

    def test_an_unterminated_backtick_before_an_opener_is_not_a_code_span(self):
        # An unterminated backtick is not a code span -- CommonMark requires
        # a matching closing run of the same length on the same line here --
        # so the opener is unprotected. It is also unterminated mid-paragraph,
        # so it is no comment and hides nothing.
        text, _ = bullet_plan()
        plan = "`a <!--\n" + text
        self.gate(plan, 0)

    def test_a_protected_backtick_candidate_does_not_disturb_fence_precedence(self):
        # A skipped (backtick-protected) comment candidate earlier in the
        # text must not disturb the "whichever construct opens first wins"
        # rule between the fence path and the real comment path.
        text, _ = bullet_plan()
        plan = (
            "We discuss `<!--` markers here.\n\n"
            "```markdown\n<!--\n```\n\n" + text
        )
        self.gate(plan, 0)


class TestCurrentPhaseResolution(GateCase):
    """With no argument the checker resolves its phase from the project's own
    STATE.md. No directory name is spliced into the `sh -c` string, so this path
    must fail CLOSED whenever it is unsure."""

    def build_project(self, root, phase_dir_name, current_phase, plan_text,
                      position="Phase: {phase} (Name) — READY TO EXECUTE"):
        (root / ".planning" / "phases" / phase_dir_name).mkdir(parents=True)
        (root / ".planning" / "STATE.md").write_text(
            "---\ngsd_state_version: 1.0\n"
            f"current_phase: {current_phase}\nstatus: planning\n---\n"
            "\n# Project State\n\n## Current Position\n\n"
            + position.format(phase=current_phase)
            + "\nPlan: 1 of 1\nStatus: Ready to execute\n",
            encoding="utf-8",
        )
        write_plan(root / ".planning" / "phases" / phase_dir_name, plan_text,
                   name="11-01-PLAN.md")

    def resolve_state(self, state, *dirs):
        """Write a raw STATE.md and phase dirs `(name, plan_text_or_None)`, run the gate."""
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(state, encoding="utf-8")
            for name, plan in dirs:
                (root / ".planning" / "phases" / name).mkdir()
                if plan is not None:
                    write_plan(root / ".planning" / "phases" / name, plan, name="11-01-PLAN.md")
            return self.run_no_arg(root)

    def resolve(self, *args, **kw):
        """Build a project via `build_project` and run the gate with no argument."""
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, *args, **kw)
            return self.run_no_arg(root)

    def run_no_arg(self, cwd):
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, timeout=15, cwd=str(cwd),
            env={**os.environ, "TMPDIR": str(PLAN_TMPDIR)},
        )

    def test_resolves_the_current_phase_and_reaches_its_verdict(self):
        self.expect(self.resolve("11-plain", "11",
                               fixture_text("plan-missing-section.md")), 1, "11-01-PLAN.md")

    def test_apostrophe_in_the_phase_directory_name_is_accepted(self):
        # An apostrophe in the directory name must not break the gate invocation.
        self.expect(self.resolve("11-o'brien", "11",
                               fixture_text("plan-compliant.md")), 0)

    def test_zero_padded_current_phase_matches_an_unpadded_directory(self):
        self.expect(self.resolve("6-six", "06", fixture_text("plan-compliant.md")), 0)

    def test_missing_current_phase_blocks(self):
        result = self.resolve_state(
            "---\ngsd_state_version: 1.0\nstatus: planning\n---\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("current_phase", result.stderr)

    def test_state_md_without_frontmatter_blocks(self):
        # Without the guard the resolver dereferences a None match and dies on
        # a traceback -- still non-zero, but exit 1 means "these plans are bad"
        # and nothing here was ever read. Only the shell suite touched this
        # path, and it does not reach this shape.
        result = self.resolve_state(
            "# Project State\n\ncurrent_phase: 11\n",
            ("11-plain", fixture_text("plan-compliant.md")))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no YAML frontmatter block", result.stderr)

    def test_current_phase_in_prose_does_not_redirect_the_gate(self):
        # Phase identity comes from the frontmatter, never document content: a
        # `current_phase:` line in prose must not point the gate at another phase.
        #
        # Prose and `## Current Position` agree with each other but not with the
        # frontmatter (which has no `current_phase`), so only the frontmatter-only
        # scan stands between the gate and phase 99.
        result = self.resolve_state(
            "---\ngsd_state_version: 1.0\nstatus: planning\n---\n"
            "\nprose that merely mentions:\n\ncurrent_phase: 99\n"
            "\n## Current Position\n\nPhase: 99 (Decoy) — READY TO EXECUTE\n",
            ("11-real", fixture_text("plan-missing-section.md")), ("99-decoy", fixture_text("plan-compliant.md")))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no `current_phase: <number>` field", result.stderr)
        self.assertNotIn("99-decoy", result.stderr)

    def test_ambiguous_current_phase_blocks(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-a", "11", fixture_text("plan-compliant.md"))
            (root / ".planning" / "phases" / "11-b").mkdir()
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected exactly 1", result.stderr)

    def test_unmatched_current_phase_blocks(self):
        self.expect(self.resolve("11-plain", "12", fixture_text("plan-compliant.md")), 2, "expected exactly 1")

    def test_dotted_current_phase_does_not_match_a_longer_sibling(self):
        # `10.1` must not resolve to `10.10`: the fractional part is compared
        # as text, so a truncated match cannot silently validate another phase.
        self.expect(self.resolve("10.10-ten-ten", "10.1",
                               fixture_text("plan-compliant.md")), 2, "expected exactly 1")

    # Two witnesses, not one: `current_phase` and the `## Current Position`
    # `Phase:` line must agree. Every case asserts the refusal REASON, since
    # the exit code alone cannot tell a verdict from a gate that checked the
    # wrong thing.

    def test_stale_frontmatter_under_a_non_canonical_position_label_blocks(self):
        # `Current Phase:` is a section gsd-core cannot rewrite, so both witnesses
        # still name phase 11 after phase 99 was planned; trusting `current_phase`
        # alone would pass the compliant stale phase.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-stale", "11",
                               fixture_text("plan-compliant.md"),
                               position="Current Phase: {phase} (Stale)")
            (root / ".planning" / "phases" / "99-just-planned").mkdir()
            write_plan(root / ".planning" / "phases" / "99-just-planned",
                       fixture_text("plan-missing-section.md"),
                       name="99-01-PLAN.md")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("carries 0 `Phase: <number>` lines", result.stderr)
        self.assertNotIn("11-01-PLAN.md", result.stderr)

    def test_current_position_disagreeing_with_the_frontmatter_blocks(self):
        # Half-applied transition: one witness moved, the other did not. The
        # gate cannot know which is fresh, so it blocks and says so.
        result = self.resolve("11-plain", "11",
                               fixture_text("plan-compliant.md"),
                               position="Phase: 99 (Elsewhere) — READY TO EXECUTE")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("disagrees with itself", result.stderr)

    def test_missing_current_position_section_blocks(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-compliant.md"))
            state = root / ".planning" / "STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").split("## Current Position")[0],
                encoding="utf-8")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no `## Current Position` section", result.stderr)

    def test_two_phase_lines_in_current_position_block(self):
        # gsd-core #3807 refuses to write a section carrying more than one
        # `Phase:` line; a reader of one cannot tell which is the fresh one.
        result = self.resolve("11-plain", "11",
                               fixture_text("plan-compliant.md"),
                               position="Phase: {phase} (One)\nPhase: 99 (Two)")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("carries 2 `Phase: <number>` lines", result.stderr)

    def test_bold_phase_label_corroborates(self):
        # gsd-core preserves the author's `**Phase:**` styling when it rewrites
        # the line, so the bold form is a correctly-updated section. Refusing
        # it would block planning on formatting.
        self.expect(self.resolve(
            "11-plain", "11", fixture_text("plan-missing-section.md"),
            position="**Phase:** {phase} (Name) — READY TO EXECUTE"), 1, "11-01-PLAN.md")

    # The frontmatter parse used to take the FIRST of possibly several
    # `current_phase:` matches while the body parse already demanded exactly
    # one. A duplicated
    # frontmatter key let an author -- or a half-applied merge -- steer this
    # blocking gate at whichever phase happened to match first, silently.

    def test_duplicate_current_phase_in_frontmatter_blocks_naming_the_count(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases" / "11-plain").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\ncurrent_phase: 11\n"
                "current_phase: 12\nstatus: planning\n---\n"
                "\n# Project State\n\n## Current Position\n\n"
                "Phase: 11 (Name) — READY TO EXECUTE\n",
                encoding="utf-8",
            )
            write_plan(root / ".planning" / "phases" / "11-plain",
                       fixture_text("plan-compliant.md"), name="11-01-PLAN.md")
            result = self.run_no_arg(root)
        # Exit 2, naming the frontmatter and the count found -- never a
        # compliance verdict on either candidate phase.
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("current_phase", result.stderr)
        self.assertIn("2", result.stderr)
        self.assertNotIn("11-01-PLAN.md", result.stderr)

    def test_three_duplicate_current_phase_fields_names_the_exact_count(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases" / "11-plain").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\ncurrent_phase: 11\n"
                "current_phase: 12\ncurrent_phase: 13\nstatus: planning\n---\n"
                "\n# Project State\n\n## Current Position\n\n"
                "Phase: 11 (Name) — READY TO EXECUTE\n",
                encoding="utf-8",
            )
            write_plan(root / ".planning" / "phases" / "11-plain",
                       fixture_text("plan-compliant.md"), name="11-01-PLAN.md")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("3", result.stderr)

    def test_frontmatter_and_body_ambiguity_reasons_are_distinguishable(self):
        # the two branches' reason
        # strings are kept parallel in shape (both name a count and "need
        # exactly one") but distinguishable in text, so a halt names which
        # parse spoke.
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases" / "11-plain").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\ncurrent_phase: 11\n"
                "current_phase: 12\nstatus: planning\n---\n"
                "\n# Project State\n\n## Current Position\n\n"
                "Phase: 11 (Name) — READY TO EXECUTE\n",
                encoding="utf-8",
            )
            write_plan(root / ".planning" / "phases" / "11-plain",
                       fixture_text("plan-compliant.md"), name="11-01-PLAN.md")
            frontmatter_result = self.run_no_arg(root)
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-compliant.md"),
                               position="Phase: {phase} (One)\nPhase: 99 (Two)")
            body_result = self.run_no_arg(root)
        self.assertEqual(frontmatter_result.returncode, 2, frontmatter_result.stdout)
        self.assertEqual(body_result.returncode, 2, body_result.stdout)
        self.assertNotEqual(frontmatter_result.stderr, body_result.stderr)
        self.assertIn("need exactly one", frontmatter_result.stderr)
        self.assertIn("need exactly one", body_result.stderr)
        self.assertIn("current_phase", frontmatter_result.stderr)
        self.assertIn("`Phase:", body_result.stderr)

    def test_a_symlinked_phase_directory_is_not_matched(self):
        # entry.is_dir() follows symlinks, so a symlinked entry under
        # .planning/phases/ used to resolve to a directory anywhere on the
        # filesystem and have its plan filenames validated -- a traversal
        # out of the tree this gate is scoped to. The real (non-symlink) control for the same resolution loop
        # is test_resolves_the_current_phase_and_reaches_its_verdict above.
        with scratch_dir() as tmp, scratch_dir() as outside:
            root = Path(tmp)
            outside_dir = Path(outside) / "16-outside"
            outside_dir.mkdir()
            write_plan(outside_dir, fixture_text("plan-missing-section.md"),
                       name="11-01-PLAN.md")
            (root / ".planning" / "phases").mkdir(parents=True)
            (root / ".planning" / "phases" / "16-sym").symlink_to(
                outside_dir, target_is_directory=True
            )
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\n"
                "current_phase: 16\nstatus: planning\n---\n"
                "\n# Project State\n\n## Current Position\n\n"
                "Phase: 16 (Name) — READY TO EXECUTE\n"
                "Plan: 1 of 1\nStatus: Ready to execute\n",
                encoding="utf-8",
            )
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("matches 0 directories", result.stderr)
        self.assertNotIn(str(outside_dir), result.stderr)


class TestFixtureYearsAreTemplated(GateCase):
    def test_no_fixture_hardcodes_a_recent_year(self):
        for path in FIXTURES_DIR.glob("*.md"):
            with self.subTest(fixture=path.name):
                text = fixture_text(path.name)
                for stale in ("(2023)", "(2024)"):
                    self.assertNotIn(stale, text)

    def test_copied_fixture_dirs_are_templated_too(self):
        with scratch_dir() as tmp:
            copy_fixture_dir("multiplan", tmp)
            self.assertNotIn("(2024)", (Path(tmp) / "11-01-PLAN.md").read_text())


class TestMultiPlanCoverage(GateCase):
    """Every plan in the directory is checked, not just
    the first readdir match."""

    def test_multiplan_dir_exits_1_even_though_first_plan_compliant(self):
        with scratch_dir() as tmp:
            copy_fixture_dir("multiplan", tmp)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("11-02-PLAN.md", result.stderr)
        self.assertNotIn("11-01-PLAN.md", result.stderr)


class TestDottedFilenames(GateCase):
    def test_dotted_phase_segment_matched(self):
        with scratch_dir() as tmp:
            copy_fixture_dir("dotted", tmp)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestEmptyDirectory(GateCase):
    def test_no_plans_exits_0(self):
        with scratch_dir() as tmp:
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestMisnamedPlans(GateCase):
    """A plan-shaped file PLAN_FILE_RE rejects is reported, never skipped: silence
    would be byte-identical to a compliant phase. A phase with no plans at all
    still exits 0 (nothing to check yet)."""

    def write(self, tmp, name, text=None):
        (Path(tmp) / name).write_text(
            text if text is not None else fixture_text("plan-missing-section.md"),
            encoding="utf-8")

    def test_plan_missing_its_index_is_reported_not_skipped(self):
        # The measured shape: `23-PLAN.md` instead of `23-01-PLAN.md`.
        with scratch_dir() as tmp:
            self.write(tmp, "23-PLAN.md")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("23-PLAN.md", result.stderr)
        self.assertIn("named like a plan but not", result.stderr)

    def test_bare_plan_md_is_reported(self):
        with scratch_dir() as tmp:
            self.write(tmp, "PLAN.md")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("named like a plan but not", result.stderr)

    def test_a_compliant_misnamed_plan_is_still_reported(self):
        # The report is about reachability, not content: a file no reader
        # opens cannot be evidence of anything, however good it looks.
        with scratch_dir() as tmp:
            self.write(tmp, "23-PLAN.md", fixture_text("plan-compliant.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("named like a plan but not", result.stderr)

    def test_sibling_phase_artifacts_are_not_plan_shaped(self):
        # Case-sensitive on purpose: a lowercase `plan` is ordinary English in a
        # filename (`notes-on-the-plan.md`); only `PLAN` is GSD's artifact token.
        with scratch_dir() as tmp:
            for name in ("23-SUMMARY.md", "23-CONTEXT.md", "23-RESEARCH.md",
                         "23-REVIEW-PONYTAIL.md", "23-BEADS-RECALL.md",
                         "23-VALIDATION.md", "README.md", "PLANNING.md",
                         "MYPLAN.md", "notes-on-the-plan.md"):
                self.write(tmp, name, "irrelevant\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_valid_plan_beside_a_misnamed_one_reports_both(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-missing-section.md"),
                       name="23-01-PLAN.md")
            self.write(tmp, "23-PLAN.md", fixture_text("plan-compliant.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("23-01-PLAN.md:1: missing '## Alternatives Considered'",
                      result.stderr)
        self.assertIn("named like a plan but not", result.stderr)
        # Still exactly one remediation line, however many violations.
        self.assertEqual(result.stderr.count("remediation:"), 1)

    def test_lowercase_phase_prefixed_plan_is_reported_as_misnamed(self):
        # `23-01-plan.md` reads as a plan to a human and to a
        # case-insensitive filesystem; silence would be a vacuous pass.
        result = check(fixture_text("plan-compliant.md"), name="23-01-plan.md")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("23-01-plan.md:1: named like a plan but not", result.stderr)

    def test_zero_plan_implicit_phase_exits_0_with_one_stderr_note(self):
        with scratch_dir() as root:
            root = Path(root)
            phase = root / ".planning" / "phases" / "11-empty"
            phase.mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\ncurrent_phase: 11\n---\n"
                "\n## Current Position\n\nPhase: 11 (Name)\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT)], capture_output=True, text=True,
                timeout=15, cwd=str(root),
                env={**os.environ, "TMPDIR": str(PLAN_TMPDIR)},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
        self.assertIn("no plan files", result.stderr)

    def test_zero_plan_explicit_phase_stays_silent(self):
        with scratch_dir() as tmp:
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


class TestBom(GateCase):
    def test_bom_plan_with_heading_on_first_line_passes(self):
        self.gate("\ufeff" + fixture_text("plan-compliant.md"), 0)

    def test_bom_does_not_unmask_heading_inside_frontmatter(self):
        text = (
            "\ufeff---\nphase: 1\n## Alternatives Considered\n---\n\n"
            "# Plan\n"
        )
        self.gate(text, 1, "missing '## Alternatives Considered'")


class TestSectionHeadingIndent(GateCase):
    BODY = (
        f"- **A**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
        f"- **B**: `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
        "Decided by: performance — A.\n"
    )

    def test_up_to_three_leading_spaces_still_a_heading(self):
        for indent in ("", " ", "   "):
            with self.subTest(indent=len(indent)):
                self.gate(f"{indent}## Alternatives Considered\n\n{self.BODY}", 0)

    def test_four_spaces_is_not_a_heading(self):
        self.gate(f"    ## Alternatives Considered\n\n{self.BODY}", 1)


class TestListMarkers(GateCase):
    def test_plus_and_ordered_markers_are_alternatives(self):
        for a, b in (("+", "+"), ("1.", "2."), ("1)", "2)")):
            with self.subTest(marker=a):
                self.gate("## Alternatives Considered\n\n"
                    f"{a} **Redis**: `https://redis.io/docs/` ({TODAY_YEAR}).\n"
                    f"{b} **Memcached**: `https://memcached.org/docs/` ({TODAY_YEAR}).\n\n"
                    "Decided by: performance — Redis.\n", 0)


class TestBorderlessTable(GateCase):
    def test_borderless_table_failure_says_unsupported(self):
        self.gate("## Alternatives Considered\n\n"
            "Rank | Mechanism | Evidence\n--- | --- | ---\n"
            f"1 | **Redis** | `https://redis.io/docs/` ({TODAY_YEAR})\n"
            f"2 | **Memcached** | `https://memcached.org/docs/` ({TODAY_YEAR})\n\n"
            "Decided by: performance — Redis.\n", 1, "borderless tables are not supported")


class TestCommentOpenerInIndentedCode(GateCase):
    def test_comment_opener_in_indented_code_masks_nothing_else(self):
        self.gate("Example input:\n\n    <!-- sample\n\n"
            "## Alternatives Considered\n\n"
            f"- **A**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
            f"- **B**: `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — A.\n", 0)


class TestDeepProjectRoot(GateCase):
    def test_phase_dir_deeper_than_ten_levels_still_finds_root(self):
        with scratch_dir() as root:
            root = Path(root)
            (root / ".planning").mkdir()
            deep = root.joinpath(*[f"d{i}" for i in range(14)])
            deep.mkdir(parents=True)
            write_plan(deep, fixture_text("plan-compliant.md"))
            result = run_check(deep)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestAllViolationsPerPlan(GateCase):
    def test_every_bad_entry_and_missing_decided_by_reported_together(self):
        result = check(
            "## Alternatives Considered\n\n"
            "- **A**: no source.\n"
            "- **B**: no source either.\n"
            f"- **C**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n"
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("alternative 'A'", result.stderr)
        self.assertIn("alternative 'B'", result.stderr)
        self.assertIn("no 'Decided by:' line", result.stderr)
        self.assertEqual(result.stderr.count("remediation:"), 1)

    def test_violations_per_plan_are_capped_at_five(self):
        bullets = "".join(f"- **Opt{i}**: no source.\n" for i in range(9))
        result = check(
            f"## Alternatives Considered\n\n{bullets}\nDecided by: performance — x.\n"
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.count("01-01-PLAN.md:"), 5, result.stderr)


class TestUnreadablePlanPermission(GateCase):
    @unittest.skipIf(os.geteuid() == 0, "root bypasses file modes")
    def test_chmod_000_plan_exits_2_without_traceback(self):
        with scratch_dir() as tmp:
            plan = Path(tmp) / "01-01-PLAN.md"
            write_plan(tmp, fixture_text("plan-compliant.md"))
            plan.chmod(0)
            try:
                result = run_check(tmp)
            finally:
                plan.chmod(0o600)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(str(plan), result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class TestSymlinkedPlan(GateCase):
    def test_symlink_named_like_a_plan_is_a_violation_not_followed(self):
        with scratch_dir() as tmp, scratch_dir() as elsewhere:
            target = Path(elsewhere, "real.md")
            target.write_text(fixture_text("plan-compliant.md"), encoding="utf-8")
            (Path(tmp) / "01-01-PLAN.md").symlink_to(target)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("01-01-PLAN.md:1:", result.stderr)
        self.assertIn("symlink", result.stderr)


class TestEmptyPhaseDir(GateCase):
    """An empty ${PHASE_DIR} must block, not silently pass: `Path("")` is
    `Path(".")`, so without the guard the checker scanned its own cwd and exited 0."""

    def test_empty_arg_rejects_before_reading_cwd_at_all(self):
        # A violating plan in cwd would have produced exit 1 -- a block, but
        # from the wrong directory. The guard sits at the argument, before
        # discovery, so cwd contents cannot reach the verdict either way.
        with scratch_dir() as tmp:
            write_plan(tmp, "# plan with no Alternatives Considered section\n")
            result = run_check("", cwd=tmp)
        self.assertEqual(result.returncode, 2)
        self.assertIn("empty phase_dir argument", result.stderr)
        self.assertNotIn("PLAN.md", result.stderr)


class TestUnreadablePlanFiles(GateCase):
    """Pins the exit codes README's "Failures and recovery" list claims: decode
    failures and other OSErrors (directory named like a plan, permissions,
    dangling link) all map to exit 2 with one clean stderr line, no traceback."""

    def test_non_utf8_plan_names_the_file_and_the_remedy(self):
        # Assert the contract (offending path and a remedy), not the wording.
        with scratch_dir() as tmp:
            plan = Path(tmp) / "01-01-PLAN.md"
            plan.write_bytes(b"\xff\xfe# plan\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(plan), result.stderr)
        self.assertIn("UTF-8", result.stderr)
        self.assertIn("re-save", result.stderr)

    def test_directory_named_like_a_plan_exits_2(self):
        # A directory named NN-NN-PLAN.md maps to the same exit-2 contract: one
        # clean stderr line naming the path, no Traceback, no remediation line.
        with scratch_dir() as tmp:
            plan = Path(tmp) / "01-01-PLAN.md"
            plan.mkdir()
            result = run_check(tmp)
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(plan), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("remediation:", result.stderr)


class TestPathSafety(GateCase):
    def test_dir_with_no_planning_ancestor_exits_2(self):
        result = run_check(Path(SCRIPT.anchor))
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not locate a .planning/ ancestor", result.stderr)

    def test_dotdot_path_matches_its_resolved_form(self):
        # find_project_root() walks up from the RESOLVED phase_dir, so relative_to()
        # can never raise; a `..`-laden argument just relocates the derived root.
        with scratch_dir() as tmp:
            write_plan(tmp, "# plan with no Alternatives Considered section\n")
            direct = run_check(tmp)
            traversed = run_check(Path(tmp) / ".." / Path(tmp).name)
        self.assertEqual(direct.returncode, 1)
        self.assertEqual(traversed.returncode, direct.returncode)
        self.assertIn("missing '## Alternatives Considered' section", traversed.stderr)

    def test_nonexistent_dir_exits_2(self):
        result = run_check("/nonexistent-check-alternatives-fixture-dir")
        self.assertEqual(result.returncode, 2)


class TestFoundationalCitationPairing(GateCase):
    """at-least-one-in-window year, not none-outside-window."""

    def test_foundational_fixture_copy_exits_0(self):
        self.gate(fixture_text("plan-foundational.md"), 0)

    def test_generated_pairing_with_live_year_exits_0(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Kahan summation**: W. Kahan, 1965. Current doc: "
            f"`https://numpy.org/doc/stable/reference/generated/numpy.cumsum.html` ({TODAY_YEAR}).\n"
            f"- **IEEE 754**: IEEE 754-1985. Current vendor doc: "
            f"`https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — standard-library default path.\n"
        )
        self.gate(text, 0)

    def test_canonical_years_only_exits_1(self):
        """Only canonical out-of-window years (1965/1985) must fail, pinning the
        at-least-one-in-window rule against an "any out-of-window year" regression."""
        text = (
            "## Alternatives Considered\n\n"
            "- **Kahan summation**: Kahan 1965, `Communications of the ACM`, no in-window year.\n"
            "- **IEEE 754**: IEEE 754-1985 `IEEE Std 754`, no in-window year.\n\n"
            "Decided by: performance — standard-library default path.\n"
        )
        self.gate(text, 1, "1965", "no citation dated within the last")


class TestRemediationOutput(GateCase):
    """the --force remediation line."""

    def test_remediation_names_phase_number_from_basename(self):
        tmp = tempfile.mkdtemp(prefix="07-", dir=PLAN_TMPDIR)
        try:
            write_plan(tmp, fixture_text("plan-missing-section.md"))
            result = run_check(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--force", result.stderr)
        self.assertIn("/gsd-plan-phase 07 --force", result.stderr)

    def test_remediation_falls_back_to_placeholder_with_no_leading_number(self):
        tmp = tempfile.mkdtemp(prefix="nodigits-", dir=PLAN_TMPDIR)
        try:
            write_plan(tmp, fixture_text("plan-missing-section.md"))
            result = run_check(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("/gsd-plan-phase <phase> --force", result.stderr)


class TestDiagnosticBounding(GateCase):
    """Every diagnostic is bounded, and a truncated span carries an explicit
    elision marker so a reader can tell truncation from a short value."""

    def test_found_years_list_truncated_to_five_distinct_values(self):
        # Seven distinct out-of-window years cited on one entry: only the
        # first five (sorted, so the message is stable regardless of the
        # order the years were written in) are named, with an explicit
        # count of how many more were elided.
        years = [1900, 1901, 1902, 1903, 1904, 1905, 1906]
        years_text = " ".join(str(y) for y in years)
        text = (
            "## Alternatives Considered\n\n"
            f"- **Ancient option**: cited many stale years. `https://numpy.org/doc` ({years_text}).\n"
            f"- **Current option**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — historical record.\n"
        )
        result = check(text)
        self.assertEqual(result.returncode, 1, result.stderr)
        for y in years[:5]:
            self.assertIn(str(y), result.stderr)
        for y in years[5:]:
            self.assertNotIn(str(y), result.stderr)
        self.assertIn("...[+2 more]", result.stderr)

    def test_pathological_multiline_entry_span_years_still_truncated(self):
        # Years spread over continuation lines make the entry span multi-line;
        # the message must stay bounded regardless.
        stale_years = "\n  ".join(
            " ".join(str(1910 + row * 5 + col) for col in range(5)) for row in range(6)
        )
        text = (
            "## Alternatives Considered\n\n"
            "- **First option**: many stale years spread across lines.\n"
            f"  {stale_years}\n"
            "  `https://numpy.org/doc`\n"
            f"- **Second option**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — historical record.\n"
        )
        self.gate(text, 1, "1910", "...[+", lacks=("1939",))

    def test_long_boundary_heading_is_truncated_with_a_marker(self):
        long_heading = "Timing table " + ("x" * 100)
        self.gate(split_across_boundary(f"{long_heading}\n" + "=" * 20), 1, "...[truncated]", long_heading[:20], lacks=(long_heading,))

    def test_long_alternative_name_is_truncated_with_a_marker(self):
        long_name = ("Uncited mechanism with an extremely long descriptive name " * 3).strip()[:150]
        text = (
            "## Alternatives Considered\n\n"
            f"- **{long_name}**: no citation here at all.\n"
            f"- **Current option**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — a real reason.\n"
        )
        self.gate(text, 1, f"alternative '{long_name[:80]}", "...[truncated]", lacks=(long_name,))

    def test_short_messages_carry_no_elision_marker(self):
        self.gate(fixture_text("plan-uncited.md"), 1, lacks=("...[truncated]", "...[+",))


class TestViolationLineShape(GateCase):
    """Each violation reports as `<plan_path>:<line>: <reason>`, and a run emits
    exactly one remediation line however many violations there are."""

    def test_missing_section_names_line_one(self):
        result = check(fixture_text("plan-missing-section.md"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(
            result.stderr,
            r"01-01-PLAN\.md:1: missing '## Alternatives Considered' section",
        )

    def test_first_entrys_violation_names_its_own_line(self):
        # Heading on line 1, blank line 2, first entry on line 3.
        text = (
            "## Alternatives Considered\n\n"
            "- **Option A**: no citation at all here.\n"
            f"- **Option B**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — a real reason.\n"
        )
        result = check(text)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stderr, r"01-01-PLAN\.md:3: alternative 'Option A'")

    def test_second_entrys_violation_names_a_later_line(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: cited current. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            "- **Option B**: no citation at all here.\n\n"
            "Decided by: performance — a real reason.\n"
        )
        result = check(text)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stderr, r"01-01-PLAN\.md:4: alternative 'Option B'")

    def test_no_decided_by_names_the_heading_line(self):
        compliant = fixture_text("plan-compliant.md")
        stripped_lines = [
            line for line in compliant.splitlines() if "Decided by:" not in line
        ]
        expected_line = next(
            i for i, line in enumerate(stripped_lines, 1)
            if line.startswith("## Alternatives Considered")
        )
        self.gate("\n".join(stripped_lines) + "\n", 1, f"01-01-PLAN.md:{expected_line}: no 'Decided by:' line")

    def test_misnamed_plan_names_a_line(self):
        with scratch_dir() as tmp:
            (Path(tmp) / "23-PLAN.md").write_text(
                fixture_text("plan-missing-section.md"), encoding="utf-8")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stderr, r"23-PLAN\.md:1: named like a plan but not")

    def test_no_stderr_line_exceeds_two_hundred_characters(self):
        # A pathologically deep phase directory path, so the composed
        # `<path>:<line>: <reason>` line would otherwise exceed the bound
        # regardless of how short the reason itself is.
        with scratch_dir() as tmp:
            deep = Path(tmp, "a" * 60, "b" * 60, "c" * 60)
            deep.mkdir(parents=True)
            write_plan(deep, fixture_text("plan-missing-section.md"))
            result = run_check(deep)
        self.assertEqual(result.returncode, 1, result.stderr)
        for line in result.stderr.splitlines():
            self.assertLessEqual(len(line), 200, line)

    def test_long_path_is_elided_not_the_reason(self):
        with scratch_dir() as tmp:
            deep = Path(tmp, "a" * 60, "b" * 60, "c" * 60)
            deep.mkdir(parents=True)
            write_plan(deep, fixture_text("plan-missing-section.md"))
            result = run_check(deep)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "01-01-PLAN.md:1: missing '## Alternatives Considered' section",
            result.stderr,
        )
        for line in result.stderr.splitlines():
            self.assertLessEqual(len(line), 200, line)

    def test_remediation_line_appears_exactly_once_with_line_numbers(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-missing-section.md"), name="01-01-PLAN.md")
            write_plan(tmp, fixture_text("plan-uncited.md"), name="01-02-PLAN.md")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.count("remediation:"), 1)
        self.assertRegex(result.stderr, r"01-01-PLAN\.md:\d+:")
        self.assertRegex(result.stderr, r"01-02-PLAN\.md:\d+:")


# Compact entry fragments shared by the gate-hardening cases below.
_A = f"- **Householder QR**: stable. https://numpy.org/doc/stable/ ({TODAY_YEAR}).\n"
_B = f"- **Pivoted LU**: fast. https://docs.scipy.org/doc/ ({TODAY_YEAR}).\n"
_D = "Decided by: performance\n"
_H = "## Alternatives Considered\n"


def _entry(name, cite=f"https://numpy.org/doc/ ({TODAY_YEAR})."):
    return f"- {name}: x. {cite}\n"


class TestEntryNameIdentity(GateCase):
    ONE = "fewer than 2 named alternatives (found 1)"

    def test_lookalike_names_are_one_alternative(self):
        for a, b in (
            ("**QR:**", "**QR**:"),
            ("**QR**", "**ＱＲ**"),
            ("**QR**", "**Q​R**"),
            ("**Straße**", "**STRASSE**"),
            ("**QR**", "__QR__"),
        ):
            with self.subTest(a=a, b=b):
                self.gate(f"{_H}\n{_entry(a)}{_entry(b)}\n{_D}", 1, self.ONE)

    def test_a_name_with_no_letter_or_digit_is_not_an_alternative(self):
        for name in ("**​**", "**::**", "**-**"):
            with self.subTest(name=name):
                self.gate(f"{_H}\n{_A}{_entry(name)}\n{_D}", 1, self.ONE)

    def test_bold_must_be_strong_emphasis(self):
        for name in ("**QR **", "** QR**"):
            with self.subTest(name=name):
                self.gate(f"{_H}\n{_A}{_entry(name)}\n{_D}", 1, self.ONE)


class TestYearOutsideCitationText(GateCase):
    def test_digits_inside_a_url_or_doc_ref_are_not_a_date(self):
        for cite in (
            "https://github.com/numpy/numpy/issues/2024",
            f"https://example.net/v/{TODAY_YEAR}/x".replace("example.net", "numpy.org"),
            f"`numpy-{TODAY_YEAR}.pdf`",
        ):
            with self.subTest(cite=cite):
                self.gate(f"{_H}\n{_A}- **Other**: see {cite}\n\n{_D}", 1,
                          "alternative 'Other'", "no citation date")


class TestEntryEndsAtUnindentedParagraph(GateCase):
    def test_a_trailing_paragraph_does_not_lend_its_citation(self):
        self.gate(f"{_H}\n{_A}- **Other**: no citation.\n\n"
                  f"Background reading: https://numpy.org/doc/ ({TODAY_YEAR}).\n\n{_D}",
                  1, "alternative 'Other'", "missing URL or doc-ref citation")

    def test_an_indented_continuation_paragraph_still_belongs_to_the_entry(self):
        self.gate(f"{_H}\n{_A}- **Other**: cited below.\n\n"
                  f"  https://numpy.org/doc/ ({TODAY_YEAR}).\n\n{_D}", 0)


class TestExemptionIsExact(GateCase):
    def test_exact_exemption_line_passes(self):
        for line in ("N/A - no mechanism choice", "N/A — no mechanism choice.", "n/a-no mechanism choice  "):
            with self.subTest(line=line):
                self.gate(f"{_H}\n{line}\n", 0)

    def test_extra_text_after_the_phrase_is_not_exempt(self):
        self.gate(f"{_H}\nN/A - no mechanism choice review needed. Picked FFTW\n", 1)

    def test_text_before_the_phrase_is_not_exempt(self):
        self.gate(f"{_H}\nN/A - we made one; no mechanism choice review needed.\n", 1)

    def test_more_content_in_the_section_is_not_exempt(self):
        self.gate(f"{_H}\nN/A - no mechanism choice\n\nWe picked FFTW over MKL.\n", 1)
        self.gate(f"{_H}\nN/A - no mechanism choice\nPicked FFTW\n", 1)


class TestTabIndentation(GateCase):
    def test_tab_indented_section_heading_is_code_not_a_heading(self):
        self.gate(f"\t{_H}\n{_A}{_B}\n{_D}", 1, "missing")

    def test_tab_indented_bullets_are_code_not_entries(self):
        self.gate(f"{_H}\n{_A}\t{_B}\n{_D}", 1, "fewer than 2 named alternatives (found 1)")

    def test_tab_indented_block_after_a_paragraph_is_masked(self):
        self.gate(f"Example:\n\n\t<!-- sample\n\n{_H}\n{_A}{_B}\n{_D}", 0)
        self.gate(f"Example:\n\n\t{_H}\n\t{_A}\t{_B}", 1, "missing")

    def test_space_tab_mix_counts_to_the_next_stop(self):
        self.gate(f"{_H}\n{_A}  \t{_B}\n{_D}", 1, "fewer than 2 named alternatives (found 1)")


class TestFenceInsideListItem(GateCase):
    def test_a_deeply_indented_fence_in_a_list_item_is_masked(self):
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                self.gate(f"{_H}\n{_A}- **Other**: no citation.\n\n"
                          f"    {fence}\n    https://numpy.org/doc/ ({TODAY_YEAR})\n    {fence}\n\n{_D}",
                          1, "alternative 'Other'", "missing URL or doc-ref citation")


for _name, (_boundary, _ends) in {
    "setext_h2_ends_the_section": ("Later Section\n---", True),
    "setext_h2_short_underline_ends_the_section": ("Later Section\n--", True),
    "empty_atx_h2_ends_the_section": ("##", True),
    "empty_atx_h1_ends_the_section": ("#", True),
    "list_item_before_a_rule_does_not_end_the_section": ("- item\n---", False),
}.items():
    setattr(TestSectionBoundary, f"test_{_name}", _boundary_test(_boundary, _ends))


class TestIndentedH3(GateCase):
    MARKER = "   ### Internal design alternatives"

    def test_an_indented_internal_heading_ends_the_entry_before_it(self):
        self.gate(f"{_H}\n{_A}- **Other**: no citation.\n{self.MARKER}\n\n"
                  f"- **Local**: https://numpy.org/doc/ ({TODAY_YEAR}).\n\n{_D}",
                  1, "alternative 'Other'", "missing URL or doc-ref citation")

    def test_an_indented_internal_heading_scopes_the_entries_after_it(self):
        self.gate(f"{_H}\n{_A}{_B}\n{self.MARKER}\n\n- **Local**: no citation.\n\n{_D}", 0)


class TestCommentOpenerForms(GateCase):
    def test_an_escaped_opener_is_literal_text(self):
        self.gate(f"Write \\<!-- to start a comment.\n\n{_H}\n{_A}{_B}\n{_D}", 0)

    def test_an_unterminated_opener_mid_paragraph_does_not_cross_a_blank_line(self):
        self.gate(f"Text <!-- never closed\n\n{_H}\n{_A}{_B}\n{_D}", 0)

    def test_a_terminated_opener_mid_paragraph_still_hides_its_span(self):
        self.gate(f"{_H}\n{_A}{_B}- **Other**: x. <!-- https://numpy.org/doc/ ({TODAY_YEAR}) -->\n\n{_D}",
                  1, "alternative 'Other'", "missing URL or doc-ref citation")

    def test_a_line_start_unterminated_opener_still_masks_to_eof(self):
        self.gate(f"<!-- never closed\n\n{_H}\n{_A}{_B}\n{_D}", 1, "missing")

    def test_many_openers_in_code_spans_scan_in_linear_time(self):
        import time
        plan = "## Approach\n\n" + "`<!--` " * 40000 + f"\n\n{_H}\n{_A}{_B}\n{_D}"
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            start = time.monotonic()
            result = run_check(tmp)
            elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 2)

    def test_many_unterminated_inline_openers_scan_in_linear_time(self):
        import time
        plan = "## Approach\n\n" + "x <!-- " * 40000 + f"\n\n{_H}\n{_A}{_B}\n{_D}"
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            start = time.monotonic()
            result = run_check(tmp)
            elapsed = time.monotonic() - start
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 2)


class TestFrontmatterClosedAtEof(GateCase):
    def test_a_section_inside_frontmatter_closed_at_eof_is_masked(self):
        for close in ("---", "..."):
            with self.subTest(close=close):
                self.gate(f"---\nphase: 1\n{_H}\n{_A}{_B}\n{_D}{close}", 1, "missing")


if __name__ == "__main__":
    unittest.main()
