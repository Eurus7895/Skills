#!/usr/bin/env python3
"""Behavioural tests for the outside-in preset and the two-way page contract.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Every other preset in this pipeline opens on structure: the dependency graph, the entry
points, the module inventory. That answers the question a reader has fourth. Outside-in
puts what the thing is first, how to run it second, and the inventory last, and it is the
first preset that consumes what C6 and C7 produced -- until now `architecture-analysis.json`
was validated, judged by Detector B, and then read by nobody.

Two rules make the ordering mean something rather than just rearranging headings:

    every required topic has a page, and a page a reader would look on for it -- the
    module reference may not be where "why is this boundary here" is filed
    a mandatory page has something to say, or the build fails rather than emitting a
    heading in a toctree

    python3 tools/test_outside_in.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
FIXTURE = os.path.join(REPO, "tests", "contracts", "flow-repo")

sys.path.insert(0, SCRIPTS)
import build_document_model as model                              # noqa: E402

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
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True)
    return path


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    tmp = tempfile.mkdtemp(prefix="outside-in-test-")
    try:
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
            for row in (
                {"id": "claim:a", "kind": "calls", "subject": "symbol:%s:main" % entry,
                 "object": "symbol:%s:normalise" % transform,
                 "evidence": [{"path": entry, "line_start": 7}], "index_hash": digest},
                {"id": "claim:b", "kind": "calls",
                 "subject": "symbol:%s:normalise" % transform,
                 "object": "symbol:%s:save" % store,
                 "evidence": [{"path": transform, "line_start": 7}],
                 "index_hash": digest},
            ):
                fh.write(json.dumps(row, sort_keys=True) + "\n")
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
                (transform, "responsibility", "s-transform",
                 "Trims the input before anything stores it.", 6),
                (store, "state", "s-store", "Owns the count of what it was given.", 4),
                (transform, "interaction", "s-interaction",
                 "Calls into the store and is called by the entry point.", 3),
                (transform, "rationale", "s-rationale",
                 "Trimming lives here so the store never sees raw input.", 1),
            ):
                fh.write(json.dumps({
                    "analysis_version": 1, "path": path, "source_hash": hashes[path],
                    "index_hash": digest, "role": "A part of the pipeline.",
                    "statements": [{"id": sid, "kind": kind, "status": "observed"
                                    if kind != "rationale" else "declared", "text": text,
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
            "procedures": [{"id": "op:test", "kind": "test",
                            "name": "Running the tests", "status": "declared",
                            "steps": [{"text": "CI runs the suite on every push.",
                                       "status": "declared",
                                       "command": "python3 -m pytest",
                                       "evidence": [{"path": ".github/workflows/ci.yml",
                                                     "line_start": 8}]}]}],
            "requirements": [{"id": "req:python", "name": "Python", "value": ">=3.9",
                              "status": "declared",
                              "evidence": [{"path": "pyproject.toml",
                                            "line_start": 4}]}],
        })
        flows = write_json(os.path.join(tmp, "flow-analysis.json"), {
            "flow_version": 1, "index_hash": digest, "flows": [],
            "absent": {"reason": "No call chain was traced for this fixture."}})

        def build(name, preset="outside-in", *extra):
            out = os.path.join(tmp, "doc-%s.json" % name)
            args = ["--index", index_path, "--claims", claims_path,
                    "--fragments", fragments_path, "--analysis", analysis_path,
                    "--preset", preset, "--out", out] + list(extra)
            code, _, err = run("build_document_model.py", *args)
            return code, out, err

        full = ("--architecture", architecture, "--operations", operations,
                "--flows", flows)
        code, doc_path, err = build("full", "outside-in", *full)
        check("the outside-in preset builds", code == 0, err[:400])

        out_dir = os.path.join(tmp, "docs")
        code, _, err = run("render_docs.py", "--doc", doc_path, "--format", "rst",
                           "--out", out_dir)
        check("and renders", code == 0, err[:300])

        with open(doc_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        page_ids = [p["id"] for p in doc["pages"]]
        check("the pages are in outside-in order, structure last",
              page_ids == ["overview", "getting-started", "architecture", "components",
                           "rationale", "flows", "operations", "reference"],
              repr(page_ids))
        check("conventions is named as the author's, not generated",
              [p["id"] for p in doc["authored_pages"]] == ["conventions"]
              and not os.path.exists(os.path.join(out_dir, "conventions.rst")),
              repr(doc["authored_pages"]))

        # --- C6's synthesis reaches a reader for the first time.
        components = read(os.path.join(out_dir, "components.rst"))
        check("the components page names the components, not the directories",
              "The pipeline" in components and "Storage" in components, components[:400])
        check("and says which modules each one holds",
              entry in components and store in components, components[:600])
        check("and what crosses between them, with the line it was read at",
              "depends on" in components and "%s:3" % transform in components,
              components[:900])

        rationale = read(os.path.join(out_dir, "rationale.rst"))
        check("a recorded rationale is cited",
              "Entry and normalisation share one rule set." in rationale
              and "README.md:3" in rationale, rationale[:600])
        check("and one recorded as unknown is shown as the open question it is",
              "Why storage counts rather than persists." in rationale
              and "nobody answered" in rationale, rationale[:900])

        started = read(os.path.join(out_dir, "getting-started.rst"))
        check("getting started quotes the command and where it was read",
              "python3 -m pytest" in started
              and ".github/workflows/ci.yml:8" in started, started[:600])
        check("and states the requirement the repository declares",
              ">=3.9" in started and "pyproject.toml:4" in started, started[:600])

        # --- Coverage is per required section.
        coverage = doc["coverage_by_section"]
        check("coverage reports a denominator per section, not one for the tree",
              set(coverage) == {"components", "rationale", "reference"}
              and set(coverage["reference"]) == {"responsibility", "state", "interface",
                                                 "failure"},
              repr(sorted(coverage)))
        check("and each section carries its own count",
              coverage["reference"]["responsibility"]["modules_stated"] == 2
              and coverage["reference"]["failure"]["modules_stated"] == 0,
              repr(coverage["reference"]))

        # --- The two rules, checked in process: they are properties of a preset, and
        # constructing a bad preset is the only way to exercise them.
        original_covers = dict(model.PRESET_COVERS["outside-in"])
        try:
            model.PRESET_COVERS["outside-in"] = dict(
                original_covers, components=(),
                modules=("responsibility", "state", "interface", "failure",
                         "interaction"))
            index_doc = json.load(open(index_path, encoding="utf-8"))
            rebuilt = model.build(index_doc, [], [], "outside-in", None,
                                  model.Analysis([json.loads(line) for line
                                                  in open(analysis_path,
                                                          encoding="utf-8")]),
                                  {"architecture": json.load(open(architecture,
                                                                  encoding="utf-8"))})
            problems = model.validate(rebuilt)
            check("the module reference cannot answer an architecture question",
                  any("cannot answer" in p for p in problems), repr(problems)[:400])
        finally:
            model.PRESET_COVERS["outside-in"] = original_covers

        original_builder = model.BUILDERS["operations"]
        try:
            model.BUILDERS["operations"] = \
                lambda ix, frags, claims, by_id, an, kinds, extra: []
            index_doc = json.load(open(index_path, encoding="utf-8"))
            rebuilt = model.build(index_doc, [], [], "outside-in", None, model.Analysis(),
                                  {})
            problems = model.validate(rebuilt)
            check("a mandatory page with nothing to say fails the build",
                  any("nothing to say" in p for p in problems), repr(problems)[:400])

            # The rule that only caught *empty* let the first outside-in overview
            # through: two uncited sentences, a file count and a list of entry points,
            # which is not an answer to "what is this".
            model.BUILDERS["operations"] = \
                lambda ix, frags, claims, by_id, an, kinds, extra: [
                    model.prose("block:operations-bare", "Operations are handled by the "
                                                         "usual deployment process.")]
            rebuilt = model.build(index_doc, [], [], "outside-in", None, model.Analysis(),
                                  {})
            problems = model.validate(rebuilt)
            check("a mandatory page of uncited prose fails too",
                  any("cites nothing" in p for p in problems), repr(problems)[:400])

            # ...and the honest alternative is to say what is missing, marked as such.
            model.BUILDERS["operations"] = \
                lambda ix, frags, claims, by_id, an, kinds, extra: [
                    model.absence("block:operations-bare", "No operations analysis was "
                                                           "supplied for this run.")]
            rebuilt = model.build(index_doc, [], [], "outside-in", None, model.Analysis(),
                                  {})
            check("while a page that says what is missing passes",
                  not any("cites nothing" in p for p in model.validate(rebuilt)),
                  repr(model.validate(rebuilt))[:400])
        finally:
            model.BUILDERS["operations"] = original_builder

        # --- What the preset does without the material it is built from.
        code, bare_doc, err = build("bare", "outside-in")
        check("the preset still builds with no architecture or operations analysis",
              code == 0, err[:300])
        bare_dir = os.path.join(tmp, "bare-docs")
        run("render_docs.py", "--doc", bare_doc, "--format", "rst", "--out", bare_dir)
        bare_components = read(os.path.join(bare_dir, "components.rst"))
        check("and says the analysis was not supplied rather than showing nothing",
              "No architecture analysis was supplied" in bare_components,
              bare_components[:400])

        # --- The presets that existed before this one are unchanged.
        for preset in ("onboarding", "architecture", "handbook"):
            code, other_doc, err = build(preset, preset)
            check("the %s preset still builds" % preset, code == 0, err[:300])
            code, _, err = run("render_docs.py", "--doc", other_doc, "--format", "rst",
                               "--out", os.path.join(tmp, "docs-%s" % preset))
            check("the %s preset still renders" % preset, code == 0, err[:300])

        # --- Identity, same as everywhere else in this pipeline.
        stale = write_json(os.path.join(tmp, "stale-arch.json"),
                           dict(json.load(open(architecture, encoding="utf-8")),
                                index_hash="sha256:" + "0" * 64))
        code, _, err = build("stale", "outside-in", "--architecture", stale)
        check("an architecture analysis from another scan stops the build",
              code == 2 and "written against" in err, "%d %r" % (code, err[:200]))
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
