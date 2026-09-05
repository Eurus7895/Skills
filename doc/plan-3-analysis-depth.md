# Plan 3 — the analysis half

Nine commits. This is `documentation-analysis-implementation-plan.md` reconciled with what
the repository actually contains, and it replaces **A8** in `doc/plan-2-layout-and-release.md`.
`A8b` (run it on a real repository) and `A9` (the release) survive and move to the end.

## Why the source plan needed reconciling

Its diagnosis is right, and one sentence carries it: **`structure.json` is evidence input,
not analysis, and must not independently satisfy semantic coverage.** Everything worth
keeping follows from that — `analysis_mode`, forbidding `passed` on `derived_only`, the
four-way rationale status, and the eight negative tests, which are the best part of the
document.

What it needed was a look at the repository. Comparing it against `be4a420` gives one
result that changes the shape of the work:

> Everything already built is the delivery half. Everything missing is the analysis half.

Scanning, indexing, context packets, verification, the document model, RST, MyST, Sphinx,
PlantUML, toctree wiring — done. That is a complete distribution system for a kind of
content the pipeline cannot yet produce. It is also exactly why a run can end in
`derived_only` with every check green: the pipe is clear, and the only thing flowing
through it is `structure.json` in prose.

Of the source plan's eleven phases, three are done, four are half done, four are absent —
and the four absent ones are the ones with no mechanical right answer to compare against.

## Corrections applied

| Source plan | This plan | Why |
| --- | --- | --- |
| Phase 1: remove Graphviz and draw.io | Dropped | Done in PR #23 |
| Phase 2: compute source hashes | Dropped | `structure.json` v2 already carries per-file `source_hash`, the run carries `index_hash`, and stale evidence already lands on `V005` / `needs_context`. The Freshness row of its own quality table is finished |
| Replace claims with analysis statements | **Layer, don't replace** | A claim can be *contradicted* by the source; a statement can only be checked for evidence validity. Keeping claims as the falsifiable floor and adding statements as the ceiling is strictly stronger than either alone |
| One analysis record per in-scope module | Per module **in the fan-in budget** | `SKILL.md` step 3 caps dispatch at the top 25 by fan-in plus entry points, deliberately. Analysing every module removes the cost ceiling. Modules outside the budget are `derived_only` **by design**, counted separately, and never drag the mode down |
| `partial` when *some* module is derived-only, or *some* rationale is inferred | Thresholds, not existence tests | Both conditions are true of every real repository, so the status would never change and would say nothing |
| `confidence: high` on every statement | Dropped | Nothing can contradict a model's self-assessment. `status` is the part that carries information |
| Phase 5 must produce an end-to-end flow whenever an entry point exists | Flows are **best-effort** | Tracing ordered interactions with evidence per step, through dynamic dispatch, is a different order of difficulty from module responsibility. A hard requirement here forces fabrication — the one thing the plan exists to prevent |
| `documentation-model.json` | `doc.json` format_version 2 | A new file discards presets, which already encode which pages must exist |
| Quality gates at Phase 9, last | **First** | The gate is the only instrument that can tell whether the expansion after it improved anything |
| "Detect generic statements" / "detect architecture that mirrors directories" | Given a method | These two are the only checks that actually close the failure mode. Named without a method, they ship as stubs |

## The inversion

Build the instrument, then build what it measures. Commits **C1–C4** close the failure
mode and change no documentation content at all; a run that was `derived_only` yesterday
still is, and now says so. **C5–C8** are the expansion, and each one can be judged by
whether the numbers from C3 move.

## Artifact map

| Source plan | Here |
| --- | --- |
| `repository-inventory.json` | `structure.json` grows an `assets` section (C5). `scan_repo.py` already walks the tree and already *excludes* non-source files; a second walker would disagree with the first |
| `structure.json` | Unchanged in role |
| `module-analysis.jsonl` | New, beside `fragments.jsonl` and `claims.jsonl` (C2) |
| `architecture-analysis.json` | New (C6) |
| `flow-analysis.json`, `operations-analysis.json` | New, best-effort (C7) |
| `documentation-model.json` | `doc.json` v2 (C8) |
| `generation-report.json` | New (C3) |

