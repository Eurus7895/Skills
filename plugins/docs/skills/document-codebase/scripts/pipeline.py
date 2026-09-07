#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/pipeline.py
# Regenerate: python3 tools/materialize.py
"""Run one component of the documentation pipeline, and stop where reading is needed.

    python3 scripts/pipeline.py survey  --root .
    python3 scripts/pipeline.py analyze
    #   ... read the packets; write module-analysis.jsonl and fragments.jsonl ...
    python3 scripts/pipeline.py check
    #   ... write architecture-analysis.json, flow-analysis.json, operations-analysis.json ...
    python3 scripts/pipeline.py document
    python3 scripts/pipeline.py publish --docs docs

Five components, and each is a directory beside this file holding the scripts that answer
one kind of question. `survey` asks what is in the repository, `analyze` what the model
needs in front of it, `check` whether a claim holds, `document` what the pages will say,
`publish` what a reader gets and whether the run may be called done. This driver runs a
component's scripts in order with the arguments that component fixes; nothing here decides
anything a script was already the authority on.

The arguments are the point. They never vary between runs, so typing them out is only ever
a chance to omit one: `--analysis` omitted produced a document that read like an inventory,
`--flow-report` omitted produced counts that included flows nothing had validated. Neither
is reachable from here.

**The pauses between components are the pipeline.** `analyze` ends because a module's
purpose is not in an index; `check` ends because what the modules add up to is not in a
claim; `publish` ends by queueing the sentences only a person can settle. A driver that ran
straight through would be a pipeline that documents nothing.

**A component stops at the first stage that fails, and says which one.** Exit codes pass
through unchanged -- `1` a policy was not met, `2` bad input or a missing dependency, `3`
internal -- so a driver never converts a verdict into silence. Two stages may fail without
stopping their component, and both say so as they do it: `build_flow_diagrams` exits `1`
when nothing was traced, the expected outcome on most repositories, and `check_prose` exits
`1` on a block queued for review, which the final report is meant to carry.

A stage whose input was never written is skipped with the reason printed. The architecture,
flow and operations analyses are optional by design, and a run without them is a visibly
thinner document rather than a failed one.

Standard library only. Exit codes: 0 ok, 1 a stage's policy was not met, 2 input error,
3 internal error.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


class Stage(object):
    """One script invocation, with the conditions under which it runs and may fail.

    `needs` names inputs that must exist; a stage missing one is skipped rather than run,
    because the optional analyses are absent far more often than they are broken.
    `tolerate` names exit codes that do not stop the component -- only for stages whose
    failure is a documented outcome, never to paper over one. `capture` sends stdout to a
    file instead of the terminal, for the stages whose output *is* the artefact.
    """

    def __init__(self, component, script, args, needs=(), tolerate=(), skip_note=None,
                 capture=None, label=None):
        self.component = component
        self.script = script
        self.args = [str(a) for a in args]
        self.needs = list(needs)
        self.tolerate = set(tolerate)
        self.skip_note = skip_note
        self.capture = capture
        self.label = label

    @property
    def name(self):
        stem = self.script[:-3] if self.script.endswith(".py") else self.script
        return "%s/%s%s" % (self.component, stem, self.label or "")

    @property
    def path(self):
        return os.path.join(HERE, self.component, self.script)

    def missing(self):
        return [path for path in self.needs if not os.path.exists(path)]


def run(stages, dry_run=False):
    """Run each stage in order. Returns the exit code the component should report."""
    worst = 0
    for position, stage in enumerate(stages):
        absent = stage.missing()
        if absent:
            note = stage.skip_note or "input not written: %s" % ", ".join(absent)
            print("\n-- skip %s (%s)" % (stage.name, note))
            continue
        command = [sys.executable, stage.path] + stage.args
        print("\n-- %s%s" % (stage.name, " > %s" % stage.capture if stage.capture else ""))
        if dry_run:
            print(" ".join(command))
            continue
        if stage.capture:
            directory = os.path.dirname(stage.capture)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(stage.capture, "w", encoding="utf-8") as fh:
                code = subprocess.call(command, stdout=fh)
        else:
            code = subprocess.call(command)
        if code == 0:
            continue
        if code in stage.tolerate:
            print("-- %s exited %d; the component continues, and the report carries it."
                  % (stage.name, code))
            worst = max(worst, code)
            continue
        remaining = len(stages) - position - 1
        sys.stderr.write("\nFAIL  %s exited %d -- %s\n"
                         % (stage.name, code,
                            "%d later stage(s) did not run." % remaining
                            if remaining else "it was the last stage of this component."))
        return code
    return worst


DERIVED_KINDS = {"defines", "imports", "inherits", "contains"}


def handwritten_claims(path):
    """Claims in `claims.jsonl` that `derive_claims.py` could not have written.

    A `calls` claim needs a call site somebody read, so it is appended here by hand after
    an analyze pass. Re-running `analyze` rewrites the file and would take those with it --
    silently, since a shorter flow analysis validates as cleanly as a longer one. This is
    what makes that loud.
    """
    if not os.path.isfile(path):
        return []
    found = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict) and row.get("kind") not in DERIVED_KINDS:
                    found.append(row.get("id"))
    except (OSError, ValueError):
        # An unreadable claims file is about to be replaced by a good one; that is a
        # repair, not a loss, and nothing here should stand in its way.
        return []
    return found


def units_of(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def survey(args):
    """What is in this repository: scan it, check the index, and pick the scope."""
    index = os.path.join(args.build, "structure.json")
    stages = [
        Stage("survey", "scan_repo.py", ["--root", args.root, "--out", index,
                                         "--summary", "--top", 20, "--detail"]),
        Stage("survey", "validate_index.py", [index, "--root", args.root]),
    ]
    if args.policy != "disabled":
        stages.append(Stage("survey", "annotate_import_usage.py",
                            [index, "--root", args.root, "--policy", args.policy]))
    stages.append(Stage("survey", "select_units.py",
                        ["--index", index, "--top", args.top,
                         "--out", os.path.join(args.build, "units.txt")]))
    return stages


def analyze(args):
    """What the model needs in front of it: the derived claims, and a packet per unit."""
    build = args.build
    index = os.path.join(build, "structure.json")
    units_path = os.path.join(build, "units.txt")
    stages = [
        Stage("analyze", "derive_claims.py", ["--index", index, "--units", units_path,
                                              "--out", os.path.join(build, "claims.jsonl")]),
    ]
    # One packet per unit, on disk rather than on the terminal: a packet is the input to
    # the reading that comes next, and reading it from a file is what lets that reading be
    # fanned out without every task re-running the query.
    for unit in units_of(units_path):
        slug = unit.replace(os.sep, "__").replace("/", "__")
        stages.append(Stage("analyze", "query_graph.py",
                            ["--index", index, "--root", args.root, "--packet", unit],
                            capture=os.path.join(build, "packets", "%s.json" % slug),
                            label=" %s" % unit))
    return stages


def check(args):
    """Whether the claims hold: validate the analysis, gate the fragments, verify."""
    build = args.build
    index = os.path.join(build, "structure.json")
    analysis = os.path.join(build, "module-analysis.jsonl")
    return [
        Stage("check", "validate_analysis.py", [analysis, "--index", index],
              needs=[analysis],
              skip_note="no module-analysis.jsonl -- this run has no reading in it"),
        Stage("check", "assemble.py", [
            "--schema", "fragment_id:str, source:str, role:str, claim_ids:list, status:str",
            "--input", os.path.join(build, "fragments.jsonl"),
            "--unit-list", os.path.join(build, "units.txt"),
            "--unit-field", "source",
            "--out", os.path.join(build, "fragments.csv")]),
        Stage("check", "verify_doc.py", ["--claims", os.path.join(build, "claims.jsonl"),
                                         "--fragments", os.path.join(build, "fragments.jsonl"),
                                         "--index", index, "--root", args.root,
                                         "--out-dir", build]),
    ]


def preset_for(args, architecture):
    """`outside-in` renders the components and the operations; nothing else does.

    Choosing it when those analyses exist is not a judgement call -- every other preset
    drops pages the run has content for. An explicit `--preset` always wins.
    """
    if args.preset != "auto":
        return args.preset
    return "outside-in" if os.path.exists(architecture) else "onboarding"


def document(args):
    """What the pages will say: check the three analyses, draw, then build the model."""
    build, docs = args.build, args.docs
    diagrams = os.path.join(docs, "_diagrams")
    index = os.path.join(build, "structure.json")
    verified = os.path.join(build, "claims.verified.jsonl")
    architecture = os.path.join(build, "architecture-analysis.json")
    flows = os.path.join(build, "flow-analysis.json")
    operations = os.path.join(build, "operations-analysis.json")
    report = os.path.join(build, "flow-report.json")
    graph = os.path.join(build, "class-graph.json")
    preset = preset_for(args, architecture)
    print("preset: %s%s" % (preset, "" if args.preset != "auto" else " (chosen from what "
                            "the build directory holds; --preset overrides)"))

    model = ["--index", index, "--claims", verified,
             "--fragments", os.path.join(build, "fragments.verified.jsonl"),
             "--analysis", os.path.join(build, "module-analysis.jsonl"),
             "--preset", preset, "--diagrams", diagrams,
             "--out", os.path.join(build, "doc.json")]
    for flag, path in (("--architecture", architecture), ("--flows", flows),
                       ("--operations", operations)):
        if os.path.exists(path):
            model.extend([flag, path])

    return [
        Stage("document", "validate_architecture.py",
              [architecture, "--index", index,
               "--analysis", os.path.join(build, "module-analysis.jsonl")],
              needs=[architecture],
              skip_note="no architecture-analysis.json -- the components page will say so"),
        Stage("document", "validate_flows.py",
              [flows, "--index", index, "--claims", verified, "--out", report],
              needs=[flows],
              skip_note="no flow-analysis.json -- the flows page will say so"),
        Stage("document", "validate_operations.py",
              [operations, "--index", index, "--root", args.root],
              needs=[operations],
              skip_note="no operations-analysis.json -- the operations page will say so"),
        Stage("document", "build_class_graph.py",
              ["--index", index, "--claims", verified,
               "--detail", args.detail, "--out", graph]),
        Stage("document", "build_diagrams.py", ["--class-graph", graph, "--out", diagrams]),
        Stage("document", "validate_diagrams.py", [diagrams, "--class-graph", graph]),
        # Exit 1 here means no flow was traceable, which is the common case and not a
        # defect; the flows page says so and the run goes on.
        Stage("document", "build_flow_diagrams.py",
              ["--flows", flows, "--report", report, "--out", diagrams],
              needs=[flows, report], tolerate=(1,),
              skip_note="no validated flow to draw"),
        Stage("document", "validate_flow_diagrams.py", [diagrams, "--flows", flows],
              needs=[flows, report], skip_note="no flow diagram was drawn"),
        Stage("document", "build_document_model.py", model),
    ]


def publish(args):
    """What a reader gets: render it, check the sentences, and report on the run."""
    build, docs = args.build, args.docs
    diagrams = os.path.join(docs, "_diagrams")
    doc = os.path.join(build, "doc.json")
    prose = os.path.join(build, "prose-report.json")
    architecture = os.path.join(build, "architecture-analysis.json")
    flows = os.path.join(build, "flow-analysis.json")
    operations = os.path.join(build, "operations-analysis.json")
    report = os.path.join(build, "flow-report.json")

    render = ["--doc", doc, "--out", docs, "--diagrams", diagrams,
              "--format", args.format, "--check"]
    if args.write_conf:
        render.append("--write-conf")
        if args.project:
            render.extend(["--project", args.project])

    checker = [doc, "--require-review", "--out", prose]
    gate = ["--index", os.path.join(build, "structure.json"),
            "--analysis", os.path.join(build, "module-analysis.jsonl"),
            "--units", os.path.join(build, "units.txt"),
            "--claims", os.path.join(build, "claims.verified.jsonl"),
            "--doc", doc, "--diagrams", diagrams, "--prose", prose,
            "--out", os.path.join(build, "generation-report.json")]
    for flag, path in (("--architecture", architecture), ("--flows", flows),
                       ("--operations", operations)):
        if os.path.exists(path):
            checker.extend([flag, path])
            gate.extend([flag, path])
    if os.path.exists(report):
        gate.extend(["--flow-report", report])
    if args.review:
        checker.extend(["--review", args.review])

    return [
        Stage("publish", "render_docs.py", render),
        # A block queued for review is honest, not broken: quality_docs still has to run
        # so the report carries `review_required` rather than the component ending in
        # silence.
        Stage("publish", "check_prose.py", checker, tolerate=(1,)),
        Stage("publish", "quality_docs.py", gate),
    ]


COMPONENTS = {"survey": survey, "analyze": analyze, "check": check,
              "document": document, "publish": publish}
ORDER = ["survey", "analyze", "check", "document", "publish"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("component", choices=ORDER, metavar="COMPONENT",
                        help="one of: %s" % ", ".join(ORDER))
    parser.add_argument("--root", default=".", help="the repository being documented")
    parser.add_argument("--build", default=".docs-build", help="where intermediates go")
    parser.add_argument("--docs", default="docs", help="where the document is written")
    parser.add_argument("--top", type=int, default=25, help="survey: fan-in cutoff")
    parser.add_argument("--policy", default="optional",
                        choices=("disabled", "optional", "required"),
                        help="survey: whether Ruff annotates import usage")
    parser.add_argument("--force", action="store_true",
                        help="analyze: rewrite claims.jsonl even if it holds hand-written "
                             "claims")
    parser.add_argument("--preset", default="auto",
                        help="document: document preset, or auto")
    parser.add_argument("--detail", default="public",
                        help="document: class-diagram detail")
    parser.add_argument("--format", default="rst", choices=("rst", "myst"),
                        help="publish: markup the renderer emits")
    parser.add_argument("--review", help="publish: prose-review.jsonl with your verdicts")
    parser.add_argument("--write-conf", action="store_true",
                        help="publish: generate a Sphinx conf.py if the output has none")
    parser.add_argument("--project", help="publish: project name for --write-conf")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands this component would run, and run nothing")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        return fail("no such directory: %s" % args.root)
    if args.top < 0:
        return fail("--top must not be negative")
    if args.review and not os.path.isfile(args.review):
        return fail("no such review file: %s" % args.review)
    os.makedirs(args.build, exist_ok=True)

    if args.component == "analyze" and not args.force:
        written = handwritten_claims(os.path.join(args.build, "claims.jsonl"))
        if written:
            return fail("%s holds %d claim(s) no script can regenerate (%s) and this "
                        "component would overwrite them. Move them aside, or pass --force "
                        "if the scan is what changed."
                        % (os.path.join(args.build, "claims.jsonl"), len(written),
                           ", ".join(str(i) for i in written[:3])), 1)

    stages = COMPONENTS[args.component](args)
    print("== %s: %d stage(s)" % (args.component, len(stages)))
    code = run(stages, dry_run=args.dry_run)
    print("\n== %s %s" % (args.component, "ok" if code == 0 else "exited %d" % code))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(3)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
