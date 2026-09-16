# Question-driven manual

Read [documentation-template.md](documentation-template.md) before selecting scope and before writing
`.docs-build/manual-analysis.json`. The template's 25 sections are the content contract; the documentation-wide
review is an additional appendix page.

**The questions are the prompt, never the document.** They exist to make the run cover a subject and to say
what evidence each part rests on. A page that renders them as headings, with an answer under each, is a
filled-in questionnaire — which is what a reader gets handed instead of a manual. So the answers are notes in
`.docs-build/`, and the delivered page is *composed* from them: your headings, your prose, one section over
as many answers as it takes.

## Workflow

1. Select `--preset manual` explicitly. Survey the product purpose, actors, entry points and configuration as
   well as the dependency graph. Select evidence needed to answer the template, not merely high-fan-in files.
2. Run the existing survey, analyze and check components. Read source, configuration, tests and repository
   documentation to answer questions the structural index cannot answer. Keep module, architecture, flow
   and operations analyses as supporting evidence; a list of files is not a manual answer.
3. Initialize the answer artifact once (exclusive creation refuses to replace existing answers).
   **The initializer writes no prose.** It writes an unanswered slot per question and a `facts` list —
   the ids this run verified, grouped by what vouched for them. That is a reading list, not an answer:
   every sentence in the manual is yours to write. Pass the analyses so `facts` is complete;
   `config-analysis.json` needs no writing, since `survey` extracts and validates it.

   ```bash
   python3 scripts/document/manual.py --init .docs-build/manual-analysis.json \
     --index .docs-build/structure.json \
     --architecture .docs-build/architecture-analysis.json \
     --flows .docs-build/flow-analysis.json \
     --operations .docs-build/operations-analysis.json \
     --config .docs-build/config-analysis.json
   ```

   Each input is optional and is refused if it was written against a different scan. The command reports
   how many slots it wrote and how many facts are available to cite. `pipeline.py document` does all of
   this for you on a first run, passing whichever of the four exist.

4. Replace each unknown draft with a project-specific explanation. A question about a component needs its
   responsibility, collaborators and mechanism; a question about a phase needs its inputs, processing,
   decisions, outputs and failure behavior. Use source paths for evidence and navigation, not as the answer.
   Include use cases in Introduction, design decisions and boundaries in System Overview, and precise
   processing behavior in Data Flow and Detailed Processing Phases. Do not invent authors' motivations.
   **These are notes.** Write them to be complete and citable, not to be read aloud.
5. **Compose each page** into `pages` (see below). Read that page's answers together and write the sections a
   reader needs: a heading that says what the section is about, and prose that reads as documentation. One
   section may draw on several answers, and should where the answers overlap — three questions about
   configuration are usually one section, not three.
6. Run `python3 scripts/pipeline.py document --preset manual`, then publish. The builder checks complete
   question IDs, scan identity, repository-relative evidence line ranges, that every `confirmed` answer
   names a `verified_ids` entry some validator already passed, and that every composed section stays inside
   what its answers cite. It does not prove that a sentence is true or sufficient, so **every composed
   section enters the prose review queue.**
7. Review the rendered RST: does it read as a manual, and does each section still say what its answers said?
   Correct the notes or the composition in `manual-analysis.json` and rebuild; do not patch generated RST
   because the next build replaces it. Review verdicts apply to section blocks
   `section:<page-id>:<n>`. Unknown answers and missing mandatory diagrams keep the quality report
   incomplete; an answered question no section uses **fails** it.

## Answer contract

`manual_version` is `2`; `index_hash` must match the current scan. `answers` maps every stable question ID
(`1.1.1`, `1.1.2`, ..., `5.7.6`, and `review.1` ... `review.8`) to one answer. The bundled
`manual_questions.json` is the machine-readable mapping; the initializer writes all IDs.

```json
{
  "manual_version": 2,
  "index_hash": "<current index_hash>",
  "answers": {
    "1.1.1": {
      "basis": "observed",
      "completeness": "complete",
      "content_review": "pending",
      "text": "Explain the actual product and the problem it solves, using the cited evidence.",
      "evidence": [{"path": "README.md", "line_start": 1, "line_end": 12}],
      "verified_ids": ["claim:imports:src/api.py:src/service.py", "op:test"],
      "facets_missing": []
    }
  }
}
```

