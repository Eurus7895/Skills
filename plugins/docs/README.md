# docs

Write a repository's architecture documentation from its real dependency graph, not from what the model
remembers reading.

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
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install docs@CopilotBox
```

## Skills

- **`document-codebase`** — parses the repository with `scan_repo.py` (Python via `ast`, other languages by
  import regex), ranks modules by fan-in, sends each one to the model in a bounded context packet with its
  real importers supplied, verifies every claim that comes back, and renders a multi-page RST or MyST document
  under `docs/`. Fires on "document this repo", "write architecture docs", "explain how this codebase fits
  together", "map the dependencies".

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
| `publish` | `render_docs.py` | Renders that to RST or MyST, wires it into an existing Sphinx project, and checks the result |
| | `sphinx_support.py` | Runs the build and says which of six things went wrong, rather than "failed" |
| | `wire_toctree.py` | Adds the generated pages to an index someone else wrote, or refuses to touch it |
| | `check_prose.py` | Holds a rendered sentence to the strength its sources carry |
| | `quality_docs.py` | Says how much of the document was read and how much was copied; a derived-only run is never `passed` |

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
- Every script exits `0` on success, `1` when it ran but the result does not meet policy, `2` on an input or
  schema-version error, and `3` on an internal error. The `1`/`2` split matters: one means the repository or
  the claims are wrong, the other means the invocation was.
- Every script here is authored in `shared/scripts/` and materialized into this plugin. Edit the source and
  run `python3 tools/materialize.py`; never edit the generated copies.
