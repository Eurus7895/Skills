---
name: debug-failing-test
description: Diagnose one failing or intermittently failing test and decide whether the test or the production code is wrong before fixing either. Use whenever a specific test fails, errors, or breaks in CI — "this test is failing", "why is this red", "CI is broken", "the test passes locally but not in CI", "this test fails intermittently", "this assertion started failing after my change", or a pasted stack trace or assertion diff. Also use when the user is tempted to delete or skip a failing test. For auditing a whole suite's quality rather than diagnosing one failure, use review-tests instead.
---

# Debug a failing test

## Overview

A failing test is a claim that behavior and expectation disagree. The job is to find out **which one is wrong**
before changing anything. Getting this backwards is how real bugs get committed: the fastest way to green is to
weaken the assertion, and that is usually the wrong fix.

The deliverable is an explicit verdict — *the test is wrong* or *the code is wrong* — the evidence for it, the
fix applied to the correct side, and a passing run.

## When to use this skill

- Any failing or erroring test, locally or in CI.
- A pasted stack trace, assertion diff, or CI log.
- "Passes locally, fails in CI" and other environment-dependent failures.
- Intermittent failures — a flaky test is still a failing test.
- The user proposes skipping or deleting a test to get green.

## When not to use this skill

- **Code has no tests and needs some** — use `write-tests`.
- **The suite passes but you doubt it is meaningful**, or flakiness is suite-wide rather
  than one test — use `review-tests`. This skill diagnoses a specific failure; that one
  audits quality across the suite.
- **The build or a compile step is broken**, not a test — that is ordinary debugging; do it directly.

## Steps

1. **Reproduce.** Detect the runner via `references/framework-detection.md` and
   `python3 scripts/detect_stack.py <repo-root>`, then run the single failing test. If it does not fail, do not
   proceed on assumption — find the condition that makes it fail (ordering, environment, seed, parallelism)
   before going further.

2. **Read the actual failure.** The assertion diff, the exception type, the line. Not the test name, not a
   guess from the summary. Quote it in your report.

3. **Isolate.** Run the test alone. Compare against running it with the full suite.
   - Fails alone and together → deterministic; go to step 4.
   - Passes alone, fails together → shared state or ordering. The defect is leaked state, not the assertion.
   - Fails intermittently either way → non-determinism: clock, network, randomness, concurrency, iteration
     order.

4. **Determine the intended behavior.** From, in order of authority: the spec or issue, the docstring or API
   contract, the surrounding tests, the commit that introduced the code. If intent is genuinely unknowable,
   **stop and ask** — you cannot decide which side is wrong without it.

5. **State the verdict explicitly, before editing anything.**

   | Verdict | Evidence | Fix |
   | ------- | -------- | --- |
   | **Code is wrong** | The test encodes the intended behavior; the code does not produce it | Fix the code. Leave the test alone. |
   | **Test is wrong** | The intended behavior changed, or the test asserted something never promised | Fix the test, and say what changed to make it obsolete. |
   | **Both wrong** | Test asserts the wrong thing *and* code does a third thing | Fix both, separately, and say so. |
   | **Neither — the test is flaky** | Non-determinism, not a behavior disagreement | Remove the non-determinism: fix the clock, seed the RNG, isolate the state. Not a retry. |

6. **Fix the correct side.** One change at a time.

7. **Re-run** the single test, then the full suite. Both must pass. Confirm you have not broken a neighbour.

8. **Report** the verdict, the evidence, the change, and the run output.

## Hard rules

- **Never weaken an assertion to get green** unless the verdict is explicitly "test is wrong", with the reason
  stated. Loosening a comparison, widening an expected range, or swapping an exact check for a truthy one is
  deleting a test while appearing to keep it.
- **Never delete or skip a failing test** to make the suite pass. If a test must be disabled, say why, say what
  would re-enable it, and get agreement first.
- **Never add a retry or sleep to fix flakiness.** That hides non-determinism instead of removing it, and the
  failure returns under load.
- **Do not fix more than the failure.** Unrelated cleanup in the same change makes the fix impossible to review
  and to revert.
- If the failure reveals a second, unrelated bug, report it — do not silently fix it too.

## Output format

```markdown
## Failure
$ <command>
<the actual assertion diff or traceback, quoted>

## Isolation
- Alone: <pass|fail>   With suite: <pass|fail>   Repeated: <n/n>

## Verdict
**<Code is wrong | Test is wrong | Both | Flaky>**

<Evidence: the intended behavior, its source, and how the observed behavior differs.>

## Fix
`path/to/file:line` — <what changed and why>

## Result
$ <command>
<output — the single test, then the full suite>
```

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/framework-detection.md` | Step 1, to find the runner command and how to run one test in isolation. |
| `scripts/detect_stack.py` | Step 1. Run it; you do not need to read it. Filesystem only, no network, no writes. |

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report the verdict before the fix, always. A fix without a stated verdict hides which side was judged wrong.
- Never claim a test passes without running it; quote the real output.
- Confirm before disabling, deleting, or weakening any test.
- Assume no network access and no package installation.
- Produce exactly the output format above, with no commentary wrapped around it.
