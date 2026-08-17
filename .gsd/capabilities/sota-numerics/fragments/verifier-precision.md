Numerical-stability and efficiency review for verification is advisory only — this capability declares no gate at execute:wave:post, so everything below is a finding, not a blocker.
Confirm the mechanism the plan justified in its Alternatives Considered section is the mechanism that actually shipped — flag a divergence even if the code works.
Flag silent scope or precision reductions: a formula quietly simplified, an edge case quietly dropped, a stable algorithm quietly swapped for an unstable shortcut.
Flag hardcoded constants standing in for a value that should be derived from first principles or measured, and flag superlative performance or overhead claims ("zero overhead", "negligible error") that no benchmark or measurement in the diff backs up.
None of these findings block; they are handed to the orchestrator as verifier output for the human or a later gate to weigh.
