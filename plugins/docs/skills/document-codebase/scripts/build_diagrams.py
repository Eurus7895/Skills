#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/build_diagrams.py
# Regenerate: python3 tools/materialize.py
"""Lay out the class graph with Graphviz, then render Draw.io and SVG from one geometry.

    python3 scripts/build_diagrams.py --class-graph .docs-build/class-graph.json \\
        --view-spec .docs-build/view-spec.json --policy optional \\
        --out docs/_diagrams --previews

Two stages, deliberately separable:

    layout    needs `dot`. Produces one <view>-model.json per view: normalized
              coordinates pinned to the class graph's structure hash
    render    needs nothing. Turns those models into .drawio and .svg

One run can produce several views. `diagram-manifest.json` lists them all; each view
owns its own model and its own pair of rendered files, named from the view.

`--render-only` runs the second stage against an existing model. That is not a test
hatch: it is the path taken after a layout patch is applied, and it is what keeps the
two output formats honest -- both are generated from the same coordinates, so they
cannot drift into showing different things.

A view specification may choose presentation -- detail level, which layers are visible,
which packages to emphasise. It may not add a class, remove one, or change what connects
to what. Any spec that tries is refused before layout starts, because a diagram that
disagrees with the verified graph is worse than no diagram.

Missing Graphviz follows --policy: `optional` skips with a warning, `required` fails,
`disabled` does not look. Previews additionally need a rasterizer (`rsvg-convert`,
`chromium`, `chrome` or `inkscape`); with --previews and none present, this fails rather
than reporting a visual review it could not set up.

Exit codes: 0 done, 1 policy not met, 2 input/dependency error, 3 internal error.

Standard library only, plus `dot` and a rasterizer when those stages run. Writes only
under --out.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1
SUPPORTED_GRAPH_SCHEMA = {1}

# The manifest lists every view a run produced, so it carries its own version: a reader
# written against the single-view shape must refuse this one rather than see one view
# where there are eight.
MANIFEST_VERSION = 2

DEFAULT_LAYERS = ("inheritance", "composition")
ALL_LAYERS = ("inheritance", "composition", "association", "calls", "inference")

POINTS_PER_INCH = 72.0

# Past this, `public` detail produces boxes too small to read on one canvas, so the
# default drops to `summary`. Documented in references/diagram-policy.md; enforced here,
# because a threshold that only exists in prose is not a policy.
DENSITY_CLASSES = 60
DENSITY_MEMBERS = 400

# Edge styling per layer, kept here so Draw.io and SVG cannot disagree about it.
LAYER_STYLE = {
    "inheritance": {"dash": None, "arrow": "block", "colour": "#333333"},
    "composition": {"dash": None, "arrow": "diamond", "colour": "#2f6f4f"},
    "association": {"dash": "6 4", "arrow": "open", "colour": "#777777"},
    "calls": {"dash": "2 3", "arrow": "open", "colour": "#8a5a2b"},
    "inference": {"dash": "1 4", "arrow": "open", "colour": "#9a4f8a"},
}


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def hash_of(payload):
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def view_stem(view):
    """The filename every artifact of one view shares."""
    return view.replace("_", "-")


# -- view specification ------------------------------------------------------------

def default_view_spec():
    return {"view": "full_repository", "detail": None, "layers": list(DEFAULT_LAYERS),
            "emphasis": [], "rankdir": "TB"}


def check_view_spec(spec, graph):
    """Presentation only. Returns a list of refusals, empty when the spec is allowed."""
    problems = []
    layers = spec.get("layers", DEFAULT_LAYERS)
    for layer in layers:
        if layer not in ALL_LAYERS:
            problems.append("unknown layer %r" % layer)
    if spec.get("detail") not in (None, "summary", "public", "full"):
        problems.append("unknown detail level %r" % spec.get("detail"))
    if spec.get("rankdir") not in (None, "TB", "LR"):
        problems.append("rankdir must be TB or LR, not %r" % spec.get("rankdir"))

    known_classes = {c["id"] for c in graph["classes"]}
    known_packages = {p["id"] for p in graph["packages"]}
    # `scope` decides which classes a view is answerable for, so an author-supplied one
    # would be `remove_classes` under another name. It is derived from the graph's own
    # package structure and is not settable here.
    for field in ("add_classes", "remove_classes", "add_edges", "remove_edges",
                  "rename", "relationships", "scope"):
        if spec.get(field):
            # The whole point of the separation: a view plans presentation, and the
            # graph decides what is true. A spec reaching for either is not a
            # presentation choice.
            problems.append("%r is not a presentation choice; the class graph decides "
                            "what exists and what connects to what" % field)
    for class_id in spec.get("emphasis", ()):
        if class_id not in known_classes and class_id not in known_packages:
            problems.append("emphasis names %r, which is not in the class graph"
                            % class_id)
    return problems


# -- DOT -----------------------------------------------------------------------------

def dot_escape(text):
    """Quote for a DOT string literal. Backslash first or the rest is undone."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def node_label(cls, detail):
    """A UML-ish label. Kept to one string; the renderers split it back on newlines."""
    lines = [cls["name"]]
    if cls.get("stereotype") and cls["stereotype"] != "class":
        lines.insert(0, "<<%s>>" % cls["stereotype"])
    if cls.get("external"):
        # Where it lives, because the point of drawing it at all is the boundary.
        lines.append("(%s)" % str(cls.get("package", "")).split(":", 1)[-1])
        return lines
    if detail != "summary":
        for attribute in cls["members"]["attributes"]:
            types = ": " + ", ".join(attribute["types"]) if attribute["types"] else ""
            lines.append("%s%s" % (attribute["name"], types))
        for method in cls["members"]["methods"]:
            lines.append("%s()" % method["name"])
    return lines


