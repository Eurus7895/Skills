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

4. Complete the question-to-source mapping below and read its sources. Then replace each unknown draft with a project-specific explanation. A question about a component needs its
   responsibility, collaborators and mechanism; a question about a phase needs its inputs, processing,
   decisions, outputs and failure behavior. Use source paths for evidence and navigation, not as the answer.
   Include use cases in Introduction, design decisions and boundaries in System Overview, and precise
   processing behavior in Data Flow and Detailed Processing Phases. Do not invent authors' motivations.
   **These are notes.** Write them to be complete and citable, not to be read aloud.
5. Read [prose-generation.md](prose-generation.md), then **compose each page** into `pages` (see below). Read that page's answers together and write the sections a
   reader needs: a heading that says what the section is about, and prose that reads as documentation. One
   section may draw on several answers, and should where the answers overlap — three questions about
   configuration are usually one section, not three.
6. Run `python3 scripts/pipeline.py document --preset manual`, then `render`. The builder checks complete
   question IDs, scan identity, repository-relative evidence line ranges, that every answer with an
   `observed` or `declared` basis names a `verified_ids` entry some validator already passed, and that every
   composed section stays inside
   what its answers cite. It does not prove that a sentence is true or sufficient: deterministic prose
   checks examine every composed section, and **every manual section enters the model review queue**.
7. **Settle the six authored pages** (see below). Fill each scaffold `render` wrote into the draft, or waive it
   with an owner and a reason. The gate holds publication until every one is `complete` or `waived`.
8. Review `.docs-build/rendered-docs/`: does it read as a manual, and does each section still say what its answers said?
   Correct the notes or the composition in `manual-analysis.json` and rebuild; do not patch generated RST
   because the next build replaces it. Review verdicts apply to section blocks
   `section:<page-id>:<n>`. Unknown answers and missing mandatory diagrams keep the quality report
   incomplete; an answered question no section uses **fails** it. Run `review`, record P4 and fresh verdicts,
   rerun `review --review .docs-build/prose-review.jsonl`, then run `publish` only after the draft is sealed.

## Map the template to this repository

Before writing answers, create `.docs-build/manual-grounding.json` with the current `index_hash` and a
`questions` map keyed by every generated question ID. This is a model-authored working artifact: scripts do
not interpret or approve it. For each entry record:

- `project_question`: rewrite the prompt using the actual repository entities and the reader's task.
- `applicability`: `applicable`, `needs_evidence` or `not_applicable`, with a repository-specific reason.
- `sources_read`: actual file paths and line ranges inspected, and what each establishes. A search hit or
  generated packet alone is not a source reading.
- `answer_outline`: concrete behavior, conditions and consequences that the answer must explain.
- `remaining_checks`: unresolved questions and where to investigate next.

For configuration, locate the loader and its callers, defaults, environment and CLI overrides, validation
and failure paths. For processing, trace a real input from its entry point through transformations to an
output or failure. For installation, read packaging metadata and the actual startup path. Adapt these
investigations to the project; do not assume it has a server, database or deployment pipeline.

Group related questions while reading so the same source need not be loaded repeatedly, but account for each
question. Follow references beyond the initial module shortlist when needed. Test code may provide supporting
evidence; test modules remain outside the product inventory and product diagrams.

`needs_evidence` means continue investigating. Use an unknown answer only after documenting what was checked
and the specific fact still unavailable. `not_applicable` needs a concrete reason. Never fill an answer with
“Explain the actual product”, “The repository reads these settings”, or a restatement of the question.
Examples in this guide illustrate schema shape; their prose and IDs must not be copied as project facts.

## Review and repair the draft

The model reviewer reads each rendered section, the questions it covers, the grounding record and relevant
source. Apply the content review criteria in [prose-rules.md](prose-rules.md). A citation that exists does not
prove its paragraph answers the question. Record stable findings with the missing behavior or unsupported
claim and a concrete requested correction. Generic but accurate text still requires changes when it leaves
its assigned question unanswered.

Repair `manual-analysis.json`, update the grounding record if more source was read, rebuild, and review the
changed sections again. Do not manufacture `confirmed` records merely to clear a gate. If the agreed budget
runs out, leave the draft at `changes_requested` or `unresolved` and report the remaining findings.

The documentation-review appendix describes the covered product revision, intended audiences, verified
scope, specific uncertainties and limitations. Pipeline execution counts, Sphinx success and claims-checking
summaries belong in the generation report. Do not use them as answers about the product or as filler in
`documentation_review.rst`.

## The six pages the run does not answer

`appendix/troubleshooting`, `faq`, `glossary`, `references`, `compliance` and `changelog` carry 38 template
questions between them that **no repository answers**. What users actually ask, which terms need defining,
what a compliance position is — none of that is in the source, and asking the run for it would buy 38 more
`unknown`s and drag `answer_mode` down for gaps that were never the run's to fill.

