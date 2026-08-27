#!/usr/bin/env python3
"""Behavioural tests for apply_layout_patch.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

This script is the one place where something a model inferred from looking at a picture
is allowed to change a generated artifact. The tests are weighted accordingly: most of
them are attempts to get a structural change through the allowlist, and the one that
matters most is that a refused patch leaves the model untouched rather than half
applied.

    python3 tools/test_layout_patch.py
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "shared", "scripts", "apply_layout_patch.py")
BUILD = os.path.join(REPO, "shared", "scripts", "build_diagrams.py")
VALIDATE = os.path.join(REPO, "shared", "scripts", "validate_diagrams.py")
CONTRACTS = os.path.join(REPO, "tests", "contracts")

MODEL = os.path.join(CONTRACTS, "diagram-model-v1-valid.json")
GRAPH = os.path.join(CONTRACTS, "class-graph-v1-minimal.json")
VALID_PATCH = os.path.join(CONTRACTS, "layout-patch-v1-valid.json")
MUTATION_PATCH = os.path.join(CONTRACTS, "layout-patch-v1-structural-mutation.json")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(model, patch, out=None, *extra):
    args = [sys.executable, SCRIPT, "--model", model, "--patch", patch]
    if out:
        args += ["--out", out]
    proc = subprocess.run(args + list(extra), capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def patch_file(tmp, name, mutate):
    data = load(VALID_PATCH)
    mutate(data)
    path = os.path.join(tmp, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def structure_of(model):
    """Everything a patch must never change."""
    return json.dumps({
        "nodes": sorted((n["id"], n.get("parent")) for n in model["nodes"]),
        "edges": sorted((e["id"], e["source"], e["target"], e["layer"])
                        for e in model["edges"]),
        "containers": sorted(c["id"] for c in model["containers"]),
        "graph": model["source_graph_hash"],
    }, sort_keys=True)


def main():
    tmp = tempfile.mkdtemp(prefix="layout-patch-test-")
    try:
        original = load(MODEL)
        before = structure_of(original)

        # -- the happy path -----------------------------------------------------
        target = os.path.join(tmp, "model.json")
        shutil.copyfile(MODEL, target)
        out = os.path.join(tmp, "patched.json")
        code, output = run(target, VALID_PATCH, out)
        check("a presentation-only patch applies", code == 0, output)
        patched = load(out)
        check("the input model is left alone", structure_of(load(target)) == before)
        check("nothing structural moved", structure_of(patched) == before,
              "a presentation patch changed the graph")

        moved = next(n for n in patched["nodes"] if n["id"] == "class:pkg/models.py:Failure")
        was = next(n for n in original["nodes"] if n["id"] == "class:pkg/models.py:Failure")
        check("a move changes only the coordinate", moved["y"] == was["y"] - 60
              and moved["x"] == was["x"], "%r vs %r" % (moved, was))
        container = next(c for c in patched["containers"] if c["id"] == "module:pkg/models.py")
        check("a resize changes only the size", container["height"] == 200)
        edge = next(e for e in patched["edges"] if e["layer"] == "composition")
        check("a route changes only the waypoints", len(edge["points"]) == 3
              and edge["source"] == "class:pkg/models.py:Order", "%r" % edge)
        wrapped = next(n for n in patched["nodes"] if n["id"] == "class:pkg/models.py:Order")
        check("a wrap reflows the label without losing it",
              len(wrapped["label"]) >= len(was["label"])
              and "Order" in " ".join(wrapped["label"]), "%r" % wrapped["label"])
        check("bounds are recomputed so a moved box stays on the page",
              patched["bounds"]["width"] > 0 and patched["bounds"]["height"] > 0)

        # -- and the result still renders and validates -------------------------
        rendered = os.path.join(tmp, "rendered")
        code, output = subprocess.run(
            [sys.executable, BUILD, "--render-only", out, "--out", rendered],
            capture_output=True, text=True).returncode, ""
        check("the patched model still renders", code == 0, output)
        proc = subprocess.run([sys.executable, VALIDATE, rendered, "--class-graph", GRAPH],
                              capture_output=True, text=True)
        check("and still passes every structural check", proc.returncode == 0,
              proc.stdout + proc.stderr)

        # -- structural mutation, in every spelling -----------------------------
        untouched = os.path.join(tmp, "untouched.json")
        shutil.copyfile(MODEL, untouched)
        code, output = run(untouched, MUTATION_PATCH)
        check("a patch that reparents a class is refused", code == 1, output)
        check("and the model on disk is byte-for-byte unchanged",
              load(untouched) == original, "the refused patch wrote anyway")

        for name, mutate, why in (
            ("add-node",
             lambda p: p["operations"].append(
                 {"op": "move", "target": "class:pkg/models.py:Invented", "dx": 5}),
             "targets a node that is not in the diagram"),
            ("change-layer",
             lambda p: p["operations"].append(
                 {"op": "style", "target": "edge:composition:class:pkg/models.py:Order:"
                                           "class:pkg/base.py:Record",
                  "layer": "inheritance"}),
             "changes a relationship's layer"),
            ("change-endpoint",
             lambda p: p["operations"].append(
                 {"op": "route", "target": "edge:composition:class:pkg/models.py:Order:"
                                           "class:pkg/base.py:Record",
                  "points": [[0, 0]], "to": "class:pkg/models.py:Failure"}),
             "changes an edge endpoint"),
            ("restamp",
             lambda p: p["operations"].append(
                 {"op": "move", "target": "class:pkg/base.py:Record", "dx": 1,
                  "source_graph_hash": "sha256:" + "f" * 64}),
             "restamps the graph hash"),
            ("recite",
             lambda p: p["operations"].append(
                 {"op": "move", "target": "class:pkg/base.py:Record", "dx": 1,
                  "cite": "somewhere/else.py:1"}),
             "rewrites a citation"),
            ("unknown-op",
             lambda p: p["operations"].append(
                 {"op": "delete", "target": "class:pkg/base.py:Record"}),
             "uses an operation that is not on the allowlist"),
            ("zero-size",
             lambda p: p["operations"].append(
                 {"op": "resize", "target": "class:pkg/base.py:Record", "width": 0}),
             "resizes a box to nothing"),
        ):
            fresh = os.path.join(tmp, name + "-model.json")
            shutil.copyfile(MODEL, fresh)
            code, output = run(fresh, patch_file(tmp, name, mutate))
            check("a patch that %s is refused" % why, code == 1, output)
            check("  and %s leaves the model unchanged" % name,
                  load(fresh) == original)

        # -- a patch made for a different diagram --------------------------------
        stale = os.path.join(tmp, "stale-model.json")
        data = copy.deepcopy(original)
        data["source_graph_hash"] = "sha256:" + "1" * 64
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, output = run(stale, VALID_PATCH)
        check("a patch whose recorded graph hash no longer matches is refused",
              code == 1 and "different diagram" in output, output)
        # This is what makes reuse safe: an unchanged repository can replay an accepted
        # patch, and a changed one cannot.
        replay = os.path.join(tmp, "replay.json")
        shutil.copyfile(MODEL, replay)
        code, output = run(replay, VALID_PATCH, None, "--dry-run")
        check("an unchanged diagram can replay an accepted patch", code == 0, output)
        check("and --dry-run writes nothing", load(replay) == original)

        # -- inputs ---------------------------------------------------------------
        code, output = run(os.path.join(tmp, "absent.json"), VALID_PATCH)
        check("a missing model exits 2", code == 2, output)
        code, output = run(MODEL, os.path.join(tmp, "absent-patch.json"))
        check("a missing patch exits 2", code == 2, output)

        empty = os.path.join(tmp, "empty-patch.json")
        with open(empty, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "operations": []}, fh)
        code, output = run(MODEL, empty)
        check("a patch with no operations is refused", code == 1, output)

        # A patch with no identity is not "applies anywhere" -- it is a patch that
        # cannot be checked, and replaying it onto another diagram is exactly what
        # recording the hashes was for.
        for name, drop in (("no-applies-to", lambda p: p.pop("applies_to", None)),
                           ("no-graph-hash",
                            lambda p: p["applies_to"].pop("source_graph_hash")),
                           ("no-view-hash",
                            lambda p: p["applies_to"].pop("view_spec_hash"))):
            fresh = os.path.join(tmp, name + "-model.json")
            shutil.copyfile(MODEL, fresh)
            code, output = run(fresh, patch_file(tmp, name, drop))
            check("a patch with %s is refused" % name.replace("-", " "), code == 1,
                  output)
            check("  and %s changes nothing" % name, load(fresh) == original)

        # A style operation that no renderer reads would report success and do nothing.
        styled = os.path.join(tmp, "styled-model.json")
        shutil.copyfile(MODEL, styled)
        styled_out = os.path.join(tmp, "styled.json")
        code, output = run(styled, patch_file(tmp, "styled", lambda p: p["operations"]
                                              .append({"op": "style",
                                                       "target": "class:pkg/base.py:Record",
                                                       "fill": "#112233"})), styled_out)
        check("a style patch applies", code == 0, output)
        styled_docs = os.path.join(tmp, "styled-docs")
        subprocess.run([sys.executable, BUILD, "--render-only", styled_out,
                        "--out", styled_docs], capture_output=True, text=True)
        svg = open(os.path.join(styled_docs, "full-repository.svg"),
                   encoding="utf-8").read()
        check("and the renderer actually uses the colour it set",
              "#112233" in svg, svg[:200])

        old = os.path.join(tmp, "old-patch.json")
        with open(old, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 99, "operations": []}, fh)
        code, output = run(MODEL, old)
        check("a patch from an unsupported schema is refused", code == 1, output)
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
