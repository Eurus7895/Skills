# Check — whether the claims hold

The third component. Validates the analysis, gates the fragments, then verifies every claim against the
graph and the source.

**Checkpoint P3 closes this component** — but only after you have written the three files in
[`three-analyses.md`](three-analyses.md), because P3 is a question about those. `document` will not run
until it is decided.

```bash
python3 scripts/pipeline.py check
```

- **Read** the assembler's exit status **and its warnings**, which do not affect it, then `findings.jsonl`
  grouped by code rather than one at a time.
- **Decide** which units to re-dispatch, and act on each finding group per the table in
  [`schemas.md`](schemas.md#the-verification-loop).

The gate catches the two ways parallel fan-out fails behind a finished-looking document. **A dispatched task
returned nothing** — the assembler fails on a unit with no row; without it, three missing modules read as a
complete document. **The descriptions are near-identical** — the `constant` warning fires when a field's
values barely vary, which usually means the tasks answered the prompt instead of reading the source. A clean
exit with a constant `role` field is a failed extraction wearing a passing grade.

Two rules hold whatever the finding: **revise only the affected fragment** — re-analysing the repository
because one claim failed wastes the budget and reintroduces claims that already passed — and **stop after two
attempts** on anything unresolved, leaving it `candidate` for the limitations page.
