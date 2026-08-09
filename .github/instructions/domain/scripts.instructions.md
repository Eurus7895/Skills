---
applyTo: "tools/**/*.py,shared/**/*.py,plugins/**/*.py"
priority: P3
description: Rules for Python in this repository — standard library only, no network, no writes outside the working directory, JSON on stdout, meaningful exit codes, and the requirement to fail loudly rather than guess.
---

# Scripts — Domain Standard (P3)

Applies to `tools/`, `shared/scripts/`, and every `plugins/**/scripts/`.

**`fixtures/` is excluded by the glob, deliberately.** Its Python is defective on purpose, and this file names
specific defect classes — matching it against a fixture would prime an agent that is supposed to be *finding*
them. Scoping is by enumeration rather than a `**/*.py` wildcard plus a written exemption, because by the time
a written exemption is read the text is already in context. Fixture rules live in the fixtures section of
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

## Hard constraints

- **Python 3, standard library only.** No third-party imports, ever. A bundled script runs on a stranger's
  machine with no install step; an `import requests` is a broken skill.
- Scripts must be readable. No obfuscation, no minification, no code generation that produces unreadable
  output.

## Side effects — default off, permitted when disclosed

The default posture is **read-only, filesystem-only, no network**. Departing from it is allowed, but only
when the side effect is **declared in the `SKILL.md` that points at the script**, at the point of use:

- Network access
- Package installation
- Writes outside the working directory

An undeclared side effect is the defect, not the side effect itself. A script that writes an output file the
skill documents is fine; one that quietly reaches the network is not.

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

There is no single output contract — the right one depends on who consumes the script. Match the interface
the script already has; do not convert one kind into another.

| Kind | Consumer | Contract | Example |
| ---- | -------- | -------- | ------- |
| **Detector** | A skill, which branches on the result | One JSON object on **stdout** | `detect_stack.py` |
| **Extractor** | A later skill or a human, via a file | JSON to the **named output file**, a short human digest on stdout | `scan_repo.py` |
| **Gate** | A person or CI, reading the terminal | Human-readable status lines | `validate.py`, `materialize.py` |

Universal to all three:

- Exit `0` on success, non-zero when the caller must not trust the output. A gate exits non-zero on any
  failure; that exit code is what CI reads.
- Diagnostics go to stderr.
- Accept an optional target path. Defaulting to the repository root silently gives the wrong answer in a
  monorepo, and in this repo it picks up `fixtures/` and reports Python/pytest for a repository that has
  neither.

## Style

- Match the surrounding code: its naming, its comment density, its idioms.
- Comment **why**, not what. A comment that restates the line below it is noise.
- No docstring theatre. A one-line docstring on an obvious function is not documentation.
