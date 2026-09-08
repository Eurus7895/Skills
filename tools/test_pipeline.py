#!/usr/bin/env python3
"""Behavioural tests for select_units.py and pipeline.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The driver's whole value is that it does not lose things: not an exit code, not a stage,
not a claim somebody wrote by hand. So the tests here are about what a driver gets wrong.
It must stop at the first failure rather than running on; it must pass the failing stage's
exit code out unchanged, because converting a verdict into a different number is the same
as hiding it; it must skip a stage whose input was never written instead of failing; and
the two stages allowed to fail must not take their component down with them.

    python3 tools/test_pipeline.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from component_scripts import script

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "tests", "contracts", "flow-repo")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(name, *args, **kwargs):
    proc = subprocess.run([sys.executable, script(name)] + list(args),
                          capture_output=True, text=True, cwd=kwargs.get("cwd"))
    return proc.returncode, proc.stdout + proc.stderr


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def units_tests(tmp):
    """select_units.py: the cutoff, the tie-break, and the warning that it is a bad one."""
    index_path = os.path.join(tmp, "structure.json")
    root = os.path.join(tmp, "repo")
    shutil.copytree(FIXTURE, root)
    run("scan_repo.py", "--root", root, "--out", index_path, "--detail")

    out = os.path.join(tmp, "units.txt")
    code, text = run("select_units.py", "--index", index_path, "--out", out)
    check("select_units exits 0 on a real index", code == 0, text)
    selected = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    check("select_units keeps the depended-upon modules",
          "src/pipeline/transform.py" in selected and "src/pipeline/store.py" in selected,
          str(selected))
    check("select_units adds the entry point despite fan-in 0",
          "src/pipeline/entry.py" in selected, str(selected))
    check("select_units names why each unit is in the list",
          "entry_point" in text and "fan_in" in text, text)

    # A cutoff of zero still keeps the entry points: they are added, not ranked.
    code, _ = run("select_units.py", "--index", index_path, "--out", out, "--top", "0")
    kept = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    check("--top 0 keeps only the entry points",
          code == 0 and kept == ["src/pipeline/entry.py"], str(kept))

    # A file that defines nothing cannot be described. `validate_analysis` wants a
    # statement naming something in the module, and `assemble` wants a fragment citing a
    # derived claim; an empty `__init__.py` offers neither. Selecting one puts a unit in
    # the budget that no work can satisfy -- the assembler then fails the run for a unit
    # with no row, which is how a package marker stopped a document being built at all.
    run("scan_repo.py", "--root", root, "--out", index_path, "--detail")
    with open(index_path, encoding="utf-8") as fh:
        scanned = json.load(fh)
    # Not "the file is empty": a package marker usually carries a docstring and still
    # defines nothing, which is the condition that matters here.
    check("the fixture holds a module that defines nothing",
          any(not r.get("symbols") for r in scanned["files"]),
          str([r["path"] for r in scanned["files"]]))
    run("select_units.py", "--index", index_path, "--out", out)
    kept = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    check("a module that defines nothing is not selected",
          not [p for p in kept if p.endswith("__init__.py")], str(kept))

    # Every entry point is added whatever the cutoff, which is right with two or three
    # ways in and wrong in a tree of standalone scripts. There the number that decides
    # the cost of the run is not the one that was typed, and it has to say so.
    code, text = run("select_units.py", "--index", index_path, "--out", out, "--top", "1")
    kept = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    over = len(kept) > 2
    check("a selection far over the cutoff says so",
          ("WARN" in text and "--top 1" in text) if over else True, text)
    check("and a selection within it stays quiet",
          "was asked for and" not in run("select_units.py", "--index", index_path,
                                         "--out", out, "--top", "25")[1], text)

    # Same index, same selection -- including the order, which units.txt is a contract for.
    run("select_units.py", "--index", index_path, "--out", out)
    first = open(out, encoding="utf-8").read()
    run("select_units.py", "--index", index_path, "--out", out)
    check("select_units is deterministic", first == open(out, encoding="utf-8").read())

    # Ties used to fall out of dict order. Two modules with the same fan-in must select in
    # path order, or the cutoff moves between runs of the same scan.
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    tied = dict(index)
    tied["fan_in"] = {r["path"]: 1 for r in index["files"]}
    tied_path = os.path.join(tmp, "tied.json")
    write(tied_path, json.dumps(tied))
    code, _ = run("select_units.py", "--index", tied_path, "--out", out, "--top", "2")
    kept = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    check("ties break by path", code == 0 and kept[:2] == sorted(kept[:2]), str(kept))

    # A repository of standalone programs ranks nothing. Built as a real tree and
    # scanned, not by editing an index: the scanner writes `fan_in` by counting incoming
    # edges, so it is *empty* here rather than full of zeroes, and a synthesised map made
    # this pass while the real case selected nothing at all.
    independent = os.path.join(tmp, "independent")
    os.makedirs(independent, exist_ok=True)
    for name in ("tool_a.py", "tool_b.py", "tool_c.py"):
        write(os.path.join(independent, name), "def go():\n    return 1\n")
    flat_index = os.path.join(tmp, "independent.json")
    run("scan_repo.py", "--root", independent, "--out", flat_index, "--detail")
    check("the scanner really does leave fan_in empty here",
          json.load(open(flat_index, encoding="utf-8"))["fan_in"] == {})
    code, text = run("select_units.py", "--index", flat_index, "--out", out)
    kept = [l.strip() for l in open(out, encoding="utf-8") if l.strip()]
    check("a repository with no internal imports still selects its modules",
          code == 0 and len(kept) == 3, "%d: %s" % (code, text[-200:]))
    check("and is warned that the ranking means nothing",
          "carries no information" in text, text)

    code, text = run("select_units.py", "--index", os.path.join(tmp, "nope.json"),
                     "--out", out)
    check("a missing index is an input error", code == 2, text)
    bad = os.path.join(tmp, "bad.json")
    write(bad, json.dumps({"schema_version": 99, "files": []}))
    code, text = run("select_units.py", "--index", bad, "--out", out)
    check("an unsupported schema is an input error", code == 2, text)
    return index_path, root


def driver_tests(tmp, root):
    """pipeline.py: what each component runs, what it skips, and what it will not swallow."""
    build = os.path.join(tmp, "build")

    code, text = run("pipeline.py", "survey", "--root", root, "--build", build,
                     "--dry-run")
    check("survey dry-run runs nothing and exits 0", code == 0, text)
    check("survey names its stages in order",
          text.index("scan_repo") < text.index("validate_index")
          < text.index("select_units"), text)
    check("a stage is named by its component",
          "survey/scan_repo" in text, text[:400])
    check("dry-run writes no index",
          not os.path.exists(os.path.join(build, "structure.json")))

    code, text = run("pipeline.py", "survey", "--root", root, "--build", build,
                     "--policy", "disabled", "--dry-run")
    check("--policy disabled drops the annotation stage",
          "annotate_import_usage" not in text, text)

    code, text = run("pipeline.py", "survey", "--root", root, "--build", build)
    check("survey runs", code == 0, text[-400:])
    check("survey writes the index and the scope",
          os.path.exists(os.path.join(build, "structure.json"))
          and os.path.exists(os.path.join(build, "units.txt")))

    # analyze puts a packet on disk per unit, so the reading that follows can be fanned
    # out without every task re-running the query.
    code, text = run("pipeline.py", "analyze", "--root", root, "--build", build)
    check("analyze runs", code == 0, text[-400:])
    units = [l.strip() for l in
             open(os.path.join(build, "units.txt"), encoding="utf-8") if l.strip()]
    packets = os.listdir(os.path.join(build, "packets"))
    check("analyze writes one packet per unit", len(packets) == len(units),
          "%d packet(s) for %d unit(s)" % (len(packets), len(units)))
    packet = json.load(open(os.path.join(build, "packets", sorted(packets)[0]),
                            encoding="utf-8"))
    check("a captured packet is the packet, not a log", "context_manifest" in packet,
          str(sorted(packet))[:200])
    check("analyze derives the structural claims",
          os.path.exists(os.path.join(build, "claims.jsonl")))

    # Two distinct module paths must not flatten to one packet name, or the second
    # overwrites the first while the component reports success.
    import hashlib
    seen = {}
    for path in ("a/b__c.py", "a__b/c.py", "a/b/c.py"):
        flat = path.replace("/", "__")
        seen.setdefault("%s.%s.json"
                        % (flat, hashlib.sha256(path.encode()).hexdigest()[:8]),
                        []).append(path)
    check("distinct unit paths get distinct packet names",
          all(len(v) == 1 for v in seen.values()), str(seen))

    # A packet left by a wider earlier scope is a module the reader would analyse and
    # `assemble` would then reject as out of scope, after the budget was spent.
    stale = os.path.join(build, "packets", "gone__module.py.deadbeef.json")
    write(stale, "{}")
    code, text = run("pipeline.py", "analyze", "--root", root, "--build", build, "--force")
    check("analyze clears packets from an earlier scope",
          code == 0 and not os.path.exists(stale), text[-200:])
    check("and still writes the current ones",
          len(os.listdir(os.path.join(build, "packets"))) == len(units))

    # A stage that fails must stop its component, and its exit code must arrive unchanged.
    broken = os.path.join(tmp, "broken")
    os.makedirs(broken, exist_ok=True)
    code, text = run("pipeline.py", "check", "--root", root, "--build", broken)
    check("a failing stage stops the component", code != 0, text[-300:])
    check("the failing stage is named", "check/assemble" in text, text[-300:])
    check("a stage that never ran is reported as such",
          "did not run" in text or "last stage" in text, text[-300:])

    # The optional analyses are absent far more often than they are broken.
    code, text = run("pipeline.py", "document", "--root", root, "--build", build,
                     "--docs", os.path.join(tmp, "docs"), "--dry-run")
    check("document skips analyses that were not written",
          text.count("-- skip ") == 5, text)
    check("document says why it skipped each one", "will say so" in text, text)

    # `auto` is not a guess: outside-in is the only preset that renders these analyses.
    check("document defaults to onboarding with no architecture analysis",
          "preset: onboarding" in text, text[:200])
    write(os.path.join(build, "architecture-analysis.json"), "{}")
    code, text = run("pipeline.py", "document", "--root", root, "--build", build,
                     "--docs", os.path.join(tmp, "docs"), "--dry-run")
    check("document switches to outside-in once the analysis exists",
          "preset: outside-in" in text, text[:200])
    check("an existing analysis reaches the model build",
          "--architecture" in text, text)
    code, text = run("pipeline.py", "document", "--root", root, "--build", build,
                     "--docs", os.path.join(tmp, "docs"), "--preset", "architecture",
                     "--dry-run")
    check("--preset overrides the choice", "preset: architecture" in text, text[:200])
    # The three analyses are independently optional, so keying the choice on the
    # architecture file alone would drop a run that only recorded how to operate the
    # repository: onboarding has no builder that reads it.
    os.remove(os.path.join(build, "architecture-analysis.json"))
    write(os.path.join(build, "operations-analysis.json"), "{}")
    code, text = run("pipeline.py", "document", "--root", root, "--build", build,
                     "--docs", os.path.join(tmp, "docs"), "--dry-run")
    check("an operations analysis alone still selects outside-in",
          "preset: outside-in" in text, text[:200])
    os.remove(os.path.join(build, "operations-analysis.json"))
    write(os.path.join(build, "architecture-analysis.json"), "{}")
    code, text = run("pipeline.py", "publish", "--root", root, "--build", build,
                     "--docs", os.path.join(tmp, "docs"), "--dry-run")
    check("publish passes the analyses to the prose check and the gate",
          text.count("--architecture") == 2, text)
    os.remove(os.path.join(build, "architecture-analysis.json"))

    # Hand-written claims are the one thing in the build directory no script can rebuild.
    claims = os.path.join(build, "claims.jsonl")
    with open(claims, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "claim:a-calls-b", "kind": "calls"}) + "\n")
    code, text = run("pipeline.py", "analyze", "--root", root, "--build", build)
    check("analyze refuses to overwrite hand-written claims", code == 1, text[-300:])
    check("the refusal names them", "claim:a-calls-b" in text, text[-300:])
    check("the refusal did not re-derive first",
          "claim:a-calls-b" in open(claims, encoding="utf-8").read())
    code, text = run("pipeline.py", "analyze", "--root", root, "--build", build, "--force")
    check("--force gets past the refusal", code == 0, text[-300:])
    check("survey is not held back by hand-written claims",
          run("pipeline.py", "survey", "--root", root, "--build", build,
              "--dry-run")[0] == 0)

    code, text = run("pipeline.py", "survey", "--root", os.path.join(tmp, "no-such-dir"),
                     "--build", build)
    check("a missing root is an input error", code == 2, text)
    code, text = run("pipeline.py", "publish", "--root", root, "--build", build,
                     "--review", os.path.join(tmp, "no-such-review.jsonl"))
    check("a missing review file is an input error", code == 2, text)
    code, text = run("pipeline.py", "audit", "--root", root, "--build", build)
    check("a component this driver does not have is refused", code != 0, text[-200:])


def diagram_directory_test(tmp):
    """Both diagram families share a directory; neither may report the other as unclaimed."""
    root = os.path.join(tmp, "flow-repo")
    shutil.copytree(FIXTURE, root)
    build = os.path.join(root, ".docs-build")
    diagrams = os.path.join(root, "docs", "_diagrams")
    code, text = run("pipeline.py", "survey", "--root", ".", cwd=root)
    if code != 0:
        check("end-to-end survey", False, text[-300:])
        return

    index = json.load(open(os.path.join(build, "structure.json"), encoding="utf-8"))
    index_hash = index["index_hash"]
    with open(os.path.join(build, "claims.jsonl"), "a", encoding="utf-8") as fh:
        for row in (("claim:entry-calls-normalise", "src/pipeline/entry.py", "main",
                     "src/pipeline/transform.py", "normalise", 7),
                    ("claim:normalise-calls-save", "src/pipeline/transform.py",
                     "normalise", "src/pipeline/store.py", "save", 7)):
            cid, src, sym, dst, target, line = row
            fh.write(json.dumps({
                "id": cid, "kind": "calls", "subject": "symbol:%s:%s" % (src, sym),
                "object": "symbol:%s:%s" % (dst, target),
                "evidence": [{"path": src, "line_start": line, "line_end": line}],
                "index_hash": index_hash}, sort_keys=True) + "\n")
    write(os.path.join(build, "flow-analysis.json"), json.dumps({
        "flow_version": 1, "index_hash": index_hash, "flows": [{
            "id": "flow:save", "name": "Saving a value", "status": "observed",
            "trigger": {"kind": "cli", "text": "The console script runs main.",
                        "status": "declared",
                        "evidence": [{"path": "pyproject.toml", "line_start": 7}]},
            "steps": [
                {"id": "step:1", "from": "symbol:src/pipeline/entry.py:main",
                 "to": "symbol:src/pipeline/transform.py:normalise",
                 "text": "The entry point hands its argument to normalise.",
                 "status": "observed", "claim_ids": ["claim:entry-calls-normalise"],
                 "evidence": [{"path": "src/pipeline/entry.py", "line_start": 7}]},
                {"id": "step:2", "from": "symbol:src/pipeline/transform.py:normalise",
                 "to": "symbol:src/pipeline/store.py:save",
                 "text": "normalise trims the value and passes it on.",
                 "status": "observed", "claim_ids": ["claim:normalise-calls-save"],
                 "evidence": [{"path": "src/pipeline/transform.py", "line_start": 7}]}],
            "outcome": {"status": "observed", "text": "save returns a length.",
                        "evidence": [{"path": "src/pipeline/store.py",
                                      "line_start": 5}]}}]}))

    code, text = run("verify_doc.py", "--claims", os.path.join(build, "claims.jsonl"),
                     "--fragments", os.path.join(build, "claims.jsonl"),
                     "--index", os.path.join(build, "structure.json"),
                     "--root", root, "--out-dir", build)
    code, text = run("validate_flows.py", os.path.join(build, "flow-analysis.json"),
                     "--index", os.path.join(build, "structure.json"),
                     "--claims", os.path.join(build, "claims.verified.jsonl"),
                     "--out", os.path.join(build, "flow-report.json"))
    check("the fixture's flow validates", code == 0, text[-300:])

    graph = os.path.join(build, "class-graph.json")
    run("build_class_graph.py", "--index", os.path.join(build, "structure.json"),
        "--claims", os.path.join(build, "claims.verified.jsonl"), "--out", graph)
    run("build_diagrams.py", "--class-graph", graph, "--out", diagrams)
    run("build_flow_diagrams.py", "--flows", os.path.join(build, "flow-analysis.json"),
        "--report", os.path.join(build, "flow-report.json"), "--out", diagrams)
    code, text = run("validate_flow_diagrams.py", diagrams,
                     "--flows", os.path.join(build, "flow-analysis.json"))
    check("a class view beside a sequence view is not reported as unclaimed",
          code == 0 and "full-repository.puml" not in text, text[-400:])

    # The check still has teeth: a .puml no manifest names is exactly what it is for.
    write(os.path.join(diagrams, "stray.puml"), "@startuml\n@enduml\n")
    code, text = run("validate_flow_diagrams.py", diagrams,
                     "--flows", os.path.join(build, "flow-analysis.json"))
    check("a .puml no manifest names is still reported",
          code == 1 and "stray.puml" in text, text[-300:])


def main():
    tmp = tempfile.mkdtemp(prefix="pipeline-test-")
    try:
        _index, root = units_tests(tmp)
        driver_tests(tmp, root)
        diagram_directory_test(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("FAILED %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all pipeline checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
