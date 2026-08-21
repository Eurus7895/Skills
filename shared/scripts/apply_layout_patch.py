#!/usr/bin/env python3
"""Apply presentation-only changes to a diagram model. Refuse everything else.

    python3 scripts/apply_layout_patch.py --model docs/_diagrams/diagram-model.json \\
        --patch docs/_diagrams/layout-patch.json --out docs/_diagrams/diagram-model.json

A visual reviewer -- a model looking at a rendered preview -- can see that two boxes
collide or a label is clipped. It cannot see whether a class really inherits from
another, and it must never be in a position to change that. So a patch is not a diff
over the model: it is a list of named operations from a fixed allowlist, and anything
outside that list is refused before a single byte is written.

Allowed:

    move    a node or container, by delta or to a position
    resize  a node or container
    route   an edge's waypoints
    style   fill or stroke of a node
    wrap    re-flow a node's label at a character width

Refused, always: adding or removing a node or edge, changing an edge's endpoints or
layer, changing a node's parent, touching a citation, a source hash, or the graph hash.
Those are facts about the code, and no amount of looking at a picture is evidence about
them.

A patch records the hashes it was made against. Applying it to a model built from a
different class graph, view spec or renderer is refused: the coordinates it moves would
be moving something else. That same record is what lets an unchanged repository reuse an
accepted patch instead of paying for another visual review.

Exit codes: 0 applied, 1 the patch does not apply, 2 input error, 3 internal error.

Standard library only. Reads the model and the patch; writes only --out.
"""

import argparse
import json
import os
import sys

SUPPORTED_MODEL_SCHEMA = {1}
PATCH_SCHEMA_VERSION = 1

OPERATIONS = ("move", "resize", "route", "style", "wrap")

# Fields a patch may never write, whatever operation it claims to be. Listed rather
# than inferred, so adding a field to the model does not silently make it patchable.
#
# `target` is deliberately absent: it is how an operation names what it acts on, not
# something it writes. The endpoint spellings a patch might reach for instead are all
# here.
PROTECTED = ("id", "parent", "source", "layer", "cite", "source_hash",
             "source_graph_hash", "claim_id", "verified", "stereotype",
             "from", "to", "target_node", "endpoint", "nodes", "edges", "containers")


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def wrap_label(lines, width):
    """Re-flow long label lines. Words are never split; a long identifier stays whole."""
    wrapped = []
    for line in lines:
        if len(line) <= width:
            wrapped.append(line)
            continue
        current = ""
        for word in line.split(" "):
            if current and len(current) + 1 + len(word) > width:
                wrapped.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            wrapped.append(current)
    return wrapped


def check_patch(patch, model):
    """Every reason this patch may not be applied. Empty means it may."""
    problems = []
    if patch.get("schema_version") != PATCH_SCHEMA_VERSION:
        problems.append("patch declares schema_version %r; this script applies %d"
                        % (patch.get("schema_version"), PATCH_SCHEMA_VERSION))
        return problems

    applies_to = patch.get("applies_to") or {}
    for field, expected in (("source_graph_hash", model.get("source_graph_hash")),
                            ("view_spec_hash", model.get("view_spec_hash"))):
        recorded = applies_to.get(field)
        if not recorded:
            # Absent is not "applies to anything". A patch with no identity could be
            # replayed onto any diagram whose ids happen to overlap, which is exactly
            # what recording the hashes was meant to stop.
            problems.append("patch records no %s, so there is nothing to check it "
                            "against; a patch without identity is not reusable" % field)
        elif recorded != expected:
            problems.append("patch was made against %s %s, but this model is %s -- the "
                            "coordinates it moves belong to a different diagram"
                            % (field, recorded[:19], (expected or "?")[:19]))

    targets = ({n["id"] for n in model["nodes"]}
               | {c["id"] for c in model["containers"]}
               | {e["id"] for e in model["edges"]})

    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        problems.append("patch lists no operations")
        return problems

    for position, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            problems.append("operation %d is not an object" % position)
            continue
        name = operation.get("op")
        if name not in OPERATIONS:
            problems.append("operation %d is %r, which is not a presentation operation; "
                            "allowed: %s" % (position, name, ", ".join(OPERATIONS)))
            continue
        target = operation.get("target")
        if target not in targets:
            problems.append("operation %d targets %r, which is not in this diagram"
                            % (position, target))
        for field in PROTECTED:
            if field in operation:
                problems.append("operation %d sets %r, which is a fact about the code, "
                                "not a presentation choice" % (position, field))
        if name == "route" and not isinstance(operation.get("points"), list):
            problems.append("operation %d is a route with no points" % position)
        if name in ("move", "resize"):
            for field in ("dx", "dy", "x", "y", "width", "height"):
                value = operation.get(field)
                if value is not None and not isinstance(value, (int, float)):
                    problems.append("operation %d has a non-numeric %s (%r)"
                                    % (position, field, value))
        if name == "resize":
            for field in ("width", "height"):
                value = operation.get(field)
                if value is not None and value <= 0:
                    problems.append("operation %d resizes %s to %r; a box with no size "
                                    "is invisible, not compact"
                                    % (position, field, value))
        if name == "wrap" and not isinstance(operation.get("width"), int):
            problems.append("operation %d is a wrap with no character width" % position)
    return problems


