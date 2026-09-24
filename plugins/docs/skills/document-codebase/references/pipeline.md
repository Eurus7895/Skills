# The components, and the driver that runs them

`scripts/` holds one directory per component. Each answers one kind of question, owns the scripts that answer
it, and hands the next one a file rather than a call:

| Component | Asks | Writes |
| --- | --- | --- |
| `survey/` | what is in this repository | `structure.json`, `units.txt` |
| `analyze/` | what the model needs in front of it | `claims.jsonl`, `packets/` |
| `check/` | whether a claim holds | `claims.verified.jsonl`, `fragments.verified.jsonl`, `findings.jsonl` |
| `document/` | what the pages will say | `.docs-build/diagrams/`, `flow-report.json`, `doc.json` |
| `render/` | what the draft looks like | `.docs-build/rendered-docs/`, `render-manifest.json` |
| `review/` | whether that exact draft may ship | `prose-report.json`, `generation-report.json`, `publish-seal.json` |
| `publish/` | which reviewed revision readers get | atomically promoted documentation tree |

`pipeline.py` sits beside them and runs one component per invocation. It exists because those runs are long,
their arguments never vary, and the failures that came of typing them out were silent ones: a `--analysis`
left off produced a document that read like an inventory, a `--flow-report` left off produced counts that
included flows nothing had validated. Neither is reachable from here.

These are phases of **one main workflow**: `survey` → `analyze` → `check` → model-written architecture,
flow and operations synthesis → `document` → `render` → `review` → `publish`. Manual authoring is a sub-workflow inside
`document`; claim repair and prose review are loops back into the same main workflow.

For design and review, treat that implementation as eight logical blocks. Component names do not define
where model work begins or where a deliverable becomes publishable:

| Logical block | Runtime/model work | Completion condition |
| --- | --- | --- |
| Survey | `survey` plus the P1 scope decision | scope, assets, entry points, configuration and exclusions are recorded |
| Analyze | packets, source reading, module and three-analysis artifacts | required source was read and claims carry evidence |
| Analysis review | validators plus P2/P3 decisions | roles, boundaries, flows and operations are accepted or repaired |
| Prose generation | manual grounding, validated answers and composed `pages` | project-specific draft covers its applicable questions |
| Diagram generation | class graph plus class and verified data-flow PlantUML | diagram semantics validate and presentation follows diagram policy |
| Render | `render_docs` and Sphinx check | the draft is viewable in its target format |
| Final review | fresh review-v2 records over rendered content | every required block is confirmed or remains explicitly unresolved |
| Publish | promotion of the confirmed output | only the reviewed revision is handed off or committed |

## Detailed-plan contract

A detailed plan is a reader-facing expansion of the eight logical blocks above, not a transcription of the
seven runtime commands. Use the block names as the plan's top-level headings and keep them in this order:

1. **Survey** — confirm target, audience, preset and scope; inspect repository conventions and existing docs;
   exclude test, generated, vendored, cache and build-output trees; run the survey; present its findings and
   record P1.
2. **Analyze** — select production modules; map documentation topics and manual questions to concrete source;
   have the model read that source; write module, architecture, flow and operations evidence with valid
   citations.
3. **Analysis Review** — review roles at P2; validate and repair claims; review architecture boundaries at P3;
   do not describe an import edge as a call flow.
4. **Prose Generation** — answer every applicable preset question from reviewed evidence; compose
   project-specific reader-facing sections; reject placeholders, internal metadata and unsupported claims;
   build and validate the manual draft.
5. **Diagram Generation** — build and validate the class graph and class views; emit data-flow diagrams only
   for verified call-site sequences; apply the diagram policy and record evidence limitations explicitly.
6. **Render** — render the combined draft into `.docs-build/rendered-docs/`; run the target-format/Sphinx checks;
   inspect the pages; do not modify the published `docs/` tree.
