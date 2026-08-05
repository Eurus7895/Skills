# Example reference

This file demonstrates level 3 of progressive disclosure: it is **not** loaded when the skill triggers. It only
enters context when `SKILL.md` explicitly tells the agent to read it.

## What belongs in a reference file

Detail that is needed sometimes but not always:

- Field-by-field format specifications
- API endpoint or parameter tables
- Per-framework or per-platform variants (one file each: `aws.md`, `gcp.md`, `azure.md`)
- Long worked examples

## What does not

- Anything needed every time the skill runs — that belongs in `SKILL.md`.
- Executable logic — that belongs in `scripts/`, where it runs without consuming context.
- Files that end up in the deliverable — those belong in `assets/`.

## Rules

- Point at this file from `SKILL.md`, with a sentence saying *when* to read it. An unreferenced file is never
  read.
- Past ~300 lines, add a table of contents at the top.
- Keep it self-contained: no links outside the plugin folder, since the plugin installs standalone.

Delete this file if your skill does not need a reference.
