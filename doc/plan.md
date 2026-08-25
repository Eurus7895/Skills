# Docs plugin — the work after PR #19

PR #19 delivered PR 3a (context selection and the verified document model) and PR 3b
(diagrams, including the per-package detail views). Three tracks remain. This file is the
plan for all three, in the order they are meant to happen.

Everything here follows the constraints already in force: scripts are authored in
`shared/scripts/` and materialized by `tools/materialize.py`; tests are `tools/test_*.py`,
standard library only, no framework; `SKILL.md` stays under 500 lines.

---

## Decisions taken

| Question | Decision |
| --- | --- |
| Sphinx in CI | **Install it.** Without it the harness ships unverified, exactly as the diagram path did before Graphviz was added |
| MyST renderer | **Build it.** RST is to be dropped in a later phase, so MyST is the successor format, not a second one |
| Author's `index.rst` | **Insert the generated pages into the existing toctree** behind a flag |
| Graphviz | **Not bundled.** See track B for what replaces the dependency |

The MyST decision changes the shape of track A. If MyST were a side format, it could be a
second emitter bolted onto the RST renderer. It is the successor, so the `doc.json` →
markup boundary has to be clean enough that RST can later be deleted without taking
anything else with it. Every helper that RST and MyST both need belongs above the split,
and nothing outside the renderers may assume RST.

---

## Track A — PR 3c: rendering and release quality

Steps 12–18 of the phase plan. Seven commits.

### A1. Fix what a real Sphinx build already finds

Not part of step 12; it is a defect in code already merged to `dev`, found the first time
`sphinx-build -W` was run against the `handbook` preset.

- **`:doc:` targets must be absolute for nested pages.** Sphinx resolves a relative
  `:doc:` against the current document's directory, so from
  `architecture/class_diagrams.rst` the reference `architecture/data_flow` resolves to
  `architecture/architecture/data_flow` and fails with `ref.doc`. Page ids are emitted
  verbatim today, which is correct only for a flat layout.
- **The docutils fallback walks `os.listdir` flat**, so every `.rst` under a subdirectory
  goes unparsed. It must recurse.
- **Separate "markup is broken" from "not wired into a toctree yet."** With the author's
  index kept, generated pages are in no toctree and Sphinx reports `toc.not_included`.
  The pages are fine; the integration is incomplete. Reporting that as `failed` is the
  wrong message, and track A5 is what resolves it properly.

Verification: build both presets with `sphinx-build -W` and get a clean pass on
`onboarding`, and on `handbook` a result that names the toctree gap as a gap rather than
a markup failure.

### A2. Step 12 — `sphinx_support.py`

Extract the harness now living inside `render_docs.py`.

- Detect whether `sphinx-build` is available.
- Run `sphinx-build -W` and capture a structured result.
- **Distinguish the four outcomes the plan requires**, which are currently collapsed into
  one `failed`: missing dependency, invalid markup, broken reference, internal runner
  failure. They imply different next moves, so they cannot share a status.
- Keep the harness independent of the target repository's `conf.py`. Pages are copied to
  a temp tree and built there; this property already exists and must survive the move.
- Add a controlled Sphinx fixture for renderer tests.

Acceptance: a valid minimal page builds with zero warnings; invalid RST fails with the
relevant Sphinx output; a broken internal reference fails and is reported as a broken
reference rather than as bad markup; a missing `sphinx-build` follows the declared
required/optional policy; the harness creates and modifies nothing in the target
documentation configuration.

### A3. Step 13 — the RST renderer, through the harness

- Build every renderer fixture with `-W`.
- Test escaping in headings, prose, inline code, links and table cells.
- `table` and `image` blocks have never been through a Sphinx build. This is the first
  time, and it is where a defect is most likely.

Acceptance: every generated page appears in a toctree; all four block types build with
zero warnings; an unresolved page, claim or image reference fails; identical `doc.json`
produces identical RST.

### A4. Step 14 — the MyST renderer

- `--format myst`, rendering the same `doc.json`.
- Equivalent navigation, and MyST link and escaping rules validated.
- Extend the harness with a `myst-parser` fixture, built with warnings as errors.
- Because RST is to be retired later, factor the shared work above the format split:
  block ordering, reference resolution, figure resolution and the toctree contents are
  format-independent. Only the emitter differs.

Acceptance: the same `doc.json` produces both formats; both build clean; escaping is
tested per format because the rules differ; identical input produces identical output.

### A5. Step 15 — Sphinx project integration

- Detect and reuse an existing configuration.
- `--init-sphinx` as an explicit, non-interactive initialisation with a stated fallback.
- Never create or overwrite `conf.py` without explicit authorisation.
- Never silently turn MyST output into RST.
- **`--wire-toctree`**: insert the generated pages into the author's existing toctree
  rather than only printing what to add. The renderer edits the author's file, so the
  rules are strict: the flag is required, the insertion is idempotent, entries already
  present are left alone, the surrounding content is preserved byte for byte, and a file
  the parser does not understand is refused rather than rewritten.

