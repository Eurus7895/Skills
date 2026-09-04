#!/usr/bin/env python3
"""Behavioural tests for validate_analysis.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The checker cannot ask whether a reading of a module is right. What it can ask is
whether a reading happened, and these tests are built around the three ways of proving
it did not: evidence that cannot be looked at, a sentence naming nothing in the file it
describes, and one sentence told about every module. Each has to come back as its own
finding, because each calls for a different fix.

    python3 tools/test_analysis_validation.py
"""

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "shared", "scripts", "validate_analysis.py")
CONTRACTS = os.path.join(REPO, "tests", "contracts")
INDEX = os.path.join(CONTRACTS, "structure-v2-minimal.json")
VALID = os.path.join(CONTRACTS, "module-analysis-v1-valid.jsonl")
INVALID = os.path.join(CONTRACTS, "module-analysis-v1-invalid.jsonl")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(path, *extra):
    proc = subprocess.run([sys.executable, SCRIPT, path, "--index", INDEX] + list(extra),
                          capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_output": proc.stdout + proc.stderr}


def rows_of(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write(tmp, name, rows):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def codes(report, severity=None):
    return sorted({f["code"] for f in report.get("findings", ())
                   if severity is None or f["severity"] == severity})


def verdict(report, statement_id):
    for module in report["modules"]:
        for statement in module["statements"]:
            if statement["id"] == statement_id:
                return statement["verdict"]
    return None


def main():
    tmp = tempfile.mkdtemp(prefix="analysis-validation-test-")
    try:
        code, report = run(VALID)
        check("real analysis passes", code == 0 and report["passed"], repr(report))
        check("and every module in it counts as analysed",
              report["analysed"] == 2, repr(report["modules"]))

        code, report = run(INVALID)
        check("a defective row fails", code == 1 and not report["passed"])
        check("and each defect gets its own code",
              codes(report) == ["A007", "A008", "A009", "A010", "A014"], codes(report))

        # The point of separating them. One file can hold four broken statements and one
        # good one, and rejecting the file wholesale would lose the good one and tell the
        # author nothing about which sentence to fix.
        check("a statement whose evidence cannot be read is rejected",
              verdict(report, "bad-s1") == "rejected")
        check("a statement naming nothing in its module does not count, but is no error",
              verdict(report, "bad-s5") == "unanchored"
              and codes(report, "error") == ["A007", "A008", "A009", "A010"],
              codes(report, "advisory"))
        check("and the one sound statement survives beside them",
              verdict(report, "bad-s6") == "valid")
        check("so the module is still analysed", report["modules"][0]["analysed"])

        # Repetition across modules. Within one module a second sentence is a second
        # thing to say; across modules an identical one was about neither.
        rows = rows_of(VALID)
        rows[1]["statements"][0]["text"] = rows[0]["statements"][0]["text"]
        code, report = run(write(tmp, "repeated.jsonl", rows))
        check("the same statement about two modules fails",
              code == 1 and "A012" in codes(report), codes(report))
        check("and both copies are rejected",
              verdict(report, "app-s1") == "rejected"
              and verdict(report, "store-s1") == "rejected")

        rows = rows_of(VALID)
        rows[0]["statements"] = [rows[0]["statements"][0]]
        rows[1]["statements"] = [dict(rows[1]["statements"][0],
                                      text=rows[0]["statements"][0]["text"]
                                      .replace("main()", "save()"))]
        code, report = run(write(tmp, "near.jsonl", rows))
        check("two statements differing only in their nouns are caught",
              "A013" in codes(report), codes(report))
        check("and a set that is all near-duplicates is called a template",
              code == 1 and any(f["code"] == "A013" and f["severity"] == "error"
                                for f in report["findings"]), repr(report["findings"]))

        # A module described only by prose that names nothing in it has not been read,
        # however many sentences there are. The sentences below are deliberately
        # *different* from each other: anchorless prose is usually repeated too, and
        # this has to isolate the one property from the other.
        rows = rows_of(VALID)
        anchorless = [["Serves as the primary boundary between the outside world and "
                       "everything behind it.",
                       "Coordinates the pieces below it without owning any of them."],
                      ["Holds persistent structures used widely across the system.",
                       "Offers a stable surface that callers elsewhere depend upon."]]
        for row, texts in zip(rows, anchorless):
            for statement, text in zip(row["statements"], texts):
                statement["text"] = text
        code, report = run(write(tmp, "anchorless.jsonl", rows))
        check("anchorless prose leaves no module analysed",
              report["analysed"] == 0, repr(report["modules"]))
        check("and says so without calling it an error",
              codes(report, "error") == [] and "A014" in codes(report, "advisory"),
              codes(report))

        # Freshness. The analysis and the index have to be talking about the same scan
        # and the same file version; either mismatch invalidates the reading, not the
        # source.
        rows = rows_of(VALID)
        rows[0]["source_hash"] = "sha256:" + "0" * 64
        code, report = run(write(tmp, "stale.jsonl", rows))
        check("analysis of a different version of the file is caught",
              code == 1 and "A004" in codes(report), codes(report))

        rows = rows_of(VALID)
        rows[0]["index_hash"] = "sha256:" + "1" * 64
        code, report = run(write(tmp, "otherscan.jsonl", rows))
        check("analysis carried over from another scan is caught",
              code == 1 and "A005" in codes(report), codes(report))

        rows = rows_of(VALID)
        rows[0]["path"] = "nowhere.py"
        code, report = run(write(tmp, "absent.jsonl", rows))
        check("analysis of a module the index does not hold is caught",
              code == 1 and "A003" in codes(report), codes(report))

        rows = rows_of(VALID)
        del rows[0]["statements"][0]["evidence"]
        code, report = run(write(tmp, "noevidence.jsonl", rows))
        check("a statement with no evidence at all is caught",
              code == 1 and "A002" in codes(report), codes(report))

        rows = rows_of(VALID)
        rows[1]["statements"][0]["id"] = rows[0]["statements"][0]["id"]
        code, report = run(write(tmp, "dupid.jsonl", rows))
        check("a statement id used twice is caught",
              code == 1 and "A011" in codes(report), codes(report))

        rows = rows_of(VALID)
        rows[0]["analysis_version"] = 99
        code, report = run(write(tmp, "future.jsonl", rows))
        check("an unknown analysis_version is an input error, not a finding",
              code == 2, repr(report))

        # `--out` writes what stdout printed, so the next stage reads a file rather than
        # parsing a pipe.
        out = os.path.join(tmp, "report.json")
        code, report = run(VALID, "--out", out)
        with open(out, encoding="utf-8") as fh:
            check("--out writes the same report it prints",
                  json.load(fh) == report, out)

        first = run(VALID)
        second = run(VALID)
        check("the same input gives the same report", first == second)

        # --- A `declared` statement cites the place the repository declares it, and
        # that place is an ADR or a README -- an asset, not a source file. Resolving
        # evidence against `files` alone rejected every such citation with A006, which
        # made the asset inventory unusable as evidence for the one statement status
        # that needs it.
        with open(INDEX, encoding="utf-8") as fh:
            v3 = json.load(fh)
        v3["schema_version"] = 3
        v3["assets"] = [
            {"path": "docs/adr/0001-layers.md", "kind": "adr",
             "source_hash": "sha256:" + "a" * 64, "bytes": 120, "lines": 6},
        ]
        index_v3 = os.path.join(tmp, "structure-v3.json")
        with open(index_v3, "w", encoding="utf-8") as fh:
            json.dump(v3, fh)

        def run_v3(path):
            proc = subprocess.run(
                [sys.executable, SCRIPT, path, "--index", index_v3],
                capture_output=True, text=True)
            try:
                return proc.returncode, json.loads(proc.stdout)
            except ValueError:
                return proc.returncode, {"_output": proc.stdout + proc.stderr}

        def declared(evidence, sid="adr-s1"):
            return [{"analysis_version": 1, "path": "app.py",
                     "source_hash": v3["files"][0]["source_hash"],
                     "index_hash": v3["index_hash"], "role": "The entry point.",
                     "statements": [{"id": sid, "kind": "rationale", "status": "declared",
                                     "text": "The ADR records that app.py owns the "
                                             "main guard and pkg/store.py owns saving.",
                                     "evidence": evidence}]}]

        cited = write(tmp, "adr-cited.jsonl", declared(
            [{"path": "docs/adr/0001-layers.md", "line_start": 3, "line_end": 4}]))
        code, report = run_v3(cited)
        check("evidence naming an indexed asset resolves",
              "A006" not in codes(report), repr(codes(report)))
        check("and the statement counts as analysis",
              verdict(report, "adr-s1") == "valid", repr(report.get("modules")))

        past_end = write(tmp, "adr-past-end.jsonl", declared(
            [{"path": "docs/adr/0001-layers.md", "line_start": 99, "line_end": 99}]))
        code, report = run_v3(past_end)
        check("an asset citation past the end of the file is A007",
              "A007" in codes(report), repr(codes(report)))

        stale = write(tmp, "adr-stale.jsonl", declared(
            [{"path": "docs/adr/0001-layers.md", "line_start": 3,
              "source_hash": "sha256:" + "b" * 64}]))
        code, report = run_v3(stale)
        check("an asset edited since the scan is A004", "A004" in codes(report),
              repr(codes(report)))

        symboled = write(tmp, "adr-symbol.jsonl", declared(
            [{"path": "docs/adr/0001-layers.md", "line_start": 3, "symbol": "save"}]))
        code, report = run_v3(symboled)
        check("naming a symbol inside an asset is A008, not a silent pass",
              "A008" in codes(report), repr(codes(report)))

        missing = write(tmp, "adr-missing.jsonl", declared(
            [{"path": "docs/adr/9999-nope.md", "line_start": 1}]))
        code, report = run_v3(missing)
        check("an asset the index does not hold is still A006",
              "A006" in codes(report), repr(codes(report)))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
