---
phase: 99-fixture-phase
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - fixture.py
autonomous: true
requirements: []
user_setup: []
---

<objective>
Fixture plan: the heading is real and rendered, but every alternative under it
is commented out "to keep the history". The rendered plan records no comparison,
so the gate must count zero entries rather than read the comment's text.
</objective>

## Approach

The realistic shape: two candidates were dropped late and the author preserved
them as a comment rather than deleting them.

## Alternatives Considered

<!--
- **NumPy `numpy.linalg.solve`**: dense LAPACK-backed solver.
  `https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html`
  (2024).
- **SciPy `scipy.linalg.lu_solve`**: reusable LU factorization.
  `https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lu_solve.html`
  (2023).
-->

Decided by: performance.
