#!/usr/bin/env python3
"""Generate deterministic PlantUML class diagrams from a verified class graph.

`class-graph.json` is structural truth and `.puml` is the reviewable Diagram as Code
artifact. Rendering is deliberately left to Sphinx and PlantUML.
"""

import argparse
import hashlib
import json
import os
import re
import sys

SUPPORTED_GRAPH_SCHEMA = {1}
MANIFEST_SCHEMA = 3
DEFAULT_LAYERS = ("inheritance", "composition")
ALL_LAYERS = ("inheritance", "composition", "association", "calls", "inference")
DENSITY_CLASSES = 60
DENSITY_MEMBERS = 400


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


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def quote(value):
    value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % value.replace("\r", " ").replace("\n", "\\n")


def alias(identifier):
    readable = re.sub(r"[^A-Za-z0-9_]", "_", str(identifier)).strip("_")[-48:]
    suffix = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:10]
    return "n_%s_%s" % (readable or "item", suffix)


def slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(value)).strip("-").lower() or "unnamed"


def view_stem(view):
    return str(view).replace("_", "-")


def is_dense(graph):
    members = sum(len(c.get("members", {}).get("methods", ()))
                  + len(c.get("members", {}).get("attributes", ()))
                  for c in graph["classes"])
    return len(graph["classes"]) > DENSITY_CLASSES or members > DENSITY_MEMBERS


def check_spec(spec, graph):
    allowed = {"view", "detail", "layers", "emphasis", "rankdir", "scope"}
    problems = ["unknown view-spec field %r" % key for key in sorted(set(spec) - allowed)]
    problems.extend("unknown relationship layer %r" % layer
                    for layer in spec.get("layers", DEFAULT_LAYERS)
                    if layer not in ALL_LAYERS)
    if spec.get("rankdir", "TB") not in ("TB", "LR"):
        problems.append("rankdir must be 'TB' or 'LR'")
    known = ({c["id"] for c in graph["classes"]} | {m["id"] for m in graph["modules"]}
             | {p["id"] for p in graph["packages"]})
    problems.extend("emphasis names unknown graph id %r" % item
                    for item in spec.get("emphasis", ()) if item not in known)
    return problems


def scope_graph(graph, kind, identifier):
    own = [c for c in graph["classes"] if c.get(kind) == identifier]
    own_ids = {c["id"] for c in own}
    if not own_ids:
        return None
    by_id = {c["id"]: c for c in graph["classes"]}
    edges, outside = [], set()
    for edge in graph["edges"]:
        ends = (edge["from"], edge["to"])
        if not any(end in own_ids for end in ends) or not all(end in by_id for end in ends):
            continue
        edges.append(edge)
        outside.update(end for end in ends if end not in own_ids)
    classes = list(own)
    for class_id in sorted(outside):
        neighbour = dict(by_id[class_id], external=True,
                         members={"methods": [], "attributes": []})
        classes.append(neighbour)
    drawn = {c["id"] for c in classes}
    modules = [dict(m, classes=[c for c in m["classes"] if c in drawn])
               for m in graph["modules"]]
    modules = [m for m in modules if m["classes"]]
    module_ids = {m["id"] for m in modules}
    packages = [dict(p, modules=[m for m in p["modules"] if m in module_ids])
                for p in graph["packages"]]
    return dict(graph, classes=classes, modules=modules,
                packages=[p for p in packages if p["modules"]], edges=edges)


def plan_views(graph, spec, detail_views):
    views = [(graph, dict(spec, view="full_repository", scope={"kind": "repository"}))]
    if not detail_views and not is_dense(graph):
        return views
    scopes = []
    for package in graph["packages"]:
        sliced = scope_graph(graph, "package", package["id"])
        if sliced is None:
            continue
        if is_dense(sliced):
            scopes.extend(("module", module_id) for module_id in package["modules"]
                          if scope_graph(graph, "module", module_id))
        else:
            scopes.append(("package", package["id"]))
    used = {}
    for kind, identifier in scopes:
        base = "%s_%s" % (kind, slug(identifier.split(":", 1)[-1]))
        used[base] = used.get(base, 0) + 1
        suffix = "" if used[base] == 1 else "_" + hashlib.sha256(
            identifier.encode("utf-8")).hexdigest()[:8]
        view = base + suffix
        views.append((scope_graph(graph, kind, identifier),
                      dict(spec, view=view, scope={"kind": kind, "id": identifier})))
    return views


def members_of(cls, detail):
    if detail == "summary":
        return []
    result = []
    members = cls.get("members") or {}
    for item in sorted(members.get("attributes", ()), key=lambda x: x["name"]):
        types = " | ".join(item.get("types") or ())
        result.append("+%s%s" % (item["name"], ": " + types if types else ""))
    for item in sorted(members.get("methods", ()), key=lambda x: x["name"]):
        result.append("+%s(%s)" % (item["name"], ", ".join(item.get("params") or ())))
    return result


