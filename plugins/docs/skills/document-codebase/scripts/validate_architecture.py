#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/validate_architecture.py
# Regenerate: python3 tools/materialize.py
"""Hold `architecture-analysis.json` to its schema, its evidence, and to being a synthesis.

    python3 scripts/validate_architecture.py .docs-build/architecture-analysis.json \\
        --index .docs-build/structure.json --analysis .docs-build/module-analysis.jsonl

A module analysis says what one file is for. An architecture analysis says what the files
add up to -- components, the layers they sit in, what crosses between them, and which
outside systems the repository talks to. That is one level further from anything a parser
can confirm, so the checks here are again of a different kind.

They cannot ask whether a grouping is the right one. They can ask whether it is a grouping
at all:

    every component holds modules the index knows, and no module sits in two of them
    every relationship joins two components that exist, and cites a line for doing so
    every statement id points at a statement the module analysis actually contains
    the whole thing was written against the scan it claims to describe

**Whether it is a synthesis rather than a rename of the directory tree is Detector B, and
it lives in `quality_docs.py`** -- with the rest of the quality gate, because it is a
judgement about the run and not a defect in the file. A file can be perfectly valid here
and still be `ls` with better nouns.

Statuses are the statement vocabulary, unchanged: `declared` where the repository says so,
`observed` where the code shows it, `inferred` for a reading, `unknown` where the
repository never says. A boundary whose reason is `unknown` is a real and useful answer --
most boundaries in most repositories have no recorded reason, and saying so beats
inventing one.

Standard library only. Reads; writes only where `--out` says to.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import json
import os
import sys

SUPPORTED_ARCHITECTURE_VERSION = {1}

STATUSES = ("declared", "observed", "inferred", "unknown")
RELATIONSHIP_KINDS = ("depends_on", "calls", "publishes_to", "reads_from", "extends")

REQUIRED_COMPONENT = ("id", "name", "modules", "status")
REQUIRED_RELATIONSHIP = ("from", "to", "kind", "status", "evidence")
REQUIRED_EXTERNAL = ("id", "name", "status")
REQUIRED_LAYER = ("id", "name", "components")


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


def statement_sources(path):
    """Map every statement id to the module paths that produced it.

    Returns `(None, None)` when no analysis was asked for, and `(None, error)` when one
    was asked for and could not be read -- a mistyped `--analysis` must not read as
    "there is nothing to check against", which would downgrade every id check to advice
    and let the run exit 0.
    """
    if not path:
        return None, None
    if not os.path.isfile(path):
        return None, "no such module analysis: %s" % path
    sources = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            origin = row.get("path")
            for statement in row.get("statements", ()) or ():
                if isinstance(statement, dict) and statement.get("id"):
                    sources.setdefault(statement["id"], set()).add(origin)
    return sources, None


class Checker(object):
    def __init__(self, index, statement_sources=None):
        self.index = index
        self.modules = {record["path"] for record in index.get("files", ())}
        self.by_path = {record["path"]: record for record in index.get("files", ())}
        self.assets = {record["path"]: record for record in index.get("assets", ())}
        # None means "no module analysis was supplied", which is different from "it
        # contained no statements". The first cannot be checked; the second is a finding.
        self.statement_sources = statement_sources
        self.findings = []

    def finding(self, code, message, subject=None, severity="error"):
        self.findings.append({"code": code, "severity": severity,
                              "subject": subject, "message": message})

    def check_evidence(self, subject, evidence, required=True):
        if not isinstance(evidence, list) or not evidence:
            if required:
                self.finding("B011", "carries no evidence", subject)
            return not required
        ok = True
        for item in evidence:
            if not isinstance(item, dict) or "path" not in item:
                self.finding("B011", "an evidence record has no path", subject)
                ok = False
                continue
            record = self.by_path.get(item["path"])
            asset = None if record is not None else self.assets.get(item["path"])
            if record is None and asset is None:
                self.finding("B007", "evidence names %r, which the index does not hold"
                             % item["path"], subject)
                ok = False
                continue
            length = record.get("loc", 0) if record is not None else asset.get("lines", 0)
            start = item.get("line_start")
            end = item.get("line_end", start)
            if not isinstance(start, int) or not isinstance(end, int) \
                    or start < 1 or end < start or end > length:
                self.finding("B007", "evidence cites lines %r-%r of a %d-line file"
                             % (start, end, length), subject)
                ok = False
        return ok

    def check_statement_ids(self, subject, ids, home=None):
        """`home` is the set of modules this subject is built from, when it has one.

        A citation is provenance only if it points back at the subject's own modules. A
        component holding `b.py` that cites a statement written about `a.py` has borrowed
        someone else's evidence, and the id existing somewhere in the analysis does not
        make the component a synthesis of what it contains.
        """
        if not ids:
            return
        if self.statement_sources is None:
            self.finding("B008", "names statement ids, but no module analysis was given "
                                 "to check them against", subject, severity="advisory")
            return
        for statement_id in ids:
            origins = self.statement_sources.get(statement_id)
            if origins is None:
                self.finding("B008", "names statement %r, which the module analysis does "
                             "not contain" % statement_id, subject)
            elif home is not None and not (origins & home):
                self.finding("B009", "names statement %r, which was written about %s -- "
                             "not a module it holds"
                             % (statement_id, ", ".join(sorted(str(o) for o in origins))),
                             subject)

    def check(self, doc):
        ids, owner = set(), {}

        components = doc.get("components")
        if not isinstance(components, list) or not components:
            self.finding("B010", "the analysis names no component at all")
            components = []

        for component in components:
            subject = component.get("id") if isinstance(component, dict) else repr(component)
            if not isinstance(component, dict):
                self.finding("B002", "a component is not an object", subject)
                continue
            missing = [f for f in REQUIRED_COMPONENT if f not in component]
            if missing:
                self.finding("B002", "missing %s" % ", ".join(missing), subject)
                continue
            if component["id"] in ids:
                self.finding("B005", "id used more than once", subject)
            ids.add(component["id"])
            if component["status"] not in STATUSES:
                self.finding("B012", "status %r is not one this schema defines"
                             % component["status"], subject)

            members = component.get("modules")
            if not isinstance(members, list) or not members:
                # A component holding nothing is a name, and a document made of names is
                # what this whole plan exists to stop being produced.
                self.finding("B010", "holds no module", subject)
                members = []
            for path in members:
                if path not in self.modules:
                    self.finding("B003", "holds %r, which the index does not know"
                                 % path, subject)
                elif path in owner and owner[path] != component["id"]:
                    # Overlapping components make every later count ambiguous: coverage,
                    # the partition Detector B compares, and what a page says a module
                    # belongs to.
                    self.finding("B004", "holds %r, which %s also holds"
                                 % (path, owner[path]), subject)
                else:
                    owner[path] = component["id"]

            rationale = component.get("rationale")
            if rationale is not None:
                if not isinstance(rationale, dict) or "status" not in rationale:
                    self.finding("B002", "rationale has no status", subject)
                elif rationale["status"] not in STATUSES:
                    self.finding("B012", "rationale status %r is not one this schema "
                                 "defines" % rationale["status"], subject)
                elif rationale["status"] != "unknown":
                    self.check_evidence(subject, rationale.get("evidence"))
            self.check_statement_ids(subject, component.get("statement_ids", ()),
                                     home={p for p in members if isinstance(p, str)})
            if component.get("evidence") is not None:
                self.check_evidence(subject, component.get("evidence"))

        for layer in doc.get("layers", ()) or ():
            subject = layer.get("id") if isinstance(layer, dict) else repr(layer)
            if not isinstance(layer, dict):
                self.finding("B002", "a layer is not an object", subject)
                continue
            missing = [f for f in REQUIRED_LAYER if f not in layer]
            if missing:
                self.finding("B002", "missing %s" % ", ".join(missing), subject)
                continue
            if layer["id"] in ids:
                self.finding("B005", "id used more than once", subject)
            ids.add(layer["id"])
            if not isinstance(layer["components"], list) or not layer["components"]:
                # Same rule as a component holding no module: a layer holding no
                # component is a name, and names are what this plan exists to stop.
                self.finding("B010", "holds no component", subject)
            for member in layer.get("components", ()):
                if member not in {c.get("id") for c in components if isinstance(c, dict)}:
                    self.finding("B006", "names component %r, which does not exist"
                                 % member, subject)

        for relationship in doc.get("relationships", ()) or ():
            if not isinstance(relationship, dict):
                self.finding("B002", "a relationship is not an object", repr(relationship))
                continue
            subject = "%s -> %s" % (relationship.get("from"), relationship.get("to"))
            missing = [f for f in REQUIRED_RELATIONSHIP if f not in relationship]
            if missing:
                self.finding("B002", "missing %s" % ", ".join(missing), subject)
                continue
            known = {c.get("id") for c in components if isinstance(c, dict)}
            known |= {e.get("id") for e in doc.get("external_systems", ()) or ()
                      if isinstance(e, dict)}
            for end in ("from", "to"):
                if relationship[end] not in known:
                    self.finding("B006", "%s names %r, which is neither a component nor "
                                 "an external system" % (end, relationship[end]), subject)
            if relationship["kind"] not in RELATIONSHIP_KINDS:
                self.finding("B012", "kind %r is not one this schema defines"
                             % relationship["kind"], subject)
            if relationship["status"] not in STATUSES:
                self.finding("B012", "status %r is not one this schema defines"
                             % relationship["status"], subject)
            # A relationship is the part a reader acts on -- it says what breaks what --
            # so it is the part that must cite a line, whatever its status.
            self.check_evidence(subject, relationship.get("evidence"))
            # A relationship may cite either end: the evidence for "edge depends on
            # storage" is as likely to sit in storage as in edge.
            members = {c.get("id"): c for c in components if isinstance(c, dict)}
            home = set()
            for end in ("from", "to"):
                held = members.get(relationship[end], {}).get("modules")
                if isinstance(held, list):
                    home |= {p for p in held if isinstance(p, str)}
            self.check_statement_ids(subject, relationship.get("statement_ids", ()),
                                     home=home or None)

        for external in doc.get("external_systems", ()) or ():
            subject = external.get("id") if isinstance(external, dict) else repr(external)
            if not isinstance(external, dict):
                self.finding("B002", "an external system is not an object", subject)
                continue
            missing = [f for f in REQUIRED_EXTERNAL if f not in external]
            if missing:
                self.finding("B002", "missing %s" % ", ".join(missing), subject)
                continue
            if external["id"] in ids:
                self.finding("B005", "id used more than once", subject)
            ids.add(external["id"])
            if external["status"] not in STATUSES:
                self.finding("B012", "status %r is not one this schema defines"
                             % external["status"], subject)
            if external.get("evidence") is not None:
                self.check_evidence(subject, external.get("evidence"))

        return owner


def rationale_status(component):
    """The rationale's status, or None when there is not a well-formed one.

    A model writing `"rationale": "because"` is a schema finding (B002), and the counters
    below must still be able to run: exiting 3 on the malformed input throws away the
    report that says what was wrong with it.
    """
    rationale = component.get("rationale")
    if not isinstance(rationale, dict):
        return None
    status = rationale.get("status")
    return status if status in STATUSES else None


def report_of(doc, checker, owner):
    components = [c for c in doc.get("components", ()) if isinstance(c, dict)]
    relationships = [r for r in doc.get("relationships", ()) or ()
                     if isinstance(r, dict)]
    errors = [f for f in checker.findings if f["severity"] == "error"]
    return {
        "architecture_version": doc.get("architecture_version"),
        "index_hash": doc.get("index_hash"),
        "passed": not errors,
        "findings": checker.findings,
        # One denominator per subject, not one figure for the synthesis. A count that
        # blends components with relationships hides which of them is the empty one, and
        # empty is the interesting case.
        "coverage": {
            "components": len(components),
            "components_with_modules": sum(1 for c in components if c.get("modules")),
            "components_with_rationale": sum(
                1 for c in components
                if rationale_status(c) not in (None, "unknown")),
            "rationale_unknown": sum(
                1 for c in components if rationale_status(c) == "unknown"),
            "relationships": len(relationships),
            "relationships_with_evidence": sum(
                1 for r in relationships if r.get("evidence")),
            "external_systems": len(doc.get("external_systems", ()) or ()),
            "modules_placed": len(owner),
            "modules_in_index": len(checker.modules),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("architecture", help="architecture-analysis.json")
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--analysis", help="module-analysis.jsonl, so statement ids can "
                                           "be checked rather than trusted")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    index, error = load_json(args.index, "index")
    if error:
        return fail(error)
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))

    doc, error = load_json(args.architecture, "architecture analysis")
    if error:
        return fail(error)
    if not isinstance(doc, dict):
        return fail("%s does not contain a JSON object" % args.architecture)
    version = doc.get("architecture_version", 1)
    if version not in SUPPORTED_ARCHITECTURE_VERSION:
        return fail("unsupported architecture_version %r" % version)

    stated = doc.get("index_hash")
    if not stated:
        return fail("the analysis carries no index_hash, so which scan it describes is "
                    "unknown")
    if stated != index.get("index_hash"):
        # Same rule as every other artefact here: a file left from an earlier run parses
        # and names real modules, and nothing else tells it apart from today's.
        return fail("the analysis was written against %s, the index is %s -- rerun the "
                    "analysis or rescan" % (stated, index.get("index_hash")))

    sources, error = statement_sources(args.analysis)
    if error:
        return fail(error)

    checker = Checker(index, sources)
    owner = checker.check(doc)
    report = report_of(doc, checker, owner)

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
