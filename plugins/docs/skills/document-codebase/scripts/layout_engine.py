#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/layout_engine.py
# Regenerate: python3 tools/materialize.py
"""Place a class graph on a canvas without Graphviz.

    import layout_engine
    placement = layout_engine.place(graph, spec, labels, sizes)

Graphviz does exactly one thing for this pipeline: it turns a graph into coordinates.
Everything after that -- the model, the Draw.io and SVG emitters, previews, the
structural checks, layout patches, detail views -- is already ours. This is the same one
thing, in the standard library, so a machine with no `dot` gets a diagram rather than a
line of prose explaining that it does not.

**Laid out by container, not by global rank.** The obvious approach is to rank every
class at once and hope the clusters fall out; they do not, which is why Graphviz needs
explicit cluster constraints to hold them together. Here the nesting comes first: a
module's classes are placed inside that module's box, modules inside their package's
box, packages across the canvas. Containment and adjacency are then properties of the
construction rather than something to enforce afterwards, and two boxes cannot overlap
because no two are ever placed in the same region.

Within a module the classes are ranked by the inheritance and composition edges between
them -- a base above its subclasses -- ordered by barycentre so edges cross as little as
a single pass manages, and packed left to right at their real widths.

What this gives up against Graphviz is edge routing. A line here runs straight between
two box borders and will cross a box that sits between them. Graphviz avoids that, and
where `dot` is installed it stays the better engine.

Deterministic: the same graph and the same spec produce the same coordinates, because
every collection is sorted before it is walked.

Standard library only. Computes; writes nothing.
"""

# Room for a container's own label, and the gap between things.
LABEL_BAND = 22
PADDING = 14
COLUMN_GAP = 30
ROW_GAP = 46
PACKAGE_GAP = 46

# Packages are laid across the canvas and wrapped, so a repository with twenty of them
# produces a page rather than a strip four screens wide.
MAX_ROW_WIDTH = 2600


def _visible_class_edges(graph, layers):
    """Edges this view draws between two classes it also draws."""
    drawn = {c["id"] for c in graph["classes"]}
    edges = []
    for edge in sorted(graph["edges"], key=lambda e: e["id"]):
        if edge["layer"] not in layers:
            continue
        if edge["from"] not in drawn or edge["to"] not in drawn:
            # Association joins modules and calls name symbols; neither is a class node,
            # so neither can pull anything onto this canvas.
            continue
        edges.append(edge)
    return edges


def _rank(members, edges):
    """Longest-path rank per class: a base above everything that derives from it.

    Cycles are broken by ignoring the edge that closes them. A class hierarchy should
    not contain one, but a `composition` layer can, and a layout that recursed forever
    on real input would be worse than one that draws the cycle slightly wrong.
    """
    inside = set(members)
    parents = {member: [] for member in members}
    for edge in edges:
        if edge["from"] in inside and edge["to"] in inside and edge["from"] != edge["to"]:
            # `from` derives from `to`, so `to` is the shallower of the two.
            parents[edge["from"]].append(edge["to"])

    rank, visiting = {}, set()

    def depth(node):
        if node in rank:
            return rank[node]
        if node in visiting:
            return 0                      # the edge closing a cycle contributes nothing
        visiting.add(node)
        found = 0
        for parent in sorted(parents[node]):
            found = max(found, depth(parent) + 1)
        visiting.discard(node)
        rank[node] = found
        return found

    for member in sorted(members):
        depth(member)
    return rank


def _order_rows(rows, edges, members):
    """One barycentre sweep per row, downwards: a child sits under its parents.

    One pass, not iterated to convergence. The rows here are a single module's classes,
    so they are short, and the honest description of this engine is "tidy enough to
    read", not "as good as Graphviz".
    """
    inside = set(members)
    parents = {member: [] for member in members}
    for edge in edges:
        if edge["from"] in inside and edge["to"] in inside:
            parents[edge["from"]].append(edge["to"])

    position = {}
    for depth in sorted(rows):
        row = rows[depth]
        if depth == min(rows):
            row.sort()
        else:
            def barycentre(node):
                above = [position[p] for p in parents[node] if p in position]
                # A class with no parent in the row above keeps a stable place rather
                # than drifting to one end: sorting is by (barycentre, id), and an
                # absent barycentre sorts as its own name would.
                return (sum(above) / float(len(above)) if above else len(position), node)
            row.sort(key=barycentre)
        for index, node in enumerate(row):
            position[node] = index
    return rows


def _place_module(members, edges, sizes, origin_x, origin_y):
    """Classes of one module, in rows by rank. Returns (placed, width, height)."""
    ranks = _rank(members, edges)
    rows = {}
    for member in sorted(members):
        rows.setdefault(ranks[member], []).append(member)
    rows = _order_rows(rows, edges, members)

    placed, y = {}, origin_y
    width = 0
    for depth in sorted(rows):
        x, tallest = origin_x, 0
        for member in rows[depth]:
            box_width, box_height = sizes[member]
            placed[member] = (x, y, box_width, box_height)
            x += box_width + COLUMN_GAP
            tallest = max(tallest, box_height)
        width = max(width, x - COLUMN_GAP - origin_x)
        y += tallest + ROW_GAP
    height = (y - ROW_GAP) - origin_y if rows else 0
    return placed, max(width, 0), max(height, 0)


