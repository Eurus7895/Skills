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
    # One base that resolves inside the repository and one that cannot: the class view
    # has to tell them apart rather than presenting both as links.
    write(root, "pkg/base.py", "class Record:\n    pass\n")
    write(root, "pkg/models.py",
          "from pkg.base import Record\n\n\nclass Order(Record):\n    pass\n\n\n"
          "class Failure(Exception):\n    pass\n")
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
        arch_ids = [p["id"] for p in doc4["pages"]]
        check("a second preset produces its own page set",
              code == 0 and set(arch_ids) == {"overview", "architecture", "dependencies",
                                              "class-views", "flows", "limitations"},
              "%r %s" % (arch_ids, output))
        check("the architecture preset carries no module reference by design",
              "modules" not in arch_ids, "%r" % arch_ids)

        # A page with nothing to show says so rather than being dropped -- a missing
        # page and an empty one read very differently to someone looking for it.
        flows = [b for p in doc4["pages"] if p["id"] == "flows" for b in p["blocks"]]
        check("a flows page with no verified call still exists and says why",
              flows and any("No call was verified" in str(b.get("text", ""))
                            for b in flows), "%r" % flows)
        rows = [r for p in doc4["pages"] if p["id"] == "class-views"
                for b in p["blocks"] for r in b.get("rows", ())]
        check("a base defined in the repository is linked to its file",
              any(r[0] == "Order" and "pkg/base.py" in r[1] for r in rows), "%r" % rows)
        check("a base from outside is marked unresolved, not linked",
              any(r[0] == "Failure" and "not resolved" in r[1] for r in rows),
              "%r" % rows)

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

        # Escaping asserted against a real build rather than against the source text.
        # Each of these came from a page that rendered, read correctly, and failed
        # `sphinx-build -W`: `|x|` is a substitution reference, `ref_` is a reference,
        # `[1]_` is a footnote, and an undefined one of any of them is a build error.
        # Only table cells had ever escaped the pipe, and nothing escaped the underscore.
        if shutil.which("sphinx-build"):
            hostile = {
                "substitution": "a |sub| and a bare | bar",
                "trailing underscore": "see ref_ and snake_case_name and _leading",
                "footnote": "[1]_ numbered and [#]_ auto and [x] plain",
                "emphasis": "2*3*4 and **bold",
                "role": "`x` and ``y``",
                "all at once": "src/api.py:12 -> `Foo`_ |x| *y* [1]_ \\z",
            }
            for label, text in hostile.items():
                doc = {"format_version": 1, "generator_version": "t",
                       "preset": "onboarding", "source_revision": None,
                       "source_dirty": True, "coverage": {}, "claims": [],
                       "authored_pages": [],
                       "pages": [{"id": "overview", "title": "T " + text, "order": 1,
                                  "mandatory": True, "blocks": [
                                      {"id": "block:p", "type": "prose", "text": text,
                                       "claim_refs": []},
                                      {"id": "block:t", "type": "table",
                                       "columns": ["c"], "rows": [[text]],
                                       "claim_refs": []}]}]}
                slug = label.replace(" ", "-")
                path = os.path.join(tmp, "hostile-%s.json" % slug)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                code, output = run_renderer(path, os.path.join(tmp, "hostile-" + slug),
                                            "--check")
                check("%s survives a real Sphinx build, in prose, heading and cell"
                      % label,
                      code == 0 and "build check: passed" in output, output[-400:])
        else:
            print("skip hostile-escaping checks -- sphinx-build is not installed")

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

        # The documented invocation is `--out docs`, which is where a project keeps its
        # real Sphinx configuration. A check that writes its own conf.py there and
        # deletes it afterwards destroys the thing it was asked to check.
        existing = os.path.join(tmp, "has-conf")
        code, output = run_renderer(doc_path, existing)
        marker = "project = 'the real project'\n"
        with open(os.path.join(existing, "conf.py"), "w", encoding="utf-8") as fh:
            fh.write(marker)
        code, output = run_renderer(doc_path, existing, "--check")
        check("--check leaves an existing conf.py exactly as it found it",
              code == 0 and os.path.isfile(os.path.join(existing, "conf.py"))
              and open(os.path.join(existing, "conf.py"),
                       encoding="utf-8").read() == marker, output)

        # Diagrams are optional, so the two cases that matter are "there is one" and
        # "there is not" -- and neither may produce a page pointing at a missing file.
        contracts = os.path.join(REPO, "tests", "contracts")
        diagrams = os.path.join(tmp, "_diagrams")
        subprocess.run([sys.executable,
                        os.path.join(REPO, "shared", "scripts", "build_diagrams.py"),
                        "--render-only",
                        os.path.join(contracts, "diagram-model-v1-valid.json"),
                        "--out", diagrams], capture_output=True, text=True)
        code, doc6, output, with_figure = run_builder(
            tmp, index, CLAIMS, FRAGMENTS, name="figure", preset="architecture")
        # Rebuild with the diagram directory attached.
        proc = subprocess.run(
            [sys.executable, BUILDER, "--index", index,
             "--claims", os.path.join(tmp, "figure-claims.jsonl"),
             "--fragments", os.path.join(tmp, "figure-fragments.jsonl"),
             "--preset", "architecture", "--diagrams", diagrams,
             "--out", with_figure], capture_output=True, text=True)
        check("a document can reference a rendered diagram", proc.returncode == 0,
              proc.stdout + proc.stderr)
        with open(with_figure, encoding="utf-8") as fh:
            doc6 = json.load(fh)
        figures = [b for p in doc6["pages"] for b in p["blocks"] if b["type"] == "image"]
        check("the figure lands on the pages about structure",
              {b["id"].split("-diagram-")[0] for b in figures}
              == {"block:architecture", "block:class-views"}, "%r" % figures)
        check("and every figure has alt text",
              all(b.get("alt") for b in figures), "%r" % figures)

        # A preset with no page for classes still has to give the detail views a home.
        # Rendering seven views into _diagrams/ and referencing one leaves the rest as
        # files the reader has no route to.
        detail_model = os.path.join(tmp, "detail-view-model.json")
        with open(os.path.join(contracts, "diagram-model-v1-valid.json"),
                  encoding="utf-8") as fh:
            detail = json.load(fh)
        detail["view"] = "package_pkg"
        detail["scope"] = {"kind": "package", "id": "package:pkg"}
        with open(detail_model, "w", encoding="utf-8") as fh:
            json.dump(detail, fh)
        subprocess.run([sys.executable,
                        os.path.join(REPO, "shared", "scripts", "build_diagrams.py"),
                        "--render-only", detail_model, "--out", diagrams],
                       capture_output=True, text=True)
        onboarding_doc = os.path.join(tmp, "onboarding-figure-doc.json")
        proc = subprocess.run(
            [sys.executable, BUILDER, "--index", index,
             "--claims", os.path.join(tmp, "figure-claims.jsonl"),
             "--fragments", os.path.join(tmp, "figure-fragments.jsonl"),
             "--preset", "onboarding", "--diagrams", diagrams,
             "--out", onboarding_doc], capture_output=True, text=True)
        check("onboarding builds with detail views present", proc.returncode == 0,
              proc.stdout + proc.stderr)
        with open(onboarding_doc, encoding="utf-8") as fh:
            shown = {b["src"] for p in json.load(fh)["pages"] for b in p["blocks"]
                     if b["type"] == "image"}
        check("a preset without a class page still shows the detail views",
              shown == {"_diagrams/full-repository.svg", "_diagrams/package-pkg.svg"},
              "%r" % sorted(shown))

        # -- a preset that matches an existing documentation tree -------------------
        # Most of a delivered manual is not derivable from a dependency graph. The
        # handbook preset names those pages and writes none of them: a generated stub
        # would replace whatever the author already has there.
        hand_doc = os.path.join(tmp, "handbook-doc.json")
        proc = subprocess.run(
            [sys.executable, BUILDER, "--index", index,
             "--claims", os.path.join(tmp, "figure-claims.jsonl"),
             "--fragments", os.path.join(tmp, "figure-fragments.jsonl"),
             "--preset", "handbook", "--out", hand_doc], capture_output=True, text=True)
        check("the handbook preset builds", proc.returncode == 0,
              proc.stdout + proc.stderr)
        with open(hand_doc, encoding="utf-8") as fh:
            handbook = json.load(fh)
        generated = {p["id"] for p in handbook["pages"]}
        authored = {p["id"] for p in handbook["authored_pages"]}
        check("it fills only the pages the graph can answer for",
              generated == {"architecture/key_modules", "architecture/class_diagrams",
                            "architecture/data_flow", "development/module_reference"},
              "%r" % sorted(generated))
        check("and names the rest rather than inventing them",
              "getting_started/installation_integrators" in authored
              and "appendix/faq" in authored and not (generated & authored),
              "%r" % sorted(authored))

        # The author's own pages and table of contents have to survive the render.
        tree = os.path.join(tmp, "handbook-docs")
        os.makedirs(os.path.join(tree, "getting_started"))
        keeper = os.path.join(tree, "getting_started", "introduction.rst")
        with open(keeper, "w", encoding="utf-8") as fh:
            fh.write("Introduction\n============\n\nWritten by a person.\n")
        with open(os.path.join(tree, "index.rst"), "w", encoding="utf-8") as fh:
            fh.write("Docs\n====\n\n.. toctree::\n\n   getting_started/introduction\n")
        code, output = run_renderer(hand_doc, tree)
        check("rendering a nested preset succeeds", code == 0, output)
        check("pages land at the paths the preset names",
              os.path.isfile(os.path.join(tree, "architecture", "class_diagrams.rst")),
              "%r" % sorted(os.listdir(tree)))
        with open(keeper, encoding="utf-8") as fh:
            check("an authored page is left exactly as it was",
                  "Written by a person." in fh.read())
        with open(os.path.join(tree, "index.rst"), encoding="utf-8") as fh:
            check("and the author's toctree is not replaced",
                  "Written by" not in fh.read() and "getting_started/introduction"
                  in open(os.path.join(tree, "index.rst"), encoding="utf-8").read())
        check("the run says which pages it did not generate",
              "not generated: appendix/faq.rst" in output, output)

        code, output = run_renderer(hand_doc, tree, "--replace-index")
        with open(os.path.join(tree, "index.rst"), encoding="utf-8") as fh:
            check("--replace-index is how the index gets rewritten, and only then",
                  "architecture/class_diagrams" in fh.read(), output)

        # Sphinx resolves a relative `:doc:` target and a relative image path against the
        # directory of the page that carries them, so a nested page referring to
        # `architecture/data_flow` asks for `architecture/architecture/data_flow`. Neither
        # is visible without a real build, and both shipped.
        nested = [os.path.join(base, name)
                  for base, _, names in os.walk(tree)
                  for name in names if name.endswith(".rst")]
        referring = [p for p in nested if ":doc:`" in open(p, encoding="utf-8").read()]
        check("a nested page refers to another page from the source root",
              referring and all("<architecture/" not in open(p, encoding="utf-8").read()
                                and "</architecture/" in open(p, encoding="utf-8").read()
                                for p in referring
                                if "architecture" in open(p, encoding="utf-8").read()),
              "%r" % [os.path.relpath(p, tree) for p in referring])
        figures = [p for p in nested if ".. figure::" in open(p, encoding="utf-8").read()]
        for path in figures:
            with open(path, encoding="utf-8") as fh:
                line = next(l for l in fh if l.startswith(".. figure::"))
            check("a figure on a nested page is addressed from the source root too",
                  line.split("::", 1)[1].strip().startswith("/"),
                  "%s: %s" % (os.path.relpath(path, tree), line.strip()))

        if shutil.which("sphinx-build"):
            # Keeping the author's index leaves the generated pages in no toctree. The
            # markup is sound; calling that a failed check sends the reader hunting for a
            # defect in a page that does not have one.
            unwired = os.path.join(tmp, "unwired-docs")
            os.makedirs(os.path.join(unwired, "getting_started"))
            with open(os.path.join(unwired, "getting_started", "introduction.rst"),
                      "w", encoding="utf-8") as fh:
                fh.write("Introduction\n============\n\nWritten by a person.\n")
            with open(os.path.join(unwired, "index.rst"), "w", encoding="utf-8") as fh:
                # A toctree that resolves. One naming a missing page is a real error and
                # would mask the distinction this is testing.
                fh.write("Docs\n====\n\n.. toctree::\n\n   getting_started/introduction\n")
            code, output = run_renderer(hand_doc, unwired, "--check")
            check("a page in no toctree is reported as unwired, not as failed",
                  "build check: unwired" in output, output)
            check("and being unwired does not fail the run", code == 0, output)
        else:
            print("skip build-check checks -- sphinx-build is not installed")

        figure_docs = os.path.join(tmp, "figure-docs")
        code, output = run_renderer(with_figure, figure_docs, "--diagrams", diagrams)
        check("rendering copies the diagrams in beside the pages",
              code == 0 and os.path.isfile(
                  os.path.join(figure_docs, "_diagrams", "full-repository.svg")), output)
        code, output = run_renderer(with_figure, os.path.join(tmp, "no-figures"))
        check("a figure with nowhere to resolve stops the render", code == 2, output)

        # `--out docs --diagrams docs/_diagrams` is the documented invocation, so the
        # source and the destination are the same directory. Clearing the destination
        # first would delete the diagrams and then copy from nothing.
        in_place = os.path.join(tmp, "in-place")
        os.makedirs(in_place)
        shutil.copytree(diagrams, os.path.join(in_place, "_diagrams"))
        code, output = run_renderer(with_figure, in_place,
                                    "--diagrams", os.path.join(in_place, "_diagrams"))
        check("rendering into the directory the diagrams already live in keeps them",
              code == 0 and os.path.isfile(
                  os.path.join(in_place, "_diagrams", "full-repository.svg")), output)
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
