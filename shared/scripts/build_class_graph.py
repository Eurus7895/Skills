#!/usr/bin/env python3
"""Build the canonical class graph. No geometry, no renderer, no opinions about layout.

    python3 scripts/build_class_graph.py --index structure.json \\
        --claims .docs-build/claims.verified.jsonl --detail public \\
        --out .docs-build/class-graph.json

`class-graph.json` is the single source every diagram is drawn from. Draw.io and SVG are
render products of it; if they disagree with this file, they are wrong. Nothing here
depends on Graphviz being installed, so the graph exists and can be checked even where
no diagram can be drawn.

Relationships live in named layers, because they are not equally well known:

    inheritance   a base class resolved to the file defining it. Deterministic
    composition   an attribute whose written type resolves to a class here.
                  Deterministic, and only as good as the annotation
    association   the defining modules import one another. Weaker: a reference
                  between files, not between the classes in them
    calls         from a `calls` claim verified at its call site. Never inferred
    inference     anything the model asserted that no pass could confirm

A class with no annotations produces no composition edges, and that absence is reported
rather than filled in from parameter names or attribute spelling.

Detail levels: `summary` (name only), `public` (public methods and typed attributes),
`full` (everything extracted). Bounded on purpose -- `full` on a large repository
produces a diagram nobody can read, and the level chosen is recorded in the output.

Exit codes: 0 written, 1 the graph is not valid, 2 input/schema error, 3 internal error.

Standard library only. Reads its inputs; writes only --out.
"""

import argparse
import hashlib
import json
import os
import sys

SCHEMA_VERSION = 1
SUPPORTED_INDEX_SCHEMA = {2}

DETAIL_LEVELS = ("summary", "public", "full")

LAYERS = ("inheritance", "composition", "association", "calls", "inference")


def load_index(path):
    if not os.path.isfile(path):
        return None, "no such index: %s" % path
    try:
        with open(path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)
    if not isinstance(index, dict):
        return None, "%s does not contain a JSON object" % path
    if index.get("schema_version") not in SUPPORTED_INDEX_SCHEMA:
        return None, ("%s declares schema_version %r; this script supports %s"
                      % (path, index.get("schema_version"), sorted(SUPPORTED_INDEX_SCHEMA)))
    return index, None


def load_claims(path):
    if path is None:
        return [], None
    if not os.path.isfile(path):
        return None, "no such claims file: %s" % path
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    return None, "%s line %d: %s" % (path, number, exc)
    except OSError as exc:
        return None, "cannot read %s: %s" % (path, exc)
    return rows, None


def package_of(path):
    """The directory a module lives in, as the package container id."""
    return os.path.dirname(path) or "."


def stereotype_of(cls):
    """A one-word label, only where the code states it plainly.

    Anything less obvious than "it inherits from Exception" or "it is decorated as a
    dataclass" is left as a plain class -- a stereotype guessed from a name is a
    presentation choice dressed up as a fact.
    """
    bases = {b["name"].split(".")[-1] for b in cls.get("bases", ())}
    decorators = {d.split(".")[-1] for d in cls.get("decorators", ())}
    if bases & {"Exception", "BaseException"} or cls["name"].endswith("Error"):
        return "exception"
    if "dataclass" in decorators:
        return "dataclass"
    if bases & {"ABC", "Protocol"} or "abstractmethod" in decorators:
        return "abstract"
    if bases & {"Enum", "IntEnum", "StrEnum"}:
        return "enum"
    return "class"


def members_of(cls, detail):
    """Members at the requested level. `summary` shows the name and nothing else."""
    if detail == "summary":
        return {"methods": [], "attributes": []}

    methods, attributes = [], []
    for method in cls.get("methods", ()):
        if detail == "public" and method.get("visibility") != "public":
            continue
        methods.append({"name": method["name"], "line": method["line"],
                        "params": method.get("params", []),
                        "visibility": method.get("visibility")})
    for attribute in cls.get("attributes", ()):
        typed = attribute.get("types") or []
        if detail == "public" and not typed and attribute["name"].startswith("_"):
            continue
        attributes.append({"name": attribute["name"], "line": attribute["line"],
                           "types": [t["name"] for t in typed]})
    return {"methods": methods, "attributes": attributes}


