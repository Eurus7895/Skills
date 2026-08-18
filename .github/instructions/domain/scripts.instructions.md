---
applyTo: "tools/**/*.py,shared/**/*.py,plugins/**/*.py"
priority: P3
description: Rules for Python in this repository — standard library by default with a named allowlist for optional accelerators, no network, no writes outside the working directory, JSON on stdout, meaningful exit codes, and the requirement to fail loudly rather than guess.
---

# Scripts — Domain Standard (P3)

Applies to `tools/`, `shared/scripts/`, and every `plugins/**/scripts/`.

**`fixtures/` is excluded by the glob, deliberately.** Its Python is defective on purpose, and this file names
specific defect classes — matching it against a fixture would prime an agent that is supposed to be *finding*
them. Scoping is by enumeration rather than a `**/*.py` wildcard plus a written exemption, because by the time
a written exemption is read the text is already in context. Fixture rules live in the fixtures section of
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

## Hard constraints

- **Python 3, standard library by default.** A bundled script runs on a stranger's machine with no install
  step, so the stdlib path must always work end to end. A top-level `import requests` is a broken skill.
- Scripts must be readable. No obfuscation, no minification, no code generation that produces unreadable
  output.

## Third-party imports — allowlisted, optional, and declared

A package outside the standard library may be used **only as an accelerator**, never as a requirement. All
three conditions hold at once, or the import does not ship:

1. **It is named in the allowlist below.** Anything absent is forbidden. Adding a row is a pull request that
   edits this table, with the fallback filled in — not a judgement call made while writing a script.
2. **The import is optional and the script still works without it.** Import inside a `try`/`except
   ImportError` and fall back to the stdlib path, or exit non-zero naming the missing package and the exact
   install command. A module-level import that raises on a clean machine is the defect this rule exists to
   prevent.
3. **The `SKILL.md` pointing at the script declares it**, at the point of use, the same way network access and
   package installation are declared.

### Allowlist

| Import | PyPI | Why it earns an exception | Fallback when absent |
| ------ | ---- | ------------------------- | -------------------- |
| `tree_sitter`, `tree_sitter_languages` | `tree-sitter`, `tree-sitter-languages` | Exact parsing for languages the stdlib cannot parse. `ast` covers Python only, and regex cannot see C++ templates, TS generics, or Go interfaces. | Regex scan, with every record it produces flagged `"exact": false` |

Forbidden regardless of the allowlist: any package that reaches the network on import, and any package used to
do what the stdlib already does.

### Reporting which path ran

A script whose accuracy depends on whether the accelerator was present **must say so in its output** —
`"parser": "tree-sitter"` versus `"parser": "regex"`, and the existing `exact` flag per record. A caller that
cannot tell an exact parse from a guess will present a guess as a fact, which is the failure the whole
verification discipline exists to catch.

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
