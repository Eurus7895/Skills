# Prose generation contract

Use this block only after survey, source reading, the three analyses, and answer validation. Its input is the
validated answer set plus `manual-grounding.json`; its output is a draft in `manual-analysis.json.pages`.
Validation proves that evidence exists and references are well formed. It does not write or approve prose.

## What each section must do

A reader-facing section must answer a concrete reader task, not replay a template question. Select the
relevant validated answers for one page, then synthesize them into the smallest coherent set of sections.
Each section should contain the applicable parts of this shape:

1. **Context or goal** — what the reader is trying to accomplish and when this behavior applies.
2. **Entry point and prerequisites** — the real command, API, event, configuration, or state that starts it.
3. **Mechanism** — the project-specific components involved and what each one does, in execution order when
   order matters.
4. **Decisions and configuration** — defaults, precedence, validation, branches, and conditions that change
   the behavior.
5. **Result and side effects** — returned values, files, state changes, emitted events, or visible output.
6. **Failures and limits** — verified failure behavior, unresolved boundaries, and facts the repository does
   not establish.
7. **Evidence** — repository-relative citations inherited from the answers; citations support the explanation
   but never replace it.

Not every section needs seven paragraphs. Installation may combine prerequisites, command, result, and
failure behavior. A processing section normally needs all of mechanism, decisions, result, and failures.

## Drafting rules

- Use names found in this repository: commands, types, settings, files, services, and outputs. If the prose
  could describe an unrelated repository after replacing the product name, it is not specific enough.
- Explain relationships, not inventories. “`OrderService` creates `Store` and records each SKU” is useful;
  a list of both class names is not.
- Preserve epistemic strength. Observed and declared behavior may be stated directly; inferred behavior must
  be qualified in natural prose. Do not emit internal labels such as `Evidence:`, `Inferred:`, or
  `Not documented:` as section body boilerplate.
- Do not include pipeline progress, question counts, review mechanics, TODOs, author instructions, or copied
  example prose in the product manual.
- Test code may corroborate behavior or failure cases, but test modules must not become product components,
  manual inventory entries, or diagram nodes.
- Keep an unresolved item explicit when its answer matters to the reader. Never fill the gap with a plausible
  convention.

## Model review before render

Review the draft against the assigned questions, grounding record, and cited source. Request changes when a
section omits a material facet, overstates evidence, remains generic, or is not actionable for its intended
reader. Repair `manual-analysis.json`, then review the changed content again. Rendering is a transformation,
not a content review.
