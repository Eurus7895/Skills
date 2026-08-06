---
name: review-tests
description: Audit an existing test suite for weakness — assertions that cannot fail, missing edge cases, over-mocking that tests the mock instead of the code, order-dependence and flakiness, and tests that pass no matter what the code does. Use whenever the user asks "are these tests any good", "review my tests", "why didn't the tests catch this", "is this suite trustworthy", mentions flaky or intermittently failing tests, says coverage is high but bugs still ship, or asks whether a test is actually testing anything.
---

# Review tests

## Overview

Audit a test suite and report what it fails to protect. High coverage with weak assertions is the common
failure mode: the suite runs every line and would notice almost no regression. The output is a severity-ordered
findings list, each with `file:line` and a concrete scenario the suite would miss.

This skill does not rewrite the suite. It tells you what is wrong and what the fix is.

## When to use this skill

- "Review my tests" / "are these tests good?"
- A bug shipped despite passing tests, and the user wants to know why.
- Tests are flaky, order-dependent, or fail only in CI.
- Coverage numbers look healthy but confidence is low.

## When not to use this skill

- **Code needs new tests** — use `write-tests`.
- **A specific test is failing right now** — use `debug-failing-test`.
- **The production code is what needs reviewing**, not the tests — use the `review-code` skill from the
  `code-review` plugin.
- **The user wants coverage measured** — run their coverage tool; that is ordinary work, not this skill.

## Steps

1. **Detect the framework.** Read `references/framework-detection.md` and run
   `python3 scripts/detect_stack.py <repo-root>`. You need the framework's idioms to judge whether a pattern is
   a smell or the house style.

2. **Run the suite.** Record the pass/fail counts and the runtime. If it does not pass on a clean checkout,
   that is the first finding.

3. **Check for order-dependence.** Run the suite in a different order or in isolation if the framework supports
   it (`pytest -p no:randomly` vs `-p randomly`, `--shuffle`, running a single file alone). Tests that pass
   together but fail alone share state — a blocking finding.

4. **Read the tests against the code they claim to cover.** For each test ask the one question that matters:
   **what change to the production code would make this test fail?** If the honest answer is "none" or "only a
   crash", the test is decorative.

5. **Apply the audit checklist** below.

6. **Report findings**, severity-ordered, each with a location and a concrete miss.

## Audit checklist

**Assertions that cannot fail**
- No assertion at all — the test only checks that nothing threw.
- Asserting on a literal (`assert 1 == 1`) or on the mock's own return value.
- `assertTrue(result)` where any non-empty value passes.
- Snapshot tests regenerated whenever they fail, which asserts only that the code is deterministic.

**Missing cases**
- Error paths in the code with no test that triggers them.
- Boundaries untested — the code branches on `> 10` and only `5` and `50` are tested.
- Empty, null, zero, single-element, and maximum inputs absent.
- Concurrency or ordering behavior the code promises but nothing exercises.

**Over-mocking**
- The unit under test is mocked, so the test asserts the mock's behavior.
- So many doubles that the test would pass against a completely different implementation.
- Mocks asserting call counts rather than outcomes, which pins the implementation and breaks on refactors that
  change nothing observable.

**Flakiness**
- Real clocks, real sleeps, real network, real randomness without a fixed seed.
- Shared mutable state — module globals, class attributes, a database not reset between tests.
- Dependence on filesystem ordering, dict/map iteration order, or locale.

**Maintenance smells**
- Tests named `test_1`, `test_it_works`, or after the function rather than the behavior.
- Assertions on incidental output — log text, key order, exact whitespace — that break on harmless changes.
- Disabled tests: `skip`, `xfail`, `it.only`, `t.Skip`, commented-out blocks. Each is a silent coverage hole.

## Severity

| Severity | Means |
| -------- | ----- |
| **Blocking** | The suite reports safety it does not provide — a real regression would pass CI. |
| **Should fix** | A meaningful gap or a flakiness source that will cost time. |
| **Nit** | Naming, duplication, readability. The author may decline. |

If you cannot name the change that would slip through, it is a nit at most.

## Output format

```markdown
## Suite summary
<files, test count, runtime, pass/fail on a clean run, order-dependence result>

## Findings

### Blocking
1. **`tests/test_auth.py:34`** — issue: `test_login_fails` asserts only that the call returned.
   A regression making `login()` return success for a wrong password would still pass.
   Assert on the returned status and that no session was created.

### Should fix
...

### Nits
...

## Not reviewed
<files skipped and why>
```

Report "no blocking findings" plainly when that is the answer. Manufacturing findings to look thorough teaches
the author to ignore reviews.

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/framework-detection.md` | Step 1, always — you need the framework's idioms to judge smells. |
| `scripts/detect_stack.py` | Step 1. Run it; you do not need to read it. Filesystem only, no network, no writes. |

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Every finding carries `file:line` and a concrete failure scenario. A finding without a location cannot be
  acted on.
- Report what was reviewed and what was skipped; never imply coverage you did not check.
- This skill reports; it does not rewrite. Ask before changing any test file.
- Assume no network access and no package installation.
- Produce exactly the output format above, with no commentary wrapped around it.
