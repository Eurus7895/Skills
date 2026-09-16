# Publish — what a reader gets, and whether the run is done

The last component, run twice: once to render, then again with `--review` once you have decided the prose
it queued. Render outcomes and formats are in [`rendering.md`](rendering.md), the verb ranks and the review
format in [`prose-rules.md`](prose-rules.md).

**P4 is an enforced checkpoint.** The first successful publish opens it only when `check_prose` queued
content. The driver then refuses the reviewed publish until `decide --checkpoint P4` records the judgement.
`review_required` remains the quality verdict for queued blocks without a review; P4 is what stops the
workflow and puts those blocks in front of a reviewer.

**Look at `docs/` before you run this.** This is the step hard rule 8 is about: the renderer writes each page
with `"w"` and will replace a hand-written `index.rst` or a page of the same name without saying so. If
anything is there, list what would be overwritten and ask first — `git status` afterwards is not a safety net.

```bash
python3 scripts/pipeline.py publish --docs docs
```

Renders the pages, checks the sentences against the analyses behind them, and reports on the run.

- **Read** the page count, the `--check` verdict, the prose findings and the queue.
- **Decide** nothing about markup — the renderer owns headings, tables, references, escaping and the toctree.
  **Do not write RST, MyST or Sphinx directives yourself.**

**`--check` answers with one of six outcomes, and `unwired` and `skipped` are not passes.** Neither fails the
run; reporting either as a pass is the failure that distinction exists to prevent. **A project with no
`conf.py` cannot build what you just wrote**, and the run says so — `--write-conf --project "<name>"`
generates one, and only when the directory has none. Do not hand-write one either. The outcomes, the formats
and the rest are in [`rendering.md`](rendering.md); read it before rendering into a
project that already has documentation in it.

## 7. Decide the prose the checker queued, then rerun

Every check before this asks whether a statement had evidence; none asks whether the sentence a reader sees
still says what it said. **A block may not use a stronger relationship verb than its sources carry** — an
import proves a reference, so it may not be rendered *depends on* — and **a reading must stay a reading**.
Read every `P003` and `P004`: they are promotions, not style.

**Pause here — P4.** A verdict of `ok` is you telling the reader the stronger sentence is true, on evidence
that does not carry it. Put each queued block next to its evidence and ask before writing the file.

Write your verdicts to `.docs-build/prose-review.jsonl` and run the component again:

```bash
python3 scripts/pipeline.py decide --checkpoint P4 --note "<what the review decided>"
python3 scripts/pipeline.py publish --docs docs --review .docs-build/prose-review.jsonl
```

A queued block you did not decide is reported as undecided, never as passed, and holds the run at
`review_required` — which is honest. Ranks, ceilings and the review format are in
[`prose-rules.md`](prose-rules.md).

## 8. Read the report against your own run

`publish` ends with the quality gate, and this is the one number you do not get to argue with. Read
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
