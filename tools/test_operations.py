#!/usr/bin/env python3
"""Behavioural tests for operations-analysis.json.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The operations page is the one a reader executes. A wrong sentence about architecture
costs an afternoon; a wrong command costs the afternoon and leaves a mess behind. It is
also the easiest page to fill from memory, because a plausible command is indistinguishable
from a real one without going and looking: `pytest -q` where the workflow says
`python3 -m pytest` runs, does the same job, and is still not what this repository does.

So most of these tests are about the literal check -- the command text has to be in the
lines it cites -- and about the two ways that check can be wrong to apply: the file moved
on since the scan, or there was no citation to begin with.

    python3 tools/test_operations.py
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
    tmp = tempfile.mkdtemp(prefix="operations-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        index_path = os.path.join(tmp, "structure.json")
        run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
        digest = index["index_hash"]

        workflow = ".github/workflows/ci.yml"
        packaging = "pyproject.toml"

        def validate(doc, name, repo_root=root):
            path = write_json(os.path.join(tmp, name), doc)
            code, out, err = run("validate_operations.py", path, "--index", index_path,
                                 "--root", repo_root)
            try:
                return code, json.loads(out)
            except ValueError:
                return code, {"_output": out + err}

        honest = {
            "operations_version": 1, "index_hash": digest,
            "procedures": [{
                "id": "op:test", "kind": "test", "name": "Running the tests",
                "status": "declared",
                "steps": [{
                    "text": "CI runs the test suite on every push.",
                    "status": "declared", "command": "python3 -m pytest",
                    "evidence": [{"path": workflow, "line_start": 8}],
                }],
            }],
            "requirements": [{
                "id": "req:python", "name": "Python", "value": ">=3.9",
                "status": "declared",
                "evidence": [{"path": packaging, "line_start": 4}],
            }],
        }

        code, report = validate(honest, "honest.json")
        check("a procedure quoting what the file really says validates", code == 0,
              repr(report)[:400])
        check("and the report says how much of it was found rather than remembered",
              report["coverage"]["commands"] == 1
              and report["coverage"]["commands_quoted"] == 1
              and report["coverage"]["kinds"] == ["test"],
              repr(report["coverage"]))

        # --- The literal check.
        plausible = json.loads(json.dumps(honest))
        plausible["procedures"][0]["steps"][0]["command"] = "pytest -q"
        code, report = validate(plausible, "plausible.json")
        check("a command that works but is not the one in the file is O006",
              "O006" in codes(report), repr(codes(report)))
        check("and the finding quotes what was claimed",
              any("pytest -q" in f["message"] for f in report["findings"]),
              repr(report["findings"])[:300])

        misplaced = json.loads(json.dumps(honest))
        misplaced["procedures"][0]["steps"][0]["evidence"] = [
            {"path": workflow, "line_start": 1}]
        code, report = validate(misplaced, "misplaced.json")
        check("the right command cited at the wrong line is O006",
              "O006" in codes(report), repr(codes(report)))

        ranged = json.loads(json.dumps(honest))
        ranged["procedures"][0]["steps"][0]["evidence"] = [
            {"path": workflow, "line_start": 6, "line_end": 8}]
        code, report = validate(ranged, "ranged.json")
        check("a range that contains the command is enough", code == 0,
              repr(codes(report)))

        uncited = json.loads(json.dumps(honest))
        uncited["procedures"][0]["steps"][0]["evidence"] = []
        code, report = validate(uncited, "uncited.json")
        check("a command with nothing to check it against is refused, not assumed",
              "O006" in codes(report) or "O011" in codes(report), repr(codes(report)))

        wrong_value = json.loads(json.dumps(honest))
        wrong_value["requirements"][0]["value"] = ">=3.11"
        code, report = validate(wrong_value, "wrongvalue.json")
        check("a requirement value the file does not state is O006",
              "O006" in codes(report), repr(codes(report)))

        # --- Stale is not the same as wrong.
        moved = os.path.join(tmp, "moved")
        shutil.copytree(root, moved)
        with open(os.path.join(moved, workflow), "a", encoding="utf-8") as fh:
            fh.write("      - run: echo done\n")
        code, report = validate(honest, "moved.json", repo_root=moved)
        check("a file that changed since the scan is O008, not a false O006",
              "O008" in codes(report) and "O006" not in codes(report),
              repr(codes(report)))

        # --- Prose needs no command, and unknown needs no citation.
        prose = {
            "operations_version": 1, "index_hash": digest,
            "procedures": [{
                "id": "op:deploy", "kind": "deploy", "name": "Deploying",
                "status": "unknown",
                "steps": [{"text": "The repository does not say how this is deployed.",
                           "status": "unknown"}],
            }],
        }
        code, report = validate(prose, "prose.json")
        check("a step the repository never states needs nothing to cite", code == 0,
              repr(codes(report)))

        silent_step = json.loads(json.dumps(prose))
        silent_step["procedures"][0]["steps"][0]["status"] = "declared"
        code, report = validate(silent_step, "silentstep.json")
        check("but a declared step with no evidence is O011",
              "O011" in codes(report), repr(codes(report)))

        # --- Schema.
        unknown_kind = json.loads(json.dumps(honest))
        unknown_kind["procedures"][0]["kind"] = "vibes"
        code, report = validate(unknown_kind, "unknownkind.json")
        check("a procedure kind the schema does not define is O012",
              "O012" in codes(report), repr(codes(report)))

        stepless = json.loads(json.dumps(honest))
        stepless["procedures"][0]["steps"] = []
        code, report = validate(stepless, "stepless.json")
        check("a procedure with no step is O010", "O010" in codes(report),
              repr(codes(report)))

        duplicate = json.loads(json.dumps(honest))
        duplicate["requirements"][0]["id"] = "op:test"
        code, report = validate(duplicate, "duplicate.json")
        check("an id used twice is O005", "O005" in codes(report), repr(codes(report)))

        ghost = json.loads(json.dumps(honest))
        ghost["procedures"][0]["steps"][0]["evidence"] = [
            {"path": "Makefile", "line_start": 1}]
        code, report = validate(ghost, "ghost.json")
        check("evidence in a file the index does not hold is O003",
              "O003" in codes(report), repr(codes(report)))

        offend = json.loads(json.dumps(honest))
        offend["procedures"][0]["steps"][0]["evidence"] = [
            {"path": workflow, "line_start": 900}]
        code, report = validate(offend, "offend.json")
        check("evidence past the end of the file is O007", "O007" in codes(report),
              repr(codes(report)))

        # --- Absence is an answer; silence is not.
        empty = {"operations_version": 1, "index_hash": digest, "procedures": []}
        code, report = validate(empty, "empty.json")
        check("nothing said and no reason given is O013", "O013" in codes(report),
              repr(codes(report)))

        stated = {"operations_version": 1, "index_hash": digest, "procedures": [],
                  "absent": {"reason": "No build, test or deploy instruction was found."}}
        code, report = validate(stated, "stated.json")
        check("nothing said with a reason is a complete answer",
              code == 0 and report["absent"] is True, repr(report)[:300])

        both = json.loads(json.dumps(honest))
        both["absent"] = {"reason": "Nothing here."}
        code, report = validate(both, "both.json")
        check("claiming operations and absence at once is O013",
              "O013" in codes(report), repr(codes(report)))

        stale = json.loads(json.dumps(honest))
        stale["index_hash"] = "sha256:" + "0" * 64
        code, report = validate(stale, "staleindex.json")
        check("an analysis written against another scan is an input error", code == 2,
              repr(report)[:200])

        floating = json.loads(json.dumps(honest))
        del floating["index_hash"]
        code, report = validate(floating, "floating.json")
        check("an analysis with no index_hash is an input error", code == 2,
              repr(report)[:200])

        # --- Same input, same report.
        check("the same analysis gives the same report",
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
