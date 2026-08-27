#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/validate_diagrams.py
# Regenerate: python3 tools/materialize.py
"""Validate generated PlantUML views against their class graph and manifest."""

import argparse
import json
import os
import sys

SUPPORTED_MANIFEST_SCHEMA = {3}


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def parse_source(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "cannot read %s: %s" % (path, exc)
    if text.count("@startuml") != 1 or text.count("@enduml") != 1:
        return None, "must contain exactly one @startuml and @enduml"
    if text.index("@startuml") > text.index("@enduml"):
        return None, "@enduml appears before @startuml"
    parsed = {"diagram": None, "nodes": [], "edges": []}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        for marker, key in (("' @diagram ", "diagram"), ("' @node ", "nodes"),
                            ("' @edge ", "edges")):
            if not stripped.startswith(marker):
                continue
            try:
                value = json.loads(stripped[len(marker):])
            except ValueError as exc:
                return None, "line %d has malformed %s metadata: %s" % (number, key, exc)
            if key == "diagram":
                if parsed[key] is not None:
                    return None, "contains duplicate diagram metadata"
                parsed[key] = value
            else:
                parsed[key].append(value)
    if parsed["diagram"] is None:
        return None, "contains no diagram metadata"
    return parsed, None


def classes_in_scope(graph, scope):
    kind = (scope or {}).get("kind", "repository")
    if kind == "repository":
        return {c["id"] for c in graph["classes"]}
    if kind == "package":
        return {c["id"] for c in graph["classes"] if c.get("package") == scope.get("id")}
    if kind == "module":
        return {c["id"] for c in graph["classes"] if c.get("module") == scope.get("id")}
    return None


def add(findings, code, message, view=None):
    findings.append({"code": code, "view": view, "message": message})


def validate_view(entry, parsed, graph, findings):
    view = entry.get("view")
    meta = parsed["diagram"]
    if meta != {key: entry.get(key) for key in
                ("schema_version", "source_graph_hash", "view_spec_hash", "view",
                 "scope", "detail", "layers")}:
        add(findings, "G002", "PlantUML metadata does not match the manifest", view)
    if meta.get("source_graph_hash") != graph.get("source_graph_hash"):
        add(findings, "G002", "view was generated from a different class graph", view)
    node_ids = [node.get("id") for node in parsed["nodes"]]
    if len(node_ids) != len(set(node_ids)):
        add(findings, "G003", "contains duplicate node metadata", view)
    if sorted(node_ids) != sorted(entry.get("nodes", ())):
        add(findings, "G005", "PlantUML nodes do not match the manifest", view)
    graph_ids = {c["id"] for c in graph["classes"]}
    invented = sorted(set(node_ids) - graph_ids)
    if invented:
        add(findings, "G001", "contains classes absent from the graph: %s" %
            ", ".join(invented[:5]), view)
    expected = classes_in_scope(graph, entry.get("scope"))
    if expected is None:
        add(findings, "G001", "declares an unsupported scope", view)
    else:
        missing = sorted(expected - set(node_ids))
        if missing:
            add(findings, "G001", "omits in-scope classes: %s" % ", ".join(missing[:5]), view)
    owners = {c["id"]: c["module"] for c in graph["classes"]}
    for node in parsed["nodes"]:
        if owners.get(node.get("id")) != node.get("module"):
            add(findings, "G003", "class %r is nested under the wrong module" %
                node.get("id"), view)
        if expected is not None:
            should_external = node.get("id") not in expected
            if bool(node.get("external")) != should_external:
                add(findings, "G001", "class %r has the wrong external marker" %
                    node.get("id"), view)
    edge_ids = [edge.get("id") for edge in parsed["edges"]]
    if len(edge_ids) != len(set(edge_ids)):
        add(findings, "G003", "contains duplicate relationship metadata", view)
    if sorted(edge_ids) != sorted(entry.get("edges", ())):
        add(findings, "G005", "PlantUML relationships do not match the manifest", view)
    by_edge = {edge["id"]: edge for edge in graph["edges"]}
    for edge in parsed["edges"]:
        source = by_edge.get(edge.get("id"))
        if source is None:
            add(findings, "G001", "contains a relationship absent from the graph", view)
            continue
        expected_edge = {"id": source["id"], "layer": source["layer"],
                         "from": source["from"], "to": source["to"]}
        if edge != expected_edge:
            add(findings, "G003", "relationship %r changes its type or endpoints" %
                edge.get("id"), view)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--class-graph", required=True)
    args = parser.parse_args()
    if not os.path.isdir(args.directory):
        sys.stderr.write("FAIL  not a directory: %s\n" % args.directory)
        return 2
    graph, error = load_json(args.class_graph, "class graph")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    manifest, error = load_json(os.path.join(args.directory, "diagram-manifest.json"),
                                "diagram manifest")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMA:
        sys.stderr.write("FAIL  unsupported diagram manifest schema_version %r\n" %
                         manifest.get("schema_version"))
        return 2
    findings = []
    files = []
    for entry in manifest.get("views", ()):
        filename = entry.get("file")
        files.append(filename)
        parsed, error = parse_source(os.path.join(args.directory, filename or ""))
        if error:
            add(findings, "G006", error, entry.get("view"))
            continue
        validate_view(entry, parsed, graph, findings)
    if len(files) != len(set(files)):
        add(findings, "G007", "manifest maps multiple views to the same file")
    if not any((view.get("scope") or {}).get("kind") == "repository"
               for view in manifest.get("views", ())):
        add(findings, "G007", "manifest has no repository view")
    report = {"schema_version": 1, "passed": not findings, "findings": findings,
              "views": len(manifest.get("views", ())) }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