## `module-analysis.jsonl` — analysis_version 1

One row per module in `units.txt`. Flat, one object per line, like every other `.jsonl`
here.

```json
{"path": "src/api.py", "source_hash": "sha256:…", "index_hash": "sha256:…",
 "role": "Exposes the HTTP boundary and delegates to application services.",
 "statements": [
   {"id": "api-s1", "kind": "responsibility", "status": "observed",
    "text": "Validates the request body before any service call, so a malformed payload never reaches the store.",
    "evidence": [{"path": "src/api.py", "line_start": 34, "line_end": 51, "symbol": "create_order"}]}]}
```

`kind` is `responsibility`, `state`, `interface`, `interaction`, `failure`, or `rationale`.
`status` is `declared`, `observed`, `inferred`, or `unknown`.

**Two vocabularies, on purpose.** A claim keeps its six statuses because a claim is about
structure and the source can prove it wrong. A statement is about meaning; nothing can
prove it wrong, so its statuses record *where the reading came from* instead. Collapsing
them would put an interpretation and a verified fact in the same column.

`role` stays what it is today: a navigation label, not the analysis.

## Thresholds

A module counts as **analysed** when it has at least one statement that

- carries at least one evidence record whose file exists, whose hash matches, whose line
  range is inside the file, and whose `symbol` (if given) is in that file's symbol table;
- survives detector A below.

Let `coverage = analysed / |units.txt|`.

```text
analysis_mode = per_module    coverage >= 0.90
                partial       0.50 <= coverage < 0.90
                derived_only  coverage < 0.50, or no statement of any kind exists
```

Modules outside `units.txt` are reported as `out_of_budget` with their own count. They are
not failures; the budget is the product decision that makes a run finite.

```text
status = failed           a required artifact is missing or invalid; evidence is
                          stale; a required diagram is absent; the Sphinx build fails
         review_required  a bounded model pass ran out of attempts, tokens or time
                          before it could decide. Nothing was learned; a person has to
                          look. Never reported as either of the two below
         partial          analysis_mode is partial; or detector B reports agreement in
                          [0.85, 0.95); or a mandatory page has no covering statement
         passed           analysis_mode is per_module, evidence validity is 1.0, both
                          detectors pass, every mandatory page is covered, Sphinx did
                          not fail
```

`passed` is forbidden when `analysis_mode` is `derived_only`, whatever else holds.

`review_required` is the same distinction `sphinx_support.py` already draws between
`skipped` and `runner_failure`: a check that could not run is not a check that passed, and
it is not a defect in what it was pointed at either. Every commit below that spends a model
on judgement — `C6`, `C7`, `C8b` — carries a **maximum number of attempts, a token ceiling
and a timeout**, and exhausting any of them yields this status rather than a guess.

**Adopting the gate is staged, not switched on.** `--require` already spells this: run at
`--require failed` to observe the numbers without blocking anything, move to the default
`partial` once a repository has a baseline, and only then to `passed`. A gate turned to its
strictest setting on its first day fails honest documents and gets disabled.

## Detector A — a statement that describes nothing

Three rules, ascending in value, all standard library.

1. **Exact repetition.** Normalise (lowercase, strip punctuation, collapse whitespace). The
   same text on two modules describes neither. Hard failure.
2. **Near repetition.** Token Jaccard ≥ 0.8 between statements on different modules. Flag
   each; if more than 20% of statements are flagged, the set is a template.
3. **Anchoring.** A statement must name at least one identifier the module defines or
   imports — taken from that file's `symbols` and its imports' `bindings`, both already in
   `structure.json`. "This module provides functionality for the application" names
   nothing in the file it claims to describe.

Rule 3 does not error. A statement that fails it simply does not count towards `analysed`,
so a run of anchorless prose degrades into `derived_only` rather than into an argument
about whether one sentence was too abstract.

## Detector B — architecture that is the directory tree with new labels

