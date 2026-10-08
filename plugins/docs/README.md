# docs

Write a repository's architecture documentation, a product manual, or a document following your own template,
from its real dependency graph — not from what the model remembers reading — and check an existing
documentation tree against a template.

The shape is what makes the result checkable:

```
scan  ->  validate  ->  bound the context per module  ->  describe  ->  verify every claim  ->  draw  ->  render
```

Structure is a fact extracted by code. Judgement happens afterwards, once each module's role can be stated
against the modules that actually import it. Nothing ships that the graph does not support.

Each description comes back as claims with citations rather than as prose alone, and each claim is decided
before it can reach a page: `verified` and `supported_inference` may be written, `candidate`,
`unsupported` and `needs_context` are confined to the limitations section, and a `rejected` claim stops the
build. A reader
cannot tell a checked sentence from an unchecked one, so the separation is enforced where it can be.

## Install

```bash
copilot plugin marketplace add eurus-labs/Skills
copilot plugin install docs@CopilotBox
```

## Skills

- **`document-codebase`** — parses the repository with `scan_repo.py` (Python via `ast`, other languages by
  import regex), ranks modules by fan-in, sends each one to the model in a bounded context packet with its
  real importers supplied, verifies every claim that comes back, and renders a multi-page RST or MyST document
  under `docs/`. Fires on a request for written documentation — "document this repo", "write architecture
  docs", "write a user manual", "fill in our documentation template", "check our docs against this
  template". A question asked in chat about how the code fits together is answered directly instead.

## Choosing the template

**No outline is mandatory.** The skill lists the choices, recommends one, and builds what you pick:

| Choice | What you get |
| --- | --- |
| `architecture`, `onboarding`, `outside-in`, `handbook` | Graph-driven presets with fixed pages |
| `manual` | The built-in question template — whole, or only the sections you keep with `--sections` / `--drop` |
| your own file | A Markdown outline (headings are sections, list items the questions each must answer) or JSON |

The choice is recorded with `pipeline.py template --use … --note "<why>"`, and every later stage validates
the document against it. If nobody chooses, the run builds the survey's recommendation marked *provisional*,
and publishing waits until you confirm it or pick another. In your own outline, `(ask)` before a question
means you answer it — by name, without counting against the cap on unevidenced answers.

