# PlantUML diagram policy

`class-graph.json` is structural truth. Generated `.puml` files are the canonical,
reviewable Diagram as Code presentation. SVG and HTML are derived by PlantUML and Sphinx.

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
| Composition | `*-->` | Verified typed attribute |
| Association | `-->` | Deterministic module relation |
| Calls | `..>` | Static call evidence |
| Inference | `..>` | Explicitly weaker evidence |

Inheritance edges record the subclass in `from` and the base in `to`. Composition records
the owner in `from` and the part in `to`. Labels are preserved when the graph supplies
them. The generator emits a legend so the rendered view is interpretable without colour.

## Presentation controls

A view spec may select `detail`, `layers`, `emphasis`, and `rankdir`. It may not add or
remove classes, change containment, alter relationship endpoints, or fabricate layers.
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