def collect_nodes(index, detail):
    """Every class the scanner extracted, exactly once, owned by module and package."""
    packages, modules, classes = {}, {}, []
    for record in sorted(index.get("files", ()), key=lambda r: r["path"]):
        if "classes" not in record:
            continue
        path = record["path"]
        package = package_of(path)
        packages.setdefault("package:%s" % package,
                            {"id": "package:%s" % package, "name": package,
                             "modules": []})
        module_id = "module:%s" % path
        modules[module_id] = {"id": module_id, "name": path, "package": "package:%s" % package,
                              "lang": record.get("lang"),
                              "source_hash": record.get("source_hash"), "classes": []}
        packages["package:%s" % package]["modules"].append(module_id)

        for cls in sorted(record["classes"], key=lambda c: (c["line"], c["name"])):
            class_id = "class:%s:%s" % (path, cls["name"])
            modules[module_id]["classes"].append(class_id)
            classes.append({
                "id": class_id,
                "name": cls["name"],
                "module": module_id,
                "package": "package:%s" % package,
                "stereotype": stereotype_of(cls),
                "cite": "%s:%d" % (path, cls["line"]),
                "source_hash": record.get("source_hash"),
                "members": members_of(cls, detail),
            })
    return packages, modules, classes


def collect_edges(index, classes, modules, claims):
    """Relationships, each in the layer that says how well it is known."""
    known_modules = set(modules)
    names_by_path = {}
    for cls in classes:
        path = cls["module"].split(":", 1)[1]
        names_by_path.setdefault(path, {})[cls["name"]] = cls["id"]

    edges, unresolved = [], []

    for record in index.get("files", ()):
        path = record["path"]
        for cls in record.get("classes", ()):
            source = names_by_path.get(path, {}).get(cls["name"])
            if source is None:
                continue

            for base in cls.get("bases", ()):
                leaf = base["name"].split(".")[-1]
                target = (names_by_path.get(base["resolved"], {}).get(leaf)
                          if base.get("resolved") else None)
                if target is None:
                    # Recorded, not drawn: the class really does name a base, and the
                    # diagram must not imply it has none.
                    unresolved.append({"kind": "inheritance", "from": source,
                                       "base_name": base["name"],
                                       "reason": "base did not resolve to a class in "
                                                 "this repository"})
                    continue
                edges.append({"id": "edge:inheritance:%s:%s" % (source, target),
                              "layer": "inheritance", "from": source, "to": target,
                              "verified": True, "cite": "%s:%d" % (path, cls["line"])})

            # Two attributes of the same type are one relationship carrying two names,
            # not two relationships. Drawn separately they are parallel lines a reader
            # has to compare; merged, the labels say what is held.
            for attribute in cls.get("attributes", ()):
                for typed in attribute.get("types", ()):
                    target = names_by_path.get(typed["resolved"], {}).get(typed["name"])
                    if target is None or target == source:
                        continue
                    edge_id = "edge:composition:%s:%s" % (source, target)
                    existing = next((e for e in edges if e["id"] == edge_id), None)
                    if existing is None:
                        edges.append({
                            "id": edge_id, "layer": "composition", "from": source,
                            "to": target, "verified": True,
                            "labels": [attribute["name"]],
                            "cites": ["%s:%d" % (path, attribute["line"])]})
                    elif attribute["name"] not in existing["labels"]:
                        existing["labels"].append(attribute["name"])
                        existing["cites"].append("%s:%d" % (path, attribute["line"]))

    # Association is a fact about modules, so it is recorded between modules. Lifting it
    # to every pair of classes the two files define would state something nobody
    # established -- and on a repository of any size it is a cross product.
    for edge in index.get("edges", ()):
        source_id, target_id = "module:%s" % edge["from"], "module:%s" % edge["to"]
        if source_id not in known_modules or target_id not in known_modules:
            continue
        edges.append({
            "id": "edge:association:%s:%s" % (source_id, target_id),
            "layer": "association", "from": source_id, "to": target_id,
            "verified": True, "approximate": True,
            "cite": "%s:%d" % (edge["from"], edge["line"]),
            "note": "these modules import each other; it says nothing about which "
                    "classes in them are related"})

    for claim in claims:
        if claim.get("kind") != "calls" or claim.get("status") != "verified":
            continue
        evidence = (claim.get("evidence") or [{}])[0]
        edges.append({"id": "edge:calls:%s" % claim["id"], "layer": "calls",
                      "from": claim.get("subject"), "to": claim.get("object"),
                      "verified": True, "claim_id": claim["id"],
                      "cite": "%s:%s" % (evidence.get("path"),
                                         evidence.get("line_start"))})

    # Duplicate ids would make two edges indistinguishable downstream; the association
    # layer can genuinely produce the same pair twice from two import lines.
    seen, deduped = set(), []
    for edge in edges:
        if edge["id"] in seen:
            continue
        seen.add(edge["id"])
        deduped.append(edge)
    return sorted(deduped, key=lambda e: e["id"]), unresolved


