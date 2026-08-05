# Contributing

The authoring standard for this repository. Everything here is normative — if a plugin or skill disagrees with
this document, the document wins.

- [Anatomy of a plugin](#anatomy-of-a-plugin)
- [Anatomy of a skill](#anatomy-of-a-skill)
- [The frontmatter contract](#the-frontmatter-contract)
- [Writing the description](#writing-the-description)
- [Progressive disclosure](#progressive-disclosure)
- [Writing style](#writing-style)
- [Scope boundaries](#scope-boundaries)
- [Safety](#safety)
- [Checklist](#checklist)

## Anatomy of a plugin

A plugin is an installable bundle of related skills. One plugin = one coherent theme.

```
plugins/<plugin-name>/
├── .github/plugin/plugin.json   # required — the manifest
├── README.md                    # required — what it is, how to install, what's inside
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

`plugin.json` follows the Claude Code plugin spec:

| Field | Required | Notes |
| ----- | -------- | ----- |
| `name` | yes | lowercase kebab-case; **must** equal the folder name; this is the install name |
| `description` | yes | one or two sentences; shown when browsing the marketplace |
| `version` | yes | semver; start at `0.1.0`, bump on every content change |
| `skills` | yes here | array of relative folder paths, each with a trailing slash: `"./skills/my-skill/"` |
| `keywords` | recommended | lowercase search terms |
| `author` | recommended | `{ "name": "..." }`, optionally `url` |
| `repository` | recommended | HTTPS URL |
| `license` | recommended | SPDX identifier, e.g. `MIT` |
| `agents` | optional | array of paths to custom agent Markdown files |
| `commands` | optional | array of paths to slash-command Markdown files |

Every plugin must also be registered in [`.github/plugin/marketplace.json`](.github/plugin/marketplace.json):

```json
{
  "name": "<plugin-name>",
  "source": "plugins/<plugin-name>",
  "description": "same text as plugin.json",
  "version": "same version as plugin.json"
}
```

Drift between the two manifests is a bug. Keep `description` and `version` byte-identical.

### Sizing a plugin

- Group by **the job the user is doing**, not by technology. `release-management` is a plugin;
  `python-and-also-terraform` is not.
- One skill in a plugin is fine. Ten is a smell — the theme is probably too broad.
- Do not create a plugin whose theme already exists. Add the skill to the existing plugin instead.

## Anatomy of a skill

```
skills/<skill-name>/
├── SKILL.md          # required — frontmatter + instructions
├── references/       # optional — docs the agent reads on demand
├── scripts/          # optional — executable code
└── assets/           # optional — files that end up in the output
```

What goes where:

- **`scripts/`** — deterministic, repetitive work that code does better than prose: parsing, transforming,
  validating. The agent runs these; it does not have to read them.
- **`references/`** — detail that is only needed sometimes: API tables, format specs, per-framework variants.
  Loaded into context only when `SKILL.md` tells the agent to read it.
- **`assets/`** — files that appear in the deliverable: templates, boilerplate, icons, fonts.

If a skill supports several variants, split by variant rather than writing one giant file:

```
cloud-deploy/
├── SKILL.md              # workflow + how to pick
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

## The frontmatter contract

`SKILL.md` opens with YAML frontmatter. Two fields are required and, in this repo, they are the only two you
should normally write:

```markdown
---
name: my-skill
description: What it does, and exactly when it should trigger.
---
```

- `name` — lowercase kebab-case, must equal the folder name. No spaces, no capitals, no underscores.
- `description` — see below. This is load-bearing.

Extra keys are runtime-specific and are not portable across agents. Leave them out unless a specific runtime
requires one, and say why in the PR.

## Writing the description

The description is the **only** thing an agent sees before deciding whether to load the skill. The body of the
`SKILL.md` is invisible until after that decision. So:

**State what the skill does AND the concrete phrases and contexts that should activate it.** Do not put "when
to use this" only in the body — by the time the body is read, the decision is already made.

Agents tend to *under*-trigger skills. Lean assertive.

❌ Too thin — nothing to match against:

```yaml
description: Helps with database migrations.
```

✅ Says what it does and when to fire:

```yaml
description: Generate, review, and roll back SQL schema migrations for Postgres and MySQL, including
  reversible up/down pairs and data backfills. Use whenever the user mentions migrations, schema changes,
  ALTER TABLE, adding or dropping columns, backfilling data, or asks how to change a database safely —
  even if they do not say the word "migration".
```

Rules of thumb:

- Name the artifacts, commands, and file types involved — those are what a user's phrasing will contain.
- Include the phrasings a user would actually type, not just the formal term.
- One dense paragraph. Not a bulleted list, not an essay.
- If two skills could both match the same request, tighten both descriptions until they cannot.

## Progressive disclosure

Skills load in three levels:

| Level | What | When |
| ----- | ---- | ---- |
| 1 | `name` + `description` | always in context |
| 2 | `SKILL.md` body | when the skill triggers |
| 3 | `references/`, `scripts/`, `assets/` | only when `SKILL.md` points at them |

Budgets:

- Keep `SKILL.md` under **~500 lines**. Approaching that means the content belongs in `references/`.
- When you move content out, leave an explicit pointer: *"For the full field reference, read
  `references/fields.md`."* An unreferenced file is never read.
- Any reference file over ~300 lines gets a table of contents at the top.
- Scripts can be arbitrarily large — they execute without being loaded into context.

## Writing style

- **Imperative.** "Run the validator", not "you might want to run the validator".
- **Concrete steps**, numbered, in the order they happen.
- **Define the output format explicitly** — show it, do not describe it. If the skill produces a file, show the
  file. If it produces a table, show the table.
- **Relative paths only**, relative to the skill folder.
- No first-person narration, no filler preamble, no restating the description in the body.

## Scope boundaries

Every `SKILL.md` needs a "When not to use this" section. A skill that fires on routine work is worse than no
skill: it burns context and drags the agent toward a workflow that does not fit.

Name the adjacent cases that should *not* trigger it, and where they should go instead.

## Safety

Skills are injected straight into an agent's context and are **not verified by GitHub**. Every line is
effectively executable. Therefore:

- No credentials, tokens, API keys, or internal hostnames — in any file, including examples.
- No destructive commands (`rm -rf`, force-push, `DROP`, bulk delete) without an explicit confirmation step
  written into the instructions.
- No obfuscated, minified, or encoded scripts. If a reviewer cannot read it, it does not ship.
- Declare side effects in `SKILL.md`: network access, package installs, writes outside the working directory.
- No instructions that try to override the host agent's safety behavior or suppress its confirmations.

## Checklist

Before opening a PR:

- [ ] `SKILL.md` exists at the skill folder root; frontmatter parses; `name` matches the folder name.
- [ ] `description` states both what it does and when it triggers, and cannot collide with a sibling skill.
- [ ] "When not to use this" section is present and specific.
- [ ] `SKILL.md` under ~500 lines; overflow moved to `references/` **and** pointed at from `SKILL.md`.
- [ ] Every bundled file is referenced from somewhere; no orphans.
- [ ] Skill listed in its plugin's `skills` array.
- [ ] `plugin.json` and `marketplace.json` agree on `name`, `description`, `version`; version bumped.
- [ ] Root `README.md` catalog row added or updated.
- [ ] Conventions from [`docs/GENERAL.md`](docs/GENERAL.md) inlined — not linked.
- [ ] No links escape the plugin folder; no absolute paths; all JSON parses.
- [ ] Safety rules above hold.
