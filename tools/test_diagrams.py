#!/usr/bin/env python3
"""Behavioral contract for PlantUML generation and semantic validation."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "shared", "scripts", "build_diagrams.py")
VALIDATE = os.path.join(REPO, "shared", "scripts", "validate_diagrams.py")
GRAPH = os.path.join(REPO, "tests", "contracts", "class-graph-v1-minimal.json")
SPEC = os.path.join(REPO, "tests", "contracts", "view-spec-v1-valid.json")
FAILURES = []


def run(*args):
    proc = subprocess.run([sys.executable] + list(args), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def check(label, condition, detail=""):
    if condition:
        print("ok  ", label)
    else:
        print("FAIL", label, detail)
        FAILURES.append(label)


def report(path):
    code, output = run(VALIDATE, path, "--class-graph", GRAPH)
    try:
        return code, json.loads(output)
    except ValueError:
        return code, output


def main():
    work = tempfile.mkdtemp(prefix="plantuml-test-")
    try:
        out = os.path.join(work, "good")
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec", SPEC,
                           "--out", out)
        check("generation succeeds without an external layout engine", code == 0, output)
        files = sorted(os.listdir(out)) if os.path.isdir(out) else []
        check("the canonical PlantUML source and manifest are written",
              files == ["diagram-manifest.json", "full-repository.puml"], repr(files))
        with open(os.path.join(out, "full-repository.puml"), encoding="utf-8") as fh:
            source = fh.read()
        check("the source is a complete PlantUML document",
              source.startswith("@startuml\n") and source.endswith("@enduml\n"))
        check("inheritance direction is represented", "--|>" in source)
        check("composition and its label are represented",
              "*-->" in source and '"engine"' in source)
        check("class members are represented", "+engine: Engine" in source and "+total()" in source)
        check("a relationship legend is present", "legend right" in source)

        if shutil.which("plantuml"):
            proc = subprocess.run(["plantuml", "-tsvg", os.path.join(
                out, "full-repository.puml")], capture_output=True, text=True)
            check("PlantUML renders the generated source to SVG",
                  proc.returncode == 0 and os.path.isfile(os.path.join(
                      out, "full-repository.svg")), proc.stdout + proc.stderr)
        else:
            print("skip PlantUML render check -- plantuml is not on PATH")

        code, result = report(out)
        check("the generated diagram validates", code == 0 and result.get("passed"), repr(result))

        second = os.path.join(work, "second")
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec", SPEC,
                           "--out", second)
        with open(os.path.join(second, "full-repository.puml"), "rb") as fh:
            again = fh.read()
        with open(os.path.join(out, "full-repository.puml"), "rb") as fh:
            first = fh.read()
        check("identical inputs produce identical PlantUML bytes", code == 0 and first == again)

        broken = os.path.join(work, "broken")
        shutil.copytree(out, broken)
        path = os.path.join(broken, "full-repository.puml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("' @node {\"external\":false,\"id\":\"class:pkg/base.py:Record\","
                            "\"module\":\"module:pkg/base.py\"}\n", "", 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        code, result = report(broken)
        check("a removed class declaration is caught", code == 1 and not result["passed"], repr(result))

        # What PlantUML draws is what a reader believes. A class or an arrow added to
        # the source without the matching metadata renders like any other, so the
        # validator has to read the drawing, not only the comments describing it.
        ghost = os.path.join(work, "ghost")
        shutil.copytree(out, ghost)
        path = os.path.join(ghost, "full-repository.puml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("legend right",
                                  'class "GhostAdmin" as n_ghost\n\nlegend right', 1))
        code, result = report(ghost)
        check("a class drawn without metadata is caught", code == 1 and not result["passed"],
              repr(result))

        extra = os.path.join(work, "extra-edge")
        shutil.copytree(out, extra)
        path = os.path.join(extra, "full-repository.puml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        aliases = sorted(set(re.findall(r"n_class_\w+", text)))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("legend right", "%s --|> %s\n\nlegend right"
                                  % (aliases[0], aliases[1]), 1))
        code, result = report(extra)
        check("a relationship drawn without metadata is caught",
              code == 1 and not result["passed"], repr(result))

        malformed = os.path.join(work, "malformed")
        shutil.copytree(out, malformed)
        path = os.path.join(malformed, "full-repository.puml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("@enduml", "", 1))
        code, result = report(malformed)
        check("malformed PlantUML boundaries are caught", code == 1 and not result["passed"],
              repr(result))

        invalid = os.path.join(work, "invalid")
        code, output = run(BUILD, "--class-graph", GRAPH, "--view-spec",
                           os.path.join(REPO, "tests", "contracts",
                                        "view-spec-v1-structural-mutation.json"),
                           "--out", invalid)
        check("a structural view-spec mutation is refused", code == 1, output)

        empty_graph = os.path.join(work, "empty.json")
        with open(GRAPH, encoding="utf-8") as fh:
            graph = json.load(fh)
        graph.update(classes=[], modules=[], packages=[], edges=[])
        with open(empty_graph, "w", encoding="utf-8") as fh:
            json.dump(graph, fh)
        empty_out = os.path.join(work, "empty")
        code, output = run(BUILD, "--class-graph", empty_graph, "--out", empty_out)
        with open(os.path.join(empty_out, "full-repository.puml"), encoding="utf-8") as fh:
            empty_source = fh.read()
        check("an empty valid graph still produces an explicit diagram",
              code == 0 and "No classes detected" in empty_source, output)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if FAILURES:
        print("\n%d failure(s)" % len(FAILURES))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
