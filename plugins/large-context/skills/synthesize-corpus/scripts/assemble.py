#!/usr/bin/env python3
"""Validate extraction rows against a declared schema and report coverage gaps.

    python3 scripts/assemble.py --schema id,topic,amount --units 500 \
        --input rows.jsonl --out table.csv

Reads JSONL (one object per line, or a JSON array), checks every row against the
schema, and prints a coverage report naming what is missing. Writes a CSV only when
--out is given. Standard library only; no network, no installs.

Exit codes:
    0  every row valid and coverage complete
    1  rows were dropped, fields are missing, or a tripwire fired

The tripwires exist because an extraction pass that silently loses units produces a
table that looks correct and is not. Read the report before trusting the table.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter

# A field this fraction-or-more empty is called out. Extraction that whiffs on one
# field usually means the prompt named it in a way the source never uses.
EMPTY_FIELD_WARN = 0.30

# A field whose values are this fraction-or-more identical is called out. Near-constant
# output usually means the model answered the prompt rather than reading the source.
CONSTANT_FIELD_WARN = 0.95


def load_rows(path):
    """Read JSONL, or a single JSON array. Returns (rows, parse_errors)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            return [], ["whole file: %s" % exc]
        if not isinstance(data, list):
            return [], ["whole file: top-level JSON is not an array"]
        return [r for r in data if isinstance(r, dict)], [
            "row %d: not an object" % i for i, r in enumerate(data, 1) if not isinstance(r, dict)
        ]

    rows, errors = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            errors.append("line %d: %s" % (lineno, exc))
            continue
        if isinstance(obj, list):
            rows.extend(o for o in obj if isinstance(o, dict))
        elif isinstance(obj, dict):
            rows.append(obj)
        else:
            errors.append("line %d: not an object" % lineno)
    return rows, errors


def is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def check_schema(rows, schema):
    """Split rows into complete and incomplete. Returns (good, bad)."""
    good, bad = [], []
    for i, row in enumerate(rows, 1):
        missing = [f for f in schema if f not in row]
        if missing:
            bad.append((i, "missing field(s): %s" % ", ".join(missing)))
        else:
            good.append(row)
    return good, bad


def field_stats(rows, schema):
    """Per-field emptiness and value concentration."""
    stats = {}
    for field in schema:
        values = [r.get(field) for r in rows]
        empty = sum(1 for v in values if is_empty(v))
        filled = [v for v in values if not is_empty(v)]
        top_share = 0.0
        if filled:
            hashable = [v if isinstance(v, (str, int, float, bool)) else json.dumps(v, sort_keys=True)
                        for v in filled]
            top_share = Counter(hashable).most_common(1)[0][1] / float(len(hashable))
        stats[field] = {
            "empty": empty,
            "empty_share": empty / float(len(rows)) if rows else 0.0,
            "top_share": top_share,
        }
    return stats


def missing_units(rows, unit_field, expected_units):
    """Which source units produced no row. Returns (covered, missing_list_or_None)."""
    if not unit_field:
        return None, None
    seen = {str(r.get(unit_field)) for r in rows if not is_empty(r.get(unit_field))}
    if expected_units and isinstance(expected_units, list):
        return len(seen), sorted(set(map(str, expected_units)) - seen)
    return len(seen), None


def write_csv(rows, schema, out_path):
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=schema, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in schema})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="JSONL (or JSON array) of extracted rows")
    parser.add_argument("--schema", required=True, help="comma-separated required field names")
    parser.add_argument("--out", help="write the validated table here as CSV")
    parser.add_argument("--units", type=int, default=0,
                        help="how many source units were sent for extraction")
    parser.add_argument("--unit-field", default="source",
                        help="row field naming the source unit (default: source)")
    parser.add_argument("--unit-list", help="file of expected unit ids, one per line")
    args = parser.parse_args()

    schema = [f.strip() for f in args.schema.split(",") if f.strip()]
    if not schema:
        print("FAIL  --schema listed no fields")
        return 1

    rows, parse_errors = load_rows(args.input)
    good, bad = check_schema(rows, schema)

    expected_list = None
    if args.unit_list:
        with open(args.unit_list, encoding="utf-8") as fh:
            expected_list = [ln.strip() for ln in fh if ln.strip()]

    covered, missing = missing_units(good, args.unit_field, expected_list)
    stats = field_stats(good, schema)

    problems = []
    print("rows parsed          %d" % len(rows))
    print("rows valid           %d" % len(good))

    if parse_errors:
        problems.append("%d line(s) did not parse" % len(parse_errors))
        print("\nparse errors:")
        for err in parse_errors[:10]:
            print("  %s" % err)
        if len(parse_errors) > 10:
            print("  ... %d more" % (len(parse_errors) - 10))

    if bad:
        problems.append("%d row(s) failed the schema" % len(bad))
        print("\nschema failures:")
        for idx, why in bad[:10]:
            print("  row %d: %s" % (idx, why))
        if len(bad) > 10:
            print("  ... %d more" % (len(bad) - 10))

    if args.units:
        print("\nunits sent           %d" % args.units)
        if covered is not None:
            print("units represented    %d" % covered)
            if covered < args.units:
                problems.append("%d unit(s) produced no row" % (args.units - covered))

    if missing:
        problems.append("%d named unit(s) missing from the table" % len(missing))
        print("\nunits with no row:")
        for unit in missing[:20]:
            print("  %s" % unit)
        if len(missing) > 20:
            print("  ... %d more" % (len(missing) - 20))

    print("\nfield                empty   top-value share")
    for field in schema:
        s = stats[field]
        print("  %-18s %5d   %.0f%%" % (field, s["empty"], s["top_share"] * 100))
        if good and s["empty_share"] >= EMPTY_FIELD_WARN:
            problems.append("field '%s' is %.0f%% empty" % (field, s["empty_share"] * 100))
        if len(good) > 5 and s["top_share"] >= CONSTANT_FIELD_WARN:
            problems.append("field '%s' is %.0f%% one value" % (field, s["top_share"] * 100))

    if not good:
        problems.append("no valid rows at all")

    if args.out and good:
        write_csv(good, schema, args.out)
        print("\nwrote %s (%d rows)" % (args.out, len(good)))

    if problems:
        print("\nPROBLEMS -- do not report numbers from this table until each is resolved:")
        for p in problems:
            print("  - %s" % p)
        return 1

    print("\nOK  schema satisfied, coverage complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