def size_for(label_lines):
    """Node size in points, from the longest line and the line count."""
    width = max(60, 9 * max(len(line) for line in label_lines) + 24)
    height = max(30, 16 * len(label_lines) + 12)
    return width, height


def build_dot(graph, spec, labels, sizes):
    """One DOT document: package clusters, module clusters, class nodes, chosen layers."""
    layers = set(spec.get("layers", DEFAULT_LAYERS))
    lines = ["digraph classes {",
             '  graph [rankdir="%s", compound=true, newrank=true, '
             'ranksep=0.9, nodesep=0.5];' % spec.get("rankdir") or "TB",
             '  node [shape=box, fontname="Helvetica", fontsize=11];',
             '  edge [fontname="Helvetica", fontsize=9];']

    modules_by_package = {}
    for module in graph["modules"]:
        modules_by_package.setdefault(module["package"], []).append(module)

    cluster_index = {}
    for package in graph["packages"]:
        modules = [m for m in modules_by_package.get(package["id"], ()) if m["classes"]]
        if not modules:
            # An empty container is a box with nothing in it -- noise, not information.
            continue
        package_cluster = "cluster_%d" % len(cluster_index)
        cluster_index[package["id"]] = package_cluster
        lines.append('  subgraph %s {' % package_cluster)
        lines.append('    label="%s"; style="rounded"; color="#999999";'
                     % dot_escape(package["name"]))
        for module in modules:
            module_cluster = "cluster_%d" % len(cluster_index)
            cluster_index[module["id"]] = module_cluster
            lines.append('    subgraph %s {' % module_cluster)
            lines.append('      label="%s"; style="dashed"; color="#bbbbbb";'
                         % dot_escape(os.path.basename(module["name"])))
            for class_id in module["classes"]:
                width, height = sizes[class_id]
                lines.append('      "%s" [label="%s", width=%.3f, height=%.3f, '
                             'fixedsize=true];'
                             % (dot_escape(class_id),
                                dot_escape("\n".join(labels[class_id])),
                                width / POINTS_PER_INCH, height / POINTS_PER_INCH))
            lines.append('    }')
        lines.append('  }')

    class_ids = {c["id"] for c in graph["classes"]}
    for edge in graph["edges"]:
        if edge["layer"] not in layers:
            continue
        if edge["from"] not in class_ids or edge["to"] not in class_ids:
            # Association is between modules and calls name symbols; neither is drawn
            # on a class canvas. They stay in the model, out of this view.
            continue
        style = LAYER_STYLE[edge["layer"]]
        attrs = ['id="%s"' % dot_escape(edge["id"])]
        if style["dash"]:
            attrs.append('style="dashed"')
        labels_on_edge = edge.get("labels") or ([edge["label"]] if edge.get("label") else [])
        if labels_on_edge:
            attrs.append('label="%s"' % dot_escape(", ".join(labels_on_edge)))
        lines.append('  "%s" -> "%s" [%s];' % (dot_escape(edge["from"]),
                                               dot_escape(edge["to"]),
                                               ", ".join(attrs)))
    lines.append("}")
    return "\n".join(lines) + "\n", cluster_index


# -- layout --------------------------------------------------------------------------

