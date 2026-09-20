#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/findings.py
# Regenerate: python3 tools/materialize.py
"""The one place every finding code is declared. Data only -- no logic, no imports.

Every script here reports its verdicts as coded findings, and until this file the codes
existed only at the point each one was raised. That made three things impossible to see:

* **What a code means.** `G003` is emitted by two different scripts, and a reader holding a
  report had to know which one produced it before the code told them anything.
* **Whether a code still exists.** `V010`-`V014` and `V020` are chosen through a dictionary
  rather than written at a call site, and the `D` family is built as literal dicts. A scan
  of the call sites finds neither, so a code could be removed or renamed and no list would
  disagree.
* **Which severities a family may use.** There are three vocabularies below, and every
  consumer filters for the exact string `"error"`. A validator that wrote `"warning"` would
  produce a finding that blocks nothing, report `passed`, and look correct.

That last one is the reason this is enforced rather than written in prose:
`tools/test_findings_registry.py` fails when a code is raised and not declared here, when a
code is declared here and raised nowhere, and when a script uses a severity its families do
not define. A registry nothing checks would drift the same way the comments did.

This file is imported by nothing at runtime, on purpose. The scripts stay standalone and
stdlib-only, and a skill that installs one script must not need this one beside it. It is a
specification with a conformance test, not a dependency.
"""

FINDINGS_VERSION = 1

# Codes that look like ours and are not. Declared rather than filtered quietly, because a
# scan that skipped them without saying so would also skip one of ours that collided with
# another tool's numbering.
FOREIGN_CODES = {
    "F401": "Ruff's unused-import diagnostic, quoted by annotate_import_usage.py as the "
            "source of what it reports. Nothing here raises it",
}

# Three vocabularies, because three different kinds of thing report findings and the words
# are not interchangeable between them.
SEVERITIES = {
    # A validator's verdict on an artifact. `error` fails the run; `advisory` is named and
    # does not, for the cases where the honest answer is "this could not be checked" or
    # "this is thin rather than wrong".
    "validator": ("error", "advisory"),
    # A scanner describing the limits of its own reading. Neither value fails anything:
    # `warning` is a gap in coverage the reader should know about, `info` is a fact about
    # what the scan found.
    "diagnostic": ("info", "warning"),
    # A person's finding in a review record, which is not a script's verdict at all.
    "review": ("blocking", "major", "minor"),
}

# Each family, the script that owns it, and the vocabulary its findings may use.
FAMILIES = {
    "A": {"owner": "check/validate_analysis.py", "severities": "validator",
          "about": "the module analysis: its rows, its evidence, and whether a statement "
                   "is about the module it names"},
    "B": {"owner": "document/validate_architecture.py", "severities": "validator",
          "about": "the architecture analysis: components, their members, and the "
                   "statements they rest on"},
    "C": {"owner": "survey/validate_config.py", "severities": "validator",
          "about": "the configuration analysis: settings, where each one is read, and "
                   "whether the cited lines still say so"},
    "D": {"owner": "survey/scan_repo.py, survey/annotate_import_usage.py",
          "severities": "diagnostic",
          "about": "what the scan could not read, and what it read approximately. These "
                   "describe the limits of the survey rather than a defect in it"},
    "E": {"owner": "survey/validate_index.py", "severities": "validator",
          "about": "the dependency index: paths, edges, fan-in, and whether the snapshot "
                   "still matches what is on disk"},
    "F": {"owner": "document/validate_flows.py", "severities": "validator",
          "about": "the flow analysis: steps, the entities they touch, and the verified "
                   "claims each step cites"},
    "G": {"owner": "document/validate_diagrams.py, document/validate_flow_diagrams.py",
          "severities": "validator",
          "about": "a diagram against the thing it draws. Deliberately shared by both "
                   "validators: a class diagram is checked against the class graph and a "
                   "sequence diagram against a flow, and the *kinds* of disagreement are "
                   "the same, so the codes are the same"},
    "H": {"owner": "publish/release_hygiene.py", "severities": "validator",
          "about": "the shape of the documentation tree rather than the content of any "
                   "page: entry points, configurations, and build output where it does "
                   "not belong"},
    "O": {"owner": "document/validate_operations.py", "severities": "validator",
          "about": "the operations analysis: procedures, requirements, and their evidence"},
    "P": {"owner": "publish/check_prose.py", "severities": "validator",
          "about": "a rendered block's prose against what its citations support"},
    "V": {"owner": "check/verify_doc.py", "severities": "validator",
          "about": "one claim against the source. The verifier's own outcomes -- rejected, "
                   "needs context, candidate, unsupported -- are codes here too, because "
                   "'could not be checked' is a result and not an absence of one"},
}

