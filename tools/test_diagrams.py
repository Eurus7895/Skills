#!/usr/bin/env python3
"""Behavioural tests for build_diagrams.py and validate_diagrams.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Graphviz is not required to run these. Layout needs `dot`; everything after it does
not, and the tests are built around that split: the render path, the equivalence between
Draw.io and SVG, and every validation finding are driven from the checked-in diagram
model in tests/contracts/. Where `dot` is present the layout path is exercised too, and
where it is absent only the policy branches are.

That is not a gap papered over -- it is the reason `--render-only` exists as a real mode
rather than a test hook, and the reason the coverage promise is checked against the
class graph instead of against a picture.

    python3 tools/test_diagrams.py
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
CLASS_GRAPH = os.path.join(REPO, "shared", "scripts", "build_class_graph.py")
BUILD = os.path.join(REPO, "shared", "scripts", "build_diagrams.py")
VALIDATE = os.path.join(REPO, "shared", "scripts", "validate_diagrams.py")
CONTRACTS = os.path.join(REPO, "tests", "contracts")

MODEL = os.path.join(CONTRACTS, "diagram-model-v1-valid.json")
GRAPH = os.path.join(CONTRACTS, "class-graph-v1-minimal.json")

HAVE_DOT = shutil.which("dot") is not None

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


def run(script, *args):
    proc = subprocess.run([sys.executable, script] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def render(model_path, out_dir, *extra):
    return run(BUILD, "--render-only", model_path, "--out", out_dir, *extra)


def validate(out_dir, graph=GRAPH, *extra):
    code, output = run(VALIDATE, out_dir, "--class-graph", graph, "--json", *extra)
    try:
        return code, json.loads(output)
    except ValueError:
        return code, {"_output": output}


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())})


def variant(tmp, name, mutate):
    """Render a one-defect copy of the good model and validate the result."""
    with open(MODEL, encoding="utf-8") as fh:
        model = json.load(fh)
    mutate(model)
    path = os.path.join(tmp, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(model, fh)
    out_dir = os.path.join(tmp, name)
    render(path, out_dir)
    return validate(out_dir)


def main():
    tmp = tempfile.mkdtemp(prefix="diagrams-test-")
    try:
        # -- render, from a model laid out earlier ------------------------------
        good = os.path.join(tmp, "good")
        code, output = render(MODEL, good)
        check("rendering from an existing model succeeds", code == 0, output)
        written = sorted(os.listdir(good))
        check("both formats and the manifest are written",
              written == ["diagram-manifest.json", "diagram-model.json",
                          "full-repository.drawio", "full-repository.svg"],
              "%r" % written)

        code, report = validate(good)
        check("the rendered fixture validates", code == 0 and report["passed"],
              "%r" % report)

        again = os.path.join(tmp, "again")
        render(MODEL, again)
        same = all(open(os.path.join(good, n), encoding="utf-8").read()
                   == open(os.path.join(again, n), encoding="utf-8").read()
                   for n in written)
        check("rendering the same model twice gives the same bytes", same)

        with open(os.path.join(good, "full-repository.drawio"), encoding="utf-8") as fh:
            drawio = fh.read()
        check("the Draw.io file is native mxGraph, not an image wrapper",
              "<mxGraphModel" in drawio and "mxGeometry" in drawio)
        check("class boxes are separate cells a person can drag",
              drawio.count('vertex="1"') >= 3, drawio[:200])
        check("edges carry the ids the model uses",
              "edge:inheritance:class:pkg/models.py:Order" in drawio)

        # -- the two formats must agree ----------------------------------------
        edited = os.path.join(tmp, "edited")
        shutil.copytree(good, edited)
        with open(os.path.join(edited, "full-repository.svg"), encoding="utf-8") as fh:
            svg = fh.read()
        with open(os.path.join(edited, "full-repository.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg.replace('id="class:pkg/models.py:Failure"', 'id="gone"'))
        code, report = validate(edited)
        check("a node removed from one format only is caught",
              code == 1 and "G005" in codes(report), "%r" % report)

        # The other direction: an artifact that grew a node no class graph backs. A
        # gate that only looks for what is missing passes a picture asserting something
        # the source never said.
        fabricated = os.path.join(tmp, "fabricated")
        shutil.copytree(good, fabricated)
        with open(os.path.join(fabricated, "full-repository.svg"), encoding="utf-8") as fh:
            svg = fh.read()
        with open(os.path.join(fabricated, "full-repository.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write(svg.replace("</g></svg>",
                                 '<rect id="class:pkg/models.py:Invented" x="10" y="10" '
                                 'width="20" height="20"/></g></svg>'))
        code, report = validate(fabricated)
        check("a node added to a rendered artifact is caught",
              code == 1 and "G005" in codes(report), "%r" % report)

        broken = os.path.join(tmp, "broken-xml")
        shutil.copytree(good, broken)
        with open(os.path.join(broken, "full-repository.drawio"), "w",
                  encoding="utf-8") as fh:
            fh.write("<mxfile><unclosed>")
        code, report = validate(broken)
        check("malformed XML is caught", code == 1 and "G006" in codes(report),
              "%r" % report)

        # -- coverage is the promise the diagram rests on ----------------------
        code, report = variant(tmp, "missing-class",
                               lambda m: m["nodes"].pop())
        check("a class missing from the diagram is caught",
              code == 1 and "G001" in codes(report), "%r" % report)

        def invent(model):
            node = copy.deepcopy(model["nodes"][0])
            node["id"] = "class:pkg/base.py:Imagined"
            node["x"] = 40.0
            node["y"] = 250.0
            model["nodes"].append(node)
        code, report = variant(tmp, "invented", invent)
        check("a node with no class behind it is caught",
              code == 1 and "G001" in codes(report), "%r" % report)

        code, report = variant(tmp, "lost-edge",
                               lambda m: m["edges"].pop(0))
        check("a verified inheritance edge that is not drawn is caught",
              code == 1 and "G001" in codes(report), "%r" % report)

        # -- identity ----------------------------------------------------------
        def restamp(model):
            model["source_graph_hash"] = "sha256:" + "9" * 64
        code, report = variant(tmp, "wrong-graph", restamp)
        check("a diagram laid out from a different graph is caught",
              code == 1 and "G002" in codes(report), "%r" % report)

        # -- integrity ---------------------------------------------------------
        def duplicate(model):
            model["nodes"].append(copy.deepcopy(model["nodes"][0]))
        code, report = variant(tmp, "duplicate", duplicate)
        check("a duplicate node id is caught",
              code == 1 and "G003" in codes(report), "%r" % report)

        def dangle(model):
            model["edges"][0]["target"] = "class:pkg/base.py:Nowhere"
        code, report = variant(tmp, "dangling", dangle)
        check("an edge to a node that is not there is caught",
              code == 1 and "G003" in codes(report), "%r" % report)

        def misplace(model):
            model["nodes"][0]["parent"] = "module:pkg/models.py"
        code, report = variant(tmp, "misplaced", misplace)
        check("a class drawn under the wrong module is caught",
              code == 1 and "G003" in codes(report), "%r" % report)

        def escape(model):
            for node in model["nodes"]:
                if node["id"] == "class:pkg/base.py:Record":
                    node["x"] = 900.0
        code, report = variant(tmp, "escaped", escape)
        check("a class drawn outside its own container is caught",
              code == 1 and "G003" in codes(report), "%r" % report)

        # -- geometry ----------------------------------------------------------
        def flatten(model):
            model["nodes"][0]["height"] = 0
        code, report = variant(tmp, "zero", flatten)
        check("a zero-height box is caught",
              code == 1 and "G004" in codes(report), "%r" % report)

        def collide(model):
            # Two classes in the same module, placed on top of each other.
            model["nodes"][2]["x"] = model["nodes"][1]["x"]
            model["nodes"][2]["y"] = model["nodes"][1]["y"]
        code, report = variant(tmp, "overlap", collide)
        check("two boxes sharing the same space are caught",
              code == 1 and "G004" in codes(report), "%r" % report)
        # Nesting is what a container is for, so it must not be reported as an overlap.
        code, report = validate(good)
        check("a class nested in its module is not reported as an overlap",
              report["passed"], "%r" % report)

        # -- view specification is presentation only ---------------------------
        spec_dir = os.path.join(tmp, "spec")
        os.makedirs(spec_dir)
        valid_spec = os.path.join(CONTRACTS, "view-spec-v1-valid.json")
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec", valid_spec,
                           "--out", spec_dir, "--policy", "disabled")
        check("a presentation-only view spec is accepted", code == 0, output)

        mutation = os.path.join(CONTRACTS, "view-spec-v1-structural-mutation.json")
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec", mutation,
                           "--out", spec_dir, "--policy", "disabled")
        check("a view spec that changes structure is refused", code == 2, output)
        check("and the refusal says why", "presentation" in output, output)

        bad_layer = os.path.join(tmp, "bad-layer.json")
        with open(bad_layer, "w", encoding="utf-8") as fh:
            json.dump({"layers": ["telepathy"]}, fh)
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec", bad_layer,
                           "--out", spec_dir, "--policy", "disabled")
        check("an unknown layer is refused", code == 2, output)

        # -- Graphviz policy ----------------------------------------------------
        policy_dir = os.path.join(tmp, "policy")
        code, output = run(BUILD, "--class-graph", GRAPH, "--out", policy_dir,
                           "--policy", "disabled")
        check("--policy disabled attempts nothing", code == 0 and "disabled" in output,
              output)
        check("and writes nothing", not os.path.isdir(policy_dir)
              or not os.listdir(policy_dir), "%r" % policy_dir)

        if HAVE_DOT:
            laid_out = os.path.join(tmp, "laid-out")
            code, output = run(BUILD, "--class-graph", GRAPH, "--out", laid_out,
                               "--policy", "required")
            check("layout runs where Graphviz is installed", code == 0, output)
            code, report = validate(laid_out)
            check("a freshly laid-out diagram validates", code == 0, "%r" % report)
            with open(os.path.join(laid_out, "diagram-model.json"),
                      encoding="utf-8") as fh:
                model = json.load(fh)
            check("the layout engine and version are recorded",
                  model["layout_engine"]["name"] == "graphviz"
                  and model["layout_engine"]["version"],
                  "%r" % model["layout_engine"])
            check("coordinates are not all identical",
                  len({(n["x"], n["y"]) for n in model["nodes"]}) > 1,
                  "%r" % [(n["x"], n["y"]) for n in model["nodes"]])
        else:
            print("skip layout checks -- Graphviz is not installed")
            code, output = run(BUILD, "--class-graph", GRAPH, "--out",
                               os.path.join(tmp, "opt"), "--policy", "optional")
            check("missing Graphviz under optional skips and says so",
                  code == 0 and "skipped" in output, output)
            code, output = run(BUILD, "--class-graph", GRAPH, "--out",
                               os.path.join(tmp, "req"), "--policy", "required")
            check("missing Graphviz under required fails", code == 2, output)

        # -- inputs -------------------------------------------------------------
        code, output = render(os.path.join(tmp, "absent.json"), os.path.join(tmp, "no"))
        check("a missing model exits 2", code == 2, output)

        stale = os.path.join(tmp, "stale.json")
        with open(MODEL, encoding="utf-8") as fh:
            model = json.load(fh)
        model["schema_version"] = 99
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump(model, fh)
        code, output = render(stale, os.path.join(tmp, "no2"))
        check("an unsupported model schema_version exits 2", code == 2, output)

        code, report = validate(os.path.join(tmp, "not-a-directory"))
        check("validating a directory that is not there exits 2",
              code == 2, "%r" % report)
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
