# Plan 4 — source understanding, drafts and content review

Status: ready for implementation; this commit records the plan, not completed runtime changes.
Baseline: `feat/config-extractor` at `521dc7d9580904790476e8cdbaabeab0e3071151`.
Target: the existing `document-codebase` skill in the `docs` plugin.

## Goal and agreed decisions

Produce documentation that helps a person understand, configure, operate and develop the product.
The model reads and understands the source, writes a draft, receives content findings, revises it,
and repeats review. A successful script run does not establish that the document explains the product.

1. Keep scripts for indexing, source retrieval, fact extraction, mechanical checks and rendering.
2. Remove templated answer prefill. Facts and citations remain structured inputs to the model.
3. Make a readable draft an explicit output before final delivery; preserve drafts and review history.
4. Reserve content `confirmed` for a model review against source. Separate it from mechanical results.
5. Cover the product source by component and user journey; a fan-in cutoff must not silently omit features.
6. Exclude test code from product documentation, component inventories and product diagrams. Tests may
   still be read as supporting evidence, and the developer guide can explain how to run them.
7. Define Analyst, Writer and Reviewer roles inside the skill. Use actual subagents when the host exposes
   them; otherwise perform explicit sequential passes and disclose self-review.
8. Keep the main agent responsible for scope, cross-component synthesis, consistency and final reporting.

This plan supersedes the fan-in-only scope and automatic answer-confirmation decisions in earlier plans
for the product manual. It retains structural claims, source hashes, PlantUML, the question template,
existing non-manual presets and human decision checkpoints. See [Plan 3](plan-3-analysis-depth.md) for
the earlier analysis work; do not rebuild its implemented components.

## Baseline: what already exists

| Existing implementation | What to retain or change |
| --- | --- |
| `SKILL.md` delegates work between script components | Retain. The model already orchestrates the run; no embedded model API client is needed |
| `references/analyze.md` requires reading packet source and every partition | Retain and expand scope coverage; source understanding is already a model responsibility |
| `references/three-analyses.md` assigns architecture, flow and operations analysis to the model | Retain; add cross-component reconciliation and explicit unresolved questions |
| `references/manual.md` separates answer notes from model-composed pages | Retain; add the draft/review/revision lifecycle |
| `manual.py:prefill()` writes templated prose with `status: confirmed` | Remove answer generation and automatic confirmation |
| `extract_config.py` collects Python settings; `validate_config.py` checks cited names | Retain as bounded evidence discovery; do not call its output complete config semantics |
| `select_units.py` already excludes `is_test` and ranks production fan-in | Extend rather than reimplement test filtering; audit all downstream paths for leaks |
| Selection requires symbols and defaults to top 25 plus entry points | Replace for manual scope; top-level side-effect modules and low-fan-in features still matter |
| `check_prose.py` accepts review rows keyed by block ID | Extend freshness and semantic-review contracts before reusing approvals after edits |
| Driver deliberately runs one component per invocation | Retain; model work happens between invocations |

`references/pipeline.md` describes the driver, not the entire model workflow. It currently omits config
extraction/validation from its survey table and describes the old automatic preset selection. Update it
alongside code. Also remove stale eight/twelve-question prefill descriptions across the references.

## Responsibility and file placement

Paths in this section are relative to `plugins/docs/skills/document-codebase/` unless stated otherwise.

| Location | Responsibility |
| --- | --- |
| `SKILL.md` | Essential rules, role dispatch, draft/review requirement, scope and final-output contract |
| `references/workflow.md` (new) | Model workflow, artifacts, transitions, budgets and resume behavior |
| `references/analyst.md` (new) | Source reading and analysis task contract |
| `references/writer.md` (new) | Reader-facing composition and revision task contract |
| `references/reviewer.md` (new) | Source-grounded content review, findings and confirmation contract |
| Existing survey/analyze/context/manual/publish references | Stage-specific instructions, linked to the new workflow without conflicting duplicates |
| `references/pipeline.md` | Actual commands, flags, exit codes and mechanically enforced checks |
| Repo `shared/scripts/` | Canonical implementation of deterministic helpers; regenerate plugin copies |

Keep roles as portable instructions, not new independently triggered skills. Custom `.agent.md` files,
MCP servers and model SDKs are not prerequisites. A skill can direct an available tool but cannot create
host capabilities or grant permissions by naming them in Markdown.

