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
    / ".gsd" / "capabilities" / "sota-numerics" / "scripts" / "check-alternatives.py"
)
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

TODAY_YEAR = datetime.date.today().year
PLAN_TMPDIR = None


def setUpModule():
    global PLAN_TMPDIR
    PLAN_TMPDIR = Path(tempfile.mkdtemp(prefix="sota-numerics-tests-"))
    (PLAN_TMPDIR / ".planning").mkdir()


def tearDownModule():
    (PLAN_TMPDIR / ".planning").rmdir()
    if any(PLAN_TMPDIR.iterdir()):
        raise RuntimeError(f"TMPDIR must finish empty: {PLAN_TMPDIR}")
    PLAN_TMPDIR.rmdir()


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


def write_plan(dir_path, text, name="01-01-PLAN.md"):
    """Write `text` under `dir_path` as a filename the discovery regex
    matches. The standalone tests/fixtures/plan-*.md files hold section
    content only -- they are copied under a matching name here rather than
    discovered by their own bare filenames."""
    Path(dir_path, name).write_text(text, encoding="utf-8")


def fixture_text(name):
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


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
    """One cited alternative inside the section; a second cited alternative
    and the `Decided by:` line placed after `boundary`.

    The plan holds two compliant alternatives in total but only one within
    the section, so it is compliant exactly when `boundary` fails to end
    the section and donates its entry to it."""
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


