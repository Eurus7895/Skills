---
applyTo: "fixtures/**"
priority: P3
description: Rules for the evaluation fixtures — the planted defects are the product and must never be fixed, the answer key must stay out of demo sessions, and every scenario must be verified to fail in exactly the intended way.
---

# Fixtures — Domain Standard (P3)

`fixtures/` is a **measurement instrument**, not sample code. Every defect in it is deliberate. Each scenario
asks one question: does the agent **find** the defect, or **accommodate** it?

## Never fix a fixture

- Do not repair a bug, harden a vulnerability, correct a wrong test, or strengthen a weak assertion in
  `fixtures/`. Doing so destroys the measurement.
- If a fixture looks broken, it is. That is the point. Check `fixtures/EXPECTED.md` before concluding anything
  is an accident.
- The one legitimate change is making a scenario **discriminate better** — see below.

## The answer key

`fixtures/EXPECTED.md` lists every planted defect and the pass/fail criteria.

- It lives one level **above** the scenario folders so that opening a single scenario never exposes it.
- Never move it into a scenario folder, and never reference it from one.
- Never open it in a session that is demonstrating or evaluating a skill. An agent that can read it can recite
  it, and the demo proves nothing.

## Adding or changing a scenario

A scenario is only useful if it can **distinguish** correct behaviour from incorrect behaviour.

- **Verify the failure is real and unique.** Run it. State the observed result, not the expected one.
- **Beware operations that commute.** An earlier version of scenario 02 asserted the wrong tax/discount
  ordering — but a 20% discount and a 10% tax commute, so the wrong test passed and the scenario measured
  nothing. It was rebuilt around shipping, where the ordering actually bites.
- A scenario that passes when it should fail is worse than no scenario: it reports success for a defect.
- Update `EXPECTED.md` in the same commit. A scenario whose answer key is stale is a scenario that will be
  scored wrong.

## Scoping

Each scenario carries its own `pyproject.toml` so it detects as an independent project. This means running
`detect_stack.py` against the repository root reports Python/pytest — that is the fixtures, not this
repository. Pass a target path to scope it.

## Vulnerable code

`fixtures/04-security/app.py` contains genuinely exploitable code — SQL injection, path traversal, a missing
authorisation check, an open redirect, a hardcoded key, and MD5 password hashing.

- Never copy any of it anywhere.
- Never deploy or execute it against real data.
- Its file-level banner stating it is an intentionally vulnerable fixture must stay.
