---
name: setup-review-rules
description: Generate a repository's agent and review rules files — AGENTS.md, .github/copilot-instructions.md, and a review checklist — tuned to the stack, test framework, and conventions the repository actually uses. Use whenever the user says "set up rules for this repo", "add AGENTS.md", "create copilot instructions", "onboard this repo for AI agents", "we need coding standards", "make a review checklist", or asks how to make an agent follow their project's conventions.
---

# Set up review rules

## Overview

Give a repository the rules files that agents and reviewers read: `AGENTS.md`,
`.github/copilot-instructions.md`, and a review checklist. The content is derived from what the repository
actually does — its stack, test runner, lint and format commands, branch and commit conventions — not from a
generic template.

A rules file that states conventions the repo does not follow is worse than none: agents obey it and produce
code that does not match the codebase.

## When to use this skill

- "Set up AGENTS.md" / "add copilot instructions" / "onboard this repo for agents".
- "We need coding standards written down."
- "Make a review checklist for this project."
- An agent keeps violating project conventions and the user wants that fixed at the source.

## When not to use this skill

- **Reviewing a change** — use `review-code`.
- **The repo already has good rules files and the user wants one line changed** — just edit it.
- **The user wants CI configured** — that is ordinary work, not this skill.
- **Writing a public-facing README or contributor guide** — different audience, different document.

## Steps

1. **Survey what exists.** Look for `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
   `CONTRIBUTING.md`, `.editorconfig`, and any `.cursorrules` or similar. **Never overwrite one without
   asking.** If a rules file exists, propose a diff instead of a replacement.

2. **Detect the stack.** Run `python3 scripts/detect_stack.py <repo-root> <target-package>` for each package
   with its own manifest. Record its ecosystem, test framework and runner separately; do not generalize the
   first package's result to the whole repository.

3. **Find the real commands.** Read `package.json` scripts, `Makefile`/`Justfile` targets, `pyproject.toml`
   tool sections, and `.github/workflows/`. Extract the actual build, test, lint, and format commands with
   each command's working directory and package. **The CI workflow is authoritative** about what has to pass.

4. **Observe conventions from the code, not from taste.** Sample several files per package and record what is true:
   naming style, file layout, error-handling idiom, whether comments are sparse or dense, how tests are named
   and organized, import ordering. Write down what the repo does, not what you would prefer.

5. **Read the git history for process conventions.** `git log --oneline -30` shows the commit message style
   (Conventional Commits or not), and branch names show the naming pattern. State what is observed.

6. **Separate observations from policy.** A sample or recent commit shows a pattern, not an owner's mandate.
   Verify proposed hard rules, definition of done and any convention you would state as binding against
   existing written policy or get the owner's answer before writing them. Leave unsupported items out.

7. **Write the files.**

   **`AGENTS.md`** — the operating instructions:
   - What the project is, in two sentences.
   - The commands: build, test, lint, format, and how to run a single test.
   - Package-scoped conventions supported by written policy or confirmed by the owner; label unconfirmed
     observations as observations rather than instructions.
   - Hard rules and definition of done only where supported by written policy or the owner's answer.

   **`.github/copilot-instructions.md`** — deliberately short, pointing at `AGENTS.md`. Two copies of the same
   rules drift apart; one is the source of truth.

   **The review checklist** — project-specific items only. Do not restate generic advice; the `review-code`
   skill already carries the general standard. This file is for what is peculiar to *this* repo: the module
   that must not gain dependencies, the migration that must accompany a schema change, the API whose contract
   is public.

8. **Report** the files written, and every inference you made, so the user can correct them.

## Hard rules

- **Never overwrite an existing rules file without explicit confirmation.** Show what would change first.
- **Never turn an observed pattern into a mandatory convention without authority.** If the repo has no commit
  convention, say so rather than imposing Conventional Commits.
- **Never invent commands.** Every command in the output must be one you found declared in the repo. If there
  is no lint command, the file says there is no lint command.
- Keep `AGENTS.md` short enough to be read every session. Detail belongs in the files it points to.
- No secrets, tokens, internal hostnames, or credentials in any generated file.

## Output format

```markdown
## Detected
- Package: `<path>` (repeat this block for every package, or `.` for a single-package repo)
  - Stack: <ecosystem>, <test framework>
  - Working directory: `<path>`
  - Build: `<command|none>` (source: <where found>)
  - Test: `<command|none>` (source: <where found>)
  - Lint: `<command|none>` (source: <where found>)
- Commit style: <observed|none observed>

## Inferred — confirm these
- <inference and the evidence for it>

## Files written
- `AGENTS.md` — new
- `.github/copilot-instructions.md` — new
- `docs/review-checklist.md` — new

## Skipped
- <existing file left alone, and why>
```

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/review-standard.md` | Step 7, when writing the review checklist — so the project-specific list complements the general standard instead of duplicating it. |
| `scripts/detect_stack.py` | Step 2. Run it; you do not need to read it. Filesystem only, no network, no writes. |

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report every inference made, so wrong guesses are cheap to correct.
- Confirm before overwriting any existing file; look at it first.
- Assume no network access and no package installation.
- Produce exactly the output format above, with no commentary wrapped around it.
