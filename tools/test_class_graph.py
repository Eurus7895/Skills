#!/usr/bin/env python3
"""Behavioural tests for build_class_graph.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The coverage promise is what a diagram rests on: every class the scanner found appears
exactly once, and every relationship sits in the layer that says how well it is known.
The cases worth the most here are the ones where the honest answer is a smaller graph --
a base that did not resolve, an attribute with no annotation, an import between modules
that says nothing about the classes inside them.

    python3 tools/test_class_graph.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
SCRIPT = os.path.join(REPO, "shared", "scripts", "build_class_graph.py")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


BASE = """\
class Record:
    pass


class Engine:
    pass
"""

MODELS = """\
from typing import Optional

from base import Record, Engine


class Order(Record):
    engine: Engine
    spare: Engine
    label: Optional[str] = None
    _hidden = 1

    def total(self):
        return 0

    def _internal(self):
        return 1


class Failure(Exception):
    pass


class ParseError:
    pass
"""

PLAIN = "def helper():\n    return 1\n"


def build_fixture(tmp, detail="public"):
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "base.py", BASE)
    write(root, "models.py", MODELS)
    write(root, "plain.py", PLAIN)

    index = os.path.join(tmp, "structure.json")
    proc = subprocess.run([sys.executable, SCANNER, "--root", root, "--out", index,
                           "--detail"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    return root, index


def run(index, out, *args):
    proc = subprocess.run([sys.executable, SCRIPT, "--index", index, "--out", out]
                          + list(args), capture_output=True, text=True)
    graph = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fh:
            graph = json.load(fh)
    return proc.returncode, graph, proc.stdout + proc.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="class-graph-test-")
    try:
        root, index = build_fixture(tmp)
        out = os.path.join(tmp, "class-graph.json")
        code, graph, output = run(index, out)
        check("the graph builds", code == 0, output)
        if code != 0:
            return 1

        ids = [c["id"] for c in graph["classes"]]
        check("every class appears exactly once",
              sorted(ids) == ["class:base.py:Engine", "class:base.py:Record",
                              "class:models.py:Failure", "class:models.py:Order",
                              "class:models.py:ParseError"],
              "%r" % ids)
        check("a module with no classes contributes none",
              not any("plain.py" in i for i in ids), "%r" % ids)
        check("every class is owned by a module and a package",
              all(c["module"] in {m["id"] for m in graph["modules"]}
                  and c["package"] in {p["id"] for p in graph["packages"]}
                  for c in graph["classes"]))
        check("every class carries the hash of the file it came from",
              all(c["source_hash"].startswith("sha256:") for c in graph["classes"]))

        by_layer = {}
        for edge in graph["edges"]:
            by_layer.setdefault(edge["layer"], []).append(edge)

        inheritance = [(e["from"], e["to"]) for e in by_layer.get("inheritance", ())]
        check("a base resolved inside the repository becomes an inheritance edge",
              ("class:models.py:Order", "class:base.py:Record") in inheritance,
              "%r" % inheritance)
        check("a base from outside becomes no edge at all",
              not any("Failure" in f for f, _ in inheritance), "%r" % inheritance)
        check("but the unresolved base is recorded rather than forgotten",
              any(u["from"] == "class:models.py:Failure" for u in graph["unresolved"]),
              "%r" % graph["unresolved"])

        composition = {(e["from"], e["to"]): e for e in by_layer.get("composition", ())}
        key = ("class:models.py:Order", "class:base.py:Engine")
        check("a typed attribute becomes a composition edge", key in composition,
              "%r" % sorted(composition))
        check("two attributes of one type are one edge carrying both names",
              key in composition
              and sorted(composition[key]["labels"]) == ["engine", "spare"],
              "%r" % (composition.get(key) or {}).get("labels"))
        check("an attribute whose type is not defined here makes no edge",
              not any("str" in str(e) for e in by_layer.get("composition", ())))

        association = [(e["from"], e["to"]) for e in by_layer.get("association", ())]
        # The import is between files. Saying it relates Order to Record would be
        # asserting something nobody established, and on a real repository it is a
        # cross product of every class in one file with every class in the other.
        check("an import becomes a module-to-module association, not a class one",
              association == [("module:models.py", "module:base.py")], "%r" % association)
        check("association edges are marked approximate",
              all(e.get("approximate") for e in by_layer.get("association", ())))

        order = next(c for c in graph["classes"] if c["name"] == "Order")
        check("public detail keeps public methods",
              [m["name"] for m in order["members"]["methods"]] == ["total"],
              "%r" % order["members"]["methods"])
        stereotypes = {c["name"]: c["stereotype"] for c in graph["classes"]}
        check("stereotypes are only assigned where the code states them",
              stereotypes.get("Order") == "class"
              and stereotypes.get("Failure") == "exception", "%r" % stereotypes)
        # A name is not a base class. `ParseError` inherits from nothing, and calling it
        # an exception is the one guess a reader would take on trust.
        check("a name ending in Error is not an exception on that basis alone",
              stereotypes.get("ParseError") == "class", "%r" % stereotypes)

        summary_out = os.path.join(tmp, "summary.json")
        code, summary, output = run(index, summary_out, "--detail", "summary")
        check("summary detail carries no members", code == 0 and all(
            not c["members"]["methods"] and not c["members"]["attributes"]
            for c in summary["classes"]), output)
        full_out = os.path.join(tmp, "full.json")
        code, full, output = run(index, full_out, "--detail", "full")
        full_order = next(c for c in full["classes"] if c["name"] == "Order")
        check("full detail keeps the private method public detail dropped",
              "_internal" in [m["name"] for m in full_order["members"]["methods"]],
              "%r" % full_order["members"]["methods"])
        check("the detail level is recorded in the output",
              graph["detail"] == "public" and summary["detail"] == "summary")

        # Geometry is pinned to this hash, so it has to move when the structure does
        # and stay put when only the rendering would.
        again = os.path.join(tmp, "again.json")
        run(index, again)
        with open(again, encoding="utf-8") as fh:
            repeat = json.load(fh)
        check("the same index produces the same graph, byte for byte",
              json.dumps(repeat, sort_keys=True) == json.dumps(graph, sort_keys=True))
        check("the structure hash differs between detail levels only if structure does",
              summary["source_graph_hash"] != graph["source_graph_hash"],
              "members are part of the graph, so the hash must move with them")

        # Calls arrive from verified claims, never from the graph's own inference.
        claims = os.path.join(tmp, "claims.jsonl")
        with open(claims, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "claim:c1", "kind": "calls", "subject": "module:models.py",
                "object": "symbol:base.py:Record", "status": "verified",
                "evidence": [{"path": "models.py", "line_start": 6}]}) + "\n")
            fh.write(json.dumps({
                "id": "claim:c2", "kind": "calls", "subject": "module:models.py",
                "object": "symbol:base.py:Engine", "status": "candidate",
                "evidence": [{"path": "models.py", "line_start": 7}]}) + "\n")
        with_calls = os.path.join(tmp, "calls.json")
        code, graph2, output = run(index, with_calls, "--claims", claims)
        call_edges = [e for e in graph2["edges"] if e["layer"] == "calls"]
        check("a verified call claim becomes a call edge",
              [e["claim_id"] for e in call_edges] == ["claim:c1"], "%r" % call_edges)
        check("a candidate call claim does not", code == 0 and len(call_edges) == 1,
              output)

        # Inputs the script cannot vouch for.
        no_detail = os.path.join(tmp, "nodetail.json")
        subprocess.run([sys.executable, SCANNER, "--root", root, "--out", no_detail],
                       capture_output=True, text=True)
        code, _, output = run(no_detail, os.path.join(tmp, "x.json"))
        check("an index with no class detail exits 2 and says to rescan",
              code == 2 and "--detail" in output, output)

        stale = os.path.join(tmp, "v1.json")
        with open(index, encoding="utf-8") as fh:
            data = json.load(fh)
        data["schema_version"] = 1
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, _, output = run(stale, os.path.join(tmp, "y.json"))
        check("an unsupported schema_version exits 2", code == 2, output)

        code, _, output = run(os.path.join(tmp, "absent.json"),
                              os.path.join(tmp, "z.json"))
        check("a missing index exits 2", code == 2, output)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
