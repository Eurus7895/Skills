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

## `outside-in`

What the thing is, then how to run it, then how it is built, then the inventory. Every other preset here
opens on structure — the dependency graph, the entry points — which answers the question a reader has
fourth. This is also the only preset that consumes the architecture and operations analyses, so it is the
one to use when steps 6b and 6c were done.

| Page | Contains | Mandatory |
| --- | --- | --- |
| `overview` | What was scanned, in what languages, at what revision, and the ways in | yes |
| `getting-started` | Install, build, test and run procedures with their quoted commands, plus declared requirements | yes |
| `conventions` | **Named, never written** — a team's conventions are not in a dependency graph | no |
| `architecture` | Import edges that cross a directory boundary, each with the line that proves it | yes |
| `components` | The components the architecture analysis names, what each holds, and what crosses between them | yes |
| `rationale` | Why each boundary is where it is, and the ones nobody recorded a reason for | yes |
| `flows` | The traced chains, or the stated reason there are none | yes |
| `operations` | Configure, deploy, release and observe procedures | yes |
| `reference` | One row per module whose description survived verification | yes |

Pass `--architecture` and `--operations` alongside `--analysis` and `--flows`. Without them the pages still
build and say the analysis was not supplied — a visibly thinner document, never a silently thinner one.

**Two rules hold this preset together**, and both are checked before `doc.json` is written:

- **A required topic must live on a page a reader would look on for it.** `interaction` belongs to
  `components` and `rationale` to `rationale`; a preset that homed either on the module reference would
  satisfy the coverage check while filing the system's shape under a list of files, and is rejected.
- **A mandatory page must have something to say.** It has to cite a claim or statement, render structured
  material an input actually holds, or carry a block marked as an *absence* — "nothing here, and why". Bare
  prose satisfies none of those and fails the build. The first version of this preset's overview passed a
  weaker version of the rule with two uncited sentences, a file count and a list of entry points, which is
  not an answer to "what is this"; requiring the marker is what closed that.

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

## Markup formats

`render_docs.py --format` emits `rst` or `myst` from the same `doc.json`. The document model carries no
markup, so the two differ only in the emitter: the same pages, the same order, the same references, the same
figures.

RST is the default and is to be retired. Everything both formats need — block ordering, reference resolution,
figure resolution, source-root addressing, the toctree contents, the rule that keeps an author's index — lives
above the split, so retiring RST is deleting one class and one table entry rather than untangling a renderer.

Escaping is the one place they genuinely disagree, because the same character means different things: `|x|` is
a substitution in RST and a column separator in Markdown, `_y_` is a reference in RST and emphasis in
Markdown. Each emitter escapes for its own format, and both are tested by building the result rather than by
reading it.

**MyST needs `myst_parser` enabled in the project it lands in.** Without it Sphinx does not read `.md` at all:
the pages are written, the toctree names them, and the build fails over documents it cannot parse. A fixture
with the extension enabled will never show this, so the check belongs against the real project.

## Adding a preset

Presets live in `PRESETS` in `build_document_model.py`, as `(page_id, title, mandatory, builder)` rows.
`builder` names an entry in `BUILDERS`, so a new preset that reuses existing builders needs no new code — the
page id and the builder are separate, which is how `architecture/data_flow` is filled by the `flows` builder.

`builder` may be `None`. That declares a page the pipeline cannot fill: it is listed in `authored_pages`,
reported as not generated, and never written. Prefer `None` over a builder that would emit a placeholder —
an empty section that looks generated is worse than a page the report names as missing.

Keep the `limitations` page mandatory in anything that generates prose from claims.
