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

## How it has to read

Everything above is about being right. None of it is about being read, and a manual nobody finishes is a
manual that failed whatever its citations prove. These rules are the other half, and they are concrete so
that "make it clearer" is not the review note.

- **Lead with the answer.** The first sentence of a section states what happens, not what the section is
  about. "This section describes how orders are validated" tells the reader nothing they did not get from
  the heading. "An order is rejected before it reaches the queue when its SKU is unknown" is the answer.
- **One idea per sentence, and keep it under 25 words.** A sentence carrying three clauses is where the
  reader loses the thread, and it is the single most common defect in generated prose. Split it. Two plain
  sentences beat one accurate paragraph-long one.
- **Two to four sentences per paragraph.** A section that is one unbroken block is one nobody scans, and a
  reader who cannot scan cannot find the part they came for.
- **The seven-point shape is coverage, not an outline.** It lists what a section may owe a reader; it is not
  the order to write them in, and following it literally makes every section read the same. When two
  consecutive sections have the same beats in the same order, at least one is padded to fit the form — cut
  it to what that subject actually needs.
- **Name the thing, then say what it does.** Subject first. "`OrderService` writes each SKU to the store"
  reads; "each SKU is written to the store by `OrderService`" makes the reader hold the object until the
  end of the sentence to find out who did it.

**Readability is not brevity.** A section may be long because the subject is; what it may not be is a single
25-line paragraph of 40-word sentences. The density floor elsewhere in this pipeline refuses a section that
replaced its answers with nothing; these rules refuse one that buried them.

## Model review before render

Review the draft against the assigned questions, grounding record, and cited source. Request changes when a
section omits a material facet, overstates evidence, remains generic, or is not actionable for its intended
reader. Repair `manual-analysis.json`, then review the changed content again. Rendering is a transformation,
not a content review.

**Read one page as a reader before you accept it**, and answer three questions about it rather than about
the answers behind it:

1. Does the first sentence of each section say something, or announce something?
2. Is there a sentence you had to read twice? That one is too long, and splitting it is the repair.
3. Do three consecutive sections open the same way? Then the shape is writing the prose, not the subject.

A page that passes every validator and fails these is a page that is correct and unread. Fix it in
`manual-analysis.json`, where the prose lives — never in the rendered output, which the next render
overwrites.
