# Detecting the test framework

Run this before writing, reviewing, or debugging any test. Never assume a framework — adopt the one the
repository already uses.

## Procedure

Work top to bottom and stop at the first confident answer.

1. **Run the detector.** `python3 scripts/detect_stack.py <repo-root> [target]` prints JSON. Pass the file or
   directory you are working on as `target` — in a monorepo it selects the nearest enclosing package instead of
   the first marker found repository-wide.

   ```json
   {"ecosystem": "python", "test_framework": "pytest", "runner_command": "pytest",
    "test_glob": "tests/test_*.py", "confidence": "high"}
   ```

   `confidence` is `high`, `low`, or `none`. Treat `low` as a hypothesis to confirm against step 2, and `none`
   as "go to step 4".

2. **Confirm against existing tests.** Find the test files and read one. It is the ground truth for import
   style, fixture and setup conventions, assertion style, naming, and how the suite is organized. Match what
   you find — a suite that mixes two idioms is worse than one written in the style you would not have chosen.

3. **Find the runner command.** Look where the project declares it, in this order: `package.json` `scripts`,
   `Makefile` / `Justfile` targets, `pyproject.toml` `[tool.*]` sections, `tox.ini`, `noxfile.py`, and CI
   workflow files under `.github/workflows/`. The CI command is authoritative — it is what has to pass.

4. **If it is still ambiguous, ask.** Say what you found and what is unclear. Do not pick for the user.

## Ecosystem reference

| Ecosystem | Marker file | Common frameworks | Typical runner | Test file convention |
| --------- | ----------- | ----------------- | -------------- | -------------------- |
| Python | `pyproject.toml`, `setup.py`, `pytest.ini`, `tox.ini` | pytest, unittest | `pytest`, `python -m pytest` | `tests/test_*.py`, `*_test.py` |
| JavaScript / TypeScript | `package.json` | vitest, jest, mocha, node:test | `npm test`, `npx vitest run` | `*.test.ts`, `*.spec.js`, `__tests__/` |
| Go | `go.mod` | stdlib `testing`, testify | `go test ./...` | `*_test.go` beside source |
| Rust | `Cargo.toml` | built-in | `cargo test` | `#[cfg(test)]` inline, `tests/` |
| Java / Kotlin | `pom.xml`, `build.gradle` | JUnit 5, TestNG | `mvn test`, `gradle test` | `src/test/java/**/*Test.java` |
| C / C++ | `CMakeLists.txt`, `Makefile` | GoogleTest, Catch2, doctest | `ctest`, `cmake --build . --target test` | `test/*_test.cpp`, `tests/` |
| C# / .NET | `*.csproj`, `*.sln` | xUnit, NUnit, MSTest | `dotnet test` | `*Tests.cs`, `*.Tests/` |
| Ruby | `Gemfile` | RSpec, minitest | `bundle exec rspec` | `spec/**/*_spec.rb` |
| PHP | `composer.json` | PHPUnit, Pest | `vendor/bin/phpunit` | `tests/*Test.php` |
| Swift | `Package.swift` | XCTest, swift-testing | `swift test` | `Tests/**/*Tests.swift` |

## The `env` object (`--check-env`)

Passing `--check-env` adds one key, `env`, saying whether the detected runner can actually be invoked. Without
the flag the output is unchanged.

| Field | Means |
| ----- | ----- |
| `available` | the runner exists **and** is executable. False means nothing can be run yet. |
| `invocation` | the command that runs it. Prefer this over `runner_command`: an inactive project virtualenv holds a working runner that the bare command will not reach. |
| `working_directory` | where `command` must be run, relative to the root you passed. In a workspace this is the member, not the root — running an add from the wrong directory edits the wrong manifest. |
| `declared` | the project's own manifest depends on this runner. Read from dependency tables and requirements files only — configuring a tool is not depending on it. |
| `action` | `none`, `sync` (install what the lockfile already pins), `add` (introduce a dependency the project lacks), or `unknown` (no safe command could be worked out). |
| `command` | the exact command. Run this or nothing. |
| `modifies` | tracked files the command rewrites, relative to the root you passed. A workspace lockfile is reported where it actually lives, which is not always beside the manifest. |
| `consent` | how much agreement the command needs: `none`, `notify`, or `ask`. |
| `notes` | what the check concluded and why. Worth reading before acting. |

**`consent` is the authority.** It is derived here so that every skill applies the same rule; re-deriving it
from `action` or `modifies` gets it wrong, because plain `pip install` adds a dependency while writing no file
at all and still needs asking. The full rules for acting on it live in each `SKILL.md`, because they are
safety rules and a rule a model must decide to go and read is not a rule.

A `sync` is not always harmless: with no lockfile to install from, the command has to create one, and
`consent` is raised to `ask` accordingly. Read the field, not the shape of the situation.

## Rules

- **Never introduce a second framework** into a repo that already has one. If the existing choice is genuinely
  wrong for the task, say so and let the user decide — do not migrate as a side effect.
- **Monorepos have more than one answer.** Detect per package, not per repository. Pass the target path as the
  second argument so the nearest enclosing marker wins.
- **A framework in `package.json` is not proof it is used.** Confirm that test files exist and match it;
  abandoned dependencies are common.
- **Prefer the CI command over a locally convenient one.** If CI runs `npm test -- --run`, that is the command
  whose behavior matters.
