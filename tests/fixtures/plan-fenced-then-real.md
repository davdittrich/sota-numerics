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
Fixture plan: a fenced example heading PRECEDES the plan's real, compliant
section. Skipping fenced regions must not stop at the first fence and miss the
genuine section that follows -- the gate must pass this plan.
</objective>

## Approach

Quoting README's shape so a reader can see it before the real record:

```markdown
## Alternatives Considered

- **Some mechanism**: prose. `some-doc` (2024).

Decided by: performance.
```

That block is illustration. The record itself follows.

## Alternatives Considered

- **NumPy `numpy.linalg.solve`**: mature, BLAS/LAPACK-backed dense linear
  solver. `https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html`
  (2024).
- **SciPy `scipy.linalg.lu_solve`**: exposes the LU factorization directly for
  reuse across right-hand sides.
  `https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lu_solve.html`
  (2023).

Decided by: performance — the single-solve path avoids a manual factorization.