def graph_hash(payload):
    """A hash of the structure only, so geometry can be pinned to it."""
    material = json.dumps({k: payload[k] for k in ("packages", "modules", "classes",
                                                   "edges")}, sort_keys=True)
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def build(index, claims, detail):
    packages, modules, classes = collect_nodes(index, detail)
    edges, unresolved = collect_edges(index, classes, modules, claims)

    graph = {
        "schema_version": SCHEMA_VERSION,
        "detail": detail,
        "source": index.get("source", {}),
        "packages": [packages[k] for k in sorted(packages)],
        "modules": [modules[k] for k in sorted(modules)],
        "classes": classes,
        "edges": edges,
        "unresolved": unresolved,
        "layers": list(LAYERS),
        "coverage": {
            "classes": len(classes),
            "modules_with_detail": len(modules),
            "modules_without_detail": sum(
                1 for r in index.get("files", ()) if "classes" not in r),
            "by_layer": {layer: sum(1 for e in edges if e["layer"] == layer)
                         for layer in LAYERS},
            "unresolved_relationships": len(unresolved),
        },
    }
    graph["source_graph_hash"] = graph_hash(graph)
    return graph


def validate(graph, index):
    problems = []
    class_ids = set()
    for cls in graph["classes"]:
        if cls["id"] in class_ids:
            problems.append("duplicate class id %r" % cls["id"])
        class_ids.add(cls["id"])
        if not cls.get("module") or not cls.get("package"):
            problems.append("class %r has no module or package owner" % cls["id"])
        if not cls.get("source_hash"):
            problems.append("class %r carries no source hash" % cls["id"])

    module_ids = {m["id"] for m in graph["modules"]}
    package_ids = {p["id"] for p in graph["packages"]}
    for cls in graph["classes"]:
        if cls["module"] not in module_ids:
            problems.append("class %r names module %r, which is not in the graph"
                            % (cls["id"], cls["module"]))
        if cls["package"] not in package_ids:
            problems.append("class %r names package %r, which is not in the graph"
                            % (cls["id"], cls["package"]))

    edge_ids = set()
    for edge in graph["edges"]:
        if edge["id"] in edge_ids:
            problems.append("duplicate edge id %r" % edge["id"])
        edge_ids.add(edge["id"])
        if edge["layer"] not in LAYERS:
            problems.append("edge %r is in unknown layer %r" % (edge["id"], edge["layer"]))
        # Each layer connects the kind of thing it is a fact about: inheritance and
        # composition join classes, association joins modules, and a call claim names
        # modules and symbols. Checking them all against the class set would either
        # reject correct edges or force association into a shape it does not have.
        if edge["layer"] in ("inheritance", "composition"):
            for end in ("from", "to"):
                if edge[end] not in class_ids:
                    problems.append("edge %r end %r is not a class in this graph"
                                    % (edge["id"], edge[end]))
        elif edge["layer"] == "association":
            for end in ("from", "to"):
                if edge[end] not in module_ids:
                    problems.append("edge %r end %r is not a module in this graph"
                                    % (edge["id"], edge[end]))

    # Every class the scanner found must be here. This is the coverage promise the
    # diagram rests on, and it is cheaper to check against the index than against a
    # rendered picture.
    expected = {"class:%s:%s" % (r["path"], c["name"])
                for r in index.get("files", ()) for c in r.get("classes", ())}
    missing = sorted(expected - class_ids)
    if missing:
        problems.append("%d class(es) in the index are absent from the graph: %s"
                        % (len(missing), ", ".join(missing[:5])))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", default="structure.json", help="path to structure.json")
    parser.add_argument("--claims", help="verified claims, JSONL; adds the calls layer")
    parser.add_argument("--detail", default="public", choices=DETAIL_LEVELS)
    parser.add_argument("--out", default=".docs-build/class-graph.json")
    args = parser.parse_args()

    index, error = load_index(args.index)
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    claims, error = load_claims(args.claims)
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2

    if not any("classes" in r for r in index.get("files", ())):
        sys.stderr.write("FAIL  the index carries no class detail; rerun scan_repo.py "
                         "with --detail\n")
        return 2

    graph = build(index, claims, args.detail)
    problems = validate(graph, index)
    if problems:
        for problem in problems:
            sys.stderr.write("  %s\n" % problem)
        sys.stderr.write("FAIL  %d problem(s); nothing written\n" % len(problems))
        return 1

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2, sort_keys=True)

    counts = graph["coverage"]["by_layer"]
    print("wrote %s: %d class(es) in %d module(s), %d package(s)"
          % (args.out, len(graph["classes"]), len(graph["modules"]),
             len(graph["packages"])))
    print("edges: " + ", ".join("%d %s" % (counts[l], l) for l in LAYERS if counts[l]))
    if graph["unresolved"]:
        print("%d relationship(s) named but not resolved; they are recorded, not drawn"
              % len(graph["unresolved"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
