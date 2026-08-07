---
name: synthesize-corpus
description: Answer counting, ranking, and exhaustive-coverage questions over a body of text far larger than
  the context window — logs, support tickets, contracts, transcripts, papers, exports — by extracting every
  source unit into one fixed-schema table and computing the answer from the table instead of reading. Use when
  the request needs totals, rankings, "all the places where", "how many", "which ones", or a per-item
  comparison across hundreds or thousands of files or records, and skimming a sample would not be a real
  answer. Use for phrasings like "go through all of these", "how many of them", "top 3 reasons", "find every",
  "compare across", "audit these". For a codebase specifically, use `document-codebase` instead. Do not use
  when the corpus fits in context, or when the answer is a passage to look up rather than a figure to compute.
---

# Synthesize a corpus larger than the context window

Turn an unreadable corpus into one table with a fixed schema, verify that every source unit is represented,
then compute the answer from the table. The deliverable is a table file plus a findings report whose every
number came from a query, not from reading.

## When to use this skill

- The corpus exceeds the context window, or would consume most of it.
- The answer is a **count, ranking, total, or complete list** — "how many contracts deviate", "top 3 churn
  reasons", "every call site missing a retry".
- Missing an item is a real failure: audit, compliance, security, billing.
- The user asks for a **comparison across items** that needs the same fields pulled from each one.

## When not to use this skill

- **The corpus fits in context.** Read it directly. This pipeline costs several round trips and is slower for
  small inputs.
- **The question is retrieval, not aggregation** — "what does the warranty clause say?". Search or grep for the
  passage and answer. Retrieval questions need a few good hits; this skill is for questions that need all of
  them.
- **The corpus is a codebase.** Use `document-codebase`, which gets exact structure from a parser instead of
  paying a model to guess it.
- **Fewer than ~50 units.** Handle them directly; the coverage machinery is not worth the overhead.

## Hard rules

These hold for every run. Violating any one produces a table that looks right and is wrong.

1. **Extract facts, never judgments.** An extraction task returns field values found in its unit. It does not
   rank, score, decide relevance, or answer the user's question. A unit-level judgment is made blind to the
   other units and cannot be recovered later.
2. **Fix the schema before extraction starts**, and enumerate every categorical field's allowed values in the
   prompt. Filtering an open-vocabulary field silently misses synonyms.
3. **Probe with an open question before writing any closed filter.** Ask the data what values it contains; do
   not assume the term. A keyword guess that finds nothing is indistinguishable from a corpus that contains
   nothing.
4. **Compute in code, not by reading.** Counts, sums, rankings, and group-bys come from querying the table. A
   figure the model produced by looking at rows is not a result.
5. **Every row carries the id of the unit it came from.** A finding without a source cannot be checked.
6. **Verify coverage before reporting any number.** Run `scripts/assemble.py`. If units were dropped, every
   count derived from that table is wrong — fix the extraction and re-run before reporting.

## Steps

### 1. Size it and confirm the shape

Count units and bytes before anything else:

```bash
ls corpus/ | wc -l
du -sh corpus/
```

If the total fits comfortably in context, stop and read it directly — say that is what you are doing and why.

### 2. Probe: let the corpus state its own vocabulary

Read a handful of units in full and, where the format is regular, extract the distribution of the field you
intend to filter on. For a log:

```bash
awk '{print $3}' corpus/server.log | sort | uniq -c | sort -rn | head -20
```

The point is rule 3: discover that severities are `SEVERE`, not `ERROR`, before a filter silently returns zero.
Report what the probe found. If a field turns out to be free-form prose, it must be a model-labelled
categorical field in step 3, not a grep target.

### 3. Declare the schema

Write it down before extracting. Every field gets a name, a type, and — for categoricals — the closed list of
allowed values.

```
source     string    the unit id (filename or record id)
topic      enum      price | bug | support | missing-feature | other
severity   enum      low | medium | high
amount     number    empty when the unit states none
quote      string    <=20 words, copied verbatim from the unit
```

Include a verbatim `quote` field. It makes each row spot-checkable against its source and is the cheapest
defence against fabricated values.

### 4. Narrow deterministically before spending a model on anything

Cut the corpus with code first — it is free and exact:

```bash
grep -rl "payment" corpus/ > candidates.txt
wc -l candidates.txt
```

Report how many units the filter removed and on what criterion. If the criterion could plausibly miss units,
skip this step rather than narrowing on a guess.

### 5. Extract, one unit per row, in parallel

Dispatch one extraction task per unit (or per shard of units, when units are small), in parallel batches.
Give every task the same prompt shape:

```
Return one JSON object per line. No prose, no markdown fence.
Schema, all fields required:
  source: "<unit id>"
  topic: one of [price, bug, support, missing-feature, other]
  severity: one of [low, medium, high]
  amount: number, or null if the text states none
  quote: <=20 words copied verbatim supporting `topic`

Do not rank, score, or judge importance. Report only what this text states.
If a field is not stated, use null -- never guess.

<unit text>
```

Append every task's output to one JSONL file. Keep raw output; do not clean it by hand.

### 6. Assemble and verify coverage

Run the validator. **Run it; you do not need to read it.**

```bash
python3 scripts/assemble.py \
  --input rows.jsonl \
  --schema source,topic,severity,amount,quote \
  --units 500 \
  --out table.csv
```

It reports parse failures, schema failures, units that produced no row, fields that came back mostly empty,
and fields that came back nearly constant. Exit code 1 means at least one problem.

Do not proceed while it exits 1. Re-run the failed units, then validate again. If some units genuinely cannot
be extracted, record how many and name them in the report.

### 7. Compute the answer

Query the table. Never eyeball it.

```bash
python3 -c "
import csv, collections
rows = list(csv.DictReader(open('table.csv')))
print(collections.Counter(r['topic'] for r in rows).most_common())
print(sum(float(r['amount']) for r in rows if r['amount']))
"
```

### 8. Report

Use the output format below. Every figure traces to the query that produced it.

## Output format

Produce exactly this, with no commentary around it:

```
## <question restated>

<direct answer, one or two sentences>

| <group>          | count | share |
| ---------------- | ----- | ----- |
| price            |   214 |  43%  |
| bug              |   139 |  28%  |
| support          |    97 |  19%  |

Evidence
- price     t-0412 "renewal quote doubled with no warning"
- bug       t-0876 "export silently truncates at 1000 rows"

Coverage
- units in corpus: 500
- units extracted: 500
- units dropped:   0
- narrowing applied: none

Method
- schema: source, topic, severity, amount, quote
- figures computed from table.csv by query, not by reading
```

State `units dropped` even when zero. When it is not zero, name the dropped units and say plainly that the
figures cover only the extracted set.

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `scripts/assemble.py` | Step 6, always. Run it; you do not need to read it. |

## Side effects

Writes `rows.jsonl`, `table.csv`, and any narrowing files into the working directory. No network access, no
package installation — the script is standard library only.

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report what was done and what was skipped; never claim success for something that was not verified. A partial
  result reported honestly is more useful than a complete result that is not true.
- Report failures with the actual output, not a paraphrase.
- Confirm before anything destructive or hard to reverse, and before anything outward-facing. Approval for one
  action does not carry to the next.
- Look at the target before overwriting or deleting it.
- Assume no network access and no package installation.
- Produce exactly the output format defined above, with no commentary wrapped around it.
