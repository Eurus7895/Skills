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
- the manifest contains a unique repository view and collision-free files (`G007`).

The metadata comments are part of the generated contract. They let the validator check
the constrained PlantUML subset without pretending to parse arbitrary user-written
PlantUML.

## Rendering

Sphinx integrates the source through `sphinxcontrib-plantuml`; PlantUML performs layout
and SVG rendering. The target documentation project must enable the extension and expose
a working PlantUML command. CI must exercise the real render path. `.puml` generation is
still independent of that runtime, so Diagram as Code remains available everywhere.
