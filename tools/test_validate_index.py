#!/usr/bin/env python3
"""Behavioural tests for validate_index.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Each case takes a valid index and breaks exactly one thing, so a finding code can be
attributed to the defect that produced it rather than to the shape of the fixture.

    python3 tools/test_validate_index.py
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
SCRIPT = os.path.join(REPO, "shared", "scripts", "validate_index.py")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def run(index_path, root):
    proc = subprocess.run([sys.executable, SCRIPT, index_path, "--root", root, "--json"],
                          capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_stdout": proc.stdout, "_stderr": proc.stderr}


def codes(report):
    return sorted({f["code"] for f in report.get("findings", ())})


def build_fixture(tmp):
    """A small tree plus its freshly scanned index."""
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "api.py", "from pkg.service import handle\n\n\ndef serve():\n    return handle()\n")
    write(root, "pkg/__init__.py")
    write(root, "pkg/service.py", "def handle():\n    return 1\n")

    index_path = os.path.join(tmp, "structure.json")
    proc = subprocess.run(
        [sys.executable, SCANNER, "--root", root, "--out", index_path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    with open(index_path, encoding="utf-8") as fh:
        return root, index_path, json.load(fh)


def main():
    tmp = tempfile.mkdtemp(prefix="validate-index-test-")
    try:
        root, index_path, good = build_fixture(tmp)

        code, report = run(index_path, root)
        check("a freshly scanned index passes", code == 0 and report.get("passed") is True,
              "exit %d, %r" % (code, report))

        broken_dir = os.path.join(tmp, "broken")
        os.makedirs(broken_dir)

        def variant(name, mutate):
            """Write a one-defect copy of the good index and validate it."""
            data = copy.deepcopy(good)
            mutate(data)
            path = os.path.join(broken_dir, name + ".json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            return run(path, root)

        def dup_path(d):
            d["files"].append(copy.deepcopy(d["files"][0]))
        code, report = variant("dup-path", dup_path)
        check("a duplicate file path is E001", code == 1 and "E001" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        def dup_edge(d):
            d["edges"].append(copy.deepcopy(d["edges"][0]))
            d["fan_in"][d["edges"][0]["to"]] = d["fan_in"].get(d["edges"][0]["to"], 0) + 1
        code, report = variant("dup-edge", dup_edge)
        check("a duplicate edge_id is E002", code == 1 and "E002" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        def dangling(d):
            d["edges"][0]["to"] = "pkg/nowhere.py"
            d["fan_in"] = {"pkg/nowhere.py": 1}
        code, report = variant("dangling", dangling)
        check("an edge to an unknown file is E003", code == 1 and "E003" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        def traversal(d):
            d["files"][0]["path"] = "../outside.py"
        code, report = variant("traversal", traversal)
        check("a path leaving the repository is E004", code == 1 and "E004" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        def absolute(d):
            d["files"][0]["path"] = "/etc/passwd"
        code, report = variant("absolute", absolute)
        check("an absolute path is E004", code == 1 and "E004" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        def bad_line(d):
            for record in d["files"]:
                if record["symbols"]:
                    record["symbols"][0]["line"] = record["loc"] + 500
                    return
        code, report = variant("bad-line", bad_line)
        check("a symbol past the end of its file is E005",
              code == 1 and "E005" in codes(report), "exit %d, %r" % (code, codes(report)))

        def no_hash(d):
            d["files"][0].pop("source_hash")
        code, report = variant("no-hash", no_hash)
        check("a record with no source_hash is E006",
              code == 1 and "E006" in codes(report), "exit %d, %r" % (code, codes(report)))

        def wrong_fan_in(d):
            d["fan_in"]["pkg/service.py"] = 99
        code, report = variant("fan-in", wrong_fan_in)
        check("fan_in disagreeing with the edges is E009",
              code == 1 and "E009" in codes(report), "exit %d, %r" % (code, codes(report)))

        def bad_entry(d):
            d["entry_points"] = [{"path": "nope.py", "reason": "main_guard"}]
        code, report = variant("entry", bad_entry)
        check("an entry point outside the index is E010",
              code == 1 and "E010" in codes(report), "exit %d, %r" % (code, codes(report)))

        # Staleness is the reason the hash is recorded at all: editing the tree after a
        # scan must be caught, because every downstream citation is now off by an
        # unknown amount.
        write(root, "pkg/service.py", "def handle():\n    return 2\n")
        code, report = run(index_path, root)
        check("editing a scanned file is E007", code == 1 and "E007" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        os.remove(os.path.join(root, "pkg/service.py"))
        code, report = run(index_path, root)
        check("deleting a scanned file is E008", code == 1 and "E008" in codes(report),
              "exit %d, %r" % (code, codes(report)))

        # Configuration problems are exit 2 and must never be reported as findings --
        # a caller branches on the difference between "the index is wrong" and "you
        # gave me the wrong thing".
        stale_schema = os.path.join(broken_dir, "v1.json")
        data = copy.deepcopy(good)
        data["schema_version"] = 1
        with open(stale_schema, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, _ = run(stale_schema, root)
        check("an unsupported schema_version exits 2", code == 2, "got exit %d" % code)

        no_schema = os.path.join(broken_dir, "none.json")
        data = copy.deepcopy(good)
        data.pop("schema_version")
        with open(no_schema, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, _ = run(no_schema, root)
        check("an index with no schema_version exits 2", code == 2, "got exit %d" % code)

        code, _ = run(os.path.join(tmp, "absent.json"), root)
        check("a missing index exits 2", code == 2, "got exit %d" % code)

        garbage = os.path.join(broken_dir, "garbage.json")
        write(broken_dir, "garbage.json", "{not json")
        code, _ = run(garbage, root)
        check("unparseable JSON exits 2", code == 2, "got exit %d" % code)
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
