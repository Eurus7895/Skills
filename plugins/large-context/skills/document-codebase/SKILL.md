---
name: document-codebase
description: Generate architecture documentation for a repository too large to read into context, by parsing
  its structure with a scanner first — symbols, imports, dependency graph, fan-in ranking — then describing
  each module with its real neighbours supplied, and cross-checking every claim against the graph so the
  document cannot assert a relationship the code does not have. Produces docs/ARCHITECTURE.md with file:line
  citations. Use for "document this repo", "write architecture docs", "explain how this codebase fits
  together", "what calls what", "onboard someone to this project", "map the dependencies", or when a large or
  unfamiliar repository needs a written overview. For non-code corpora — logs, tickets, contracts, papers —
  use `synthesize-corpus` instead. Do not use to explain a single file or to generate API reference from
  docstrings.
---

# Document a codebase larger than the context window

Get the structure from a parser, not from the model. Describe each module with its real callers and
dependencies in hand. Synthesize the architecture from those descriptions, then verify every structural claim
against the graph before writing `docs/ARCHITECTURE.md`.

## When to use this skill

- The repository is too large to read in full — roughly 50k lines or more, or hundreds of source files.
- The user wants an **architecture overview**: layers, data flow, entry points, what depends on what.
- An unfamiliar repository needs an onboarding document.
- Existing docs have drifted and need regenerating against current code.

## When not to use this skill

- **The repo fits in context** (under ~50k lines). Read it and write the document directly — this pipeline's
  overhead buys nothing.
- **A single file or function needs explaining.** Read it and answer.
- **API reference from docstrings** is wanted. That is a documentation-generator job, not this.
- **The corpus is not code** — logs, tickets, contracts, transcripts. Use `synthesize-corpus`.

## Hard rules

1. **Structure comes from the scanner, never from the model.** Imports, symbols, callers, and file sizes are
   facts in `structure.json`. Never write a dependency, call, or "used by" claim that is not an edge in the
   graph.
2. **Every claim carries `path:line`.** A statement a reader cannot check in five seconds does not ship.
3. **Give every per-module task its neighbours.** A module described without knowing who imports it gets
   described as a bag of functions instead of as a role in the system. This is the step that makes the
   document coherent.
4. **Label approximate data.** Records with `"exact": false` had their imports guessed by regex, not parsed.
   Any claim resting on them is marked *(approximate)* in the document.
5. **Document only what was scanned.** Say how many files were covered and name what was skipped.
6. **Never overwrite an existing architecture document without confirming.** Read it first, then ask.

## Steps

### 1. Scan the repository

**Run it; you do not need to read it.**

```bash
python3 scripts/scan_repo.py --root . --out structure.json --summary --top 20
```

The digest printed to stdout is what you read. `structure.json` stays on disk — query it with code, do not
load it into context.

The digest gives: file and line totals, languages, how many files were parsed exactly, unresolved import
count, the fan-in ranking, files nothing imports, and isolated files.

If `unresolved imports` is high relative to total imports, most dependencies point outside the repo
(third-party or standard library). That is normal; say so rather than treating it as a defect.

### 2. Pick the scope from fan-in, not from filenames

Not every file earns a paragraph. Rank by how many modules depend on it:

```bash
python3 -c "
import json; d = json.load(open('structure.json'))
top = sorted(d['fan_in'].items(), key=lambda kv: -kv[1])[:25]
print('\n'.join('%-4d %s' % (n, p) for p, n in top))
"
```

Describe in detail: the top ~25 by fan-in, plus every entry point the digest listed. Cover the rest in one
line each, grouped by directory. State the cutoff you used in the document.

### 3. Describe each module, with its graph neighbourhood attached

For each in-scope file, build the task prompt from the graph, not from the file alone:

```bash
python3 -c "
import json,sys; d = json.load(open('structure.json'))
p = sys.argv[1]
inbound = sorted({a for a,b in d['edges'] if b == p})
outbound = sorted({b for a,b in d['edges'] if a == p})
rec = next(f for f in d['files'] if f['path'] == p)
print('Imported by:', ', '.join(inbound) or 'nothing in this repo')
print('Imports:', ', '.join(outbound) or 'nothing in this repo')
print('Symbols:', ', '.join('%s (%s:%d)' % (s['name'], p, s['line']) for s in rec['symbols']))
print('Exact parse:', rec['exact'])
" src/api.py
```