## Source scope and reading coverage

Create `.docs-build/scope.json`, bound to the scan identity, containing product roots, audiences,
required documentation topics, component assignments and every inventoried file's disposition.

- Include first-party product source within the requested product roots, including CLI/entry modules,
  side-effect-only modules, configuration consumers, integration adapters and error-handling paths.
- Classify tests, test support, generated code and vendored code separately with reasons. Use scanner
  metadata and repository conventions; do not blindly exclude a production path because it contains
  the substring `test`. Disclose uncertain classifications for scope review.
- Keep README, packaging, CI, configuration and examples as supporting assets. Reading tests for evidence
  does not add them to the product graph, module reference, component membership or product coverage.
- Group reading tasks by responsibility or end-to-end behavior. Fan-in may order work but does not define
  which features exist. A budget limits the next batch, not the denominator of the promised coverage.
- Record `unread`, `read`, `analyzed` or `excluded`, source hashes, task ownership, consumed partitions,
  relevant template questions, evidence and unresolved questions. These are records of work, not proof
  that a model understood a file.
- Require every in-scope product file to be read and accounted for before a full-product completion claim.
  An empty package marker may be accounted for without inventing four semantic statements. A symbol-free
  executable module still needs meaningful analysis. Update assembly and coverage contracts accordingly.
- Follow actual collaborators beyond a packet's interface summaries when needed to understand a flow.
  Load source in bounded parts; do not require the whole repository to fit in one prompt.
- If the budget ends with unread product source or uncovered required topics, save progress and report an
  incomplete draft. An explicitly narrowed user scope is recorded as a scope change, not a completed full scan.

The authoritative index may retain test records for evidence lookup. Derive one documented product view
for claims, diagrams, component membership, page generation and coverage; avoid ad hoc exclusions in each.

## Roles and delegation

| Role | Inputs | Output and boundary |
| --- | --- | --- |
| Coordinator | User goal, template, index, scope and available host tools | Own scope, dispatch, merge artifacts, reconcile conflicts, maintain revisions and decide next work |
| Analyst | Assigned product source, packets, collaborators, supporting assets and question IDs | Explain responsibilities, mechanisms, state, interfaces, failures and relationships with evidence; return gaps, not invented intent |
| Writer | Reconciled analysis, source access, audience, page contract and current draft | Compose coherent sections and useful examples; request more analysis when evidence is insufficient; never self-confirm |
| Reviewer | Exact draft revision, scope, source access, analyses and mechanical reports | Independently inspect supporting source, assess correctness/completeness/readability and return actionable findings or confirmation |

Discover the host's actual subagent capability before dispatch. If available, assign independent component
analyses or page reviews in parallel within the run budget. Keep writing dependent on reconciled analysis,
and review dependent on a rendered draft. Parallelism does not remove these dependencies.

Every task specifies task ID, role, scope, source/index identity, input artifacts, expected output,
acceptance criteria, budget and read/write boundaries. Give each subagent the relevant role instructions;
do not assume it inherits the skill or conversation. Prefer one task per component or journey, not per file.
Workers return results or write isolated task artifacts. Only the coordinator merges shared JSONL files
and resolves conflicting interpretations. A timed-out task remains pending and cannot count as complete.

Use a reviewer context separate from the writer when possible. Sequential fallback must report
`review_mode: self_review`; actual separate review uses `review_mode: independent`. Both apply the same
rubric, but reports must not claim independence where none occurred. The same model family can perform an
independent-context review; a different provider is not required. Host permissions always remain in force.

## Draft, review and revision lifecycle

1. Survey, classify and agree scope; keep P1 and the existing authorization rules.
2. Read product source in batches; write module analyses and reconcile architecture, flows and operations.
   Preserve P2/P3 judgements and resolve source conflicts before composing claims based on them.
3. Initialize empty answer slots and optional references to supporting facts. The model writes all
   explanatory answers and page sections; the initializer supplies no stock answer sentences.
4. Render revision 1 under `.docs-build/drafts/rev-0001/`, including the readable RST/MyST pages and diagrams;
   build a browsable preview when existing tooling supports it. Keep draft labeling visible. Missing optional
   preview dependencies are reported, not installed or called a successful build.
5. Run mechanical checks and review the exact draft against source. Review every substantive section plus
   the document's topic coverage, navigation, cross-page consistency and usefulness to its audience.