Build two partitions of the same module set: `P_arch` from `architecture-analysis.json`
(component → modules) and `P_dir` from the paths (parent directory → modules).

- **Identical partition and each component's name normalising to its directory's name** →
  hard failure. Nothing was merged, nothing was split, nothing was renamed: no synthesis
  happened.
- Otherwise compute pair agreement (the Rand index: the fraction of module pairs the two
  partitions classify the same way). `>= 0.95` → failure. `[0.85, 0.95)` → `partial` with
  the finding reported.

A repository may genuinely be organised the way its architecture is, so the middle band is
reported rather than fatal — but a synthesis that renamed nothing and moved nothing is not
evidence of that, it is absence of work.

Two things the rules above do not settle, decided here rather than in the code:

**A tidy repository still fails at `>= 0.95`.** Pair agreement cannot tell "lazy" from
"correct, because the layout already matches". Rather than soften the threshold — which
would hand back the escape hatch the detector exists to close — the report carries a second
number beside it: the fraction of components that hold something a path cannot give, being
a rationale of any status, a named external system, or membership spanning more than one
directory. A maintainer reading *agreement 0.97, independent content 0.9* can see the
difference the index cannot. If real repositories trip this, the threshold is what to
revisit, and the number to revisit it with is already there.

**Below two directories or two components there is no partition to compare.** The Rand
index is 1.0 by construction on a single group, which would fail every small repository for
being small. That case reports `not_applicable` with the count that made it so — not a pass,
and not a failure either.

## Commits

### C1. Make the shortcut visible before fixing it

`tests/contracts/` gains a fixture repository with layers, a CLI entry point, a CI
workflow, and no stated rationale. A test takes the shortcut deliberately — claims derived
from the index and nothing else — and asserts **that nothing notices**: identical prose on
every module goes unchallenged, no artifact reports an analysis mode, and non-source
evidence is not in the index at all. Staleness is exercised by editing a file in a copy of
the fixture after the scan, so there is no second tree to keep in step with the first.

It is written as a **passing** test, not a failing one. A suite that stays red until some
later commit lands teaches everyone to stop reading it, and this repository keeps CI green.
Each assertion that a later commit will invert carries a comment naming that commit, so the
lines to change are found by reading rather than by watching what breaks.

*Done when* the characterisation runs green, every inverting assertion is marked, and the
fixture is held to its shape by `tools/test_contracts.py` like every other contract.

### C2. `module-analysis.jsonl` and `validate_analysis.py`

The schema above, and the script that holds rows to it: evidence validity, anchoring,
duplicate detection, `index_hash` freshness. Claims and fragments are untouched.

*Done when* a row with an invalid line range, a stale hash, a missing symbol, or text
repeated across modules is refused with a distinct finding code for each, and a valid row
passes.

### C3. `quality_docs.py` and `generation-report.json`

The report the source plan specifies at §6.8, with the thresholds and detector A above,
`analysis_mode`, the `out_of_budget` bucket, and the statement mix by kind and status.
Replaces A8 in plan 2.

*Done when* a derived-only run reports `derived_only` and cannot return `passed`, and a run
with real statements reports `per_module` — both proven on the C1 fixtures.

### C4. Say it in the skill

`SKILL.md` step 4 currently reads as though the model hand-writes structural claims, and
shows an `imports` claim as its example. Rewrite: structural claims are derived by script,
the model budget buys statements — responsibility, state, interaction, failure, rationale.
Step 3 keeps the fan-in budget and states that everything outside it is `derived_only` by
design and covered in one line each.

*Done when* the documented workflow and `quality_docs.py` describe the same run, and the
end-to-end fixture run reports a mode that matches what actually happened.

**The failure mode is closed here.** Everything below is expansion, and each commit is
judged by whether the C3 numbers move.

### C8a. The analysis reaches the page — taken before C5

