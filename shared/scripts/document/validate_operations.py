#!/usr/bin/env python3
"""Hold `operations-analysis.json` to its schema, its evidence, and to quoting correctly.

    python3 scripts/validate_operations.py .docs-build/operations-analysis.json \\
        --index .docs-build/structure.json --root .

How a repository is built, tested, configured and run is the part of a document a reader
executes rather than reads. A wrong sentence about architecture wastes an afternoon; a
wrong command wastes it and leaves a mess. And it is easy to get wrong in a way that
survives review, because a plausible command is indistinguishable from a real one unless
somebody goes and looks: `npm run build` is what the file *should* say.

So the check here is a literal one. A procedure step may carry a `command`, and if it
does, that exact text must appear in the lines it cites. Not a similar command, not the
same command with the flags tidied -- the characters, in the file, where the citation
says they are. It is the operations analogue of reading a call at its call site, and it
is the only claim in this schema a parser can settle on its own.

Two things follow from that:

    a step whose evidence file changed since the scan is reported as stale rather than
    checked -- the line may now say anything, and a literal match against today's text
    would prove nothing about the run that wrote the claim
    a step with no command is fine. Most of a deployment is prose, and prose here is
    held to the same statuses as everywhere else: `declared` where the repository says
    so, `observed` where a file shows it, `inferred` for a reading, `unknown` where the
    repository never says

A repository with nothing operational to say records that in `absent` with a reason. An
empty list on its own is a generator that gave up quietly.

Standard library only. Reads the inputs and the working tree; writes only where `--out`
says to.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import hashlib
import json
import os
import sys

SUPPORTED_OPERATIONS_VERSION = {1}

STATUSES = ("declared", "observed", "inferred", "unknown")

# What a procedure is for. Kept short on purpose: a vocabulary that grows to fit every
# repository stops sorting anything, and a page that groups by kind needs the groups to
# mean something.
PROCEDURE_KINDS = ("install", "build", "test", "run", "configure", "deploy", "release",
                   "observe")

REQUIRED_PROCEDURE = ("id", "kind", "name", "status", "steps")
REQUIRED_STEP = ("text", "status")
REQUIRED_REQUIREMENT = ("id", "name", "status")


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


def file_hash(path):
    try:
        with open(path, "rb") as fh:
            return "sha256:" + hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


class Checker(object):
    def __init__(self, index, root):
        self.root = root
        self.by_path = {record["path"]: record for record in index.get("files", ())}
        self.assets = {record["path"]: record for record in index.get("assets", ())}
        self.findings = []
        self._lines = {}
        self.quoted = 0

    def finding(self, code, message, subject=None, severity="error"):
        self.findings.append({"code": code, "severity": severity,
                              "subject": subject, "message": message})

    def record_for(self, path):
        record = self.by_path.get(path)
        if record is not None:
            return record, record.get("loc", 0)
        asset = self.assets.get(path)
        if asset is not None:
            return asset, asset.get("lines", 0)
        return None, 0

    def lines_of(self, path):
        """The file's lines as scanned, or None when it cannot be read now."""
        if path in self._lines:
            return self._lines[path]
        try:
            with open(os.path.join(self.root, path), encoding="utf-8",
                      errors="replace") as fh:
                self._lines[path] = fh.read().splitlines()
        except OSError:
            self._lines[path] = None
        return self._lines[path]

    def check_evidence(self, subject, evidence, required=True):
        if not isinstance(evidence, list) or not evidence:
            if required:
                self.finding("O011", "carries no evidence", subject)
            return []
        resolved = []
        for item in evidence:
            if not isinstance(item, dict) or "path" not in item:
                self.finding("O011", "an evidence record has no path", subject)
                continue
            record, length = self.record_for(item["path"])
            if record is None:
                self.finding("O003", "evidence names %r, which the index does not hold"
                             % item["path"], subject)
                continue
            start = item.get("line_start")
            end = item.get("line_end", start)
            if not isinstance(start, int) or not isinstance(end, int) \
                    or start < 1 or end < start or end > length:
                self.finding("O007", "evidence cites lines %r-%r of a %d-line file"
                             % (start, end, length), subject)
                continue
            # The index's hash, never the evidence record's. An analysis that supplies
            # the *current* hash of a file that changed after the scan would otherwise
            # authorise itself: a command added since would match its cited lines and
            # pass, while the analysis is still bound to the old index.
            resolved.append((item["path"], start, end, record.get("source_hash")))
        return resolved

    def check_quote(self, subject, text, resolved, label="command"):
        """The text appears, character for character, in the lines it cites.

        A near miss is the interesting case and the reason this compares raw text rather
        than tokens: `pytest -q` where the file says `pytest --quiet` is a command that
        works, describes the same intent, and is still not what the repository runs.
        """
        if not resolved:
            self.finding("O006", "carries a %s but no evidence that resolves, so there "
                                 "is nothing to check it against" % label, subject)
            return False
        for path, start, end, recorded in resolved:
            current = file_hash(os.path.join(self.root, path))
            if current is None:
                # Not advisory. A command nothing can be checked against is exactly the
                # thing this validator exists to refuse; recording it as advice let the
                # run exit 0 with the command unverified and commands_quoted at zero.
                self.finding("O008", "%s cannot be read, so the %s cannot be checked"
                             % (path, label), subject)
                continue
            if recorded and recorded != current:
                # Not wrong -- no longer checkable. Matching against today's text would
                # say nothing about the run that wrote the claim.
                self.finding("O008", "%s changed since it was scanned; the quoted %s "
                             "cannot be confirmed" % (path, label), subject)
                continue
            lines = self.lines_of(path)
            if lines is None:
                continue
            region = "\n".join(lines[start - 1:end])
            if text in region:
                # Only commands feed the commands_quoted counter: a requirement value
                # checked by the same rule is not something a reader types.
                if label == "command":
                    self.quoted += 1
                return True
        # Every citation resolved and none of them holds the text.
        if not any(f["subject"] == subject and f["code"] == "O008"
                   for f in self.findings):
            self.finding("O006", "quotes %r as a %s, which does not appear in the lines "
                         "it cites" % (text, label), subject)
        return False

    def check_procedure(self, procedure, ids):
        subject = procedure.get("id") if isinstance(procedure, dict) else repr(procedure)
        if not isinstance(procedure, dict):
            self.finding("O002", "a procedure is not an object", subject)
            return
        missing = [f for f in REQUIRED_PROCEDURE if f not in procedure]
        if missing:
            self.finding("O002", "missing %s" % ", ".join(missing), subject)
            return
        if procedure["id"] in ids:
            self.finding("O005", "id used more than once", subject)
        ids.add(procedure["id"])
        if procedure["kind"] not in PROCEDURE_KINDS:
            self.finding("O012", "kind %r is not one this schema defines"
                         % procedure["kind"], subject)
        if procedure["status"] not in STATUSES:
            self.finding("O012", "status %r is not one this schema defines"
                         % procedure["status"], subject)
        if procedure.get("evidence") is not None:
            self.check_evidence(subject, procedure.get("evidence"))

        steps = procedure["steps"]
        if not isinstance(steps, list) or not steps:
            self.finding("O010", "has no step", subject)
            return
        for position, step in enumerate(steps):
            step_subject = "%s [%d]" % (subject, position)
            if not isinstance(step, dict):
                self.finding("O002", "step %d is not an object" % position, subject)
                continue
            missing = [f for f in REQUIRED_STEP if f not in step]
            if missing:
                self.finding("O002", "step %d is missing %s"
                             % (position, ", ".join(missing)), subject)
                continue
            if step["status"] not in STATUSES:
                self.finding("O012", "status %r is not one this schema defines"
                             % step["status"], step_subject)
            # A step the repository never states needs nothing to cite; anything else
            # does, because a step is what a reader is about to type.
            required = step["status"] != "unknown"
            resolved = self.check_evidence(step_subject, step.get("evidence"),
                                           required=required)
            if step.get("command"):
                self.check_quote(step_subject, step["command"], resolved)

    def check_requirement(self, requirement, ids):
        subject = requirement.get("id") if isinstance(requirement, dict) \
            else repr(requirement)
        if not isinstance(requirement, dict):
            self.finding("O002", "a requirement is not an object", subject)
            return
        missing = [f for f in REQUIRED_REQUIREMENT if f not in requirement]
        if missing:
            self.finding("O002", "missing %s" % ", ".join(missing), subject)
            return
        if requirement["id"] in ids:
            self.finding("O005", "id used more than once", subject)
        ids.add(requirement["id"])
        if requirement["status"] not in STATUSES:
            self.finding("O012", "status %r is not one this schema defines"
                         % requirement["status"], subject)
        required = requirement["status"] != "unknown"
        resolved = self.check_evidence(subject, requirement.get("evidence"),
                                       required=required)
        if requirement.get("value"):
            self.check_quote(subject, requirement["value"], resolved, label="value")

    def check(self, doc):
        ids = set()
        procedures = doc.get("procedures")
        if procedures is None:
            procedures = []
        if not isinstance(procedures, list):
            self.finding("O002", "procedures is not a list")
            procedures = []
        for procedure in procedures:
            self.check_procedure(procedure, ids)

        requirements = doc.get("requirements")
        if requirements is None:
            requirements = []
        if not isinstance(requirements, list):
            self.finding("O002", "requirements is not a list")
            requirements = []
        for requirement in requirements:
            self.check_requirement(requirement, ids)

        absent = doc.get("absent")
        if not procedures and not requirements:
            if not isinstance(absent, dict) or not absent.get("reason"):
                self.finding("O013", "names no procedure and no requirement, and does "
                                     "not say why")
        elif absent is not None:
            self.finding("O013", "declares operations and an absent reason at the same "
                                 "time")