class TestMixedAlternatives(unittest.TestCase):
    def test_mixed_bullets_exits_0(self):
        with scratch_dir() as tmp:
            write_plan(tmp, DOCUMENTED_MIXED_BODY)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)

    def test_internal_entries_do_not_count(self):
        text = f"""## Alternatives Considered

- **Only mechanism**: cited mechanism evidence. `authoritative-doc` ({TODAY_YEAR}).

### Internal design alternatives

- **Local layout A**: project-local reasoning.
- **Local layout B**: project-local reasoning.

{SHAPE_DECISION}
"""
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Deficient mechanism'", result.stderr)
        self.assertIn("missing URL or doc-ref citation", result.stderr)
        self.assertIn("no citation date", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Resumed mechanism'", result.stderr)
        self.assertIn("missing URL or doc-ref citation", result.stderr)
        self.assertIn("no citation date", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Resumed mechanism'", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Resumed mechanism'", result.stderr)

    def test_mixed_section_missing_decided_by_fails(self):
        text = DOCUMENTED_MIXED_BODY.replace(f"\n{SHAPE_DECISION}\n", "\n")
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 'Decided by:' line naming a ranked criterion", result.stderr)


class TestMixedCompatibility(unittest.TestCase):
    def test_no_marker_bullets_and_table_exit_0(self):
        for text, _ in (bullet_plan(), table_plan()):
            with self.subTest(shape=text.splitlines()[2][:1]):
                with scratch_dir() as tmp:
                    write_plan(tmp, text)
                    result = run_check(tmp)
                self.assertEqual(result.returncode, 0)

    def test_uncited_mechanism_still_fails(self):
        text = f"""## Alternatives Considered

- **Mechanism A**: cited. `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited. `authoritative-doc-B` ({TODAY_YEAR}).
- **Uncited mechanism**: its evidence is deliberately absent.

### Internal design alternatives

- **Local layout**: project-local reasoning.

{SHAPE_DECISION}
"""
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Uncited mechanism'", result.stderr)
        self.assertIn("missing URL or doc-ref citation", result.stderr)
        self.assertIn("no citation date", result.stderr)

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
                with scratch_dir() as tmp:
                    write_plan(tmp, text)
                    result = run_check(tmp)
                self.assertEqual(result.returncode, 1)
                self.assertIn("alternative 'Local choice'", result.stderr)

    def test_exact_marker_allows_trailing_horizontal_whitespace(self):
        text = DOCUMENTED_MIXED_BODY.replace(
            "### Internal design alternatives",
            "### Internal design alternatives \t",
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_marker_bearing_exemption_exits_0(self):
        text = """## Alternatives Considered

N/A — no mechanism choice

### Internal design alternatives

- **Local layout**: project-local reasoning.
"""
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_one_bullet_selects_valid_table(self):
        table, _ = table_plan()
        text = table.replace(
            "## Alternatives Considered\n\n",
            "## Alternatives Considered\n\n- **Ignored bullet**: no evidence.\n\n",
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_bullet_and_table_do_not_combine(self):
        text = f"""## Alternatives Considered

- **Bullet mechanism**: cited. `authoritative-doc-A` ({TODAY_YEAR}).

| Rank | Mechanism | Evidence |
| ---: | --- | --- |
| 1 | **Table mechanism** | `authoritative-doc-B` ({TODAY_YEAR}) |

{SHAPE_DECISION}
"""
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)

    def test_unrelated_h3_without_marker_preserves_evidence_span(self):
        text = f"""## Alternatives Considered

- **Mechanism A**: evidence continues below.

### Other notes

Continuation with `authoritative-doc-A` ({TODAY_YEAR}).
- **Mechanism B**: cited. `authoritative-doc-B` ({TODAY_YEAR}).

{SHAPE_DECISION}
"""
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestDocumentedSyntax(unittest.TestCase):
    def test_readme_and_planner_name_exact_mixed_contract(self):
        control, _ = bullet_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, control)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

        root = Path(__file__).resolve().parent.parent
        marker = "### Internal design alternatives"
        contract = (
            "Internal entries need no external citation or date, do not count toward "
            "the two mechanism alternatives, and cannot lend evidence to a mechanism entry."
        )
        paths = (
            root / "README.md",
            root / ".gsd/capabilities/sota-numerics/fragments/planner-sota.md",
        )
        missing = [
            str(path)
            for path in paths
            if marker not in path.read_text(encoding="utf-8")
            or contract not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])

        readme_text = (root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("Each parsed entry must contain:", readme_text)

        checker_text = (
            root / ".gsd/capabilities/sota-numerics/scripts/check-alternatives.py"
        ).read_text(encoding="utf-8")
        normalized_checker_text = " ".join(checker_text.split())
        self.assertIn(
            "at least two named mechanism alternatives", normalized_checker_text
        )
        self.assertIn(
            "Internal entries are excluded from the count and evidence validation.",
            normalized_checker_text,
        )

    def test_documented_mixed_body_exits_0(self):
        with scratch_dir() as tmp:
            write_plan(tmp, DOCUMENTED_MIXED_BODY)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestSectionPresence(unittest.TestCase):
    """The section heading itself."""

    def test_missing_section_exits_1(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-missing-section.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Alternatives Considered", result.stderr)

    def test_suffixed_heading_accepts_identical_bullet_body(self):
        exact, exact_entries = bullet_plan()
        suffixed, suffixed_entries = bullet_plan("## Alternatives Considered (REQ-10)")
        self.assertEqual(exact.split("\n\n", 1)[1], suffixed.split("\n\n", 1)[1])
        self.assertEqual(exact_entries, suffixed_entries)
        with scratch_dir() as tmp:
            write_plan(tmp, suffixed)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_concatenated_heading_remains_missing(self):
        text, _ = bullet_plan("## Alternatives ConsideredFoo")
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)


class TestSectionBoundary(unittest.TestCase):
    """Which heading forms end the section body.

    Donation is the dangerous direction: an entry written under a *later*
    heading, counted as if it sat in this section, turns a one-alternative
    plan into a passing two-alternative one. H1 and H2 end the section,
    indented up to the three leading spaces CommonMark allows on an ATX
    heading. H3 and deeper stay inside: `### Internal design alternatives`
    is a documented in-section construct, so widening the boundary scan to
    `#{1,6}` would truncate the body at that H3 and drop the `Decided by:`
    line following it.

    Each donation case asserts the *reason*, not merely the exit code. A
    donated entry that happens to be uncited also exits 1 -- but names the
    donated bullet, which leaves the boundary defect live behind a red
    exit status.
    """

    def assert_does_not_donate(self, boundary):
        with scratch_dir() as tmp:
            write_plan(tmp, split_across_boundary(boundary))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)
        self.assertNotIn(SHAPE_ENTRIES[1][0], result.stderr)

    def assert_stays_inside(self, boundary):
        with scratch_dir() as tmp:
            write_plan(tmp, split_across_boundary(boundary))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_h2_ends_the_section(self):
        self.assert_does_not_donate("## Later Section")

    def test_h1_ends_the_section(self):
        self.assert_does_not_donate("# Later Section")

    def test_indented_h2_ends_the_section(self):
        self.assert_does_not_donate("   ## Later Section")

    def test_indented_h1_ends_the_section(self):
        self.assert_does_not_donate("   # Later Section")

    def test_setext_h1_ends_the_section(self):
        # A setext H1 is an H1; only its spelling differs. The ATX fix left this
        # member of the same class live, and it was found by enumerating the
        # boundary axis rather than by another report.
        self.assert_does_not_donate("Later Section\n=============")

    def test_thematic_break_does_not_end_the_section(self):
        # `---` is a setext H2 underline AND a thematic break AND a frontmatter
        # fence. Treating it as a boundary would false-BLOCK a plan that puts a
        # horizontal rule between its alternatives, so `-` is never a boundary.
        self.assert_stays_inside("---")

    def test_bare_setext_rule_does_not_end_the_section(self):
        # `===` with nothing above it is a horizontal rule, not a heading:
        # CommonMark makes an underline a heading only under a paragraph. The
        # first version of the setext boundary fired on the run alone, cut the
        # section at the rule, and reported "fewer than 2 named alternatives
        # (found 1)" on a plan that had two -- a false block whose diagnostic
        # named neither the rule nor the truncation, on a gate that halts
        # planning.
        self.assert_stays_inside("===")

    def test_a_truncating_heading_is_named_in_the_count_message(self):
        with scratch_dir() as tmp:
            write_plan(tmp, split_across_boundary("Timing table\n============"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)
        self.assertIn("the section ended at the heading 'Timing table'",
                      result.stderr)

    def test_a_truncating_heading_is_named_rather_than_a_missing_field(self):
        # Same exit code, opposite instruction to the author. The
        # `Decided by:` line is not absent -- it is three lines down, below a
        # heading nobody noticed writing. Reported as absence, the message
        # sends the author to fix a line that is already correct, which is how
        # a correct block still wastes the round.
        entries = "\n".join(
            f"- **{name}**: {prose} {citation} ({year})."
            for name, prose, citation, year in SHAPE_ENTRIES)
        with scratch_dir() as tmp:
            write_plan(tmp, f"## Alternatives Considered\n\n{entries}\n\n"
                            f"Timing table\n============\n\n{SHAPE_DECISION}\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 'Decided by:' line", result.stderr)
        self.assertIn("the section ended at the heading 'Timing table'",
                      result.stderr)

    def test_a_boundary_is_not_blamed_when_the_field_is_simply_absent(self):
        # The note exists to stop a misdiagnosis. Firing it unconditionally
        # would be the same misdiagnosis pointing the other way: sending an
        # author to move a heading when what they owe is a line they never
        # wrote.
        entries = "\n".join(
            f"- **{name}**: {prose} {citation} ({year})."
            for name, prose, citation, year in SHAPE_ENTRIES)
        with scratch_dir() as tmp:
            write_plan(tmp, f"## Alternatives Considered\n\n{entries}\n\n"
                            "## Approach\n\nNothing relevant here.\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 'Decided by:' line", result.stderr)
        self.assertNotIn("the section ended at the heading", result.stderr)

    def test_h3_does_not_end_the_section(self):
        self.assert_stays_inside("### Notes")


class TestSupportedEntryShapes(unittest.TestCase):
    def test_table_accepts_same_semantics_as_bullets(self):
        bullets, bullet_entries = bullet_plan()
        table, table_entries = table_plan()
        self.assertEqual(bullet_entries, table_entries)
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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("alternative 'Uncited option'", result.stderr)
        self.assertIn("missing URL or doc-ref citation", result.stderr)
        self.assertIn("no citation date", result.stderr)

    def test_present_section_without_supported_entries_has_distinct_message(self):
        text = f"## Alternatives Considered\n\nplain text only\n\n{SHAPE_DECISION}\n"
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("section found but no alternatives parsed", result.stderr)
        self.assertIn("bullets", result.stderr)
        self.assertIn("table", result.stderr)

    def test_one_table_row_excludes_bold_header_and_separator(self):
        only_entry = SHAPE_ENTRIES[:1]
        text, _ = table_plan(entries=only_entry)
        text = text.replace(
            "| Rank | Mechanism | Evidence |",
            f"| Rank | **Not an alternative** | `{TODAY_YEAR}` |",
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)

    def test_pipe_rows_without_separator_are_not_a_markdown_table(self):
        rows = "\n".join(
            f"| **{name}**: {prose} {citation} ({year}). |"
            for name, prose, citation, year in SHAPE_ENTRIES
        )
        text = f"## Alternatives Considered\n\n{rows}\n\n{SHAPE_DECISION}\n"
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("section found but no alternatives parsed", result.stderr)

    def test_bullet_control_remains_accepted(self):
        text, _ = bullet_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestBulletIndentationBound(unittest.TestCase):
    """`BULLET_RE` and the framed table-row scan bound their leading
    indentation to CommonMark's zero-to-three-space top-level range (D-03,
    REVIEW-CRITICAL-FINAL P1-1(b)). Unbounded, either scan let a
    four-space-indented sub-entry -- nested under an organizational
    top-level bullet that names no mechanism of its own -- satisfy the
    "at least two named alternatives" requirement, on a plan that named
    exactly zero alternatives at the level the requirement is about.
    `mask_indented_code_blocks` (D-02, plan 24-01) does not close this: it
    deliberately never masks a line inside an open list item, because an
    ordinary continuation paragraph under a bullet must stay readable.
    """

    def test_entries_stated_only_as_four_space_sub_bullets_are_not_top_level(self):
        text = (
            "## Alternatives Considered\n\n"
            "- Candidates evaluated:\n"
            f"    - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **Pivoted LU**: baseline. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("section found but no alternatives parsed", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("section found but no alternatives parsed", result.stderr)

    def test_zero_to_three_space_indented_bullets_still_count(self):
        # CommonMark's own top-level range: a bullet indented up to three
        # spaces is unaffected by the bound and must keep passing.
        text = (
            "## Alternatives Considered\n\n"
            f"   - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"   - **Pivoted LU**: baseline. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "Decided by: performance -- QR is the stable first choice.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_compliant_top_level_entry_still_draws_citation_from_a_sub_bullet(self):
        # D-05's negative case: a compliant top-level entry that carries an
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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestCitationAndDate(unittest.TestCase):
    """Citation and recency-date requirements."""

    def test_uncited_undated_exits_1_names_both_issues(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-uncited.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("citation", result.stderr)
        self.assertIn("date", result.stderr)

    def test_example_com_placeholder_url_exits_1(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: a placeholder source. `https://example.com/docs` ({TODAY_YEAR}).\n"
            f"- **Option B**: a real source. `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — Option A is faster.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)

    def test_stale_only_year_exits_1(self):
        stale_year = TODAY_YEAR - 10
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: cited once, a decade stale. `https://numpy.org/doc/stable/` ({stale_year}).\n"
            f"- **Option B**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — Option A was the original pick.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(stale_year), result.stderr)


class TestDecidedBy(unittest.TestCase):
    """The ranked-criterion line."""

    def test_missing_decided_by_exits_1(self):
        compliant = fixture_text("plan-compliant.md")
        stripped_lines = [
            line for line in compliant.splitlines() if "Decided by:" not in line
        ]
        with scratch_dir() as tmp:
            write_plan(tmp, "\n".join(stripped_lines) + "\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Decided by", result.stderr)


class TestMinimumCount(unittest.TestCase):
    def test_one_alternative_exits_1(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Only Option**: `https://numpy.org/doc/stable/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — only one considered.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2", result.stderr)

    def test_two_alternatives_exits_0(self):
        text = COMPLIANT_ENTRY_TEMPLATE.format(year_a=TODAY_YEAR, year_b=TODAY_YEAR - 1)
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestExemption(unittest.TestCase):
    def test_exempt_plan_exits_0(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-exempt.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestFencedRegions(unittest.TestCase):
    """A `## Alternatives Considered` inside a code fence is illustration, not
    a decision record (gsd-beads-358).

    `extract_section_body` took the FIRST occurrence anywhere in the file, so a
    plan whose only occurrence sat inside a ```markdown fence -- README ships
    four such examples for authors to copy -- satisfied the blocking gate on
    the example's text. Both directions are pinned: a fence-only heading must
    NOT count, and a fence must not hide a real heading that follows it.
    """

    def test_fenced_only_heading_does_not_satisfy_the_gate(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-fenced-only.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_fenced_example_before_a_real_section_still_passes(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-fenced-then-real.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fenced_entries_do_not_count_toward_the_minimum(self):
        # Same root cause one level down: bullets inside a fence were counted
        # as mechanism alternatives, so a single real entry plus a fenced
        # example reached the two-alternative minimum.
        plan = (
            "## Alternatives Considered\n\n"
            f"- **Real mechanism**: prose. `real-doc` ({TODAY_YEAR}).\n\n"
            "```markdown\n"
            f"- **Example mechanism**: prose. `example-doc` ({TODAY_YEAR}).\n"
            "```\n\n"
            "Decided by: performance.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fewer than 2 named alternatives (found 1)", result.stderr)

    def test_tilde_fence_is_skipped_too(self):
        plan = (
            "## Approach\n\n~~~markdown\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n~~~\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_unterminated_fence_fails_closed(self):
        # An unterminated fence blanks to EOF. The section then reads as
        # missing, which blocks -- the safe direction for a blocking gate.
        plan = (
            "## Approach\n\n```markdown\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)

    def test_inline_backticks_are_not_mistaken_for_a_fence(self):
        # Doc-ref citations are backtick-delimited; only a line of three or
        # more opens a fence, so ordinary citations must survive untouched.
        text, _ = bullet_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    # FENCE_LINE_RE's three conditions -- the `^` anchor, the three-marker
    # minimum, and the backtick info-string rule -- each transcribe a CommonMark
    # requirement, and each was unpinned: all three could be removed and the
    # whole suite stayed green (ponytail-2 F-Py-4). Every one of them fails in
    # the same direction, which is why nothing caught them: a false opener
    # blanks to EOF, so the section reads as truncated and a compliant plan is
    # BLOCKED. A gate that halts planning on correct input is not the safe
    # error. One case each, and each asserts the reason.

    def test_a_backtick_run_mid_line_does_not_open_a_fence(self):
        # CommonMark: a fence opener starts its line. Without the anchor, prose
        # that ends in a marker opens a fence nothing closes.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "The marker is written ```\n\n" + SHAPE_DECISION)
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_two_marker_run_does_not_open_a_fence(self):
        # CommonMark: three or more. Strikethrough at the start of a line is
        # two tildes, and the info-string rule below does not cover tildes, so
        # the count is the only thing keeping this from opening a fence.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "~~An earlier approach~~ is not considered.\n\n"
                            + SHAPE_DECISION)
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_backtick_info_string_does_not_open_a_fence(self):
        # CommonMark: a backtick fence's info string may not contain a
        # backtick, which is what makes ```code``` an inline code span on its
        # own line rather than an opener.
        text, _ = bullet_plan()
        plan = text.replace(SHAPE_DECISION,
                            "```code``` is how this plan writes it.\n\n"
                            + SHAPE_DECISION)
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestIndentedCodeBlocks(unittest.TestCase):
    """A four-space indented code block is CommonMark's other invisible-on-
    the-rendered-page construct (D-02, REVIEW-CRITICAL-FINAL P1-1a). Fences
    are already masked by `TestFencedRegions` above; this class pins the
    indented form, reproducing the exact shape that review confirmed passes
    at exit 0 on the shipped script.
    """

    def test_indented_alternatives_are_not_counted_as_prose(self):
        # REVIEW-CRITICAL-FINAL P1-1a's reproduction: a real, column-0
        # heading is found correctly, but its entries and Decided-by line
        # sit four spaces in. CommonMark renders that as inert code, not
        # list items -- BULLET_RE's unbounded indentation (D-03, out of
        # scope here) still counts them today, so this exits 0 before the
        # fix and must exit 1 after it.
        plan = (
            "## Alternatives Considered\n\n"
            "Example of the required shape:\n\n"
            f"    - **Householder QR**: stable. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **Pivoted LU**: baseline. `https://docs.scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "    Decided by: performance -- QR is the stable first choice.\n\n"
            "That is all; this plan makes no real comparison.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "section found but no alternatives parsed", result.stderr
        )

    def test_a_wholly_indented_heading_and_body_is_still_a_missing_section(self):
        # Not a masking case: SECTION_HEADING_RE is anchored `^##` at
        # column 0, so a heading indented four spaces was already
        # invisible to it before this task's fix. Pinned so a future
        # change to that anchor cannot silently start crediting it.
        plan = (
            "Some intro paragraph, not a list.\n\n"
            "    ## Alternatives Considered\n\n"
            f"    - **NumPy**: mature. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            f"    - **SciPy**: alternative. `https://scipy.org/doc` ({TODAY_YEAR}).\n\n"
            "    Decided by: performance.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_a_bullet_continuation_paragraph_is_not_treated_as_code(self):
        # D-05's negative case: an ordinary continuation paragraph under a
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
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unrelated_indented_code_block_does_not_affect_a_compliant_section(self):
        text, _ = bullet_plan()
        plan = (
            "Setup note.\n\n"
            "    $ pip install numpy scipy\n"
            "    $ python solve.py\n\n"
        ) + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestFrontmatterMasking(unittest.TestCase):
    """Leading YAML frontmatter is CommonMark-invisible on the rendered
    page the same way a fence or an indented code block is, but neither
    mask covers it: a `## Alternatives Considered` heading declared only
    inside the frontmatter block was still credited by the section scan
    (D-01, REVIEW-AGY-FINAL blocking item 2).
    """

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
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

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
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_document_without_frontmatter_is_unaffected(self):
        text, _ = bullet_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unclosed_leading_dashes_line_is_not_treated_as_frontmatter(self):
        # First line is exactly `---`, but nothing that follows closes it
        # with a line that is exactly `---` or `...` -- this is a
        # thematic break (or a setext H2 underline for an empty
        # preceding paragraph), not a frontmatter opener, and must be
        # scanned exactly as it was before this task's change.
        text, _ = bullet_plan()
        plan = "---\n\n" + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestHtmlComments(unittest.TestCase):
    """An `## Alternatives Considered` inside an HTML comment renders nothing,
    so it records nothing (gsd-beads-a54).

    The same defect as the fenced one in the other syntax CommonMark keeps off
    the page, and the more reachable of the two: the author who drops two
    candidates late comments them out "to keep the history" rather than
    deleting them. Every case asserts the REASON, because two of the three
    already exited non-zero before the fix -- for the wrong reason, having
    counted commented text as a decision record.
    """

    def test_commented_only_heading_does_not_satisfy_the_gate(self):
        # Was exit 1 "fewer than 2 named alternatives (found 1)": the gate read
        # the commented heading AND counted a commented bullet under it.
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-commented-only.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_commented_entries_do_not_count_toward_the_minimum(self):
        # The fail-open the release notes already claimed was closed: a real
        # heading whose only entries were commented out exited 0.
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-commented-entries.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no alternatives parsed", result.stderr)

    def test_commented_example_before_a_real_section_still_passes(self):
        # Was exit 1 "found 1": the scan stopped at the commented heading and
        # never reached the genuine section below it.
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-commented-then-real.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unterminated_comment_fails_closed(self):
        plan = (
            "## Approach\n\n<!--\n## Alternatives Considered\n\n"
            "N/A — no mechanism choice is made by this plan.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_a_comment_opener_inside_a_fence_is_code_not_a_comment(self):
        # Whichever construct opens first owns the span, as in CommonMark:
        # a lone `<!--` quoted inside a fence must not swallow the real
        # section that follows the fence.
        text, _ = bullet_plan()
        plan = "## Approach\n\n```markdown\n<!--\n```\n\n" + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_fence_opener_inside_a_comment_does_not_open_a_fence(self):
        # The mirror image: a ``` inside a comment must not leave a fence open
        # across the real section and blank it to EOF.
        text, _ = bullet_plan()
        plan = "## Approach\n\n<!--\n```\n-->\n\n" + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_backticked_comment_opener_does_not_open_a_comment(self):
        # A `<!--` written inside a single-backtick inline code span renders
        # as literal text on the page -- CommonMark shows the backticks and
        # the arrows, not a comment -- so it must not start a masked span
        # (gsd-beads-25vc.21.1, P2-1).
        text, _ = bullet_plan()
        plan = "We discuss `<!--` markers here.\n\n" + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unrelated_code_span_does_not_protect_a_real_opener_on_the_same_line(
        self,
    ):
        # The backtick-span check must protect only a `<!--` that is itself
        # inside a span. An unrelated span earlier on the line must not act
        # as a blanket exemption for a real, unprotected opener later on the
        # same line -- that would turn the fix into a bypass.
        text, _ = bullet_plan()
        plan = "Uses `numpy`. <!--\n" + text + "-->\n"
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_an_unterminated_backtick_before_an_opener_still_masks_to_eof(self):
        # An unterminated backtick is not a code span -- CommonMark requires
        # a matching closing run of the same length on the same line here --
        # so the fail-closed residual from mask_fenced_regions' own
        # docstring still applies: the opener is unprotected and masks to
        # EOF.
        text, _ = bullet_plan()
        plan = "`a <!--\n" + text
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing '## Alternatives Considered' section", result.stderr)

    def test_a_protected_backtick_candidate_does_not_disturb_fence_precedence(self):
        # A skipped (backtick-protected) comment candidate earlier in the
        # text must not disturb the "whichever construct opens first wins"
        # rule between the fence path and the real comment path.
        text, _ = bullet_plan()
        plan = (
            "We discuss `<!--` markers here.\n\n"
            "```markdown\n<!--\n```\n\n" + text
        )
        with scratch_dir() as tmp:
            write_plan(tmp, plan)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestCurrentPhaseResolution(unittest.TestCase):
    """With no argument, the checker resolves its phase from the project's own
    STATE.md (gsd-beads-cqt).

    The gate command is constant precisely so that no directory name is ever
    spliced into the `sh -c` string gsd-core builds. That moves phase identity
    onto this path, which must therefore fail CLOSED whenever it is unsure.
    """

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

    def run_no_arg(self, cwd):
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, timeout=15, cwd=str(cwd),
            env={**os.environ, "TMPDIR": str(PLAN_TMPDIR)},
        )

    def test_resolves_the_current_phase_and_reaches_its_verdict(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-missing-section.md"))
            result = self.run_no_arg(root)
        # Exit 1, naming the plan: proof it read THAT directory, not cwd.
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("11-01-PLAN.md", result.stderr)

    def test_apostrophe_in_the_phase_directory_name_is_accepted(self):
        # The behaviour this fix exists to restore. Under the previous
        # `'${PHASE_DIR}'` splice this name aborted the gate with exit 2
        # before the checker ran at all.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-o'brien", "11",
                               fixture_text("plan-compliant.md"))
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_padded_current_phase_matches_an_unpadded_directory(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "6-six", "06", fixture_text("plan-compliant.md"))
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_current_phase_blocks(self):
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\nstatus: planning\n---\n", encoding="utf-8")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("current_phase", result.stderr)

    def test_state_md_without_frontmatter_blocks(self):
        # Without the guard the resolver dereferences a None match and dies on
        # a traceback -- still non-zero, but exit 1 means "these plans are bad"
        # and nothing here was ever read. Only the shell suite touched this
        # path, and it does not reach this shape.
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases" / "11-plain").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "# Project State\n\ncurrent_phase: 11\n", encoding="utf-8")
            write_plan(root / ".planning" / "phases" / "11-plain",
                       fixture_text("plan-compliant.md"), name="11-01-PLAN.md")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no YAML frontmatter block", result.stderr)

    def test_current_phase_in_prose_does_not_redirect_the_gate(self):
        # Phase identity must come from the frontmatter, never from document
        # content. Scanning the whole file let a `current_phase:` line in prose
        # point the blocking gate at a DIFFERENT, compliant phase while the
        # real one went uninspected -- a bypass in the very path that replaced
        # the ${PHASE_DIR} splice.
        #
        # The prose value and the `## Current Position` section agree with each
        # other and disagree with the frontmatter, which carries no
        # `current_phase` at all. That shape matters: a decoy the corroboration
        # would reject anyway proves nothing about where the field is read
        # from, and the earlier version of this case became exactly that when
        # the corroboration landed. Here the only thing standing between the
        # gate and phase 99 is the frontmatter-only scan.
        with scratch_dir() as tmp:
            root = Path(tmp)
            (root / ".planning" / "phases" / "11-real").mkdir(parents=True)
            (root / ".planning" / "phases" / "99-decoy").mkdir(parents=True)
            (root / ".planning" / "STATE.md").write_text(
                "---\ngsd_state_version: 1.0\nstatus: planning\n---\n"
                "\nprose that merely mentions:\n\ncurrent_phase: 99\n"
                "\n## Current Position\n\nPhase: 99 (Decoy) — READY TO EXECUTE\n",
                encoding="utf-8")
            write_plan(root / ".planning" / "phases" / "11-real",
                       fixture_text("plan-missing-section.md"), name="11-01-PLAN.md")
            write_plan(root / ".planning" / "phases" / "99-decoy",
                       fixture_text("plan-compliant.md"), name="99-01-PLAN.md")
            result = self.run_no_arg(root)
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
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "12", fixture_text("plan-compliant.md"))
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected exactly 1", result.stderr)

    def test_dotted_current_phase_does_not_match_a_longer_sibling(self):
        # `10.1` must not resolve to `10.10`: the fractional part is compared
        # as text, so a truncated match cannot silently validate another phase.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "10.10-ten-ten", "10.1",
                               fixture_text("plan-compliant.md"))
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected exactly 1", result.stderr)

    # Two witnesses, not one (gsd-beads-76k). gsd-core's step 13b writes the
    # `## Current Position` `Phase:` line and re-derives `current_phase` from
    # it, so it updates both or neither. On three measured section shapes it
    # updates neither and still exits 0, and the surviving stale
    # `current_phase` then pointed this gate at the PREVIOUS phase: it opened
    # an old compliant directory, found nothing wrong, and printed a clean
    # zero-byte pass while the phase actually planned went uninspected. Every
    # case below asserts the refusal REASON, because the exit code alone
    # cannot tell a real verdict from a gate that checked the wrong thing.

    def test_stale_frontmatter_under_a_non_canonical_position_label_blocks(self):
        # The reproduction. `## Current Position` spelled `Current Phase:` is a
        # section `plannedPhaseCore` cannot rewrite -- measured, it exits 0
        # updating only `Last Activity Description` -- so both witnesses still
        # name phase 11 after phase 99 was planned. Phase 11 is compliant and
        # phase 99 is not, so a gate that trusts `current_phase` alone passes.
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
        # No verdict was reached on either phase -- least of all a pass on the
        # stale one, which is what the exit 0 used to mean.
        self.assertNotIn("11-01-PLAN.md", result.stderr)

    def test_current_position_disagreeing_with_the_frontmatter_blocks(self):
        # Half-applied transition: one witness moved, the other did not. The
        # gate cannot know which is fresh, so it blocks and says so.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-compliant.md"),
                               position="Phase: 99 (Elsewhere) — READY TO EXECUTE")
            result = self.run_no_arg(root)
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
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-compliant.md"),
                               position="Phase: {phase} (One)\nPhase: 99 (Two)")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("carries 2 `Phase: <number>` lines", result.stderr)

    def test_bold_phase_label_corroborates(self):
        # gsd-core preserves the author's `**Phase:**` styling when it rewrites
        # the line, so the bold form is a correctly-updated section. Refusing
        # it would block planning on formatting.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11",
                               fixture_text("plan-missing-section.md"),
                               position="**Phase:** {phase} (Name) — READY TO EXECUTE")
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("11-01-PLAN.md", result.stderr)

    # The frontmatter parse used to take the FIRST of possibly several
    # `current_phase:` matches while the body parse already demanded exactly
    # one (D-04, REVIEW-CRITICAL-FINAL shape 2, gsd-beads-25vc.7). A duplicated
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

    def test_a_single_frontmatter_current_phase_still_resolves(self):
        # Regression pin: the exactly-one case, unaffected by the fix.
        with scratch_dir() as tmp:
            root = Path(tmp)
            self.build_project(root, "11-plain", "11", fixture_text("plan-compliant.md"))
            result = self.run_no_arg(root)
        self.assertEqual(result.returncode, 0, result.stdout)

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
        # T-24-12 / D-04 internal alternative: the two branches' reason
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


class TestMultiPlanCoverage(unittest.TestCase):
    """Every plan in the directory is checked, not just
    the first readdir match."""

    def test_multiplan_dir_exits_1_even_though_first_plan_compliant(self):
        with scratch_dir() as tmp:
            shutil.copytree(FIXTURES_DIR / "multiplan", tmp, dirs_exist_ok=True)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("11-02-PLAN.md", result.stderr)
        self.assertNotIn("11-01-PLAN.md", result.stderr)


class TestDottedFilenames(unittest.TestCase):
    def test_dotted_phase_segment_matched(self):
        with scratch_dir() as tmp:
            shutil.copytree(FIXTURES_DIR / "dotted", tmp, dirs_exist_ok=True)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestEmptyDirectory(unittest.TestCase):
    def test_no_plans_exits_0(self):
        with scratch_dir() as tmp:
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestMisnamedPlans(unittest.TestCase):
    """A plan-shaped file PLAN_FILE_RE rejects is reported, never skipped
    (gsd-beads-8d5).

    Discovery answered two different questions with the same silence: "this
    phase has no plans" and "this phase has a plan I refused to read". The
    second is the dangerous one -- a phase directory holding only `23-PLAN.md`
    exited 0 with no output, byte-identical to a compliant phase, while the
    plan inside it had no `## Alternatives Considered` section at all.

    The first still exits 0. That is a phase with nothing to check, and
    blocking it would make the gate fire on every phase before its plans are
    written.
    """

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
        # The bound in the other direction, and it is not decoration: the
        # first pattern tried here carried re.IGNORECASE and blocked the phase
        # on `notes-on-the-plan.md`. `PLAN` in capitals is GSD's artifact
        # token; a lowercase `plan` is ordinary English in a filename.
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


class TestEmptyPhaseDir(unittest.TestCase):
    """An empty ${PHASE_DIR} must block, not silently pass.

    gsd-core interpolates an omitted --phase-dir to the empty string
    (check-command-router.cts:1240 -> gate-predicate-evaluator.cts:45), so the
    gate can run `check-alternatives.py ""`. Python reads `Path("")` as
    `Path(".")`, which is a directory, so before the guard the checker scanned
    its own cwd -- the project root, holding no NN-NN-PLAN.md children -- and
    exited 0. A blocking, fail-closed gate passed without reading one plan.
    """

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


class TestUnreadablePlanFiles(unittest.TestCase):
    """Pins the exit codes README's "Failures and recovery" list claims.

    Both paths reach main() from validate_plan()'s path.read_text(): a decode
    failure is a UnicodeDecodeError, which subclasses ValueError and so is
    caught and mapped to 2, while every other OSError escapes uncaught and
    Python exits 1. The two look alike in the source and behave differently.
    """

    def test_non_utf8_plan_names_the_file_and_the_remedy(self):
        # The bare codec message named a byte offset and no path, so a phase
        # holding twenty plans gave the author no way to tell which one to fix.
        # Assert the contract -- offending path, and a remedy -- not the
        # wording, so the message can be reworded without breaking this.
        with scratch_dir() as tmp:
            plan = Path(tmp) / "01-01-PLAN.md"
            plan.write_bytes(b"\xff\xfe# plan\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(plan), result.stderr)
        self.assertIn("UTF-8", result.stderr)
        self.assertIn("re-save", result.stderr)

    def test_directory_named_like_a_plan_exits_1(self):
        # Discovery matches on the name, so a directory named NN-NN-PLAN.md is
        # opened as a file: IsADirectoryError escapes and the gate blocks
        # without a remediation line.
        with scratch_dir() as tmp:
            (Path(tmp) / "01-01-PLAN.md").mkdir()
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("remediation:", result.stderr)


class TestPathSafety(unittest.TestCase):
    def test_dir_with_no_planning_ancestor_exits_2(self):
        # Named for what it actually exercises. It never tested containment:
        # find_project_root() raises here, before any containment check could
        # run. See test_dotdot_path_matches_its_resolved_form below.
        result = run_check(Path(SCRIPT.anchor))
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not locate a .planning/ ancestor", result.stderr)

    def test_dotdot_path_matches_its_resolved_form(self):
        # The deleted confined() was unreachable, so removing it changed
        # nothing observable. find_project_root() walks up from the RESOLVED
        # phase_dir, so the root it derives is always an ancestor of that path
        # and relative_to() could never raise -- a `..`-laden argument simply
        # relocates the derived root with it. Pinned so a future containment
        # check has to state a root the caller supplies independently.
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


class TestFoundationalCitationPairing(unittest.TestCase):
    """REVIEWS finding 2: at-least-one-in-window year, not none-outside-window."""

    def test_foundational_fixture_copy_exits_0(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-foundational.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_generated_pairing_with_live_year_exits_0(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Kahan summation**: W. Kahan, 1965. Current doc: "
            f"`https://numpy.org/doc/stable/reference/generated/numpy.cumsum.html` ({TODAY_YEAR}).\n"
            f"- **IEEE 754**: IEEE 754-1985. Current vendor doc: "
            f"`https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — standard-library default path.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)

    def test_canonical_years_only_exits_1(self):
        """Mirror-image negative: strip the in-window year, leaving only the
        1965/1985 canonical years -- must fail, pinning the at-least-one-rule
        against a future 'reject any out-of-window year' regression. The
        script reports the first offending entry (Kahan/1965) -- validation
        is fail-fast per plan, matching the single-violation-per-plan shape
        every other test in this suite already relies on."""
        text = (
            "## Alternatives Considered\n\n"
            "- **Kahan summation**: `Kahan 1965 Communications of the ACM`, no in-window year.\n"
            "- **IEEE 754**: `IEEE 754-1985`, no in-window year.\n\n"
            "Decided by: performance — standard-library default path.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("1965", result.stderr)
        self.assertIn("no citation dated within the last", result.stderr)


class TestRemediationOutput(unittest.TestCase):
    """REVIEWS findings 1/3: the --force remediation line."""

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

    def test_remediation_line_appears_exactly_once_across_two_violations(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-missing-section.md"), name="01-01-PLAN.md")
            write_plan(tmp, fixture_text("plan-uncited.md"), name="01-02-PLAN.md")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count("remediation:"), 1)


class TestDiagnosticBounding(unittest.TestCase):
    """D-07/D-08: every diagnostic the gate emits is bounded, and a
    truncated span carries an explicit elision marker so a reader can tell
    truncation from a value that was already short (T-24-13, T-24-14).

    `check-alternatives.py:537-540` joined every four-digit year found in
    one entry's whole span into the message with no cap; probed against the
    shipped script (REVIEW-PROSE-TOKENS.md P1), a plan whose first bullet
    carried 2,000 out-of-window years produced 12,280 chars / 8,099 tokens
    on a single stderr line. The heading echoed by `below_the_boundary` had
    the same defect: an arbitrary, unbounded document line.
    """

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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        for y in years[:5]:
            self.assertIn(str(y), result.stderr)
        for y in years[5:]:
            self.assertNotIn(str(y), result.stderr)
        self.assertIn("...[+2 more]", result.stderr)

    def test_pathological_multiline_entry_span_years_still_truncated(self):
        # Reproduces the reported defect's actual shape: years spread across
        # continuation lines under one bullet, so the entry's span -- from
        # its own bullet to the next one -- is multi-line, not a single
        # citation line. The fix must bound the message regardless of how
        # the span grew, not merely how it looks in the common case.
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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("1910", result.stderr)
        self.assertIn("...[+", result.stderr)
        self.assertNotIn("1939", result.stderr)

    def test_long_boundary_heading_is_truncated_with_a_marker(self):
        long_heading = "Timing table " + ("x" * 100)
        with scratch_dir() as tmp:
            write_plan(tmp, split_across_boundary(f"{long_heading}\n" + "=" * 20))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn(long_heading, result.stderr)
        self.assertIn("...[truncated]", result.stderr)
        # A meaningful prefix of the heading survives. Exactly how much
        # depends on the line-level backstop (D-07), which may cut further
        # into an already-bounded span when the rest of the message -- the
        # fixed "fewer than 2 ... the section ended at ..." prose plus the
        # plan path -- is itself long; the two bounds are independent, and
        # the coarser one (200 chars, whole line) wins when they conflict.
        self.assertIn(long_heading[:20], result.stderr)

    def test_long_alternative_name_is_truncated_with_a_marker(self):
        long_name = ("Uncited mechanism with an extremely long descriptive name " * 3).strip()[:150]
        text = (
            "## Alternatives Considered\n\n"
            f"- **{long_name}**: no citation here at all.\n"
            f"- **Current option**: cited current. `https://docs.scipy.org/doc/scipy/` ({TODAY_YEAR}).\n\n"
            "Decided by: performance — a real reason.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"alternative '{long_name[:80]}", result.stderr)
        self.assertNotIn(long_name, result.stderr)
        self.assertIn("...[truncated]", result.stderr)

    def test_short_messages_carry_no_elision_marker(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-uncited.md"))
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("...[truncated]", result.stderr)
        self.assertNotIn("...[+", result.stderr)


class TestViolationLineShape(unittest.TestCase):
    """D-08: each violation reports as `<plan_path>:<line>: <reason>` -- the
    shape the capability already documents for its other usage error (Phase
    23 D-13 precedent) -- and a run still emits exactly one remediation
    line no matter how many violations there are or how long any one
    diagnostic line would otherwise be (T-24-15)."""

    def test_missing_section_names_line_one(self):
        with scratch_dir() as tmp:
            write_plan(tmp, fixture_text("plan-missing-section.md"))
            result = run_check(tmp)
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
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stderr, r"01-01-PLAN\.md:3: alternative 'Option A'")

    def test_second_entrys_violation_names_a_later_line(self):
        text = (
            "## Alternatives Considered\n\n"
            f"- **Option A**: cited current. `https://numpy.org/doc` ({TODAY_YEAR}).\n"
            "- **Option B**: no citation at all here.\n\n"
            "Decided by: performance — a real reason.\n"
        )
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
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
        with scratch_dir() as tmp:
            write_plan(tmp, "\n".join(stripped_lines) + "\n")
            result = run_check(tmp)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            f"01-01-PLAN.md:{expected_line}: no 'Decided by:' line", result.stderr
        )

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
        # regardless of how short the reason itself is (D-07).
        with scratch_dir() as tmp:
            deep = Path(tmp, "a" * 60, "b" * 60, "c" * 60)
            deep.mkdir(parents=True)
            write_plan(deep, fixture_text("plan-missing-section.md"))
            result = run_check(deep)
        self.assertEqual(result.returncode, 1, result.stderr)
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


if __name__ == "__main__":
    unittest.main()
