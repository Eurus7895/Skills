#!/usr/bin/env python3
"""Behavioural tests for architecture-analysis.json and Detector B.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

There is an easy way to fake an architecture synthesis, and an unconstrained model will
usually take it: read the directory listing and rename it. `src/app/api/` becomes "API
layer", `src/app/core/` becomes "Core", and the output has components, layers and a shape,
while containing nothing a reader could not have got from `ls`. It is the generic-prose
failure one level up, and Detector B exists for it -- so most of this file is about a
synthesis that is a rename, and about the cases where calling it one would be wrong.

    python3 tools/test_architecture.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
FIXTURE = os.path.join(REPO, "tests", "contracts", "layered-repo")

sys.path.insert(0, SCRIPTS)
import quality_docs                                           # noqa: E402
from quality_docs import DETECTOR_B_FAIL, DETECTOR_B_PARTIAL   # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True)
    return path


def component(cid, name, modules, **extra):
    row = {"id": cid, "name": name, "modules": list(modules), "status": "observed"}
    row.update(extra)
    return row


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())})


def validate(tmp, index, doc, analysis=None, name="arch.json"):
    path = write_json(os.path.join(tmp, name), doc)
    args = [path, "--index", index]
    if analysis:
        args += ["--analysis", analysis]
    code, out, err = run("validate_architecture.py", *args)
    try:
        return code, json.loads(out)
    except ValueError:
        return code, {"_output": out + err}


def main():
    tmp = tempfile.mkdtemp(prefix="architecture-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        index_path = os.path.join(tmp, "structure.json")
        run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
        digest = index["index_hash"]
        hashes = {r["path"]: r["source_hash"] for r in index["files"]}

        http = "src/app/api/http.py"
        analysis = os.path.join(tmp, "module-analysis.jsonl")
        with open(analysis, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "analysis_version": 1, "path": http, "source_hash": hashes[http],
                "index_hash": digest, "role": "The HTTP boundary.",
                "statements": [{"id": "m1", "kind": "interaction", "status": "observed",
                                "text": "Reaches core.service and never infra.store.",
                                "evidence": [{"path": http, "line_start": 3}]}]},
                sort_keys=True) + "\n")

        edge = ["src/app/api/http.py", "src/app/api/cli.py", "src/app/core/service.py"]
        store = ["src/app/infra/store.py", "src/app/infra/config.py",
                 "src/app/core/models.py"]
        honest = {
            "architecture_version": 1, "index_hash": digest,
            "components": [
                component("component:edge", "Request handling", edge,
                          statement_ids=["m1"],
                          rationale={"status": "declared",
                                     "text": "Both entry points share one rule set.",
                                     "evidence": [{"path": "README.md",
                                                   "line_start": 1}]}),
                component("component:storage", "Persistence", store),
            ],
            "relationships": [
                {"from": "component:edge", "to": "component:storage",
                 "kind": "depends_on", "status": "observed",
                 "evidence": [{"path": "src/app/core/service.py", "line_start": 4}]},
            ],
            "external_systems": [],
        }

        # --- The schema, and the things a synthesis cannot be.
        code, report = validate(tmp, index_path, honest, analysis)
        check("an honest synthesis validates", code == 0, repr(report)[:300])
        check("and reports a denominator per subject, not one figure",
              report["coverage"]["components"] == 2
              and report["coverage"]["relationships_with_evidence"] == 1
              and report["coverage"]["modules_placed"] == 6,
              repr(report["coverage"]))

        overlap = json.loads(json.dumps(honest))
        overlap["components"][1]["modules"].append("src/app/api/http.py")
        code, report = validate(tmp, index_path, overlap, analysis, "overlap.json")
        check("a module in two components is B004", "B004" in codes(report),
              repr(codes(report)))

        ghost = json.loads(json.dumps(honest))
        ghost["components"][0]["modules"].append("src/app/nowhere.py")
        code, report = validate(tmp, index_path, ghost, analysis, "ghost.json")
        check("a module the index does not know is B003", "B003" in codes(report),
              repr(codes(report)))

        empty = json.loads(json.dumps(honest))
        empty["components"][1]["modules"] = []
        code, report = validate(tmp, index_path, empty, analysis, "empty.json")
        check("a component holding nothing is B010", "B010" in codes(report),
              repr(codes(report)))

        dangling = json.loads(json.dumps(honest))
        dangling["relationships"][0]["to"] = "component:nope"
        code, report = validate(tmp, index_path, dangling, analysis, "dangling.json")
        check("a relationship to a component that does not exist is B006",
              "B006" in codes(report), repr(codes(report)))

        unevidenced = json.loads(json.dumps(honest))
        unevidenced["relationships"][0]["evidence"] = []
        code, report = validate(tmp, index_path, unevidenced, analysis, "noev.json")
        check("a relationship with no evidence is B011", "B011" in codes(report),
              repr(codes(report)))

        invented = json.loads(json.dumps(honest))
        invented["components"][0]["statement_ids"] = ["m1", "does-not-exist"]
        code, report = validate(tmp, index_path, invented, analysis, "invented.json")
        check("a statement id the module analysis does not contain is B008",
              "B008" in codes(report), repr(codes(report)))

        # An `unknown` rationale needs no evidence -- it is the honest answer for a
        # boundary nobody wrote a reason for, which is most of them.
        silent = json.loads(json.dumps(honest))
        silent["components"][0]["rationale"] = {
            "status": "unknown", "text": "Why the entry points share a rule set."}
        code, report = validate(tmp, index_path, silent, analysis, "silent.json")
        check("an unknown rationale needs no evidence", code == 0, repr(codes(report)))
        check("and is counted separately from one that has a reason",
              report["coverage"]["rationale_unknown"] == 1
              and report["coverage"]["components_with_rationale"] == 0,
              repr(report["coverage"]))

        stale = json.loads(json.dumps(honest))
        stale["index_hash"] = "sha256:" + "0" * 64
        code, report = validate(tmp, index_path, stale, analysis, "stale.json")
        check("a synthesis written against another scan is an input error", code == 2,
              repr(report)[:200])

        # --- Detector B.
        detect = quality_docs.detector_b

        rename = {"architecture_version": 1, "index_hash": digest, "relationships": [],
                  "external_systems": [], "components": []}
        by_dir = {}
        for path in [r["path"] for r in index["files"] if r.get("symbols")]:
            by_dir.setdefault(os.path.dirname(path), []).append(path)
        for directory, members in sorted(by_dir.items()):
            leaf = os.path.basename(directory)
            rename["components"].append(
                component("component:%s" % leaf, leaf, sorted(members)))

        verdict = detect(rename)
        check("the directory tree with its own names fails",
              verdict["outcome"] == "failed" and verdict["is_directory_rename"],
              repr(verdict))
        check("and says nothing was merged, split or renamed",
              "nothing was merged" in verdict["detail"], verdict["detail"])

        # The same partition under invented names is still the same partition. Comparing
        # labels would call this a synthesis; pair counting does not.
        relabelled = json.loads(json.dumps(rename))
        for i, entry in enumerate(relabelled["components"]):
            entry["name"] = "Subsystem %d" % i
        verdict = detect(relabelled)
        check("the same grouping under invented names still fails",
              verdict["outcome"] == "failed" and verdict["agreement"] == 1.0,
              repr(verdict))
        check("but is not reported as a rename", not verdict["is_directory_rename"],
              repr(verdict))

        verdict = detect(honest)
        check("a grouping that crosses directories passes",
              verdict["outcome"] == "passed", repr(verdict))
        check("and its independent content is reported beside the index",
              verdict["independent_content"] == 1.0, repr(verdict))

        # One module moved out of its directory's component: closer to the tree than the
        # honest grouping, further than a rename. Reported, not fatal -- a repository is
        # allowed to be organised the way its architecture is.
        #
        # Built to size rather than taken from the fixture. Whether one moved module
        # lands in [0.85, 0.95) depends entirely on how many modules there are -- with
        # the fixture's seven it scores 0.8 and passes, which says nothing about the
        # threshold. Twenty modules over two directories put it at 0.9.
        wide = ["pkg%d/m%d.py" % (0 if i < 10 else 1, i) for i in range(20)]
        first, second = wide[:10], wide[10:]
        nearly = {"architecture_version": 1, "index_hash": digest, "relationships": [],
                  "external_systems": [], "components": [
                      component("component:one", "One", first + second[:1]),
                      component("component:two", "Two", second[1:])]}
        verdict = detect(nearly)
        check("a grouping that is nearly the tree is partial, not fatal",
              verdict["outcome"] == "partial"
              and DETECTOR_B_PARTIAL <= verdict["agreement"] < DETECTOR_B_FAIL,
              "%s agreement=%s" % (verdict["outcome"], verdict.get("agreement")))

        exact = {"architecture_version": 1, "index_hash": digest, "relationships": [],
                 "external_systems": [], "components": [
                     component("component:one", "One", first),
                     component("component:two", "Two", second)]}
        check("and the same shape with nothing moved fails",
              detect(exact)["outcome"] == "failed", repr(detect(exact)))

        # --- Nothing to compare is not a pass.
        tiny = {"architecture_version": 1, "index_hash": digest, "relationships": [],
                "external_systems": [],
                "components": [component("component:all", "Everything",
                                         ["src/app/api/http.py"])]}
        verdict = detect(tiny)
        check("one component over one directory is not_applicable",
              verdict["outcome"] == "not_applicable", repr(verdict))
        check("and says why rather than reporting a number",
              verdict["agreement"] is None and "no partition" in verdict["detail"],
              repr(verdict))

        # --- The gate carries the verdict, and not_applicable never reads as a pass.
        for name, doc, expected in (("rename", rename, "failed"),
                                    ("honest", honest, None),
                                    ("tiny", tiny, "partial")):
            path = write_json(os.path.join(tmp, "gate-%s.json" % name), doc)
            code, out, err = run("quality_docs.py", "--index", index_path,
                                 "--analysis", analysis, "--architecture", path)
            gate = json.loads(out)
            if expected == "failed":
                check("the gate fails a document whose architecture is the tree",
                      gate["status"] == "failed"
                      and any("detector B" in r for r in gate["reasons"]),
                      repr(gate["reasons"]))
            elif expected == "partial":
                check("the gate never reports not_applicable as passed",
                      gate["status"] != "passed"
                      and any("did not run" in r for r in gate["reasons"]),
                      repr(gate["reasons"]))
            else:
                check("the gate does not fail an honest synthesis",
                      gate["architecture"]["outcome"] == "passed", repr(gate["reasons"]))

        # --- Same input, same report.
        first = validate(tmp, index_path, honest, analysis, "again-a.json")
        second = validate(tmp, index_path, honest, analysis, "again-b.json")
        check("the same synthesis gives the same report", first == second)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
