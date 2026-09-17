# Publish — promote the sealed draft

`publish` performs no rendering, prose checking, or quality review. It verifies the seal produced by the
successful final `review`, then atomically promotes `.docs-build/rendered-docs/` to `docs/`.

**P4 is an enforced checkpoint.** The first `review` opens it when `check_prose` queues content. That run
normally returns `review_required`; the queue is the condition that opens the checkpoint. The driver refuses
the reviewed `review` and all later components until
`decide --checkpoint P4` records the judgement.
`review_required` remains the quality verdict for queued blocks without a review; P4 is what stops the
workflow and puts those blocks in front of a reviewer.

The seal binds the rendered tree, `doc.json`, and `generation-report.json`. Editing any one after review makes
publication fail. A missing seal, a non-passing report, or a changed draft also fails without touching `docs/`.
Promotion copies the draft to a sibling temporary directory and swaps directories; if the swap fails, the
previous target is restored.

```bash
python3 scripts/pipeline.py render --docs docs
python3 scripts/pipeline.py review
# write reviews, decide P4
python3 scripts/pipeline.py review --review .docs-build/prose-review.jsonl
python3 scripts/pipeline.py publish --docs docs
```

Inspect the staged diff before the last command. The published tree is exactly the reviewed tree, excluding
transient `_build/` output.

**`--check` answers with one of six outcomes, and `unwired` and `skipped` are not passes.** Neither fails the
run; reporting either as a pass is the failure that distinction exists to prevent. **A project with no
`conf.py` cannot build what you just wrote**, and the run says so — `--write-conf --project "<name>"`
generates one, and only when the directory has none. Do not hand-write one either. The outcomes, the formats
and the rest are in [`rendering.md`](rendering.md); read it before rendering into a
project that already has documentation in it.

## Final review happens before publish

Every check before this asks whether a statement had evidence; none asks whether the sentence a reader sees
still says what it said. **A block may not use a stronger relationship verb than its sources carry** — an
import proves a reference, so it may not be rendered *depends on* — and **a reading must stay a reading**.
Read every `P003` and `P004`: they are promotions, not style.

**Pause here — P4.** A verdict of `confirmed` accepts the exact wording and evidence identified by its
hashes. Put each queued block next to its evidence and ask before writing the file. A later edit makes that
review stale and requires another model review; a block id alone never approves changed content.

Write verdicts to `.docs-build/prose-review.jsonl` and run `review` again:

```bash
python3 scripts/pipeline.py decide --checkpoint P4 --note "<what the review decided>"
python3 scripts/pipeline.py review --review .docs-build/prose-review.jsonl
```

A queued block you did not decide is reported as undecided, never as passed, and holds the run at
`review_required` — which is honest. Ranks, ceilings and the review format are in
[`prose-rules.md`](prose-rules.md).

## 8. Read the report against your own run

`review` ends with the quality gate and seal, and this is the one number you do not get to argue with. Read
`analysis_mode` first, then `status` and its `reasons`.

**`analysis_mode` is the honest summary**, and no other check can produce it: every other stage passes on a
document derived entirely from `structure.json`, because a claim taken out of the index and checked against
the index agrees with itself. Modules outside `units.txt` are counted apart and never lower the coverage —
staying inside the budget is the plan, not a shortfall.

**It reads two figures, and they call for different work.** A module counts as *read* when it answers two of
`responsibility`, `state`, `interface`, `failure`, and *answered in full* when it answers all four — the ones a
module page renders as headings. `derived_only` means fewer than half were read and is never `passed`, however
green everything else is. `partial` with high coverage and low `full_coverage` is the other failure and the
easier one to miss: every module is present and most are a line long. The first calls for dispatching the
modules nobody read; the second for going back to the ones already done and asking what they did not answer.
The reason line says which of the two you have.

**Detector B** reports under `architecture`. It compares your components against the directory tree by
counting module pairs, not by comparing names, so renaming every folder does not fool it. `failed` means the
grouping is the tree; `not_applicable` means there was no partition to compare and is **not** a pass.

**The flow and operations figures are counts, not percentages** — one flow traced and one refused is not
"50% documented". Naming nothing and giving no reason holds the run back; `absent` with a reason does not.

Then state, from the artefacts rather than memory: files scanned and skipped, the fan-in cutoff,
`analysis_mode` and the counts behind it, claims verified, what is candidate or unsupported and why, what was
traced and what was not, whether a diagram was generated, whether the build check passed or was skipped, and
that `.docs-build/` can be deleted.