def _border_point(box, towards):
    """Where a line from the centre of `box` to `towards` leaves the box.

    Straight lines between borders rather than between centres: an arrow that starts
    inside its own node looks like it starts nowhere.
    """
    x, y, width, height = box
    cx, cy = x + width / 2.0, y + height / 2.0
    dx, dy = towards[0] - cx, towards[1] - cy
    if dx == 0 and dy == 0:
        return [round(cx, 2), round(cy, 2)]
    scale_x = (width / 2.0) / abs(dx) if dx else float("inf")
    scale_y = (height / 2.0) / abs(dy) if dy else float("inf")
    scale = min(scale_x, scale_y)
    return [round(cx + dx * scale, 2), round(cy + dy * scale, 2)]


def place(graph, spec, labels, sizes):
    """Coordinates for every class, container and edge this view draws.

    Returns the same shape the Graphviz path produces after normalisation: top-left
    origins, y increasing downwards, ready for either renderer.
    """
    layers = set(spec.get("layers", ()))
    edges = _visible_class_edges(graph, layers)

    classes_by_module = {}
    for cls in sorted(graph["classes"], key=lambda c: c["id"]):
        classes_by_module.setdefault(cls["module"], []).append(cls["id"])
    modules_by_package = {}
    for module in sorted(graph["modules"], key=lambda m: m["id"]):
        if classes_by_module.get(module["id"]):
            modules_by_package.setdefault(module["package"], []).append(module)

    node_boxes, containers = {}, []
    cursor_x, row_top, row_height = PADDING, PADDING, 0

    for package in sorted(graph["packages"], key=lambda p: p["id"]):
        modules = modules_by_package.get(package["id"], [])
        if not modules:
            # An empty container is a box with nothing in it: noise, not information.
            continue

        # Lay the package's modules out relative to (0, 0), then translate the lot once
        # the package's own size is known. Two passes are simpler to follow than
        # arithmetic that guesses the width up front.
        local, inner_y, inner_width = [], LABEL_BAND + PADDING, 0
        for module in modules:
            members = classes_by_module[module["id"]]
            placed, width, height = _place_module(
                members, edges, sizes, PADDING * 2, inner_y + LABEL_BAND + PADDING)
            module_height = height + LABEL_BAND + PADDING * 2
            local.append((module, placed,
                          (PADDING, inner_y, width + PADDING * 2, module_height)))
            inner_width = max(inner_width, width + PADDING * 3)
            inner_y += module_height + PADDING
        package_width = inner_width + PADDING
        package_height = inner_y + PADDING - (LABEL_BAND + PADDING) + LABEL_BAND

        if cursor_x > PADDING and cursor_x + package_width > MAX_ROW_WIDTH:
            cursor_x = PADDING
            row_top += row_height + PACKAGE_GAP
            row_height = 0

        containers.append({"id": package["id"], "label": package["name"],
                           "kind": "package", "x": round(float(cursor_x), 2),
                           "y": round(float(row_top), 2),
                           "width": round(float(package_width), 2),
                           "height": round(float(package_height), 2)})
        for module, placed, (mx, my, mw, mh) in local:
            containers.append({
                "id": module["id"],
                "label": module["name"].rsplit("/", 1)[-1], "kind": "module",
                "x": round(float(cursor_x + mx), 2), "y": round(float(row_top + my), 2),
                "width": round(float(mw), 2), "height": round(float(mh), 2)})
            for member, (bx, by, bw, bh) in placed.items():
                node_boxes[member] = (cursor_x + bx, row_top + by, bw, bh)

        cursor_x += package_width + PACKAGE_GAP
        row_height = max(row_height, package_height)

    by_class = {c["id"]: c for c in graph["classes"]}
    nodes = []
    for identifier, (x, y, width, height) in sorted(node_boxes.items()):
        cls = by_class[identifier]
        nodes.append({
            "id": identifier, "label": labels[identifier],
            "stereotype": cls.get("stereotype"),
            "external": bool(cls.get("external")),
            "parent": cls["module"], "cite": cls.get("cite"),
            "x": round(float(x), 2), "y": round(float(y), 2),
            "width": round(float(width), 2), "height": round(float(height), 2)})

    drawn_edges = []
    for edge in edges:
        tail, head = node_boxes.get(edge["from"]), node_boxes.get(edge["to"])
        if not tail or not head:
            continue
        tail_centre = (tail[0] + tail[2] / 2.0, tail[1] + tail[3] / 2.0)
        head_centre = (head[0] + head[2] / 2.0, head[1] + head[3] / 2.0)
        drawn_edges.append({
            "id": edge["id"], "layer": edge["layer"],
            "source": edge["from"], "target": edge["to"],
            "label": ", ".join(edge.get("labels") or ([edge["label"]]
                                                      if edge.get("label") else [])),
            "points": [_border_point(tail, head_centre),
                       _border_point(head, tail_centre)]})

    boxes = list(node_boxes.values()) + [(c["x"], c["y"], c["width"], c["height"])
                                         for c in containers]
    width = max([x + w for x, _, w, _ in boxes] or [0]) + PADDING
    height = max([y + h for _, y, _, h in boxes] or [0]) + PADDING
    return {
        "nodes": nodes,
        "containers": sorted(containers, key=lambda c: c["id"]),
        "edges": sorted(drawn_edges, key=lambda e: e["id"]),
        "bounds": {"width": round(float(width), 2), "height": round(float(height), 2)},
    }