6. Route findings to the relevant analyst or writer. Update source analysis when the reasoning was wrong;
   do not merely rewrite prose around a faulty interpretation. Record findings addressed and unresolved.
7. Render a new immutable revision and review affected content again. Reassess whole-document coverage and
   consistency after revisions. Unchanged sections can reuse review only when their content and all reviewed
   inputs still match; use conservative invalidation if dependencies are uncertain.
8. Finish only after fresh content review, mechanical checks and required human checkpoints. Deliver the
   exact reviewed content to the chosen docs directory; verify content identity across final-path rendering.

Persist iteration number, budget remaining, draft revision, findings and next actions. Stop on exhausted
budget or two consecutive revision attempts with the same unresolved blocking findings and no substantive
progress. Save a readable draft and a continuation report; never convert that stop into `confirmed`.
The existing two-attempt structural-claim retry policy is separate from this document revision loop.

Keep rendering and final publication distinct. Today `publish` writes pages before its final quality gate;
the implementation must support staging without overwriting established docs. No automatic
external publication, git commit, network call or human approval is implied by a model review verdict.
Previously authorized local delivery proceeds without asking again solely because a review completed.

## Confirmation and review contract

Use a versioned manual schema rather than redefining legacy `manual_version: 1` silently. Separate:

| Field | Values and meaning |
| --- | --- |
| `basis` | `observed`, `declared`, `inferred`, `unknown`, `not_applicable`; how the answer is supported |
| `completeness` | `unanswered`, `partial`, `complete`; required facets answered and missing facets recorded |
| `content_review` | `pending`, `confirmed`, `changes_requested`, `unresolved`; review outcome |
| `mechanical_checks` | `not_run`, `passed`, `failed`; checks actually executed, with reports |

`confirmed` means the reviewer accepted the wording, support and uncertainty of this exact revision.
It is a model judgement, not mathematical proof or a guarantee about runtime behavior. A responsibly
labelled inference can be confirmed as an interpretation without becoming an observed fact. Honest unknowns
can be reviewed for wording, but unresolved required topics still prevent complete-product delivery.

Scripts may check schema, paths, line ranges, hashes, reference consistency and supported AST attributes.
They must not assign semantic confirmation. Resolved `verified_ids` remain provenance links, not a licence
to confirm every sentence that names one. Syntax/graph checks do not establish rationale or reader usefulness.

Extend the existing review channel instead of inventing parallel approval files. A versioned
`prose-review.jsonl` record should include:

- Stable review ID, target section/page/document ID and draft revision.
- Exact content hash, index hash and the hashes of source/analysis inputs actually reviewed.
- Reviewer/task identity, `review_mode`, verdict and rationale with inspected evidence.
- Findings with stable IDs, severity, location, why it matters, requested correction and open/resolved state.

Reject malformed or conflicting duplicate review rows. An old block ID alone cannot approve changed text.
Editing evidence, analysis, scope, section membership or source invalidates dependent reviews. Final delivery
checks the actual reviewed artifact, rather than trusting a writer-set status. This checks review bookkeeping;
it cannot prove that the recorded review was insightful or that the model truly read the source.

The review rubric covers behavior, configuration precedence/defaults, failures, component interactions,
unsupported intent, missing question facets, examples, reader task completion and cross-page consistency.
Mechanical verb-strength heuristics remain useful findings, not a substitute for this review.

## Implementation work packages

All packages below are pending. Implement in this order, with W1/W2 drafted together so schema and scope
contracts agree. Ship changes to instructions and their supporting behavior together, not as contradictory
intermediate instructions. Keep the plan updated with commit references as packages land.

