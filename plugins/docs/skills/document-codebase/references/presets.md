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
| `flows` | Calls verified at their call site, never chains assembled from import edges | yes |
| `modules` | One row per module whose description survived verification | yes |
| `navigation` | Directory groupings, the busiest file in each, and where to start reading | yes |
| `limitations` | Coverage counts, unresolved claims, scanner diagnostics, import-usage caveat | yes |

## `architecture`

Denser, and assumes the reader already knows the domain. Drops the entry-point tour and the module
inventory, and adds a fan-in ranking and the inheritance forest.

| Page | Contains | Mandatory |
| --- | --- | --- |
| `overview` | As above | yes |
| `architecture` | Components and the boundaries between them | yes |
| `dependencies` | The top 25 files by fan-in | yes |
| `class-views` | Every class that names a base, with the base linked only where it resolved | yes |
| `flows` | As above | yes |
| `limitations` | As above | yes |

**`architecture` has no module reference on purpose.** A reader who already knows the domain wants the shape,
not the inventory; someone who wants a file-by-file list should generate `onboarding` instead.

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