# Every code, and what it means in one line. The line is the code's definition: where two
# scripts raise the same code, it has to be true of both.
CODES = {
    # -- A: the module analysis ------------------------------------------------------
    "A002": "a row is missing a field the schema requires",
    "A003": "the row names a file the index does not hold",
    "A004": "the analysis was written against a different version of the file it cites",
    "A005": "the analysis names a different scan than the index it was checked against",
    "A006": "evidence names a file the index does not hold",
    "A007": "evidence cites lines outside the file it names",
    "A008": "evidence names a symbol in a file that has none, such as an asset",
    "A009": "the statement's kind is not one the schema defines",
    "A010": "the statement's status is not one the schema defines",
    "A011": "a statement id is used twice",
    "A012": "the same statement is made about two different modules",
    "A013": "statements are near-duplicates of another module's, so one of them was not "
            "read: advisory for a pair, an error once it is a share of the set",
    "A014": "the statement names nothing that is in the module, so it is not about it. "
            "Advisory on purpose: an abstract sentence is not an error, and a document "
            "made of them is already caught by the coverage count",
    "A015": "a statement carries no evidence, or an evidence record has no path",
    "A016": "the module is described without naming more than one thing in it, so it is "
            "described in isolation: advisory for one module, which may honestly be a "
            "single-function leaf, an error past a share of the set, which reads as an "
            "analysis written from the file names",

    # -- B: the architecture analysis ------------------------------------------------
    "B002": "a component is not an object",
    "B003": "a component holds a member the index does not know",
    "B004": "two components hold the same member",
    "B005": "a component id is used more than once",
    "B006": "a relation names a component that does not exist",
    "B007": "evidence names a file the index does not hold",
    "B008": "a component cites statement ids that cannot be confirmed: advisory when no "
            "module analysis was supplied to check against, an error when one was and "
            "does not hold the statement",
    "B009": "a component cites a statement written about something that is not a module",
    "B010": "the analysis names no component at all",
    "B011": "a component carries no evidence",
    "B012": "a status is not one the schema defines",

    # -- C: the configuration analysis -----------------------------------------------
    "C002": "a setting is missing a field the schema requires",
    "C003": "a setting cites a file the index does not hold",
    "C005": "a setting id is used twice",
    "C006": "the setting's name does not appear in the lines it cites",
    "C007": "a setting cites something that is not a file",
    "C008": "the cited file changed since the scan, so its lines cannot be checked",
    "C012": "a kind is not one the schema defines",

    # -- D: what the scan could not read ---------------------------------------------
    "D001": "imports named nothing in this repository, so they are third-party or "
            "standard library",
    "D002": "files with an extension the scanner does not examine were left unread",
    "D003": "a symlink resolves outside the root and was skipped rather than followed",
    "D004": "a file could not be read, so it is in the index without its contents",
    "D005": "no parser for the language, so its imports are approximated by regex",
    "D006": "imported bindings are never read according to Ruff, which is not proof the "
            "dependency is unnecessary",
    "D007": "Ruff diagnostics could not be tied to an import record, and are reported "
            "rather than discarded",

    # -- E: the dependency index -----------------------------------------------------
    "E001": "a path appears more than once in the file list",
    "E002": "an edge carries no edge_id",
    "E003": "an edge names a file that is not in the index",
    "E004": "a path is not a normalized repository-relative path",
    "E005": "a record has no usable line count",
    "E006": "an asset carries no source_hash, so its freshness cannot be checked",
    "E007": "an asset on disk differs from the scanned snapshot",
    "E008": "an indexed file is not on disk, so the index is stale",
    "E009": "the recorded fan-in disagrees with the edge list",
    "E010": "an entry point names a file that is not in the index",
    "E011": "an asset path is not a normalized repository-relative path",

    # -- F: the flow analysis --------------------------------------------------------
    "F002": "a step's subject or object is not an entity id",
    "F003": "a step names an entity the index does not know",
    "F004": "a step starts somewhere the step before it did not reach",
    "F005": "a flow id is used more than once",
    "F006": "a step's citation does not establish that the call was read: advisory when "
            "no claims file was supplied, an error when the claim is absent, of the "
            "wrong kind, unverified, or joins the wrong pair",
    "F007": "evidence names a file the index does not hold",
    "F010": "a flow has no step",
    "F011": "a flow carries no evidence",
    "F012": "a status is not one the schema defines",
    "F013": "the analysis names no flow and does not say why, and an empty list needs a "
            "reason",

    # -- G: a diagram against what it draws ------------------------------------------
    "G001": "the diagram holds something its source does not, or omits something the "
            "source has in scope",
    "G002": "the diagram's metadata does not match the manifest, or it was generated "
            "against a source that has since changed",
    "G003": "the diagram carries a duplicate, or labels the same thing two ways",
    "G005": "the drawn output does not match the metadata that describes it",
    "G006": "the drawn contents are not the ones the metadata declares",
    "G007": "the manifest maps more than one view to the same file",

    # -- H: the shape of the documentation tree --------------------------------------
    "H001": "no index page, so a reader has no entry point and Sphinx has no root",
    "H002": "more than one root index page, and nothing says which the build reads",
    "H003": "more than one Sphinx configuration, and a build uses whichever it is "
            "pointed at",
    "H004": "build output is committed, so every later diff carries generated files",
    "H005": "build output is neither committed nor ignored, so it will be committed next",
    "H006": "generated output sits in the source tree, where the next build reads it",
    "H007": "the document model names a page that is not in the tree",

    # -- O: the operations analysis --------------------------------------------------
    "O002": "a procedure is not an object",
    "O003": "evidence names a file the index does not hold",
    "O005": "a procedure id is used more than once",
    "O006": "a procedure carries a field but no evidence that resolves for it",
    "O007": "evidence cites lines outside the file it names",
    "O008": "a cited file cannot be read, so the claim about it cannot be checked",
    "O010": "a procedure has no step",
    "O011": "a procedure carries no evidence",
    "O012": "a kind is not one the schema defines",
    "O013": "the analysis names no procedure and no requirement, and does not say why",
    "O014": "a record carries a field this schema does not define, so nothing reads it. "
            "Advisory: an ignored field is a mistake about the schema, not a false claim",

    # -- P: prose against its citations ----------------------------------------------
    "P003": "the block says more than its citations support",
    "P004": "the block rests on an inferred reading and states it as fact",
    "P005": "the block carries no citation, so nothing in it can be compared with a "
            "source. Advisory: there is no source to have overstated",
    "P006": "a verdict was supplied for a block that is not queued for review",
    "P007": "the block's review verdict is not one the schema defines",
    "P008": "a review is stale because what it was written against has changed",

    # -- V: one claim against the source ---------------------------------------------
    "V001": "the claim carries no evidence",
    "V002": "evidence names a file that is not in the index",
    "V003": "evidence cites lines outside the file it names",
    "V004": "an evidence file cannot be read",
    "V005": "the file changed since it was scanned, so the citation no longer proves it",
    "V006": "the claim's kind is not one the verifier knows",
    "V007": "the claim's subject or object is not a valid entity id",
    "V008": "a claim id appears more than once",
    "V009": "a fragment references a claim that was not supplied",
    "V010": "the verifier looked and the source does not support the claim",
    "V011": "the verifier could not decide without more context, and this is retryable",
    "V012": "the source is consistent with the claim without establishing it, so it "
            "stays a candidate rather than a fact",
    "V013": "the verifier returned an outcome this table does not name",
    "V014": "the claim is of a shape this verifier cannot check, which is not a defect "
            "in the claim",
    "V015": "the claim joins two kinds of entity its kind does not join",
    "V020": "this finding was already reported for this claim, and is not repeated",
    "V021": "the input carries no index_hash, so nothing says which scan it was written "
            "against",
}
