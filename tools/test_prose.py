#!/usr/bin/env python3
"""Behavioural tests for check_prose.py: the sentence against the analysis behind it.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Everything upstream asks whether a statement had evidence. This asks whether the sentence
a reader ends up seeing still says what that statement said, and the interesting cases are
the ones where every upstream check is green: the claim is verified, the line is cited, the
page is covered, and the verb has been quietly promoted on the way to the page.

Most of what follows seeds exactly that -- a page saying *owns* over a `calls` claim, a
page asserting a rationale the analysis recorded as `unknown` -- and then checks that the
honest document those seeds were grown from still passes. A checker that fails the honest
fixture is worse than none, because it gets switched off.

    python3 tools/test_prose.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")

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


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())
                   if f.get("severity") != "advisory"})


def prose(block_id, text, claim_refs=(), analysis_refs=()):
    return {"id": block_id, "type": "prose", "text": text,
            "claim_refs": list(claim_refs), "analysis_refs": list(analysis_refs)}


def main():
    tmp = tempfile.mkdtemp(prefix="prose-test-")
    try:
        def doc_with(*blocks, **kw):
            return {
                "format_version": 2, "preset": "outside-in",
                "claims": kw.get("claims", [
                    {"id": "claim:import", "kind": "imports", "status": "verified",
                     "subject": "module:a.py", "object": "module:b.py"},
                    {"id": "claim:call", "kind": "calls", "status": "verified",
                     "subject": "symbol:a.py:f", "object": "symbol:b.py:g"},
                ]),
                "statements": kw.get("statements", [
                    {"id": "s-observed", "kind": "interaction", "status": "observed",
                     "path": "a.py", "text": "a.py calls into b.py to store the order."},
                    {"id": "s-inferred", "kind": "rationale", "status": "inferred",
                     "path": "a.py", "text": "The split exists to keep storage separate."},
                ]),
                "pages": [{"id": "components", "title": "The parts", "order": 1,
                           "mandatory": True, "covers": [], "analysis_ids": [],
                           "blocks": list(blocks)}],
                "authored_pages": [],
            }

        def check_prose(doc, name, *extra):
            path = write_json(os.path.join(tmp, name), doc)
            code, out, err = run("check_prose.py", path, *extra)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        # --- The honest document.
        honest = doc_with(
            prose("block:a", "a.py imports b.py.", claim_refs=["claim:import"]),
            prose("block:b", "a.py calls into b.py to store the order.",
                  analysis_refs=["s-observed"]),
            prose("block:c", "Inferred, not observed: the split exists to keep storage "
                             "separate.", analysis_refs=["s-inferred"]),
        )
        code, report = check_prose(honest, "honest.json")
        check("an honest document passes", code == 0 and report["status"] == "passed",
              repr(codes(report)))

        # --- The verb ladder.
        promoted = doc_with(
            prose("block:a", "a.py depends on b.py.", claim_refs=["claim:import"]))
        code, report = check_prose(promoted, "promoted.json")
        check("an import rendered as 'depends on' is P003", "P003" in codes(report),
              repr(codes(report)))

        owned = doc_with(
            prose("block:a", "a.py owns the storage in b.py.",
                  claim_refs=["claim:call"]))
        code, report = check_prose(owned, "owned.json")
        check("a call rendered as 'owns' is P003", "P003" in codes(report),
              repr(codes(report)))

        allowed = doc_with(
            prose("block:a", "a.py calls b.py.", claim_refs=["claim:call"]))
        code, report = check_prose(allowed, "allowed.json")
        check("a call rendered as 'calls' is fine", code == 0, repr(codes(report)))

        weaker = doc_with(
            prose("block:a", "a.py references b.py.", claim_refs=["claim:import"]))
        code, report = check_prose(weaker, "weaker.json")
        check("saying less than the claim supports is never a finding", code == 0,
              repr(codes(report)))

        # The statement's own words are the ceiling for prose built from it.
        upgraded = doc_with(
            prose("block:b", "a.py owns b.py and drives the whole write path.",
                  analysis_refs=["s-observed"]))
        code, report = check_prose(upgraded, "upgraded.json")
        check("prose may not use a stronger verb than the statement it restates",
              "P003" in codes(report), repr(codes(report)))

        restated = doc_with(
            prose("block:b", "a.py calls b.py.", analysis_refs=["s-observed"]))
        code, report = check_prose(restated, "restated.json")
        check("but restating the statement's own verb is fine", code == 0,
              repr(codes(report)))

        # A word that merely contains a verb is not that verb.
        substring = doc_with(
            prose("block:a", "The callback registry imports b.py.",
                  claim_refs=["claim:import"]))
        code, report = check_prose(substring, "substring.json")
        check("'callback' is not a call", code == 0, repr(codes(report)))

        # --- The hedge.
        bald = doc_with(
            prose("block:c", "The split exists to keep storage separate.",
                  analysis_refs=["s-inferred"]))
        code, report = check_prose(bald, "bald.json")
        check("an inferred reading stated as fact is P004", "P004" in codes(report),
              repr(codes(report)))

        # --- Sources the doc model carries no ref for: the mechanically rendered tables.
        architecture = write_json(os.path.join(tmp, "arch.json"), {
            "architecture_version": 1, "index_hash": "sha256:x",
            "components": [{"id": "component:store", "name": "Storage",
                            "status": "observed", "modules": ["b.py"],
                            "rationale": {"status": "unknown",
                                          "text": "Why storage is separate."}}]})
        flows = write_json(os.path.join(tmp, "flows.json"), {
            "flow_version": 1, "index_hash": "sha256:x",
            "flows": [{"id": "flow:x", "name": "x", "status": "observed",
                       "trigger": {"kind": "cli", "status": "inferred",
                                   "text": "A scheduler starts it every hour."},
                       "steps": []}]})

        asserted = doc_with(
            {"id": "block:t", "type": "table",
             "columns": ["Component", "Why"], "claim_refs": [], "analysis_refs": [],
             "rows": [["Storage", "Why storage is separate."]]})
        code, report = check_prose(asserted, "asserted.json", "--architecture",
                                   architecture)
        check("a rationale recorded as unknown, stated as the reason, is P004",
              "P004" in codes(report), repr(codes(report)))

        marked = doc_with(
            {"id": "block:t", "type": "table",
             "columns": ["Component", "The question nobody answered"],
             "claim_refs": [], "analysis_refs": [],
             "rows": [["Storage", "Why storage is separate."]]})
        code, report = check_prose(marked, "marked.json", "--architecture", architecture)
        check("the same table hedged by its own column header passes", code == 0,
              repr(codes(report)))

        # This is what the renderer emits: the hedge is a prefix on the source text, so
        # dropping it leaves that text on the page bare. Substring matching catches that
        # exactly, and catches nothing if the sentence is rewritten instead -- see the
        # note in the plan; a rewrite of unreferenced material is the model pass's job.
        flat_trigger = doc_with(
            prose("block:f", "Starts when: Inferred, not observed: A scheduler starts "
                             "it every hour."))
        code, report = check_prose(flat_trigger, "flowok.json", "--flows", flows)
        check("an inferred trigger keeps its hedge and passes", code == 0,
              repr(codes(report)))

        stripped = doc_with(
            prose("block:f", "Starts when: A scheduler starts it every hour."))
        code, report = check_prose(stripped, "flowbald.json", "--flows", flows)
        check("the same trigger with the hedge dropped is P004",
              "P004" in codes(report), "%d %s" % (code, repr(codes(report))))

        # --- Generator framing is listed, never failed.
        framing = doc_with(
            prose("block:intro", "Each row is an import edge that crosses a directory "
                                 "boundary. An import proves a reference, not a call."))
        code, report = check_prose(framing, "framing.json")
        check("an uncited generator sentence is advisory, not a failure",
              code == 0 and "P005" in {f["code"] for f in report["findings"]},
              repr(report["findings"])[:300])

        # --- The bounded model pass.
        queued = doc_with(
            prose("block:c", "Inferred, not observed: the split exists to keep storage "
                             "separate.", analysis_refs=["s-inferred"]))
        code, report = check_prose(queued, "queued.json")
        check("a block resting on a reading is queued for the model pass",
              [q["block"] for q in report["review_queue"]] == ["block:c"],
              repr(report["review_queue"]))

        code, report = check_prose(queued, "queued2.json", "--require-review")
        check("and with no verdicts the run is review_required, not passed",
              code == 1 and report["status"] == "review_required",
              "%d %s" % (code, report.get("status")))
        check("which is reported as what it is: nothing was decided",
              report["unreviewed"] == ["block:c"], repr(report.get("unreviewed")))

        review = os.path.join(tmp, "review.jsonl")
        with open(review, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"block": "block:c", "verdict": "ok"}) + "\n")
        code, report = check_prose(queued, "queued3.json", "--require-review",
                                   "--review", review)
        check("a verdict of ok lets it pass",
              code == 0 and report["status"] == "passed", repr(report)[:200])

        with open(review, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"block": "block:c", "verdict": "overstated",
                                 "note": "the reading became the reason"}) + "\n")
        code, report = check_prose(queued, "queued4.json", "--require-review",
                                   "--review", review)
        check("and a verdict of overstated is a finding",
              "P007" in codes(report) and report["status"] == "failed",
              repr(codes(report)))

        code, out, err = run("check_prose.py",
                             write_json(os.path.join(tmp, "typo.json"), honest),
                             "--review", os.path.join(tmp, "not-here.jsonl"))
        check("a mistyped --review path is an input error", code == 2,
              "%d %r" % (code, err[:150]))

        # --- The gate carries the verdict.
        index_path = write_json(os.path.join(tmp, "structure.json"), {
            "schema_version": 3, "index_hash": "sha256:x", "files": [], "edges": [],
            "assets": [], "coverage": {}, "diagnostics": [], "entry_points": [],
            "fan_in": {}, "fan_out": {}})

        def gate(prose_report):
            code, out, err = run("quality_docs.py", "--index", index_path,
                                 "--prose", prose_report)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        failing = os.path.join(tmp, "prose-failed.json")
        check_prose(bald, "forgate.json", "--out", failing)
        code, report = gate(failing)
        check("the gate fails a document whose prose outruns its analysis",
              report["status"] == "failed"
              and any("says more than the analysis" in r for r in report["reasons"]),
              repr(report.get("reasons")))

        pending = os.path.join(tmp, "prose-review.json")
        check_prose(queued, "forgate2.json", "--require-review", "--out", pending)
        code, report = gate(pending)
        check("and reports review_required as itself, never as partial or passed",
              report["status"] == "review_required", repr(report.get("status")))
        check("with the reason naming what was not decided",
              any("did not decide" in r for r in report["reasons"]),
              repr(report.get("reasons")))

        # --- Same input, same report.
        check("the same document gives the same report",
              check_prose(honest, "again-a.json") == check_prose(honest, "again-b.json"))
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
