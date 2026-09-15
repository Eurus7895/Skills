#!/usr/bin/env python3
"""Check that every extracted setting is where it says it is.

    python3 validate_config.py config.json --index structure.json --root .

**This is the check that lets a configuration answer be `confirmed`.** An extracted row
is not trustworthy because a script produced it -- a script can be wrong, and a row left
over from an earlier scan is wrong about today's tree. `C006` is the rule that matters
and it is the `O006` rule applied here: **the setting's name must appear, character for
character, in the lines it cites.** That is the one thing about a configuration row a
parser can settle, so it is the one that decides whether the row may stand behind a
sentence in the delivered manual.

Findings:

    C002  a row is missing a required field
    C003  evidence names a path the index does not hold
    C005  two rows share an id
    C006  the name does not appear in the lines it cites
    C007  evidence names a line range the file does not have
    C008  the cited file changed since the scan, so nothing can be checked against it
    C012  an unknown kind

`C008` is an error, not advice, for the same reason it is in the operations validator: a
file that moved on since the scan may now say anything, so matching against today's text
would prove nothing about the run that recorded the row.

Standard library only. Reads; writes only the report named by --out.
"""

import argparse
import hashlib
import json
import os
import sys

CONFIG_VERSION = 1
KINDS = ("env", "option")
REQUIRED = ("id", "kind", "name", "evidence")


def file_hash(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


class Checker(object):
    def __init__(self, index, root):
        self.root = root
        self.by_path = {r["path"]: r for r in index.get("files", ())}
        for asset in index.get("assets", ()) or ():
            self.by_path.setdefault(asset["path"], asset)
        self.findings = []

    def finding(self, code, message, subject):
        self.findings.append({"code": code, "message": message, "subject": subject,
                              "severity": "error"})

    def lines_of(self, path, start, end, subject):
        """The cited lines, or None with a finding saying why they could not be read."""
        record = self.by_path.get(path)
        if record is None:
            self.finding("C003", "cites %s, which the index does not hold" % path, subject)
            return None
        full = os.path.join(self.root, path)
        if not os.path.isfile(full):
            self.finding("C007", "cites %s, which is not a file" % path, subject)
            return None
        recorded = record.get("source_hash")
        if recorded and file_hash(full) != recorded:
            self.finding("C008", "%s changed since the scan, so the lines it cites "
                                 "cannot be checked" % path, subject)
            return None
        with open(full, encoding="utf-8") as handle:
            body = handle.read().splitlines()
        if not isinstance(start, int) or not isinstance(end, int) \
                or not 1 <= start <= end <= len(body):
            self.finding("C007", "cites %s:%s-%s, which the file does not have"
                         % (path, start, end), subject)
            return None
        return body[start - 1:end]

    def check(self, row, seen):
        subject = row.get("id") or "<no id>"
        missing = [f for f in REQUIRED if not row.get(f)]
        if missing:
            self.finding("C002", "is missing %s" % ", ".join(missing), subject)
            return
        if row["id"] in seen:
            self.finding("C005", "id used twice", subject)
        seen.add(row["id"])
        if row["kind"] not in KINDS:
            self.finding("C012", "kind %r is not one this schema defines" % row["kind"],
                         subject)
        if not isinstance(row["evidence"], list) or not row["evidence"]:
            self.finding("C002", "is missing evidence", subject)
            return
        for item in row["evidence"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                self.finding("C002", "evidence needs a path", subject)
                continue
            lines = self.lines_of(item["path"], item.get("line_start"),
                                  item.get("line_end"), subject)
            if lines is None:
                continue
            # The whole point. A row whose name is not in the lines it cites is a row
            # about some other line, and nothing downstream would notice.
            if row["name"] not in "\n".join(lines):
                self.finding("C006", "names %r, which does not appear in %s:%s-%s"
                             % (row["name"], item["path"], item["line_start"],
                                item["line_end"]), subject)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", help="config-analysis.json")
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    try:
        with open(args.config, encoding="utf-8") as handle:
            content = json.load(handle)
        with open(args.index, encoding="utf-8") as handle:
            index = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("FAIL  cannot read input: %s\n" % exc)
        return 2
    if content.get("config_version") != CONFIG_VERSION:
        sys.stderr.write("FAIL  unsupported config_version %r\n"
                         % content.get("config_version"))
        return 2
    stated = content.get("index_hash")
    if stated != index.get("index_hash"):
        # A file from an earlier run names real settings and validates cleanly against
        # the tree it was written for. The identity is what tells it from today's.
        sys.stderr.write("FAIL  %s was written against %s, the index is %s\n"
                         % (args.config, stated, index.get("index_hash")))
        return 2

    checker = Checker(index, args.root)
    seen = set()
    settings = content.get("settings") or []
    for row in settings:
        if isinstance(row, dict):
            checker.check(row, seen)
        else:
            checker.finding("C002", "a setting must be an object", "<malformed>")

    kinds = sorted({r.get("kind") for r in settings if isinstance(r, dict)})
    report = {"config_version": CONFIG_VERSION, "index_hash": stated,
              "passed": not checker.findings, "findings": checker.findings,
              "coverage": {"settings": len(settings), "kinds": kinds,
                           "cited": sum(len(r.get("evidence") or ())
                                        for r in settings if isinstance(r, dict))}}
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
