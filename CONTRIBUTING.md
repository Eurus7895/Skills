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

### Sharing content between plugins

A plugin installs standalone into `~/.copilot/installed-plugins/<marketplace>/<plugin>/`. Nothing it references
can live outside its own folder — a path into a repo-level directory is dead on the user's machine.

So content used by more than one plugin is authored once under `shared/` and **copied in**:

1. Put the file in `shared/references/` or `shared/scripts/`.
2. List it in the consuming plugin's `shared.manifest`, one line per destination:

   ```
   references/framework-detection.md -> skills/write-tests/references/framework-detection.md
   scripts/detect_stack.py           -> skills/write-tests/scripts/detect_stack.py
   ```

3. Run `python3 tools/materialize.py`. Commit the generated copies.

**Destinations are per-skill, not per-plugin.** A `SKILL.md` resolves its bundled paths relative to its own
folder, so a file at the plugin root will not resolve from `skills/<name>/SKILL.md`. Each skill that needs a
shared file gets its own copy.

The copies are committed because `copilot plugin marketplace add` reads the repository directly — an
unmaterialized plugin installs broken.

**Never hand-edit a generated file.** They carry a `GENERATED FILE -- DO NOT EDIT` banner, and
`tools/validate.py` fails on any drift between source and copy. Edit `shared/` and re-run the script.

### Checks before committing

```bash
python3 tools/validate.py
```

It verifies: every JSON parses; `plugin.json` and skill frontmatter `name`s match their folders; every
`skills[]` path resolves to a `SKILL.md`; no skill folder is missing from `skills[]`; `marketplace.json` agrees
with each `plugin.json` on `description` and `version`; no dead or plugin-escaping links; skills stay under the
500-line budget; every plugin has a README catalog row; and no materialized file has drifted.

The same check runs in CI on every pull request
([`.github/workflows/validate.yml`](.github/workflows/validate.yml)), against Python 3.9 and 3.13. CI is the
gate — a pull request that fails it does not merge. Running it locally first is still expected.

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

**This is the standard. Decide which level every piece of content belongs to before you write it.**

Skills load in three stages so that having many installed does not flood the context window. Each stage has a
different trigger, a different cost, and — critically — a different **guarantee**.

| Level | What loads | When | Guaranteed? |
| ----- | ---------- | ---- | ----------- |
| 1 | `name` + `description` | Session start, every skill installed | **Yes** — mechanical |
| 2 | The **whole** `SKILL.md` body | The skill activates | Activation is model judgment; the load is mechanical |
| 3 | One file under `references/`, `scripts/`, `assets/` | The model chooses to open or run it | **No** — model judgment throughout |

The single rule that follows from this table: **if it must always apply, it goes in Level 2.** A rule the model
has to decide to go and read is not a rule.

### Level 1 — metadata