**Your decisions can be signed.** Commit `.github/docs-allowed-signers` (OpenSSH's allowed_signers format)
and the template choice, the final sign-off on the readings, and each authored page you settle must carry
your SSH signature over exactly what you approved; `pipeline.py approve` prints the `ssh-keygen -Y sign`
commands, and `publish` verifies them. Without that file, approvals are recorded as text and reported as
unverified. `pipeline.py template --check-docs docs --use <template>` checks a documentation
tree that already exists — written by you or by an earlier run — and reports each section as present,
incomplete or missing, without editing anything.

## Components

`scripts/` holds one directory per component, and `pipeline.py` beside them runs one component per
invocation. Each component answers one kind of question and hands the next a file rather than a call.

| Component | Script | Does |
| --- | --- | --- |
| `survey` | `scan_repo.py` | Extracts the index: symbols, imports, classes, edges, a hash per file, the revision scanned |
| | `validate_index.py` | Re-derives what can be re-derived and reports findings; catches an index gone stale |
| | `annotate_import_usage.py` | Optional Ruff F401 pass, report-only, marking bindings nothing reads |
| | `select_units.py` | Picks the modules worth a model call, and says when fan-in is a bad way to pick them |
| `analyze` | `derive_claims.py` | Writes the structural claims the index already holds, so no model budget is spent copying a table |
| | `query_graph.py` | Builds one bounded context packet per scope, partitioning rather than truncating |
| `check` | `validate_analysis.py` | Cannot ask whether a reading is right, so asks whether one was made: evidence, anchoring, repetition |
| | `assemble.py` | Fails the run when a dispatched module returned no row, or every row says the same thing |
| | `verify_doc.py` | Decides every claim against the graph and the source; never rewrites prose |
| `document` | `validate_architecture.py` | Checks the components, their boundaries and their evidence — never whether the grouping is a good one |
| | `validate_flows.py` | Accepts a step only where a verified call joins the two entities it names |
| | `validate_operations.py` | Refuses a quoted command that is not in the lines it cites |
| | `build_class_graph.py` | Builds the canonical class graph: packages, modules, classes, relationships in layers |
| | `build_diagrams.py` | Generates deterministic PlantUML Diagram as Code from the class graph |
| | `validate_diagrams.py` | Checks PlantUML declarations and relationships against the graph |
| | `build_flow_diagrams.py` | Draws a validated flow as a sequence, and refuses one edited since it was validated |
| | `validate_flow_diagrams.py` | Reads the drawing back, because a `.puml` is a text file |
| | `build_document_model.py` | Turns verified claims and statements into pages and blocks, with no markup in them |
| `render` | `prepare_stage.py`, `render_docs.py`, `snapshot_draft.py` | Copies existing docs into staging, renders/checks there, and binds the draft to `doc.json` |
| `review` | `validate_draft.py`, `check_prose.py`, `release_hygiene.py`, `quality_docs.py`, `seal_draft.py` | Rejects direct draft edits, requires fresh model review and a direct P4 response for queued prose, checks the staging tree, runs the final gate, and seals the exact revision |
| `publish` | `approvals.py`, `promote_docs.py` | Verifies any signatures the repository requires, then the seal, and atomically promotes only the reviewed draft |

**MyST needs `myst_parser` enabled in the project it lands in.** Sphinx does not read `.md` without it, so
`render_docs.py --format myst` refuses to write into a `conf.py` that does not enable it rather than leaving a
build failing over pages that are not at fault. A fresh directory with no `conf.py` has nothing to
misconfigure and is written to normally.

## Notes

- **Import edges are not call edges.** `scan_repo.py` records imports; it builds no call graph. A `calls`
  claim is verified only when the cited line really holds a call to that name **and** the name is bound by an
  import from the file the callee lives in — a name match alone would credit a local function to whichever
  module happens to share its name. Outside Python there is no tree to read, so a call stays a candidate.
- **An unused import is not a dead dependency.** The Ruff pass says whether a bound name is ever read. It
  never removes an edge, never proposes an edit, and runs with `--no-cache` so nothing lands in the scanned
  repository. Re-export, side effects, registration and dynamic discovery all look identical from here, and
  the generated document says so wherever it reports the count.
- **Nothing is silently truncated.** A file too large for the context ceiling is split along its own top-level
  definitions and fetched part by part; a file with nothing to split on is refused rather than halved.
- **The class diagram is a claim too.** `class-graph.json` is structural truth and generated PlantUML is
  the reviewable Diagram as Code presentation. Every class the scanner found
  appears exactly once, an unresolved base draws no edge at all, and inheritance and composition are kept in
  separate layers from the weaker association and call edges. Sphinx and PlantUML own rendering and layout;
  the generator and validator own structural correctness.
- **Approximate data labels itself.** Python is parsed exactly with `ast`. JavaScript, TypeScript, Go, Rust,
  Java, Ruby, C and C++ are approximated by import regex; those records carry `"exact": false`, and any claim
  resting on them is marked *(approximate)*.
- **`--detail` covers classes.** Base classes, methods with parameters and visibility, and attributes from both
  the class body and `self` assignments — Python only, because regex can find a class name but not its bases,
  and a half-filled record reads like a complete one. A base class links to a defining file only when the
  import resolves **and** that file defines a class by that name.
- **Coverage is reported, not assumed.** The document says how many files were scanned, how many were parsed
  exactly, how many claims were checked against the graph, how many failed, and what was skipped — including
  symlinks resolving outside the scanned root.
- Bundled scripts are Python 3, stdlib only. Intermediates go to `.docs-build/`; the document goes to `docs/`.
  Nothing else in the working tree is written. No network, no installs. `ruff`, `sphinx-build` and `docutils`
  are used when present and reported as absent when not — an absent checker reports `skipped`, never `passed`.
  `ssh-keygen` verifies signed approvals when the repository requires them, and its absence then fails
  publication rather than skipping the check.
- Every script exits `0` on success, `1` when it ran but the result does not meet policy, `2` on an input or
  schema-version error, and `3` on an internal error. The `1`/`2` split matters: one means the repository or
  the claims are wrong, the other means the invocation was.
- Every script here is authored in `shared/scripts/` and materialized into this plugin. Edit the source and
  run `python3 tools/materialize.py`; never edit the generated copies.

## Question-driven manual

The `manual` template — or a selection of it, or your own — is answered in `manual-analysis.json` with
evidence, and its pages are composed from those answers. Pages the template marks `authored` (in the
built-in manual: troubleshooting, FAQ, glossary, references, compliance, changelog) are written by a person,
never generated: you write each one or waive it with your name and a reason, and publication waits until
you have. Only pages marked with a diagram require one. Unknown answers keep the manual incomplete. See
[the manual guide](skills/document-codebase/references/manual.md).
