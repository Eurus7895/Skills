#!/usr/bin/env python3
"""Check that every finding's citation points at code that actually says what it quotes.

    python3 scripts/verify_findings.py --input findings.jsonl --root .

Each finding must carry a file path, a line number, and a verbatim quote. This reads
the real file and confirms the quote appears at or near that line. A finding whose
quote is not there is a fabricated citation -- the reviewer described code that does
not exist, and the finding must be dropped or corrected before the report is written.

Standard library only. Reads files under --root; writes nothing. No network. Paths
resolving outside --root are refused rather than read.

Exit codes:
    0  every finding verified
    1  at least one finding could not be verified
"""

import argparse
import json
import os
import re
import sys

WHITESPACE = re.compile(r"\s+")


def normalise(text):
    """Collapse whitespace so indentation and wrapping do not cause false misses."""
    return WHITESPACE.sub(" ", text).strip()


def load_findings(path):
    """Read JSONL or a JSON array. Returns (findings, parse_errors)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            return [], ["whole file: %s" % exc]
        return [r for r in data if isinstance(r, dict)], []

    findings, errors = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            errors.append("line %d: %s" % (lineno, exc))
            continue
        if isinstance(obj, dict):
            findings.append(obj)
        elif isinstance(obj, list):
            findings.extend(o for o in obj if isinstance(o, dict))
        else:
            errors.append("line %d: not an object" % lineno)
    return findings, errors


def read_lines(cache, root_real, rel_path):
    """Return (lines, error). Refuses paths that escape the root."""
    if rel_path in cache:
        return cache[rel_path]

    resolved = os.path.realpath(os.path.join(root_real, rel_path))
    if resolved != root_real and not resolved.startswith(root_real + os.sep):
        result = (None, "path resolves outside --root")
    elif not os.path.isfile(resolved):
        result = (None, "file does not exist")
    else:
        try:
            with open(resolved, encoding="utf-8", errors="replace") as fh:
                result = (fh.read().splitlines(), None)
        except OSError as exc:
            result = (None, "cannot be read (%s)" % exc)

    cache[rel_path] = result
    return result


def verify(finding, cache, root_real, fields, window):
    """Return None when the citation holds, else a reason string."""
    path = finding.get(fields["file"])
    raw_line = finding.get(fields["line"])
    quote = finding.get(fields["quote"])

    if not path:
        return "no %s" % fields["file"]
    if quote is None or not str(quote).strip():
        return "no %s -- a finding without a verbatim quote cannot be checked" % fields["quote"]
    try:
        line_no = int(raw_line)
    except (TypeError, ValueError):
        return "%s is not a number: %r" % (fields["line"], raw_line)

    lines, error = read_lines(cache, root_real, str(path))
    if error:
        return error
    if not 1 <= line_no <= len(lines):
        return "line %d is outside the file (%d lines)" % (line_no, len(lines))

    target = normalise(str(quote))
    if not target:
        return "quote is blank"

    low = max(0, line_no - 1 - window)
    high = min(len(lines), line_no + window)
    haystack = normalise(" ".join(lines[low:high]))
    if target in haystack:
        return None

    whole = normalise(" ".join(lines))
    if target in whole:
        return "quote is in the file but not within %d line(s) of %d" % (window, line_no)
    return "quote does not appear in the file"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="JSONL (or JSON array) of findings")
    parser.add_argument("--root", default=".", help="repository root the paths are relative to")
    parser.add_argument("--window", type=int, default=2,
                        help="how many lines either side of the cited line to accept")
    parser.add_argument("--file-field", default="file")
    parser.add_argument("--line-field", default="line")
    parser.add_argument("--quote-field", default="quote")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print("FAIL  --root is not a directory: %s" % args.root)
        return 1

    root_real = os.path.realpath(args.root)
    fields = {"file": args.file_field, "line": args.line_field, "quote": args.quote_field}

    findings, parse_errors = load_findings(args.input)
    cache, bad = {}, []

    for index, finding in enumerate(findings, 1):
        reason = verify(finding, cache, root_real, fields, args.window)
        if reason:
            bad.append((index, finding.get(fields["file"]), finding.get(fields["line"]), reason))

    print("findings read        %d" % len(findings))
    print("citations verified   %d" % (len(findings) - len(bad)))

    if parse_errors:
        print("\nparse errors:")
        for err in parse_errors[:10]:
            print("  %s" % err)
        if len(parse_errors) > 10:
            print("  ... %d more" % (len(parse_errors) - 10))

    if bad:
        print("\nunverified citations:")
        for index, path, line, reason in bad[:20]:
            print("  #%d  %s:%s  -- %s" % (index, path, line, reason))
        if len(bad) > 20:
            print("  ... %d more" % (len(bad) - 20))

    if parse_errors or bad:
        print("\nFAILURES -- drop or correct each of these before writing the report.")
        print("A finding whose quote is not in the code is a fabricated citation, not a near miss.")
        return 1

    if not findings:
        print("\nOK  no findings to verify")
        return 0

    print("\nOK  every finding quotes code that is really there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
