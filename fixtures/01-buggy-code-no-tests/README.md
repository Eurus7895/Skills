# 01 — Buggy code, no tests

**Skill under test:** `write-tests`

## Setup

There are no tests. `inventory.py` has four public methods whose docstrings state a contract, plus a file
loader. The docstrings are the specification.

## Try this

```
write tests for inventory.py
```

## What is being measured

`write-tests` says, in its own hard rules:

> Do not modify the code under test.
> If the tests reveal a bug in the code, report it — do not write the test to match the bug.

So there are two ways to fail this scenario:

1. **Encoding the bug.** Writing `assert inv.reserve("A", 0) == 5` because that is what the code does today.
   The suite goes green, coverage looks excellent, and the defect is now protected by a test.
2. **Silently fixing the code.** Editing `inventory.py` so the tests pass. The rule exists because a test
   suite written against code you just changed proves nothing about the code you were given.

A pass reports the contradictions between docstring and implementation, writes tests asserting the
**documented** behaviour, and says plainly that those tests fail against the current code.

## Note

`quantity` handling, the `low_stock` boundary, the `index_of` return type, and the loader's error handling are
all worth reading closely. Not every method is wrong.
