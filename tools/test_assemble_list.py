#!/usr/bin/env python3
"""Behavioural tests for assemble.py's `list` field type.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Scoped to the type added for fragment rows: a fragment names the claims it rests on,
which is a list of ids, and the schema had no way to express that. The rest of the
assembler is unchanged and covered by its own usage.

    python3 tools/test_assemble_list.py
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "shared", "scripts", "assemble.py")

SCHEMA = "fragment_id:str, source:str, role:str, claim_ids:list, status:str"

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(tmp, rows, schema=SCHEMA, units=None, name="run"):
    rows_path = os.path.join(tmp, name + ".jsonl")
    with open(rows_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    out = os.path.join(tmp, name + ".csv")
    args = [sys.executable, SCRIPT, "--schema", schema, "--input", rows_path, "--out", out]
    if units is not None:
        unit_path = os.path.join(tmp, name + "-units.txt")
        with open(unit_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(units) + "\n")
        args += ["--unit-list", unit_path, "--unit-field", "source"]
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr, out


def fragment(source, claim_ids):
    return {"fragment_id": "fragment:" + source, "source": source,
            "role": "Holds a boundary.", "claim_ids": claim_ids, "status": "candidate"}


def main():
    tmp = tempfile.mkdtemp(prefix="assemble-list-test-")
    try:
        code, output, out = run(tmp, [fragment("a.py", ["claim:1", "claim:2"]),
                                      fragment("b.py", ["claim:3"])], name="ok")
        check("rows carrying a list of ids validate", code == 0, output)

        with open(out, encoding="utf-8") as fh:
            written = list(csv.DictReader(fh))
        check("a list cell is written joined, not as a Python repr",
              written[0]["claim_ids"] == "claim:1 claim:2",
              "%r" % written[0]["claim_ids"])

        code, output, _ = run(tmp, [fragment("a.py", [])], name="empty")
        check("an empty list fails a non-nullable list field", code == 1, output)

        code, output, _ = run(tmp, [fragment("a.py", [])],
                              schema=SCHEMA.replace("claim_ids:list", "claim_ids:list?"),
                              name="nullable")
        check("a nullable list field accepts empty", code == 0, output)

        code, output, _ = run(tmp, [fragment("a.py", "claim:1")], name="scalar")
        check("a string where a list belongs fails", code == 1, output)
        check("and the message names the type", "expected list" in output, output)

        # The schema exists to keep nesting out; a list of objects is nesting.
        code, output, _ = run(tmp, [fragment("a.py", [{"id": "claim:1"}])], name="nested")
        check("a list of objects fails", code == 1, output)
        check("and the message says why", "non-empty strings" in output, output)

        code, output, _ = run(tmp, [fragment("a.py", ["claim:1", ""])], name="blank")
        check("a blank element fails", code == 1, output)

        # The coverage gate must keep working with a list field present.
        code, output, _ = run(tmp, [fragment("a.py", ["claim:1"])],
                              units=["a.py", "b.py"], name="coverage")
        check("a missing unit still fails the coverage gate", code == 1, output)
        check("and names the unit that never came back", "b.py" in output, output)

        code, output, _ = run(tmp, [fragment("a.py", ["claim:1"])],
                              schema="claim_ids:listy", name="badtype")
        check("an unknown type is still refused", code != 0, output)
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
