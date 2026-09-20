# PlantUML diagram policy

`class-graph.json` is structural truth. Generated `.puml` files are the canonical,
reviewable Diagram as Code presentation. SVG and HTML are derived by PlantUML and Sphinx.

The block has two independent outputs: **class diagrams** describe verified static structure and
**data-flow diagrams** describe verified call sequences. Never turn an import edge into a call arrow, and
never draw a plausible sequence when no complete verified flow exists. An explicit absent-flow result is
more accurate than an invented diagram.

## Source layout and style

Generated PlantUML follows this order: reusable palette and `skinparam` declarations; title and generated
metadata; containers or participants; relationships or messages; notes; legend; `@enduml`. Reusable style
files, when used, contain only palette and `skinparam` declarations. Repository-specific classes, arrows,
notes, and legend text remain in the diagram source.

- Use `package` for architectural boundaries, layers, domains, and subsystems. Keep nesting to two levels
  where practical, give containers descriptive names, and declare a class inside its owning container.
- Keep the canvas and class bodies white. Use restrained, consistent container colors to show ownership;
  color is not evidence and must not create a category absent from the analyses.
- Show only architecturally useful public members. Use a stereotype only when source establishes the role.
- Declare cross-container relationships after all containers. Keep direction from caller or orchestrator to
  dependency.
- Use ordinary neutral arrows for dependencies. Reserve bold colored arrows for a major verified business or
  data flow, and add a legend whenever color or line style carries meaning.
- Use inheritance only for resolved specialization. Use composition only when evidence establishes lifecycle
  ownership, and aggregation only when evidence establishes a whole–part relation with an independent child.
  A typed attribute alone proves an association, not ownership.
- Explain every non-obvious color or line style in a `legend right`; use the same terms as the diagram.

The visual baseline is a white background, white class bodies, dark neutral borders and text, an 11-point
readable sans-serif font, 13-point package labels, orthogonal class-diagram lines, and no decorative effects
that obscure endpoints. A project may adapt the palette for accessibility or existing documentation style,
but must keep contrast and semantic consistency.

## Required artifacts

Every valid graph produces `diagram-manifest.json` and at least
`full-repository.puml`. A graph with no classes produces an explicit empty-state diagram;
it is not skipped. Generation uses the Python standard library and never invokes a
renderer, the network, Graphviz, or a browser.

## Views and density

The repository view is always present. At more than 60 classes or 400 public members,
the overview uses summary detail and package views are generated. A package over the
same threshold is split into module views. External neighbours reached by a visible
relationship remain in detail views and carry `<<external>>`.

## Relationship layers

| Layer | PlantUML notation | Confidence |
| --- | --- | --- |
| Inheritance | `--|>` | Verified resolved base |
| Composition | `*-->` | Verified lifecycle ownership |
| Aggregation | `o-->` | Verified whole–part relation; child survives independently |
| Association | `-->` | Typed attribute or deterministic module relation |
| Calls | `..>` | Static call evidence |
| Inference | `..>` | Explicitly weaker evidence |

Inheritance edges record the subclass in `from` and the base in `to`. Composition records
the lifecycle owner in `from` and the part in `to`; aggregation records the whole and independent part.
Labels are preserved when the graph supplies
them. The generator emits a legend so the rendered view is interpretable without colour.

The current structural extractor proves inheritance, typed-attribute association, imports, and verified call
claims. It does not infer lifecycle ownership from a type annotation. Therefore composition and aggregation
must remain absent unless a future extractor records the stronger evidence explicitly.

## Presentation controls

A view spec may select `detail`, `layers`, `emphasis`, and `rankdir`. `emphasis` names
graph ids and changes how those boxes are filled — an emphasised class is the same class,
related to the same classes. It may not add or remove classes, change containment, alter
relationship endpoints, or fabricate layers, and it may not set `scope`: which classes a
view holds comes from the package structure, so a spec naming its own scope is refused
rather than quietly overridden.
PlantUML owns geometry; coordinate patches, route patches, and manual SVG editing are not
part of this pipeline.

## Validation

`validate_diagrams.py` checks:

- every in-scope class appears exactly once (`G001`);
- each view is pinned to the supplied graph and manifest (`G002`);
- containment, endpoints, relationship types, and unique ids remain intact (`G003`);
- the PlantUML source and manifest declare identical nodes and relationships (`G005`);
- the source has valid document boundaries and machine metadata (`G006`);
- the manifest contains a unique repository view, collision-free files, and an own-class
  list matching each view's scope (`G007`).

The metadata comments are part of the generated contract. They let the validator check
the constrained PlantUML subset without pretending to parse arbitrary user-written
PlantUML. **The declarations themselves are checked too**, not only the comments
describing them: the classes and arrows PlantUML will draw must be exactly the ones the
metadata declares, and a class- or arrow-shaped line outside the generated form is a
finding. Otherwise a class added to a `.puml` by hand renders like any other while every
check passes.

## Rendering

Sphinx integrates the source through `sphinxcontrib-plantuml`; PlantUML performs layout
and SVG rendering. CI exercises that real render path.

**The extension is optional, and not in the way a parser is.** Without `myst_parser` a
MyST page is not read at all; without `sphinxcontrib-plantuml` every page still builds
and one picture is missing. So a project that has not enabled it still gets its
documentation, with a warning naming what to enable, and the build check accepts the
`uml` directive without drawing it rather than failing the page over a renderer nobody
installed. The `.puml` is the artifact either way — reading it needs no runtime at all.

### What a build establishes, and what it does not

**`passed` is about markup. It is not a diagram verdict**, and the two are reported
separately so a run on a machine with no renderer cannot read as full diagram validation.
`result.diagrams` carries one of four states:

| State | Means |
| --- | --- |
| `drawn` | an image the renderer writes was found in the build tree |
| `accepted` | the build finished, the markup parsed, and no picture came of it. A stub swallowing the source is one way here: it parsed, and the source could say anything |
| `none` | there is no diagram here to report on — no renderer was asked for, or no page holds a directive one would draw |
| `unknown` | nothing was established — no builder installed, or a build that produced no picture and cannot be shown to have finished |

`unknown` is separate from `none` deliberately. A skipped check that reported `none` would
be *claiming* the document holds no diagrams, and that claim is wrong on any document that
does. Nothing looked, so nothing is said.

**`drawn` is found, not inferred.** The state is decided by looking in the build tree for
the files the renderer writes. Deciding it from the extension being installed is the
mistake this check exists to catch, one level up: an extension loads and still draws
nothing when the renderer binary is absent, when a `.puml` is unreadable, or when the build
stops before the writing phase — and every one of those reads as success to anything that
only checks what was *requested*.

**A failing status is not a verdict on the pictures, in either direction.** `-W` aborts at
the first error on Sphinx 7 and runs to the end on Sphinx 9, so the same `invalid_markup`
build draws nothing on one and everything on the other. The status cannot tell you which,
so it is not consulted: a picture that exists is `drawn` whatever the exit code, and no
picture on a build that cannot be shown to have finished is `unknown`.

A renderer that is installed but still produced no picture — `plantuml command … cannot be
run` — is `accepted`, not `drawn`. The extension being absent and the tool behind it being
absent are the same outcome for a reader: the source parsed, no image exists.

**There is no state for "visually reviewed", and that is not an omission.** A drawn diagram
with unreadable labels, ambiguous relationships, or a shape that contradicts the prose
beside it is still a drawn diagram. No build settles those, so the report says the question
belongs to review rather than implying it has been answered. `G001`–`G007` check that the
source matches the graph; whether the picture *communicates* is a person's judgement and
goes through the review channel like any other reading.
