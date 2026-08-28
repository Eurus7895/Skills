#!/usr/bin/env python3
"""Pin what a derived-only documentation run looks like today.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

An agent asked to document a repository can skip the reading and emit every claim
straight out of `structure.json`: `defines` from the symbol table, `imports` from the
edge list. Four of the six claim kinds are verified by looking them up in that same
index, so the round trip is derive-then-check-against-what-you-derived-from, and it is
always green. The document that comes out is `structure.json` in prose.

This file does exactly that, deliberately, and asserts that **nothing notices**. Every
check below is a characterisation of current behaviour, not an endorsement of it: each
one names what will change it. When `quality_docs.py` and `generation-report.json` land
(plan 3, C3), the assertions marked CHANGES AT C3 flip, and this file becomes the
regression test that the shortcut stays visible.

It is written as a passing test rather than a failing one on purpose. A test that is
red until some future commit lands teaches everyone to ignore a red suite.

    python3 tools/test_analysis_depth.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
FIXTURE = os.path.join(REPO, "tests", "contracts", "layered-repo")

# The role an agent taking the shortcut writes: true of every module, therefore about
# none of them. Detector A of plan 3 is what will eventually reject it.
GENERIC_ROLE = "Provides functionality for the application."

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


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def derived_only(index):
    """Claims and fragments an agent can produce without opening a single file.

    Nothing here required reading source: `defines` comes from the symbol table and
    `imports` from the edge list, both already in the index.
    """
    claims, fragments = [], []
    edges_by_source = {}
    for edge in index["edges"]:
        edges_by_source.setdefault(edge["from"], []).append(edge)

    for record in index["files"]:
        path = record["path"]
        if record.get("is_test"):
            continue
        claim_ids = []
        for symbol in record.get("symbols", ()):
            claim_id = "claim:defines:%s:%s" % (path, symbol["name"])
            claims.append({
                "id": claim_id, "kind": "defines",
                "subject": "module:%s" % path,
                "object": "symbol:%s:%s" % (path, symbol["name"]),
                "evidence": [{"path": path, "line_start": symbol["line"],
                              "line_end": symbol["line"]}],
                "index_hash": index["index_hash"]})
            claim_ids.append(claim_id)
        for edge in edges_by_source.get(path, ()):
            claim_id = "claim:imports:%s:%s" % (path, edge["to"])
            claims.append({
                "id": claim_id, "kind": "imports",
                "subject": "module:%s" % path, "object": "module:%s" % edge["to"],
                "evidence": [{"path": path, "line_start": edge["line"],
                              "line_end": edge["line"]}],
                "index_hash": index["index_hash"]})
            claim_ids.append(claim_id)
        if not claim_ids:
            continue
        fragments.append({"fragment_id": "fragment:%s" % path, "source": path,
                          "role": GENERIC_ROLE, "claim_ids": sorted(claim_ids),
                          "status": "candidate", "index_hash": index["index_hash"]})
    return claims, fragments


def main():
    tmp = tempfile.mkdtemp(prefix="analysis-depth-test-")
    try:
        root = os.path.join(tmp, "repo")
        shutil.copytree(FIXTURE, root)
        build = os.path.join(tmp, "build")
        os.makedirs(build)
        index_path = os.path.join(build, "structure.json")

        code, output = run("scan_repo.py", "--root", root, "--out", index_path,
                           "--detail")
        check("the fixture scans", code == 0, output)
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)

        # The fixture is the shape the later commits need: three directories that are
        # nearly the layering, so an architecture synthesis that just renames folders is
        # detectable rather than plausible.
        check("the fixture crosses directory boundaries",
              len({os.path.dirname(e["from"]) for e in index["edges"]}
                  | {os.path.dirname(e["to"]) for e in index["edges"]}) == 3,
              "%r" % [e["from"] + " -> " + e["to"] for e in index["edges"]])
        check("and declares one entry point",
              [e["path"] for e in index["entry_points"]] == ["src/app/api/cli.py"],
              "%r" % index["entry_points"])

        # CHANGES AT C5. README, pyproject.toml and the CI workflow are in the fixture
        # and absent from the index: `scan_repo.py` classes them as non-source. Until
        # that changes, no page about installation, conventions or CI can cite anything.
        indexed = {record["path"] for record in index["files"]}
        check("non-source evidence is not indexed at all",
              not indexed & {"README.md", "pyproject.toml",
                             ".github/workflows/ci.yml"},
              "%r" % sorted(indexed))

        claims_path = os.path.join(build, "claims.jsonl")
        fragments_path = os.path.join(build, "fragments.jsonl")
        claims, fragments = derived_only(index)
        write_rows(claims_path, claims)
        write_rows(fragments_path, fragments)

        code, output = run("verify_doc.py", "--claims", claims_path,
                           "--fragments", fragments_path, "--index", index_path,
                           "--root", root, "--out-dir", build)
        check("a run that read no source verifies cleanly", code == 0, output)

        with open(os.path.join(build, "claims.verified.jsonl"), encoding="utf-8") as fh:
            verified = [json.loads(line) for line in fh if line.strip()]
        statuses = {row["status"] for row in verified}
        check("and every one of its claims comes back verified",
              statuses == {"verified"}, "%r" % sorted(statuses))

        # The heart of it. These claims were derived from the index and checked against
        # the index; the agreement says nothing about the repository.
        check("because the checker and the author read the same file",
              all(row["index_hash"] == index["index_hash"] for row in verified))

        # CHANGES AT C3. Every fragment carries the same sentence, and no stage objects.
        with open(os.path.join(build, "fragments.verified.jsonl"),
                  encoding="utf-8") as fh:
            verified_fragments = [json.loads(line) for line in fh if line.strip()]
        check("one identical role describes every module, unchallenged",
              len({row["role"] for row in verified_fragments}) == 1
              and len(verified_fragments) > 1,
              "%d fragment(s)" % len(verified_fragments))

        doc_path = os.path.join(build, "doc.json")
        code, output = run("build_document_model.py", "--index", index_path,
                           "--claims", os.path.join(build, "claims.verified.jsonl"),
                           "--fragments", os.path.join(build,
                                                       "fragments.verified.jsonl"),
                           "--preset", "onboarding", "--out", doc_path)
        check("the document model builds from it", code == 0, output)

        docs = os.path.join(tmp, "docs")
        code, output = run("render_docs.py", "--doc", doc_path, "--out", docs)
        check("and renders to a full set of pages", code == 0, output)

        # CHANGES AT C3. Nothing produced anywhere states how the document was made.
        produced = ([os.path.join(base, name) for base, _, names in os.walk(build)
                     for name in names]
                    + [os.path.join(base, name) for base, _, names in os.walk(docs)
                       for name in names])
        check("no artifact reports how much of this was analysis",
              not [p for p in produced
                   if os.path.basename(p) == "generation-report.json"],
              "%r" % sorted(os.path.basename(p) for p in produced))
        with open(doc_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        check("and the document model records no analysis mode",
              not [key for key in doc.get("coverage", {}) if "analysis" in key],
              "%r" % sorted(doc.get("coverage", {})))

        # Freshness already works, and plan 3 relies on it rather than rebuilding it:
        # evidence that no longer describes the file is uncheckable, not false.
        moved = os.path.join(root, "src", "app", "core", "service.py")
        with open(moved, encoding="utf-8") as fh:
            body = fh.read()
        with open(moved, "w", encoding="utf-8") as fh:
            fh.write("# a line nobody analysed\n" + body)
        stale = os.path.join(tmp, "stale")
        os.makedirs(stale)
        code, output = run("verify_doc.py", "--claims", claims_path,
                           "--fragments", fragments_path, "--index", index_path,
                           "--root", root, "--out-dir", stale)
        with open(os.path.join(stale, "findings.jsonl"), encoding="utf-8") as fh:
            findings = [json.loads(line) for line in fh if line.strip()]
        check("a source file edited after the scan stops the run",
              code != 0 and any(row["code"] == "V005" for row in findings),
              "exit %d, codes %r" % (code, sorted({r["code"] for r in findings})))
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
