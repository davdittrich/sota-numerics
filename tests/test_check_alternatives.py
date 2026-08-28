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
PLAN_TMPDIR = Path("/home/dd/projects/gsd-beads/.scratch/issue-1-plan")


def setUpModule():
    configured = Path(os.environ["TMPDIR"]).resolve()
    if configured != PLAN_TMPDIR or not configured.is_dir():
        raise RuntimeError(f"TMPDIR must be the prepared plan scratchpad: {PLAN_TMPDIR}")
    if any(configured.iterdir()):
        raise RuntimeError(f"TMPDIR must start empty: {PLAN_TMPDIR}")


def tearDownModule():
    if any(PLAN_TMPDIR.iterdir()):
        raise RuntimeError(f"TMPDIR must finish empty: {PLAN_TMPDIR}")


def scratch_dir():
    return tempfile.TemporaryDirectory(dir=PLAN_TMPDIR)


def run_check(phase_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(phase_dir)],
        capture_output=True,
        text=True,
        timeout=15,
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


class TestSectionPresence(unittest.TestCase):
    """D-01/D-02: the section heading itself."""

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


class TestSupportedEntryShapes(unittest.TestCase):
    def test_table_accepts_same_semantics_as_bullets(self):
        bullets, bullet_entries = bullet_plan()
        table, table_entries = table_plan()
        self.assertEqual(bullet_entries, table_entries)
        self.assertEqual(SHAPE_DECISION, SHAPE_DECISION)
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

    def test_bullet_control_remains_accepted(self):
        text, _ = bullet_plan()
        with scratch_dir() as tmp:
            write_plan(tmp, text)
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestCitationAndDate(unittest.TestCase):
    """D-06/D-07: citation and recency-date requirements."""

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
    """D-09: the ranked-criterion line."""

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


class TestMultiPlanCoverage(unittest.TestCase):
    """RESEARCH Pattern 3: every plan in the directory is checked, not just
    the first readdir match."""

    def test_multiplan_dir_exits_1_even_though_first_plan_compliant(self):
        result = run_check(FIXTURES_DIR / "multiplan")
        self.assertEqual(result.returncode, 1)
        self.assertIn("11-02-PLAN.md", result.stderr)
        self.assertNotIn("11-01-PLAN.md", result.stderr)


class TestDottedFilenames(unittest.TestCase):
    def test_dotted_phase_segment_matched(self):
        result = run_check(FIXTURES_DIR / "dotted")
        self.assertEqual(result.returncode, 0)


class TestEmptyDirectory(unittest.TestCase):
    def test_no_plans_exits_0(self):
        with scratch_dir() as tmp:
            result = run_check(tmp)
        self.assertEqual(result.returncode, 0)


class TestPathSafety(unittest.TestCase):
    def test_phase_dir_outside_project_root_exits_2(self):
        with scratch_dir() as tmp:
            # The temporary allocation remains inside the approved root; its
            # ancestor outside the project has no `.planning/` marker.
            result = run_check(Path(tmp).parents[3])
        self.assertEqual(result.returncode, 2)

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


if __name__ == "__main__":
    unittest.main()
