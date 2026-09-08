#!/usr/bin/env python3
"""Say what the run actually produced, and refuse to call the shortcut a success.

    python3 scripts/quality_docs.py --index .docs-build/structure.json \\
        --analysis .docs-build/module-analysis.jsonl \\
        --units .docs-build/units.txt --doc .docs-build/doc.json \\
        --out .docs-build/generation-report.json

Every other check in this pipeline asks whether an artifact is internally consistent.
They all pass on a document derived entirely from `structure.json`, because a claim
taken out of the index and checked against the index agrees with itself. This one asks
the question none of them can: **how much of this was read, and how much was copied?**

    per_module     nine in ten modules answer all four module questions
    partial        half were read, but fewer than nine in ten were answered in full
    derived_only   fewer than half were read, or nothing was written at all

A module is *read* when it answers two of the four -- responsibility, state, interface,
failure -- and *answered in full* when it answers all of them. Two tiers because they
fail differently: too few modules read is a dispatch that stopped early, while enough
read and few answered in full is the document that has every module in it and a line
under each heading. One surviving statement used to be the whole bar, and a run of
one-line modules reported `per_module` at coverage 1.0.

`passed` is impossible under `derived_only`, whatever else is green. A document with no
reading in it can still be true -- it is `structure.json` in prose, and every sentence
checks out -- so nothing else in the pipeline has grounds to reject it. That is exactly
why the count has to be stated rather than inferred from an absence of complaints.

**The budget is not a failure.** `units.txt` names the modules a run pays to read, and
everything outside it is covered in a line. Those modules are counted separately and
never drag the coverage down; a run that analysed everything it set out to analyse is
`per_module` on a repository of four files and on one of four thousand.

Standard library only, plus this directory's own `validate_analysis`. Reads; writes only
where `--out` says to.

Exit codes: 0 ok, 1 the run does not meet the policy asked for, 2 input error,
3 internal error.
"""

import argparse
import json
import os
import sys

# The gate is the one script that reads across components: it counts statements the way
# `check` validates them and it needs the presets `document` builds from, so both have to
# agree with it or the figures would be about a different document. The layout is the same
# in `shared/` and in a materialized plugin, so this resolves in both.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _sibling in ("check", "document"):
    sys.path.insert(0, os.path.join(os.path.dirname(_HERE), _sibling))

import validate_analysis  # noqa: E402
from build_document_model import PRESETS  # noqa: E402

REPORT_VERSION = 1

PER_MODULE = "per_module"
PARTIAL = "partial"
DERIVED_ONLY = "derived_only"

PASSED, STATUS_PARTIAL, FAILED = "passed", "partial", "failed"

# A bounded model pass ran out of attempts, tokens or time before it could decide.
# Nothing was learned, so this is neither a defect in what was checked nor a pass -- the
# same distinction sphinx_support.py draws between `skipped` and `runner_failure`. It
# ranks below partial so it can never be reported as one, and above failed because a real
# defect outranks "could not tell".
REVIEW_REQUIRED = "review_required"

# Where the two lines sit. Nine in ten leaves room for a module whose only honest
# statement was unanchored; half is where a document stops being an account of the
# repository and starts being an index with sentences around it.
PER_MODULE_COVERAGE = 0.90
PARTIAL_COVERAGE = 0.50

# A module counts as read once it answers two of the four questions below, and the run
# may only call itself `per_module` when nine in ten answer all four.
#
# One statement was the old bar, and it let a run report `per_module` at coverage 1.0
# while the median module answered one question -- true in every particular and an
# outline to read. Two is where a reading starts: a module with a responsibility and an
# interface has been looked at, a module with a responsibility alone has been named.
# Four is what a module page renders, so a module short of it is a heading with nothing
# under it.
READ_KINDS_FLOOR = 2