They are not silent, though. Each carries a row in **`.docs-build/authored.jsonl`**:

```json
{"authored_version": 1, "page_id": "appendix/troubleshooting", "status": "scaffolded",
 "owner": null, "waiver_reason": null, "default_waiver": false,
 "questions": [{"id": "5.3.1", "answered": false}]}
```

`status` is `scaffolded`, `drafted`, `complete` or `waived`. **Only `complete` and `waived` release the
publication gate** — `drafted` deliberately does not, because a draft is what gets reviewed and treating it
as done would publish the review's input as its output. A waiver names an owner and a reason: "we looked,
and this page is not needed here" is an answer, and an answer has somebody behind it.

The file holds only what a person owns. The evidence a page is offered is recomputed on every build against
that run's index, so a stale reading list never sits in a file somebody is editing.

**`appendix/compliance` starts `waived` by default**, with `default_waiver: true` and no owner. It asserts a
legal position rather than describing behaviour, and an unowned compliance claim is worse than an absent one:
a reader cannot tell a considered "this does not apply" from nobody having looked. Set an owner to make it an
assertion.

### What the run hands over

`render` writes a scaffold for every unsettled page that has no file yet — **never overwriting one that
exists** — carrying the audience, the questions, and the evidence this run already verified:

| Page | Gets |
| --- | --- |
| `troubleshooting` | every `declared`/`observed` **`failure`** statement, and the validated procedures |
| `faq` | the validated procedures, and the README |
| `changelog` | the repository's changelog asset |
| `references` | its licence and packaging assets |
| `glossary`, `compliance` | nothing, and the scaffold says so |

**Nothing here is extracted.** Every row was collected and checked by a component that already runs, and
arrives with the id it carries elsewhere in the document, so the page cites what the rest of the manual
cites. `inferred` rows are excluded: the model's own reading, on a page whose whole problem is that evidence
is thin, would arrive looking like evidence.

The scaffold also says what the run looked for and **did not** find — *"1 of 2 analysed module(s) carry no
failure statement (src/store.py)"*. Without it a thin troubleshooting page and a thin analysis look
identical, and the difference decides whose problem it is.

What a scaffold never does is compose a sentence. A symptom-and-cause table built from a guess at what
usually goes wrong would arrive looking finished, and that is the failure this skill is arranged against.

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
      "text": "OrderLog records orders in a local store so the team can retain order history without running a database server.",
      "evidence": [{"path": "README.md", "line_start": 1, "line_end": 12}],
      "verified_ids": ["claim:imports:src/api.py:src/service.py", "op:test"],
      "facets_missing": []
    }
  }
}
```

The excerpt shows one answer; a valid artifact contains every question. Use plain text in `text`, with
paragraph breaks where helpful; the renderer owns RST/MyST syntax. Do not paste escaped RST directives.

**`basis: unknown` is for a question the repository does not answer, not for one nobody looked up.** This is
the rule the other basis values hang off, and the one worth stating first, because the incentives run the
other way: `observed` and `declared` cost evidence plus a verified id, `inferred` costs evidence, and
`unknown` costs a sentence.
A run that answers nothing is therefore cheapest, entirely honest question by question, and worthless — so
the gate refuses it. **Under half the template answered is `answer_mode: unanswered`, which can never pass**,
the same way `derived_only` can never pass on the analysis side. Before writing `unknown`, look: the README,
the packaging manifest, the CI workflow, the configuration, the tests, the source. `inferred` is the basis
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
- `basis: asserted`: **the one basis with no repository evidence.** For what a reader needs and the source
  cannot settle — what a domain term means, what people actually ask, what to check first when something
  fails. It requires `reviewer`, refuses `verified_ids`, and the rendered paragraph says *"Not documented in
  the source; stated by …"*. Capped at 20% of the answered set; past that the build stops.
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
is derived from them — `evidence` and `verified_ids` default to the union of what those answers cite. The
section keeps the weakest basis and completeness of the answers it uses; its content review remains pending
until a reviewer decides that exact rendered wording.

### Naming an answer is not composing it

**A section must give at least four words of prose per answer it names.** Below that, publication is held.

Composition was the one step here with no floor under it. The rule it enforces runs in one direction only —
a section may not cite more than its answers — and narrowing to nothing was permitted by design, so every
gate asked *"is this claim supported?"* and none asked *"is this all you had?"*

What that allowed, measured: all 161 questions answered with distinct text and real evidence, then one
section per page reading **"It works."** `validate` clean, `uncomposed` zero, `answer_mode: answered` — the
top tier — and a rendered page of nineteen words, seventeen of them citations.

The floor is deliberately low. Calibration, from sections measured rather than imagined:

| Section | Words per answer | |
| --- | --- | --- |
| `"It works."` over 9 answers | 0.2 | held |
| a terse but real 2-answer section | 7.5 | passes |
| a proper 7-answer paragraph | 9.6 | passes |

It will not catch forty words of filler over nine answers. Nothing mechanical will, which is what the prose
review queue is for.

**A section may say it really is that short**, with a `brevity` object naming a reason and a reviewer:

```json
{"heading": "Invoking", "body": "…", "answers": ["3.1.1", "3.1.2"],
 "brevity": {"reason": "This tool has one entry point and no arguments beyond the input path.",
             "reviewer": "docs@example.com"}}