The excerpt shows one answer; a valid artifact contains every question. Use plain text in `text`, with
paragraph breaks where helpful; the renderer owns RST/MyST syntax. Do not paste escaped RST directives.

**`unknown` is for a question the repository does not answer, not for one nobody looked up.** This is the
rule the other three hang off, and the one worth stating first, because the incentives run the other way:
`confirmed` costs evidence and a verified id, `inferred` costs evidence, and `unknown` costs a sentence.
A run that answers nothing is therefore cheapest, entirely honest question by question, and worthless — so
the gate refuses it. **Under half the template answered is `answer_mode: unanswered`, which can never pass**,
the same way `derived_only` can never pass on the analysis side. Before writing `unknown`, look: the README,
the packaging manifest, the CI workflow, the configuration, the tests, the source. `inferred` is the status
for what the repository shows without stating, and it is a real answer — reaching for `unknown` instead of
`inferred` is the failure this rule is about.

**One sentence repeated across the template is not a set of answers, and the build refuses it.** A run
once answered every question with the same generic text citing the same line range, and every check
passed: the count was right and each citation resolved. Past 30% of the answered set sharing one
answer, the build stops — questions asking different things cannot honestly share an answer. Identical
`TODO` placeholders in a fresh draft are exempt: that is the initializer saying nothing yet.

- `basis: observed` or `declared`: the repository settles it — evidence **and at least one `verified_ids`
  entry**, something a validator could have rejected.
- `basis: inferred`: supported interpretation with evidence, visibly labelled Inferred. Explain its limits.
- `unknown`: only once you have looked and the repository is silent. Give a concrete `next_check` naming what
  to inspect or whom to ask — a real next step, not the question restated. Keep the question; do not silently
  omit it or call the manual finished.
- `not_applicable`: explain why, and record `reviewer` only after an actual reviewer confirms applicability.
  Never fabricate review. Keep the explanation in the delivered page.

Evidence locations must exist within `--root` and have valid line ranges. For external evidence, record the
reference in a repository document and cite that location; do not make inaccessible sources look verified.
The documentation-wide review records revision, audiences, sources, uncertainty and lifecycle coverage.

## Composition contract — `pages`

`pages` maps a template page id to the sections a reader will see. **This, not `answers`, is the document.**

```json
"pages": {
  "getting_started/installation": {
    "sections": [
      {"heading": "Prerequisites",
       "body": "OrderLog runs on Python 3.9 or newer. No other runtime is declared.",
       "answers": ["1.2.1", "1.2.5"]}
    ]
  }
}
```

`heading` and `body` are yours. `answers` names the notes the section was written from, and everything else
is derived from them — `evidence` and `verified_ids` default to the union of what those answers cite, and the
status is the weaker of theirs.

Five rules, all checked before `doc.json` is written:

- **A heading is not a question.** A trailing `?` is refused outright. The question asked what to find out;
  the heading says what the section is about.
- **A section names at least one answer, and only answers on its own page.** Prose attached to nothing is
  prose nothing checked.
- **Only `confirmed` and `inferred` answers can be composed.** An `unknown` is a gap and an
  `not_applicable` is an exclusion; both are reported on the page, neither is written up as content.
- **Composition may narrow what an answer rests on, never add to it.** A section may cite fewer locations
  than its answers do — that is editing. Citing one they do not is provenance nothing checked, and is the
  failure this whole contract exists to prevent.
- **One `inferred` answer makes the section `inferred`**, however many confirmed ones sit beside it.
  Surrounding a reading with facts does not turn it into one.

**Every composable answer must reach some section on its page.** An answer the run paid for and then dropped
fails the quality gate rather than passing quietly — it is a defect in the composition, not a gap in the
repository. Gaps are collected into one marked block per page instead of being scattered through the prose:
what is not documented, what is not applicable, and what is answered but not yet written up.

## `verified_ids` — what separates `confirmed` from `inferred`

**A citation that resolves is not a citation that supports.** `src/api.py:34-51` can exist, be in range, and
have nothing to do with the sentence beside it; nothing downstream catches that, because the prose review
queue is looking for verb inflation rather than fabricated support. So the status that asserts *the
repository settles this* has to borrow its standing from a check that could have failed, and name it.

`verified_ids` accepts an id from any of five files, each already validated by the script that owns it:

