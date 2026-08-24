#!/usr/bin/env python3
"""Check rendered diagrams against the class graph they claim to draw.

    python3 scripts/validate_diagrams.py docs/_diagrams \\
        --class-graph .docs-build/class-graph.json

A diagram is a claim like any other: it says these classes exist, in these packages,
related this way. This script decides whether the rendered files still say that. It runs
without Graphviz, so the render path stays checkable on a machine that cannot lay one
out, and it runs again after every layout patch -- a patch that is allowed to move a box
is not allowed to lose one.

What is checked:

    coverage    every class in the graph is a node; every verified inheritance edge
                is drawn. This is the promise the diagram rests on
    identity    the model is pinned to the graph hash it was laid out from
    integrity   unique ids, no edge to a node that is not there, every class inside
                the container that owns it
    geometry    finite, non-zero, and no two sibling boxes overlapping. Nesting a
                class inside its module is not an overlap; two classes sharing the
                same space is
    equivalence Draw.io and SVG contain the same nodes and edges. They are generated
                from one geometry, so a difference means one of them was edited or
                one renderer has drifted

Finding codes: G001 coverage, G002 identity, G003 integrity, G004 geometry,
G005 equivalence, G006 malformed output.

Exit codes: 0 no findings, 1 findings, 2 input error, 3 internal error.

Standard library only. Reads the diagram directory and the class graph; writes nothing.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

SUPPORTED_MODEL_SCHEMA = {1}
SUPPORTED_MANIFEST_SCHEMA = {2}

# Two boxes may share space only when one contains the other. A class sits inside its
# module, which sits inside its package; anything else overlapping is a readability
# defect the renderer should not have produced.
OVERLAP_TOLERANCE = 1.0


class Findings(object):
    def __init__(self):
        self.rows = []

    def add(self, code, message):
        self.rows.append({"code": code, "message": message})

    def __len__(self):
        return len(self.rows)


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def view_stem(view):
    return str(view).replace("_", "-")


def classes_in_scope(graph, scope):
    """Which classes this view is answerable for.

    A view of one package is complete when it holds that package's classes, not the
    repository's. Judging every view against the whole graph would make each detail
    view look like a full canvas that lost most of its boxes.
    """
    kind = (scope or {}).get("kind", "repository")
    if kind == "repository":
        return {c["id"] for c in graph["classes"]}
    if kind == "package":
        return {c["id"] for c in graph["classes"] if c.get("package") == scope.get("id")}
    if kind == "module":
        return {c["id"] for c in graph["classes"] if c.get("module") == scope.get("id")}
    return None


def box_of(item):
    return (float(item["x"]), float(item["y"]),
            float(item["x"]) + float(item["width"]),
            float(item["y"]) + float(item["height"]))


def contains(outer, inner):
    return (outer[0] <= inner[0] + OVERLAP_TOLERANCE
            and outer[1] <= inner[1] + OVERLAP_TOLERANCE
            and outer[2] >= inner[2] - OVERLAP_TOLERANCE
            and outer[3] >= inner[3] - OVERLAP_TOLERANCE)


def overlaps(a, b):
    return (a[0] < b[2] - OVERLAP_TOLERANCE and b[0] < a[2] - OVERLAP_TOLERANCE
            and a[1] < b[3] - OVERLAP_TOLERANCE and b[1] < a[3] - OVERLAP_TOLERANCE)


def check_coverage(model, graph, findings):
    scope = model.get("scope") or {"kind": "repository"}
    expected = classes_in_scope(graph, scope)
    if expected is None:
        findings.add("G001", "the diagram declares scope %r, which this checker does "
                             "not know how to hold it to" % scope)
        return
    drawn = {n["id"] for n in model["nodes"]}
    missing = sorted(expected - drawn)
    if missing:
        findings.add("G001", "%d class(es) in scope are not in the diagram: %s"
                     % (len(missing), ", ".join(missing[:5])))
    invented = sorted(drawn - {c["id"] for c in graph["classes"]})
    if invented:
        # Worse than a missing class: a box nobody can trace back to the source.
        findings.add("G001", "%d node(s) in the diagram are not in the graph: %s"
                     % (len(invented), ", ".join(invented[:5])))

    # A node outside the scope is legitimate only as a marked neighbour: the far end of
    # a relationship that leaves this view. An unmarked one is a view quietly drawing
    # something it is not answerable for.
    for node in model["nodes"]:
        if node["id"] not in expected and not node.get("external"):
            findings.add("G001", "node %r is outside this view's scope but is not "
                                 "marked as an external neighbour" % node["id"])
        if node["id"] in expected and node.get("external"):
            findings.add("G001", "node %r is in scope but is drawn as an external "
                                 "neighbour" % node["id"])

    if "inheritance" in model.get("layers", ()):
        # An edge with one end in scope is drawn, and so is required: dropping it is how
        # a package view comes to look self-contained.
        wanted = {e["id"] for e in graph["edges"]
                  if e["layer"] == "inheritance"
                  and (e["from"] in expected or e["to"] in expected)
                  and e["from"] in drawn and e["to"] in drawn}
        present = {e["id"] for e in model["edges"]}
        lost = sorted(wanted - present)
        if lost:
            findings.add("G001", "%d verified inheritance edge(s) are not drawn: %s"
                         % (len(lost), ", ".join(lost[:5])))


def check_identity(model, graph, findings):
    if model.get("source_graph_hash") != graph.get("source_graph_hash"):
        findings.add("G002", "the diagram was laid out from a different class graph "
                             "(%s) than the one supplied (%s)"
                     % (model.get("source_graph_hash", "?")[:19],
                        graph.get("source_graph_hash", "?")[:19]))


def check_integrity(model, graph, findings):
    node_ids, container_ids = set(), set()
    for node in model["nodes"]:
        if node["id"] in node_ids:
            findings.add("G003", "duplicate node id %r" % node["id"])
        node_ids.add(node["id"])
    for container in model["containers"]:
        if container["id"] in container_ids:
            findings.add("G003", "duplicate container id %r" % container["id"])
        container_ids.add(container["id"])

    edge_ids = set()
    for edge in model["edges"]:
        if edge["id"] in edge_ids:
            findings.add("G003", "duplicate edge id %r" % edge["id"])
        edge_ids.add(edge["id"])
        for end in ("source", "target"):
            if edge[end] not in node_ids:
                findings.add("G003", "edge %r end %r is not a node in this diagram"
                             % (edge["id"], edge[end]))

    owner = {c["id"]: c["module"] for c in graph["classes"]}
    for node in model["nodes"]:
        expected = owner.get(node["id"])
        if expected and node.get("parent") != expected:
            findings.add("G003", "node %r is placed in %r but the graph owns it under %r"
                         % (node["id"], node.get("parent"), expected))
        if expected and expected in container_ids:
            module_box = box_of(next(c for c in model["containers"]
                                     if c["id"] == expected))
            if not contains(module_box, box_of(node)):
                findings.add("G003", "node %r is drawn outside its module container"
                             % node["id"])


def check_geometry(model, findings):
    boxes = []
    container_ids = {c["id"] for c in model["containers"]}
    for item in list(model["nodes"]) + list(model["containers"]):
        try:
            box = box_of(item)
        except (KeyError, TypeError, ValueError):
            findings.add("G004", "%r has no usable geometry" % item.get("id"))
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        if not all(map(_finite, box)):
            findings.add("G004", "%r has non-finite geometry" % item["id"])
            continue
        if width <= 0 or height <= 0:
            findings.add("G004", "%r has zero or negative size (%gx%g)"
                         % (item["id"], width, height))
            continue
        boxes.append((item["id"], box))

    if len({box for _, box in boxes}) == 1 and len(boxes) > 1:
        findings.add("G004", "every box has identical geometry; the layout did not run")

    for position, (id_a, box_a) in enumerate(boxes):
        for id_b, box_b in boxes[position + 1:]:
            if not overlaps(box_a, box_b):
                continue
            # Nesting is the whole point of a container, so a container swallowing
            # something is fine. Two *class* boxes are never legitimately nested: one
            # drawn on top of another hides it completely, and treating that as
            # containment would let the worst overlap there is pass unreported.
            outer = None
            if contains(box_a, box_b):
                outer = id_a
            elif contains(box_b, box_a):
                outer = id_b
            if outer is not None and outer in container_ids:
                continue
            findings.add("G004", "%r and %r overlap; neither is a container, so one is "
                                 "hiding the other" % (id_a, id_b))

    bounds = model.get("bounds") or {}
    if not bounds.get("width") or not bounds.get("height"):
        findings.add("G004", "the diagram declares no usable bounds")


def _finite(value):
    return value == value and value not in (float("inf"), float("-inf"))


def parse_drawio(path, findings):
    """Node and edge ids from the Draw.io file, or None when it will not parse."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        findings.add("G006", "%s is not well-formed XML: %s" % (os.path.basename(path), exc))
        return None, None
    nodes, edges = set(), set()
    for cell in root.iter("mxCell"):
        cell_id = cell.get("id")
        if cell.get("edge") == "1":
            edges.add(cell_id)
        elif cell.get("vertex") == "1":
            nodes.add(cell_id)
    return nodes, edges


