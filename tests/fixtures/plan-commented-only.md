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
Fixture plan: the ONLY `## Alternatives Considered` heading in the file sits
inside an HTML comment, so the rendered plan shows no section at all. The gate
must treat this as a missing section, exactly as it treats a fenced one.
</objective>

## Approach

The author drafted a section, thought better of it, and commented the draft out
instead of deleting it. Nothing outside the comment claims anything:

<!--
## Alternatives Considered

- **Some mechanism**: prose. `some-doc` (2024).

Decided by: performance.
-->

The paragraph above is prose about a draft, not a decision record.
