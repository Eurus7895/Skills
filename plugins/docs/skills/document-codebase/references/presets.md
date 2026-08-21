# Presets

A preset fixes the skeleton: which pages exist, in what order, and which may not be dropped. It says nothing
about what is true — that comes entirely from the verified claims. Two documents built from the same preset
against different repositories share a shape and nothing else.

Pass one with `--preset`. `onboarding` is the default.

## `onboarding`

For someone who has not seen the repository before.

| Page | Contains | Mandatory |
| --- | --- | --- |
| `overview` | What was scanned, at which revision, and the most depended-upon modules with their roles | yes |
| `entry-points` | Files nothing imports that carry a main guard or a conventional launcher name | yes |
| `architecture` | Import edges that cross a directory boundary, each with the line that proves it | yes |
| `modules` | One row per module whose description survived verification | yes |
| `limitations` | Coverage counts, unresolved claims, scanner diagnostics, import-usage caveat | yes |

## `architecture`

Denser, and assumes the reader already knows the domain. Drops the entry-point tour and adds a fan-in ranking.

| Page | Contains | Mandatory |
| --- | --- | --- |
| `overview` | As above | yes |
| `architecture` | Components and the boundaries between them | yes |
| `dependencies` | The top 25 files by fan-in | yes |
| `modules` | As above | yes |
| `limitations` | As above | yes |

## What the model may and may not decide

The agent chooses which modules are in scope (step 3 of `SKILL.md`), what each one's role is, and which
claims support it. It does **not** choose whether the limitations page exists. Every mandatory page is
generated whether or not there is much to put on it, because a document that silently omits its own coverage
section reads exactly like one with nothing to disclose.

A page with no content to show says so in a sentence — "No import crosses a directory boundary in this
repository" — rather than being dropped.

## Adding a preset

Presets live in `PRESETS` in `build_document_model.py`, as `(page_id, title, mandatory)` triples, alongside a
builder function per page id in `BUILDERS`. A new preset that reuses existing page ids needs no new builder.
Keep the `limitations` page mandatory in anything you add.
