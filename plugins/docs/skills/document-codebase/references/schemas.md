# Data contracts

Every artefact carries a version. A script given a version it does not know exits `2` rather than guessing
what the fields mean.

## Entity ids

Claims name things by id, not by prose. Four forms, and nothing else parses:

```text
module:<path>                     src/api.py as a whole
symbol:<path>:<name>              a top-level function or class
class:<path>:<Name>               a class, where --detail extracted it
method:<path>:<Class>.<name>      a method on such a class
```

Paths are repository-relative and forward-slashed, exactly as they appear in `structure.json`. An absolute
path, a `../`, or a Windows separator is rejected.

## `structure.json` — schema_version 2

Written by `scan_repo.py`, checked by `validate_index.py`. The deterministic half of everything downstream.

```json
{
  "schema_version": 2,
  "index_hash": "sha256:…",
  "source": {"root": "/abs/path", "revision": "a1b2c3…", "dirty": false},
  "files": [],
  "edges": [],
  "fan_in": {},
  "entry_points": [],
  "diagnostics": [],
  "coverage": {}
}
```

`source.dirty` is true when the tree had uncommitted changes **and** when git could not answer. A revision
that might not describe the files is worth no more than no revision.

Each file record carries `path`, `lang`, `loc`, `exact`, `parser`, `is_test`, `source_hash`, `main_guard`,
`symbols`, `imports`, and — only where `--detail` reached it — `classes` and `functions`. A file that produced
no detail has **no** `classes` key at all; that is different from an empty list, and must be reported as
"not checked" rather than "no classes".

Each import entry carries `name`, `line`, `level`, and (Python only) `bindings` — the names the statement
actually binds. `import a.b.c` binds `a`; `import a.b as x` binds `x`; `from a import p, q` binds both.

Each edge carries `edge_id`, `from`, `to`, `line`, `import`, and the union of the `bindings` that produced it.
There is one edge per `(from, to)` pair, keeping the first line, so a file imported twice does not appear as
two dependencies.

`diagnostics` rows are `{code, severity, path, message}`:

| Code | Meaning |
| --- | --- |
| `D001` | imports that named nothing in this repository (third-party or stdlib) |
| `D002` | files with no parser for their extension |
| `D003` | symlink resolving outside the root; skipped, not followed |
| `D004` | a Python file that did not parse; its imports are regex-approximated |
| `D005` | a language with no exact parser; imports are regex-approximated |
| `D006` | imported bindings Ruff reports as never read |
| `D007` | Ruff diagnostics that could not be tied to an import statement |

### Usage annotation

`annotate_import_usage.py` adds `usage` to import entries, mapping each binding to `used`,
`unused_binding`, `suppressed` or `unknown`, and a `coverage.import_usage` summary. It adds nothing else.
Removing those fields must restore the index byte for byte — a test asserts it.

## Context packet — packet_version 1

Printed on stdout by `query_graph.py --packet`. Never stored; it is context for one model call.

Beyond the scope's own source and symbols, the fields that matter are:

- `imports` / `imported_by` — each with a `cite` of the form `path:line` ready to quote, and `edge_id`.
- `binding_usage_advisory` — present only where step 2 ran. Advisory, and named so at the point of use.
- `neighbour_interfaces` — public symbols of each neighbour, not their bodies.
- `import_usage_coverage` — `absent`, `partial` or `complete`. When it is `absent`, "not marked unused" means
  "never looked at", which is not the same claim as "used".
- `context_manifest` — `included`, `omitted`, `token_estimate`, and the limits in force. The token count is
  characters divided by four and is labelled an estimate everywhere it appears.
- `partitioned` / `parts` — when the scope was too large to send whole. Each part has an id to fetch with
  `--part`, and the parts tile the file with no gap.

## Run identity

`structure.json` carries `index_hash`, a sha256 over the scan's content — the files, edges and coverage. It
deliberately excludes `source` and `root`: the absolute path, the revision and the dirty flag say nothing
about what the code *is*, and including them would invalidate every fragment as soon as an unrelated file was
committed or the repository was scanned from a second checkout. It is the identity of a scan, not a checksum
of the file, so the advisory fields `annotate_import_usage.py` adds later do not change it. Every row in
`fragments.jsonl` and `claims.jsonl` repeats it, and `verify_doc.py` rejects (`V021`) a row whose hash does
not match the index it was given, or that carries none.

