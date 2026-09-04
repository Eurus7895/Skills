#!/usr/bin/env python3
"""Behavioural tests for flow-analysis.json.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

A flow is the most useful thing a document can say and the easiest to fabricate. Three
plausible hops read like a traced request whether or not any of the calls happen, and the
raw material for the fabrication -- an import graph -- is sitting right there. So the
tests here are mostly about a flow that is *nearly* right: a chain whose middle hop cites
a call the verifier rejected, one whose steps do not join up, one citing a real verified
call between two other files.

The chain comes from `tests/contracts/flow-repo`, and the claims behind it are run
through `verify_doc.py` for real rather than hand-written as verified: a test that
asserts on a status it wrote itself proves nothing about the pipeline it stands in.

    python3 tools/test_flows.py
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


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())})


def main():
    tmp = tempfile.mkdtemp(prefix="flows-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        index_path = os.path.join(tmp, "structure.json")
        run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
        digest = index["index_hash"]

        entry = "src/pipeline/entry.py"
        transform = "src/pipeline/transform.py"
        store = "src/pipeline/store.py"
        main_id = "symbol:%s:main" % entry
        normalise_id = "symbol:%s:normalise" % transform
        save_id = "symbol:%s:save" % store

        # Two real calls plus one the verifier will refuse: `save` is not imported into
        # entry.py, so a claim that entry calls it directly cannot be read at a call site.
        raw_claims = os.path.join(tmp, "claims.jsonl")
        with open(raw_claims, "w", encoding="utf-8") as fh:
            for row in (
                {"id": "claim:main-normalise", "kind": "calls", "subject": main_id,
                 "object": normalise_id,
                 "evidence": [{"path": entry, "line_start": 7}], "index_hash": digest},
                {"id": "claim:normalise-save", "kind": "calls", "subject": normalise_id,
                 "object": save_id,
                 "evidence": [{"path": transform, "line_start": 7}],
                 "index_hash": digest},
                {"id": "claim:main-save", "kind": "calls", "subject": main_id,
                 "object": save_id,
                 "evidence": [{"path": entry, "line_start": 7}], "index_hash": digest},
                {"id": "claim:entry-imports", "kind": "imports",
                 "subject": "module:%s" % entry, "object": "module:%s" % transform,
                 "evidence": [{"path": entry, "line_start": 3}], "index_hash": digest},
            ):
                fh.write(json.dumps(row, sort_keys=True) + "\n")

        out_dir = os.path.join(tmp, "verified")
        run("verify_doc.py", "--claims", raw_claims, "--index", index_path,
            "--root", root, "--out-dir", out_dir)
        claims_path = os.path.join(out_dir, "claims.verified.jsonl")
        with open(claims_path, encoding="utf-8") as fh:
            verified = {json.loads(line)["id"]: json.loads(line) for line in fh if line.strip()}
        check("the fixture's two real hops verify at their call sites",
              verified["claim:main-normalise"]["status"] == "verified"
              and verified["claim:normalise-save"]["status"] == "verified",
              repr({k: v["status"] for k, v in verified.items()}))
        check("and the plausible hop that is not in the code does not",
              verified["claim:main-save"]["status"] != "verified",
              verified["claim:main-save"]["status"])

        def validate(doc, name, claims=claims_path):
            path = write_json(os.path.join(tmp, name), doc)
            args = [path, "--index", index_path]
            if claims:
                args += ["--claims", claims]
            code, out, err = run("validate_flows.py", *args)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        def step(sid, source, target, claim, line, path):
            return {"id": sid, "from": source, "to": target, "text": "A hop.",
                    "status": "observed", "claim_ids": [claim],
                    "evidence": [{"path": path, "line_start": line}]}

        honest = {
            "flow_version": 1, "index_hash": digest,
            "flows": [{
                "id": "flow:normalise-and-save",
                "name": "Normalising an argument and saving it",
                "status": "observed",
                "trigger": {"kind": "cli", "text": "The console script calls main.",
                            "status": "declared",
                            "evidence": [{"path": "pyproject.toml", "line_start": 7}]},
                "steps": [
                    step("step:1", main_id, normalise_id, "claim:main-normalise", 7, entry),
                    step("step:2", normalise_id, save_id, "claim:normalise-save", 7,
                         transform),
                ],
                "outcome": {"status": "observed", "text": "The length is returned.",
                            "evidence": [{"path": store, "line_start": 5}]},
            }],
        }

        code, report = validate(honest, "honest.json")
        check("a flow whose every hop was read at its call site validates", code == 0,
              repr(report)[:400])
        check("and the flow is accepted whole",
              report["accepted"] == ["flow:normalise-and-save"] and not report["refused"],
              repr(report.get("accepted")))
        check("coverage counts steps and their backing separately",
              report["coverage"]["steps"] == 2
              and report["coverage"]["steps_with_claims"] == 2
              and report["coverage"]["flows_accepted"] == 1,
              repr(report["coverage"]))

        # --- The ways a flow breaks.
        unverified = json.loads(json.dumps(honest))
        unverified["flows"][0]["steps"] = [
            step("step:1", main_id, save_id, "claim:main-save", 7, entry)]
        code, report = validate(unverified, "unverified.json")
        check("a hop citing a call the verifier refused is F006",
              "F006" in codes(report), repr(codes(report)))
        check("and the flow is refused whole, not trimmed",
              report["refused"] == ["flow:normalise-and-save"] and not report["accepted"],
              repr(report))

        borrowed = json.loads(json.dumps(honest))
        borrowed["flows"][0]["steps"][1]["claim_ids"] = ["claim:main-normalise"]
        code, report = validate(borrowed, "borrowed.json")
        check("a hop citing a verified call between two other entities is F006",
              "F006" in codes(report), repr(codes(report)))

        wrong_kind = json.loads(json.dumps(honest))
        wrong_kind["flows"][0]["steps"][0]["claim_ids"] = ["claim:entry-imports"]
        code, report = validate(wrong_kind, "wrongkind.json")
        check("an import edge dressed up as a hop is F006", "F006" in codes(report),
              repr(codes(report)))

        naked = json.loads(json.dumps(honest))
        naked["flows"][0]["steps"][0]["claim_ids"] = []
        code, report = validate(naked, "naked.json")
        check("a hop citing no claim at all is F006", "F006" in codes(report),
              repr(codes(report)))

        ghost = json.loads(json.dumps(honest))
        ghost["flows"][0]["steps"][0]["claim_ids"] = ["claim:does-not-exist"]
        code, report = validate(ghost, "ghost.json")
        check("a hop citing a claim id nothing produced is F006",
              "F006" in codes(report), repr(codes(report)))

        # Both hops are real; the order is a fiction. This is the failure that looks most
        # like a flow, because every individual line of it checks out.
        disjoint = json.loads(json.dumps(honest))
        disjoint["flows"][0]["steps"] = [
            step("step:2", normalise_id, save_id, "claim:normalise-save", 7, transform),
            step("step:1", main_id, normalise_id, "claim:main-normalise", 7, entry),
        ]
        code, report = validate(disjoint, "disjoint.json")
        check("real hops in an impossible order are F004", "F004" in codes(report),
              repr(codes(report)))

        # Continuity used to compare the file paths behind the entities, so two real
        # calls that never meet joined as long as they passed through the same file.
        # This is the shuffled-chain failure wearing a disguise.
        same_file = json.loads(json.dumps(honest))
        same_file["flows"][0]["steps"][1]["from"] = "symbol:%s:other" % transform
        code, report = validate(same_file, "samefile.json")
        check("a hop leaving a different symbol in the same file does not join",
              "F004" in codes(report), repr(codes(report)))

        # A step is a call site, so it always has a line to cite. Without evidence the
        # diagram labels the arrow with the step id where the citation was promised.
        bare = json.loads(json.dumps(honest))
        del bare["flows"][0]["steps"][0]["evidence"]
        code, report = validate(bare, "bare.json")
        check("a step with no evidence is refused", code == 1 and report["refused"],
              "%d %s" % (code, repr(codes(report))))

        # F005 was recorded and then ignored, so the flow still reached `accepted` and
        # the diagram builder drew it as validated.
        twice = json.loads(json.dumps(honest))
        twice["flows"][0]["steps"][1]["id"] = "step:1"
        code, report = validate(twice, "twice.json")
        check("a duplicate step id refuses the flow, not just records a finding",
              not report["accepted"] and report["refused"], repr(report)[:300])

        # claims.verified.jsonl survives between runs. One from another scan names
        # entities that still exist and would go on authorising hops.
        elsewhere = os.path.join(tmp, "elsewhere.jsonl")
        with open(claims_path, encoding="utf-8") as src, \
                open(elsewhere, "w", encoding="utf-8") as dst:
            for line in src:
                if line.strip():
                    row = json.loads(line)
                    row["index_hash"] = "sha256:" + "0" * 64
                    dst.write(json.dumps(row, sort_keys=True) + "\n")
        code, out, err = run("validate_flows.py",
                             write_json(os.path.join(tmp, "otherclaims.json"), honest),
                             "--index", index_path, "--claims", elsewhere)
        check("claims verified against another scan do not authorise a hop",
              code == 2 and "another scan" in err, "%d %r" % (code, err[:200]))

        # The report has to say which *version* of a flow it accepted, or an edit that
        # keeps the id and the index hash rides through into the diagram.
        report_path = os.path.join(tmp, "report.json")
        run("validate_flows.py", write_json(os.path.join(tmp, "forhash.json"), honest),
            "--index", index_path, "--claims", claims_path, "--out", report_path)
        with open(report_path, encoding="utf-8") as fh:
            saved = json.load(fh)
        check("the report records a hash per accepted flow",
              saved["flow_hashes"].get("flow:normalise-and-save", "").startswith("sha256:"),
              repr(saved.get("flow_hashes")))

        unknown_entity = json.loads(json.dumps(honest))
        unknown_entity["flows"][0]["steps"][0]["from"] = "symbol:src/nowhere.py:main"
        code, report = validate(unknown_entity, "unknown.json")
        check("a hop starting in a file the index does not know is F003",
              "F003" in codes(report), repr(codes(report)))

        empty = json.loads(json.dumps(honest))
        empty["flows"][0]["steps"] = []
        code, report = validate(empty, "empty.json")
        check("a flow with no step is F010", "F010" in codes(report), repr(codes(report)))

        duplicate = json.loads(json.dumps(honest))
        duplicate["flows"][0]["steps"][1]["id"] = "step:1"
        code, report = validate(duplicate, "duplicate.json")
        check("a step id used twice is F005", "F005" in codes(report), repr(codes(report)))

        offend = json.loads(json.dumps(honest))
        offend["flows"][0]["steps"][0]["evidence"] = [{"path": entry, "line_start": 9000}]
        code, report = validate(offend, "offend.json")
        check("evidence past the end of the file is F007", "F007" in codes(report),
              repr(codes(report)))

        bad_status = json.loads(json.dumps(honest))
        bad_status["flows"][0]["trigger"]["kind"] = "telepathy"
        code, report = validate(bad_status, "badstatus.json")
        check("a trigger kind the schema does not define is F012",
              "F012" in codes(report), repr(codes(report)))

        # --- Absent is an answer; silence is not.
        silent = {"flow_version": 1, "index_hash": digest, "flows": []}
        code, report = validate(silent, "silent.json")
        check("an empty flows list with no reason is F013", "F013" in codes(report),
              repr(codes(report)))

        stated = {"flow_version": 1, "index_hash": digest, "flows": [],
                  "absent": {"reason": "No call was verified at its call site."}}
        code, report = validate(stated, "stated.json")
        check("an empty flows list with a reason is a complete answer",
              code == 0 and report["absent"] is True, repr(report)[:300])

        both = json.loads(json.dumps(honest))
        both["absent"] = {"reason": "Nothing here."}
        code, report = validate(both, "both.json")
        check("claiming flows and absence at once is F013", "F013" in codes(report),
              repr(codes(report)))

        # --- Inputs that must not pass quietly.
        stale = json.loads(json.dumps(honest))
        stale["index_hash"] = "sha256:" + "0" * 64
        code, report = validate(stale, "stale.json")
        check("a flow written against another scan is an input error", code == 2,
              repr(report)[:200])

        floating = json.loads(json.dumps(honest))
        del floating["index_hash"]
        code, report = validate(floating, "floating.json")
        check("a flow with no index_hash is an input error", code == 2,
              repr(report)[:200])

        code, out, err = run("validate_flows.py",
                             write_json(os.path.join(tmp, "typo.json"), honest),
                             "--index", index_path,
                             "--claims", os.path.join(tmp, "not-here.jsonl"))
        check("a mistyped --claims path is an input error, not silence",
              code == 2 and "no such claims file" in err, "%d %r" % (code, err[:200]))

        code, report = validate(honest, "noclaims.json", claims=None)
        check("with no claims file at all, nothing is accepted",
              not report["accepted"] and report["refused"] == ["flow:normalise-and-save"],
              repr(report)[:300])
        check("and the reason is recorded as advice, not as a defect in the file",
              all(f["severity"] == "advisory" for f in report["findings"]),
              repr(report["findings"])[:300])

        # --- Same input, same report.
        check("the same flow gives the same report",
              validate(honest, "again-a.json") == validate(honest, "again-b.json"))
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
