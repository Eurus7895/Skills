#!/usr/bin/env python3
"""The traced flow has to reach the rendered page, and the gate has to count it.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

`validate_flows.py` and `validate_operations.py` are worth nothing if what they check
never arrives on a page. This asserts against the rendered RST rather than `doc.json`,
because the document model is an intermediate file and the reader sees the other one; a
block that exists in JSON and renders to nothing is the failure this file is for.

    python3 tools/test_flow_document.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
FIXTURE = os.path.join(REPO, "tests", "contracts", "flow-repo")

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


def main():
    tmp = tempfile.mkdtemp(prefix="flow-document-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        index_path = os.path.join(tmp, "structure.json")
        run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
        with open(index_path, encoding="utf-8") as fh:
            digest = json.load(fh)["index_hash"]

        entry = "src/pipeline/entry.py"
        transform = "src/pipeline/transform.py"
        store = "src/pipeline/store.py"
        main_id = "symbol:%s:main" % entry
        normalise_id = "symbol:%s:normalise" % transform
        save_id = "symbol:%s:save" % store

        claims_in = os.path.join(tmp, "claims.jsonl")
        with open(claims_in, "w", encoding="utf-8") as fh:
            for row in (
                {"id": "claim:a", "kind": "calls", "subject": main_id,
                 "object": normalise_id,
                 "evidence": [{"path": entry, "line_start": 7}], "index_hash": digest},
                {"id": "claim:b", "kind": "calls", "subject": normalise_id,
                 "object": save_id,
                 "evidence": [{"path": transform, "line_start": 7}],
                 "index_hash": digest},
            ):
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        verified = os.path.join(tmp, "verified")
        run("verify_doc.py", "--claims", claims_in, "--index", index_path,
            "--root", root, "--out-dir", verified)
        claims_path = os.path.join(verified, "claims.verified.jsonl")
        fragments_path = os.path.join(verified, "fragments.verified.jsonl")
        if not os.path.isfile(fragments_path):
            open(fragments_path, "w", encoding="utf-8").close()

        flow_doc = {
            "flow_version": 1, "index_hash": digest,
            "flows": [{
                "id": "flow:normalise", "name": "Normalising an argument",
                "status": "observed",
                "trigger": {"kind": "cli", "text": "The console script calls main.",
                            "status": "declared",
                            "evidence": [{"path": "pyproject.toml", "line_start": 7}]},
                "steps": [
                    {"id": "step:1", "from": main_id, "to": normalise_id,
                     "text": "main hands its argument to normalise.",
                     "status": "observed", "claim_ids": ["claim:a"],
                     "evidence": [{"path": entry, "line_start": 7}]},
                    {"id": "step:2", "from": normalise_id, "to": save_id,
                     "text": "normalise saves the trimmed value.", "status": "observed",
                     "claim_ids": ["claim:b"],
                     "evidence": [{"path": transform, "line_start": 7}]},
                ],
                "outcome": {"status": "observed", "text": "The length is returned.",
                            "evidence": [{"path": store, "line_start": 5}]},
                "unresolved": [{"after": "step:2",
                                "reason": "Nothing inside the repository calls main."}],
            }],
        }
        flows_path = write_json(os.path.join(tmp, "flow-analysis.json"), flow_doc)

        def build(name, *extra):
            # Named apart from the inputs on purpose: an earlier version wrote doc.json
            # over the flow analysis it had just been given, and every later check in
            # this file then ran against a file that was no longer a flow analysis.
            out = os.path.join(tmp, "doc-%s.json" % name)
            code, _, err = run("build_document_model.py", "--index", index_path,
                               "--claims", claims_path, "--fragments", fragments_path,
                               "--preset", "onboarding", "--out", out, *extra)
            return code, out, err

        code, plain_doc, err = build("plain")
        check("the document builds without a flow analysis, as it always did",
              code == 0, err[:300])

        code, traced_doc, err = build("traced", "--flows", flows_path)
        check("and builds with one", code == 0, err[:300])

        def render(doc_path, name):
            out = os.path.join(tmp, name)
            code, _, err = run("render_docs.py", "--doc", doc_path, "--format", "rst",
                               "--out", out)
            page = os.path.join(out, "flows.rst")
            with open(page, encoding="utf-8") as fh:
                return code, fh.read()

        code, plain_rst = render(plain_doc, "plain-rst")
        code, traced_rst = render(traced_doc, "traced-rst")

        # The fallback is a table of verified calls with no order to them -- which is
        # exactly why the flow analysis is worth having. It lists the same two calls and
        # cannot say that one leads to the other, or what starts either.
        check("without a flow analysis the page is an unordered table of calls",
              "src/pipeline/entry.py:7" in plain_rst
              and "Normalising an argument" not in plain_rst
              and "The console script calls main." not in plain_rst,
              plain_rst[:600])

        check("with one, the flow is named on the page a reader sees",
              "Normalising an argument" in traced_rst, traced_rst[:600])
        check("the trigger is stated, with where it was read",
              "The console script calls main." in traced_rst
              and "pyproject.toml:7" in traced_rst, traced_rst[:800])
        check("every hop carries the line the call was read at",
              "%s:7" % entry in traced_rst and "%s:7" % transform in traced_rst,
              traced_rst[:1200])
        check("the hops appear in the order the flow holds them",
              traced_rst.index("entry.main") < traced_rst.index("store.save"),
              traced_rst[:1200])
        check("the outcome is stated", "The length is returned." in traced_rst,
              traced_rst[:1200])
        check("and where the trace stopped is on the page, not only in a report",
              "Nothing inside the repository calls main." in traced_rst,
              traced_rst[:1500])

        # A trigger the analysis only inferred must not read like one it observed. The
        # validator allows `inferred` and `unknown` without observed evidence, so the
        # page is the last place the distinction can survive.
        hedge = json.loads(json.dumps(flow_doc))
        hedge["flows"][0]["trigger"]["status"] = "inferred"
        hedge["flows"][0]["outcome"]["status"] = "unknown"
        hedge_path = write_json(os.path.join(tmp, "hedged.json"), hedge)
        code, hedge_doc, err = build("hedged", "--flows", hedge_path)
        code, hedge_rst = render(hedge_doc, "hedged-rst")
        check("an inferred trigger is rendered with its hedge, not as a fact",
              "Inferred, not observed:" in hedge_rst, hedge_rst[:800])
        check("and an outcome the repository never states says so",
              "Not recorded in the repository:" in hedge_rst, hedge_rst[:1200])
        check("while the observed version of the same flow carries no hedge",
              "Inferred, not observed:" not in traced_rst, traced_rst[:800])

        absent = write_json(os.path.join(tmp, "absent.json"),
                            {"flow_version": 1, "index_hash": digest, "flows": [],
                             "absent": {"reason": "No call was verified at its call "
                                                  "site, so no chain could be traced."}})
        code, absent_doc, err = build("absent", "--flows", absent)
        code, absent_rst = render(absent_doc, "absent-rst")
        check("a stated absence is what the page says, in the analysis's own words",
              "no chain could be traced" in absent_rst, absent_rst[:400])

        stale = write_json(os.path.join(tmp, "stale.json"),
                           dict(flow_doc, index_hash="sha256:" + "0" * 64))
        code, _, err = build("stalebuild", "--flows", stale)
        check("a flow analysis from another scan stops the build",
              code == 2 and "written against" in err, "%d %r" % (code, err[:200]))

        # --- The gate.
        operations = write_json(os.path.join(tmp, "operations.json"), {
            "operations_version": 1, "index_hash": digest,
            "procedures": [{
                "id": "op:test", "kind": "test", "name": "Running the tests",
                "status": "declared",
                "steps": [{"text": "CI runs the suite.", "status": "declared",
                           "command": "python3 -m pytest",
                           "evidence": [{"path": ".github/workflows/ci.yml",
                                         "line_start": 8}]}]}]})

        def gate(*extra):
            code, out, err = run("quality_docs.py", "--index", index_path,
                                 "--claims", claims_path, *extra)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        flow_report = os.path.join(tmp, "flow-report.json")
        run("validate_flows.py", flows_path, "--index", index_path,
            "--claims", claims_path, "--out", flow_report)

        code, first = gate("--flows", flows_path, "--flow-report", flow_report,
                           "--operations", operations)
        check("the gate reports a flow denominator",
              first["flows"] == {"flows": 1, "steps": 2, "unresolved": 1,
                                 "refused": 0, "validated": True,
                                 "absent_stated": False},
              repr(first.get("flows")))
        check("and it is counts, not a percentage",
              all(not isinstance(v, float) for v in first["flows"].values()
                  if v is not None),
              repr(first.get("flows")))
        check("the gate reports what operations were found",
              first["operations"]["procedures"] == 1
              and first["operations"]["commands"] == 1
              and first["operations"]["kinds"] == ["test"],
              repr(first.get("operations")))

        # Counting the raw analysis let a refused flow read as a traced one: the
        # supported workflow leaves it in the file and the diagram builder skips it.
        mixed = json.loads(json.dumps(flow_doc))
        broken = json.loads(json.dumps(flow_doc["flows"][0]))
        broken["id"] = "flow:broken"
        broken["steps"][1]["claim_ids"] = ["claim:a"]         # a real call, wrong hop
        mixed["flows"].append(broken)
        mixed_path = write_json(os.path.join(tmp, "mixed.json"), mixed)
        mixed_report = os.path.join(tmp, "mixed-report.json")
        run("validate_flows.py", mixed_path, "--index", index_path,
            "--claims", claims_path, "--out", mixed_report)
        code, report = gate("--flows", mixed_path, "--flow-report", mixed_report)
        check("a refused flow is not counted as traced",
              report["flows"]["flows"] == 1 and report["flows"]["refused"] == 1,
              repr(report.get("flows")))
        check("and the run is held back for it",
              report["status"] != "passed"
              and any("refused" in r for r in report["reasons"]),
              repr(report.get("reasons")))

        code, report = gate("--flows", mixed_path)
        check("without a flow report the counts are marked unvalidated",
              report["flows"]["validated"] is False
              and any("nothing has validated" in r for r in report["reasons"]),
              repr(report.get("flows")))
        empty_flows = write_json(os.path.join(tmp, "empty-flows.json"),
                                 {"flow_version": 1, "index_hash": digest, "flows": []})
        code, report = gate("--flows", empty_flows)
        check("nothing traced and no reason given is not a pass",
              report["status"] != "passed"
              and any("does not say why" in r for r in report["reasons"]),
              repr(report.get("reasons")))

        code, report = gate("--flows", absent)
        check("nothing traced with a reason given does not hold the gate back",
              not any("does not say why" in r for r in report["reasons"]),
              repr(report.get("reasons")))

        code, report = gate("--flows", stale)
        check("a flow analysis from another scan is an input error at the gate too",
              code == 2, repr(report)[:200])
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
