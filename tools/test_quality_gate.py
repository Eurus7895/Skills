#!/usr/bin/env python3
"""Behavioural tests for quality_docs.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The gate is the one stage that can tell a read document from a derived one, so what it
has to get right is where the lines sit and what does not move them: the budget a run
set for itself, and modules it never undertook to read.

    python3 tools/test_quality_gate.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
GATE = os.path.join(SCRIPTS, "quality_docs.py")
CONTRACTS = os.path.join(REPO, "tests", "contracts")
INDEX = os.path.join(CONTRACTS, "structure-v2-minimal.json")
ANALYSIS = os.path.join(CONTRACTS, "module-analysis-v1-valid.jsonl")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(*extra):
    proc = subprocess.run([sys.executable, GATE, "--index", INDEX] + list(extra),
                          capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_output": proc.stdout + proc.stderr}


def rows_of(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="quality-gate-test-")
    try:
        code, report = run("--analysis", ANALYSIS)
        check("two modules read out of two is per_module",
              report["analysis_mode"] == "per_module"
              and report["modules"]["coverage"] == 1.0, repr(report["modules"]))
        check("and that passes", code == 0 and report["status"] == "passed",
              repr(report.get("reasons")))

        code, report = run()
        check("no analysis at all is derived_only",
              report["analysis_mode"] == "derived_only", repr(report))
        check("which is never passed, but is not a failure either",
              report["status"] == "partial", repr(report["reasons"]))
        check("so it exits 0 by default and 1 when per-module work was required",
              code == 0 and run("--require", "passed")[0] == 1)

        # Half is the line. One of two modules read is the weakest thing that still
        # counts as partial rather than as nothing.
        half = write_rows(os.path.join(tmp, "half.jsonl"), rows_of(ANALYSIS)[:1])
        code, report = run("--analysis", half)
        check("one of two is partial, exactly on the boundary",
              report["analysis_mode"] == "partial"
              and report["modules"]["coverage"] == 0.5, repr(report["modules"]))
        check("and partial is reported with the count that produced it",
              any("1 of 2" in reason for reason in report["reasons"]),
              repr(report["reasons"]))

        # The budget is the point of the whole design: a run that read everything it
        # undertook to read is per_module however large the repository is.
        units = os.path.join(tmp, "units.txt")
        with open(units, "w", encoding="utf-8") as fh:
            fh.write("app.py\n")
        code, report = run("--analysis", half, "--units", units)
        check("a module outside the budget does not drag coverage down",
              report["analysis_mode"] == "per_module"
              and report["modules"]["in_budget"] == 1
              and report["modules"]["out_of_budget"] == 2, repr(report["modules"]))
        check("and the report says where the budget came from",
              report["modules"]["budget_from"] == "units.txt",
              report["modules"]["budget_from"])

        with open(units, "w", encoding="utf-8") as fh:
            fh.write("app.py\nnot/a/file.py\n")
        code, report = run("--analysis", half, "--units", units)
        check("a budget naming a module the index does not hold is an input error",
              code == 2, repr(report))

        # A statement that cannot be checked is a different answer from a document that
        # was never read, and outranks it: the run is broken, not merely shallow.
        code, report = run("--analysis",
                           os.path.join(CONTRACTS, "module-analysis-v1-invalid.jsonl"))
        check("rejected statements fail the run outright",
              code == 1 and report["status"] == "failed", repr(report["reasons"]))

        # Everything below is the rest of the run, reported beside the analysis rather
        # than in place of it.
        doc = {"format_version": 1, "generator_version": "t", "preset": "onboarding",
               "source_revision": None, "source_dirty": True, "coverage": {},
               "claims": [], "authored_pages": [],
               "pages": [{"id": "overview", "title": "Overview", "order": 1,
                          "mandatory": True, "blocks": []}]}
        doc_path = os.path.join(tmp, "doc.json")
        with open(doc_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        code, report = run("--analysis", ANALYSIS, "--doc", doc_path)
        check("a preset missing mandatory pages fails",
              code == 1 and report["status"] == "failed"
              and "entry-points" in report["pages"]["missing"], repr(report["pages"]))

        empty = os.path.join(tmp, "diagrams")
        os.makedirs(empty)
        with open(os.path.join(empty, "diagram-manifest.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"schema_version": 3, "views": [
                {"view": "package_pkg", "scope": {"kind": "package", "id": "package:pkg"}}
            ]}, fh)
        code, report = run("--analysis", ANALYSIS, "--diagrams", empty)
        check("a diagram set with no repository view fails",
              code == 1 and not report["diagrams"]["repository_view"],
              repr(report.get("diagrams")))

        claims = os.path.join(tmp, "claims.jsonl")
        write_rows(claims, [{"id": "c1", "status": "verified"},
                            {"id": "c2", "status": "rejected"}])
        code, report = run("--analysis", ANALYSIS, "--claims", claims)
        check("a rejected claim fails the run too",
              code == 1 and report["claims"]["by_status"]["rejected"] == 1,
              repr(report.get("claims")))

        out = os.path.join(tmp, "report.json")
        code, report = run("--analysis", ANALYSIS, "--out", out)
        with open(out, encoding="utf-8") as fh:
            check("--out writes the same report it prints", json.load(fh) == report)
        check("the same inputs give the same report",
              run("--analysis", ANALYSIS) == run("--analysis", ANALYSIS))
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