`.docs-build/` outlives a run. A fragment left there by an earlier one parses, names a real file, and its
claims may still verify against today's index — the identity is the only thing that separates it from a row
written a minute ago. The scanner prints the hash so it can be copied without opening the JSON.

## `fragments.jsonl`

One row per dispatched scope. Flat — the assembler validates a flat schema, and a nested row cannot be
checked against it.

```json
{"fragment_id": "fragment:src/api.py", "source": "src/api.py", "role": "…", "claim_ids": ["claim:…"], "status": "candidate", "index_hash": "sha256:…"}
```

`verify_doc.py` rewrites `status` to the worst status among the claims the fragment references. One rejected
claim makes the whole fragment untrustworthy, however many verified ones surround it.

## `claims.jsonl`

```json
{
  "id": "claim:api-imports-service",
  "kind": "imports",
  "subject": "module:src/api.py",
  "object": "module:src/service.py",
  "evidence": [{"path": "src/api.py", "line_start": 5, "line_end": 5}],
  "status": "unverified",
  "index_hash": "sha256:…"
}
```

| Kind | Verified when |
| --- | --- |
| `defines` | the symbol is in the file's symbol table |
| `contains` | the method is on that class in the extracted detail |
| `imports` | the edge is in the graph, at the cited line |
| `inherits` | the base resolved to the named file |
| `calls` | the cited line holds a call to that name **and** the name is bound by an import from the callee's file |
| `responsibility` | never; it is recorded as `supported_inference` |

`evidence.source_hash` is optional — the file's hash from the index is used when it is absent. Either way, a
file that has changed since the scan makes the citation uncheckable, not false: status `needs_context`,
finding `V005`, and the fix is to rescan.

### Statuses

| Status | Means | Retryable | May appear in prose |
| --- | --- | --- | --- |
| `verified` | the source says so | — | yes |
| `supported_inference` | a reading of the code, not a structural fact | — | yes, labelled |
| `candidate` | not decidable here — for example a call in a language with no parser | no | limitations only |
| `unsupported` | not decidable in principle — a call target computed at run time | no | limitations only |
| `needs_context` | could not be decided from what was supplied | yes | limitations only |
| `rejected` | the source contradicts it | no | never; it fails the build |

The three negative statuses are deliberately distinct, because each implies a different next move.
`needs_context` asks for another packet. `unsupported` asks for nothing — `table[key]()` will still be
`table[key]()` after any amount of extra context, so retrying it only spends budget. `rejected` says the claim
is false. Collapsing any pair of them either discards true claims or retries hopeless ones forever.

Only `rejected` and `needs_context` make `verify_doc.py` exit `1`. A run whose worst outcome is `unsupported`
has finished: the claim is recorded, labelled, and reported in the limitations.

## `module-analysis.jsonl` — analysis_version 1

One row per module the run actually read. It sits **beside** `claims.jsonl`, not in place of it: a claim
states a fact about structure that the source can contradict, a statement states what a module is for and
nothing can. Keeping both means the run has a floor that can be proven wrong and a ceiling that carries
meaning; collapsing them would put an interpretation in the same column as a verified fact.

```json
{"analysis_version": 1, "path": "src/api.py", "source_hash": "sha256:…", "index_hash": "sha256:…",
 "role": "Exposes the HTTP boundary and delegates to application services.",
 "statements": [{"id": "api-s1", "kind": "responsibility", "status": "observed",
   "text": "Validates the request body before any service call, so a malformed payload never reaches the store.",
   "evidence": [{"path": "src/api.py", "line_start": 34, "line_end": 51, "symbol": "create_order"}]}]}
```

`kind` is `responsibility`, `state`, `interface`, `interaction`, `failure` or `rationale`. `role` stays what
it has always been — a navigation label, not the analysis.

| `status` | Means |
| --- | --- |
| `declared` | the repository states it: an ADR, a design document, a docstring |
| `observed` | visible in the code, with no reason given for it |
| `inferred` | the model's reading, supported by more than one place |
| `unknown` | the repository does not say, and the document must not pretend otherwise |

There is no confidence field. Nothing can contradict a model's assessment of its own certainty, so it would
be a number no check could ever disagree with.

`validate_analysis.py` cannot ask whether a reading is right. It asks whether one happened:

| Code | Meaning |
| --- | --- |
| `A002` | a row or statement is missing a required field |
| `A003` | the module is not in the index |
| `A004` | written against a different version of the file |
| `A005` | carried over from a different scan |
| `A006` / `A007` / `A008` | evidence names a file, a line range or a symbol that is not there |
| `A009` / `A010` | unknown statement kind or status |
| `A011` | a statement id used twice |
| `A012` | the same statement made about two modules — it was about neither |
| `A013` | two statements differing only in their nouns; past a fifth of the set, one template |
| `A014` | the statement names nothing that is in the module it describes |

`A013` between one pair and `A014` are **advisory**: they do not fail the run, they stop the statement
counting as analysis. A document made of anchorless prose then falls to `derived_only` on its own, without
an argument about whether one sentence was too abstract.

## `generation-report.json` — schema_version 1

Written by `quality_docs.py`. It is the only artefact that says **how much of the document was read and how
much was copied**, and it exists because no other check can tell the difference: a claim derived from the index
and checked against the index agrees with itself, so a document made entirely of them passes every other stage.

```json
{"schema_version": 1, "analysis_mode": "per_module", "status": "passed", "reasons": [],
 "modules": {"budget_from": "units.txt", "in_budget": 25, "analysed": 24, "coverage": 0.96,
             "out_of_budget": 310, "unanalysed": ["…"]},
 "statements": {"total": 61, "valid": 58, "unanchored": 2, "near_duplicate": 1, "rejected": 0,
                "with_valid_evidence": 61, "by_kind": {}, "by_status": {}}}
```

| `analysis_mode` | Coverage of the budget |
| --- | --- |
| `per_module` | 0.90 and above |
| `partial` | 0.50 to 0.90 |
| `derived_only` | below 0.50, or no statement was written at all |

**`passed` is impossible under `derived_only`**, whatever else is green. Such a run is not broken — every
sentence in it checks out — so it is reported as `partial` with the count that produced it, never as a failure
of the tooling and never as a success.

`status` is `failed` when a statement or a claim was rejected, a mandatory page is missing, or no diagram
covers the repository; `partial` when the mode is `partial` or `derived_only`; `passed` otherwise. `--require`
chooses which of those still exits `0`, defaulting to `partial`.

**Coverage is measured against the budget, not the repository.** `units.txt` names the modules the run paid to
read; everything else is covered in a line and counted in `out_of_budget`. A run that read everything it
undertook to read is `per_module` on four files and on four thousand.

## `doc.json` — format_version 1

Pages and blocks, with no markup in it. Block types are `prose`, `table`, `image`, `plantuml` and `ref`. Page ids, block
ids, `ref` targets and `claim_refs` must all resolve before the model is written; a `claim_ref` to anything
that is not `verified` or `supported_inference` is a build failure, not a warning.

## PlantUML diagram artifacts — manifest_version 3

One run may draw several views. `diagram-manifest.json` is the index of them:

```json
{"schema_version": 3, "views": [{"view": "full_repository",
  "file": "full-repository.puml", "scope": {"kind": "repository"},
  "source_graph_hash": "sha256:...", "nodes": ["..."], "scope_nodes": ["..."],
  "edges": ["..."]}]}
```

`nodes` is every class the view draws; `scope_nodes` is the subset it is answerable for. A detail view also
draws the far end of any relationship that leaves its scope, so on a package view the two differ, and whoever
writes a caption counts `scope_nodes` — counting `nodes` describes a package as holding classes that belong to
its neighbours.

Each view owns one `.puml` source file. PlantUML and Sphinx derive SVG/HTML during the
documentation build; those rendered files are not the canonical diagram artifact.
`scope.kind` is `repository`, `package` or `module`, with `scope.id` naming the container
for the latter two. Machine-readable `@diagram`, `@node`, and `@edge` comments let the
validator check the generated PlantUML subset without parsing arbitrary PlantUML.

**Scope is what a view is answerable for.** A checker holds a view to the classes in its scope, not to the
whole graph — otherwise a view of one package reads as a repository view that lost most of its boxes. Scope is
derived from the graph's package structure and cannot be set in a view specification: an author-chosen scope
would be `remove_classes` under another name.

## Exit codes

Shared by every script here:

```text
0  succeeded
1  ran, but the result does not meet policy (findings, a failed check)
2  input, configuration, schema-version or dependency error
3  internal error
```

`1` and `2` are different on purpose: one means the repository or the claims are wrong, the other means the
invocation was.