Done out of order, and the reason is worth recording. After C4 the pages were still
generic, and reading the generated RST said why: `build_document_model.py` did not mention
`module-analysis.jsonl` anywhere. Step 4 wrote the per-module reading, `quality_docs.py`
counted it, and the document was then built from claims alone — so every page said
structural things, and structural things read as generic however well they are phrased.
The Flows page rendered its empty branch, because a flow needs a `calls` claim verified at
its call site and nothing derives one.

C5, C6 and C7 all add *more* material to the front of a pipeline that was dropping the
material it already had. Wiring it up first makes each of them visible when it lands
instead of accumulating at the input.

So: `doc.json` v2 with `covers` and `analysis_ids` per page, statements rendered under
their own section headings, the statement status boundary enforced the way the claim one
already was — `declared` and `observed` stated, `inferred` hedged in the sentence,
`unknown` listed in Limitations as a question — and `coverage_by_section` reporting a
denominator per question. A statement kind no page covers fails the build, which is the
original defect turned into a check.

*Done when* a statement written in step 4 appears on a page, an `unknown` cannot reach
prose, a kind covered by no page fails, a page whose blocks are all headings and links
fails, v1 documents still render, and a run without `--analysis` builds the old document
while saying why it is thin.

What is left of C8 after this: the outside-in preset, which needs C5–C7's material before
its pages have anything to hold.

### C5. Evidence that is not source code

`scan_repo.py` records the files it currently skips — README, packaging manifests, CI
workflows, contribution and release files, configuration and examples — with `kind`,
`source_hash` and nothing else. No analysis, no parsing: availability only.

*Done when* the index names them, hashes are deterministic, and `structure.json` v3 still
loads everywhere v2 did.

**Done.** Two defects surfaced only by running it twice, neither visible by reading:

- A scan indexed its own output. `.docs-build/structure.json` is a `.json` file inside the
  repository, so the second scan hashed the first scan's artifacts and `index_hash` changed
  on a tree that had not changed — quietly invalidating every fragment from the run before.
  The directory holding `--out` is now excluded when it sits inside the repository, and
  `.docs-build/` is skipped outright.
- The fallback walker skipped every dot-directory, so `.github/workflows/` was invisible
  whenever `git ls-files` could not answer. The same tree scanned differently depending on
  whether it was a git checkout, and nothing downstream could see or explain the difference.

Assets enter `index_hash`, so editing a README forces a rescan. That is the intended cost:
a run cites an asset exactly where it could not derive the answer, so a stale asset citation
is the one kind nothing downstream would catch.

### C6. Architecture synthesis

`architecture-analysis.json`: components, layers, boundaries, external systems, and
rationale, every item carrying a status, evidence, and the module-analysis statement ids it
was built from. Detector B lands in `quality_docs.py` with it.

*Done when* every component links to contributing modules, every relationship to structural
or behavioural evidence, every inferred rationale is labelled, and a synthesis that is the
directory tree fails.

Coverage grows a denominator per subject here, not one number for the run: components with
contributing modules, relationships with evidence, entry points reached by a flow, boundaries
with a rationale of any status. A single percentage hides which of them is empty, and empty
is the interesting case.

**Done**, less the flow denominator, which has nothing to count until C7 exists. Two notes
for whoever reads this next:

- `detector_b` takes only the architecture. It was written taking the index as well and
  never read it — the question "is this the directory tree" is answerable from the
  component-to-modules map alone, and the parameter was doing nothing but implying
  otherwise.
- The band is coarser than it looks on a small repository. Moving one module out of its
  directory's component scores 0.8 on a seven-module fixture and 0.9 on a twenty-module
  one, so a test that means to exercise `[0.85, 0.95)` has to be built to size rather than
  taken from whatever fixture is to hand.

### C7. Flows and operations, best-effort

`flow-analysis.json` and `operations-analysis.json`, plus a PlantUML sequence diagram
generated from the former. Both are optional outputs: a repository that yields no traceable
flow gets that stated in the limitations, never a flow assembled from import edges. The
existing rule holds — call chains are built from calls verified at their call site, and
from nothing else.

*Done when* a flow with a broken step is refused, an absent flow is reported as absent, and
the sequence diagram is validated against the flow the way class diagrams are validated
against the class graph.