def report_of(doc, checker):
    procedures = [p for p in doc.get("procedures", ()) or () if isinstance(p, dict)]
    steps = [s for p in procedures for s in (p.get("steps") or ())
             if isinstance(s, dict)]
    requirements = [r for r in doc.get("requirements", ()) or () if isinstance(r, dict)]
    errors = [f for f in checker.findings if f["severity"] == "error"]
    return {
        "operations_version": doc.get("operations_version"),
        "index_hash": doc.get("index_hash"),
        "passed": not errors,
        "findings": checker.findings,
        "absent": bool(isinstance(doc.get("absent"), dict)
                       and doc["absent"].get("reason")),
        # `commands` against `commands_quoted` is the number worth reading: it is how
        # much of what a reader will type was found in the repository rather than
        # remembered.
        "coverage": {
            "procedures": len(procedures),
            "kinds": sorted({p.get("kind") for p in procedures
                             if p.get("kind") in PROCEDURE_KINDS}),
            "steps": len(steps),
            "commands": sum(1 for s in steps if s.get("command")),
            "commands_quoted": checker.quoted,
            "requirements": len(requirements),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("operations", help="operations-analysis.json")
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--root", default=".", help="the repository the index describes, "
                                                    "so quoted commands can be read")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    index, error = load_json(args.index, "index")
    if error:
        return fail(error)
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))
    if not os.path.isdir(args.root):
        return fail("not a directory: %s" % args.root)

    doc, error = load_json(args.operations, "operations analysis")
    if error:
        return fail(error)
    if not isinstance(doc, dict):
        return fail("%s does not contain a JSON object" % args.operations)
    version = doc.get("operations_version", 1)
    if version not in SUPPORTED_OPERATIONS_VERSION:
        return fail("unsupported operations_version %r" % version)

    stated = doc.get("index_hash")
    if not stated:
        return fail("the analysis carries no index_hash, so which scan it describes is "
                    "unknown")
    if stated != index.get("index_hash"):
        return fail("the analysis was written against %s, the index is %s -- rerun the "
                    "analysis or rescan" % (stated, index.get("index_hash")))

    checker = Checker(index, args.root)
    checker.check(doc)
    report = report_of(doc, checker)

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
