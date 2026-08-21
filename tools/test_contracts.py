#!/usr/bin/env python3
"""Check the committed contract fixtures against the scripts that own them.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The other test files build their inputs in a temp directory, which proves the scripts
agree with themselves today. These fixtures are checked in, so they also catch the case
those tests cannot: a schema that drifts. If a change makes
`tests/contracts/doc-v1-minimal.json` stop loading, that is a breaking change to a
published contract, and it should take a deliberate act to update the fixture rather
than happening quietly inside a refactor.

Each file's name states what it is for, and this runner holds the scripts to it: the
`-valid` ones must be accepted, the `-invalid`/`-dangling`/`unsupported-` ones must be
refused with the documented exit code.

    python3 tools/test_contracts.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
CONTRACTS = os.path.join(REPO, "tests", "contracts")
MINIMAL_REPO = os.path.join(CONTRACTS, "minimal-repo")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def fixture(name):
    return os.path.join(CONTRACTS, name)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    tmp = tempfile.mkdtemp(prefix="contracts-test-")
    try:
        expected = [
            "structure-v2-minimal.json", "context-packet-v1-full.json",
            "fragment-v1-valid.jsonl", "fragment-v1-invalid-reference.jsonl",
            "claims-v1-valid.jsonl", "doc-v1-minimal.json", "doc-v1-full.json",
            "doc-v1-dangling-ref.json", "unsupported-version.json",
        ]
        missing = [n for n in expected if not os.path.isfile(fixture(n))]
        check("every named fixture is present", not missing, "missing %r" % missing)
        if missing:
            return 1

        # -- structure ---------------------------------------------------------
        index = load(fixture("structure-v2-minimal.json"))
        check("the index fixture declares the schema version it was written for",
              index["schema_version"] == 2, "%r" % index.get("schema_version"))
        check("the committed fixture carries no absolute path from a build machine",
              index["source"]["root"] == "." and index["root"] == ".",
              "%r" % index.get("source"))

        code, output = run("validate_index.py", fixture("structure-v2-minimal.json"),
                           "--root", MINIMAL_REPO)
        check("the index fixture still describes the repository beside it",
              code == 0, output)

        # -- context packet ----------------------------------------------------
        packet = load(fixture("context-packet-v1-full.json"))
        check("the packet fixture declares its version", packet["packet_version"] == 1)
        for field in ("packet_id", "task", "scope", "context_manifest",
                      "source_revision", "import_usage_coverage"):
            check("the packet fixture carries %s" % field, field in packet)
        check("the packet manifest names both what is in and what is out",
              "included" in packet["context_manifest"]
              and "omitted" in packet["context_manifest"])

        code, fresh = run("query_graph.py", "--index",
                          fixture("structure-v2-minimal.json"), "--root", MINIMAL_REPO,
                          "--packet", "app.py")
        check("regenerating the packet reproduces the fixture", code == 0
              and json.loads(fresh) == packet,
              "the packet contract changed; update the fixture deliberately")

        # -- fragments and claims ----------------------------------------------
        out_dir = os.path.join(tmp, "verified")
        code, output = run("verify_doc.py",
                           "--claims", fixture("claims-v1-valid.jsonl"),
                           "--fragments", fixture("fragment-v1-valid.jsonl"),
                           "--index", fixture("structure-v2-minimal.json"),
                           "--root", MINIMAL_REPO, "--out-dir", out_dir)
        check("the valid fragment and claim fixtures verify cleanly", code == 0, output)

        code, output = run("verify_doc.py",
                           "--claims", fixture("claims-v1-valid.jsonl"),
                           "--fragments", fixture("fragment-v1-invalid-reference.jsonl"),
                           "--index", fixture("structure-v2-minimal.json"),
                           "--root", MINIMAL_REPO,
                           "--out-dir", os.path.join(tmp, "invalid"))
        check("a fragment naming a claim nobody supplied is caught",
              code == 1 and "V009" in output, output)

        code, output = run("assemble.py", "--schema",
                           "fragment_id:str, source:str, role:str, claim_ids:list, "
                           "status:str",
                           "--input", fixture("fragment-v1-valid.jsonl"))
        check("the fragment fixture matches the schema SKILL.md publishes",
              code == 0, output)

        # -- document model ----------------------------------------------------
        for name in ("doc-v1-minimal.json", "doc-v1-full.json"):
            doc = load(fixture(name))
            check("%s declares its format version" % name, doc["format_version"] == 1)
            code, output = run("render_docs.py", "--doc", fixture(name),
                               "--out", os.path.join(tmp, name.replace(".json", "")))
            check("%s renders" % name, code == 0, output)

        full = load(fixture("doc-v1-full.json"))
        cited = {c for p in full["pages"] for b in p["blocks"]
                 for c in b.get("claim_refs", ())}
        by_id = {c["id"]: c for c in full["claims"]}
        check("no block in the full fixture cites a claim that may not be quoted",
              all(by_id[c]["status"] in ("verified", "supported_inference")
                  for c in cited if c in by_id),
              "%r" % [(c, by_id[c]["status"]) for c in cited if c in by_id])
        check("every mandatory onboarding page is in the full fixture",
              {p["id"] for p in full["pages"]} >= {
                  "overview", "entry-points", "architecture", "flows", "modules",
                  "navigation", "limitations"},
              "%r" % [p["id"] for p in full["pages"]])

        # A ref target that is not among the pages must stop the render, not become a
        # link that 404s for the reader.
        dangling_out = os.path.join(tmp, "dangling")
        code, output = run("render_docs.py", "--doc", fixture("doc-v1-dangling-ref.json"),
                           "--out", dangling_out)
        check("a dangling page reference stops the render", code == 2, output)
        check("and names the page that does not exist", "nowhere" in output, output)
        check("and writes nothing",
              not os.path.isdir(dangling_out) or not os.listdir(dangling_out),
              "%r" % (os.path.isdir(dangling_out) and os.listdir(dangling_out)))

        # -- unsupported versions ----------------------------------------------
        for script, args in (
                ("validate_index.py", [fixture("unsupported-version.json"),
                                       "--root", MINIMAL_REPO]),
                ("query_graph.py", ["--index", fixture("unsupported-version.json"),
                                    "--root", MINIMAL_REPO, "--clusters"]),
                ("annotate_import_usage.py", [fixture("unsupported-version.json"),
                                              "--root", MINIMAL_REPO,
                                              "--policy", "disabled",
                                              "--out", os.path.join(tmp, "x.json")]),
                ("render_docs.py", ["--doc", fixture("unsupported-version.json"),
                                    "--out", os.path.join(tmp, "y")]),
        ):
            code, output = run(script, *args)
            check("%s exits 2 on an unsupported version" % script, code == 2,
                  "exit %d: %s" % (code, output))
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