| Id | Comes from | What passed |
| --- | --- | --- |
| `claim:…` | `claims.verified.jsonl` | `verify_doc.py` read it against the graph, or at its call site. Must be `verified` — a `candidate` is an unchecked citation, not a weaker one |
| a statement id | `module-analysis.jsonl` | `validate_analysis.py`, and the status is `declared` or `observed`. An `inferred` statement is the model's own reading and cannot confirm another one |
| `op:…` | `operations-analysis.json` | `validate_operations.py` matched the command or value character for character (`O006`) |
| `flow:…` | `flow-analysis.json` | `validate_flows.py` proved every step is a call verified at its call site (`F006`) |
| `component:…` | `architecture-analysis.json` | `validate_architecture.py` checked the shape and the evidence (`B002`–`B012`) |
| `config:…` | `config-analysis.json` | `validate_config.py` matched the setting's name against the lines it cites (`C006`) |

An id none of them holds is refused outright — the build stops rather than downgrading the answer, because
an id that reads as provenance and carries none is worse than no id. An answer you cannot back this way is
`inferred`, which is a real answer and says so on the page; the bar is not raised for `inferred`, or honest
readings would be pushed down to `unknown`.

This is also what puts the three analyses back to work in this preset. Without it they are written on every
manual run and rendered nowhere: the commands `validate_operations.py` quoted are spent, and the traced
flows behind the data-flow diagram vouch for no sentence.

## Prefill — the eight questions the analyses already answered

Pass the analyses to the initializer and it answers the questions they settle, leaving the rest `unknown`:

```bash
python3 scripts/document/manual.py --init .docs-build/manual-analysis.json \
  --index .docs-build/structure.json \
  --architecture .docs-build/architecture-analysis.json \
  --flows .docs-build/flow-analysis.json \
  --operations .docs-build/operations-analysis.json
```

| Question | Filled from |
| --- | --- |
| `1.2.1` prerequisites | the declared `requirements` |
| `1.2.3` how to install | the `install` and `build` procedures, with their commands |
| `2.1.1` the major components | the components and the modules each holds |
| `2.1.3` how components interact | the relationships, named by their endpoints |
| `2.2.1` inputs, transformations and outputs in order | the traced flows, step by step |
| `3.1.1` the primary entry point | the `run` procedures |
| `4.2.3` which commands run the suite | the `test` procedures |
| `4.5.4` which commands build a release | the `deploy` and `release` procedures |
| `1.2.6` which environment variables are required | the extracted `env` settings |
| `3.1.2` which arguments and options are required | the extracted `option` settings |
| `3.2.1` the configuration schema's fields | every extracted setting |
| `3.2.2` defaults and required status | the extracted defaults and `required` flags |

**The point is not saving typing.** A prefilled answer quotes its analysis rather than paraphrasing it, so a
command arrives on the page exactly as `O006` matched it and a flow arrives as the steps `F006` verified.
The same sentence written freehand over the same material carries none of that.

The list is short on purpose. A mapping earns its place only where the analysis holds *the answer*, not
something adjacent: `usage/configuration` asks for a configuration schema and the operations analysis has
procedures for configuring, which is a different question, so it is not prefilled. A prefilled answer that
is true and says nothing is the failure `A014` exists to catch, and it would arrive already marked
`confirmed`.

Nothing else is guessed. Every other question keeps its `unknown` status and its own text as the
`next_check`, and a kind the analysis never recorded leaves its question open rather than growing an empty
heading. Prefilled answers are ordinary answers: correct them, and they go through the prose review queue
like the rest.

## Diagrams

Only `architecture/class_diagram.rst` and `architecture/data_flow.rst` require diagrams. Other pages answer
questions in prose; no diagram is required there. Class diagrams come from the existing class manifest;
flow diagrams come from the validated flow manifest. Both pages must explain the diagram and its limits.
Do not invent classes for a function-only repository or call relationships from import edges. If the scanner
cannot establish the required view, disclose the missing evidence and keep the result incomplete.

## Migration

The template replaces the old manual layout. `processing_flow` becomes `data_flow`; `class_diagrams` becomes
`class_diagram`. Fold boundaries and design decisions into Overview; consolidate invocation examples under
`usage/invoking`; split release and CI/CD into separate pages. Every template section is generated from
answers, including pages previously left to an author. Existing files at old paths are not automatically
removed. Inspect and migrate valuable authored content into answers, then obtain authorization before
removing obsolete generated pages or changing an owned toctree.
