#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/validate_analysis.py
# Regenerate: python3 tools/materialize.py
"""Hold `module-analysis.jsonl` to its schema, its evidence, and to saying something.

    python3 scripts/validate_analysis.py .docs-build/module-analysis.jsonl \\
        --index .docs-build/structure.json

A claim says the code is shaped a certain way, and the source can prove it wrong. A
statement says what a module is *for*, and nothing can prove it wrong -- so the checks
here are of a different kind. They cannot ask whether a reading is correct. They can ask
whether it was made at all:

    the evidence exists, at those lines, in that file, at the scanned version
    the statement names something that is actually in the module it describes
    the same sentence is not being told about every module in the repository

That is the whole design. A statement anchored to nothing and repeated everywhere is
what a run produces when it never opened a file, and those two properties are visible
without understanding a word of it.

**Anchoring does not fail the run.** A statement that names nothing in its module is
reported and does not count as analysis; it is not an error. Erroring would turn every
legitimately abstract sentence into an argument, while the count already does the work:
a document made of anchorless prose falls to `derived_only` on its own.

Statuses record where a reading came from, not how sure anyone is:

    declared   the repository states it -- an ADR, a design document, a docstring
    observed   visible in the code, with no reason given for it
    inferred   the model's reading, supported by more than one place
    unknown    the repository does not say

There is deliberately no confidence field. Nothing can contradict a model's assessment
of itself, so recording one adds a number that no check can ever disagree with.

Standard library only. Reads; writes only where `--out` says to.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import json
import os
import re
import sys

SUPPORTED_ANALYSIS_VERSION = {1}

KINDS = ("responsibility", "state", "interface", "interaction", "failure", "rationale")
STATUSES = ("declared", "observed", "inferred", "unknown")

REQUIRED_ROW = ("path", "source_hash", "index_hash", "role", "statements")
REQUIRED_STATEMENT = ("id", "kind", "status", "text", "evidence")

# Two statements about different modules this close are one statement with the nouns
# swapped. Flagged individually; past the ratio the set is a template.
NEAR_DUPLICATE = 0.8
TEMPLATE_RATIO = 0.2

# An identifier shorter than this matches by accident: `os`, `id`, `to`.
MIN_IDENTIFIER = 3

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def load_rows(path):
    if not os.path.isfile(path):
        return None, "no such analysis file: %s" % path
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    return None, "%s line %d: %s" % (path, number, exc)
                if not isinstance(row, dict):
                    return None, "%s line %d: not an object" % (path, number)
                rows.append(row)
    except OSError as exc:
        return None, "cannot read %s: %s" % (path, exc)
    return rows, None


def normalise(text):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).split())


def tokens(text):
    return set(normalise(text).split())


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def identifiers_of(record):
    """Every name the module defines or binds, as written.

    Symbols and import bindings come from any scan; classes, methods and attributes only
    from a `--detail` one. A module scanned without detail therefore anchors on less,
    which understates it -- so the run says `--detail` and this says nothing clever.
    """
    names = {symbol["name"] for symbol in record.get("symbols", ())}
    for entry in record.get("imports", ()):
        names.update(entry.get("bindings", ()))
        names.add(str(entry.get("name", "")).rsplit(".", 1)[-1])
    for cls in record.get("classes", ()):
        names.add(cls.get("name", ""))
        for member in list(cls.get("methods", ())) + list(cls.get("attributes", ())):
            names.add(member.get("name", ""))
    for function in record.get("functions", ()):
        names.add(function.get("name", ""))
    return {name for name in names if name and len(name) >= MIN_IDENTIFIER}


def anchored(text, names):
    return bool(names & set(WORD.findall(str(text))))


class Checker(object):
    def __init__(self, index):
        self.index = index
        self.by_path = {record["path"]: record for record in index.get("files", ())}
        # A `declared` statement is one the repository states -- in an ADR, a design
        # note, a README. Those are assets, not source files, so resolving evidence
        # against `files` alone rejected exactly the citations the inventory was added
        # to make possible.
        self.assets = {record["path"]: record for record in index.get("assets", ())}
        self.findings = []

    def finding(self, code, message, path=None, statement=None, severity="error"):
        self.findings.append({"code": code, "severity": severity, "path": path,
                              "statement": statement, "message": message})

    def check_evidence(self, path, statement_id, evidence):
        """True when this evidence can be looked at and still describes the same file."""
        ok = True
        if not isinstance(evidence, list) or not evidence:
            self.finding("A015", "statement carries no evidence", path, statement_id)
            return False
        for item in evidence:
            if not isinstance(item, dict) or "path" not in item:
                self.finding("A015", "an evidence record has no path", path, statement_id)
                ok = False
                continue
            record = self.by_path.get(item["path"])
            asset = None if record is not None else self.assets.get(item["path"])
            if record is None and asset is None:
                self.finding("A006", "evidence names %r, which the index does not hold"
                             % item["path"], path, statement_id)
                ok = False
                continue
            length = record.get("loc", 0) if record is not None else asset.get("lines", 0)
            start, end = item.get("line_start"), item.get("line_end", item.get(
                "line_start"))
            if not isinstance(start, int) or not isinstance(end, int) \
                    or start < 1 or end < start or end > length:
                self.finding("A007", "evidence cites lines %r-%r of a %d-line file"
                             % (start, end, length), path, statement_id)
                ok = False
                continue
            symbol = item.get("symbol")
            if symbol and asset is not None:
                # An asset is never parsed, so there is no symbol table to check against
                # and "not found" would mean "not looked for". Cite the lines instead.
                self.finding("A008", "evidence names symbol %r in %s, which is an asset "
                             "and has no symbol table; cite its lines instead"
                             % (symbol, item["path"]), path, statement_id)
                ok = False
            elif symbol and symbol.split(".")[-1] not in identifiers_of(record):
                self.finding("A008", "evidence names symbol %r, which is not in %s"
                             % (symbol, item["path"]), path, statement_id)
                ok = False
            stated = item.get("source_hash")
            if stated and stated != (record if record is not None
                                     else asset).get("source_hash"):
                self.finding("A004", "evidence in %s was written against a different "
                             "version of it" % item["path"], path, statement_id)
                ok = False
        return ok

    def check_row(self, row, seen_ids):
        """One module's analysis. Returns its per-statement verdicts."""
        path = row.get("path")
        missing = [field for field in REQUIRED_ROW if field not in row]
        if missing:
            self.finding("A002", "row is missing %s" % ", ".join(missing), path)
            return {}
        record = self.by_path.get(path)
        if record is None:
            self.finding("A003", "%s is not in the index" % path, path)
            return {}
        if row["source_hash"] != record.get("source_hash"):
            self.finding("A004", "the analysis was written against a different version "
                         "of %s; rescan and redo it" % path, path)
        if row["index_hash"] != self.index.get("index_hash"):
            self.finding("A005", "the analysis names a different scan than the index "
                         "given", path)
        if not str(row.get("role", "")).strip():
            self.finding("A002", "role is empty", path)

        names = identifiers_of(record)
        verdicts = {}
        for statement in row["statements"]:
            if not isinstance(statement, dict):
                self.finding("A002", "a statement is not an object", path)
                continue
            statement_id = statement.get("id")
            absent = [f for f in REQUIRED_STATEMENT if f not in statement]
            if absent:
                self.finding("A002", "statement is missing %s" % ", ".join(absent),
                             path, statement_id)
                continue
            if statement_id in seen_ids:
                self.finding("A011", "statement id %r is used twice" % statement_id,
                             path, statement_id)
                continue
            seen_ids.add(statement_id)

            good = True
            if statement["kind"] not in KINDS:
                self.finding("A009", "unknown statement kind %r" % statement["kind"],
                             path, statement_id)
                good = False
            if statement["status"] not in STATUSES:
                self.finding("A010", "unknown statement status %r" % statement["status"],
                             path, statement_id)
                good = False
            if not str(statement.get("text", "")).strip():
                self.finding("A002", "statement text is empty", path, statement_id)
                good = False
            if not self.check_evidence(path, statement_id, statement.get("evidence")):
                good = False
            if not good:
                verdicts[statement_id] = "rejected"
                continue
            if not anchored(statement["text"], names):
                self.finding("A014", "the statement names nothing that is in %s, so it "
                             "is not about it" % path, path, statement_id,
                             severity="advisory")
                verdicts[statement_id] = "unanchored"
                continue
            verdicts[statement_id] = "valid"
        return verdicts

    def check_repetition(self, rows, verdicts):
        """The same sentence told about two modules is told about neither."""
        entries = []
        for row in rows:
            for statement in row.get("statements", ()):
                if not isinstance(statement, dict) or "id" not in statement:
                    continue
                entries.append((row.get("path"), statement["id"],
                                normalise(statement.get("text", "")),
                                tokens(statement.get("text", ""))))
        flagged = set()
        for index, (path, statement_id, text, words) in enumerate(entries):
            for other_path, other_id, other_text, other_words in entries[index + 1:]:
                if path == other_path:
                    # One module may say several things; only cross-module repetition
                    # means the sentence was not about a module at all.
                    continue
                if text and text == other_text:
                    self.finding("A012", "the same statement is made about %s and %s"
                                 % (path, other_path), path, statement_id)
                    verdicts[statement_id] = "rejected"
                    verdicts[other_id] = "rejected"
                elif jaccard(words, other_words) >= NEAR_DUPLICATE:
                    self.finding("A013", "this statement and %s's differ only in their "
                                 "nouns" % other_path, path, statement_id,
                                 severity="advisory")
                    flagged.update((statement_id, other_id))
        if entries and len(flagged) > TEMPLATE_RATIO * len(entries):
            self.finding("A013", "%d of %d statements are near-duplicates of another "
                         "module's: this is one template, not %d readings"
                         % (len(flagged), len(entries), len(entries)))
        for statement_id in flagged:
            if verdicts.get(statement_id) == "valid":
                verdicts[statement_id] = "near_duplicate"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("analysis", help="module-analysis.jsonl")
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    index, error = load_json(args.index, "index")
    if error:
        return fail(error)
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))
    rows, error = load_rows(args.analysis)
    if error:
        return fail(error)

    for row in rows:
        version = row.get("analysis_version", 1)
        if version not in SUPPORTED_ANALYSIS_VERSION:
            return fail("unsupported analysis_version %r" % version)

    checker = Checker(index)
    verdicts, seen_ids = {}, set()
    for row in rows:
        verdicts.update(checker.check_row(row, seen_ids))
    checker.check_repetition(rows, verdicts)

    modules = []
    for row in rows:
        ids = [s.get("id") for s in row.get("statements", ())
               if isinstance(s, dict)]
        own = {i: verdicts.get(i, "rejected") for i in ids}
        modules.append({
            "path": row.get("path"),
            "statements": [{"id": i, "verdict": v} for i, v in sorted(own.items())
                           if i is not None],
            # What C3 counts. A module is analysed when at least one statement about it
            # survived every check above -- not when a record for it exists.
            "analysed": any(v == "valid" for v in own.values())})

    errors = [f for f in checker.findings if f["severity"] == "error"]
    report = {"schema_version": 1, "passed": not errors,
              "modules": sorted(modules, key=lambda m: m["path"] or ""),
              "analysed": sum(1 for m in modules if m["analysed"]),
              "findings": checker.findings}
    body = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
    print(body)
    return 0 if not errors else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