**Done.** Four notes for whoever reads this next:

- **The "best-effort" caveat is much larger than it looks, and it is the honest finding of
  this step.** `verify_doc.py` verifies a call when the cited line holds a call by that
  name *and* the name was bound by an import from the callee's file. Ordinary
  object-oriented code does not satisfy that: `self.service.record(...)` reaches its
  target through an instance attribute, and no import binds `record`. So on most real
  repositories there are no verified calls and therefore no steps, and `absent` is the
  correct output. The alternative — assembling chains from import edges — is the exact
  substitution this plan exists to prevent, so the rule stands and the caveat is stated on
  the page instead. `tests/contracts/flow-repo` exists because the layered fixture cannot
  produce a single traceable hop.
- **Binding a citation to its subject is the check that carries the weight**, in both new
  validators. A step that names any verified call inherits its standing without being that
  call; the same hole was found in C6's `statement_ids` during review. Worth checking for
  wherever an id crosses between two files.
- **Order is the claim.** Every hop of a shuffled chain validates individually, so
  continuity (`F004`) and message order in the diagram are separate checks from evidence.
- The operations analogue of "read at the call site" is the literal quote: a `command`
  must appear character for character in the lines it cites. `O008` — the file changed
  since the scan — has to be kept apart from `O006`, or a stale tree produces confident
  false failures.

The operations *page* is not here; C8's outside-in preset is where it lands. C7 produced
the artefact, the validator and the gate counters, and the flows page now renders traced
chains via `build_document_model.py --flows`.

### C8. Outside-in documentation model

`doc.json` v2 with `covers` and `analysis_ids` per page, checked in both directions: every
mandatory topic has a page, and no page exists without something to say. A new preset lays
out the outside-in hierarchy — product overview, getting started, conventions,
architecture, rationale, components, flows, operations, reference — filled from C5–C7. RST
and MyST rendering do not change.

*Done when* a reference page cannot satisfy an architecture requirement, a page with no
covering statement fails, the existing presets still render, and coverage reports a
denominator per required section rather than one figure for the tree.

**Done.** Three notes:

- **`architecture-analysis.json` had no reader.** C6 built it, `validate_architecture.py`
  checked it and Detector B judged whether it was a rename — and then the document went
  on describing the import graph, because nothing wired the synthesis into
  `build_document_model.py`. The same was true of `operations-analysis.json` after C7.
  Both were validated artefacts nobody rendered. Worth checking, for any artefact this
  plan adds, that something downstream actually consumes it; validation is not use.
- The two rules are properties of a *preset*, not of a document, so the only way to
  exercise them is to construct a bad preset. The tests patch `PRESET_COVERS` and
  `BUILDERS` in process and call `validate` directly. A preset that homed `interaction`
  on the module reference would otherwise satisfy every coverage check while filing the
  system's shape under a list of files.
- Builders now take an `extra` mapping rather than a positional parameter each. Three
  optional artefacts arrived in two commits; a fourth would have been a fourth signature
  change across ten lambdas.

`conventions` is in the preset and deliberately unfilled — a team's conventions are not
in a dependency graph. It is named so the skill updates it and the report can say it was
not generated, exactly as `handbook` treats its authored pages.

### C8b. The prose may not say more than the analysis

Everything up to here checks that a statement had evidence. Nothing checks that the
**sentence a reader actually sees** still says what the statement said. Between
`module-analysis.jsonl` and a rendered page sits a rewrite, and a rewrite is where a
relationship gets promoted: `calls` becomes *owns*, `imports` becomes *depends on*, an
`inferred` rationale loses its hedge and becomes the reason the boundary exists.

Deterministic first, and it goes a long way: a table of the words each relationship may be
rendered with, and a rule that a page may not use a stronger one than the claim or statement
behind it carries. A page citing an `inferred` or `unknown` statement may not assert. Only
what survives those rules goes to a bounded model pass, under the budgets above.

*Done when* a seeded contradiction fails — a page saying *owns* over a `calls` claim, a page
asserting a rationale recorded as `unknown` — the honest fixture passes, and exhausting the
budget returns `review_required` rather than a verdict.

