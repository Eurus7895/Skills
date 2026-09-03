#!/usr/bin/env python3
"""Write the structural claims that are already in the index.

    python3 scripts/derive_claims.py --index .docs-build/structure.json \\
        --units .docs-build/units.txt --out .docs-build/claims.jsonl

`defines`, `imports` and `inherits` are facts `scan_repo.py` already extracted. Asking a
model to write them out spends budget copying a table it was handed, and buys a chance of
copying it wrong -- a line number off by one, an edge that was never there. There is
nothing to think about here, so nothing thinks.

**This is not the analysis, and a run made only of this is not a documented repository.**
`verify_doc.py` will pass every row below, because a claim taken out of the index and
checked against the index agrees with itself. What the model's budget is for is what no
index holds: what a module is for, what it owns, how it fails, why a boundary is where it
is. Those go in `module-analysis.jsonl`, and `quality_docs.py` counts them.

Only modules named in `units.txt` get claims. Everything else is covered in a line in the
document and does not need a claim apiece.

Standard library only. Deterministic: same index, same bytes.

Exit codes: 0 ok, 2 input error, 3 internal error.
"""

import argparse
import json
import os
import sys


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def claims_for(index, units):
    """Every structural claim the index already supports, for the modules in scope."""
    edges = {}
    for edge in index.get("edges", ()):
        edges.setdefault(edge["from"], []).append(edge)
    index_hash = index.get("index_hash")

    rows = []
    for record in sorted(index.get("files", ()), key=lambda r: r["path"]):
        path = record["path"]
        if path not in units:
            continue
        for symbol in record.get("symbols", ()):
            rows.append({
                "id": "claim:defines:%s:%s" % (path, symbol["name"]),
                "kind": "defines", "subject": "module:%s" % path,
                "object": "symbol:%s:%s" % (path, symbol["name"]),
                "evidence": [{"path": path, "line_start": symbol["line"],
                              "line_end": symbol["line"]}],
                "index_hash": index_hash})
        for edge in sorted(edges.get(path, ()), key=lambda e: (e["to"], e["line"])):
            rows.append({
                "id": "claim:imports:%s:%s" % (path, edge["to"]),
                "kind": "imports", "subject": "module:%s" % path,
                "object": "module:%s" % edge["to"],
                "evidence": [{"path": path, "line_start": edge["line"],
                              "line_end": edge["line"]}],
                "index_hash": index_hash})
        # Inheritance needs `--detail`; a scan without it has no `classes` key at all,
        # which is different from a file with no classes and is left alone here.
        for cls in record.get("classes", ()):
            for base in cls.get("bases", ()):
                if not isinstance(base, dict):
                    continue
                target, name = base.get("resolved"), base.get("name")
                if not target or not name:
                    # An unresolved base is listed by the class graph and claimed by
                    # nobody. A guess here would be a claim the source cannot support.
                    continue
                line = base.get("line", cls.get("line", 1))
                rows.append({
                    "id": "claim:inherits:%s:%s:%s" % (path, cls["name"], name),
                    "kind": "inherits", "subject": "class:%s:%s" % (path, cls["name"]),
                    "object": "class:%s:%s" % (target, name.rsplit(".", 1)[-1]),
                    "evidence": [{"path": path, "line_start": line, "line_end": line}],
                    "index_hash": index_hash})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--units", required=True,
                        help="units.txt: the modules this run describes in full")
    parser.add_argument("--out", default=".docs-build/claims.jsonl")
    args = parser.parse_args()

    if not os.path.isfile(args.index):
        return fail("no such index: %s" % args.index)
    try:
        with open(args.index, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        return fail("cannot read %s: %s" % (args.index, exc))
    if index.get("schema_version") != 2:
        return fail("unsupported index schema_version %r" % index.get("schema_version"))
    if not os.path.isfile(args.units):
        return fail("no such units file: %s" % args.units)
    with open(args.units, encoding="utf-8") as fh:
        units = {line.strip() for line in fh if line.strip()}

    known = {record["path"] for record in index.get("files", ())}
    unknown = sorted(units - known)
    if unknown:
        return fail("units.txt names %d path(s) the index does not hold: %s"
                    % (len(unknown), ", ".join(unknown[:3])))

    rows = claims_for(index, units)
    directory = os.path.dirname(args.out)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    kinds = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print("wrote %d claim(s) to %s: %s" % (
        len(rows), args.out,
        ", ".join("%d %s" % (count, kind) for kind, count in sorted(kinds.items()))
        or "none"))
    print("These are copied from the index, not read from the source. The reading goes "
          "in module-analysis.jsonl.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
