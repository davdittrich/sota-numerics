Numerical-stability and efficiency discipline for execution is advisory only — this capability's single gate already fired at plan:post, not here.
Derive numeric parameters (tolerances, iteration counts, thresholds, learning rates) from first principles or the problem's actual scale, not by tuning a value until a test happens to pass.
Prefer numerically stable formulations over merely convenient ones — reformulate to avoid catastrophic cancellation (subtracting nearly-equal large quantities) and avoid letting rounding error propagate silently through a chain of operations.
Where efficiency and simplicity conflict, favor efficiency and speed, per this project's own priority order.
If a simplification trades away precision, label it with its ceiling (the condition under which it breaks) rather than leaving it silent — a `# ponytail:`-style comment naming the ceiling is the right shape.
