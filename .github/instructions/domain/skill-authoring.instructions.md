---
applyTo: "**/SKILL.md"
priority: P3
description: Rules for authoring a SKILL.md — the frontmatter contract, description limits and ordering, progressive disclosure level placement, section order, and the install-boundary rule that forbids linking outside the plugin.
---

# Skill Authoring — Domain Standard (P3)

Full rationale lives in [`CONTRIBUTING.md`](../../../CONTRIBUTING.md). These are the operative rules.

## The install boundary — the rule that breaks everything else

A plugin installs standalone into `~/.copilot/installed-plugins/<marketplace>/<plugin>/`. The repository root
never reaches the user's machine.

The rule constrains **paths the skill itself must resolve at load time** — links and bundled resources. It
does **not** constrain paths the skill *names as output* in the user's repository.

- **A bundled reference or link may never escape the plugin folder.** No `../../docs/`, no link to this
  repository's `AGENTS.md` or `CONTRIBUTING.md`, no `shared/`, no absolute paths. Those resolve to nothing
  once installed.
- Bundled paths resolve relative to **the skill's own folder**, not the plugin root:
  `references/framework-detection.md`, `scripts/detect_stack.py`.
- **Naming paths in the target repository is required, not forbidden.** `setup-review-rules` writes
  `AGENTS.md` and `.github/copilot-instructions.md`; `document-codebase` writes `docs/ARCHITECTURE.md`. Those
  are outputs in someone else's project — state them plainly. Removing them breaks the skill.
- Content needed by more than one plugin lives in `shared/` and is copied in by `tools/materialize.py`.
  Never hand-edit a generated file — edit the source and re-run the script.

## Frontmatter

```markdown
---
name: my-skill
description: What it does, and exactly when it should trigger.
---
```

- `name` — lowercase kebab-case, **must equal the folder name**. No spaces, capitals, or underscores.
- `description` — required here even though the platform treats it as optional.
- Add no other keys **unless a specific runtime requires one** — extra keys are runtime-specific and not
  portable across agents. When one is genuinely needed, add it and say why in the pull request. Do not strip
  a key that an existing skill depends on.

## The description is the router

It is the only text seen before the skill is selected, so it is the highest-leverage content in the repository.

- State what the skill does **and** the concrete phrases a user would actually type.
- Put the key use case and any *"for X, use `other-skill` instead"* clause **first** — the tail is what gets
  truncated.
- Stay under **1,536 characters** (`description` + `when_to_use` combined are truncated there, silently).
- Descriptions also share a collection-wide listing budget of roughly 1% of the context window. On overflow,
  the least-invoked skills lose their descriptions first — a new skill goes quiet while still appearing
  installed. Keep descriptions dense, not long.
- If two skills could match the same request, tighten **both** until they cannot.

## Progressive disclosure — decide the level before writing

| The content is… | Level | Where |
| --------------- | ----- | ----- |
| What it does, when to fire | 1 | `description` |
| A rule that must always hold | 2 | `SKILL.md` body, **near the top** |
| The output contract | 2 | `SKILL.md` body |
| Needed only in some branches | 3 | `references/`, with an explicit pointer |
| Deterministic and repetitive | 3 | `scripts/` |

- **If it must always apply, it goes in Level 2.** A rule the model has to choose to go and read is not a rule.
- Keep the body under **~500 lines**. It stays in context for the whole session, so every line is a recurring
  cost.
- After compaction only a skill's **first ~5,000 tokens** are re-attached. Hard rules, safety constraints, and
  the output contract go early; housekeeping conventions may trail.
- An unreferenced bundled file is never read. Say when to load it.
- For scripts, say *"run it; you do not need to read it"* — scripts execute without entering context, and
  reading the source wastes it.

## Required sections

1. `## Overview`
2. `## When to use this skill`
3. `## When not to use this skill` — name the adjacent cases and where they should go instead
4. `## Steps` — numbered, imperative, in execution order
5. `## Hard rules` — the constraints that must not be violated
6. `## Output format` — **show** the format, do not describe it
7. `## Bundled resources` — a table of path and when to load it
8. `## Conventions`

**Ordering is not fixed.** The list above is the default and suits a short skill, where nothing is far from
the top. It is subordinate to the placement rule: **`## Hard rules` and `## Output format` move above
`## Steps` whenever `## Steps` grows long** — past roughly 60 lines, or any time the skill approaches the
budget. A long procedure between the top of the file and its constraints is exactly the arrangement
compaction truncates.

Do not reorder an existing skill's sections just to match the default. Reorder when the placement rule
actually bites.

## Style

- Imperative. "Run the validator", not "you might want to run the validator".
- No first-person narration, no preamble, no restating the description in the body.
- Relative paths only.
