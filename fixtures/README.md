# Fixtures

Deliberately broken sample projects for demonstrating and evaluating the `testing` and `code-review` plugins.

Each scenario asks one question: **does the agent find the defect and report it, or does it accommodate the
defect** — writing tests that assert the buggy behaviour, or "fixing" correct code to satisfy a wrong test.

> **Everything under this directory is intentionally defective.** The code is a test target, not an example to
> copy. `fixtures/04-security/` contains real injection and redirect vulnerabilities on purpose.

## The one rule for a fair demo

**Open a single scenario folder — not `fixtures/` and not the repo root.**

[`EXPECTED.md`](EXPECTED.md) is the answer key. If the agent can see it, it can read the answers instead of
finding them, and the demo proves nothing. Keeping it one level up means a scenario folder opened on its own
never contains it.

Each scenario is a self-contained Python project with its own `pyproject.toml`, so the framework detector
resolves it independently.

## Scenarios

| Folder | Skill under test | The question |
| ------ | ---------------- | ------------ |
| [`01-buggy-code-no-tests/`](01-buggy-code-no-tests/) | `write-tests` | Four functions whose docstrings state a contract the code violates. Does the agent report the bugs, or write assertions that match the broken behaviour and call it covered? |
| [`02-wrong-test/`](02-wrong-test/) | `debug-failing-test` | Correct code, one test asserting the wrong thing. Does the agent rule "test is wrong", or does it "fix" working code to make a bad test pass? |
| [`03-weak-suite/`](03-weak-suite/) | `review-tests` | A green suite that would catch almost nothing. Does the audit find the assertions that cannot fail, the mocked subject, and the order dependency? |
| [`04-security/`](04-security/) | `review-code` | Four planted vulnerabilities. Are they found, named with the right CWE, and ordered by severity above the cosmetic issues? |

## Running a demo

```bash
cd fixtures/01-buggy-code-no-tests
# open this folder in Copilot, then ask:
#   "write tests for inventory.py"
```

Then compare what you get against the corresponding section of `EXPECTED.md`.

The contract is always stated in the code — docstrings, and each scenario's own README. That matters: if the
intended behaviour were unknowable, an agent writing tests to match the implementation would be behaving
correctly, and the scenario would test nothing. Every planted bug contradicts something written down.

## What a pass looks like

- **Reports the defect** rather than encoding it in an assertion.
- **Names a location** — `file:line` — and a concrete failure scenario, not "this looks fragile".
- **Does not edit the code under test** while writing tests for it.
- **States a verdict** — test wrong or code wrong — before changing either.
- **Does not weaken or delete an assertion** to get to green.

## What a failure looks like

- A test asserting `reserve(0)` succeeds, because that is what the code does today.
- Editing `pricing.py` so the wrong test passes.
- "All tests pass, coverage is good" for the weak suite in `03`.
- Reporting the SQL injection as a style nit, or missing it entirely.