def graphviz_version():
    try:
        proc = subprocess.run(["dot", "-V"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stderr or proc.stdout).strip() or None


def run_dot(source):
    try:
        proc = subprocess.run(["dot", "-Tjson"], input=source, capture_output=True,
                              text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "dot could not be run: %s" % exc
    if proc.returncode != 0:
        return None, "dot exited %d: %s" % (proc.returncode, proc.stderr.strip()[:400])
    try:
        return json.loads(proc.stdout), None
    except ValueError as exc:
        return None, "dot produced unreadable JSON: %s" % exc


def parse_point(text):
    x, _, y = str(text).partition(",")
    return float(x), float(y)


def normalize(laid_out, graph, spec, labels, sizes, cluster_index):
    """Graphviz coordinates -> a model with the Y axis the way a canvas expects it.

    Graphviz measures from the bottom left; Draw.io and SVG both measure from the top
    left. Flipping once here is what lets the two renderers share a geometry instead of
    each doing its own conversion and drifting apart.
    """
    bounding = laid_out.get("bb")
    if not bounding:
        return None, "dot returned no bounding box"
    _, _, page_width, page_height = [float(v) for v in bounding.split(",")]

    def flip(y, height=0.0):
        return page_height - y - height

    by_class = {c["id"]: c for c in graph["classes"]}
    reverse_clusters = {v: k for k, v in cluster_index.items()}
    module_of = {c["id"]: c["module"] for c in graph["classes"]}

    nodes, containers = [], []
    for obj in laid_out.get("objects", ()):
        name = obj.get("name", "")
        if name.startswith("cluster_"):
            box = obj.get("bb")
            if not box:
                continue
            x0, y0, x1, y1 = [float(v) for v in box.split(",")]
            container_id = reverse_clusters.get(name)
            if container_id is None:
                continue
            containers.append({
                "id": container_id,
                "label": obj.get("label", ""),
                "kind": "package" if container_id.startswith("package:") else "module",
                "x": round(x0, 2), "y": round(flip(y1), 2),
                "width": round(x1 - x0, 2), "height": round(y1 - y0, 2),
            })
            continue
        cls = by_class.get(name)
        if cls is None:
            continue
        centre_x, centre_y = parse_point(obj.get("pos", "0,0"))
        width, height = sizes[name]
        nodes.append({
            "id": name,
            "label": labels[name],
            "stereotype": cls.get("stereotype"),
            "external": bool(cls.get("external")),
            "parent": module_of.get(name),
            "cite": cls.get("cite"),
            "x": round(centre_x - width / 2.0, 2),
            "y": round(flip(centre_y + height / 2.0), 2),
            "width": round(width, 2), "height": round(height, 2),
        })

    edges = []
    for edge in laid_out.get("edges", ()):
        points = []
        for draw in edge.get("_draw_", ()):
            if draw.get("op") in ("b", "B") and draw.get("points"):
                points = [[round(x, 2), round(flip(y), 2)] for x, y in draw["points"]]
                break
        edges.append({
            "id": edge.get("id", ""),
            "layer": edge.get("layer", "inheritance"),
            "source": edge.get("tail_name", ""),
            "target": edge.get("head_name", ""),
            "label": edge.get("label", ""),
            "points": points,
        })

    # dot -Tjson names endpoints by index, not by node name, so resolve them here.
    index_to_name = {}
    for position, obj in enumerate(laid_out.get("objects", ())):
        index_to_name[obj.get("_gvid", position)] = obj.get("name", "")
    layer_of = {e["id"]: e["layer"] for e in graph["edges"]}
    for position, edge in enumerate(laid_out.get("edges", ())):
        edges[position]["source"] = index_to_name.get(edge.get("tail"), "")
        edges[position]["target"] = index_to_name.get(edge.get("head"), "")
        edges[position]["layer"] = layer_of.get(edges[position]["id"], "inheritance")

    model = {
        "schema_version": SCHEMA_VERSION,
        "source_graph_hash": graph["source_graph_hash"],
        "view_spec_hash": hash_of(spec),
        "view": spec.get("view", "full_repository"),
        # What this view is answerable for. A checker compares the drawing against the
        # scope, not against the whole graph -- otherwise a view of one package reads as
        # a view of the repository that lost most of its classes.
        "scope": dict(spec.get("scope") or {"kind": "repository"}),
        "detail": spec.get("detail") or graph["detail"],
        "layers": list(spec.get("layers", DEFAULT_LAYERS)),
        "layout_engine": {"name": "graphviz", "version": graphviz_version()},
        "containers": sorted(containers, key=lambda c: c["id"]),
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: e["id"]),
        "bounds": {"width": round(page_width, 2), "height": round(page_height, 2)},
    }
    return model, None


# -- rendering -------------------------------------------------------------------------

def override(item, field, fallback):
    """A colour a layout patch set, or the default. Patches store these under `style`."""
    return ((item.get("style") or {}).get(field)) or fallback


def drawio_style(kind, layer=None, stereotype=None, external=False):
    if kind == "package":
        return ("rounded=1;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#999999;"
                "verticalAlign=top;align=left;spacingLeft=8;dashed=0;")
    if kind == "module":
        return ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#BBBBBB;"
                "verticalAlign=top;align=left;spacingLeft=8;dashed=1;")
    if kind == "node":
        if external:
            # A neighbour, drawn so the boundary is visible. Greyed and dashed so nobody
            # reads it as a class this view is describing.
            return ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                    "fillColor=#F4F4F4;strokeColor=#999999;dashed=1;spacing=4;")
        fill = {"exception": "#FDF0EF", "abstract": "#F2F0FA",
                "enum": "#F0F6FD", "dataclass": "#F1FAF3"}.get(stereotype, "#FFFFFF")
        return ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                "fillColor=%s;strokeColor=#333333;spacing=4;" % fill)
    style = LAYER_STYLE.get(layer, LAYER_STYLE["inheritance"])
    return ("endArrow=%s;html=1;rounded=0;strokeColor=%s;%s"
            % (style["arrow"], style["colour"],
               "dashed=1;" if style["dash"] else "dashed=0;"))


