# 03 — Weak suite

**Skill under test:** `review-tests`

## Setup

`cart.py` is correct. `tests/test_cart.py` is green — and would survive almost any regression you could
introduce into `cart.py`.

## Try this

```
review my tests
```

or

```
why didn't the tests catch this bug?
```

## What is being measured

Coverage here is excellent and confidence should be near zero. The audit has to distinguish "the suite runs
every line" from "the suite would notice if a line were wrong".

The question `review-tests` tells the agent to ask about every test is:

> What change to the production code would make this test fail?

For most of this file the honest answer is "none" or "only a crash". A pass identifies which tests those are,
says what regression each would let through, and separates that from the merely cosmetic.

## What is planted

Without giving away the line numbers — the suite contains examples of each of the following:

- Assertions that pass regardless of the returned value.
- A test asserting a type rather than a behaviour.
- An assertion whose two allowed outcomes cover every possible result.
- The unit under test replaced by a mock, so the test asserts the mock's configured return value.
- A test asserting a call count instead of an outcome.
- Module-level shared state, making at least one test dependent on execution order.
- A test with no assertion at all.

A strong review also notes that running the file in isolation or in a different order changes the result — the
suite is not just weak, it is not reproducible.

## Failure modes

- "All 8 tests pass, coverage looks good" — mistaking green for meaningful.
- Rewriting the tests instead of reporting. `review-tests` reports; it does not rewrite.
- Reporting only style issues (naming, duplication) while missing that the subject is mocked out.
