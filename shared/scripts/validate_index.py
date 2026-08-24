#!/usr/bin/env python3
"""Check that a structure.json says something a later step can safely build on.

    python3 scripts/validate_index.py structure.json --root .

The scanner is trusted to parse; it is not trusted to have been run against the tree
you are looking at now. This script re-derives what can be re-derived -- that the paths
are inside the repository, that every edge lands on a file the index knows, that a line
number fits inside the file it cites, and that each source hash still matches the bytes
on disk -- and reports the rest as findings rather than fixing them.

Nothing here writes. A stale index is a fact about the index, not a thing to repair
silently: rerun the scanner.

Findings carry stable codes so a report can group them:

    E001  duplicate file path                 E006  source hash missing
    E002  duplicate edge id                   E007  source hash stale
    E003  edge endpoint not in files          E008  indexed file absent from disk
    E004  path escapes the repository         E009  fan-in disagrees with edges
    E005  cited line outside the file         E010  entry point not in files

Exit codes:

    0  no findings
    1  findings -- the index is not safe to build on
    2  input, schema-version, or dependency error
    3  internal error

Standard library only. Reads the index and the working tree; writes nothing.
"""

import argparse
import hashlib
import json
import os
import sys

SUPPORTED_SCHEMA = {2}

# Anything a claim can cite a line inside. Kept explicit rather than walking the record
# blindly, so a new scanner field cannot silently start being range-checked.
LINE_BEARING = ("symbols", "imports")


def file_hash(full):
    digest = hashlib.sha256()
    try:
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


class Findings(object):
    def __init__(self):
        self.rows = []

    def add(self, code, message, path=None):
        self.rows.append({"code": code, "message": message, "path": path})

    def __len__(self):
        return len(self.rows)


def normalized(path):
    """True when the path is repository-relative, forward-slashed, and stays inside.

    `os.path.normpath` is the wrong test on its own: it happily normalizes `../x` into
    something that still leaves the root. The check is that normalizing changes nothing
    *and* the result does not start by climbing out.
    """
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return False
    if "\\" in path:
        return False
    if os.path.normpath(path).replace(os.sep, "/") != path:
        return False
    return not path.startswith("../")


def check_files(index, root, findings):
    """Paths, presence on disk, hashes, and line ranges. Returns {path: record}."""
    by_path = {}
    for record in index.get("files", []):
        path = record.get("path")
        if not normalized(path):
            findings.add("E004", "path is not a normalized repository-relative path",
                         path if isinstance(path, str) else repr(path))
            continue
        if path in by_path:
            findings.add("E001", "path appears more than once in files", path)
            continue
        by_path[path] = record

        full = os.path.join(root, path)
        if not os.path.isfile(full):
            findings.add("E008", "indexed file is not on disk; the index is stale", path)
        else:
            recorded = record.get("source_hash")
            if not recorded:
                findings.add("E006", "record carries no source_hash, so freshness "
                                     "cannot be checked", path)
            elif recorded != file_hash(full):
                findings.add("E007", "file on disk differs from the scanned snapshot", path)

        loc = record.get("loc")
        if not isinstance(loc, int) or loc < 1:
            findings.add("E005", "record has no usable line count", path)
            continue
        for field in LINE_BEARING:
            for item in record.get(field, ()):
                line = item.get("line")
                if not isinstance(line, int) or line < 1 or line > loc:
                    findings.add("E005", "%s %r cites line %r, outside a %d-line file"
                                 % (field[:-1], item.get("name"), line, loc), path)
    return by_path


def check_edges(index, by_path, findings):
    seen = set()
    for edge in index.get("edges", []):
        edge_id = edge.get("edge_id")
        if not edge_id:
            findings.add("E002", "edge carries no edge_id: %s -> %s"
                         % (edge.get("from"), edge.get("to")), edge.get("from"))
        elif edge_id in seen:
            findings.add("E002", "edge_id appears more than once: %s" % edge_id,
                         edge.get("from"))
        else:
            seen.add(edge_id)

        for end in ("from", "to"):
            path = edge.get(end)
            if path not in by_path:
                findings.add("E003", "edge %r end %r names a file not in the index"
                             % (edge_id, path), path if isinstance(path, str) else None)

        source = by_path.get(edge.get("from"))
        line = edge.get("line")
        if source and isinstance(line, int) and line > source.get("loc", 0):
            findings.add("E005", "edge %r cites line %d, past the end of the file"
                         % (edge_id, line), edge.get("from"))


def check_derived(index, by_path, findings):
    """fan_in and entry_points restate the edge list; disagreement means one is wrong."""
    counted = {}
    for edge in index.get("edges", []):
        target = edge.get("to")
        if target in by_path:
            counted[target] = counted.get(target, 0) + 1

    recorded = index.get("fan_in", {})
    for path in set(counted) | set(recorded):
        if counted.get(path, 0) != recorded.get(path, 0):
            findings.add("E009", "fan_in says %r, the edge list says %r"
                         % (recorded.get(path, 0), counted.get(path, 0)), path)

    for entry in index.get("entry_points", []):
        path = entry.get("path")
        if path not in by_path:
            findings.add("E010", "entry point names a file not in the index", path)


def validate(index, root):
    findings = Findings()
    by_path = check_files(index, root, findings)
    check_edges(index, by_path, findings)
    check_derived(index, by_path, findings)
    return findings


def load(path):
    """Returns (index, error). An error here is exit 2, never a finding."""
    if not os.path.isfile(path):
        return None, "no such index: %s" % path
    try:
        with open(path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)
    if not isinstance(index, dict):
        return None, "%s does not contain a JSON object" % path

    version = index.get("schema_version")
    if version is None:
        return None, ("%s has no schema_version -- it predates this validator; rerun "
                      "scan_repo.py" % path)
    if version not in SUPPORTED_SCHEMA:
        return None, ("%s declares schema_version %r; this validator supports %s"
                      % (path, version, sorted(SUPPORTED_SCHEMA)))
    return index, None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository the index describes")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()

    index, error = load(args.index)
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    if not os.path.isdir(args.root):
        sys.stderr.write("FAIL  --root is not a directory: %s\n" % args.root)
        return 2

    findings = validate(index, args.root)

    if args.json:
        json.dump({"index": args.index, "schema_version": index["schema_version"],
                   "findings": findings.rows, "passed": not findings},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    elif findings:
        for row in findings.rows:
            print("%s  %-40s %s" % (row["code"], row["path"] or "-", row["message"]))
        print("")
        print("FAIL  %d finding(s); rerun scan_repo.py or fix its input" % len(findings))
    else:
        print("ok  %d file(s), %d edge(s), schema_version %d"
              % (len(index.get("files", ())), len(index.get("edges", ())),
                 index["schema_version"]))

    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