Dispatch one task per module, in parallel batches, each shaped like this:

```
File: src/api.py  (412 lines, exact parse: true)
Imported by: src/main.py, src/worker.py
Imports: src/db.py, src/auth.py
Symbols: ApiServer (src/api.py:31), handle_request (src/api.py:88)

In 5 sentences, state this module's ROLE IN THE SYSTEM -- what responsibility it
holds for the modules that import it. Cite path:line for each claim.
Do not speculate about modules not listed above.

<file contents>
```

Collect the descriptions into one JSON file keyed by path. They are short, so the whole set fits in context
for the next step even when the sources did not.

### 4. Synthesize the architecture

With the graph and the descriptions — both small — write the overview: layers, entry points, the main data
flow path, and the boundaries between subsystems. This is the one step where the whole system is visible at
once, which is exactly why the earlier steps compress rather than judge.

### 5. Cross-check every structural claim before writing

For each "X uses Y", "X is called by Y", "X depends on Y" in the draft, confirm the edge exists:

```bash
python3 -c "
import json; d = json.load(open('structure.json'))
edges = {(a,b) for a,b in d['edges']}
for a,b in [('src/api.py','src/db.py'), ('src/worker.py','src/auth.py')]:
    print('OK  ' if (a,b) in edges else 'BAD ', a, '->', b)
"
```

Delete or correct every `BAD` line. Report how many claims were checked and how many failed — a non-zero
count is worth stating, since it is the failure mode this whole pipeline exists to catch.

### 6. Write the document

Default path `docs/ARCHITECTURE.md`. If it already exists, read it and confirm before overwriting.

## Output format

```markdown
# Architecture

<2-3 sentences: what this system does and its dominant organising idea>

## Entry points

| Entry | Path | Starts |
| ----- | ---- | ------ |
| CLI | `src/main.py:12` | request loop via `ApiServer` |

## Layers

**API** — `src/api.py`, `src/routes.py`
Accepts requests, validates, delegates to services. Imported by `src/main.py:8`.

**Storage** — `src/db.py`
Connection pooling and query execution. Highest fan-in in the repo (14 modules).

## Main flow

1. `src/main.py:12` binds the socket and constructs `ApiServer` (`src/api.py:31`).
2. `src/api.py:88` authenticates via `src/auth.py:44`.
3. `src/db.py:120` executes the query and returns rows.

## Module reference

| Path | Fan-in | Role |
| ---- | ------ | ---- |
| `src/db.py` | 14 | Connection pool and query execution |

## Coverage

- files scanned: 412 of 412
- described in detail: 25 (fan-in >= 3, plus 4 entry points)
- summarised in one line: 387
- exact parse: 380; regex-approximated: 32 (Go, TypeScript)
- structural claims checked against the graph: 41; corrected: 2
- skipped: none
```

Mark any claim resting on a regex-approximated file with *(approximate)*.

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `scripts/scan_repo.py` | Step 1, always — before reading any source file. Run it; you do not need to read it. |

## Side effects

Writes `structure.json` to the working directory and `docs/ARCHITECTURE.md` (or a path you name). Reads the
working tree only. Uses `git ls-files` when the target is a git repository so ignored files are skipped; falls
back to a filtered directory walk otherwise. No network access, no package installation — standard library
only.

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report what was done and what was skipped; never claim success for something that was not verified. A partial
  result reported honestly is more useful than a complete result that is not true.
- Report failures with the actual output, not a paraphrase.
- Confirm before anything destructive or hard to reverse, and before anything outward-facing. Approval for one
  action does not carry to the next.
- Look at the target before overwriting or deleting it.
- Assume no network access and no package installation.
- Match the surrounding document's naming, structure, and idioms. Prefer editing what exists over generating a
  parallel new thing.
- Produce exactly the output format defined above, with no commentary wrapped around it.
