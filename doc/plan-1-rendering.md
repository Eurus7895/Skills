# Plan 1 — rendering: Sphinx, RST and MyST

Steps 12–15 of the phase plan. Five commits, one branch, one pull request. This half is
releasable on its own: it changes how a document is rendered and checked, and touches
nothing in the diagram pipeline.

Plan 2 (`doc/plan-2-layout-and-release.md`) carries the layout engine, the quality gate
and the release, and depends on this one being merged first.

Constraints already in force: scripts are authored in `shared/scripts/` and materialized
by `tools/materialize.py`; tests are `tools/test_*.py`, standard library only, no
framework; `SKILL.md` stays under 500 lines.

## Decisions taken

| Question | Decision |
| --- | --- |
| Sphinx in CI | **Install it.** Without it the harness ships unverified, exactly as the diagram path did before Graphviz was added |
| MyST renderer | **Build it.** RST is to be dropped in a later phase, so MyST is the successor format, not a second one |
| Author's `index.rst` | **Insert the generated pages into the existing toctree** behind a flag |

The MyST decision changes the shape of this plan. If MyST were a side format, it could be
a second emitter bolted onto the RST renderer. It is the successor, so the `doc.json` →
markup boundary has to be clean enough that RST can later be deleted without taking
anything else with it. Every helper that RST and MyST both need belongs above the split,
and nothing outside the renderers may assume RST.

---

## Commits

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

---

## Branch

`feat/docs-sphinx-and-quality-gate`, cut from `origin/dev` at `74c1435`. Pull request #20.

## What this plan does not do

The layout engine, `quality_docs.py`, the version bump and the release are plan 2. This
plan can be released on its own as a patch version if the rendering work is wanted before
the layout engine is ready; that is a decision to take when A5 lands, not now.