Acceptance: an existing `conf.py` is never touched without the flag; wiring twice
produces the same file as wiring once; a hand-written index keeps everything it had; the
toctree gap from A1 disappears once wiring has run.

### A6. Step 16 — `quality_docs.py` and `generation-report.json`

- Validate schemas and references; enforce preset coverage; enforce class-graph and
  diagram structural coverage.
- Ingest `visual-findings.json` **without delegating pass/fail to the model**; apply the
  critical/major/minor policy and the visual-review availability policy.
- Aggregate every stage's result into `generation-report.json` with stable exit codes.
- Last, because it consumes the output of every stage; writing it earlier means rewriting
  it as the stages settle.

### A7. Steps 17 and 18 — metadata and release

`SKILL.md`, plugin README, `plugin.json`, marketplace manifest, root catalog,
`shared.manifest`. Advertise only what is implemented and invoked. Version, then release
through `dev` before `main`.

**Branch:** `feat/docs-sphinx-and-quality-gate`, cut from `origin/dev` at `74c1435`.

---

## Track B — a layout engine that needs no external binary

Today a machine without Graphviz gets no diagram at all. Bundling Graphviz binaries was
considered and rejected: a DLL is Windows-only so it would mean five or six platform
builds; `dot` loads its layout engines as plugins through `libltdl`, driven by a
`config6a` file that says of itself *"generated by `dot -c` at time of install"* and whose
absolute paths do not survive being copied to another machine; Graphviz is EPL-1.0, so
redistribution carries notice obligations; and a marketplace of text files that every user
clones is the wrong place for executables.

The dependency is narrower than it looks. Graphviz does exactly one thing here: it turns a
DOT document into coordinates. Normalisation, the Y-axis flip, `diagram-model.json`, the
Draw.io and SVG emitters, previews, `validate_diagrams.py`, layout patches and the detail
views are all already ours.

**Shape.** One internal contract with two implementations:

```
layout(graph, spec, sizes) -> nodes, containers, edges, bounds
```

`graphviz` is the existing path. `builtin` is pure Python, in `shared/scripts/`, no new
dependency and nothing to install. `diagram-model.json` already records `layout_engine`,
so which one ran is visible in the artefact.

**What `builtin` has to do**, in order:

1. Rank by longest path over inheritance and composition edges, ignoring back edges to
   break cycles.
2. Group by container: classes of a module adjacent, modules of a package adjacent. This
   is the hard part and the part Graphviz is best at.
3. Order within a rank by a few barycentre sweeps, to reduce crossings.
4. Assign x by packing the widths already computed by `size_for`, plus padding.
5. Container boxes: the bounding box of the children, plus room for the label.
6. Edges as polylines between box edges. Obstacle-avoiding routing is where quality falls
   furthest short of Graphviz.
7. Bounds.

Graphviz stays the preferred engine where it is installed; it lays out better.

**A checker that already exists becomes the acceptance test.** `validate_diagrams.py`
`G004` forbids two non-container boxes overlapping, so any layout that stacks boxes fails
immediately without a new rule being written. Output must also be deterministic.

**Consequence to accept up front:** a hand-written layout is less tidy than Graphviz, so
the visual review loop moves from optional to necessary. That loop has never run as a
complete cycle, which makes it part of this track rather than a separate concern.

---

## Track C — the debts

Neither of these is a missing feature. They are things that exist and that nobody has yet
shown to work.

### C1. Never run on a large repository

The phase plan says outright that this repository is only a smoke test: its dependency
graph is too small to evaluate against. So every mechanism built for scale has never once
been reached — the 60-class density threshold, the packet hard limit and its partitioning,
the top-25 fan-in budget (there are 33 units here in total), import cycles, deep
inheritance, nested packages.

The tests cover those branches with data written to fit them. Nothing real has ever
disagreed. The precedent is the preview that was silently clipping the canvas: the SVG was
correct, coverage passed, both formats agreed, and the picture a reviewer would have
studied was missing a class. Only looking at it found that.

Do: run the whole pipeline against a few hundred files of real open-source Python, and see
what breaks, what is slow, and what turns out to be pointless.

### C2. The visual review loop has never run a full cycle

Four stages: render a preview, have a model look at the image and write findings and a
patch, apply the patch, rerender and re-run every structural check.

Stage one has run for real, and it is what found the clipping defect. Stages three and
four have tests, but driven by patches written by hand, not derived from looking at an
image. The four stages have never run end to end with a patch that came from a picture.

So the central question of the loop is still open: shown a real class diagram, does a
model say anything useful? Either answer matters — it finds genuine overlap and the patch
improves the picture, or it invents problems, the patch makes things worse, and the
two-attempt stop condition gets its first real test. `apply_layout_patch.py` exists
entirely to serve this loop.

This depends on C1 for a diagram dense enough to have something worth fixing. The one in
this repository is too sparse to complain about.

---

## Order

Track A first: it is on the path to a release, and `dev` → `main` is waiting on it.

Track B is independent and blocks nobody, **unless** a target machine that cannot install
Graphviz is a live problem — in which case B goes first. It changes what arrives sooner,
not the total.

Track C last, and C2 after C1, because C2 needs the dense real diagram that C1 produces.