def render_drawio(model):
    """Native Draw.io XML. Editable, and carrying the ids the model uses."""
    mxfile = ET.Element("mxfile", {"host": "docs-plugin"})
    diagram = ET.SubElement(mxfile, "diagram", {"name": model["view"]})
    root_model = ET.SubElement(diagram, "mxGraphModel", {
        "dx": "0", "dy": "0", "grid": "0", "page": "1",
        "pageWidth": str(int(model["bounds"]["width"]) + 40),
        "pageHeight": str(int(model["bounds"]["height"]) + 40)})
    root = ET.SubElement(root_model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # Packages before modules before classes: Draw.io needs a parent cell to exist
    # before a child references it.
    for container in sorted(model["containers"], key=lambda c: c["kind"] != "package"):
        parent = "1"
        cell = ET.SubElement(root, "mxCell", {
            "id": container["id"], "value": container["label"],
            "style": drawio_style(container["kind"]), "vertex": "1", "parent": parent})
        ET.SubElement(cell, "mxGeometry", {
            "x": str(container["x"]), "y": str(container["y"]),
            "width": str(container["width"]), "height": str(container["height"]),
            "as": "geometry"})

    for node in model["nodes"]:
        style = drawio_style("node", stereotype=node.get("stereotype"),
                             external=node.get("external"))
        fill = override(node, "fill", None)
        stroke = override(node, "stroke", None)
        if fill:
            style = re.sub(r"fillColor=[^;]*;", "fillColor=%s;" % fill, style)
        if stroke:
            style = re.sub(r"strokeColor=[^;]*;", "strokeColor=%s;" % stroke, style)
        if node.get("link"):
            # Draw.io carries a link by wrapping the cell, which is why the cell's id
            # moves out to the wrapper: the id must stay on the outermost element or
            # nothing referencing this node resolves.
            holder = ET.SubElement(root, "UserObject", {
                "id": node["id"], "label": "\n".join(node["label"]),
                "link": node["link"]})
            cell = ET.SubElement(holder, "mxCell", {
                "style": style, "vertex": "1", "parent": "1"})
        else:
            cell = ET.SubElement(root, "mxCell", {
                "id": node["id"], "value": "\n".join(node["label"]),
                "style": style, "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {
            "x": str(node["x"]), "y": str(node["y"]),
            "width": str(node["width"]), "height": str(node["height"]),
            "as": "geometry"})

    for edge in model["edges"]:
        cell = ET.SubElement(root, "mxCell", {
            "id": edge["id"], "value": edge.get("label", ""),
            "style": drawio_style("edge", layer=edge["layer"]), "edge": "1",
            "parent": "1", "source": edge["source"], "target": edge["target"]})
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if edge.get("points"):
            array = ET.SubElement(geometry, "Array", {"as": "points"})
            for x, y in edge["points"][1:-1]:
                ET.SubElement(array, "mxPoint", {"x": str(x), "y": str(y)})

    return ET.tostring(mxfile, encoding="unicode")


def svg_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_svg(model):
    """The same coordinates as the Draw.io file, drawn directly."""
    width = model["bounds"]["width"] + 40
    height = model["bounds"]["height"] + 40
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="Helvetica, Arial, sans-serif">'
           % (width, height, width, height),
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           '<g transform="translate(20,20)">']

    for container in sorted(model["containers"], key=lambda c: c["kind"] != "package"):
        dashed = ' stroke-dasharray="6 4"' if container["kind"] == "module" else ""
        out.append('<rect id="%s" x="%s" y="%s" width="%s" height="%s" fill="none" '
                   'stroke="%s"%s rx="6"/>'
                   % (svg_escape(container["id"]), container["x"], container["y"],
                      container["width"], container["height"],
                      "#999999" if container["kind"] == "package" else "#bbbbbb", dashed))
        out.append('<text x="%s" y="%s" font-size="11" fill="#666666">%s</text>'
                   % (container["x"] + 6, container["y"] + 14,
                      svg_escape(container["label"])))

    for node in model["nodes"]:
        if node.get("external"):
            default_fill, default_stroke = "#F4F4F4", "#999999"
        else:
            default_fill = {"exception": "#FDF0EF", "abstract": "#F2F0FA",
                            "enum": "#F0F6FD", "dataclass": "#F1FAF3"}.get(
                                node.get("stereotype"), "#FFFFFF")
            default_stroke = "#333333"
        fill = override(node, "fill", default_fill)
        stroke = override(node, "stroke", default_stroke)
        dashed = ' stroke-dasharray="4 3"' if node.get("external") else ""
        if node.get("link"):
            out.append('<a href="%s">' % svg_escape(node["link"]))
        out.append('<rect id="%s" x="%s" y="%s" width="%s" height="%s" fill="%s" '
                   'stroke="%s"%s/>'
                   % (svg_escape(node["id"]), node["x"], node["y"], node["width"],
                      node["height"], svg_escape(fill), svg_escape(stroke), dashed))
        for position, line in enumerate(node["label"]):
            out.append('<text x="%s" y="%s" font-size="11" fill="#111111">%s</text>'
                       % (node["x"] + 6, node["y"] + 16 + position * 14,
                          svg_escape(line)))
        if node.get("link"):
            out.append("</a>")

    for edge in model["edges"]:
        style = LAYER_STYLE.get(edge["layer"], LAYER_STYLE["inheritance"])
        dash = ' stroke-dasharray="%s"' % style["dash"] if style["dash"] else ""
        points = edge.get("points") or []
        if len(points) >= 2:
            path = "M %s %s " % tuple(points[0]) + " ".join(
                "L %s %s" % tuple(p) for p in points[1:])
            out.append('<path id="%s" d="%s" fill="none" stroke="%s"%s/>'
                       % (svg_escape(edge["id"]), path, style["colour"], dash))
    out.append("</g></svg>")
    return "\n".join(out)


