#!/usr/bin/env python3
"""The vertical slice, run end to end: repository in, rendered document out.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The per-script tests each prove one component. This proves they compose: that the ids
one writes are the ids the next reads, that a claim verified in step 4 is still citable
in step 6, and that running the whole thing twice on an unchanged tree produces the same
bytes. A pipeline can pass every unit test and still not join up.

The fixture is built in a temp directory rather than under fixtures/, because everything
in fixtures/ is deliberately defective by that directory's own rule, and this one has to
be correct.

    python3 tools/test_pipeline_end_to_end.py
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


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def script(name, *args):
    return [sys.executable, os.path.join(SCRIPTS, name)] + list(args)


def run(argv, cwd):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


# The import on line 2 is `from store.index import ...`, not `from store import index`:
# the scanner resolves the latter to the package's __init__.py and does not also record
# an edge to the submodule, so the fixture would be exercising that gap rather than the
# pipeline. Worth fixing in the scanner; not by weakening this test.
#
#  1 from store.records import Record
#  2 from store.index import lookup
#  3 import logging
#  4 (blank)
#  5 (blank)
#  6 class Order(Record):
#  7     def total(self):
#  8         return lookup(self.key)
#  9 (blank)
# 10 (blank)
# 11 def main():
# 12     return Order()
# 13 (blank)
# 14 (blank)
# 15 if __name__ == "__main__":
# 16     main()
APP = '''\
from store.records import Record
from store.index import lookup
import logging


class Order(Record):
    def total(self):
        return lookup(self.key)


def main():
    return Order()


if __name__ == "__main__":
    main()
'''


def build_repo(root):
    write(root, "app.py", APP)
    write(root, "store/__init__.py")
    write(root, "store/records.py", "class Record:\n    key = 0\n")
    write(root, "store/index.py", "def lookup(key):\n    return key\n")


CLAIMS = [
    {"id": "claim:app-imports-records", "kind": "imports", "subject": "module:app.py",
     "object": "module:store/records.py",
     "evidence": [{"path": "app.py", "line_start": 1}]},
    {"id": "claim:app-imports-index", "kind": "imports", "subject": "module:app.py",
     "object": "module:store/index.py",
     "evidence": [{"path": "app.py", "line_start": 2}]},
    {"id": "claim:order-inherits-record", "kind": "inherits", "subject": "class:app.py:Order",
     "object": "class:store/records.py:Record",
     "evidence": [{"path": "app.py", "line_start": 6}]},
    {"id": "claim:order-has-total", "kind": "contains", "subject": "class:app.py:Order",
     "object": "method:app.py:Order.total",
     "evidence": [{"path": "app.py", "line_start": 7}]},
    {"id": "claim:app-calls-lookup", "kind": "calls", "subject": "module:app.py",
     "object": "symbol:store/index.py:lookup",
     "evidence": [{"path": "app.py", "line_start": 8}]},
    {"id": "claim:app-role", "kind": "responsibility", "subject": "module:app.py",
     "object": None, "evidence": []},
    {"id": "claim:index-role", "kind": "responsibility", "subject": "module:store/index.py",
     "object": None, "evidence": []},
]

FRAGMENTS = [
    {"fragment_id": "fragment:app.py", "source": "app.py",
     "role": "Entry module: defines Order on the shared Record base and resolves keys "
             "through the store index.",
     "claim_ids": ["claim:app-imports-records", "claim:app-imports-index",
                   "claim:order-inherits-record", "claim:order-has-total",
                   "claim:app-calls-lookup", "claim:app-role"],
     "status": "candidate"},
    {"fragment_id": "fragment:store/index.py", "source": "store/index.py",
     "role": "Resolves a key to a record. The only lookup path in the package.",
     "claim_ids": ["claim:index-role"], "status": "candidate"},
]


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def pipeline(root, out="docs"):
    """Run every stage in order. Returns [(stage, code, output)]."""
    steps = [
        ("scan", script("scan_repo.py", "--root", ".", "--out",
                        ".docs-build/structure.json", "--detail")),
        ("validate-index", script("validate_index.py", ".docs-build/structure.json",
                                  "--root", ".")),
        ("annotate", script("annotate_import_usage.py", ".docs-build/structure.json",
                            "--root", ".", "--policy", "optional")),
        ("packet", script("query_graph.py", "--index", ".docs-build/structure.json",
                          "--root", ".", "--packet", "app.py")),
        ("verify", script("verify_doc.py", "--claims", ".docs-build/claims.jsonl",
                          "--fragments", ".docs-build/fragments.jsonl",
                          "--index", ".docs-build/structure.json", "--root", ".",
                          "--out-dir", ".docs-build")),
        ("model", script("build_document_model.py", "--index", ".docs-build/structure.json",
                         "--claims", ".docs-build/claims.verified.jsonl",
                         "--fragments", ".docs-build/fragments.verified.jsonl",
                         "--preset", "onboarding", "--out", ".docs-build/doc.json")),
        ("render", script("render_docs.py", "--doc", ".docs-build/doc.json",
                          "--out", out, "--check")),
    ]
    results = []
    for name, argv in steps:
        code, output = run(argv, root)
        results.append((name, code, output))
        if code not in (0,):
            break
    return results


def main():
    tmp = tempfile.mkdtemp(prefix="pipeline-e2e-test-")
    try:
        root = os.path.join(tmp, "lib")
        os.makedirs(os.path.join(root, ".docs-build"))
        build_repo(root)
        write_rows(os.path.join(root, ".docs-build", "claims.jsonl"), CLAIMS)
        write_rows(os.path.join(root, ".docs-build", "fragments.jsonl"), FRAGMENTS)

        results = pipeline(root)
        for name, code, output in results:
            check("%s exits 0" % name, code == 0, output.strip()[:400])
        if any(code != 0 for _, code, _ in results):
            return 1

        # Every claim in the fixture is true, so none may come back unresolved.
        with open(os.path.join(root, ".docs-build", "claims.verified.jsonl"),
                  encoding="utf-8") as fh:
            statuses = {}
            for line in fh:
                row = json.loads(line)
                statuses[row["id"]] = row["status"]
        check("every structural claim verified",
              all(statuses[c] == "verified" for c in statuses
                  if not c.endswith("-role")), "%r" % statuses)
        check("the call claim survived the AST check",
              statuses.get("claim:app-calls-lookup") == "verified", "%r" % statuses)
        check("the inheritance claim resolved across files",
              statuses.get("claim:order-inherits-record") == "verified", "%r" % statuses)
        check("responsibilities are inferences, not facts",
              statuses.get("claim:app-role") == "supported_inference", "%r" % statuses)

        with open(os.path.join(root, ".docs-build", "findings.jsonl"),
                  encoding="utf-8") as fh:
            findings = [json.loads(l) for l in fh if l.strip()]
        check("a correct fixture produces no findings", findings == [], "%r" % findings)

        docs = os.path.join(root, "docs")
        pages = sorted(n for n in os.listdir(docs) if n.endswith(".rst"))
        check("the document has an index and every preset page",
              pages == ["architecture.rst", "entry-points.rst", "index.rst",
                        "limitations.rst", "modules.rst", "overview.rst"], "%r" % pages)

        text = {}
        for name in pages:
            with open(os.path.join(docs, name), encoding="utf-8") as fh:
                text[name] = fh.read()

        check("the entry point reached the document",
              "app.py" in text["entry-points.rst"], text["entry-points.rst"])
        check("both module descriptions reached the document",
              "Entry module" in text["modules.rst"]
              and "Resolves a key" in text["modules.rst"], text["modules.rst"])
        check("a cross-directory dependency is cited with its line",
              "app.py:1" in text["architecture.rst"]
              or "app.py:2" in text["architecture.rst"], text["architecture.rst"])
        check("coverage is stated from the scan, not asserted",
              "files scanned" in text["limitations.rst"], text["limitations.rst"])
        check("the unused-import caveat is present and hedged",
              "logging" not in text["limitations.rst"]
              and "not evidence" in text["limitations.rst"], text["limitations.rst"])

        # `.docs-build/` is the only place intermediates may land.
        stray = [n for n in os.listdir(root)
                 if n not in ("app.py", "store", "docs", ".docs-build")]
        check("nothing was written outside .docs-build/ and docs/", stray == [],
              "%r" % stray)
        check("the scanned repository was not modified",
              open(os.path.join(root, "app.py"), encoding="utf-8").read() == APP)
        check("no conf.py was created", not os.path.isfile(os.path.join(docs, "conf.py")))

        # Determinism across the whole pipeline, not just one stage.
        second = os.path.join(tmp, "lib2")
        os.makedirs(os.path.join(second, ".docs-build"))
        build_repo(second)
        write_rows(os.path.join(second, ".docs-build", "claims.jsonl"), CLAIMS)
        write_rows(os.path.join(second, ".docs-build", "fragments.jsonl"), FRAGMENTS)
        pipeline(second)
        same = all(
            open(os.path.join(docs, n), encoding="utf-8").read()
            == open(os.path.join(second, "docs", n), encoding="utf-8").read()
            for n in pages)
        check("two runs over identical trees render identical pages", same)

        # And the failure path: one false claim must stop the document, not colour it.
        third = os.path.join(tmp, "lib3")
        os.makedirs(os.path.join(third, ".docs-build"))
        build_repo(third)
        false_claim = dict(CLAIMS[0], id="claim:false",
                           object="module:store/__init__.py")
        write_rows(os.path.join(third, ".docs-build", "claims.jsonl"),
                   CLAIMS + [false_claim])
        write_rows(os.path.join(third, ".docs-build", "fragments.jsonl"), FRAGMENTS)
        results = pipeline(third)
        by_stage = {name: (code, output) for name, code, output in results}
        check("verification reports the false claim",
              by_stage["verify"][0] == 1 and "claim:false" in by_stage["verify"][1],
              "%r" % (by_stage.get("verify"),))
        check("the pipeline stops before rendering", "render" not in by_stage,
              "%r" % sorted(by_stage))
        check("no document was written from a rejected claim",
              not os.path.isdir(os.path.join(third, "docs")))
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