```

The reason needs at least five words: `"Short."` is a label, not a reason. What the exception excused is kept
beside it in `manual_coverage.brevity_exceptions` and named in the report — an exception nobody can see
afterwards is indistinguishable from a check that was never there. Only the blocking problem is excused;
`retained` and `words_per_answer` still say what happened.

**Capped at a quarter of the sections.** Unbounded, the exception does not soften the retention floor — it
deletes it, one section at a time. The floor was calibrated so that nothing honest came within twice it, so a
manual needing the exception on more than a quarter of its sections is telling you something other than that
its sections are short.

**Two other measures were tried and rejected**, and both are still reported so you can see the shape of a
section without re-deriving it:

- `retained` — prose words over the words its answers hold. Unsound as a verdict, because **compression is
  what composition is**: a well-written 67-word paragraph built from 1400 words of notes retains 4.8%, and
  the stub that replaced nine answers retains 4.1%. Only the prose tells them apart. It is also gameable from
  the wrong end — write terse notes and a terse section clears it — which would reward the run that read least.
- `shared_terms` — vocabulary the section shares with its answers. A section may paraphrase completely and
  still be correct.

The draft still renders when a section is thin. That is the point: a thin draft you can read is reviewable,
and a build that refuses leaves nothing to look at. `manual_coverage.thin_sections` names them, and
`quality_docs` holds publication — the same render-then-hold pattern as P4, the prose queue and the authored
ledger.

Five rules, all checked before `doc.json` is written:

- **A heading is not a question.** A trailing `?` is refused outright. The question asked what to find out;
  the heading says what the section is about.
- **A section names at least one answer, and only answers on its own page.** Prose attached to nothing is
  prose nothing checked.
- **Only substantive answers can be composed:** their basis is `observed`, `declared`, `inferred` or
  `asserted`, and
  completeness is `partial` or `complete`. An `unknown` is a gap and a `not_applicable` is an exclusion;
  both are reported on the page, neither is written up as content.
- **Composition may narrow what an answer rests on, never add to it.** A section may cite fewer locations
  than its answers do — that is editing. Citing one they do not is provenance nothing checked, and is the
  failure this whole contract exists to prevent.
- **One `inferred` answer makes the section `inferred`**, however many observed or declared ones sit beside it.
- **One `asserted` answer outranks even that**, and the section carries the provenance line naming who
  stated it. It is the only basis with nothing cited underneath, so a section holding one cannot honestly
  be presented as observed or inferred.
  Surrounding a reading with facts does not turn it into one.

**Every composable answer must reach some section on its page.** An answer the run paid for and then dropped
fails the quality gate rather than passing quietly — it is a defect in the composition, not a gap in the
repository. Gaps are collected into one marked block per page instead of being scattered through the prose:
what is not documented, what is not applicable, and what is answered but not yet written up.

## `verified_ids` — what separates observed or declared support from inference

**A citation that resolves is not a citation that supports.** `src/api.py:34-51` can exist, be in range, and
have nothing to do with the sentence beside it; nothing downstream catches that, because the prose review
queue is looking for verb inflation rather than fabricated support. So a basis that asserts *the repository
settles this* has to borrow its standing from a check that could have failed, and name it. Content
confirmation is separate and belongs to the review record.

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

## Facts — verified inputs available to the model

Pass the analyses to the initializer and it records eligible ids in `facts`, grouped by the validator or
analysis that produced them. It leaves every answer unanswered:

```bash
python3 scripts/document/manual.py --init .docs-build/manual-analysis.json \
  --index .docs-build/structure.json \
  --architecture .docs-build/architecture-analysis.json \
  --flows .docs-build/flow-analysis.json \
  --operations .docs-build/operations-analysis.json \
  --config .docs-build/config-analysis.json
```

| Facts group | Eligible inputs |
| --- | --- |
| `claim` | verified structural or call claims |
| `statement` | declared or observed module statements |
| `component` | validated components that name modules |
| `flow` | flows with verified call steps |
| `procedure`, `requirement` | operations whose command or value was matched against source |
| `setting` | extracted settings with source evidence |

The inventory is a reading list, never an answer. A setting id establishes its name and cited location; it
does not establish what the setting means, its legal values or its precedence. The model reads the relevant
source and writes every answer and section. Missing facts leave questions open rather than creating empty or
generic prose.

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
