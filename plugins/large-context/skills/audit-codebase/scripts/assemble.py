#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/assemble.py
# Regenerate: python3 tools/materialize.py
"""Validate extraction rows against a declared schema and report coverage gaps.

    python3 scripts/assemble.py \
        --schema "source:str, topic:enum(price|bug|support|other), amount:num?, quote:str" \
        --input rows.jsonl --units 500 --out table.csv

Reads JSONL (one object per line, or a JSON array), checks every row against the
schema, and prints a coverage report naming what is missing. Writes a CSV only when
--out is given. Standard library only; no network, no installs.

Schema syntax, comma-separated:

    name              str, any value accepted (including empty)
    name:str          non-empty string required
    name:num          numeric required
    name:int          integer required
    name:enum(a|b|c)  must be one of the listed values
    name:...?         trailing ? marks the field nullable -- empty is valid,
                      and the field is exempt from the mostly-empty warning

Exit codes:
    0  no failures; warnings may still be printed and must be read
    1  at least one FAILURE -- the table is not safe to report from

FAILURES are facts: a row did not parse, a value violates the schema, a unit produced
no row, a unit produced more rows than --rows-per-unit allows. WARNINGS are heuristics
that are often but not always a defect; they never set the exit code, because a
legitimately sparse or skewed field must not deadlock a correct extraction.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

# A non-nullable field this fraction-or-more empty is flagged. Nullable fields are
# exempt -- the schema already said empty is expected there.
EMPTY_FIELD_WARN = 0.30

# A field whose values are this fraction-or-more identical is flagged. Near-constant
# output is often a model answering the prompt rather than reading the source -- but a
# genuinely skewed category is also real, so this is a warning, never a failure.
CONSTANT_FIELD_WARN = 0.95

# With --rows-per-unit many, a unit that legitimately contains nothing emits no row and
# is indistinguishable from a task that died. The extraction contract has to close that
# gap, because this script cannot tell the two apart from the rows alone.
SENTINEL_HINT = (
    " -- with --rows-per-unit many, a unit holding nothing must still emit one sentinel"
    " row, or an empty unit cannot be told apart from a failed one"
)

FIELD_RE = re.compile(r"""^\s*([A-Za-z_][\w-]*)\s*(?::\s*([a-z]+)\s*(\([^)]*\))?\s*)?(\?)?\s*$""")


def parse_schema(text):
    """'a:str, b:enum(x|y)?' -> [{name,type,values,nullable}]. Raises ValueError."""
    fields, depth, current = [], 0, ""
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)

    parsed = []
    for raw in fields:
        if not raw.strip():
            continue
        match = FIELD_RE.match(raw)
        if not match:
            raise ValueError("cannot parse schema field %r" % raw.strip())
        name, kind, values, nullable = match.groups()
        kind = kind or "any"
        if kind not in ("any", "str", "num", "int", "enum"):
            raise ValueError("unknown type %r for field %r" % (kind, name))
        allowed = None
        if kind == "enum":
            if not values:
                raise ValueError("enum field %r lists no values" % name)
            allowed = [v.strip() for v in values[1:-1].split("|") if v.strip()]
            if not allowed:
                raise ValueError("enum field %r lists no values" % name)
        parsed.append({
            "name": name,
            "type": kind,
            "values": allowed,
            # A bare name keeps the permissive behaviour: present, any value.
            "nullable": bool(nullable) or kind == "any",
        })
    if not parsed:
        raise ValueError("schema listed no fields")
    return parsed


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


def check_value(value, field):
    """Return an error string, or None when the value satisfies the field."""
    if is_empty(value):
        return None if field["nullable"] else "empty, but field is not nullable"

    kind = field["type"]
    if kind in ("num", "int"):
        if isinstance(value, bool):
            return "expected %s, got boolean" % kind
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "expected %s, got %r" % (kind, value)
        # json.loads accepts NaN and Infinity, and float() accepts the strings too.
        # Left in, a NaN turns every downstream sum into NaN silently, and int(NaN)
        # raises rather than returning a wrong answer. Neither is a valid value.
        if math.isnan(number) or math.isinf(number):
            return "expected a finite %s, got %r" % (kind, value)
        if kind == "int" and number != int(number):
            return "expected int, got %r" % value
    elif kind == "enum":
        if str(value) not in field["values"]:
            return "%r not in [%s]" % (value, "|".join(field["values"]))
    elif kind == "str":
        if not isinstance(value, str):
            return "expected str, got %s" % type(value).__name__
    return None


def check_rows(rows, schema):
    """Split rows into valid and invalid. Returns (good, bad)."""
    good, bad = [], []
    for index, row in enumerate(rows, 1):
        problems = []
        for field in schema:
            if field["name"] not in row:
                problems.append("%s: missing" % field["name"])
                continue
            error = check_value(row[field["name"]], field)
            if error:
                problems.append("%s: %s" % (field["name"], error))
        if problems:
            bad.append((index, "; ".join(problems)))
        else:
            good.append(row)
    return good, bad


def field_stats(rows, schema):
    """Per-field emptiness and value concentration."""
    stats = {}
    for field in schema:
        values = [r.get(field["name"]) for r in rows]
        empty = sum(1 for v in values if is_empty(v))
        filled = [v for v in values if not is_empty(v)]
        top_share = 0.0
        if filled:
            hashable = [v if isinstance(v, (str, int, float, bool)) else json.dumps(v, sort_keys=True)
                        for v in filled]
            top_share = Counter(hashable).most_common(1)[0][1] / float(len(hashable))
        stats[field["name"]] = {
            "empty": empty,
            "empty_share": empty / float(len(rows)) if rows else 0.0,
            "filled": len(filled),
            "top_share": top_share,
        }
    return stats


def unit_coverage(rows, unit_field, expected_list, rows_per_unit):
    """Returns (per_unit_counts, duplicates, missing_named)."""
    counts = defaultdict(int)
    for row in rows:
        value = row.get(unit_field)
        if not is_empty(value):
            counts[str(value)] += 1

    duplicates = []
    if rows_per_unit == "one":
        duplicates = sorted((u, n) for u, n in counts.items() if n > 1)

    missing = None
    if expected_list is not None:
        missing = sorted(set(map(str, expected_list)) - set(counts))
    return counts, duplicates, missing


def write_csv(rows, names, out_path):
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({n: row.get(n, "") for n in names})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="JSONL (or JSON array) of extracted rows")
    parser.add_argument("--schema", required=True,
                        help="comma-separated fields; see the module docstring for the syntax")
    parser.add_argument("--out", help="write the validated table here as CSV")
    parser.add_argument("--units", type=int, default=0,
                        help="how many source units were sent for extraction")
    parser.add_argument("--unit-field", default="source",
                        help="row field naming the source unit (default: source)")
    parser.add_argument("--unit-list", help="file of expected unit ids, one per line")
    parser.add_argument("--rows-per-unit", choices=("one", "many"), default="one",
                        help="'one' (default) treats a repeated unit id as a failure; "
                             "'many' allows several rows per unit, as when extracting "
                             "every transaction out of each shard")
    args = parser.parse_args()

    try:
        schema = parse_schema(args.schema)
    except ValueError as exc:
        print("FAIL  %s" % exc)
        return 1
    names = [f["name"] for f in schema]

    rows, parse_errors = load_rows(args.input)
    good, bad = check_rows(rows, schema)

    expected_list = None
    if args.unit_list:
        with open(args.unit_list, encoding="utf-8") as fh:
            expected_list = [ln.strip() for ln in fh if ln.strip()]

    counts, duplicates, missing = unit_coverage(good, args.unit_field, expected_list,
                                                args.rows_per_unit)
    stats = field_stats(good, schema)

    failures, warnings = [], []

    print("rows parsed          %d" % len(rows))
    print("rows valid           %d" % len(good))
    print("distinct units       %d" % len(counts))

    if parse_errors:
        failures.append("%d line(s) did not parse" % len(parse_errors))
        print("\nparse errors:")
        for err in parse_errors[:10]:
            print("  %s" % err)
        if len(parse_errors) > 10:
            print("  ... %d more" % (len(parse_errors) - 10))

    if bad:
        failures.append("%d row(s) violated the schema" % len(bad))
        print("\nschema violations:")
        for index, why in bad[:10]:
            print("  row %d: %s" % (index, why))
        if len(bad) > 10:
            print("  ... %d more" % (len(bad) - 10))

    if duplicates:
        failures.append("%d unit(s) produced more than one row "
                        "(pass --rows-per-unit many if that is intended)" % len(duplicates))
        print("\nrepeated unit ids:")
        for unit, count in duplicates[:10]:
            print("  %s -> %d rows" % (unit, count))
        if len(duplicates) > 10:
            print("  ... %d more" % (len(duplicates) - 10))

    if args.units:
        print("\nunits sent           %d" % args.units)
        print("units represented    %d" % len(counts))
        if len(counts) < args.units:
            failures.append("%d unit(s) produced no row%s"
                            % (args.units - len(counts), SENTINEL_HINT
                               if args.rows_per_unit == "many" else ""))
        elif len(counts) > args.units:
            failures.append("%d more unit id(s) than were sent" % (len(counts) - args.units))

    if missing:
        failures.append("%d named unit(s) missing from the table%s"
                        % (len(missing), SENTINEL_HINT
                           if args.rows_per_unit == "many" else ""))
        print("\nunits with no row:")
        for unit in missing[:20]:
            print("  %s" % unit)
        if len(missing) > 20:
            print("  ... %d more" % (len(missing) - 20))

    print("\nfield                type        empty   top-value share")
    for field in schema:
        name = field["name"]
        stat = stats[name]
        kind = field["type"] + ("?" if field["nullable"] and field["type"] != "any" else "")
        print("  %-18s %-10s %5d   %.0f%%" % (name, kind, stat["empty"], stat["top_share"] * 100))
        if good and not field["nullable"] and stat["empty_share"] >= EMPTY_FIELD_WARN:
            warnings.append("field '%s' is %.0f%% empty" % (name, stat["empty_share"] * 100))
        if stat["filled"] > 5 and stat["top_share"] >= CONSTANT_FIELD_WARN:
            warnings.append("field '%s' is %.0f%% a single value -- confirm that is real"
                            % (name, stat["top_share"] * 100))

    if not good:
        failures.append("no valid rows at all")

    if args.out and good:
        write_csv(good, names, args.out)
        print("\nwrote %s (%d rows)" % (args.out, len(good)))

    if warnings:
        print("\nWARNINGS -- not failures. Confirm each is genuine before reporting:")
        for warning in warnings:
            print("  - %s" % warning)

    if failures:
        print("\nFAILURES -- do not report numbers from this table until each is resolved:")
        for failure in failures:
            print("  - %s" % failure)
        return 1

    print("\nOK  schema satisfied, coverage complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
