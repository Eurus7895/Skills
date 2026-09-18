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
    python3 scripts/pipeline.py render --docs docs
    python3 scripts/pipeline.py review
    python3 scripts/pipeline.py publish --docs docs

Seven runtime components answer one kind of question each. `survey` asks what is in the
repository, `analyze` what the model needs in front of it, `check` whether a claim holds,
`document` what the pages will say, `render` what the draft looks like, `review` whether
that exact draft may ship, and `publish` promotes it. This driver runs a
component's scripts in order with the arguments that component fixes; nothing here decides
anything a script was already the authority on.

The arguments are the point. They never vary between runs, so typing them out is only ever
a chance to omit one: `--analysis` omitted produced a document that read like an inventory,
`--flow-report` omitted produced counts that included flows nothing had validated. Neither
is reachable from here.

**The pauses between components are the pipeline.** `analyze` ends because a module's
purpose is not in an index; `check` ends because what the modules add up to is not in a
claim; `review` ends by queueing the sentences only a person can settle. A driver that ran
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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_dir  # noqa: E402


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
                 capture=None, label=None, script_component=None):
        self.component = component
        self.script = script
        self.args = [str(a) for a in args]
        self.needs = list(needs)
        self.tolerate = set(tolerate)
        self.skip_note = skip_note
        self.capture = capture
        self.label = label
        self.script_component = script_component or component

    @property
    def name(self):
        stem = self.script[:-3] if self.script.endswith(".py") else self.script
        return "%s/%s%s" % (self.component, stem, self.label or "")

    @property
    def path(self):
        return os.path.join(HERE, self.script_component, self.script)

    def missing(self):
        return [path for path in self.needs if not os.path.exists(path)]


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_timing(path, record):
    """Append one measurement without making telemetry a pipeline dependency."""
    if not path:
        return
    try:
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        sys.stderr.write("WARN  could not write timing record: %s\n" % exc)


def run(stages, dry_run=False, timings=None, invocation_id=None):
    """Run each stage in order. Returns the exit code the component should report."""
    worst = 0
    for position, stage in enumerate(stages):
        started_at = utc_now()
        started = time.perf_counter()
        absent = stage.missing()
        if absent:
            note = stage.skip_note or "input not written: %s" % ", ".join(absent)
            print("\n-- skip %s (%s)" % (stage.name, note))
            append_timing(timings, {
                "schema_version": 1, "record_type": "stage",
                "invocation_id": invocation_id, "component": stage.component,
                "stage": stage.name, "status": "skipped", "exit_code": None,
                "started_at": started_at, "finished_at": utc_now(),
                "duration_seconds": round(time.perf_counter() - started, 6),
                "note": note,
            })
            continue
        command = [sys.executable, stage.path] + stage.args
        print("\n-- %s%s" % (stage.name, " > %s" % stage.capture if stage.capture else ""))
        if dry_run:
            print(" ".join(command))
            append_timing(timings, {
                "schema_version": 1, "record_type": "stage",
                "invocation_id": invocation_id, "component": stage.component,
                "stage": stage.name, "status": "dry_run", "exit_code": None,
                "started_at": started_at, "finished_at": utc_now(),
                "duration_seconds": round(time.perf_counter() - started, 6),
            })
            continue
        if stage.capture:
            directory = os.path.dirname(stage.capture)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(stage.capture, "w", encoding="utf-8") as fh:
                code = subprocess.call(command, stdout=fh)
        else:
            code = subprocess.call(command)
        status = "passed" if code == 0 else (
            "tolerated" if code in stage.tolerate else "failed")
        duration = time.perf_counter() - started
        print("-- timing %s %.3fs" % (stage.name, duration))
        append_timing(timings, {
            "schema_version": 1, "record_type": "stage",
            "invocation_id": invocation_id, "component": stage.component,
            "stage": stage.name, "status": status, "exit_code": code,
            "started_at": started_at, "finished_at": utc_now(),
            "duration_seconds": round(duration, 6),
        })
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


