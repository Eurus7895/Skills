# What a sentence may say

Every other check in this pipeline asks whether a statement had evidence. This one asks whether the sentence
a reader ends up seeing still says what that statement said.

Between `module-analysis.jsonl` and a rendered page sits a rewrite, and a rewrite is where a relationship
gets promoted. `calls` becomes *owns*. `imports` becomes *depends on*. An `inferred` rationale loses its
hedge and becomes the reason the boundary exists. **None of that is caught by anything upstream**: the claim
is still verified, the statement still cites its line, the page still passes every coverage check — and the
reader has been told something nobody established.

```bash
python3 scripts/check_prose.py .docs-build/doc.json \
    --architecture .docs-build/architecture-analysis.json \
    --flows .docs-build/flow-analysis.json \
    --operations .docs-build/operations-analysis.json \
    --require-review --review .docs-build/prose-review.jsonl \
    --out .docs-build/prose-report.json
```

## Rule 1 — no verb stronger than the source carries

Relationship verbs are ranked by how much they claim:

| Rank | Verbs |
| --- | --- |
| 1 | references, mentions, names, reads from |
| 2 | imports, includes, pulls in |
| 3 | uses, consumes, reads |
| 4 | calls, invokes, delegates to, dispatches to |
| 5 | depends on, requires, relies on, needs |
| 6 | owns, manages, controls, drives, orchestrates, governs, is responsible for |

A block citing **statements** may use the strongest verb any of those statements uses, and no stronger — the
analysis's own words are the ceiling. A block citing only **claims** gets the ceiling of the claim kind:

| Claim kind | Ceiling | Because |
| --- | --- | --- |
| `imports`, `defines`, `contains` | 2 | An import proves a reference between two files and nothing about what either does with the other |
| `calls`, `inherits` | 4 | A call read at its call site proves invocation, not authority |
| `responsibility` | 6 | Someone read the code and wrote what the module is for |

Saying *less* than the source supports is never a finding. `P003` is the code.

The list is deliberately short. A longer one catches more promotions and also flags ordinary English —
"handles", "provides", "supports" say nothing precise about a relationship, and findings nobody can act on
are how a checker gets switched off.

## Rule 2 — a reading must stay a reading

A block resting on an `inferred` statement must carry a hedge. So must a block rendering any text the
architecture, flow or operations analysis recorded as `inferred` or `unknown` — those tables are rendered
mechanically and carry no citation, so rule 1 cannot reach them, but a status is one field and dropping it
is a one-line change. `P004` is the code.

Hedge markers: *inferred*, *not observed*, *not recorded*, *appears to*, *seems to*, *probably*, *may*,
*might*, *nobody answered*, *does not say*, *no reason*, *unknown*, *cannot be*, *could not be*. A table
column header counts — a rationale table titled "The question nobody answered" is hedged by its own heading.

**A rationale recorded as `unknown` is the seeded contradiction to watch for.** Naming the open question is
the answer; asserting it is not.

## What is not checked, and why

A block carrying no citation is the generator's own framing — the sentence above a table, the "nothing here,
and why" line. It is not a rewrite of anything, so it is listed as `P005` advisory rather than failed.

Rule 2 matches the source text verbatim, because that is what the renderer emits: the hedge is a prefix on
the analysis's own sentence. **A rewritten sentence escapes it.** That is the model pass's job, not the
deterministic one's — say so rather than implying the check is tighter than it is.

## The bounded model pass

What survives the two rules goes to a model pass, which `check_prose.py` does not run. It builds the queue —
every block resting on a reading, plus every block using a rank-5 or rank-6 verb, the two places where only
a person can tell a restatement from an upgrade — and the agent writes verdicts to a JSONL:

```json
{"block": "block:components-interaction-src/api.py", "verdict": "ok"}
{"block": "block:rationale-recorded", "verdict": "overstated", "note": "the reading became the reason"}
```

With `--require-review`, a queued block with **no** verdict leaves the run `review_required`. That is not a
pass and not a defect in what was checked: the budget ran out before anything was decided, and a person has
to look. It is the same distinction `sphinx_support.py` draws between `skipped` and `runner_failure`.

`review_required` ranks below `partial` in the quality gate and above `failed` — it can never be reported as
a pass, and a real defect still outranks "could not tell".
