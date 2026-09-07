# The components, and the driver that runs them

`scripts/` holds one directory per component. Each answers one kind of question, owns the scripts that answer
it, and hands the next one a file rather than a call:

| Component | Asks | Writes |
| --- | --- | --- |
| `survey/` | what is in this repository | `structure.json`, `units.txt` |
| `analyze/` | what the model needs in front of it | `claims.jsonl`, `packets/` |
| `check/` | whether a claim holds | `claims.verified.jsonl`, `fragments.verified.jsonl`, `findings.jsonl` |
| `document/` | what the pages will say | the diagrams, `flow-report.json`, `doc.json` |
| `publish/` | what a reader gets, and whether the run is done | the pages, `prose-report.json`, `generation-report.json` |

`pipeline.py` sits beside them and runs one component per invocation. It exists because those runs are long,
their arguments never vary, and the failures that came of typing them out were silent ones: a `--analysis`
left off produced a document that read like an inventory, a `--flow-report` left off produced counts that
included flows nothing had validated. Neither is reachable from here.

**The driver decides nothing.** Every stage is a script that was already the authority on its own question,
invoked with the paths its component fixes. Where a genuine choice exists — the fan-in cutoff, the preset,
whether Ruff runs — it is a flag with a default, not a rule hidden in the driver.

## What each component runs

| Component | Stages, in order |
| --- | --- |
| `survey` | `scan_repo` → `validate_index` → `annotate_import_usage` → `select_units` |
| `analyze` | `derive_claims` → `query_graph --packet`, once per unit |
| `check` | `validate_analysis` → `assemble` → `verify_doc` |
| `document` | `validate_architecture` → `validate_flows` → `validate_operations` → `build_class_graph` → `build_diagrams` → `validate_diagrams` → `build_flow_diagrams` → `validate_flow_diagrams` → `build_document_model` |
| `publish` | `render_docs` → `check_prose` → `quality_docs` |

Stages are named `component/script` as they run, so the line that reports a failure also says which component
owns the thing that failed.

`--dry-run` prints the exact commands a component would run and runs none of them. It is the fastest way to
see what a flag changed, and the only way to read a stage's invocation without reading the driver.

## Stopping, skipping, and the codes

A component runs its stages in order and **stops at the first one that fails**, printing which stage it was
and how many later stages did not run. That stage's exit code is what the component returns, unchanged: `0`
fine, `1` a policy was not met, `2` bad input or a missing dependency, `3` internal.

**Two stages may fail without stopping their component**, and both say so as they do:

| Stage | Why `1` is not fatal |
| --- | --- |
| `document/build_flow_diagrams` | exits `1` when no flow was traced, the common answer on ordinary object-oriented code |
| `publish/check_prose` | exits `1` on a block queued for review, and the quality gate is meant to carry that forward |

The component still ends non-zero in both cases. Tolerating a code is not forgiving it.

**A stage whose input was never written is skipped, with the reason printed.** The three analyses of step 4
are optional by design: `document` skips the validator for each file that is absent and passes
`--architecture`, `--flows` and `--operations` only for the ones that exist, and `publish` does the same for
the prose check and the gate. A run without them is a visibly thinner document, never a silently thinner one.

## Flags

| Flag | Component | Default | Effect |
| --- | --- | --- | --- |
| `--root` | all | `.` | the repository being documented |
| `--build` | all | `.docs-build` | where intermediates go |
| `--docs` | `document`, `publish` | `docs` | where the document and `_diagrams/` are written |
| `--top` | `survey` | `25` | the fan-in cutoff for `units.txt` |
| `--policy` | `survey` | `optional` | `disabled` drops the Ruff stage entirely |
| `--force` | `analyze` | off | re-derive `claims.jsonl` over hand-written claims |
| `--preset` | `document` | `auto` | `auto` picks `outside-in` when an architecture analysis exists, else `onboarding` |
| `--detail` | `document` | `public` | class-diagram detail level |
| `--format` | `publish` | `rst` | `rst` or `myst` |
| `--review` | `publish` | — | your `prose-review.jsonl` verdicts |
| `--write-conf`, `--project` | `publish` | off | generate a Sphinx `conf.py` if the output directory has none |
| `--dry-run` | all | off | print the commands, run nothing |

## Why `analyze` can refuse to run

`derive_claims` writes `claims.jsonl` from the index, and a `calls` claim is appended to that same file by
hand, because a call site is something a person read. Re-running `analyze` would rewrite the file and take
those with it — silently, since a shorter flow analysis validates just as cleanly as a longer one. So the
component checks for claims no script could have produced and stops rather than overwriting them, naming the
ones it found. `--force` proceeds, and is right when the scan itself is what changed: the tree moved, the
hashes are stale, and those claims need writing again anyway.

## Where the boundaries leak, and why

Two places, both deliberate.

**`publish/quality_docs.py` imports across components** — `validate_analysis` from `check/` and the presets
from `document/`. It has to: it counts statements the way `check` validates them and reports coverage against
the presets `document` builds from, and a second copy of either rule would drift into reporting on a
different document than the one that was built. It resolves them by the relative layout, which is identical in
`shared/` and in an installed plugin.

**`document/` writes into `docs/_diagrams/`, which `publish/` then renders references to.** Diagrams are
content rather than markup, so they are built with the model that cites them; the renderer only resolves
figures it is handed. Both diagram families share that directory, which is why `validate_flow_diagrams`
consults the class manifest before reporting a `.puml` as unclaimed.

## What is still yours to run

`analyze/query_graph.py`, for the parts of a partitioned packet. It is not a stage because how much of a
partitioned module you need is a judgement, and a driver that fetched every part would spend the budget the
partition exists to protect.
