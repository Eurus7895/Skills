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

## `fragments.jsonl`

One row per dispatched scope. Flat — the assembler validates a flat schema, and a nested row cannot be
checked against it.

```json
{"fragment_id": "fragment:src/api.py", "source": "src/api.py", "role": "…", "claim_ids": ["claim:…"], "status": "candidate"}
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
  "status": "unverified"
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

| Status | Means | May appear in prose |
| --- | --- | --- |
| `verified` | the source says so | yes |
| `supported_inference` | a reading of the code, not a structural fact | yes, labelled |
| `candidate` | not decidable here — for example a call in a language with no parser | limitations only |
| `needs_context` | could not be decided from what was supplied; retryable | limitations only |
| `rejected` | the source contradicts it | never; it fails the build |

`rejected` and `needs_context` are deliberately not the same. Collapsing them either discards true claims or
retries false ones forever.

## `doc.json` — format_version 1

Pages and blocks, with no markup in it. Block types are `prose`, `table`, `image` and `ref`. Page ids, block
ids, `ref` targets and `claim_refs` must all resolve before the model is written; a `claim_ref` to anything
that is not `verified` or `supported_inference` is a build failure, not a warning.

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
