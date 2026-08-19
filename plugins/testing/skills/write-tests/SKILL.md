---
name: write-tests
description: Write automated tests for code that already exists — unit tests, edge cases, error paths, and boundary conditions — in whatever framework the repository already uses. Use whenever the user says "write tests", "add unit tests", "cover this function", "this needs test coverage", "test this file", mentions low or missing coverage, asks what cases they should be testing, or hands over a function or module and asks for a test suite. Also use when a change is finished and tests are the remaining work.
---

# Write tests

## Overview

Given a file, function, class, or module, produce a test suite that would actually catch a regression: the
happy path, the edge cases, the error paths, and the boundaries. The suite matches the repository's existing
framework and idioms — you adopt what is there rather than introducing what you prefer.

The deliverable is test files written to disk, plus the command that runs them and the result of running it.

## When to use this skill

- "Write tests for `parse_config`" / "add unit tests for this module".
- "What cases am I missing?" for existing code.
- Coverage is low or a file has no tests, and the user wants that fixed.
- A feature is implemented and the tests are the remaining work.

## When not to use this skill

- **A test is failing and you need to know why** — use `debug-failing-test`. Writing more tests will not
  diagnose a failure.
- **Tests already exist and the question is whether they are any good** — use `review-tests`.
- **The user wants the implementation written too** — that is ordinary work; do it directly. This skill assumes
  the code under test already exists.
- **Test-first / TDD**, where the test is written before the code — this skill reads existing behavior to
  decide what to assert, which does not apply when there is nothing to read.

## Steps

1. **Detect the framework and check the environment.** Read `references/framework-detection.md` and follow it.
   Run `python3 scripts/detect_stack.py <repo-root> --check-env` to get the ecosystem, framework, runner,
   test-file convention, and whether that runner can actually be invoked. If `confidence` is `none`, or the
   result conflicts with what you see, stop and ask — do not pick a framework for the user.

   If `env.available` is false, settle it here under **Preparing the environment** below. Step 6 runs the suite;
   discovering a missing runner there means the tests were written blind.

2. **Read the code under test.** Identify for each unit: the inputs and their valid ranges, the return values,
   the error conditions and how they surface, the side effects, and the dependencies that will need doubles.

3. **Read one existing test file.** It is ground truth for import style, fixtures and setup, assertion style,
   naming, and file organization. Match it.

4. **Enumerate cases before writing any.** For each unit list:
   - **Happy path** — the ordinary call with ordinary input.
   - **Edge cases** — empty, zero, one, maximum, unicode, whitespace-only, duplicates, unsorted input.
   - **Error paths** — every raise/throw/error-return the code can produce, asserted by type *and* trigger.
   - **Boundaries** — the values on either side of every comparison in the code.
   Show this list before writing. It is cheap to correct here and expensive to correct after.

5. **Write the tests.** One behavior per test. Name each for the behavior it pins, not the function it calls —
   `test_rejects_negative_quantity`, not `test_add_item_2`.

6. **Run them.** Use the runner command from step 1. Every test must pass. A test you did not run is not a
   test you wrote.

7. **Verify they can fail.** For at least the most important assertions, confirm the test actually detects a
   regression — break the behavior mentally or temporarily and check the test would catch it. A test that
   passes against broken code is worse than no test, because it reports safety that does not exist.

8. **Report.** State the files written, the command, the pass count, and anything you deliberately did not
   cover with the reason.

## Preparing the environment

You may install the project's test runner, and nothing else. `env.consent` says how much agreement that
takes. **Read `consent`; do not re-derive it** from `action` or `modifies` — pip can add a dependency while
writing no file at all, and that still needs asking.

| `env.consent` | Situation | What to do |
| ------------- | --------- | ---------- |
| `none` | the runner is installed | proceed |
| `notify` | the project already depends on this runner and the lockfile pins it; the command installs it and rewrites nothing | say what you are running and why, run `env.command`, continue |
| `ask` | the command introduces a dependency or writes a tracked file — `env.modifies` names them | quote the command and those files, ask, and wait for a yes |

- **Never install unattended.** If there is no one to ask — CI, a coding agent, `-p` mode, a subagent — report
  what is missing and stop. Nobody objecting is not consent, and an install in CI lands in someone's pipeline
  with no one watching.
- **Install only what `env.command` says.** Not a framework you prefer, not a global install to sidestep a
  refusal, not an upgrade of something already there.
- **Prefer `env.invocation` over `runner_command`.** A project virtualenv that is not active holds a working
  `pytest` the bare command will not reach.
- If the install fails, report its real output and stop. A second framework in a repo that already has one is
  worse than no tests.
- When `env.action` is `unknown` the script could not work out a safe command — say what is missing and let the
  user install it.

## Hard rules

- **Do not modify the code under test.** If it cannot be tested without changing it — a hard-coded dependency,
  a hidden global, an untestable constructor — say so, explain what change would make it testable, and stop.
  Silently refactoring the subject of a test is how a passing suite starts lying.
- **Do not assert on things the code does not promise.** Testing incidental output — key order, exact
  whitespace, log text — produces tests that break on harmless changes and get deleted.
- **Do not mock what you own.** Mock the network, the clock, the filesystem, and third-party services. Mocking
  your own function under test means asserting the mock works.
- If the tests reveal a bug in the code, report it — do not write the test to match the bug.

## Output format

```
## Cases

`<unit>`
- happy: <case>
- edge: <case>
- error: <case> -> <expected error>
- boundary: <case>

## Files written
- `tests/test_config.py` — 11 tests

## Result
$ pytest tests/test_config.py
11 passed

## Not covered
- <what, and why>
```

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/framework-detection.md` | Step 1, always — before choosing any framework or runner. |
| `scripts/detect_stack.py` | Step 1, with `--check-env`. Run it; you do not need to read it. Filesystem only, no network, no writes — it reports what an install would cost, it never installs. |

## Side effects

Writes test files to the repository. May run the project's package manager to install its test runner, under
the consent rules in **Preparing the environment** — that command can reach the network and, when consent is
`ask`, rewrite the files listed in `env.modifies`. Nothing else is installed.

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report what was done and what was skipped; never claim a test passes without running it.
- Confirm before anything destructive or irreversible — overwriting an existing test file needs a look first.
- Installing the project's test runner is the one exception to "no network, no package installation", and only
  under **Preparing the environment** above. Nothing else may be installed.
- Produce exactly the output format above, with no commentary wrapped around it.
