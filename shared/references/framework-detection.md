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

## Rules

- **Never introduce a second framework** into a repo that already has one. If the existing choice is genuinely
  wrong for the task, say so and let the user decide — do not migrate as a side effect.
- **Monorepos have more than one answer.** Detect per package, not per repository. Pass the target path as the
  second argument so the nearest enclosing marker wins.
- **A framework in `package.json` is not proof it is used.** Confirm that test files exist and match it;
  abandoned dependencies are common.
- **Prefer the CI command over a locally convenient one.** If CI runs `npm test -- --run`, that is the command
  whose behavior matters.