| ID | Work and main files | Acceptance criteria |
| --- | --- | --- |
| W1 | Define manual/review/scope versions in `references/schemas.md`; extend `manual.py`, `check_prose.py`, `quality_docs.py`, builder/renderer consumers | Drafts render without confirmation; final completion requires fresh review; mechanical success cannot promote prose; partial answers remain partial |
| W2 | Update `select_units.py`, `query_graph.py`, driver selection and assembly; wire shared product scope into class graph, document model and coverage | Low-fan-in and symbol-free product behavior is covered; tests do not leak into pages/diagrams; exclusions and unread files are visible |
| W3 | Remove `prefill()` prose generation and confirmation; retain structured extractors and provenance | Initializer writes unanswered slots and empty page sections; no stock prose or completed answers; existing authored drafts are never overwritten |
| W4 | Add workflow/role references and update `SKILL.md`, survey/analyze/context/manual/three-analyses/publish/pipeline references | Model source reading is required; roles have concrete tasks; actual delegation and sequential fallback both work; no custom-agent installation required |
| W5 | Implement staging, revision snapshots, review binding and resume in driver/render/review/gate helpers | A draft can be inspected before final output; stale approvals fail; findings route to revisions; stop/resume preserves outstanding work |
| W6 | Migrate legacy artifacts and evaluate full runs; regenerate plugin copies and update release metadata | Old `confirmed` becomes review-pending; prose/evidence preserved; tests below pass; plugin installs with all references and scripts |

Canonical scripts live under `shared/scripts/`. Regenerate via `tools/materialize.py`, updating
`plugins/docs/shared.manifest` when needed. Bump the docs plugin version and the matching marketplace
entry when implementation changes ship. A repository-only plan does not change the installed plugin version.

## Migration and compatibility

- Preserve v1 artifacts and provide explicit migration into a new version; never treat a legacy
  `confirmed` or unbound `ok` review as approval under the new contract.
- Preserve authored text and citations, mark content review pending, and retain inferred/unknown meaning.
  Remove generated prefill only through a reviewable migration, not by guessing which prose was authored.
- Rescan or rebuild scope on source changes; do not relabel an old scan or reuse P1/P2/P3 decisions against
  a different identity. Account for scope changes even if the source index is unchanged.
- Keep non-manual presets functional; apply test exclusion to product documentation, but do not silently
  change their page contracts. Report any remaining limited scope explicitly.
- Keep a full product dependency graph available: reading batches must not truncate relations or diagrams.
- For config extraction, report supported patterns, skipped/unparsed source and conflicting defaults.
  Absence of matches means no supported matches found, not proof that the product has no configuration.
- Do not delete tests, alter the documented application's code, add model SDKs or require a new MCP server.

## Verification and completion criteria

Use focused behavioral tests for changed contracts and a real skill run for semantic quality. Script tests
must not be presented as proof that prose is useful. Required scenarios:

1. A valid config citation paired with a false fallback explanation passes the appropriate location check,
   remains unconfirmed, and is challenged by source-grounded review.
2. The initializer produces no prose answers or automatic confirmations, while preserving facts for reading.
3. A low-fan-in feature outside the former top 25 and a symbol-free entry module both receive reading tasks.
4. Tests/test-support are absent from product pages and diagrams, but an intentional test citation and a
   documented test command remain usable. Generated/vendor exclusions have explicit reasons.
5. A configuration answer containing only names/defaults remains partial when types, constraints or
   precedence are still required. Adding a validator ID cannot make it complete.
6. A confirmed section is edited without changing its block ID; its review becomes stale. Changing its
   supporting source or analysis also invalidates review. Unchanged bound content can be reused safely.
7. A reviewer requests a correction, the writer revises, and a second review accepts the corrected draft;
   only that revision can be delivered. Stop/no-progress paths retain the draft and open findings.
8. A host with subagents records separate task results; a host without them completes sequential passes
   and truthfully reports self-review. Neither permits concurrent writers to corrupt aggregate artifacts.
9. Draft rendering leaves existing docs untouched. Final rendering does not introduce unreviewed content.
10. Legacy artifacts migrate without losing authored content or inheriting automatic confirmation; malformed
    or duplicate conflicting review rows fail visibly.

Run `tools/validate.py`, `tools/materialize.py --check` and the affected focused tests. Extend existing
`tools/test_manual_preset.py`, `tools/test_prose.py`, selection/coverage and pipeline tests instead of
creating a second test framework. Keep semantic evaluation expectations separate from reviewer inputs.

Evaluate one small end-to-end repository and one multi-component scope with a low-fan-in feature. A reader
should be able to explain the product's purpose, trace a key operation, configure it and understand a failure
from the draft. Record source-based findings, corrections, remaining gaps and whether review was independent.
Retain the existing mandatory class/data-flow diagram policy and state unsupported flows honestly.

Completion requires implemented work packages, source-backed content review, current mechanical checks,
explicit scope coverage and final output matching the reviewed revision. A plan commit alone meets none of
those implementation gates; it supplies the agreed contract for the next work.
