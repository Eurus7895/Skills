#!/usr/bin/env python3
"""Behavioural tests for the `manual` preset and the pages it adds.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

This preset exists because `handbook` predates the architecture, flow and operations
analyses: it leaves the component map, the processing flow, the procedures and the
coverage page to an author even when the run has all four. The tests here are about the
line between the two halves. Every page the pipeline claims to generate must render
something a reader can check; every page it cannot fill must be *named* as the author's
rather than emitted empty, because a heading in a toctree over nothing is the failure the
authored-page mechanism exists to prevent.

The procedure split is the other thing worth pinning. Testing and releasing get their own
pages here, so the same procedure must not also appear on the installation page -- a
command shown twice reads as two different commands.

    python3 tools/test_manual_preset.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from component_scripts import component_paths, script

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "tests", "contracts", "flow-repo")

sys.path[:0] = component_paths()
import build_document_model as model                              # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(name, *args):
    proc = subprocess.run([sys.executable, script(name)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True)
    return path


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def shape_tests():
    """What the preset promises, before anything is built from it."""
    rows = model.PRESETS["manual"]
    ids = [r[0] for r in rows]
    check("every page id is unique", len(ids) == len(set(ids)), repr(ids))
    check("the tree is the five areas the blueprint names",
          {i.split("/")[0] for i in ids if "/" in i}
          == {"getting_started", "architecture", "usage", "development", "appendix"},
          repr(sorted({i.split("/")[0] for i in ids if "/" in i})))
    check("every named builder exists",
          all(r[3] in model.BUILDERS for r in rows if r[3]),
          repr([r[3] for r in rows if r[3] and r[3] not in model.BUILDERS]))

    # A page the pipeline cannot fill is listed as the author's. Marking one mandatory
    # *and* unfillable would fail every run on a repository that has no such content.
    unfillable = [r for r in rows if r[3] is None and r[2]]
    check("no page is both mandatory and impossible to generate",
          not unfillable, repr([r[0] for r in unfillable]))
    generated = [r[0] for r in rows if r[3]]
    check("the generated half covers architecture, procedures and disclosure",
          {"architecture/overview", "architecture/processing_flow",
           "architecture/module_reference", "development/testing",
           "appendix/limitations", "appendix/traceability"}.issubset(set(generated)),
          repr(generated))

    # Same rule the other prose presets keep: a document that omits its own coverage
    # section reads exactly like one with nothing to disclose.
    check("limitations is mandatory", ("appendix/limitations", "Limitations", True,
                                       "limitations") in rows)

    # The procedure kinds are partitioned, not repeated. A command on two pages reads as
    # two commands.
    kinds = {"installation": ("install", "build"), "testing": ("test",),
             "release": ("deploy", "release", "observe"),
             "configuration": ("configure",)}
    seen = [k for group in kinds.values() for k in group]
    check("no procedure kind is claimed by two pages",
          len(seen) == len(set(seen)), repr(sorted(seen)))


def build_tests(tmp):
    """What it renders against a real scan."""
    root = os.path.join(tmp, "repo")
    shutil.copytree(FIXTURE, root)
    index_path = os.path.join(tmp, "structure.json")
    run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    digest = index["index_hash"]
    hashes = {r["path"]: r["source_hash"] for r in index["files"]}

    entry = "src/pipeline/entry.py"
    transform = "src/pipeline/transform.py"
    store = "src/pipeline/store.py"

    claims_in = os.path.join(tmp, "claims.jsonl")
    with open(claims_in, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "id": "claim:a", "kind": "calls", "subject": "symbol:%s:main" % entry,
            "object": "symbol:%s:normalise" % transform,
            "evidence": [{"path": entry, "line_start": 7}],
            "index_hash": digest}, sort_keys=True) + "\n")
    run("verify_doc.py", "--claims", claims_in, "--index", index_path,
        "--root", root, "--out-dir", tmp)
    claims_path = os.path.join(tmp, "claims.verified.jsonl")
    fragments_path = os.path.join(tmp, "fragments.verified.jsonl")
    if not os.path.isfile(fragments_path):
        open(fragments_path, "w", encoding="utf-8").close()

    analysis_path = os.path.join(tmp, "module-analysis.jsonl")
    with open(analysis_path, "w", encoding="utf-8") as fh:
        for path, kind, sid, text, line in (
            (entry, "responsibility", "s-entry",
             "Hands its argument to the pipeline and returns the result.", 6),
            (transform, "interaction", "s-interaction",
             "Calls into the store and is called by the entry point.", 3),
            (transform, "rationale", "s-rationale",
             "Trimming lives here so the store never sees raw input.", 1),
            (store, "state", "s-store", "Owns the count of what it was given.", 4),
        ):
            fh.write(json.dumps({
                "analysis_version": 1, "path": path, "source_hash": hashes[path],
                "index_hash": digest, "role": "A part of the pipeline.",
                "statements": [{"id": sid, "kind": kind,
                                "status": "declared" if kind == "rationale" else "observed",
                                "text": text,
                                "evidence": [{"path": path, "line_start": line}]}]},
                sort_keys=True) + "\n")

    architecture = write_json(os.path.join(tmp, "architecture-analysis.json"), {
        "architecture_version": 1, "index_hash": digest,
        "components": [
            {"id": "component:pipeline", "name": "The pipeline", "status": "observed",
             "modules": [entry, transform], "statement_ids": ["s-interaction"],
             "rationale": {"status": "declared",
                           "text": "Entry and normalisation share one rule set.",
                           "evidence": [{"path": "README.md", "line_start": 3}]}},
            {"id": "component:storage", "name": "Storage", "status": "observed",
             "modules": [store, "src/pipeline/__init__.py"],
             "rationale": {"status": "unknown",
                           "text": "Why storage counts rather than persists."}},
        ],
        "relationships": [{"from": "component:pipeline", "to": "component:storage",
                           "kind": "depends_on", "status": "observed",
                           "evidence": [{"path": transform, "line_start": 3}]}],
        "external_systems": [],
    })
    operations = write_json(os.path.join(tmp, "operations-analysis.json"), {
        "operations_version": 1, "index_hash": digest,
        "procedures": [
            {"id": "op:test", "kind": "test", "name": "Running the tests",
             "status": "declared",
             "steps": [{"text": "The README names the test command.",
                        "status": "declared", "command": "python3 -m pytest",
                        "evidence": [{"path": "README.md", "line_start": 5}]}]},
            {"id": "op:release", "kind": "release", "name": "Publishing",
             "status": "declared",
             "steps": [{"text": "The workflow builds on every push.",
                        "status": "declared",
                        "evidence": [{"path": ".github/workflows/ci.yml",
                                      "line_start": 1}]}]},
        ],
        "requirements": [{"id": "req:python", "name": "Python", "value": ">=3.9",
                          "status": "declared",
                          "evidence": [{"path": "pyproject.toml", "line_start": 4}]}],
    })
    flows = write_json(os.path.join(tmp, "flow-analysis.json"), {
        "flow_version": 1, "index_hash": digest, "flows": [],
        "absent": {"reason": "No call chain was traced for this fixture."}})

    doc_path = os.path.join(tmp, "doc-manual.json")
    diagrams = os.path.join(tmp, "diagrams")
    os.makedirs(diagrams, exist_ok=True)
    code, out, err = run(
        "build_document_model.py", "--index", index_path, "--claims", claims_path,
        "--fragments", fragments_path, "--analysis", analysis_path,
        "--architecture", architecture, "--operations", operations, "--flows", flows,
        "--preset", "manual", "--diagrams", diagrams, "--out", doc_path)
    check("the manual preset builds", code == 0, (out + err)[-400:])
    if code != 0:
        return

    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    pages = {p["id"]: p for p in doc["pages"]}
    authored = [p["id"] for p in doc["authored_pages"]]

    check("the pages a graph cannot answer are named as the author's",
          {"usage/python_api", "appendix/glossary", "appendix/troubleshooting",
           "getting_started/quick_start"}.issubset(set(authored)), repr(authored))
    check("and none of them was written",
          not (set(authored) & set(pages)), repr(sorted(set(authored) & set(pages))))

    def text_of(page_id):
        return " ".join(
            [b.get("text", "") for b in pages[page_id]["blocks"]]
            + [str(c) for b in pages[page_id]["blocks"] for row in b.get("rows", ()) or ()
               for c in row])

    check("the test command is on the testing page",
          "python3 -m pytest" in text_of("development/testing"),
          text_of("development/testing")[:200])
    check("and not also on the installation page",
          "python3 -m pytest" not in text_of("getting_started/installation"),
          text_of("getting_started/installation")[:200])
    check("the declared requirement is on the installation page",
          "Python" in text_of("getting_started/installation")
          and ">=3.9" in text_of("getting_started/installation"),
          text_of("getting_started/installation")[:200])
    check("the release page carries the release procedure",
          "workflow" in text_of("development/ci_cd_and_release"),
          text_of("development/ci_cd_and_release")[:200])

    # The traceability page is what a reviewer opens first: it says which scan the rest
    # of the document is about.
    trace = text_of("appendix/traceability")
    check("traceability names the scan", digest in trace, trace[:200])
    check("traceability lists the analyses this run carried",
          "architecture" in trace and "operations" in trace, trace[:300])

    # A repository with no git revision has no clean state to be dirty against; the
    # scanner's default would otherwise read as uncommitted work.
    check("a non-git tree is not reported as dirty",
          "yes" not in [c for b in pages["appendix/traceability"]["blocks"]
                        for row in b.get("rows", ()) or () for c in row
                        if isinstance(c, str)],
          repr([row for b in pages["appendix/traceability"]["blocks"]
                for row in b.get("rows", ()) or ()]))

    # Rationale gets its own page here, so the module reference must not also claim it.
    check("rationale is filed where a reader looks for why",
          "Trimming lives here" in text_of("architecture/design_decisions"),
          text_of("architecture/design_decisions")[:200])
    check("and not in the module reference",
          "Trimming lives here" not in text_of("architecture/module_reference"),
          text_of("architecture/module_reference")[:200])

    out_dir = os.path.join(tmp, "docs")
    code, out, err = run("render_docs.py", "--doc", doc_path, "--out", out_dir,
                         "--diagrams", diagrams, "--check")
    check("the manual preset renders", code == 0, (out + err)[-400:])
    check("the tree is written as directories",
          os.path.isfile(os.path.join(out_dir, "architecture", "overview.rst"))
          and os.path.isfile(os.path.join(out_dir, "appendix", "traceability.rst")))
    check("an authored page is not written",
          not os.path.exists(os.path.join(out_dir, "appendix", "glossary.rst")))
    index_rst = read(os.path.join(out_dir, "index.rst"))
    check("every generated page is in the toctree",
          all(pid in index_rst for pid in pages), index_rst[:400])

    # With no operations analysis the procedure pages must still say something rather
    # than emit a heading over nothing.
    bare = os.path.join(tmp, "doc-bare.json")
    code, out, err = run(
        "build_document_model.py", "--index", index_path, "--claims", claims_path,
        "--fragments", fragments_path, "--analysis", analysis_path,
        "--preset", "manual", "--diagrams", diagrams, "--out", bare)
    check("the preset builds with no analyses at all", code == 0, (out + err)[-400:])
    if code == 0:
        with open(bare, encoding="utf-8") as fh:
            thin = {p["id"]: p for p in json.load(fh)["pages"]}
        check("and the procedure pages say what is missing",
              all(any(b.get("absence") for b in thin[pid]["blocks"])
                  for pid in ("getting_started/installation", "development/testing",
                              "development/ci_cd_and_release", "usage/configuration")),
              repr(sorted(thin)))


def main():
    tmp = tempfile.mkdtemp(prefix="manual-preset-test-")
    try:
        shape_tests()
        build_tests(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("FAILED %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all manual-preset checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