def measure(args):
    """Start or stop a model-driven step that runs between component commands."""
    active_path = os.path.join(args.build, "timing-active.json")
    timings = os.path.join(args.build, "timings.jsonl")
    if not (args.step or "").strip():
        return fail("measure requires --step")
    step = args.step.strip()
    if args.state == "start":
        if os.path.isfile(active_path):
            try:
                with open(active_path, encoding="utf-8") as fh:
                    active = json.load(fh)
            except (OSError, ValueError):
                active = {}
            return fail("%s is already being measured; stop it before starting %s"
                        % (active.get("step", "another step"), step), 1)
        record = {"schema_version": 1, "step": step, "started_at": utc_now(),
                  "started_epoch": time.time(), "kind": "model"}
        with open(active_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("timing started: %s" % step)
        return 0
    if not os.path.isfile(active_path):
        return fail("no model step is being measured", 1)
    try:
        with open(active_path, encoding="utf-8") as fh:
            active = json.load(fh)
    except (OSError, ValueError) as exc:
        return fail("cannot read %s: %s" % (active_path, exc))
    if active.get("step") != step:
        return fail("%s is being measured, not %s" % (active.get("step"), step), 1)
    finished = time.time()
    append_timing(timings, {
        "schema_version": 1, "record_type": "model_step", "step": step,
        "status": args.status, "started_at": active.get("started_at"),
        "finished_at": utc_now(),
        "duration_seconds": round(max(0.0, finished - active["started_epoch"]), 6),
    })
    os.remove(active_path)
    print("timing stopped: %s (%s)" % (step, args.status))
    return 0


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


def packet_name(unit):
    """A file name for this unit's packet that no other unit can also produce.

    Flattening separators alone does not: `a/b__c.py` and `a__b/c.py` flatten to the same
    name, and the second packet would overwrite the first while the component reported
    success -- leaving no context for a unit whose analysis is still required. The digest
    of the original path is what makes it injective; the flattened stem is kept so the
    directory is still readable.
    """
    flat = unit.replace(os.sep, "__").replace("/", "__")
    digest = hashlib.sha256(unit.encode("utf-8")).hexdigest()[:8]
    return "%s.%s.json" % (flat, digest)


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
    # Settings are cross-cutting: the answer to "what does this project take" is spread
    # across every file that reads one, which is the shape a per-module packet cannot
    # deliver. Extracting them here, once, is what lets a configuration answer cite
    # something a check passed instead of something the model went looking for.
    config = os.path.join(args.build, "config-analysis.json")
    stages.append(Stage("survey", "extract_config.py",
                        ["--index", index, "--root", args.root, "--out", config]))
    stages.append(Stage("survey", "validate_config.py",
                        [config, "--index", index, "--root", args.root,
                         "--out", os.path.join(args.build, "config-report.json")]))
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
        stages.append(Stage("analyze", "query_graph.py",
                            ["--index", index, "--root", args.root, "--packet", unit],
                            capture=os.path.join(build, "packets", packet_name(unit)),
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


def preset_for(args, *analyses):
    """`manual` is the default deliverable; `--preset` picks any other.

    The older behaviour inferred the preset from which analyses happened to be on disk --
    `outside-in` if any existed, `onboarding` otherwise -- so the shape of the delivered
    document was a side effect of what the run got around to writing. A default is a
    decision and reads better as one.

    The graph-driven presets are still here and still the right answer for an
    architecture report; they are one flag away. What they are no longer is the thing you
    get by not choosing.
    """
    if args.preset != "auto":
        return args.preset
    return "manual"


def document(args):
    """What the pages will say: check the three analyses, draw, then build the model."""
    build = args.build
    diagrams = os.path.join(build, "diagrams")
    index = os.path.join(build, "structure.json")
    verified = os.path.join(build, "claims.verified.jsonl")
    architecture = os.path.join(build, "architecture-analysis.json")
    flows = os.path.join(build, "flow-analysis.json")
    operations = os.path.join(build, "operations-analysis.json")
    config = os.path.join(build, "config-analysis.json")
    report = os.path.join(build, "flow-report.json")
    graph = os.path.join(build, "class-graph.json")
    preset = preset_for(args, architecture, operations, flows)
    print("preset: %s%s" % (preset, "" if args.preset != "auto"
                            else " (the default; --preset overrides)"))

    if preset == "manual":
        answers = os.path.join(build, "manual-analysis.json")
        if not os.path.exists(answers) and args.dry_run:
            # `--dry-run` reports the plan and writes nothing, this draft included.
            print("would write %s and stop: a manual cannot be built before it is "
                  "answered" % answers)
        elif not os.path.exists(answers):
            # Now that `manual` is what you get by not choosing, reaching `document`
            # without an answer artifact is the ordinary first run, not a mistake. Write
            # the draft here rather than failing with a command to go and type -- `--init`
            # refuses to overwrite, so this can never eat answers that already exist.
            argv = [sys.executable, os.path.join(HERE, "document", "manual.py"),
                    "--init", answers, "--index", index,
                    "--authored", os.path.join(build, "authored.jsonl")]
            # The two largest sources of citable ids. Left off, the reading list held only
            # what the three optional analyses contributed -- an end-to-end run offered 2
            # facts where 15 existed -- and an answer cannot be `observed` or `declared`
            # without naming an id the draft never told the model was there.
            for flag, path in (("--claims", verified),
                               ("--analysis", os.path.join(build,
                                                           "module-analysis.jsonl"))):
                if os.path.exists(path):
                    argv.extend([flag, path])
            for flag, path in (("--architecture", architecture), ("--flows", flows),
                               ("--operations", operations), ("--config", config)):
                if os.path.exists(path):
                    argv.extend([flag, path])
            code = subprocess.call(argv)
            if code:
                return fail("could not write %s" % answers, code)
            # Exit 1: a verdict, not breakage. The run cannot build a manual nobody has
            # answered, and saying so is the honest stopping point.
            return fail("answer %s, compose each page's sections from those answers, "
                        "then rerun `document`. `unknown` is for a question the "
                        "repository does not answer, not one nobody looked up." % answers,
                        1)

    model = ["--index", index, "--claims", verified,
             "--fragments", os.path.join(build, "fragments.verified.jsonl"),
             "--analysis", os.path.join(build, "module-analysis.jsonl"),
             "--preset", preset, "--diagrams", diagrams,
             "--out", os.path.join(build, "doc.json")]
    if preset == "manual":
        model.extend(["--manual-analysis", os.path.join(build, "manual-analysis.json"),
                      "--root", args.root,
                      "--authored", os.path.join(build, "authored.jsonl")])
    for flag, path in (("--architecture", architecture), ("--flows", flows),
                       ("--operations", operations), ("--config", config)):
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


def staging_of(args):
    return args.staging or os.path.join(args.build, "rendered-docs")


def render(args):
    """Render a reviewable draft without changing the published documentation."""
    build, staging = args.build, staging_of(args)
    render_args = ["--doc", os.path.join(build, "doc.json"), "--out", staging,
                   "--diagrams", os.path.join(build, "diagrams"),
                   "--format", args.format, "--check"]
    if args.write_conf:
        render_args.append("--write-conf")
        if args.project:
            render_args.extend(["--project", args.project])
    return [
        Stage("render", "prepare_stage.py", ["--source", args.docs, "--out", staging]),
        Stage("render", "render_docs.py", render_args, script_component="publish"),
        Stage("render", "snapshot_draft.py",
              ["--draft", staging, "--doc", os.path.join(build, "doc.json"),
               "--out", os.path.join(build, "render-manifest.json")]),
    ]


def review(args):
    """Review and seal the exact rendered draft; never promote it."""
    build, staging = args.build, staging_of(args)
    diagrams = os.path.join(staging, "_diagrams")
    doc = os.path.join(build, "doc.json")
    prose = os.path.join(build, "prose-report.json")
    architecture = os.path.join(build, "architecture-analysis.json")
    flows = os.path.join(build, "flow-analysis.json")
    operations = os.path.join(build, "operations-analysis.json")
    report = os.path.join(build, "flow-report.json")

    checker = [doc, "--require-review", "--out", prose]
    gate = ["--index", os.path.join(build, "structure.json"),
            "--analysis", os.path.join(build, "module-analysis.jsonl"),
            "--units", os.path.join(build, "units.txt"),
            "--claims", os.path.join(build, "claims.verified.jsonl"),
            "--doc", doc, "--diagrams", diagrams, "--prose", prose,
            "--checkpoints", os.path.join(build, "checkpoints"),
            "--hygiene", os.path.join(build, "hygiene-report.json"),
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

    generation = os.path.join(build, "generation-report.json")
    return [
        Stage("review", "validate_draft.py",
              ["--draft", staging, "--doc", doc,
               "--manifest", os.path.join(build, "render-manifest.json")]),
        # A block queued for review is honest, not broken: quality_docs still has to run
        # so the report carries `review_required` rather than the component ending in
        # silence.
        Stage("review", "check_prose.py", checker, tolerate=(1,),
              script_component="publish"),
        # Between the prose check and the gate, and tolerated, so the gate reads the
        # findings and decides. A tree finding is a real defect and not one that should
        # stop the report that names it.
        #
        # Pointed at the staging draft rather than at `docs`: the shape problems this
        # catches -- two indexes, two configurations, a page the model named and the tree
        # does not hold -- must block publication, and after `publish` has promoted the
        # tree atomically it is too late to say so. `H004`/`H005`, which ask git about
        # committed build output, do not fire on a staging directory that is ignored in
        # its entirety; those are about a published tree and are not what holds a seal.
        Stage("review", "release_hygiene.py",
              ["--docs", staging, "--root", args.root,
               "--doc", os.path.join(build, "doc.json"),
               "--out", os.path.join(build, "hygiene-report.json")],
              tolerate=(1,), script_component="publish"),
        Stage("review", "quality_docs.py", gate, script_component="publish"),
        Stage("review", "seal_draft.py",
              ["--draft", staging, "--doc", doc, "--report", generation,
               "--render-manifest", os.path.join(build, "render-manifest.json"),
               "--out", os.path.join(build, "publish-seal.json")]),
    ]


def publish(args):
    """Promote only the sealed draft; perform no generation or review."""
    return [Stage("publish", "promote_docs.py",
                  ["--draft", staging_of(args), "--target", args.docs,
                   "--doc", os.path.join(args.build, "doc.json"),
                   "--report", os.path.join(args.build, "generation-report.json"),
                   "--seal", os.path.join(args.build, "publish-seal.json")])]


COMPONENTS = {"survey": survey, "analyze": analyze, "check": check,
              "document": document, "render": render, "review": review,
              "publish": publish}
ORDER = ["survey", "analyze", "check", "document", "render", "review", "publish"]

# The judgements the document rests on that no script can make, and the component each
# one stands in front of.
#
# These were written in `SKILL.md` as prose and nothing enforced them, which made them the
# only rule in this pipeline that fails silently. Every other invariant here is a script
# that refuses -- `analyze` will not overwrite hand-written claims, `assemble` will not
# accept a unit with no row, the gate will not call a thin run `passed`. A checkpoint that
# only exists in a paragraph is one a reader skips without ever seeing an error, and then
# a wrong scope or a wrong set of module roles survives every check downstream, because a
# check compares a claim against evidence and never against what the repository is *for*.
#
# P4 was left out of this table once, on the reasoning that a queued block nobody decided
# already holds the run at `review_required`. That confuses two things. Holding the *gate*
# is not opening a *pause*: nothing printed the question, nothing refused to run, and a
# run went all the way to a published manual with twenty blocks queued, zero reviewed, and
# the final validation never executed -- because the workflow was never told to stop.
# P1-P3 stop it by refusing the next component. P4 now does the same.
CHECKPOINTS = (
    {"id": "P1", "opened_by": "survey", "blocks": "analyze",
     "show": "the selected units with their fan-in, the cutoff, and every warning the "
             "selection printed",
     "ask": "is this the right scope to spend the budget on"},
    {"id": "P2", "opened_by": "analyze", "blocks": "check",
     "show": "one line per module -- what you decided it is for -- and every `unknown`",
     "ask": "do these roles match what the repository is"},
    {"id": "P3", "opened_by": "check", "blocks": "document",
     "show": "the components and their boundaries, the flows traced and the ones "
             "refused, the operations found",
     "ask": "is this the architecture, and are the boundaries where they would put them"},
    # Opened by `review` and blocking `review`: the first run queues, and
    # the second -- the one that carries `--review` and reaches the final gate -- is the
    # one held. `opens_when` keeps it quiet on a run that queued nothing, because a
    # checkpoint that opens with no question to ask teaches people to decide it blind.
    {"id": "P4", "opened_by": "review", "blocks": "review", "opens_when": "prose_queued",
     "show": "each queued block beside the evidence under it, and the verb you propose",
     "ask": "are these the intended readings"},
)


def prose_queued(build):
    """Whether `check_prose` left blocks nobody has decided."""
    try:
        with open(os.path.join(build, "prose-report.json"), encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        return False
    coverage = report.get("coverage") or {}
    return (coverage.get("queued") or 0) > (coverage.get("reviewed") or 0)


OPENS_WHEN = {"prose_queued": prose_queued}


def invoked_as():
    """The command the reader typed, so the one this prints can be retyped."""
    return sys.argv[0] or "scripts/pipeline.py"


def checkpoint_path(build, checkpoint_id):
    return os.path.join(build, "checkpoints", "%s.json" % checkpoint_id)


def index_hash_of(build):
    """Which scan the build directory currently describes, or None before the survey."""
    try:
        with open(os.path.join(build, "structure.json"), encoding="utf-8") as fh:
            return json.load(fh).get("index_hash")
    except (OSError, ValueError):
        return None


def decision_for(build, checkpoint_id, digest):
    """A recorded decision on this checkpoint for this scan, or None.

    Bound to `index_hash` for the same reason every other artifact here is: a scope
    approved against one scan says nothing about a tree that has since moved. Rescanning
    reopens the checkpoints, which is the honest outcome -- the units may be different.
    """
    try:
        with open(checkpoint_path(build, checkpoint_id), encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    if record.get("state") != "decided":
        return None
    if digest and record.get("index_hash") != digest:
        return None
    return record


def open_checkpoint(build, checkpoint, digest):
    """Mark a checkpoint pending, unless it is already decided for this scan."""
    if decision_for(build, checkpoint["id"], digest):
        return False
    path = checkpoint_path(build, checkpoint["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"checkpoint": checkpoint["id"], "state": "pending",
                   "index_hash": digest, "show": checkpoint["show"],
                   "ask": checkpoint["ask"]}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return True


# What `status` reads. Every one of these is an artifact some component already writes;
# nothing here is computed a second way. The point is only that one command can read them
# all without running a stage, because the session that needs them most is the one that
# cannot run a stage.
READ_KINDS = ("responsibility", "state", "interface", "failure")
READ_KINDS_FLOOR = 2                      # the same bar quality_docs applies


def _json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [line for line in (l.strip() for l in fh) if line]
    except OSError:
        return []


def analysis_progress(build):
    """(in scope, read, remaining) module paths, from units.txt and module-analysis.jsonl.

    **This is the number a resumed session actually needs, and it was the one it could not
    get.** `quality_docs.py` computes it and names the remainder, but that runs in
    `publish` -- and a partial analysis fails `check` first, so a run interrupted halfway
    through the modules could not reach the report that would say which half. Nothing was
    missing from the pipeline except a way to ask without running it.

    `read` uses the same floor as the gate: at least `READ_KINDS_FLOOR` of the four module
    kinds. A module named once and left there is not a module that was read.
    """
    scope = _lines(os.path.join(build, "units.txt"))
    kinds = {}
    for line in _lines(os.path.join(build, "module-analysis.jsonl")):
        try:
            row = json.loads(line)
        except ValueError:
            continue                       # validate_analysis owns the verdict on this
        path = row.get("path")
        if not path:
            continue
        kinds.setdefault(path, set()).update(
            s.get("kind") for s in row.get("statements", ()) if isinstance(s, dict))
    read = [p for p in scope
            if len(kinds.get(p, set()) & set(READ_KINDS)) >= READ_KINDS_FLOOR]
    # Touched but not read is its own state, and the one a resumed session most needs
    # told apart: a module with a single statement has work already in it, and reporting
    # it beside the untouched ones invites someone to write it a second time.
    touched = [p for p in scope if p in kinds and p not in set(read)]
    untouched = [p for p in scope if p not in kinds]
    return scope, read, touched, untouched


def status(args, build):
    """Where the run is, read-only, and never blocked by anything.

    A checkpoint refuses to let the next component run, and a failing stage stops the ones
    behind it -- both correct, and between them they mean the state of a run is only ever
    reported by something that might decline to report it. This declines nothing: it runs
    no stage, writes nothing, and answers the same whether the last component passed,
    failed, or was never reached.
    """
    digest = index_hash_of(build)
    if not digest:
        print("no scan yet in %s. Start with: python3 %s survey --root %s"
              % (build, os.path.basename(__file__), args.root))
        return 0
    index = _json(os.path.join(build, "structure.json"), {}) or {}
    source = index.get("source") or {}
    print("scan       %s" % digest)
    print("           revision %s%s"
          % (source.get("revision") or "untracked",
             " (uncommitted changes when scanned)" if source.get("dirty") else ""))

    print("\ncheckpoints")
    for checkpoint in CHECKPOINTS:
        path = checkpoint_path(build, checkpoint["id"])
        decided = decision_for(build, checkpoint["id"], digest)
        if decided:
            state = "decided -- %s" % (decided.get("note") or "no note recorded")
        elif os.path.isfile(path):
            # Stale means opened against an earlier scan: the units may now be different,
            # so the question has to be asked again rather than inherited.
            stale = (_json(path, {}) or {}).get("index_hash") != digest
            state = "OPEN (from an earlier scan)" if stale else "OPEN"
            state += " -- blocks %s" % checkpoint["blocks"]
        else:
            state = "not opened yet (%s opens it)" % checkpoint["opened_by"]
        print("  %-3s %s" % (checkpoint["id"], state))

    scope, read, touched, untouched = analysis_progress(build)
    if scope:
        print("\nmodules    %d in scope, %d read, %d partly written, %d not started"
              % (len(scope), len(read), len(touched), len(untouched)))
        for label, paths in (("finish", touched), ("start", untouched)):
            for path in paths[:10]:
                print("           %-6s %s" % (label, path))
            if len(paths) > 10:
                print("           %-6s ... and %d more" % ("", len(paths) - 10))

    manual = _json(os.path.join(build, "manual-analysis.json"))
    if isinstance(manual, dict):
        answers = manual.get("answers") or {}
        answered = sum(1 for a in answers.values()
                       if isinstance(a, dict)
                       and a.get("completeness") not in (None, "unanswered"))
        composed = sum(len((p or {}).get("sections") or [])
                       for p in (manual.get("pages") or {}).values())
        print("\nmanual     %d of %d question(s) answered, %d section(s) composed"
              % (answered, len(answers), composed))

    ledger = [json.loads(l) for l in _lines(os.path.join(build, "authored.jsonl"))]
    if ledger:
        settled = [r for r in ledger if r.get("status") in ("complete", "waived")]
        print("authored   %d of %d page(s) settled" % (len(settled), len(ledger)))
        for row in ledger:
            if row.get("status") not in ("complete", "waived"):
                print("           - %s (%s)" % (row.get("page_id"), row.get("status")))

    report = _json(os.path.join(build, "prose-report.json"))
    if isinstance(report, dict):
        print("review     %d block(s) queued, %d reviewed"
              % (len(report.get("queue") or ()), report.get("reviewed") or 0))

    print("\nnext       %s" % next_step(build, digest, remaining=touched + untouched))
    return 0


def next_step(build, digest, remaining):
    """One line naming the next action, in the order the run would hit them.

    A checkpoint first, because nothing downstream of an unanswered question runs anyway.
    Then work that is the model's rather than a component's -- an unread module, an
    unanswered question -- because those are what a resumed session is most likely to
    think is already done.
    """
    for component in ORDER:
        blocking = blocking_checkpoint(build, component, digest)
        if blocking:
            return "decide %s (%s) -- it blocks %s" % (
                blocking["id"], blocking["ask"], blocking["blocks"])
    if remaining:
        return ("write the analysis for %d remaining module(s), appending one scope at a "
                "time, then run check" % len(remaining))
    manual = _json(os.path.join(build, "manual-analysis.json"))
    if isinstance(manual, dict):
        answers = manual.get("answers") or {}
        open_questions = [q for q, a in answers.items() if isinstance(a, dict)
                          and a.get("completeness") in (None, "unanswered")]
        if open_questions:
            return "answer %d remaining question(s) in manual-analysis.json" % \
                len(open_questions)
        if not any((p or {}).get("sections") for p in (manual.get("pages") or {}).values()):
            return "compose each page's sections from the answers"
    return "run the next component: it has the inputs it needs"


def blocking_checkpoint(build, component, digest):
    """The open checkpoint standing in front of this component, if there is one.

    A checkpoint that was never opened does not block. It is opened by the component
    before it, so its absence means that component never succeeded -- and then the honest
    error is the one this component's own first stage gives about its missing input, not
    a question about a decision nobody was ever asked to make.

    **An open checkpoint blocks every component after it, not only the next one.** A
    build directory that already holds artifacts from an earlier run is the case: with
    `P1` open again, blocking only `analyze` still leaves `document` and `publish` free to
    run over what is already on disk and produce a finished report with the scope decision
    outstanding. The rule is that nothing downstream of an unanswered question runs, so
    the first open checkpoint at or before this component in the order is the one that
    holds it.
    """
    try:
        position = ORDER.index(component)
    except ValueError:
        return None
    for checkpoint in CHECKPOINTS:
        if ORDER.index(checkpoint["blocks"]) > position:
            continue
        if not os.path.isfile(checkpoint_path(build, checkpoint["id"])):
            continue
        if not decision_for(build, checkpoint["id"], digest):
            return checkpoint
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("component", choices=ORDER + ["decide", "measure", "status"],
                        metavar="COMPONENT",
                        help="one of: %s, decide, measure, or status" % ", ".join(ORDER))
    parser.add_argument("--checkpoint", help="decide: which checkpoint (P1, P2, P3, P4)")
    parser.add_argument("--note", help="decide: what was decided, and by whom -- this is "
                                       "what the closing report carries")
    parser.add_argument("--step", help="measure: model-driven step name")
    parser.add_argument("--state", choices=("start", "stop"), default="start",
                        help="measure: start or stop the named step")
    parser.add_argument("--status", choices=("completed", "failed", "cancelled"),
                        default="completed", help="measure --state stop: outcome")
    parser.add_argument("--root", default=".", help="the repository being documented")
    parser.add_argument("--build", default=".docs-build", help="where intermediates go")
    parser.add_argument("--docs", default="docs", help="where the document is written")
    parser.add_argument("--staging", help="rendered draft directory; defaults to "
                                          ".docs-build/rendered-docs")
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
                        help="render: markup the renderer emits")
    parser.add_argument("--review", help="review: prose-review.jsonl with your verdicts")
    parser.add_argument("--write-conf", action="store_true",
                        help="render: generate a Sphinx conf.py in staging if none exists")
    parser.add_argument("--project", help="render: project name for --write-conf")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands this component would run, and run nothing")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        return fail("no such directory: %s" % args.root)
    if args.top < 0:
        return fail("--top must not be negative")
    if args.review and not os.path.isfile(args.review):
        return fail("no such review file: %s" % args.review)

    # Ahead of `build_dir.ensure`, deliberately. `status` answers questions about a run and
    # must not start one: creating the build directory to report that there is no build
    # directory would be the command changing the thing it was asked to describe.
    if args.component == "status":
        return status(args, args.build)

    build_dir.ensure(args.build)
    digest = index_hash_of(args.build)

    if args.component == "measure":
        if args.dry_run:
            print("would %s timing for %s" % (args.state, args.step or "<missing step>"))
            return 0
        return measure(args)

    if args.component == "decide":
        known = {c["id"]: c for c in CHECKPOINTS}
        if args.checkpoint not in known:
            return fail("--checkpoint must be one of: %s" % ", ".join(sorted(known)))
        if not (args.note or "").strip():
            return fail("--note is required: a decision with no record of what was "
                        "decided is not one the closing report can carry")
        path = checkpoint_path(args.build, args.checkpoint)
        # Only a checkpoint that is actually open may be decided. Without this a caller
        # can answer a question nobody has been asked yet -- decide `P2` straight after
        # `survey`, and when `analyze` later finishes it finds a decision carrying the
        # current `index_hash`, leaves it alone, and `check` runs with the module roles
        # unreviewed. Pre-approval defeats the whole mechanism, and it is the shape a
        # script written for the old behaviour naturally takes.
        if not os.path.isfile(path):
            return fail("%s has not been opened yet, so there is nothing to decide: %s "
                        "opens it, and a decision recorded before the question exists "
                        "is not one anybody answered."
                        % (args.checkpoint, known[args.checkpoint]["opened_by"]), 1)
        if args.dry_run:
            print("would record %s: %s" % (args.checkpoint, args.note.strip()))
            print("would write %s" % path)
            return 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"checkpoint": args.checkpoint, "state": "decided",
                       "index_hash": digest, "note": args.note.strip(),
                       "ask": known[args.checkpoint]["ask"]}, fh, indent=1,
                      sort_keys=True)
            fh.write("\n")
        print("%s decided: %s" % (args.checkpoint, args.note.strip()))
        print("wrote %s" % path)
        return 0

    # Refuse rather than run on. The message has to be enough to act on without opening
    # anything: what to put in front of the person, what to ask them, and the one command
    # that records the answer.
    if not args.dry_run:
        blocked = blocking_checkpoint(args.build, args.component, digest)
        if blocked is not None:
            sys.stderr.write(
                "FAIL  %s is held at checkpoint %s, which %s opens and nothing has "
                "decided.\n"
                "      Show them: %s\n"
                "      Ask them:  %s\n"
                "      Then:      python3 %s decide --checkpoint %s --note '<what they "
                "said>'\n"
                "      Running unattended is a decision too -- record what you chose and "
                "why, and it will be in the closing report.\n"
                % (args.component, blocked["id"], blocked["opened_by"], blocked["show"],
                   blocked["ask"], invoked_as(), blocked["id"]))
            return 1

    if args.component == "analyze" and not args.force:
        written = handwritten_claims(os.path.join(args.build, "claims.jsonl"))
        if written:
            return fail("%s holds %d claim(s) no script can regenerate (%s) and this "
                        "component would overwrite them. Move them aside, or pass --force "
                        "if the scan is what changed."
                        % (os.path.join(args.build, "claims.jsonl"), len(written),
                           ", ".join(str(i) for i in written[:3])), 1)

    if args.component == "analyze" and not args.dry_run:
        # The skill tells the reader to work through every file in packets/, so one left
        # behind by a wider earlier scope is a module they would analyse and `assemble`
        # would then reject as outside the current units -- after the budget was spent.
        packets = os.path.join(args.build, "packets")
        if os.path.isdir(packets):
            shutil.rmtree(packets)

    component_started_at = utc_now()
    component_started = time.perf_counter()
    invocation_id = "%s-%d" % (args.component, time.time_ns())
    stages = COMPONENTS[args.component](args)
    if isinstance(stages, int):
        # A component may end the run before it has any stage to run: `document` does it
        # when a manual has no answer artifact yet, which is a verdict about the run
        # rather than a stage that failed. The code is the exit code.
        append_timing(os.path.join(args.build, "timings.jsonl"), {
            "schema_version": 1, "record_type": "component",
            "invocation_id": invocation_id, "component": args.component,
            "status": "passed" if stages == 0 else "failed", "exit_code": stages,
            "started_at": component_started_at, "finished_at": utc_now(),
            "duration_seconds": round(time.perf_counter() - component_started, 6),
        })
        return stages
    print("== %s: %d stage(s)" % (args.component, len(stages)))
    timings = None if args.dry_run else os.path.join(args.build, "timings.jsonl")
    code = run(stages, dry_run=args.dry_run, timings=timings,
               invocation_id=invocation_id)
    if not args.dry_run:
        append_timing(timings, {
            "schema_version": 1, "record_type": "component",
            "invocation_id": invocation_id, "component": args.component,
            "status": "passed" if code == 0 else "failed", "exit_code": code,
            "started_at": component_started_at, "finished_at": utc_now(),
            "duration_seconds": round(time.perf_counter() - component_started, 6),
            "stage_count": len(stages),
        })
    print("\n== %s %s" % (args.component, "ok" if code == 0 else "exited %d" % code))

    # Ordinarily a checkpoint opens only on success: a failed survey has no scope to
    # approve. A conditional checkpoint is different. P4 is intentionally produced by
    # the review-required result (exit 1), so its predicate -- the report the stage just
    # wrote -- is the authority on whether there is material to review.
    if not args.dry_run:
        for checkpoint in CHECKPOINTS:
            if checkpoint["opened_by"] != args.component:
                continue
            condition = OPENS_WHEN.get(checkpoint.get("opens_when"))
            if code != 0 and condition is None:
                continue
            if condition and not condition(args.build):
                continue
            if open_checkpoint(args.build, checkpoint, index_hash_of(args.build)):
                print("\n-- checkpoint %s is open, and %s will not run until it is "
                      "decided.\n   Show them: %s\n   Ask them:  %s\n   Then:      "
                      "python3 %s decide --checkpoint %s --note '<what they said>'"
                      % (checkpoint["id"], checkpoint["blocks"], checkpoint["show"],
                         checkpoint["ask"], invoked_as(), checkpoint["id"]))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(3)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
