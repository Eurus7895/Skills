# General conventions

Shared conventions that every skill in this repository follows.

> **Inline these, do not link them.** A plugin installs standalone onto someone's machine, where this file does
> not exist. A `SKILL.md` that links here produces a dead path for the user. Copy the relevant lines into the
> skill's own `## Conventions` section instead. This file is the source of truth for *authors*, not a runtime
> dependency for skills.

## Paths

Reference bundled files relative to the skill folder: `references/fields.md`, `scripts/validate.py`. Never use
absolute paths, and never reference anything outside the plugin the skill belongs to.

## Reporting

- Say what was done and what was skipped. A partial result reported honestly is more useful than a complete
  result that is not true.
- Do not claim success for anything that was not verified. If a check was not run, say it was not run.
- Report failures with the actual output, not a paraphrase.

## Acting

- Confirm before anything destructive or hard to reverse: deleting files, force-pushing, dropping data,
  overwriting work that was not just created.
- Confirm before anything outward-facing: posting, sending, publishing, opening a PR.
- Approval for one action does not carry to the next one.
- Look at the target before overwriting or deleting it.

## Environment

- Assume no network access unless the skill explicitly declares it needs it.
- Assume no packages may be installed unless the skill explicitly declares it.
- Do not read or write outside the working directory without saying so.

## Output

- When a skill defines an output format, produce exactly that format — no extra commentary wrapped around it.
- Match the surrounding code or document: its naming, its comment density, its idioms.
- Prefer editing what exists over generating a parallel new thing.
