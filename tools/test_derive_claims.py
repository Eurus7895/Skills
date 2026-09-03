#!/usr/bin/env python3
"""Behavioural tests for derive_claims.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

There is no judgement in this script, so the tests are about the two things that could
still go wrong: claiming something the index does not support, and claiming it about a
module the run never undertook to describe.

    python3 tools/test_derive_claims.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
DERIVE = os.path.join(SCRIPTS, "derive_claims.py")
FIXTURE = os.path.join(REPO, "tests", "contracts", "layered-repo")

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
    return proc.returncode, proc.stdout + proc.stderr


def rows_of(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    tmp = tempfile.mkdtemp(prefix="derive-claims-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        index_path = os.path.join(tmp, "structure.json")
        run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)

        modules = sorted(r["path"] for r in index["files"] if r.get("symbols"))
        units = os.path.join(tmp, "units.txt")
        with open(units, "w", encoding="utf-8") as fh:
            fh.write("\n".join(modules) + "\n")

        out = os.path.join(tmp, "claims.jsonl")
        code, output = run("derive_claims.py", "--index", index_path,
                           "--units", units, "--out", out)
        check("derivation succeeds", code == 0, output)
        rows = rows_of(out)
        kinds = {}
        for row in rows:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        check("it writes the three kinds the index supports",
              kinds == {"defines": 7, "imports": 5, "inherits": 1}, repr(kinds))
        check("and says out loud that this is not the analysis",
              "module-analysis.jsonl" in output, output)

        # The whole point: these must survive the checker, because if they did not the
        # model would be right to write them itself.
        fragments = os.path.join(tmp, "fragments.jsonl")
        by_module = {}
        for row in rows:
            path = row["subject"].split(":", 2)[1]
            by_module.setdefault(path, []).append(row["id"])
        with open(fragments, "w", encoding="utf-8") as fh:
            for path, ids in sorted(by_module.items()):
                fh.write(json.dumps({
                    "fragment_id": "fragment:%s" % path, "source": path, "role": "r",
                    "claim_ids": sorted(ids), "status": "candidate",
                    "index_hash": index["index_hash"]}, sort_keys=True) + "\n")
        code, output = run("verify_doc.py", "--claims", out, "--fragments", fragments,
                           "--index", index_path, "--root", root,
                           "--out-dir", os.path.join(tmp, "verified"))
        check("every derived claim verifies against the source", code == 0, output)

        # An unresolved base is the one place a derivation could invent a relationship.
        # models.py inherits within its own file; nothing here reaches outside it.
        inherits = [row for row in rows if row["kind"] == "inherits"]
        check("inheritance is only claimed where the base resolved",
              all(row["object"].split(":")[1] in modules for row in inherits),
              repr(inherits))

        # The budget decides who gets claims. A module nobody undertook to describe does
        # not need one per symbol.
        narrow = os.path.join(tmp, "narrow.txt")
        with open(narrow, "w", encoding="utf-8") as fh:
            fh.write("src/app/infra/config.py\n")
        small = os.path.join(tmp, "small.jsonl")
        run("derive_claims.py", "--index", index_path, "--units", narrow, "--out", small)
        check("only modules in the budget get claims",
              {row["subject"] for row in rows_of(small)}
              == {"module:src/app/infra/config.py"},
              repr({row["subject"] for row in rows_of(small)}))

        with open(narrow, "w", encoding="utf-8") as fh:
            fh.write("src/app/nowhere.py\n")
        code, output = run("derive_claims.py", "--index", index_path,
                           "--units", narrow, "--out", os.path.join(tmp, "x.jsonl"))
        check("a budget naming a module the index does not hold is refused",
              code == 2, output)

        again = os.path.join(tmp, "again.jsonl")
        run("derive_claims.py", "--index", index_path, "--units", units, "--out", again)
        with open(out, "rb") as fh:
            first = fh.read()
        with open(again, "rb") as fh:
            check("the same index gives the same bytes", first == fh.read())
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
