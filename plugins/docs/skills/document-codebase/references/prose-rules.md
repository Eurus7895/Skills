# What a sentence may say

Every other check in this pipeline asks whether a statement had evidence. This one asks whether the sentence
a reader ends up seeing still says what that statement said.

Between `module-analysis.jsonl` and a rendered page sits a rewrite, and a rewrite is where a relationship
gets promoted. `calls` becomes *owns*. `imports` becomes *depends on*. An `inferred` rationale loses its
hedge and becomes the reason the boundary exists. **None of that is caught by anything upstream**: the claim
is still verified, the statement still cites its line, the page still passes every coverage check — and the
reader has been told something nobody established.

```bash
python3 scripts/publish/check_prose.py .docs-build/doc.json \
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
every manual section, every block resting on a reading, and every block using a rank-5 or rank-6 verb. The
agent writes version 2 review records bound to the exact content and inputs it reviewed:

```json
{"review_version": 2, "review_id": "rev-1", "target_id": "section:usage/configuration:1",
 "draft_revision": "rev-0001", "verdict": "confirmed", "review_mode": "self_review",
 "reviewer": "documentation-agent", "content_hash": "sha256:...",
 "index_hash": "sha256:...", "scope_hash": "sha256:...", "analysis_hash": "sha256:...",
 "findings": []}
```

Copy `target_id`, `draft_revision` and the hash fields from `prose-report.json`'s `review_queue`; do not
reconstruct them from memory. The checker recomputes them from the current document when the review returns.

`confirmed` only applies while the content and input hashes still match. `changes_requested` fails the prose
gate; `unresolved`, a missing row, or a stale row leaves the run at `review_required`. Malformed and duplicate
records are refused rather than silently treated as missing. The complete schema is in `schemas.md`.

`review_required` ranks below `partial` in the quality gate and above `failed` — it can never be reported as
a pass, and a real defect still outranks "could not tell".

## Content review criteria for manual sections

Before assigning `confirmed`, the model reviewer checks all of the following against the source and the
question-to-source mapping:

- **Support:** the cited code or repository documentation supports the actual claim and its certainty.
- **Coverage:** the section answers the assigned questions, including relevant conditions, failure behavior
  and limits. Mentioning a component or attaching a citation is insufficient.
- **Reader usefulness:** the explanation enables the intended reader to understand a mechanism or perform
  a task using the project's actual commands, settings, inputs and outputs where relevant.
- **Specificity:** ask whether the paragraph could describe an unrelated repository after changing only its
  name. If so, inspect what concrete information is missing. This is a review heuristic, not a keyword rule.
- **Composition:** prose contains no TODOs, instructions to an author, copied schema examples or pipeline
  progress reports standing in for product information. Necessary uncertainty identifies the specific gap.

Use `changes_requested` for generic or incomplete content, with a stable finding ID and the missing detail
in `requested`. Use `unresolved` when evidence cannot settle the reading. A sequential second pass reports
`self_review`; do not claim independent review. Deterministic validators check format and consistency;
semantic adequacy remains the model reviewer's responsibility.
