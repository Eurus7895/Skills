---
applyTo: "**/*.py"
priority: P3
description: Rules for Python in this repository — standard library only, no network, no writes outside the working directory, JSON on stdout, meaningful exit codes, and the requirement to fail loudly rather than guess.
---

# Scripts — Domain Standard (P3)

Applies to `tools/`, `shared/scripts/`, and every `plugins/**/scripts/`. Fixture code is exempt from the
quality rules and governed by [`fixtures.instructions.md`](fixtures.instructions.md).

## Hard constraints

- **Python 3, standard library only.** No third-party imports, ever. A bundled script runs on a stranger's
  machine with no install step; an `import requests` is a broken skill.
- **No network access.** Filesystem only.
- **No writes outside the working directory**, and no writes at all unless the script's purpose is to write.
- Scripts must be readable. No obfuscation, no minification, no code generation that produces unreadable
  output.

## Behaviour

- **Fail loudly rather than guess.** When a script cannot determine something, it says so and exits non-zero.
  `detect_stack.py` emits `{"confidence": "none"}` and exits 1 rather than reporting a plausible guess, so
  the calling skill can branch instead of acting on a fabrication.
- Report confidence honestly. Do not mark a result `high` when the evidence is a filename that could mean
  several things — check the manifest before claiming a framework.
- Guard path traversal anywhere a path is composed from input. `os.path.join` does **not** constrain the
  result; resolve and verify containment.
- Prefer a script over a `references/` document whenever the work is deterministic. Scripts execute without
  entering context; references cost their full length when read.

## Interface

- Results go to **stdout as JSON**, one object. Diagnostics go to stderr.
- Exit `0` on success, non-zero when the caller must not trust the output.
- Accept an optional target path. Defaulting to the repository root silently gives the wrong answer in a
  monorepo, and in this repo it picks up `fixtures/` and reports Python/pytest for a repository that has
  neither.

## Style

- Match the surrounding code: its naming, its comment density, its idioms.
- Comment **why**, not what. A comment that restates the line below it is noise.
- No docstring theatre. A one-line docstring on an obvious function is not documentation.