def render(graph, spec):
    detail = spec.get("detail") or ("summary" if is_dense(graph) else graph["detail"])
    layers = set(spec.get("layers", DEFAULT_LAYERS))
    meta = {"schema_version": 1, "source_graph_hash": graph["source_graph_hash"],
            "view_spec_hash": digest(spec), "view": spec["view"], "scope": spec["scope"],
            "detail": detail, "layers": sorted(layers)}
    lines = ["@startuml", "' Generated from class-graph.json; do not edit by hand.",
             "hide empty members", "skinparam classAttributeIconSize 0",
             "left to right direction" if spec.get("rankdir") == "LR"
             else "top to bottom direction",
             "' @diagram %s" % json.dumps(meta, sort_keys=True, separators=(",", ":"))]
    classes = {c["id"]: c for c in graph["classes"]}
    modules = {m["id"]: m for m in graph["modules"]}
    for package in sorted(graph["packages"], key=lambda x: x["id"]):
        lines.append("package %s as %s {" % (quote(package["name"]), alias(package["id"])))
        for module_id in sorted(package["modules"]):
            module = modules[module_id]
            lines.append("  package %s as %s {" %
                         (quote(module["name"].rsplit("/", 1)[-1]), alias(module_id)))
            for class_id in sorted(module["classes"]):
                cls = classes[class_id]
                keyword = "enum" if cls.get("stereotype") == "enum" else (
                    "abstract class" if cls.get("stereotype") == "abstract" else "class")
                stereotypes = []
                if cls.get("stereotype") not in (None, "class", "enum", "abstract"):
                    stereotypes.append(cls["stereotype"])
                if cls.get("external"):
                    stereotypes.append("external")
                suffix = " " + " ".join("<<%s>>" % s for s in stereotypes) if stereotypes else ""
                head = "    %s %s as %s%s" % (keyword, quote(cls["name"]), alias(class_id), suffix)
                class_members = members_of(cls, detail)
                lines.append(head + (" {" if class_members else ""))
                lines.extend("      %s" % value for value in class_members)
                if class_members:
                    lines.append("    }")
                lines.append("    ' @node %s" % json.dumps(
                    {"id": class_id, "module": cls["module"],
                     "external": bool(cls.get("external"))},
                    sort_keys=True, separators=(",", ":")))
            lines.append("  }")
        lines.append("}")
    if not graph["classes"]:
        lines.append('note "No classes detected" as empty_state')
    operators = {"inheritance": "--|>", "composition": "*-->",
                 "association": "-->", "calls": "..>", "inference": "..>"}
    drawn = set(classes)
    edge_ids = []
    for edge in sorted(graph["edges"], key=lambda x: x["id"]):
        if edge["layer"] not in layers or edge["from"] not in drawn or edge["to"] not in drawn:
            continue
        label = ", ".join(edge.get("labels") or
                          ([edge["label"]] if edge.get("label") else []))
        lines.append("%s %s %s%s" % (alias(edge["from"]), operators[edge["layer"]],
                                     alias(edge["to"]), " : " + quote(label) if label else ""))
        lines.append("' @edge %s" % json.dumps(
            {"id": edge["id"], "layer": edge["layer"], "from": edge["from"],
             "to": edge["to"]}, sort_keys=True, separators=(",", ":")))
        edge_ids.append(edge["id"])
    lines.extend(["legend right", "  |= Relation |= Notation |",
                  "  | Inheritance | --|> |", "  | Composition | *--> |",
                  "  | Association | --> |", "  | Calls / inference | ..> |",
                  "endlegend", "@enduml", ""])
    return "\n".join(lines), meta, edge_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--class-graph", required=True)
    parser.add_argument("--view-spec")
    parser.add_argument("--out", default="docs/_diagrams")
    parser.add_argument("--detail-views", action="store_true")
    args = parser.parse_args()
    graph, error = load_json(args.class_graph, "class graph")
    if error:
        return fail(error)
    if graph.get("schema_version") not in SUPPORTED_GRAPH_SCHEMA:
        return fail("unsupported class-graph schema_version %r" % graph.get("schema_version"))
    spec = {"view": "full_repository", "layers": list(DEFAULT_LAYERS),
            "emphasis": [], "rankdir": "TB"}
    if args.view_spec:
        supplied, error = load_json(args.view_spec, "view specification")
        if error:
            return fail(error)
        spec.update(supplied)
    problems = check_spec(spec, graph)
    if problems:
        for problem in problems:
            sys.stderr.write("  %s\n" % problem)
        return fail("the view specification is not presentation-only", 1)
    os.makedirs(args.out, exist_ok=True)
    entries = []
    for view_graph, view_spec in plan_views(graph, spec, args.detail_views):
        source, meta, edges = render(view_graph, view_spec)
        filename = "%s.puml" % view_stem(view_spec["view"])
        with open(os.path.join(args.out, filename), "w", encoding="utf-8") as fh:
            fh.write(source)
        entries.append(dict(meta, file=filename,
                            nodes=sorted(c["id"] for c in view_graph["classes"]),
                            edges=sorted(edges)))
        print("%s: %d class(es), %d relationship(s)" %
              (view_spec["view"], len(entries[-1]["nodes"]), len(edges)))
    with open(os.path.join(args.out, "diagram-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema_version": MANIFEST_SCHEMA, "views": entries}, fh,
                  indent=2, sort_keys=True)
    print("wrote %d PlantUML view(s) to %s" % (len(entries), args.out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