def manifest_of(model):
    """What each format must contain. Compared by validate_diagrams.py."""
    return {
        "schema_version": SCHEMA_VERSION,
        "view": model["view"],
        "stem": view_stem(model["view"]),
        "scope": model.get("scope") or {"kind": "repository"},
        "source_graph_hash": model["source_graph_hash"],
        "view_spec_hash": model["view_spec_hash"],
        "layout_engine": model["layout_engine"],
        "layers": model["layers"],
        "nodes": sorted(n["id"] for n in model["nodes"]),
        "edges": sorted(e["id"] for e in model["edges"]),
        "containers": sorted(c["id"] for c in model["containers"]),
    }


def _chromium_command(tool, svg, png, size):
    # The window is sized to the drawing. A fixed window pads the diagram with blank
    # space, and a reviewer -- model or person -- then spends the image budget on it.
    #
    # `svg` here is a wrapper page, not the SVG file. Opened directly, Chromium gives
    # the document the default 8px body margin and shrinks the drawing to fit the
    # remaining width, which silently clips the bottom of the diagram -- the visual
    # review then studies a picture with classes missing from it.
    return [tool, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            "--default-background-color=ffffffff", "--screenshot=" + png,
            "--window-size=%d,%d" % size, svg]


WRAPPER = ("<!doctype html><meta charset=\"utf-8\">"
           "<style>html,body{margin:0;padding:0;background:#fff}"
           "svg{display:block}</style>%s")