# The four questions that are about a module rather than about the tree it sits in.
# `interaction` and `rationale` are the architecture's, and a module page renders exactly
# these -- `COVERS["modules"]` in `build_document_model`, which is where a reader meets
# them as four headings. Depth is measured against them for that reason: a module missing
# one is a heading with nothing under it.
MODULE_KINDS = ("responsibility", "state", "interface", "failure")

# Rejections that mean the evidence could not be looked at, as opposed to the statement
# being malformed. Reported apart because they call for a different fix.
EVIDENCE_CODES = ("A004", "A006", "A007", "A008", "A015")

# Detector B. Above the first, the components are the directories; between the two, they
# may be -- a repository is allowed to be organised the way its architecture is, so that
# band is reported rather than fatal.
DETECTOR_B_FAIL = 0.95
DETECTOR_B_PARTIAL = 0.85

RANK = {FAILED: 0, REVIEW_REQUIRED: 1, STATUS_PARTIAL: 2, PASSED: 3}
MODE_RANK = {DERIVED_ONLY: 0, PARTIAL: 1, PER_MODULE: 2}


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def budget_of(index, units_path):
    """The modules this run undertook to read.

    With no `units.txt` the budget is every non-test module, which is what a small
    repository does anyway. The report says which of the two it was, because
    `coverage: 1.0` means different things under each.
    """
    modules = [record["path"] for record in index.get("files", ())
               if not record.get("is_test") and record.get("symbols")]
    if not units_path:
        return sorted(modules), "every non-test module (no units.txt given)"
    known = set(modules) | {record["path"] for record in index.get("files", ())}
    with open(units_path, encoding="utf-8") as fh:
        wanted = [line.strip() for line in fh if line.strip()]
    unknown = [path for path in wanted if path not in known]
    if unknown:
        raise ValueError("units.txt names %d path(s) the index does not hold: %s"
                         % (len(unknown), ", ".join(sorted(unknown)[:3])))
    return sorted(set(wanted)), "units.txt"


def analyse(index, analysis_path):
    """Run C2's checker and turn its verdicts into counts.

    Returns `(kinds_by_path, tally, findings)`. The first is what a module was actually
    asked and answered -- not whether it was read, which is a weaker thing entirely.
    """
    rows = load_jsonl(analysis_path)
    checker = validate_analysis.Checker(index)
    verdicts, seen = {}, set()
    for row in rows:
        verdicts.update(checker.check_row(row, seen))
    checker.check_repetition(rows, verdicts)
    checker.check_relatedness(rows)

    evidence_failures = {finding["statement"] for finding in checker.findings
                         if finding["code"] in EVIDENCE_CODES and finding["statement"]}
    by_kind, by_status = {}, {}
    kinds_by_path = {}
    for row in rows:
        for statement in row.get("statements", ()):
            if not isinstance(statement, dict):
                continue
            by_kind[statement.get("kind")] = by_kind.get(statement.get("kind"), 0) + 1
            by_status[statement.get("status")] = by_status.get(
                statement.get("status"), 0) + 1
            if verdicts.get(statement.get("id")) == "valid":
                kinds_by_path.setdefault(row.get("path"), set()).add(
                    statement.get("kind"))

    tally = {"total": len(verdicts), "valid": 0, "unanchored": 0,
             "near_duplicate": 0, "rejected": 0}
    for verdict in verdicts.values():
        tally[verdict] = tally.get(verdict, 0) + 1
    tally["with_valid_evidence"] = tally["total"] - len(evidence_failures)
    tally["by_kind"] = by_kind
    tally["by_status"] = by_status
    return kinds_by_path, tally, checker.findings


