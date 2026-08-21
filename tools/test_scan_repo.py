#!/usr/bin/env python3
"""Behavioural tests for scan_repo.py's schema v2 output.

Stdlib only, no test framework -- this repository's scripts must run on a stranger's
machine with no install step, and its own tests should not be the exception.

Covers what a later step depends on and the scanner alone can guarantee: the snapshot
fields, the per-file hash, the import bindings, and stable edge identity. The parsing
itself is covered by the digest a human reads; these are the contract.

    python3 tools/test_scan_repo.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "shared", "scripts", "scan_repo.py")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def scan(root, *args):
    out = os.path.join(root, "structure.json")
    proc = subprocess.run([sys.executable, SCRIPT, "--root", root, "--out", out] + list(args),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return proc.returncode, {"_stderr": proc.stderr}
    with open(out, encoding="utf-8") as fh:
        return 0, json.load(fh)


def tree(tmp, name):
    root = os.path.join(tmp, name)
    os.makedirs(root)
    return root


API = """\
import os
import pkg.helpers as helpers
from pkg.service import handle, retire
from pkg.service import handle


def serve():
    return handle()


if __name__ == "__main__":
    serve()
"""

SERVICE = "def handle():\n    return 1\n\n\ndef retire():\n    return 0\n"


def build_repo(tmp):
    root = tree(tmp, "lib")
    write(root, "api.py", API)
    write(root, "pkg/__init__.py")
    write(root, "pkg/service.py", SERVICE)
    write(root, "pkg/helpers.py", "def helper():\n    return 2\n")
    return root


def main():
    tmp = tempfile.mkdtemp(prefix="scan-repo-test-")
    try:
        root = build_repo(tmp)
        code, data = scan(root)
        check("scan succeeds", code == 0, data.get("_stderr", ""))
        if code != 0:
            return 1

        check("schema_version is 2", data.get("schema_version") == 2,
              "got %r" % data.get("schema_version"))

        source = data.get("source", {})
        check("source names the root", source.get("root") == os.path.realpath(root),
              "got %r" % source.get("root"))
        check("a non-git tree reports no revision and is dirty",
              source.get("revision") is None and source.get("dirty") is True,
              "got %r" % source)

        by_path = {r["path"]: r for r in data["files"]}
        check("every file carries a sha256",
              all(r["source_hash"].startswith("sha256:") for r in data["files"]),
              "got %r" % [r.get("source_hash") for r in data["files"]])

        # The hash must be of the bytes on disk, or a freshness check compares two
        # different things and passes a stale index.
        with open(os.path.join(root, "api.py"), "rb") as fh:
            import hashlib
            want = "sha256:" + hashlib.sha256(fh.read()).hexdigest()
        check("the hash is of the file's bytes", by_path["api.py"]["source_hash"] == want,
              "got %s" % by_path["api.py"]["source_hash"])

        check("a __main__ guard is recorded", by_path["api.py"]["main_guard"] is True)
        check("a module without one is not",
              by_path["pkg/service.py"]["main_guard"] is False)
        check("api.py is an entry point by its guard",
              {"path": "api.py", "reason": "main_guard"} in data["entry_points"],
              "got %r" % data["entry_points"])
        check("an imported module is not an entry point",
              not any(e["path"] == "pkg/service.py" for e in data["entry_points"]))

        # One module imported on several lines stays several entries -- each carries the
        # line it can be cited at -- so gather across them rather than keying by name.
        bindings = {}
        for item in by_path["api.py"]["imports"]:
            bindings.setdefault(item["name"], []).extend(item.get("bindings", ()))
        check("`import os` binds os", bindings.get("os") == ["os"], "got %r" % bindings)
        check("`import pkg.helpers as helpers` binds the alias, not the module",
              bindings.get("pkg.helpers") == ["helpers"], "got %r" % bindings)
        check("`from pkg.service import handle, retire` binds both names",
              sorted(set(bindings.get("pkg.service") or ())) == ["handle", "retire"],
              "got %r" % bindings)

        edges = {(e["from"], e["to"]): e for e in data["edges"]}
        service = edges.get(("api.py", "pkg/service.py"))
        check("two imports of one module still make one edge",
              sum(1 for e in data["edges"]
                  if (e["from"], e["to"]) == ("api.py", "pkg/service.py")) == 1,
              "got %d" % sum(1 for e in data["edges"]
                             if (e["from"], e["to"]) == ("api.py", "pkg/service.py")))
        check("the edge keeps every binding that produced it",
              service and sorted(service.get("bindings", ())) == ["handle", "retire"],
              "got %r" % (service or {}).get("bindings"))
        check("edge_id carries the citation",
              service and service["edge_id"] == "import:api.py:%d:pkg/service.py"
              % service["line"], "got %r" % (service or {}).get("edge_id"))
        check("edge ids are unique",
              len({e["edge_id"] for e in data["edges"]}) == len(data["edges"]))

        coverage = data.get("coverage", {})
        check("coverage counts what was scanned",
              coverage.get("files_scanned") == len(data["files"])
              and coverage.get("files_hashed") == len(data["files"]),
              "got %r" % coverage)

        # A Python file that will not parse must say so as a row, not only in a digest.
        broken = build_repo(os.path.join(tmp, "broken-holder"))
        write(broken, "bad.py", "def oops(:\n")
        code, data = scan(broken)
        codes = [d["code"] for d in data.get("diagnostics", ())]
        check("an unparseable Python file raises D004", "D004" in codes,
              "got %r" % data.get("diagnostics"))

        # Two scans of an unchanged tree must be byte-identical, or nothing downstream
        # can claim determinism.
        first = json.dumps(scan(root)[1], sort_keys=True)
        second = json.dumps(scan(root)[1], sort_keys=True)
        check("rescanning an unchanged tree is deterministic", first == second)

        empty = tree(tmp, "empty")
        write(empty, "README.md", "# nothing here\n")
        code, data = scan(empty)
        check("a tree with no source exits non-zero", code != 0, "got exit %d" % code)
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
