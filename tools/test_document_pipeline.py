#!/usr/bin/env python3
"""Behavioural tests for build_document_model.py and render_docs.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

These two run back to back, so they are tested together: the model's job is to decide
what may be said, and the renderer's is to say it in markup that builds. The boundary
they jointly enforce -- a candidate claim never reaching a paragraph -- is checked from
both sides.

Sphinx and docutils are optional here. Where neither is installed the renderer reports
`skipped`, and these tests assert the structural properties a build would otherwise
catch: every page in the toctree, headings underlined to the full width, no unescaped
table separator inside a cell.

    python3 tools/test_document_pipeline.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
BUILDER = os.path.join(REPO, "shared", "scripts", "build_document_model.py")
RENDERER = os.path.join(REPO, "shared", "scripts", "render_docs.py")

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


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def build_fixture(tmp):
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "api.py", "from pkg.service import handle\n\n\ndef serve():\n"
                          "    return handle()\n\n\nif __name__ == '__main__':\n"
                          "    serve()\n")
    write(root, "pkg/__init__.py")
    write(root, "pkg/service.py", "def handle():\n    return 1\n")
    index = os.path.join(tmp, "structure.json")
    proc = subprocess.run([sys.executable, SCANNER, "--root", root, "--out", index,
                           "--detail"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    return root, index


CLAIMS = [
    {"id": "c:imports", "kind": "imports", "subject": "module:api.py",
     "object": "module:pkg/service.py", "status": "verified",
     "evidence": [{"path": "api.py", "line_start": 1}]},
    {"id": "c:role", "kind": "responsibility", "subject": "module:api.py",
     "object": None, "status": "supported_inference", "evidence": []},
]
FRAGMENTS = [
    {"fragment_id": "f:api", "source": "api.py",
     "role": "Entry module; delegates to the service layer.",
     "claim_ids": ["c:imports", "c:role"], "status": "verified"},
]


def run_builder(tmp, index, claims, fragments, name="doc", preset="onboarding"):
    claims_path = os.path.join(tmp, name + "-claims.jsonl")
    frag_path = os.path.join(tmp, name + "-fragments.jsonl")
    out = os.path.join(tmp, name + ".json")
    write_rows(claims_path, claims)
    write_rows(frag_path, fragments)
    proc = subprocess.run([sys.executable, BUILDER, "--index", index,
                           "--claims", claims_path, "--fragments", frag_path,
                           "--preset", preset, "--out", out],
                          capture_output=True, text=True)
    doc = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fh:
            doc = json.load(fh)
    return proc.returncode, doc, proc.stdout + proc.stderr, out


def run_renderer(doc_path, out_dir, *args):
    proc = subprocess.run([sys.executable, RENDERER, "--doc", doc_path, "--out", out_dir]
                          + list(args), capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def blocks_of(doc):
    return [b for page in doc["pages"] for b in page["blocks"]]


def main():
    tmp = tempfile.mkdtemp(prefix="doc-pipeline-test-")
    try:
        root, index = build_fixture(tmp)

        code, doc, output, doc_path = run_builder(tmp, index, CLAIMS, FRAGMENTS)
        check("the model builds", code == 0, output)

        ids = [p["id"] for p in doc["pages"]]
        check("every mandatory page of the preset exists",
              set(ids) >= {"overview", "entry-points", "architecture", "modules",
                           "limitations"}, "%r" % ids)
        check("pages are ordered", [p["order"] for p in doc["pages"]]
              == sorted(p["order"] for p in doc["pages"]))
        check("block ids are unique",
              len({b["id"] for b in blocks_of(doc)}) == len(blocks_of(doc)))
        check("the model carries the revision it was built from",
              "source_revision" in doc)
        check("the entry point found by its main guard reaches the page",
              any("api.py" in str(b.get("rows")) for b in blocks_of(doc)
                  if b["id"] == "block:entry-points"), "%r" % blocks_of(doc))
        check("a verified module description reaches the module table",
              any("Entry module" in str(b.get("rows")) for b in blocks_of(doc)
                  if b["type"] == "table"))

        # Determinism: the same inputs must produce the same file, or no diff of
        # generated docs is readable.
        code, again, _, _ = run_builder(tmp, index, CLAIMS, FRAGMENTS, name="doc2")
        check("the same inputs produce the same model",
              json.dumps(doc, sort_keys=True) == json.dumps(again, sort_keys=True))

        # The boundary: what may appear in prose.
        candidate = CLAIMS + [{"id": "c:maybe", "kind": "calls", "subject": "module:api.py",
                               "object": "symbol:pkg/service.py:handle",
                               "status": "candidate",
                               "evidence": [{"path": "api.py", "line_start": 5}]}]
        code, doc2, output, _ = run_builder(tmp, index, candidate, FRAGMENTS, name="cand")
        check("a candidate claim does not block the build", code == 0, output)
        cited = {c for b in blocks_of(doc2) for c in b.get("claim_refs", ())}
        check("but no block cites it", "c:maybe" not in cited, "%r" % cited)
        check("it is named in the limitations instead",
              any("c:maybe" in str(b.get("rows")) for b in blocks_of(doc2)),
              "candidate claim vanished entirely")

        rejected = CLAIMS + [{"id": "c:false", "kind": "imports", "subject": "module:api.py",
                              "object": "module:pkg/__init__.py", "status": "rejected",
                              "evidence": [{"path": "api.py", "line_start": 1}]}]
        code, _, output, _ = run_builder(tmp, index, rejected, FRAGMENTS, name="rej")
        check("a rejected claim stops the build outright", code == 2, output)
        check("and the message names it", "c:false" in output, output)

        # A fragment that did not survive verification must not be quoted as if it had.
        unverified = [dict(FRAGMENTS[0], status="candidate")]
        code, doc3, output, _ = run_builder(tmp, index, CLAIMS, unverified, name="unver")
        check("an unverified fragment is left out of the module table",
              code == 0 and not any("Entry module" in str(b.get("rows"))
                                    for b in blocks_of(doc3) if b["type"] == "table"),
              output)

        code, doc4, output, arch_path = run_builder(tmp, index, CLAIMS, FRAGMENTS,
                                                    name="arch", preset="architecture")
        check("a second preset produces its own page set",
              code == 0 and "dependencies" in [p["id"] for p in doc4["pages"]], output)

        # Rendering.
        out_dir = os.path.join(tmp, "docs")
        code, output = run_renderer(doc_path, out_dir, "--check")
        check("rendering succeeds", code == 0, output)
        check("the check reports its status honestly",
              "build check: passed" in output or "build check: skipped" in output, output)

        written = sorted(n for n in os.listdir(out_dir) if n.endswith(".rst"))
        check("one file per page, plus an index",
              written == sorted([p["id"] + ".rst" for p in doc["pages"]] + ["index.rst"]),
              "%r" % written)

        with open(os.path.join(out_dir, "index.rst"), encoding="utf-8") as fh:
            index_text = fh.read()
        check("every page appears in the toctree",
              all(("   %s\n" % p["id"]) in index_text for p in doc["pages"]), index_text)

        pages = {}
        for name in written:
            with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
                pages[name] = fh.read()

        for name, text in pages.items():
            lines = text.splitlines()
            check("%s underlines its title to full width" % name,
                  len(lines) > 1 and len(lines[1]) >= len(lines[0])
                  and set(lines[1]) == {"="},
                  "%r / %r" % (lines[0] if lines else "", lines[1] if len(lines) > 1 else ""))
        check("no page contains a tab", not any("\t" in t for t in pages.values()))

        # Escaping. A role containing RST metacharacters must not change the markup.
        nasty = [dict(FRAGMENTS[0],
                      role="Handles *everything* | including `backticks` and \\ slashes")]
        code, doc5, output, nasty_doc = run_builder(tmp, index, CLAIMS, nasty, name="nasty")
        nasty_dir = os.path.join(tmp, "nasty-docs")
        code, output = run_renderer(nasty_doc, nasty_dir, "--check")
        check("a role full of markup characters still renders", code == 0, output)
        with open(os.path.join(nasty_dir, "modules.rst"), encoding="utf-8") as fh:
            table_text = fh.read()
        check("the emphasis marker is escaped", "\\*everything\\*" in table_text, table_text)
        check("the row separator is escaped inside the cell",
              "\\|" in table_text and "including" in table_text, table_text)
        check("the backtick is escaped", "\\`backticks\\`" in table_text, table_text)

        # A model the renderer cannot trust.
        bad = os.path.join(tmp, "bad.json")
        with open(doc_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["format_version"] = 99
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, output = run_renderer(bad, os.path.join(tmp, "no"))
        check("an unsupported format_version exits 2", code == 2, output)

        broken = os.path.join(tmp, "broken.json")
        with open(doc_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["pages"][0]["blocks"].append({"id": "block:weird", "type": "carousel"})
        with open(broken, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        target = os.path.join(tmp, "partial")
        code, output = run_renderer(broken, target)
        check("an unknown block type exits 2", code == 2, output)
        check("and nothing was written to the output directory",
              not os.path.isdir(target) or not os.listdir(target),
              "%r" % (os.path.isdir(target) and os.listdir(target)))

        code, output = run_renderer(os.path.join(tmp, "absent.json"),
                                    os.path.join(tmp, "no2"))
        check("a missing model exits 2", code == 2, output)

        # Rendering must be deterministic too.
        first_dir, second_dir = os.path.join(tmp, "d1"), os.path.join(tmp, "d2")
        run_renderer(doc_path, first_dir)
        run_renderer(doc_path, second_dir)
        same = all(open(os.path.join(first_dir, n), encoding="utf-8").read()
                   == open(os.path.join(second_dir, n), encoding="utf-8").read()
                   for n in os.listdir(first_dir))
        check("rendering the same model twice gives the same bytes", same)

        check("the renderer wrote no conf.py",
              not os.path.isfile(os.path.join(out_dir, "conf.py")),
              "a conf.py was left behind")
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
