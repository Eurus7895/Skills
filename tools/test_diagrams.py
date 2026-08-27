#!/usr/bin/env python3
"""Behavioural tests for build_diagrams.py and validate_diagrams.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Graphviz is not required to run these. Layout needs `dot`; everything after it does
not, and the tests are built around that split: the render path, the equivalence between
the rendered SVG, and every validation finding are driven from the checked-in diagram
model in tests/contracts/. Where `dot` is present the layout path is exercised too, and
where it is absent only the policy branches are.

That is not a gap papered over -- it is the reason `--render-only` exists as a real mode
rather than a test hook, and the reason the coverage promise is checked against the
class graph instead of against a picture.

    python3 tools/test_diagrams.py
"""

import copy
import hashlib
import json
import os
import shutil
import struct
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

# Past DENSITY_CLASSES, so the overview drops to summary and the detail views become the
# only place members are shown. Generated rather than checked in: this fixture is about
# scale, not about a schema shape worth freezing, and 72 hand-written classes would be
# 40KB of noise in every review of this directory.
DENSE_PACKAGES, DENSE_MODULES, DENSE_CLASSES = 6, 3, 4
ALL_LAYERS = ("inheritance", "composition", "association", "calls", "inference")


def dense_graph(collide=False):
    """A class graph past the density threshold, with relationships that leave packages.

    `collide` adds a package whose path slugs to the same filename as another's, which
    is the case that silently overwrote one view's files with another's.
    """
    def cid(p, m, c):
        return "class:src/pkg%d/mod%d.py:C%d%d%d" % (p, m, p, m, c)

    packages, modules, classes, edges = [], [], [], []
    paths = ["src/pkg%d" % p for p in range(DENSE_PACKAGES)]
    if collide:
        paths[-1] = "src/pkg0"          # same slug as paths[0], different id below
    for p, path in enumerate(paths):
        package = "package:%s" % (path if not collide or p != len(paths) - 1
                                  else "src.pkg0")
        module_ids = []
        for m in range(DENSE_MODULES):
            module = "module:src/pkg%d/mod%d.py" % (p, m)
            module_ids.append(module)
            ids = []
            for c in range(DENSE_CLASSES):
                ids.append(cid(p, m, c))
                classes.append({
                    "id": cid(p, m, c), "name": "C%d%d%d" % (p, m, c),
                    "module": module, "package": package, "stereotype": "class",
                    "cite": "src/pkg%d/mod%d.py:%d" % (p, m, c + 1),
                    "source_hash": "sha256:%02d" % p,
                    "members": {
                        "methods": [{"name": "run", "line": 2, "params": [],
                                     "visibility": "public"}],
                        "attributes": [{"name": "value", "line": 3, "types": ["int"],
                                        "visibility": "public"}]},
                })
            modules.append({"id": module, "name": "src/pkg%d/mod%d.py" % (p, m),
                            "package": package, "lang": "python",
                            "source_hash": "sha256:%02d" % p, "classes": ids})
        packages.append({"id": package, "name": path, "modules": module_ids})

    for p in range(len(paths)):
        for m in range(DENSE_MODULES):
            for c in range(1, DENSE_CLASSES):
                edges.append({"id": "edge:inheritance:%s:%s" % (cid(p, m, c),
                                                                cid(p, m, 0)),
                              "layer": "inheritance", "from": cid(p, m, c),
                              "to": cid(p, m, 0), "verified": True,
                              "cite": "src/pkg%d/mod%d.py:%d" % (p, m, c)})
        # One relationship out of every package: the boundary a detail view has to show
        # rather than hide.
        nxt = (p + 1) % len(paths)
        edges.append({"id": "edge:composition:%s:%s" % (cid(p, 0, 0), cid(nxt, 0, 1)),
                      "layer": "composition", "from": cid(p, 0, 0), "to": cid(nxt, 0, 1),
                      "verified": True, "cite": "src/pkg%d/mod0.py:1" % p})

    payload = {"packages": packages, "modules": modules, "classes": classes,
               "edges": edges}
    graph = {"schema_version": 1, "detail": "public",
             "source": {"root": ".", "revision": None, "dirty": True},
             "source_graph_hash": "sha256:" + hashlib.sha256(
                 json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
             "layers": list(ALL_LAYERS), "unresolved": [],
             "coverage": {"classes": len(classes), "modules_with_detail": len(modules),
                          "modules_without_detail": 0, "unresolved_relationships": 0,
                          "by_layer": {}}}
    graph.update(payload)
    return graph


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
        check("the model, the drawing and the manifest are written",
              written == ["diagram-manifest.json", "full-repository-model.json",
                          "full-repository.svg"],
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

        with open(os.path.join(good, "full-repository.svg"), encoding="utf-8") as fh:
            svg = fh.read()
        check("every box carries the id the model uses, so a checker can find it",
              'id="class:pkg/models.py:Order"' in svg)
        check("and so does every edge",
              'id="edge:inheritance:class:pkg/models.py:Order' in svg)

        # A render-only pass rebuilds one view. Rewriting the manifest from that single
        # entry would drop every other view from the record while its files sit on disk,
        # so the patch loop would read as having destroyed the rest to fix one.
        two_views = os.path.join(tmp, "two-views")
        render(MODEL, two_views)
        with open(MODEL, encoding="utf-8") as fh:
            second = json.load(fh)
        second["view"] = "package_pkg"
        second["scope"] = {"kind": "package", "id": "package:pkg"}
        second_path = os.path.join(tmp, "second-model.json")
        with open(second_path, "w", encoding="utf-8") as fh:
            json.dump(second, fh)
        render(second_path, two_views)
        with open(os.path.join(two_views, "diagram-manifest.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        listed = sorted(v["view"] for v in manifest["views"])
        check("a render-only pass adds its view without dropping the others",
              listed == ["full_repository", "package_pkg"], "%r" % listed)
        check("the manifest records what each view is answerable for",
              sorted(v["scope"]["kind"] for v in manifest["views"])
              == ["package", "repository"], "%r" % manifest["views"])
        check("each view keeps its own model file",
              os.path.isfile(os.path.join(two_views, "full-repository-model.json"))
              and os.path.isfile(os.path.join(two_views, "package-pkg-model.json")),
              "%r" % sorted(os.listdir(two_views)))

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
        with open(os.path.join(broken, "full-repository.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write("<svg><unclosed>")
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
            with open(os.path.join(laid_out, "full-repository-model.json"),
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

        # -- previews -------------------------------------------------------------
        # A browser's --window-size counts the window frame, which the screenshot does
        # not include, so a window sized to the drawing loses the bottom of it. That is
        # invisible in every structural check -- the SVG is correct, the picture is not
        # -- and it cost a class off the canvas before it was caught.
        preview_dir = os.path.join(tmp, "preview")
        code, output = render(MODEL, preview_dir, "--previews")
        png = os.path.join(preview_dir, "full-repository-preview.png")
        if code == 0 and os.path.isfile(png):
            with open(MODEL, encoding="utf-8") as fh:
                bounds = json.load(fh)["bounds"]
            with open(png, "rb") as fh:
                header = fh.read(24)
            width, height = struct.unpack(">II", header[16:24])
            check("the preview is at least as tall as the drawing plus frame allowance",
                  height >= bounds["height"] + 40, "%dx%d for a %r drawing"
                  % (width, height, bounds))
            check("and at least as wide", width >= bounds["width"],
                  "%d for width %r" % (width, bounds["width"]))
        else:
            print("skip preview checks -- no rasterizer available")
            check("--previews without a rasterizer fails rather than reporting success",
                  code != 0, output)

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

        # -- detail views, past the density threshold ------------------------------
        # The whole point of the threshold is that the overview stops showing members.
        # Until these views existed, that detail was simply lost.
        if HAVE_DOT:
            dense_path = os.path.join(tmp, "dense-graph.json")
            with open(dense_path, "w", encoding="utf-8") as fh:
                json.dump(dense_graph(), fh)
            dense_dir = os.path.join(tmp, "dense")
            code, output = run(BUILD, "--class-graph", dense_path, "--out", dense_dir,
                               "--policy", "required")
            check("a graph past the threshold lays out", code == 0, output)

            with open(os.path.join(dense_dir, "diagram-manifest.json"),
                      encoding="utf-8") as fh:
                manifest = json.load(fh)
            kinds = sorted(v["scope"]["kind"] for v in manifest["views"])
            check("the run produces one repository view and one view per package",
                  kinds == ["package"] * DENSE_PACKAGES + ["repository"], "%r" % kinds)

            models = {}
            for entry in manifest["views"]:
                with open(os.path.join(dense_dir, "%s-model.json" % entry["stem"]),
                          encoding="utf-8") as fh:
                    models[entry["view"]] = json.load(fh)
            overview = models["full_repository"]
            package_view = models[next(v for v in models if v != "full_repository")]
            check("the overview drops to summary, as the threshold requires",
                  overview["detail"] == "summary"
                  and all(len(n["label"]) == 1 for n in overview["nodes"]),
                  "%r" % overview["detail"])
            check("and the detail view is where the members went",
                  package_view["detail"] == "public"
                  and any(len(n["label"]) > 1 for n in package_view["nodes"]
                          if not n["external"]),
                  "%r" % package_view["detail"])

            neighbours = [n for n in package_view["nodes"] if n["external"]]
            check("a relationship leaving the package is drawn to a marked neighbour",
                  neighbours and all(n["label"][-1].startswith("(") for n in neighbours),
                  "%r" % [n["id"] for n in neighbours])

            drawn = set()
            for name, model in models.items():
                if name != "full_repository":
                    drawn |= {n["id"] for n in model["nodes"] if not n["external"]}
            check("every class the overview stopped describing is in some detail view",
                  drawn == {n["id"] for n in overview["nodes"]},
                  "%d vs %d" % (len(drawn), len(overview["nodes"])))

            check("every box on the overview leads to the view that shows it in full",
                  all(n.get("link") for n in overview["nodes"]),
                  "%r" % [n["id"] for n in overview["nodes"] if not n.get("link")][:3])

            code, report = validate(dense_dir, dense_path)
            check("the whole set validates", code == 0 and report["passed"],
                  "%r" % report.get("findings"))

            # A package with no view of its own takes its members out of the document
            # while every remaining view still checks out on its own.
            gap = os.path.join(tmp, "dense-gap")
            shutil.copytree(dense_dir, gap)
            with open(os.path.join(gap, "diagram-manifest.json"), encoding="utf-8") as fh:
                trimmed = json.load(fh)
            trimmed["views"] = [v for v in trimmed["views"]
                                if v["scope"]["kind"] != "package"][:1] + [
                v for v in trimmed["views"] if v["scope"]["kind"] == "package"][1:]
            with open(os.path.join(gap, "diagram-manifest.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(trimmed, fh)
            code, report = validate(gap, dense_path)
            check("a package left without a detail view is caught",
                  code == 1 and "G007" in codes(report), "%r" % report.get("findings"))

            # `src/api` and `src.api` slug to one filename. Without the collision guard
            # one view's files silently overwrite the other's.
            collide_path = os.path.join(tmp, "collide-graph.json")
            with open(collide_path, "w", encoding="utf-8") as fh:
                json.dump(dense_graph(collide=True), fh)
            collide_dir = os.path.join(tmp, "collide")
            code, output = run(BUILD, "--class-graph", collide_path, "--out",
                               collide_dir, "--policy", "required")
            check("packages whose paths slug alike still lay out", code == 0, output)
            with open(os.path.join(collide_dir, "diagram-manifest.json"),
                      encoding="utf-8") as fh:
                stems = [v["stem"] for v in json.load(fh)["views"]]
            check("and each gets its own filename, so no view overwrites another",
                  len(stems) == len(set(stems)) == DENSE_PACKAGES + 1, "%r" % stems)
            code, report = validate(collide_dir, collide_path)
            check("the colliding set validates too", code == 0 and report["passed"],
                  "%r" % report.get("findings"))
        else:
            print("skip detail-view checks -- Graphviz is not installed")
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
