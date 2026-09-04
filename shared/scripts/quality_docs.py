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

    per_module     nine in ten modules in the budget carry a statement that survived
    partial        between half and nine in ten did
    derived_only   fewer than half, or no statement was written at all

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

import validate_analysis
from build_document_model import PRESETS

REPORT_VERSION = 1

PER_MODULE = "per_module"
PARTIAL = "partial"
DERIVED_ONLY = "derived_only"

PASSED, STATUS_PARTIAL, FAILED = "passed", "partial", "failed"

# Where the two lines sit. Nine in ten leaves room for a module whose only honest
# statement was unanchored; half is where a document stops being an account of the
# repository and starts being an index with sentences around it.
PER_MODULE_COVERAGE = 0.90
PARTIAL_COVERAGE = 0.50

# Rejections that mean the evidence could not be looked at, as opposed to the statement
# being malformed. Reported apart because they call for a different fix.
EVIDENCE_CODES = ("A004", "A006", "A007", "A008", "A015")

# Detector B. Above the first, the components are the directories; between the two, they
# may be -- a repository is allowed to be organised the way its architecture is, so that
# band is reported rather than fatal.
DETECTOR_B_FAIL = 0.95
DETECTOR_B_PARTIAL = 0.85

RANK = {FAILED: 0, STATUS_PARTIAL: 1, PASSED: 2}
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
    """Run C2's checker and turn its verdicts into counts."""
    rows = load_jsonl(analysis_path)
    checker = validate_analysis.Checker(index)
    verdicts, seen = {}, set()
    for row in rows:
        verdicts.update(checker.check_row(row, seen))
    checker.check_repetition(rows, verdicts)

    evidence_failures = {finding["statement"] for finding in checker.findings
                         if finding["code"] in EVIDENCE_CODES and finding["statement"]}
    by_kind, by_status = {}, {}
    analysed = set()
    for row in rows:
        for statement in row.get("statements", ()):
            if not isinstance(statement, dict):
                continue
            by_kind[statement.get("kind")] = by_kind.get(statement.get("kind"), 0) + 1
            by_status[statement.get("status")] = by_status.get(
                statement.get("status"), 0) + 1
            if verdicts.get(statement.get("id")) == "valid":
                analysed.add(row.get("path"))

    tally = {"total": len(verdicts), "valid": 0, "unanchored": 0,
             "near_duplicate": 0, "rejected": 0}
    for verdict in verdicts.values():
        tally[verdict] = tally.get(verdict, 0) + 1
    tally["with_valid_evidence"] = tally["total"] - len(evidence_failures)
    tally["by_kind"] = by_kind
    tally["by_status"] = by_status
    return analysed, tally, checker.findings


def mode_of(coverage, statements):
    if not statements:
        return DERIVED_ONLY
    if coverage >= PER_MODULE_COVERAGE:
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


def flow_report(flows):
    """What was traced, what was refused, and whether absence was stated.

    The denominator C6 left open. It is deliberately not a percentage: a repository with
    one traceable flow and one refused is not "50% documented", it is a document with a
    hole in a named place.
    """
    entries = [f for f in flows.get("flows", ()) or () if isinstance(f, dict)]
    absent = flows.get("absent")
    return {
        "flows": len(entries),
        "steps": sum(len(f.get("steps") or ()) for f in entries),
        "unresolved": sum(len(f.get("unresolved") or ()) for f in entries),
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
    parser.add_argument("--architecture", help="architecture-analysis.json, so Detector B "
                                               "can ask whether it is a synthesis")
    parser.add_argument("--flows", help="flow-analysis.json, for the flow denominator")
    parser.add_argument("--operations", help="operations-analysis.json")
    parser.add_argument("--diagrams", help="directory holding diagram-manifest.json")
    parser.add_argument("--require", default=STATUS_PARTIAL,
                        choices=(PASSED, STATUS_PARTIAL, FAILED),
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
            analysed, statements, findings = analyse(index, args.analysis)
        except ValueError as exc:
            return fail("cannot read %s: %s" % (args.analysis, exc))
    else:
        analysed, statements = set(), {"total": 0, "valid": 0, "unanchored": 0,
                                       "near_duplicate": 0, "rejected": 0,
                                       "with_valid_evidence": 0,
                                       "by_kind": {}, "by_status": {}}
        reasons.append("no module analysis was supplied, so nothing was read")

    in_budget = set(budget)
    analysed_in_budget = analysed & in_budget
    coverage = (len(analysed_in_budget) / float(len(in_budget))) if in_budget else 0.0
    mode = mode_of(coverage, statements["total"])

    report = {
        "schema_version": REPORT_VERSION,
        "index_hash": index.get("index_hash"),
        "analysis_mode": mode,
        "modules": {
            "budget_from": budget_source,
            "in_budget": len(in_budget),
            "analysed": len(analysed_in_budget),
            "coverage": round(coverage, 4),
            # Outside the budget by design: covered in a line, never read in full. They
            # are not failures and must not move the coverage above.
            "out_of_budget": len([record["path"] for record in index.get("files", ())
                                  if not record.get("is_test")
                                  and record["path"] not in in_budget]),
            "unanalysed": sorted(in_budget - analysed_in_budget)[:20],
        },
        "statements": statements,
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
                       "carry a statement that survived"
                       % (len(analysed_in_budget), len(in_budget)))
    elif mode == PARTIAL:
        status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
        reasons.append("analysis mode is partial: %d of %d module(s) in the budget were "
                       "read" % (len(analysed_in_budget), len(in_budget)))

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
        report[key] = builder(loaded)
        # Nothing traced and nothing said about why is the quiet failure this whole step
        # exists to stop. "Nothing here" is a result and passes; silence is not.
        if not report[key].get("absent_stated") and not (
                report[key].get("flows") or report[key].get("procedures")):
            status = min(status, STATUS_PARTIAL, key=lambda s: RANK[s])
            reasons.append("the %s names nothing and does not say why" % label)

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
