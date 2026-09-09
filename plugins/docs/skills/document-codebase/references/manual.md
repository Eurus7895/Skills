# Question-driven manual

Read [documentation-template.md](documentation-template.md) before selecting scope and before writing
`.docs-build/manual-analysis.json`. The template's 25 sections are the content contract; the documentation-wide
review is an additional appendix page. Preserve every question heading through review.

## Workflow

1. Select `--preset manual` explicitly. Survey the product purpose, actors, entry points and configuration as
   well as the dependency graph. Select evidence needed to answer the template, not merely high-fan-in files.
2. Run the existing survey, analyze and check components. Read source, configuration, tests and repository
   documentation to answer questions the structural index cannot answer. Keep module, architecture, flow
   and operations analyses as supporting evidence; a list of files is not a manual answer.
3. Initialize the answer artifact once (exclusive creation refuses to replace existing answers):

   ```bash
   python3 scripts/document/manual.py --index .docs-build/structure.json --init .docs-build/manual-analysis.json
   ```

4. Replace each unknown draft with a project-specific explanation. A question about a component needs its
   responsibility, collaborators and mechanism; a question about a phase needs its inputs, processing,
   decisions, outputs and failure behavior. Use source paths for evidence and navigation, not as the answer.
   Include use cases in Introduction, design decisions and boundaries in System Overview, and precise
   processing behavior in Data Flow and Detailed Processing Phases. Do not invent authors' motivations.
5. Run `python3 scripts/pipeline.py document --preset manual`, then publish. The model builder requires
   `manual-analysis.json` and renders its answers instead of the old inventory/absence builders. It checks
   complete question IDs, scan identity and repository-relative evidence line ranges. It does not prove
   that a sentence is true or sufficient. Every substantive manual answer enters the prose review queue.
6. Review the rendered RST against each question: does it actually explain the project? Correct weak answers
   in `manual-analysis.json` and rebuild; do not patch generated RST because the next build replaces it.
   Review verdicts apply to actual answer blocks `answer:<question-id>` using the existing prose-review
   workflow. Unknown answers and missing mandatory diagrams keep the quality report incomplete.

## Answer contract

`manual_version` is `1`; `index_hash` must match the current scan. `answers` maps every stable question ID
(`1.1.1`, `1.1.2`, ..., `5.7.6`, and `review.1` ... `review.8`) to one answer. The bundled
`manual_questions.json` is the machine-readable mapping; the initializer writes all IDs.

```json
{
  "manual_version": 1,
  "index_hash": "<current index_hash>",
  "answers": {
    "1.1.1": {
      "status": "confirmed",
      "text": "Explain the actual product and the problem it solves, using the cited evidence.",
      "evidence": [{"path": "README.md", "line_start": 1, "line_end": 12}]
    }
  }
}
```

The excerpt shows one answer; a valid artifact contains every question. Use plain text in `text`, with
paragraph breaks where helpful; the renderer owns RST/MyST syntax. Do not paste escaped RST directives.

- `confirmed`: repository-supported answer with evidence.
- `inferred`: supported interpretation with evidence, visibly labelled Inferred. Explain its basis and limits.
- `unknown`: write `Unknown — evidence required` and a concrete `next_check` naming what to inspect or whom
  to ask. Keep the question; do not silently omit it or call the manual finished.
- `not_applicable`: explain why, and record `reviewer` only after an actual reviewer confirms applicability.
  Never fabricate review. Keep the explanation in the delivered page.

Evidence locations must exist within `--root` and have valid line ranges. For external evidence, record the
reference in a repository document and cite that location; do not make inaccessible sources look verified.
The documentation-wide review records revision, audiences, sources, uncertainty and lifecycle coverage.

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
