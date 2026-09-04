#!/usr/bin/env python3
"""Behavioural tests for the analysis reaching the document.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The defect these tests exist for was not a crash. The pipeline collected a per-module
reading, validated it, counted it in the quality gate, and then built the document
without it; every check passed and every page said only what the import graph could
prove. So the tests below are mostly about *absence being noticed*: a statement kind no
page covers, a page left with nothing but a heading, an `unknown` reaching prose.

    python3 tools/test_document_analysis.py
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

sys.path.insert(0, SCRIPTS)
import build_document_model as model                          # noqa: E402

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


def statement(sid, kind, status, text, path, line):
    return {"id": sid, "kind": kind, "status": status, "text": text,
            "evidence": [{"path": path, "line_start": line, "line_end": line}]}


def analysis_row(path, source_hash, index_hash, statements):
    return {"analysis_version": 1, "path": path, "source_hash": source_hash,
            "index_hash": index_hash, "role": "A module.", "statements": statements}


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def prepare(tmp):
    """Scan the fixture and derive everything a document needs except the reading."""
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
    claims = os.path.join(tmp, "claims.jsonl")
    run("derive_claims.py", "--index", index_path, "--units", units, "--out", claims)

    with open(claims, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    by_module = {}
    for row in rows:
        by_module.setdefault(row["subject"].split(":", 2)[1], []).append(row["id"])
    fragments = os.path.join(tmp, "fragments.jsonl")
    write_jsonl(fragments, [
        {"fragment_id": "fragment:%s" % path, "source": path, "role": "Role of %s." % path,
         "claim_ids": sorted(ids), "status": "candidate", "index_hash": index["index_hash"]}
        for path, ids in sorted(by_module.items())])

    run("verify_doc.py", "--claims", claims, "--fragments", fragments, "--index",
        index_path, "--root", root, "--out-dir", tmp)
    hashes = {r["path"]: r.get("source_hash") for r in index["files"]}
    return {"root": root, "index": index_path, "index_hash": index["index_hash"],
            "hashes": hashes, "modules": modules,
            "claims": os.path.join(tmp, "claims.verified.jsonl"),
            "fragments": os.path.join(tmp, "fragments.verified.jsonl")}


def build_doc(tmp, ctx, analysis_path=None, name="doc.json", preset=None):
    out = os.path.join(tmp, name)
    args = ["--index", ctx["index"], "--claims", ctx["claims"],
            "--fragments", ctx["fragments"], "--out", out]
    if preset:
        args += ["--preset", preset]
    if analysis_path:
        args += ["--analysis", analysis_path]
    code, output = run("build_document_model.py", *args)
    doc = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fh:
            doc = json.load(fh)
    return code, output, doc, out


def page(doc, page_id):
    for entry in doc["pages"]:
        if entry["id"] == page_id:
            return entry
    return None


def texts(page_entry):
    return " ".join(b.get("text", "") for b in page_entry["blocks"])


def main():
    tmp = tempfile.mkdtemp(prefix="doc-analysis-test-")
    try:
        ctx = prepare(tmp)
        http, service = "src/app/api/http.py", "src/app/core/service.py"

        # --- The document without a reading, which is what the pipeline used to build.
        code, output, bare, _ = build_doc(tmp, ctx, name="bare.json")
        check("a run with no analysis still builds", code == 0, output)
        check("and says why its pages are thin", "read like an inventory" in output, output)
        check("it carries no statements", bare["statements"] == [], repr(bare["statements"]))
        check("the modules page is only the table",
              all(b["type"] != "subheading" for b in page(bare, "modules")["blocks"]))

        # --- The same run with the reading attached.
        good = os.path.join(tmp, "analysis.jsonl")
        write_jsonl(good, [
            analysis_row(http, ctx["hashes"][http], ctx["index_hash"], [
                statement("s1", "responsibility", "observed",
                          "Turns a request body into an Order before the service is "
                          "entered.", http, 3),
                statement("s2", "interaction", "observed",
                          "Calls core.service and never reaches infra.store.", http, 3),
                statement("s3", "failure", "inferred",
                          "A malformed body raises before any record is written.",
                          http, 3)]),
            analysis_row(service, ctx["hashes"][service], ctx["index_hash"], [
                statement("s4", "rationale", "unknown",
                          "Why the service depends on infra.store directly.", service, 4)]),
        ])
        code, output, doc, doc_path = build_doc(tmp, ctx, good, "doc.json")
        check("a run with an analysis builds", code == 0, output)
        check("doc.json is v2", doc["format_version"] == 2, repr(doc["format_version"]))
        check("every statement is carried in the model",
              {s["id"] for s in doc["statements"]} == {"s1", "s2", "s3", "s4"},
              repr([s["id"] for s in doc["statements"]]))

        # The whole point: a reading that was paid for shows up on a page.
        check("what a module is responsible for reaches the module reference",
              "Turns a request body into an Order" in texts(page(doc, "modules")))
        check("how modules work together reaches the architecture page",
              "never reaches infra.store" in texts(page(doc, "architecture")))
        check("pages record what they cover",
              page(doc, "architecture")["covers"] == ["interaction", "rationale"],
              repr(page(doc, "architecture")["covers"]))
        check("and which statements they used",
              page(doc, "modules")["analysis_ids"] == ["s1", "s3"],
              repr(page(doc, "modules")["analysis_ids"]))

        # An inferred statement must not read as a fact, and an unknown must not appear
        # at all except as a question.
        check("an inferred statement keeps its hedge in the sentence",
              "Inferred: A malformed body raises" in texts(page(doc, "modules")))
        check("an unknown never reaches a page that asserts",
              "Why the service depends" not in texts(page(doc, "architecture")))
        check("it is listed as a question instead",
              "Why the service depends" in texts(page(doc, "limitations"))
              or any("Why the service depends" in str(row)
                     for b in page(doc, "limitations")["blocks"]
                     for row in b.get("rows", ())))
        check("no page cites the unknown statement",
              all("s4" not in p.get("analysis_ids", ()) for p in doc["pages"]))

        # --- Coverage per section, which is the figure that says what is missing.
        section = doc["coverage_by_section"]
        check("coverage is reported per section, not once for the tree",
              set(section) == {"modules", "architecture"}, repr(sorted(section)))
        check("each question has its own denominator",
              section["modules"]["interface"] == {
                  "modules_stated": 0, "modules_unknown": 0,
                  "modules_in_scope": len(ctx["modules"])},
              repr(section["modules"]["interface"]))
        check("a question the repository refused is counted as refused",
              section["architecture"]["rationale"]["modules_unknown"] == 1,
              repr(section["architecture"]["rationale"]))

        # --- The check that would have caught the original defect.
        doc_dropped = model.build(
            json.load(open(ctx["index"], encoding="utf-8")), [], [], "onboarding", None,
            model.Analysis([analysis_row(http, "x", "y", [
                statement("s9", "responsibility", "observed", "Something read.", http, 3)])]))
        doc_dropped["pages"] = [dict(p, covers=[]) for p in doc_dropped["pages"]]
        problems = model.validate(doc_dropped)
        check("a statement kind no page covers is a build failure",
              any("would be dropped" in p for p in problems), repr(problems))

        # --- A page that renders and says nothing.
        empty = model.build(json.load(open(ctx["index"], encoding="utf-8")),
                            [], [], "onboarding", None, model.Analysis())
        target = [p for p in empty["pages"] if p["id"] == "modules"][0]
        target["blocks"] = [b for b in target["blocks"] if b["type"] in ("ref",)] or [
            {"id": "block:x", "type": "ref", "target": "navigation"}]
        problems = model.validate(empty)
        check("a page whose blocks are all headings and links fails",
              any("nothing to say" in p for p in problems), repr(problems))

        # --- An unknown smuggled into prose is refused, whoever wrote the block.
        smuggled = json.loads(json.dumps(doc))
        smuggled["pages"][0]["blocks"].append(
            {"id": "block:smuggled", "type": "prose", "text": "The boundary is there "
             "because of the storage format.", "claim_refs": [], "analysis_refs": ["s4"]})
        problems = model.validate(smuggled)
        check("a block citing an unknown statement fails the build",
              any("may not appear in prose" in p and "s4" in p for p in problems),
              repr(problems))

        # --- A preset with no module reference still has to keep the reading.
        #
        # `architecture` drops the inventory deliberately, for a reader who knows the
        # domain. Dropping the per-module *reading* with it made the preset refuse to
        # build against any real analysis, which is not what "no inventory" meant.
        code, output, arch, _ = build_doc(tmp, ctx, good, "arch.json",
                                          preset="architecture")
        check("the architecture preset builds with a module-level analysis",
              code == 0, output)
        check("and the reading lands on its architecture page",
              "Turns a request body into an Order" in texts(page(arch, "architecture")),
              texts(page(arch, "architecture"))[:200])

        # --- The fragment table and the analysis fail independently.
        #
        # A fragment dies when a claim behind it is rejected; that says nothing about
        # whether anyone read the module. Returning early on an empty table threw every
        # statement away, and the coverage check passed because it only asked whether
        # the page *declared* the kinds.
        empty = os.path.join(tmp, "empty-fragments.jsonl")
        write_jsonl(empty, [])
        bare_ctx = dict(ctx, fragments=empty)
        code, output, thin, _ = build_doc(tmp, bare_ctx, good, "thin.json")
        check("statements survive an empty fragment table", code == 0, output)
        check("and are still rendered on the modules page",
              page(thin, "modules")["analysis_ids"] == ["s1", "s3"],
              repr(page(thin, "modules")["analysis_ids"]))

        # The check that would have caught it: declaring a kind is not rendering it.
        starved = json.loads(json.dumps(doc))
        for entry in starved["pages"]:
            entry["analysis_ids"] = []
            entry["blocks"] = [b for b in entry["blocks"] if not b.get("analysis_refs")]
        problems = model.validate(starved)
        check("a page that covers a kind but renders none of it fails",
              any("appears on no page" in p for p in problems), repr(problems))

        # --- Every citation, not the first.
        #
        # An inferred statement is supported by more than one place by definition, and a
        # reader of the rendered page cannot open doc.json to find the rest.
        rendered = model.sentence({
            "status": "inferred", "text": "Two places support this.", "path": http,
            "evidence": [{"path": http, "line_start": 3},
                         {"path": http, "line_start": 9}]})
        check("all evidence is cited, not just the first",
              "http.py:3" in rendered and "http.py:9" in rendered, rendered)

        # --- Block ids must survive paths that differ only in separator placement.
        collide = model.Analysis([
            analysis_row("a-b/c.py", "h", "i",
                         [statement("c1", "responsibility", "observed", "One.",
                                    "a-b/c.py", 1)]),
            analysis_row("a/b-c.py", "h", "i",
                         [statement("c2", "responsibility", "observed", "Two.",
                                    "a/b-c.py", 1)]),
        ])
        ids = [b["id"] for b in model.statement_blocks("modules", collide,
                                                       ("responsibility",))]
        check("two paths differing only by separator get distinct block ids",
              len(ids) == len(set(ids)), repr(ids))

        # --- Input errors are input errors, not silent omissions.
        future = os.path.join(tmp, "future.jsonl")
        write_jsonl(future, [dict(analysis_row(http, ctx["hashes"][http],
                                               ctx["index_hash"], []),
                                  analysis_version=99)])
        code, output, _, _ = build_doc(tmp, ctx, future, "future.json")
        check("an analysis from a future schema is refused", code == 2, output)

        unknown_kind = os.path.join(tmp, "unknown-kind.jsonl")
        write_jsonl(unknown_kind, [analysis_row(http, ctx["hashes"][http], ctx["index_hash"],
                                                [statement("s5", "vibes", "observed",
                                                           "Feels right.", http, 3)])])
        code, output, _, _ = build_doc(tmp, ctx, unknown_kind, "unknown-kind.json")
        check("a statement kind the renderer has no home for is refused",
              code == 2 and "vibes" in output, output)

        # --- Rendering, in both markups, and the v1 documents still render.
        for fmt in ("rst", "myst"):
            out_dir = os.path.join(tmp, "render-%s" % fmt)
            code, output = run("render_docs.py", "--doc", doc_path, "--out", out_dir,
                               "--format", fmt)
            check("a v2 document renders to %s" % fmt, code == 0, output)
            name = "modules.rst" if fmt == "rst" else "modules.md"
            with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
                body = fh.read()
            check("%s gets a real section heading" % fmt,
                  ("What it is responsible for\n---" in body) if fmt == "rst"
                  else ("## What it is responsible for" in body), body[:400])

        with open(os.path.join(tmp, "v1.json"), "w", encoding="utf-8") as fh:
            legacy = json.loads(json.dumps(bare))
            legacy["format_version"] = 1
            for entry in legacy["pages"]:
                entry.pop("covers", None)
                entry.pop("analysis_ids", None)
            json.dump(legacy, fh)
        code, output = run("render_docs.py", "--doc", os.path.join(tmp, "v1.json"),
                           "--out", os.path.join(tmp, "render-v1"))
        check("a v1 document still renders", code == 0, output)

        # --- Same inputs, same bytes.
        _, _, _, again = build_doc(tmp, ctx, good, "again.json")
        with open(doc_path, "rb") as fh:
            first = fh.read()
        with open(again, "rb") as fh:
            check("the same inputs give the same document", first == fh.read())
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
