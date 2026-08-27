# Diagram policy

The full-repository class diagram is the primary diagram deliverable, and it is a claim
like any other: it says these classes exist, in these packages, related this way. The SVG
is a render product of `class-graph.json`; if it disagrees with the graph, the drawing is
wrong and `validate_diagrams.py` says so.

## What is drawn, and how well it is known

Relationships live in named layers because they are not equally well established.

| Layer | Comes from | Visible by default |
| --- | --- | --- |
| `inheritance` | a base class resolved to the file defining it | yes |
| `composition` | an attribute whose written type resolves to a class here | yes |
| `association` | the defining **modules** import one another | no |
| `calls` | a `calls` claim verified at its call site | no |
| `inference` | asserted by the model, confirmed by nothing | no |

Association is recorded between modules, not classes. An import is a fact about two
files; drawing it between every pair of classes those files define would state something
nobody established, and on a repository of any size it is a cross product.

A class with no type annotations produces no composition edges. That absence is reported
in the coverage counts, never filled in by reading attribute names.

An unresolved base class produces **no edge at all** and is listed under `unresolved` in
the class graph. A diagram that guessed the link would be worse than one that admits it
does not know.

## Detail levels

| Level | Shows | Use for |
| --- | --- | --- |
| `summary` | class name and stereotype | the full-repository canvas past the density threshold |
| `public` | public methods and typed attributes | the default |
| `full` | everything extracted | one module's detail view, never the whole repository |

**Density threshold (decision 15):** the default drops from `public` to `summary` when
the graph holds more than **60 classes** or more than **400 members** in total. Past that
a full canvas at `public` produces boxes too small to read, and the honest move is fewer
words per box rather than a smaller font. `build_diagrams.py` enforces this and says so
on stderr; a detail level named explicitly in a view spec is the author's call and is
left alone.

**Detail views (decision 16):** past the threshold the run also draws one view per
package, at `public` detail, and every box on the overview links to the view that shows
it in full. That is where the members the overview stopped showing now live. Below the
threshold no detail views are drawn: the full canvas already shows members, so a second
set of pictures would only repeat it. `--detail-views` asks for them anyway.

A package that is itself past the threshold would produce a second unreadable canvas, so
it yields one view per module instead. That stops one level down; a module too dense to
draw at `public` falls back to `summary` and says so.

**Which classes a view holds is not a presentation choice.** Scope comes from the
package structure in the class graph -- where the source files actually live -- and a
view specification is refused for setting it, exactly as it is for `remove_classes`.
Otherwise "show only this package" becomes the way to drop the classes an author would
rather not explain.

A detail view draws the far end of any relationship that leaves its scope, as an
`external` neighbour: greyed, dashed, labelled with the package it belongs to, and shown
without members. The view is not answerable for what is inside a neighbour, only for the
fact that the boundary is crossed. Dropping those instead would draw a package talking
to nobody, which is a stronger false statement than an extra grey box.

`validate_diagrams.py` holds the set together as well as each view: some view covers the
whole repository, no class is absent from every detail view (`G007`), no view is empty
(`G008`), and every link lands somewhere that exists (`G009`).

## Stereotypes

Assigned only where the code states them plainly: a base of `Exception`, a `dataclass`
decorator, `ABC`/`Protocol`/`abstractmethod`, an `Enum` base. Anything guessed from a
class name is a presentation choice dressed up as a fact, and this is the one place the
diagram would be believed without a citation.

## Missing tools

```text
Graphviz    optional  → skip with a warning, and say so in the document
            required  → fail
            disabled  → do not look
Rasterizer  required whenever --previews is asked for
```

The rasterizer is looked for in this order: `rsvg-convert`, `chromium`, `chrome`,
`inkscape`, then a Playwright-bundled Chromium under `/opt/pw-browsers`. Previews are
sized to the drawing, not to a fixed window -- a reviewer given a mostly-blank image
spends the budget on whitespace.

A browser rasterizer needs one concession to that: `--window-size` counts the window
frame, which the screenshot does not contain, so a window sized exactly to the drawing
loses the bottom of it. The request adds a generous allowance, which leaves white space
under a browser-rendered preview. That is deliberate. Guessing the allowance low clips
the canvas and takes classes out of the picture a reviewer studies, and no structural
check can see it -- the SVG is correct and only the image is wrong.

## The visual review loop

The model sees a rendered preview, `diagram-manifest.json`, this file, and the findings
from the previous attempt. It reviews what only a picture shows: overlap, clipped labels,
spacing, alignment, edge crossings, dense regions, colour consistency.

It returns `visual-findings.json` and a candidate `layout-patch.json`. It does **not**
decide whether the diagram ships.

### What a patch may contain

`apply_layout_patch.py` accepts five operations and refuses everything else:

```text
move    a node or container, by delta or to a position
resize  a node or container
route   an edge's waypoints
style   fill or stroke
wrap    re-flow a label at a character width
```

Refused always, in any spelling: adding or removing a node or edge, changing an edge's
endpoints or layer, changing a node's parent, touching a citation, a source hash, or the
graph hash. A refused patch leaves the model byte-for-byte unchanged — it is never
half applied.

Every patch records the class-graph hash, view-spec hash, renderer and policy version it
was made against. Applied to a diagram built from anything else it is refused: the
coordinates it moves would be moving something else. That same record is what lets an
unchanged repository replay an accepted patch instead of paying for another review.

### Stopping

Stop the loop when any of these is true:

- the review passes;
- two attempts have been used;
- the same finding appears twice;
- no measurable improvement (overlap count, crossing count, bounds) after a patch;
- a structural check regresses — in which case the patch is reverted, not retried.

### Severity (decision 14)

| Severity | Examples | Effect on the run |
| --- | --- | --- |
| critical | a class hidden behind another, a label unreadable at full size, an edge that cannot be traced to its ends | fails |
| major | heavy edge crossing in one region, a container badly oversized, inconsistent spacing across packages | `partial`, reported |
| minor | uneven alignment, colour drift, a slightly cramped label | `passed_with_warnings` |

**Availability (decision 13):** visual review is **optional** for the full-repository
diagram. Where no visual-capable model or no rasterizer is available, the run reports
`visual review: skipped` with the reason and continues on the deterministic checks alone.
`skipped` is never reported as `passed`.

That is a deliberate loosening of what the plan proposed: the deterministic checks catch
every defect that makes a diagram *wrong*, and only the ones that make it *ugly* need a
pair of eyes. Blocking a correct diagram on the absence of an optional model would make
the primary deliverable unavailable on most machines.

## What the deterministic checks guarantee

`validate_diagrams.py` runs with no external tool at all, after the initial render and
again after every patch:

- every class in the graph is a node, and no node lacks a class (`G001`);
- the model is pinned to the graph hash it was laid out from (`G002`);
- unique ids, no edge to a node that is not there, every class inside its own module's
  container (`G003`);
- geometry finite and non-zero; no two boxes overlapping unless one is a container
  (`G004`);
- the SVG contains exactly the nodes and edges the model declares (`G005`);
- both files are well-formed XML (`G006`).