7. **Final Review** — review prose, diagrams, citations, navigation, coverage and limitations against the exact
   rendered hashes; record stable findings; repair blocking findings and return to Render; perform a fresh
   review after every content-changing repair; record P4 and create a seal only for confirmed current content.
8. **Publish** — verify that the review and seal are fresh; atomically promote the sealed staging tree to
   `docs/`; report artifacts, timings, validation results, unresolved limitations and cleanup choices.

Within those headings, adapt the number and granularity of steps to the repository and preset. Never collapse
**Prose Generation** and **Diagram Generation** into `document`, or **Render**, **Final Review** and **Publish**
into one delivery step. If the user asked only for a plan, state that no documentation has been generated or
published and stop after presenting it. Do not claim that no files were modified unless that is known from the
current run.

The last three are separate runtime components. `render` writes only to staging and hashes the result;
`review` first rejects any direct edit or changed `doc.json`, then binds its verdict to that draft and creates
a seal only after the gate passes; `publish` verifies the seal and atomically promotes the staged tree. None
of them performs another block's work.

**There is no command that runs the whole pipeline**, and that is the design rather than a gap. Four of the
judgements the document rests on — the scope, the module roles, the architecture, the prose promotions — sit
between components, and none of the validators downstream can tell a wrong role or a wrong boundary from a
right one.

**All four are enforced by the driver.** `survey` opens `P1` and `analyze` refuses while it is open;
`analyze` opens `P2` and `check` refuses; `check` opens `P3` and `document` refuses; the first
`review` opens `P4` when prose is queued, and the reviewed `review` is held until that checkpoint is
decided. Each refusal prints what to put in front of the person, what to ask them, and the command that
records the answer:

| | Opened by | Blocks | Asks |
| --- | --- | --- | --- |
| `P1` | `survey` | `analyze` and everything after it | is this the right scope to spend the budget on |
| `P2` | `analyze` | `check` and everything after it | do these roles match what the repository is |
| `P3` | `check` | `document` and everything after it | is this the architecture, and are the boundaries right |
| `P4` | `review`, only when prose is queued | reviewed `review` and `publish` | are these the intended readings |

**An open checkpoint holds every later component, not only the next one.** A build directory that already
holds an earlier run's artifacts is why: blocking `analyze` alone would leave later components free to
run over what is on disk and produce a finished report with the scope decision still outstanding.

P4 is conditional: a review that queues nothing does not open it. When it opens, the driver records the
question and blocks the reviewed review and publication. The gate's `review_required` result is the verdict;
the checkpoint is the control-flow stop.

They are enforced because they used to be prose, and prose was the only rule in this pipeline that failed
silently. Everything else here refuses — `analyze` will not overwrite hand-written claims, `assemble` will not
accept a unit with no row, the gate will not call a thin run `passed` — so a checkpoint that merely asked was
the one a reader could skip without ever seeing an error.

`decide --checkpoint <id> --note "<text>"` records one, and **only for a checkpoint that is open**. Answering a
question nobody has been asked yet is not an answer: deciding `P2` straight after `survey` would leave a
standing approval that `analyze` then finds valid and leaves alone, and `check` would run with the module roles
unreviewed. The note is required, because a decision the closing report cannot carry is not a decision anybody
can check later. P4 additionally requires the user's response to the displayed queue. Record it with
`decide --checkpoint P4 --user-response "<their answer>" --p4-verdict accepted|changes-requested`;
`changes-requested` keeps the checkpoint open. An unattended run cannot decide P4.
The driver records the response but cannot authenticate its origin; quote a real answer, carry requested
corrections into the draft, and review the resulting blocks before confirming them. P4 is bound to the
`review_queue` and its content/input hashes. After a repair, render and run `review` without `--review`
to refresh the queue; the old P4 response cannot release a reviewed pass or publish changed content.
`--dry-run` prints what would be recorded and records nothing.