def parse_svg(path, findings):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        findings.add("G006", "%s is not well-formed XML: %s" % (os.path.basename(path), exc))
        return None, None
    nodes, edges = set(), set()
    for element in root.iter():
        identifier = element.get("id")
        if not identifier:
            continue
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "rect":
            nodes.add(identifier)
        elif tag == "path":
            edges.add(identifier)
    return nodes, edges


def check_equivalence(model, out_dir, findings):
    stem = view_stem(model["view"])
    drawio_path = os.path.join(out_dir, "%s.drawio" % stem)
    svg_path = os.path.join(out_dir, "%s.svg" % stem)
    for path in (drawio_path, svg_path):
        if not os.path.isfile(path):
            findings.add("G006", "%s was not rendered" % os.path.basename(path))
            return

    drawio_nodes, drawio_edges = parse_drawio(drawio_path, findings)
    svg_nodes, svg_edges = parse_svg(svg_path, findings)
    if drawio_nodes is None or svg_nodes is None:
        return

    expected_nodes = {n["id"] for n in model["nodes"]} | {c["id"] for c in model["containers"]}
    expected_edges = {e["id"] for e in model["edges"] if e.get("points")}

    # Both directions. Checking only what is missing lets an artifact grow a node or an
    # edge that no class graph backs -- a picture asserting something the source never
    # said, which is the failure the whole gate exists to catch.
    for label, found in (("Draw.io", drawio_nodes), ("SVG", svg_nodes)):
        missing = sorted(expected_nodes - found)
        if missing:
            findings.add("G005", "%s is missing %d node(s) the model declares: %s"
                         % (label, len(missing), ", ".join(missing[:5])))
        extra = sorted(found - expected_nodes)
        if extra:
            findings.add("G005", "%s contains %d node(s) the model does not declare: %s"
                         % (label, len(extra), ", ".join(extra[:5])))
    for label, found in (("Draw.io", drawio_edges), ("SVG", svg_edges)):
        missing = sorted(expected_edges - found)
        if missing:
            findings.add("G005", "%s is missing %d edge(s) the model declares: %s"
                         % (label, len(missing), ", ".join(missing[:5])))
        extra = sorted(found - {e["id"] for e in model["edges"]})
        if extra:
            findings.add("G005", "%s contains %d edge(s) the model does not declare: %s"
                         % (label, len(extra), ", ".join(extra[:5])))

    # The two formats come from one geometry, so a difference between them means one was
    # edited by hand or one renderer has drifted from the other.
    only_drawio = sorted(drawio_nodes - svg_nodes)
    only_svg = sorted(svg_nodes - drawio_nodes)
    if only_drawio or only_svg:
        findings.add("G005", "Draw.io and SVG disagree: %r only in Draw.io, %r only in SVG"
                     % (only_drawio[:3], only_svg[:3]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="the rendered diagram directory")
    parser.add_argument("--class-graph", default=".docs-build/class-graph.json")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()

    if not os.path.isdir(args.out_dir):
        sys.stderr.write("FAIL  not a directory: %s\n" % args.out_dir)
        return 2
    manifest, error = load_json(os.path.join(args.out_dir, "diagram-manifest.json"),
                                "diagram manifest")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMA:
        sys.stderr.write("FAIL  the diagram manifest declares schema_version %r; this "
                         "script supports %s\n" % (manifest.get("schema_version"),
                                                   sorted(SUPPORTED_MANIFEST_SCHEMA)))
        return 2
    if not manifest.get("views"):
        sys.stderr.write("FAIL  the diagram manifest lists no views\n")
        return 2
    graph, error = load_json(args.class_graph, "class graph")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2

    findings = Findings()
    models = []
    for entry in manifest["views"]:
        stem = entry.get("stem") or view_stem(entry.get("view", ""))
        model, error = load_json(os.path.join(args.out_dir, "%s-model.json" % stem),
                                 "diagram model for view %r" % entry.get("view"))
        if error:
            sys.stderr.write("FAIL  %s\n" % error)
            return 2
        if model.get("schema_version") not in SUPPORTED_MODEL_SCHEMA:
            sys.stderr.write("FAIL  the diagram model for %r declares schema_version "
                             "%r; this script supports %s\n"
                             % (entry.get("view"), model.get("schema_version"),
                                sorted(SUPPORTED_MODEL_SCHEMA)))
            return 2
        models.append(model)
        check_identity(model, graph, findings)
        check_coverage(model, graph, findings)
        check_integrity(model, graph, findings)
        check_geometry(model, findings)
        check_equivalence(model, args.out_dir, findings)

    if args.json:
        json.dump({"diagram": args.out_dir,
                   "views": [m.get("view") for m in models],
                   "findings": findings.rows, "passed": not findings},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    elif findings:
        for row in findings.rows:
            print("%s  %s" % (row["code"], row["message"]))
        print("")
        print("FAIL  %d finding(s)" % len(findings))
    else:
        for model in models:
            print("ok  %s: %d node(s), %d edge(s), %d container(s); Draw.io and SVG "
                  "agree" % (model["view"], len(model["nodes"]), len(model["edges"]),
                             len(model["containers"])))
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