def apply_patch(model, patch):
    """Apply an already-checked patch. Returns the count of operations applied."""
    by_id = {}
    for item in list(model["nodes"]) + list(model["containers"]) + list(model["edges"]):
        by_id[item["id"]] = item

    applied = 0
    for operation in patch["operations"]:
        target = by_id[operation["target"]]
        name = operation["op"]
        if name == "move":
            if "x" in operation:
                target["x"] = float(operation["x"])
            if "y" in operation:
                target["y"] = float(operation["y"])
            target["x"] = float(target.get("x", 0)) + float(operation.get("dx", 0))
            target["y"] = float(target.get("y", 0)) + float(operation.get("dy", 0))
        elif name == "resize":
            if "width" in operation:
                target["width"] = float(operation["width"])
            if "height" in operation:
                target["height"] = float(operation["height"])
        elif name == "route":
            target["points"] = [[float(x), float(y)] for x, y in operation["points"]]
        elif name == "style":
            style = target.setdefault("style", {})
            for field in ("fill", "stroke"):
                if field in operation:
                    style[field] = operation[field]
        elif name == "wrap":
            target["label"] = wrap_label(target.get("label", []), operation["width"])
        applied += 1

    # A moved box can leave the page. Recomputing here means the renderers and the
    # rasterizer all see the same canvas the patch produced.
    extents = [(float(i["x"]) + float(i["width"]), float(i["y"]) + float(i["height"]))
               for i in list(model["nodes"]) + list(model["containers"])]
    if extents:
        model["bounds"] = {"width": round(max(x for x, _ in extents), 2),
                           "height": round(max(y for _, y in extents), 2)}
    model["patched"] = True
    return applied


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="diagram-model.json to patch")
    parser.add_argument("--patch", required=True, help="candidate layout-patch.json")
    parser.add_argument("--out", help="where to write the patched model (default: in place)")
    parser.add_argument("--dry-run", action="store_true",
                        help="check the patch and report, writing nothing")
    args = parser.parse_args()

    model, error = load_json(args.model, "diagram model")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    if model.get("schema_version") not in SUPPORTED_MODEL_SCHEMA:
        sys.stderr.write("FAIL  the model declares schema_version %r; this script "
                         "supports %s\n" % (model.get("schema_version"),
                                            sorted(SUPPORTED_MODEL_SCHEMA)))
        return 2
    patch, error = load_json(args.patch, "layout patch")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2

    problems = check_patch(patch, model)
    if problems:
        for problem in problems:
            sys.stderr.write("  %s\n" % problem)
        sys.stderr.write("FAIL  the patch was refused; the model is unchanged\n")
        return 1

    if args.dry_run:
        print("ok  %d operation(s) would apply" % len(patch["operations"]))
        return 0

    before = json.dumps({k: model[k] for k in ("nodes", "edges", "containers")},
                        sort_keys=True)
    applied = apply_patch(model, patch)

    # A last check on the way out. The allowlist should make this impossible, which is
    # exactly why it is worth asserting rather than assuming.
    for node in model["nodes"]:
        if node["id"] not in before:
            sys.stderr.write("FAIL  applying the patch introduced node %r; refusing to "
                             "write\n" % node["id"])
            return 1

    out = args.out or args.model
    directory = os.path.dirname(os.path.abspath(out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, sort_keys=True)

    print("applied %d operation(s) to %s" % (applied, out))
    print("rerender and revalidate: a patch is not accepted until the structural checks "
          "pass again")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