Decisions are bound to the `index_hash` they were made against, so a rescan
reopens them — the scope approved against the old tree says nothing about the new one. Deleting a checkpoint
file bypasses it, in the same way deleting `claims.jsonl` bypasses the claims: the mechanism is against
forgetting, not against intent.

## `status` — where the run is

```bash
python3 scripts/pipeline.py status
```

**Read-only, and never blocked by anything.** It runs no stage, writes nothing — not even the build directory
it would report as absent — and answers the same whether the last component passed, failed, or was never
reached.

That last part is the reason it exists. A checkpoint refuses to let the next component run, and a failing
stage stops the ones behind it; both are correct, and between them they meant the state of a run was only ever
reported by something that might decline to report it. A session whose context was reset halfway through the
modules had no way to ask what was left: `quality_docs.py` names the unread modules, but that runs in
`publish`, and a partial analysis fails `check` first.

It prints the scan identity and revision, each checkpoint's state, the module budget, the manual's answered
and composed counts, the authored ledger, and the review queue — then one line naming the next action.

**Modules are reported in three states, not two:**

| | Means |
| --- | --- |
| read | at least two of `responsibility`, `state`, `interface`, `failure` — the same floor the gate applies |
| partly written | a statement or two and no more; there is work in it already |
| not started | nothing under this path at all |

A module with one statement is *touched*, not read. Reporting it beside the untouched ones is what invites a
resumed session to write it a second time.

A checkpoint opened or decided against an earlier `index_hash` is marked as such rather than counted, for the
same reason `decision_for` refuses it: the units may now be different.

**Run it first in any session that did not start the run.** Nothing else reports state without the power to
withhold it.

**The driver decides nothing.** Every stage is a script that was already the authority on its own question,
invoked with the paths its component fixes. Where a genuine choice exists — the fan-in cutoff, the preset,
whether Ruff runs — it is a flag with a default, not a rule hidden in the driver.

## What each component runs

| Component | Stages, in order |
| --- | --- |
| `survey` | `scan_repo` → `validate_index` → optional `annotate_import_usage` → `select_units` → `extract_config` → `validate_config` |
| `analyze` | `derive_claims` → `query_graph --packet`, once per unit |
| `check` | `validate_analysis` → `assemble` → `verify_doc` |
| `document` | `validate_architecture` → `validate_flows` → `validate_operations` → `build_class_graph` → `build_diagrams` → `validate_diagrams` → `build_flow_diagrams` → `validate_flow_diagrams` → `build_document_model` |
| `render` | `prepare_stage` → `render_docs` → `snapshot_draft` |
| `review` | `validate_draft` → `check_prose` → `release_hygiene` → `quality_docs` → `seal_draft` |
| `publish` | `promote_docs` |

Stages are named `component/script` as they run, so the line that reports a failure also says which component
owns the thing that failed.

`--dry-run` prints the exact commands a component would run and runs none of them. It is the fastest way to
see what a flag changed, and the only way to read a stage's invocation without reading the driver.

## Stopping, skipping, and the codes

A component runs its stages in order and **stops at the first one that fails**, printing which stage it was
and how many later stages did not run. That stage's exit code is what the component returns, unchanged: `0`
fine, `1` a policy was not met, `2` bad input or a missing dependency, `3` internal.

**Three stages may fail with exit code `1` without stopping their component**, and each says so as it does:

| Stage | Why `1` is not fatal |
| --- | --- |
| `document/build_flow_diagrams` | exits `1` when no flow was traced, the common answer on ordinary object-oriented code |
| `review/check_prose` | exits `1` on a block queued for review, and the quality gate carries that forward |
| `review/release_hygiene` | exits `1` on a staging-tree finding; the quality gate reads its report and blocks publication |

The component still ends non-zero in both cases. Tolerating a code is not forgiving it.

**A stage whose input was never written is skipped, with the reason printed.** The three analyses in
[`three-analyses.md`](three-analyses.md)
are optional by design: `document` skips the validator for each file that is absent and passes
`--architecture`, `--flows` and `--operations` only for the ones that exist, and `review` does the same for
the prose check and the gate. A run without them is a visibly thinner document, never a silently thinner one.

