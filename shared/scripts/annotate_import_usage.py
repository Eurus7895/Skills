#!/usr/bin/env python3
"""Annotate which imported bindings Ruff cannot see being used. Report only.

    python3 scripts/annotate_import_usage.py structure.json --root . --policy optional

An import edge is a physical fact: the statement is in the file. Whether the name it
binds is ever read is a different, weaker fact, and this script keeps the two apart. It
writes `usage` onto import records and nothing else -- no edge is removed, no fan-in
changes, no claim loses its evidence.

**An unused import is not proof that a dependency is unnecessary.** It may exist for a
side effect, a re-export, a registration hook, framework discovery, or backwards
compatibility. Removing one is a source change with its own review, its own tests and
its own rescan; this script never proposes it and never runs Ruff with `--fix`.

Each binding gets a record, not a bare word -- a verdict is only meaningful next to the
tool and the line that produced it:

    {"status": "unused_binding", "source": "ruff:F401",
     "diagnostic_path": "src/api.py", "diagnostic_line": 5, "auto_fix": false}

Statuses:

    used            Ruff parsed the file and did not report this binding
    unused_binding  Ruff reported it as imported but unused
    suppressed      the import line carries a `noqa` for it
    unknown         Ruff did not cover the file, or no bindings were recorded

`auto_fix` is always false and is written rather than implied: this script never passes
`--fix`, and every reader of the annotation can see that without trusting a docstring.

Policy for a missing `ruff` executable:

    disabled   never invoked; every binding stays `unknown`
    optional   warn, continue, and record that the tool was absent (default)
    required   exit 2

Exit codes: 0 annotated, 2 input/dependency error, 3 internal error.

Standard library only, plus the external `ruff` executable when enabled. Reads the
index and the working tree, writes only the index and --report. No network.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

SUPPORTED_SCHEMA = {2}

# Ruff names the *imported* symbol, which is not the bound name: `import sys as system`
# is reported as "`sys` imported but unused". The leaf is the best cross-check available,
# and where it fails the line still identifies a single binding often enough to be worth
# trying -- with anything ambiguous left unmatched rather than guessed.
MESSAGE_NAME = re.compile(r"^`([^`]+)`")
NOQA = re.compile(r"#\s*noqa(?::\s*(?P<codes>[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*))?",
                  re.IGNORECASE)


def run_ruff(root):
    """Return (diagnostics, error). Exit status 1 means findings, not failure."""
    if shutil.which("ruff") is None:
        return None, "ruff is not on PATH"
    try:
        proc = subprocess.run(
            # --no-cache because the default writes a .ruff_cache/ directory into the
            # repository being documented, and this script promises to read only.
            ["ruff", "check", "--no-cache", "--select", "F401",
             "--output-format", "json", "."],
            cwd=root, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "ruff could not be run: %s" % exc
    # 0 = clean, 1 = diagnostics. Anything else is ruff itself failing.
    if proc.returncode not in (0, 1):
        return None, "ruff exited %d: %s" % (proc.returncode, proc.stderr.strip()[:200])
    try:
        return json.loads(proc.stdout or "[]"), None
    except ValueError as exc:
        return None, "ruff produced unreadable JSON: %s" % exc


def suppressed_codes(line_text):
    """Which rules a `noqa` on this physical line silences. None means "not a noqa"."""
    match = NOQA.search(line_text)
    if match is None:
        return None
    codes = match.group("codes")
    return {c.strip().upper() for c in codes.split(",")} if codes else set()


def source_line(root, path, line):
    try:
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
            for number, text in enumerate(fh, 1):
                if number == line:
                    return text
    except OSError:
        pass
    return ""


def match_binding(entries, reported):
    """Pick the binding a diagnostic refers to, or None rather than guess.

    `entries` are the import records sharing the diagnostic's line. Two ways to land it:
    the reported leaf is one of the bindings, or the line binds exactly one name so
    there is nothing to be ambiguous about.
    """
    leaf = reported.split(".")[-1]
    for entry in entries:
        for binding in entry.get("bindings", ()):
            if binding == leaf:
                return entry, binding
    bindings = [(e, b) for e in entries for b in e.get("bindings", ())]
    return bindings[0] if len(bindings) == 1 else (None, None)


def usage_record(status, source=None, path=None, line=None):
    """One binding's verdict, with where it came from.

    The status alone would not survive review: "unused" is only meaningful next to the
    tool and the line that said so, and `auto_fix` is recorded as data rather than left
    as a promise in a docstring -- this script never passes `--fix`, and the annotation
    says so wherever it is read.
    """
    return {"status": status, "source": source, "diagnostic_path": path,
            "diagnostic_line": line, "auto_fix": False}


def annotate(index, root, diagnostics):
    """Write `usage` onto import records. Returns the report."""
    # (path, line) -> entries, so a diagnostic finds its statement in one lookup.
    at_line = {}
    python_files = set()
    for record in index.get("files", []):
        if record.get("lang") == "python" and record.get("exact"):
            python_files.add(record["path"])
        for entry in record.get("imports", []):
            at_line.setdefault((record["path"], entry.get("line")), []).append(entry)

    matched, unmatched = 0, []
    reported = set()
    for item in diagnostics:
        filename = item.get("filename", "")
        try:
            path = os.path.relpath(filename, root).replace(os.sep, "/")
        except ValueError:
            path = filename
        line = (item.get("location") or {}).get("row")
        name = MESSAGE_NAME.match(item.get("message", ""))
        entries = at_line.get((path, line), [])
        entry, binding = match_binding(entries, name.group(1)) if name and entries else (None, None)
        if entry is None:
            unmatched.append({"path": path, "line": line,
                              "message": item.get("message", ""),
                              "reason": "no import record binds this name at this line"})
            continue
        entry.setdefault("usage", {})[binding] = usage_record(
            "unused_binding", "ruff:F401", path, line)
        reported.add((path, line, binding))
        matched += 1

    # Everything Ruff parsed and did not report is used -- unless the line silences the
    # rule, in which case Ruff was never going to report it and `used` would be a lie.
    counts = {"used": 0, "unused_binding": matched, "suppressed": 0, "unknown": 0}
    for record in index.get("files", []):
        path = record["path"]
        covered = path in python_files
        for entry in record.get("imports", []):
            bindings = entry.get("bindings")
            if not bindings:
                continue
            if not covered:
                for binding in bindings:
                    entry.setdefault("usage", {})[binding] = usage_record(
                        "unknown", "ruff:F401")
                    counts["unknown"] += 1
                continue
            silenced = suppressed_codes(source_line(root, path, entry.get("line", 0)))
            for binding in bindings:
                if (path, entry.get("line"), binding) in reported:
                    continue
                status = "suppressed" if silenced is not None and (
                    not silenced or "F401" in silenced) else "used"
                # A suppressed binding has a location worth keeping -- the noqa itself.
                # A used one has nothing to point at; Ruff simply said nothing.
                entry.setdefault("usage", {})[binding] = usage_record(
                    status, "ruff:F401",
                    path if status == "suppressed" else None,
                    entry.get("line") if status == "suppressed" else None)
                counts[status] += 1

    return {"tool": "ruff", "rule": "F401", "mode": "report_only", "available": True,
            "matched": matched, "unmatched": len(unmatched), "source_modified": False,
            "counts": counts, "findings": unmatched}


def unknown_everywhere(index, reason):
    """No Ruff run: say `unknown` explicitly rather than leave the field absent."""
    counts = {"used": 0, "unused_binding": 0, "suppressed": 0, "unknown": 0}
    for record in index.get("files", []):
        for entry in record.get("imports", []):
            for binding in entry.get("bindings", ()) or ():
                # No tool ran, so no tool is named as the source of this verdict.
                entry.setdefault("usage", {})[binding] = usage_record("unknown")
                counts["unknown"] += 1
    return {"tool": "ruff", "rule": "F401", "mode": "report_only", "available": False,
            "matched": 0, "unmatched": 0, "source_modified": False, "counts": counts,
            "findings": [], "reason": reason}


def apply_report(index, report):
    """Fold the report into the index's own coverage and diagnostics."""
    counts = report["counts"]
    index.setdefault("coverage", {})["import_usage"] = {
        "tool_available": report["available"],
        "annotated": sum(counts.values()),
        "unused_bindings": counts["unused_binding"],
        "suppressed": counts["suppressed"],
        "unmatched": report["unmatched"],
    }
    rows = index.setdefault("diagnostics", [])
    if counts["unused_binding"]:
        rows.append({
            "code": "D006", "severity": "info", "path": None,
            "message": "%d imported binding(s) are never read according to Ruff F401. "
                       "That is not proof the dependency is unnecessary -- re-export, "
                       "side effect, registration and dynamic discovery all look like "
                       "this." % counts["unused_binding"]})
    if report["unmatched"]:
        rows.append({
            "code": "D007", "severity": "warning", "path": None,
            "message": "%d Ruff diagnostic(s) could not be tied to an import record; "
                       "they are listed in the usage report, not discarded"
                       % report["unmatched"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository the index describes")
    parser.add_argument("--policy", default="optional",
                        choices=("disabled", "optional", "required"),
                        help="what to do when ruff is unavailable")
    parser.add_argument("--out", help="where to write the annotated index (default: in place)")
    parser.add_argument("--report", help="also write the usage report here")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        sys.stderr.write("FAIL  --root is not a directory: %s\n" % args.root)
        return 2
    if not os.path.isfile(args.index):
        sys.stderr.write("FAIL  no such index: %s\n" % args.index)
        return 2
    try:
        with open(args.index, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("FAIL  cannot read %s: %s\n" % (args.index, exc))
        return 2
    if index.get("schema_version") not in SUPPORTED_SCHEMA:
        sys.stderr.write("FAIL  %s declares schema_version %r; this script supports %s\n"
                         % (args.index, index.get("schema_version"), sorted(SUPPORTED_SCHEMA)))
        return 2

    if args.policy == "disabled":
        report = unknown_everywhere(index, "policy is disabled; ruff was not invoked")
    else:
        diagnostics, error = run_ruff(args.root)
        if error is not None:
            if args.policy == "required":
                sys.stderr.write("FAIL  --policy required but %s\n" % error)
                return 2
            sys.stderr.write("WARN  %s; import usage stays unknown\n" % error)
            report = unknown_everywhere(index, error)
        else:
            report = annotate(index, args.root, diagnostics)

    apply_report(index, report)

    out = args.out or args.index
    directory = os.path.dirname(os.path.abspath(out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, sort_keys=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

    counts = report["counts"]
    print("import usage: %d used, %d unused, %d suppressed, %d unknown; "
          "%d diagnostic(s) unmatched (ruff available: %s)"
          % (counts["used"], counts["unused_binding"], counts["suppressed"],
             counts["unknown"], report["unmatched"], report["available"]))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