**Done**, and the limits are worth stating plainly because the check is easy to overrate.

- **The verb ladder only reaches blocks that carry a citation.** On the outside-in preset
  that is 5 of 22 blocks: the components, rationale, flows and operations tables are
  rendered mechanically from their analyses and record no `claim_refs` or `analysis_refs`.
  That is defensible — a mechanical render is not a rewrite, and there is nothing to have
  overstated — but it means rule 1 is a check on *statement-derived prose*, not on the
  document. Uncited blocks are reported as `P005` advisory rather than quietly skipped.
- **Rule 2 reaches those tables, and does it by substring.** The renderer prefixes a hedge
  to the analysis's own sentence, so dropping the hedge leaves that sentence bare and the
  match finds it. A *rewritten* sentence escapes. That is the model pass's job, and saying
  so is better than implying the deterministic pass is tighter than it is.
- **`block_text` has to include table column headers.** Leaving them out made the rationale
  page's "The question nobody answered" table read as a set of assertions — a false
  positive on the one page written to be honest about not knowing. A checker that fails the
  honest fixture gets switched off, so this was the bug most worth catching.

`review_required` is now a real status in `quality_docs.py`, ranked below `partial` and
above `failed`: it can never be reported as a pass, and a real defect still outranks "could
not tell". The model pass itself is not run by the script — the agent runs it and writes
verdicts to a JSONL — which is the only shape that fits a pipeline whose model is the
caller.

SKILL.md is at its 500-line ceiling with nothing left to compress. The step 6 finding-to-
action table moved to `references/schemas.md` to make room for step 8b. C9 has none.

### C9. A8b, then A9

Run the whole thing on a real repository (plan 2's A8b), read the output as a reader
rather than as a checker, then the release. Unchanged from plan 2, and still not to be
started without saying so first.

## The second source plan, and what came out of it

`architecture-documentation-implementation-plan.md` proposed twelve work packages over the
same pipeline. Six of them describe work already done — the baseline (`C1`), versioned
schemas, analysis as an artifact (`C2`), the `.puml`-to-analysis link (PR #23), the manifest
and the evidence checks (`C3`). Three do not apply, and the reason is the same for all
three: **it was written for a system that runs, and this is a set of scripts an agent runs
by hand.** There is no CI job that generates documentation for a repository, no publication
step, and no pipeline service for two triggers to share. `.github/workflows/validate.yml`
checks this marketplace, nothing else. A reviewer approval gate needs something to gate.

`C8b` above is its one genuinely missing idea, and it is a good one.

Refused, with the reason:

| Proposal | Why not |
| --- | --- |
| Visual validation with a layout loop | Removed on purpose in PR #23. PlantUML owns layout, and the rasterizer it needs is not on most machines |
| An `evidence.json` table with its own ids | Evidence already travels inside the claim or statement that rests on it. A second id space is a second thing to keep in step, bought for orphan detection |
| A `documentation-output/` tree | `.docs-build/` for intermediates and `docs/` for pages is published in `SKILL.md`. Breaking that buys a different arrangement, not a better one |
| A CI trigger and an approval gate | No substrate. When this should run inside another repository's CI, that is its own plan, and it starts from what runs it rather than from what it emits |

## Out of scope, stated once

- **Design intent that the repository does not record.** `unknown` is a supported answer and
  the renderer must not promote it.
- **Rationale from issue trackers.** The source plan lists "issue text included in the
  repository" under `declared`; issues are not in the repository, so that branch would never
  fire.
- **Deployment behaviour** beyond what CI workflow files state.

## Branch

This document travels with the commits it plans rather than on a branch of its own: a plan
merged ahead of the work describes a repository that does not exist yet, and one merged
behind it is a record. `C1` through `C4` landed with it in PR #24, which is where the
failure mode was closed. `C5` onward follow one commit at a time from `origin/dev`, per
`AGENTS.md`, and each is judged by whether the numbers `C3` reports move.
