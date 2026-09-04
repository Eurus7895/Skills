#!/usr/bin/env python3
"""Behavioural tests for generated sequence diagrams and their validator.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

A sequence diagram is the most persuasive artifact this pipeline produces: a reader
believes an arrow they would have questioned as a sentence. That makes the gap between
"generated from verified calls" and "a text file somebody can edit" the thing worth
testing. Most of what follows edits a generated `.puml` the way a person would -- adding
an arrow, retitling a note, swapping two messages -- and asks whether the validator still
passes it.

    python3 tools/test_flow_diagrams.py
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


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def rewrite(path, old, new):
    text = read(path)
    assert old in text, "fixture text not found: %r" % old
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new, 1))


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())})


def main():
    tmp = tempfile.mkdtemp(prefix="flow-diagram-test-")
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

        raw_claims = os.path.join(tmp, "claims.jsonl")
        with open(raw_claims, "w", encoding="utf-8") as fh:
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
        verified_dir = os.path.join(tmp, "verified")
        run("verify_doc.py", "--claims", raw_claims, "--index", index_path,
            "--root", root, "--out-dir", verified_dir)
        claims_path = os.path.join(verified_dir, "claims.verified.jsonl")

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
                     "text": "main normalises its argument.", "status": "observed",
                     "claim_ids": ["claim:a"],
                     "evidence": [{"path": entry, "line_start": 7}]},
                    {"id": "step:2", "from": normalise_id, "to": save_id,
                     "text": "normalise saves the trimmed value.", "status": "observed",
                     "claim_ids": ["claim:b"],
                     "evidence": [{"path": transform, "line_start": 7}]},
                ],
                "outcome": {"status": "observed", "text": "The length is returned.",
                            "evidence": [{"path": store, "line_start": 5}]},
                "unresolved": [{"after": "step:2",
                                "reason": "Nothing calls main inside the repository."}],
            }],
        }
        flows_path = write_json(os.path.join(tmp, "flow-analysis.json"), flow_doc)
        report_path = os.path.join(tmp, "flow-report.json")
        code, out, err = run("validate_flows.py", flows_path, "--index", index_path,
                             "--claims", claims_path, "--out", report_path)
        check("the flow behind the diagram validates first", code == 0, err[:200])

        diagrams = os.path.join(tmp, "diagrams")
        code, out, err = run("build_flow_diagrams.py", "--flows", flows_path,
                             "--report", report_path, "--out", diagrams)
        check("a diagram is generated for the accepted flow", code == 0, err[:200])
        puml = os.path.join(diagrams, "flow-normalise.puml")
        check("and the file is named after the flow", os.path.isfile(puml),
              repr(os.listdir(diagrams)))

        source = read(puml)
        check("every arrow is labelled with the line the call was read at",
              "%s:7" % entry in source and "%s:7" % transform in source,
              source)

        def validate(directory=diagrams, flows=flows_path):
            code, out, err = run("validate_flow_diagrams.py", directory, "--flows", flows)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        code, report = validate()
        check("the generated diagram validates against its flow", code == 0,
              repr(report)[:400])

        # --- Determinism, before anything is edited.
        again = os.path.join(tmp, "diagrams-again")
        run("build_flow_diagrams.py", "--flows", flows_path, "--report", report_path,
            "--out", again)
        check("the same flow gives the same diagram",
              read(os.path.join(again, "flow-normalise.puml")) == source)

        # --- Editing the drawing by hand.
        def clone(name):
            copy = os.path.join(tmp, name)
            shutil.copytree(diagrams, copy)
            return copy, os.path.join(copy, "flow-normalise.puml")

        copy, path = clone("extra-arrow")
        aliases = [line.split(" as ")[1] for line in source.splitlines()
                   if line.startswith("participant ")]
        rewrite(path, "@enduml", "%s -> %s : src/pipeline/entry.py:7\n@enduml"
                % (aliases[0], aliases[2]))
        code, report = validate(copy)
        check("an arrow added by hand is caught even though the metadata is untouched",
              "G005" in codes(report), repr(codes(report)))

        copy, path = clone("extra-participant")
        rewrite(path, "@enduml", 'participant "ghost" as p_ghost_0000000000\n@enduml')
        code, report = validate(copy)
        check("a lifeline added by hand is caught", "G005" in codes(report),
              repr(codes(report)))

        copy, path = clone("relabelled")
        rewrite(path, "%s:7" % entry, "src/pipeline/entry.py:99")
        code, report = validate(copy)
        check("an arrow relabelled to cite another line is caught",
              "G005" in codes(report), repr(codes(report)))

        copy, path = clone("renoted")
        rewrite(path, "The console script calls main.", "Anyone may call main.")
        code, report = validate(copy)
        check("a note rewritten to say something the flow does not is caught",
              "G005" in codes(report) or "G001" in codes(report), repr(codes(report)))

        copy, path = clone("odd-form")
        rewrite(path, "@enduml", "Alice -> Bob : hello\n@enduml")
        code, report = validate(copy)
        check("a line outside the generated form is reported, not ignored",
              "G006" in codes(report), repr(codes(report)))

        # A directive that is neither participant-, note- nor arrow-shaped used to be
        # ignored outright, so anything a reader can see could be added by hand.
        copy, path = clone("titled")
        rewrite(path, "@enduml", "title Verified end to end\n@enduml")
        code, report = validate(copy)
        check("a title added by hand is caught", "G006" in codes(report),
              repr(codes(report)))

        # Deleting a note *and* its metadata left two empty lists agreeing, so the
        # trigger -- the one thing saying what starts the flow -- could be removed.
        copy, path = clone("noteless")
        text = read(path)
        keep = [ln for ln in text.splitlines()
                if "The console script calls main." not in ln]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(keep) + "\n")
        code, report = validate(copy)
        check("removing a note and its metadata together is still caught",
              "G001" in codes(report), repr(codes(report)))

        # The alias is what the checks matched on; the label is what a reader reads.
        copy, path = clone("relabelled-participant")
        rewrite(path, 'participant "entry.main"', 'participant "Trusted gateway"')
        code, report = validate(copy)
        check("a lifeline retitled by hand is caught",
              "G003" in codes(report) or "G005" in codes(report), repr(codes(report)))

        # --- The manifest has to account for every flow.
        copy, _ = clone("dropped-view")
        manifest_path = os.path.join(copy, "flow-diagram-manifest.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["views"] = []
        write_json(manifest_path, manifest)
        code, report = validate(copy)
        check("a flow the manifest neither draws nor skips is caught",
              "G007" in codes(report), repr(codes(report)))

        copy, _ = clone("stray-puml")
        shutil.copy(os.path.join(copy, "flow-normalise.puml"),
                    os.path.join(copy, "flow-extra.puml"))
        code, report = validate(copy)
        check("a .puml the manifest does not name is caught",
              "G007" in codes(report), repr(codes(report)))

        # --- Editing the flow after the diagram was drawn.
        moved = json.loads(json.dumps(flow_doc))
        moved["flows"][0]["steps"][0]["text"] = "Something else entirely."
        moved_path = write_json(os.path.join(tmp, "moved.json"), moved)
        code, report = validate(flows=moved_path)
        check("a flow edited after the diagram was drawn is G002",
              "G002" in codes(report), repr(codes(report)))

        swapped = json.loads(json.dumps(flow_doc))
        swapped["flows"][0]["steps"].reverse()
        swapped_path = write_json(os.path.join(tmp, "swapped.json"), swapped)
        code, report = validate(flows=swapped_path)
        check("the same two arrows in the other order is another flow",
              "G001" in codes(report), repr(codes(report)))

        # --- A refused flow is not drawn.
        broken = json.loads(json.dumps(flow_doc))
        broken["flows"][0]["steps"][1]["claim_ids"] = ["claim:a"]
        broken_path = write_json(os.path.join(tmp, "broken.json"), broken)
        broken_report = os.path.join(tmp, "broken-report.json")
        run("validate_flows.py", broken_path, "--index", index_path,
            "--claims", claims_path, "--out", broken_report)
        refused_dir = os.path.join(tmp, "refused")
        code, out, err = run("build_flow_diagrams.py", "--flows", broken_path,
                             "--report", broken_report, "--out", refused_dir)
        check("a flow the validator refused is skipped, not drawn",
              code == 1 and not [f for f in os.listdir(refused_dir)
                                 if f.endswith(".puml")],
              "%d %r" % (code, os.listdir(refused_dir)))
        with open(os.path.join(refused_dir, "flow-diagram-manifest.json"),
                  encoding="utf-8") as fh:
            check("and the manifest records which flow was skipped",
                  json.load(fh)["skipped"] == ["flow:normalise"])

        # The report used to carry only an index hash and the accepted ids, neither of
        # which changes when a validated flow is edited in place. The builder drew the
        # edited steps, marked the manifest `validated`, and the diagram validator agreed
        # because it compared the drawing against the same edited flow.
        edited = json.loads(json.dumps(flow_doc))
        edited["flows"][0]["steps"][1]["text"] = "normalise writes to the audit log."
        edited_path = write_json(os.path.join(tmp, "edited.json"), edited)
        after = os.path.join(tmp, "after-edit")
        code, out, err = run("build_flow_diagrams.py", "--flows", edited_path,
                             "--report", report_path, "--out", after)
        check("a flow edited after validation is not drawn under the old report",
              code == 2 and "edited after the report" in err,
              "%d %r" % (code, err[:200]))

        # --- Drawn with nothing vouching for it.
        unchecked = os.path.join(tmp, "unchecked")
        run("build_flow_diagrams.py", "--flows", flows_path, "--out", unchecked)
        code, report = validate(unchecked)
        check("a diagram built without a flow report never passes silently",
              "G007" in codes(report), repr(codes(report)))

        mismatched = write_json(os.path.join(tmp, "other-scan.json"),
                                dict(flow_doc, index_hash="sha256:" + "0" * 64))
        code, report = validate(flows=mismatched)
        check("a manifest and a flow analysis from different scans is an input error",
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
