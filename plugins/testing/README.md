# testing

Write, review, and debug automated tests in whatever framework a repository already uses.

Every skill starts by detecting the stack rather than assuming one, so the plugin works across ecosystems and
never introduces a second test framework into a repo that already has one.

## Install

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install testing@CopilotBox
```

## Skills

- **`write-tests`** — produce a suite for existing code: happy path, edge cases, error paths, boundaries.
  Fires on "write tests", "add unit tests", "cover this function", coverage gaps.
- **`review-tests`** — audit an existing suite for assertions that cannot fail, missing cases, over-mocking,
  and flakiness. Fires on "are these tests any good", "why didn't the tests catch this", flaky failures.
- **`debug-failing-test`** — decide whether the test or the code is wrong, then fix the correct side. Fires on
  any failing test, CI breakage, or "passes locally but not in CI".

## Notes

- Bundled scripts are Python 3, stdlib only. They read the filesystem; no network, no writes.
- `references/framework-detection.md` and `scripts/detect_stack.py` are generated from `shared/` in the source
  repository. Do not edit them here — edit `shared/` and run `python3 tools/materialize.py`.
