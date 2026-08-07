# large-context

Answer questions over a body of material too large to read — thousands of log lines, tickets, contracts,
papers, or a whole repository — without pretending a sample is an answer.

Both skills follow the same shape, because it is the shape that makes the result checkable:

```
narrow with code  ->  extract every unit to a fixed schema  ->  verify coverage  ->  compute from the table
```

The ordering is the point. Extraction happens per unit, where a small context is enough. Judgement happens
afterwards, once every unit sits in one table — so a pattern spread across units is still visible, and a count
is a query rather than an impression.

## Install

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install large-context@CopilotBox
```

## Skills

- **`synthesize-corpus`** — for text corpora: logs, support tickets, contracts, transcripts, papers, exports.
  Defines the unit before counting anything, probes the corpus for its own vocabulary, extracts every unit
  against a typed schema, validates with `assemble.py`, and reports figures with source ids. Fires on "how many
  of these", "top 3 reasons", "find every", "audit these", "compare across".
- **`document-codebase`** — for repositories. Parses structure with `scan_repo.py` (Python via `ast`, other
  languages by import regex), ranks modules by fan-in, describes each one with its real importers supplied,
  then cross-checks every dependency claim against the graph before writing `docs/ARCHITECTURE.md`. Fires on
  "document this repo", "explain how this fits together", "map the dependencies".
- **`audit-codebase`** — sweeps a whole repository for one stated concern and reports every occurrence with
  `file:line` and a verbatim quote, each machine-checked against the real file by `verify_findings.py`. Every
  in-scope file emits a row even when clean, so coverage is provable rather than asserted. Fires on "audit this
  repo for X", "find every place that Y", "is this migration finished".

`audit-codebase` and the `code-review` plugin's `review-code` do not overlap: `review-code` reviews a
**change** — a diff, pull request, or working tree — against a review standard. `audit-codebase` sweeps the
**repository as it stands** for one concern, and its promise is completeness rather than judgement.

## Notes

- **Both skills refuse small inputs on purpose.** Under roughly 50 units, or a corpus that fits in context,
  they tell you to read it directly. The pipeline costs several round trips; it only pays above that threshold.
  The threshold counts **units**, not files — one log holding a million records is a million units.
- **Retrieval is not aggregation.** "What does the warranty clause say" is a search. These skills are for
  questions where missing an item is a wrong answer.
- **Coverage is verified, not assumed.** `assemble.py` fails on a unit that produced no row, a unit that
  produced two, a value outside its declared enum, or a non-numeric where a number was declared. It warns —
  without failing — on fields that look suspiciously empty or constant, since a legitimately sparse or skewed
  field must not block a correct extraction.
- **Import edges are not call edges.** `scan_repo.py` records imports; it builds no call graph. `document-
  codebase` verifies dependency claims against the graph and requires any "X calls Y" claim to cite a call site
  that was actually read, or be downgraded to the import claim the data supports.
- **A citation is checked, not trusted.** `audit-codebase` re-reads every cited file and confirms the quoted
  line is really there. A finding whose quote is absent is treated as fabricated and dropped, and the count of
  dropped findings is reported.
- Scripts are standard library only. They read the working tree and write their outputs (`rows.jsonl`,
  `table.csv`, `structure.json`, `findings.jsonl`, `docs/ARCHITECTURE.md`) into the working directory. No
  network, no installs. Symlinks resolving outside the scanned root are skipped and reported rather than
  followed.
- `scan_repo.py` and `assemble.py` are shared by more than one skill, so they are authored in `shared/scripts/`
  and materialized into each skill folder. Edit the source and run `python3 tools/materialize.py`; never edit
  the generated copies.
- `document-codebase` parses Python exactly and approximates JavaScript, TypeScript, Go, Rust, Java, Ruby, C,
  and C++ by import regex. Approximate records are flagged `"exact": false` and any claim resting on them is
  marked in the output.