def depth_of(kinds_by_path, in_budget):
    """How many of the four module questions each module in the budget answered.

    Coverage says a module was read. It says so on one surviving statement, which is why
    a run can be `per_module` and still render a page with four headings and one line
    under them -- the shape the reader complains about, and the shape no other check in
    this pipeline can see.

    `unknown` is a status, not a silence: a module with nothing recorded about how it
    fails answers that question with a `failure`/`unknown` statement. So a missing kind
    here means the question went unasked, never that the repository had no answer.
    """
    counts = [len(set(kinds_by_path.get(path, ())) & set(MODULE_KINDS))
              for path in in_budget]
    histogram = {str(n): counts.count(n) for n in range(len(MODULE_KINDS) + 1)}
    # Lower median on an even split. Two modules answering one and four questions is a
    # run with a hole in it, and reporting that as "the median module answers four"
    # would round in the run's own favour -- the one direction this file must not.
    ordered = sorted(counts)
    median = ordered[(len(ordered) - 1) // 2] if ordered else 0
    thin = sorted(path for path in in_budget
                  if len(set(kinds_by_path.get(path, ())) & set(MODULE_KINDS))
                  < len(MODULE_KINDS))
    return {
        "kinds": list(MODULE_KINDS),
        "histogram": histogram,
        "median_kinds": median,
        "full": len(in_budget) - len(thin),
        "thin": thin[:20],
    }


def decisions_of(directory):
    """What was decided at each checkpoint, and what is still open.

    The report is where a run is accounted for afterwards, and "who agreed this scope" is
    part of that account. A run made unattended is a legitimate answer and shows up here
    as one -- which is the point of requiring the note.
    """
    decided, pending = [], []
    if not directory or not os.path.isdir(directory):
        return {"decided": decided, "pending": pending}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        entry = {"checkpoint": record.get("checkpoint"), "ask": record.get("ask")}
        if record.get("state") == "decided":
            entry["note"] = record.get("note")
            decided.append(entry)
        else:
            pending.append(entry)
    return {"decided": decided, "pending": pending}


def mode_of(coverage, full_ratio, statements):
    """The mode, from how many modules were read and how many were answered in full.

    Two tiers, because they fail differently and the fix differs with them. `coverage`
    asks how many modules were read at all; `full_ratio` asks how many answered all four
    questions their page renders. A run can be excellent on the first and poor on the
    second -- that is a document with every module present and most of them a line long,
    and it is `partial`, not `per_module`.
    """
    if not statements:
        return DERIVED_ONLY
    if coverage >= PER_MODULE_COVERAGE and full_ratio >= PER_MODULE_COVERAGE:
        return PER_MODULE
    if coverage >= PARTIAL_COVERAGE:
        return PARTIAL
    return DERIVED_ONLY


def rand_index(left, right, keys):
    """The fraction of pairs the two partitions classify the same way.

    Pair counting rather than label matching, because the labels are the thing under
    suspicion: a synthesis that renamed every directory and moved nothing is exactly what
    this has to catch, and comparing names would call that a difference.
    """
    keys = sorted(keys)
    if len(keys) < 2:
        return 1.0
    same = total = 0
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            total += 1
            if (left.get(a) == left.get(b)) == (right.get(a) == right.get(b)):
                same += 1
    return same / float(total) if total else 1.0


def normalise_name(text):
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def detector_b(architecture):
    """Is this a synthesis, or the directory tree with better nouns?

    Returns a dict; the verdict is in `outcome`. `not_applicable` is a real answer and
    not a pass: below two directories or two components there is no partition to compare,
    and the index would read 1.0 for every small repository purely for being small.
    """
    components = [c for c in architecture.get("components", ()) if isinstance(c, dict)]
    by_component, placed = {}, []
    for component in components:
        for path in component.get("modules", ()) or ():
            by_component[path] = component.get("id")
            placed.append(path)
    by_directory = {path: os.path.dirname(path) or "." for path in by_component}

    directories = set(by_directory.values())
    result = {"components": len(components), "directories": len(directories),
              "modules_placed": len(by_component)}
    if len(components) < 2 or len(directories) < 2:
        result.update(outcome="not_applicable", agreement=None,
                      detail="%d component(s) over %d director(y/ies): there is no "
                             "partition to compare" % (len(components), len(directories)))
        return result

    agreement = rand_index(by_component, by_directory, by_component)
    result["agreement"] = round(agreement, 4)

    # The pure rename: same grouping, and every component named after the directory it
    # contains. Nothing merged, nothing split, nothing named for what it does.
    renamed = False
    if agreement >= 1.0:
        renamed = True
        for component in components:
            members = component.get("modules", ()) or ()
            folders = {os.path.dirname(p) or "." for p in members}
            leaf = normalise_name(os.path.basename(sorted(folders)[0])) if folders else ""
            if normalise_name(component.get("name", "")) != leaf:
                renamed = False
                break
    result["is_directory_rename"] = renamed

    # What the synthesis holds that a path cannot give. This does not change the verdict
    # -- softening the threshold would hand back the escape hatch the detector closes --
    # but a maintainer reading `agreement 0.97, independent content 0.9` can see the
    # difference the index cannot, and decide whether the threshold is what to revisit.
    external = {e.get("id") for e in architecture.get("external_systems", ()) or ()
                if isinstance(e, dict)}
    linked = set()
    for relationship in architecture.get("relationships", ()) or ():
        if isinstance(relationship, dict):
            if relationship.get("to") in external:
                linked.add(relationship.get("from"))
            if relationship.get("from") in external:
                linked.add(relationship.get("to"))
    earned = 0
    for component in components:
        folders = {os.path.dirname(p) or "." for p in component.get("modules", ()) or ()}
        if ((component.get("rationale") or {}).get("status") not in (None, "unknown")
                or component.get("id") in linked or len(folders) > 1):
            earned += 1
    result["independent_content"] = round(earned / float(len(components)), 4)

    if renamed:
        result.update(outcome="failed",
                      detail="the components are the directories, renamed to match: "
                             "nothing was merged, split, or named for what it does")
    elif agreement >= DETECTOR_B_FAIL:
        result.update(outcome="failed",
                      detail="components and directories agree on %.0f%% of module "
                             "pairs; %.0f%% of components carry something a path cannot "
                             "give" % (agreement * 100,
                                       result["independent_content"] * 100))
    elif agreement >= DETECTOR_B_PARTIAL:
        result.update(outcome="partial",
                      detail="components and directories agree on %.0f%% of module pairs"
                             % (agreement * 100))
    else:
        result.update(outcome="passed",
                      detail="the grouping is not the directory tree")
    return result


def flow_report(flows, validation=None):
    """What was traced, what was refused, and whether absence was stated.

    The denominator C6 left open. It is deliberately not a percentage: a repository with
    one traceable flow and one refused is not "50% documented", it is a document with a
    hole in a named place.

    Counting every entry in the analysis overstated it. `validate_flows.py` refuses a
    flow without removing it from the file -- that is the supported workflow, and the
    diagram builder skips it -- so the raw list holds flows nothing vouches for. With the
    validation report the counts are of accepted flows only, and `refused` is reported
    beside them; without it nothing here has been checked and the caller is told so.
    """
    entries = [f for f in flows.get("flows", ()) or () if isinstance(f, dict)]
    absent = flows.get("absent")
    accepted = None
    if isinstance(validation, dict):
        accepted = set(validation.get("accepted", ()))
        entries = [f for f in entries if f.get("id") in accepted]
    return {
        "flows": len(entries),
        "steps": sum(len(f.get("steps") or ()) for f in entries),
        "unresolved": sum(len(f.get("unresolved") or ()) for f in entries),
        "refused": len(validation.get("refused", ())) if accepted is not None else None,
        "validated": accepted is not None,
        "absent_stated": bool(isinstance(absent, dict) and absent.get("reason")),
    }


def operations_report(operations):
    procedures = [p for p in operations.get("procedures", ()) or ()
                  if isinstance(p, dict)]
    steps = [s for p in procedures for s in (p.get("steps") or ())
             if isinstance(s, dict)]
    absent = operations.get("absent")
    return {
        "procedures": len(procedures),
        "kinds": sorted({p.get("kind") for p in procedures if p.get("kind")}),
        "commands": sum(1 for s in steps if s.get("command")),
        "requirements": len([r for r in operations.get("requirements", ()) or ()
                             if isinstance(r, dict)]),
        "absent_stated": bool(isinstance(absent, dict) and absent.get("reason")),
    }


def page_report(doc):
    preset = doc.get("preset")
    pages = {page["id"] for page in doc.get("pages", ())}
    required = [page_id for page_id, _, mandatory, _ in PRESETS.get(preset, ())
                if mandatory]
    return {"preset": preset, "generated": len(pages), "mandatory": len(required),
            "missing": sorted(set(required) - pages)}


def diagram_report(directory):
    manifest, error = load_json(os.path.join(directory, "diagram-manifest.json"),
                                "diagram manifest")
    if error:
        return {"views": 0, "repository_view": False, "error": error}
    views = manifest.get("views", ())
    return {"views": len(views),
            "repository_view": any((view.get("scope") or {}).get("kind") == "repository"
                                   for view in views)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--analysis", help="module-analysis.jsonl")
    parser.add_argument("--units", help="units.txt: the modules this run paid to read")
    parser.add_argument("--claims", help="claims.verified.jsonl")
    parser.add_argument("--doc", help="doc.json")
    parser.add_argument("--checkpoints", help="the checkpoints directory, so the report "
                                              "carries who decided the run's judgements")
    parser.add_argument("--architecture", help="architecture-analysis.json, so Detector B "
                                               "can ask whether it is a synthesis")
    parser.add_argument("--flows", help="flow-analysis.json, for the flow denominator")
    parser.add_argument("--flow-report", help="the report from validate_flows.py, so "
                                              "refused flows are not counted as traced")
    parser.add_argument("--operations", help="operations-analysis.json")
    parser.add_argument("--diagrams", help="directory holding diagram-manifest.json")
    parser.add_argument("--prose", help="the report from check_prose.py, so a document "
                                        "whose sentences outrun their sources cannot pass")
    parser.add_argument("--require", default=STATUS_PARTIAL,
                        choices=(PASSED, STATUS_PARTIAL, REVIEW_REQUIRED, FAILED),
                        help="lowest status that still exits 0 (default: partial)")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    index, error = load_json(args.index, "index")
    if error:
        return fail(error)
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))

    try:
        budget, budget_source = budget_of(index, args.units)
    except (OSError, ValueError) as exc:
        return fail(str(exc))

    reasons, findings = [], []
    if args.analysis:
        if not os.path.isfile(args.analysis):
            return fail("no such analysis file: %s" % args.analysis)
        try:
            kinds_by_path, statements, findings = analyse(index, args.analysis)
        except ValueError as exc:
            return fail("cannot read %s: %s" % (args.analysis, exc))
    else:
        kinds_by_path, statements = {}, {"total": 0, "valid": 0, "unanchored": 0,
                                         "near_duplicate": 0, "rejected": 0,
                                         "with_valid_evidence": 0,
                                         "by_kind": {}, "by_status": {}}
        reasons.append("no module analysis was supplied, so nothing was read")

    in_budget = set(budget)
    depth = depth_of(kinds_by_path, in_budget)
    # Read means answered at least `READ_KINDS_FLOOR` of the four, not "has a surviving
    # statement". A module named once and left there is counted below as touched, so the
    # difference between the two numbers is visible rather than argued about.
    analysed_in_budget = {path for path in in_budget
                          if len(set(kinds_by_path.get(path, ())) & set(MODULE_KINDS))
                          >= READ_KINDS_FLOOR}
    touched = set(kinds_by_path) & in_budget
    coverage = (len(analysed_in_budget) / float(len(in_budget))) if in_budget else 0.0
    full_ratio = (depth["full"] / float(len(in_budget))) if in_budget else 0.0
    mode = mode_of(coverage, full_ratio, statements["total"])

    report = {
        "schema_version": REPORT_VERSION,
        "index_hash": index.get("index_hash"),
        "analysis_mode": mode,
        "modules": {
            "budget_from": budget_source,
            "in_budget": len(in_budget),
            "analysed": len(analysed_in_budget),
            "read_floor": READ_KINDS_FLOOR,
            # Modules carrying any surviving statement at all. Never the coverage figure
            # -- it was, and that is how a run of one-line modules passed for a read one.
            "touched": len(touched),
            "coverage": round(coverage, 4),
            "full_coverage": round(full_ratio, 4),
            # Outside the budget by design: covered in a line, never read in full. They
            # are not failures and must not move the coverage above.
            "out_of_budget": len([record["path"] for record in index.get("files", ())
                                  if not record.get("is_test")
                                  and record["path"] not in in_budget]),
            "unanalysed": sorted(in_budget - analysed_in_budget)[:20],
            # Reported beside coverage rather than folded into it: the two answer
            # different questions, and collapsing them would hide whichever is worse.
            "depth": depth,
        },
        "statements": statements,
        # Never a pass or a failure on its own: an open checkpoint means a component that
        # would have refused was not reached, so it is reported and left to the reader.
        "checkpoints": decisions_of(args.checkpoints),
        "findings": findings,
    }

    status = PASSED
    if statements["rejected"]:
        status = FAILED
        reasons.append("%d statement(s) were rejected outright"
                       % statements["rejected"])
    if mode == DERIVED_ONLY:
        # The rule this file exists for. A derived-only document is not broken, so it is
        # not `failed`; it is a document with no reading in it, so it is never `passed`.
        status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
        reasons.append("analysis mode is derived_only: %d of %d module(s) in the budget "
                       "answer at least %d of %s"
                       % (len(analysed_in_budget), len(in_budget), READ_KINDS_FLOOR,
                          ", ".join(MODULE_KINDS)))
    elif mode == PARTIAL:
        status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
        # Which of the two tiers fell short decides what to do next, so say which. Too
        # few modules read means dispatch the rest; enough read but thin means go back
        # to the ones already done and ask them the questions they did not answer.
        if coverage < PER_MODULE_COVERAGE:
            reasons.append("analysis mode is partial: %d of %d module(s) in the budget "
                           "were read" % (len(analysed_in_budget), len(in_budget)))
        else:
            reasons.append("analysis mode is partial: %d of %d module(s) were read, but "
                           "only %d answer all four of %s -- the modules are present "
                           "and thin"
                           % (len(analysed_in_budget), len(in_budget), depth["full"],
                              ", ".join(MODULE_KINDS)))

    # Reported whatever the mode, and deliberately not folded into it: a run can be
    # `per_module` on coverage and still answer one question in four, which is the
    # document that comes back looking like an outline. Stated so the shortfall is in
    # the report rather than in the reader's first impression of the pages.
    if depth["full"] < len(in_budget):
        reasons.append("depth: %d of %d module(s) in the budget answer all four of %s; "
                       "the median module answers %d"
                       % (depth["full"], len(in_budget), ", ".join(MODULE_KINDS),
                          depth["median_kinds"]))

    if args.claims:
        try:
            claims = load_jsonl(args.claims)
        except (OSError, ValueError) as exc:
            return fail("cannot read %s: %s" % (args.claims, exc))
        by_status = {}
        for claim in claims:
            by_status[claim.get("status")] = by_status.get(claim.get("status"), 0) + 1
        report["claims"] = {"total": len(claims), "by_status": by_status}
        # The floor the statements sit on: structural facts the source could have
        # contradicted and did not.
        if by_status.get("rejected"):
            status = FAILED
            reasons.append("%d claim(s) were rejected" % by_status["rejected"])

    if args.doc:
        doc, error = load_json(args.doc, "document model")
        if error:
            return fail(error)
        report["pages"] = page_report(doc)
        if report["pages"]["missing"]:
            status = FAILED
            reasons.append("the %s preset requires pages that were not generated: %s"
                           % (report["pages"]["preset"],
                              ", ".join(report["pages"]["missing"])))

    if args.architecture:
        architecture, error = load_json(args.architecture, "architecture analysis")
        if error:
            return fail(error)
        stated = architecture.get("index_hash")
        if not stated:
            # Without it the synthesis cannot be tied to the repository that was scanned,
            # and detector B would hand back a verdict on modules from who knows where.
            return fail("the architecture analysis carries no index_hash, so which scan "
                        "it describes is unknown")
        if stated != index.get("index_hash"):
            return fail("the architecture analysis was written against %s, the index is "
                        "%s" % (stated, index.get("index_hash")))
        detector = detector_b(architecture)
        report["architecture"] = detector
        if detector["outcome"] == "failed":
            status = FAILED
            reasons.append("detector B: %s" % detector["detail"])
        elif detector["outcome"] == "partial":
            status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
            reasons.append("detector B: %s" % detector["detail"])
        elif detector["outcome"] == "not_applicable":
            # Not a pass. Saying so keeps a small repository from reading as though the
            # detector had looked and approved.
            status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
            reasons.append("detector B did not run: %s" % detector["detail"])

    for option, label, builder, key in (
            (args.flows, "flow analysis", flow_report, "flows"),
            (args.operations, "operations analysis", operations_report, "operations")):
        if not option:
            continue
        loaded, error = load_json(option, label)
        if error:
            return fail(error)
        stated = loaded.get("index_hash")
        if not stated:
            return fail("the %s carries no index_hash, so which scan it describes is "
                        "unknown" % label)
        if stated != index.get("index_hash"):
            return fail("the %s was written against %s, the index is %s"
                        % (label, stated, index.get("index_hash")))
        if key == "flows":
            validation = None
            if args.flow_report:
                validation, error = load_json(args.flow_report, "flow validation report")
                if error:
                    return fail(error)
                if validation.get("index_hash") != stated:
                    return fail("the flow report describes %s, the flow analysis is %s"
                                % (validation.get("index_hash"), stated))
            report[key] = builder(loaded, validation)
            if not report[key]["validated"]:
                # Unchecked counts are not coverage. Saying so beats a figure that reads
                # like one and includes flows validate_flows.py would have refused.
                status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
                reasons.append("no flow report was supplied, so the flow counts include "
                               "flows nothing has validated")
            elif report[key]["refused"]:
                status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
                reasons.append("%d flow(s) were refused and are not documented"
                               % report[key]["refused"])
        else:
            report[key] = builder(loaded)
        # Nothing traced and nothing said about why is the quiet failure this whole step
        # exists to stop. "Nothing here" is a result and passes; silence is not.
        if not report[key].get("absent_stated") and not (
                report[key].get("flows") or report[key].get("procedures")):
            status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
            reasons.append("the %s names nothing and does not say why" % label)

    if args.prose:
        prose, error = load_json(args.prose, "prose report")
        if error:
            return fail(error)
        report["prose"] = {"status": prose.get("status"),
                           "findings": len([f for f in prose.get("findings", ())
                                            if f.get("severity") != "advisory"]),
                           "queued": (prose.get("coverage") or {}).get("queued"),
                           "unreviewed": len(prose.get("unreviewed", ()))}
        if prose.get("status") == FAILED:
            status = FAILED
            reasons.append("the prose says more than the analysis behind it: %d finding(s)"
                           % report["prose"]["findings"])
        elif prose.get("status") == REVIEW_REQUIRED:
            status = min(status, REVIEW_REQUIRED, key=lambda s: RANK[s])
            reasons.append("%d block(s) were queued for a model pass that did not "
                           "decide them" % report["prose"]["unreviewed"])

    if args.diagrams:
        report["diagrams"] = diagram_report(args.diagrams)
        if not report["diagrams"]["repository_view"]:
            status = FAILED
            reasons.append("no diagram covers the whole repository")

    report["status"] = status
    report["reasons"] = reasons
    body = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
    print(body)
    return 0 if RANK[status] >= RANK[args.require] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