Always resident, for every installed skill, whether or not it is ever used. This is the **only** text seen on
every request, and it is the sole input to skill selection — Level 1 *is* the router. See
[Writing the description](#writing-the-description).

Two separate limits apply, and the second is the one that bites first:

- **Per skill:** `description` and `when_to_use` are concatenated and truncated at **1,536 characters**.
  Silent — no error. Put the key use case and any *"use X instead"* disambiguation **first**, because the tail
  is what gets cut.
- **Per collection:** all descriptions share a listing budget of roughly **1% of the model's context window**.
  On overflow, descriptions are dropped **starting with the least-invoked skills** — and a newly added skill
  is by definition least-invoked. The skill's *name* survives; only its description disappears, so it stops
  matching requests while still appearing installed.

That second failure mode is invisible until someone asks why a new skill never fires. It is also the strongest
argument for keeping plugins narrow and separately installable: a user who installs one plugin spends budget on
its skills alone.

Measure it rather than guessing — `/doctor` reports the listing's context cost and its biggest contributors,
and `/context` shows the size after the budget is applied.

### Level 2 — the `SKILL.md` body

On activation the **entire** body loads. Not a summary, not the relevant sections — all of it. And it **stays
in context for the rest of the session**, so every line is a recurring cost, not a one-time one. That is the
real reason for the budget below.

- Keep `SKILL.md` under **~500 lines**. Approaching that means the content belongs in `references/`.
- **Put what matters at the top.** After context compaction a skill is re-attached with only its **first
  ~5,000 tokens** kept, so content at the end is what gets cut. Hard rules, safety constraints, and the output
  contract go early; housekeeping conventions can trail.
- State what to do, not how or why. Narration is pure recurring cost.

### Level 3 — bundled resources

Loaded only if the model opts in, one file at a time. Two kinds live here and they behave **completely
differently**:

- **`references/` are read** — opening one costs its full length in context. Real cost, paid on use. Only put
  detail here that is needed *sometimes*: per-framework variants, API tables, format specs.
- **`scripts/` are executed** — they never enter context at all. Only their output does. A 350-line script
  costs whatever its output costs, and the model cannot misremember logic it never read. Prefer a script over
  a reference whenever the work is deterministic.

Rules:

- **Always leave an explicit pointer.** An unreferenced file is never read. Say when to load it:
  *"Step 1, always — before choosing any framework."*
- For scripts, say so explicitly: *"Run it; you do not need to read it."* Otherwise the model may read the
  source and pay for it needlessly.
- Any reference file over ~300 lines gets a table of contents at the top.
- Scripts can be arbitrarily large.

### Choosing a level

| The content is… | Level | Why |
| --------------- | ----- | --- |
| What the skill does and when to fire | 1 | It is the only thing available at selection time |
| A rule that must always hold | 2, near the top | Level 3 is optional; the tail is truncated on compaction |
| The output contract | 2 | The skill cannot honour a format it did not load |
| Needed only in some branches | 3, `references/` | Keeps the recurring cost off every turn |
| Deterministic and repetitive | 3, `scripts/` | Executes without entering context |

### A caveat on the numbers

The budgets above (1,536 characters, ~1% listing budget, ~5,000-token re-attachment) are Claude Code's
documented behaviour and several are configurable. Other runtimes may differ, and GitHub does not publish
equivalents. Treat them as the tightest known constraints and design to them — a skill that fits here fits
everywhere.

**Being in context is not the same as being obeyed.** No level guarantees compliance. A rule only counts as
verified once a fixture in [`fixtures/`](fixtures/) fails when it is violated.

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
- Declare side effects in `SKILL.md`: network access, package installs, writes outside the working directory,
  and any third-party import a bundled script uses.
- **Bundled scripts are standard library by default.** A third-party import ships only as an optional
  accelerator with a working stdlib fallback, and only if it is named in the allowlist in
  [`.github/instructions/domain/scripts.instructions.md`](.github/instructions/domain/scripts.instructions.md).
  A script that cannot run on a clean machine is a broken skill — there is no install step on the user's side.
- No instructions that try to override the host agent's safety behavior or suppress its confirmations.

## Fixtures

`fixtures/` is a **measurement instrument**, not sample code. Every defect in it is deliberate, and each
scenario asks one question: does the agent **find** the defect, or **accommodate** it?

These rules are for people *authoring* fixtures. They deliberately do **not** live in
`.github/instructions/`: an instruction scoped to `fixtures/**` is injected automatically whenever anything
under that path is touched — including when an agent is *being evaluated* on a scenario. The glob cannot tell
an author from a subject, so any rule placed there contaminates the measurement it is meant to protect.

- **Never repair a fixture** while working on the repository. If it looks broken, it is.
- **Never restate a planted defect** anywhere reachable from a scenario — not in a README, not in a comment,
  not in an instruction file. Naming the vulnerabilities in `04-security` is a partial answer key, and an
  agent that can recite them has not found them.
- `fixtures/EXPECTED.md` is the answer key. It sits one level **above** the scenario folders so that opening
  a single scenario never exposes it. Never move it into one, never reference it from one, and never open it
  in a session that is demonstrating or evaluating a skill.
- **A scenario's own pass condition overrides the "never repair" rule for the agent under test.** Scenario 02
  is passed by correcting the wrong test's expected value — that is the measured behaviour, not a violation.
  The rule binds contributors to this repository, not the skill being evaluated.
- A scenario is only useful if it can **distinguish** correct from incorrect behaviour. Verify the failure is
  real and unique by running it, and state the observed result. Beware operations that commute: an earlier
  version of scenario 02 measured nothing because a 20% discount and a 10% tax produce the same total in
  either order.
- Update `EXPECTED.md` in the same commit. A scenario with a stale answer key is scored wrong.
- `fixtures/04-security/app.py` is genuinely exploitable. Never copy from it, never run it against real data,
  and leave its file-level warning banner intact.

## Checklist

Before opening a PR:

- [ ] `SKILL.md` exists at the skill folder root; frontmatter parses; `name` matches the folder name.
- [ ] `description` states both what it does and when it triggers, and cannot collide with a sibling skill.
- [ ] `description` under 1,536 characters, with the key use case and any disambiguation clause **first**.
- [ ] "When not to use this" section is present and specific.
- [ ] `SKILL.md` under ~500 lines; overflow moved to `references/` **and** pointed at from `SKILL.md`.
- [ ] Hard rules and the output contract sit **near the top** of `SKILL.md`, not in the trailing sections.
- [ ] Every piece of content is at the right [level](#progressive-disclosure): always-applies → Level 2;
      sometimes-needed → `references/`; deterministic → `scripts/`.
- [ ] Every bundled file is referenced from somewhere; no orphans. Scripts say *"run it, do not read it"*.
- [ ] Skill listed in its plugin's `skills` array.
- [ ] `plugin.json` and `marketplace.json` agree on `name`, `description`, `version`; version bumped.
- [ ] Root `README.md` catalog row added or updated.
- [ ] `## Conventions` states rules specific to **this** skill, not generic boilerplate.
- [ ] No links escape the plugin folder; no absolute paths; all JSON parses.
- [ ] Safety rules above hold.