## Flags

| Flag | Component | Default | Effect |
| --- | --- | --- | --- |
| `--root` | all | `.` | the repository being documented |
| `--build` | all | `.docs-build` | where intermediates go |
| `--docs` | `render`, `publish` | `docs` | existing/target documentation tree; render reads it, publish replaces it |
| `--staging` | `render`, `review`, `publish` | `.docs-build/rendered-docs` | isolated rendered draft |
| `--top` | `survey` | `25` | the fan-in cutoff for `units.txt` |
| `--policy` | `survey` | `optional` | `disabled` drops the Ruff stage entirely |
| `--force` | `analyze` | off | re-derive `claims.jsonl` over hand-written claims |
| `--preset` | `document` | `auto` | `auto` selects `manual`; name another preset explicitly for a graph-driven report |
| `--detail` | `document` | `public` | class-diagram detail level |
| `--format` | `render` | `rst` | `rst` or `myst` |
| `--review` | `review` | — | your `prose-review.jsonl` verdicts |
| `--write-conf`, `--project` | `render` | off | generate a Sphinx `conf.py` in staging if none exists |
| `--dry-run` | all | off | print the commands, run nothing (and neither open nor consult a checkpoint) |
| `--checkpoint`, `--note` | `decide` for P1–P3 | — | which judgement is being recorded, and what was decided |
| `--checkpoint P4`, `--user-response`, `--p4-verdict` | `decide` for P4 | — | user's answer and acceptance or requested changes |

## Timing the workflow

Every non-dry-run component appends one record per script stage and one component summary to
`.docs-build/timings.jsonl`. Records include timestamps, elapsed seconds, status and exit code, so a slow
`document`, `render`, `review` or `publish` can be split into the exact script responsible.

Model work happens between component commands and cannot be observed by a child script. Bracket it explicitly:

```bash
python3 scripts/pipeline.py measure --step source_reading --state start
# read source and write the analysis
python3 scripts/pipeline.py measure --step source_reading --state stop
```

Use the same pattern for `architecture_synthesis`, `manual_authoring`, `prose_rewrite` and `model_review`.
Stopping may add `--status failed` or `--status cancelled`. Only one model step may be active, preventing two
overlapping measurements from being reported as separate elapsed time. Do not infer model duration from the
gap between commands; that gap may include a checkpoint or time waiting for the user.

## Why `analyze` can refuse to run

`derive_claims` writes `claims.jsonl` from the index, and a `calls` claim is appended to that same file by
hand, because a call site is something a person read. Re-running `analyze` would rewrite the file and take
those with it — silently, since a shorter flow analysis validates just as cleanly as a longer one. So the
component checks for claims no script could have produced and stops rather than overwriting them, naming the
ones it found. `--force` proceeds, and is right when the scan itself is what changed: the tree moved, the
hashes are stale, and those claims need writing again anyway.

## Where the boundaries leak, and why

Two places, both deliberate.

**The review gate imports across components** — `validate_analysis` from `check/` and the presets
from `document/`. It has to: it counts statements the way `check` validates them and reports coverage against
the presets `document` builds from, and a second copy of either rule would drift into reporting on a
different document than the one that was built. It resolves them by the relative layout, which is identical in
`shared/` and in an installed plugin.

**`document/` writes diagrams into `.docs-build/diagrams/`.** `render` copies them into the staged tree;
`publish` never reads the source diagrams separately because the seal covers the staged copies. Both diagram
families share the build directory, so `validate_flow_diagrams` consults the class manifest before reporting a
`.puml` as unclaimed.

## What is still yours to run

`analyze/query_graph.py`, for the parts of a partitioned packet. It is not a stage because how much of a
partitioned module you need is a judgement, and a driver that fetched every part would spend the budget the
partition exists to protect.