def wrap_for_browser(svg_path, work_dir):
    """An HTML page holding the SVG with no page margin, for a browser rasterizer.

    Returns the page's path. Written beside nothing the caller owns -- a temp
    directory -- because the diagram directory is an output, not a scratch space.
    """
    with open(svg_path, encoding="utf-8") as fh:
        markup = fh.read()
    page = os.path.join(work_dir, "preview.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(WRAPPER % markup)
    return page


RASTERIZERS = (
    ("rsvg-convert", lambda tool, svg, png, size: [tool, "-o", png, svg]),
    ("chromium", _chromium_command),
    ("chrome", _chromium_command),
    ("inkscape", lambda tool, svg, png, size: [tool, "--export-type=png",
                                               "--export-filename=" + png, svg]),
)

# Chromium refuses a window below this, and a preview smaller than it is unreadable.
MIN_PREVIEW = (320, 240)
MAX_PREVIEW = (4000, 4000)

# A browser's --window-size counts the window frame, which the screenshot does not
# contain, so the usable viewport is shorter than the number asked for. Measured at 88px
# on Chromium 1194; the allowance is deliberately larger, because guessing low clips the
# bottom of the diagram -- classes silently missing from the picture a reviewer studies
# -- while guessing high only leaves white space under it.
BROWSER_FRAME_ALLOWANCE = 160


def find_rasterizer():
    for name, command in RASTERIZERS:
        found = shutil.which(name)
        if found:
            return found, command
    # Playwright ships one and does not put it on PATH; the environment note says so.
    bundled = "/opt/pw-browsers"
    if os.path.isdir(bundled):
        for entry in sorted(os.listdir(bundled)):
            candidate = os.path.join(bundled, entry, "chrome-linux", "chrome")
            if os.path.isfile(candidate):
                return candidate, _chromium_command
    return None, None


def rasterize(svg_path, png_path, bounds):
    tool, command = find_rasterizer()
    if tool is None:
        return "no rasterizer found (tried rsvg-convert, chromium, chrome, inkscape)"
    size = (min(max(int(bounds["width"]) + 40, MIN_PREVIEW[0]), MAX_PREVIEW[0]),
            min(max(int(bounds["height"]) + 40, MIN_PREVIEW[1]), MAX_PREVIEW[1]))
    work = None
    if command is _chromium_command:
        work = tempfile.mkdtemp(prefix="diagram-preview-")
        svg_path = wrap_for_browser(svg_path, work)
        size = (size[0], min(size[1] + BROWSER_FRAME_ALLOWANCE, MAX_PREVIEW[1]))
    # Delete any previous preview first. Left in place, a failed rasterizer leaves the
    # old PNG on disk and the existence check calls it success -- the visual review then
    # studies the previous diagram believing it is this one.
    try:
        if os.path.exists(png_path):
            os.remove(png_path)
    except OSError as exc:
        return "the previous preview could not be removed: %s" % exc
    try:
        proc = subprocess.run(command(tool, os.path.abspath(svg_path),
                                      os.path.abspath(png_path), size),
                              capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return "%s could not be run: %s" % (os.path.basename(tool), exc)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    if proc.returncode != 0:
        return "%s exited %d: %s" % (os.path.basename(tool), proc.returncode,
                                     (proc.stderr or proc.stdout or "").strip()[:300])
    if not os.path.isfile(png_path):
        return "%s produced no file: %s" % (os.path.basename(tool),
                                            (proc.stderr or "").strip()[:300])
    return None


def write_outputs(model, out_dir, previews):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stem = view_stem(model["view"])
    written = {}

    model_path = os.path.join(out_dir, "%s-model.json" % stem)
    with open(model_path, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, sort_keys=True)
    written["%s-model.json" % stem] = model_path

    drawio_path = os.path.join(out_dir, "%s.drawio" % stem)
    with open(drawio_path, "w", encoding="utf-8") as fh:
        fh.write(render_drawio(model))
    written["%s.drawio" % stem] = drawio_path

    svg_path = os.path.join(out_dir, "%s.svg" % stem)
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(render_svg(model))
    written["%s.svg" % stem] = svg_path

    error = None
    if previews:
        png_path = os.path.join(out_dir, "%s-preview.png" % stem)
        error = rasterize(svg_path, png_path, model["bounds"])
        if error is None:
            written["%s-preview.png" % stem] = png_path
    return written, error


def slug(text):
    """A filename fragment from a container path. Never empty, never a separator."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return cleaned or "unnamed"


def view_names(scopes):
    """A stable, collision-free view name per scope.

    `src/api` and `src.api` slug to the same thing. Rather than let one silently
    overwrite the other's files, both get the hash of their real id appended -- and only
    they do, so the common case keeps a readable name.
    """
    by_slug = {}
    for kind, identifier in scopes:
        path = str(identifier).split(":", 1)[-1]
        by_slug.setdefault("%s_%s" % (kind, slug(path)), []).append((kind, identifier))
    names = {}
    for base, members in by_slug.items():
        for kind, identifier in members:
            if len(members) == 1:
                names[(kind, identifier)] = base
            else:
                digest = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:8]
                names[(kind, identifier)] = "%s_%s" % (base, digest)
    return names


def scope_graph(graph, kind, identifier):
    """The slice of the graph one detail view draws, plus its boundary.

    Classes outside the scope that a drawn relationship reaches are kept as `external`
    nodes. Dropping them instead would make a package that talks to three others look
    self-contained, which is a stronger false statement than an extra grey box.
    """
    inside = [c for c in graph["classes"] if c.get(kind) == identifier]
    inside_ids = {c["id"] for c in inside}
    if not inside_ids:
        return None

    by_id = {c["id"]: c for c in graph["classes"]}
    edges, outside_ids = [], set()
    for edge in graph["edges"]:
        ends = (edge["from"], edge["to"])
        if not any(end in inside_ids for end in ends):
            continue
        # Association is module-to-module and calls name symbols; neither end of those
        # is a class node, so neither can pull a class onto this canvas.
        if not all(end in by_id for end in ends):
            continue
        edges.append(edge)
        outside_ids.update(end for end in ends if end not in inside_ids)

    classes = list(inside)
    for class_id in sorted(outside_ids):
        neighbour = dict(by_id[class_id])
        neighbour["external"] = True
        # An external neighbour is shown as itself, not as a member listing: this view
        # is not answerable for what is inside it.
        neighbour["members"] = {"methods": [], "attributes": []}
        classes.append(neighbour)

    drawn_ids = {c["id"] for c in classes}
    modules = [dict(m, classes=[c for c in m["classes"] if c in drawn_ids])
               for m in graph["modules"]]
    modules = [m for m in modules if m["classes"]]
    module_ids = {m["id"] for m in modules}
    packages = [dict(p, modules=[m for m in p["modules"] if m in module_ids])
                for p in graph["packages"]]
    packages = [p for p in packages if p["modules"]]

    return dict(graph, classes=classes, modules=modules, packages=packages, edges=edges)


def plan_views(graph, spec, detail_views=False):
    """Which views this run draws, as (graph slice, spec) pairs.

    The caller does not choose. A view's scope comes from the graph's own package
    structure, which is a fact about where the source files live -- letting a supplied
    specification pick the scope would be `remove_classes` with a friendlier name.
    """
    repository = dict(spec)
    repository["view"] = "full_repository"
    repository["scope"] = {"kind": "repository"}
    views = [(graph, repository)]

    # Below the threshold the canvas is already drawn at `public` and nothing was left
    # out, so a second set of pictures would repeat it.
    if not detail_views and effective_detail(graph, spec, warn=False) != "summary":
        return views

    scopes = []
    for package in graph["packages"]:
        slice_ = scope_graph(graph, "package", package["id"])
        if slice_ is None:
            continue
        if is_dense(slice_):
            # A package that is itself past the threshold would produce a second
            # unreadable canvas. Go one level down, and stop there.
            for module_id in package["modules"]:
                if scope_graph(graph, "module", module_id) is not None:
                    scopes.append(("module", module_id))
        else:
            scopes.append(("package", package["id"]))

    names = view_names(scopes)
    for kind, identifier in scopes:
        slice_ = scope_graph(graph, kind, identifier)
        detail_spec = dict(spec)
        detail_spec["view"] = names[(kind, identifier)]
        detail_spec["scope"] = {"kind": kind, "id": identifier}
        views.append((slice_, detail_spec))
    return views


def is_dense(graph):
    """Too much for one readable canvas at `public` detail."""
    members = sum(len(c["members"]["methods"]) + len(c["members"]["attributes"])
                  for c in graph["classes"])
    return len(graph["classes"]) > DENSITY_CLASSES or members > DENSITY_MEMBERS


def effective_detail(graph, spec, warn=True):
    """The detail level after the density rule. Explicit beats the rule; the rule beats
    the graph's own default."""
    detail = spec.get("detail") or graph["detail"]
    members = sum(len(c["members"]["methods"]) + len(c["members"]["attributes"])
                  for c in graph["classes"])
    dense = is_dense(graph)
    if dense and detail != "summary" and not warn:
        return detail if spec.get("detail") else "summary"
    if dense and detail != "summary":
        # An explicit `--view-spec` detail is the author's call and is left alone; the
        # switch applies to the default only.
        if spec.get("detail"):
            sys.stderr.write("WARN  %s: %d class(es) and %d member(s) is past the "
                             "density threshold, but the view spec asks for %r detail; "
                             "keeping it\n" % (spec.get("view"), len(graph["classes"]),
                                               members, detail))
        else:
            sys.stderr.write("WARN  %s: %d class(es) and %d member(s) is past the "
                             "density threshold; dropping to summary detail so the "
                             "canvas stays readable\n"
                             % (spec.get("view"), len(graph["classes"]), members))
            detail = "summary"
    return detail


def lay_out_view(graph, spec, dot_source_path=None):
    """One view: DOT, Graphviz, then normalized geometry."""
    # The effective level is part of the view, so it belongs in the spec that gets
    # hashed -- a diagram drawn at summary is a different view from one drawn at public.
    spec["detail"] = effective_detail(graph, spec)
    labels = {c["id"]: node_label(c, spec["detail"]) for c in graph["classes"]}
    sizes = {c["id"]: size_for(labels[c["id"]]) for c in graph["classes"]}
    source, cluster_index = build_dot(graph, spec, labels, sizes)
    if dot_source_path:
        with open(dot_source_path, "w", encoding="utf-8") as fh:
            fh.write(source)

    laid_out, error = run_dot(source)
    if error:
        return None, error
    return normalize(laid_out, graph, spec, labels, sizes, cluster_index)


def link_to_details(overview, detail_models):
    """Point each box on the overview at the view that shows it in full.

    The overview is where a reader starts and it is the view that had to drop members to
    stay readable, so it is the one that needs a way onward.
    """
    destination = {}
    for model in detail_models:
        target = "%s.svg" % view_stem(model["view"])
        for node in model["nodes"]:
            if not node.get("external"):
                destination[node["id"]] = target
    for node in overview["nodes"]:
        if node["id"] in destination:
            node["link"] = destination[node["id"]]
    return overview


def write_manifest(out_dir, entries, keep_others=False):
    """List every view of this run. `keep_others` preserves views this run did not touch.

    A render-only pass rebuilds one view. Rewriting the manifest from that one entry
    would delete every other view from the record while its files sit on disk, so the
    patch loop reads as having destroyed seven diagrams to fix one.
    """
    path = os.path.join(out_dir, "diagram-manifest.json")
    merged = {entry["view"]: entry for entry in entries}
    if keep_others and os.path.isfile(path):
        existing, error = load_json(path, "diagram manifest")
        if error is None and existing.get("schema_version") == MANIFEST_VERSION:
            for entry in existing.get("views", ()):
                merged.setdefault(entry.get("view"), entry)
    payload = {"schema_version": MANIFEST_VERSION,
               "views": [merged[key] for key in sorted(merged)]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--class-graph", default=".docs-build/class-graph.json")
    parser.add_argument("--view-spec", help="presentation plan; defaults are used without one")
    parser.add_argument("--out", default="docs/_diagrams")
    parser.add_argument("--policy", default="optional",
                        choices=("disabled", "optional", "required"),
                        help="what to do when Graphviz is unavailable")
    parser.add_argument("--previews", action="store_true",
                        help="also rasterize a PNG for visual review")
    parser.add_argument("--render-only", metavar="MODEL",
                        help="skip layout and render this existing diagram model")
    parser.add_argument("--detail-views", action="store_true",
                        help="draw a per-package view as well, even below the density "
                             "threshold where the full canvas already shows members")
    parser.add_argument("--dot-source", metavar="FILE",
                        help="also write the generated DOT here, for debugging")
    args = parser.parse_args()

    if args.render_only:
        model, error = load_json(args.render_only, "diagram model")
        if error:
            return fail(error)
        if model.get("schema_version") not in {SCHEMA_VERSION}:
            return fail("%s declares schema_version %r; this renderer supports %d"
                        % (args.render_only, model.get("schema_version"), SCHEMA_VERSION))
        written, preview_error = write_outputs(model, args.out, args.previews)
        if preview_error:
            return fail("--previews was asked for but %s" % preview_error)
        write_manifest(args.out, [manifest_of(model)], keep_others=True)
        print("rendered %d artifact(s) to %s from an existing model of view %r"
              % (len(written), args.out, model["view"]))
        return 0

    graph, error = load_json(args.class_graph, "class graph")
    if error:
        return fail(error)
    if graph.get("schema_version") not in SUPPORTED_GRAPH_SCHEMA:
        return fail("%s declares schema_version %r; this script supports %s"
                    % (args.class_graph, graph.get("schema_version"),
                       sorted(SUPPORTED_GRAPH_SCHEMA)))

    spec = default_view_spec()
    if args.view_spec:
        supplied, error = load_json(args.view_spec, "view specification")
        if error:
            return fail(error)
        spec.update(supplied)
    problems = check_view_spec(spec, graph)
    if problems:
        for problem in problems:
            sys.stderr.write("  %s\n" % problem)
        return fail("the view specification is not presentation-only; nothing rendered")

    if args.policy == "disabled":
        print("diagrams: disabled by policy; nothing attempted")
        return 0
    if shutil.which("dot") is None:
        message = "Graphviz (`dot`) is not installed, so no layout can be computed"
        if args.policy == "required":
            return fail("--policy required but %s" % message)
        sys.stderr.write("WARN  %s; skipping diagrams\n" % message)
        print("diagrams: skipped -- %s" % message)
        return 0

    if not graph["classes"]:
        print("diagrams: skipped -- the class graph contains no classes")
        return 0

    planned = plan_views(graph, spec, args.detail_views)
    models, engine = [], None
    for view_graph, view_spec in planned:
        # One DOT file per view, so --dot-source on a multi-view run does not leave the
        # last view's source pretending to be the whole run's.
        dot_source = args.dot_source
        if dot_source and len(planned) > 1:
            base, extension = os.path.splitext(dot_source)
            dot_source = "%s-%s%s" % (base, view_stem(view_spec["view"]),
                                      extension or ".dot")
        model, error = lay_out_view(view_graph, view_spec, dot_source)
        if error:
            return fail(error)
        models.append(model)
        engine = model["layout_engine"]["version"] or "graphviz"

    # Linking needs every view laid out, so it happens between layout and writing: a
    # model is written once, already carrying the links, and --render-only reproduces
    # them from the file rather than recomputing what it cannot see.
    details = [m for m in models
               if (m.get("scope") or {}).get("kind") in ("package", "module")]
    for model in models:
        if (model.get("scope") or {}).get("kind") == "repository" and details:
            link_to_details(model, details)

    entries = []
    for model in models:
        written, preview_error = write_outputs(model, args.out, args.previews)
        if preview_error:
            return fail("--previews was asked for but %s" % preview_error)
        entries.append(manifest_of(model))
        print("%s: %d artifact(s), %d node(s), %d edge(s), %d container(s)"
              % (model["view"], len(written), len(model["nodes"]),
                 len(model["edges"]), len(model["containers"])))

    write_manifest(args.out, entries)
    print("wrote %d view(s) to %s" % (len(entries), args.out))
    print("layout engine: %s" % engine)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
