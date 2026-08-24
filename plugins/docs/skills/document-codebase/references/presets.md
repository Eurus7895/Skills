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

## `handbook`

The layout a delivered manual usually has: `getting_started/`, `architecture/`, `usage/`, `development/`,
`appendix/`, and a changelog. Use it when the repository already has a documentation tree in that shape and
you want the generated pages to land in it rather than beside it.

**This preset fills four pages and writes none of the others.**

| Page | Filled from | |
| --- | --- | --- |
| `architecture/key_modules` | cross-boundary import edges | generated |
| `architecture/class_diagrams` | the class graph and its rendered views | generated |
| `architecture/data_flow` | calls verified at their call site | generated |
| `development/module_reference` | one row per verified module description | generated |
| everything else | — | **authored** |

An installation guide, a quick start, a contribution guide, a changelog, a glossary, an FAQ: none of these
follow from a dependency graph. They are things a person knows. Generating them from "verified repository
evidence" is not possible, and generating them anyway would produce exactly the unverifiable prose the rest of
this skill exists to prevent — so the pipeline names them, reports them as not generated, and leaves the files
alone.

That is what makes the preset useful with an existing tree: **you supply the real document, and the skill
updates it.** For an authored page, read what is there, check its statements against the verified claims, and
change only what the evidence contradicts or completes — same citation rule, same status boundary. A page you
cannot check against evidence, you leave.

`index.rst` is the author's too. The renderer writes one only when the output directory has none; where an
index already exists it is kept and the run says so, because that file lists pages this run knows nothing
about. `--replace-index` overrides that, and then the toctree is the generated one.

Page ids in this preset contain `/`, and a page id is its path under the output directory.

## What the model may and may not decide

The agent chooses which modules are in scope (step 3 of `SKILL.md`), what each one's role is, and which
claims support it. It does **not** choose whether the limitations page exists. Every mandatory page is
generated whether or not there is much to put on it, because a document that silently omits its own coverage
section reads exactly like one with nothing to disclose.

A page with no content to show says so in a sentence — "No import crosses a directory boundary in this
repository" — rather than being dropped.

## Adding a preset

Presets live in `PRESETS` in `build_document_model.py`, as `(page_id, title, mandatory, builder)` rows.
`builder` names an entry in `BUILDERS`, so a new preset that reuses existing builders needs no new code — the
page id and the builder are separate, which is how `architecture/data_flow` is filled by the `flows` builder.

`builder` may be `None`. That declares a page the pipeline cannot fill: it is listed in `authored_pages`,
reported as not generated, and never written. Prefer `None` over a builder that would emit a placeholder —
an empty section that looks generated is worse than a page the report names as missing.

Keep the `limitations` page mandatory in anything that generates prose from claims.
