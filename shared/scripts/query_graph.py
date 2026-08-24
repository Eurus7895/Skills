#!/usr/bin/env python3
"""Select a bounded, labelled slice of the index for one analysis task.

    python3 scripts/query_graph.py --index structure.json --packet src/api.py

The index is too big to read and a single file is too little to understand. This script
prints one *context packet*: the scope's own source, its public interface, the edges in
and out with the lines that prove them, and a manifest saying exactly what was left out.
The manifest is the point -- an agent that cannot see what it is missing will confidently
describe a module by the half of it that fitted.

Nothing here is ever silently truncated. A scope whose source exceeds the hard limit is
*partitioned*: the packet comes back with `partitioned: true` and a list of parts, and
each part is fetched by id with --part. A partial file is worse than a file in pieces,
because only one of the two announces itself.

Other queries:

    --inheritance PATH            resolved base classes for one file
    --cross-dir-edges             edges that leave their own directory
    --clusters                    directory -> files, for grouping scopes
    --call-candidates A --to B    import evidence that A *could* call into B

Call candidates always come back `verified: false`. An import edge proves a reference,
not an invocation; only reading the call site can promote it, and that is verify_doc.py's
job, not this one's.

Token counts are estimates (characters / 4), not measurements. They exist to make the
partitioning decision reproducible, not to predict a bill.

Exit codes: 0 ok, 2 input/schema error, 3 internal error.

Standard library only. Reads the index and the working tree; writes nothing.
"""

import argparse
import json
import os
import sys

SUPPORTED_SCHEMA = {2}
PACKET_VERSION = 1

# Assuming a 200k-token host window. Scope analysis gets a soft target and a hard
# ceiling; crossing the ceiling partitions rather than trims.
SOFT_LIMIT = 32000
HARD_LIMIT = 48000

CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    """Characters / 4. An estimate, and labelled as one everywhere it is reported."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def fail(message):
    sys.stderr.write("FAIL  %s\n" % message)
    return 2


def load_index(path):
    if not os.path.isfile(path):
        return None, "no such index: %s" % path
    try:
        with open(path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)
    if not isinstance(index, dict):
        return None, "%s does not contain a JSON object" % path
    if index.get("schema_version") not in SUPPORTED_SCHEMA:
        return None, ("%s declares schema_version %r; this script supports %s"
                      % (path, index.get("schema_version"), sorted(SUPPORTED_SCHEMA)))
    return index, None


def safe_path(root, path):
    """Resolve a repository-relative path, refusing anything that leaves the root.

    Both halves matter: a `../` in the string, and a symlink whose target is outside.
    The second is invisible to string checks, so realpath decides.
    """
    if not isinstance(path, str) or not path or path.startswith("/"):
        return None
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root, path))
    if full != root_real and not full.startswith(root_real + os.sep):
        return None
    return full


def read_source(root, path):
    full = safe_path(root, path)
    if full is None or not os.path.isfile(full):
        return None
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def usage_coverage(record):
    """absent / partial / complete -- how much of this file Ruff had an opinion on.

    Reported so the agent knows whether "not marked unused" means "used" or "never
    looked at". Those are not the same claim and must not read alike.
    """
    total, annotated = 0, 0
    for entry in record.get("imports", ()):
        bindings = entry.get("bindings") or ()
        total += len(bindings)
        usage = entry.get("usage") or {}
        annotated += sum(1 for b in bindings
                         if (usage.get(b) or {}).get("status") not in (None, "unknown"))
    if not total or not annotated:
        return "absent"
    return "complete" if annotated == total else "partial"


def interface_of(record, limit):
    """A neighbour's public names -- enough to know what it offers, not its body."""
    public = [s for s in record.get("symbols", ()) if not s["name"].startswith("_")]
    return [{"name": s["name"], "kind": s["kind"],
             "cite": "%s:%d" % (record["path"], s["line"])} for s in public[:limit]]


def edges_for(index, path):
    out_edges = [e for e in index.get("edges", ()) if e["from"] == path]
    in_edges = [e for e in index.get("edges", ()) if e["to"] == path]
    return out_edges, in_edges


def describe_edge(edge, record, direction):
    """An edge as the agent should cite it, with usage kept visibly separate."""
    other = edge["to"] if direction == "out" else edge["from"]
    # The citation line belongs to whichever file wrote the import statement.
    cite = "%s:%d" % (edge["from"], edge["line"])
    described = {"path": other, "cite": cite, "import": edge.get("import"),
                 "edge_id": edge["edge_id"], "relationship": "imports"}
    if direction == "out" and record is not None:
        usage = {}
        for entry in record.get("imports", ()):
            if entry.get("line") == edge["line"]:
                # The status alone here: the packet is bounded context, and it already
                # states the path and line the diagnostic would repeat back.
                for binding, verdict in (entry.get("usage") or {}).items():
                    usage[binding] = (verdict or {}).get("status")
        if usage:
            # Advisory, and named so at the point of use: a binding nothing reads is
            # still an import the file contains.
            described["binding_usage_advisory"] = usage
    return described


def parts_of(record, source, hard_limit):
    """Split one oversized file along its own top-level definitions.

    Partitioning by module or package cannot help a single file that is too big by
    itself, which is exactly the case that would otherwise be truncated. Boundaries are
    the top-level symbols the scanner already found, so the parts line up with something
    a reader can name.
    """
    lines = source.splitlines(True)
    anchors = sorted({s["line"] for s in record.get("symbols", ()) if s["line"] > 1})
    if not anchors:
        return []

    bounds = [1] + anchors + [len(lines) + 1]
    parts, start_index = [], 0
    while start_index < len(bounds) - 1:
        end_index = start_index + 1
        # Grow each part until it is close to the ceiling, so a file splits into a few
        # readable pieces rather than one per function.
        while end_index < len(bounds) - 1:
            text = "".join(lines[bounds[start_index] - 1:bounds[end_index + 1] - 1])
            if estimate_tokens(text) > hard_limit:
                break
            end_index += 1
        start, end = bounds[start_index], bounds[end_index] - 1
        text = "".join(lines[start - 1:end])
        names = [s["name"] for s in record.get("symbols", ())
                 if start <= s["line"] <= end]
        parts.append({
            "id": "%s#L%d-L%d" % (record["path"], start, end),
            "path": record["path"],
            "line_start": start,
            "line_end": end,
            "symbols": names,
            "token_estimate": estimate_tokens(text),
            # One definition can be bigger than the ceiling all by itself -- a generated
            # function, a large data literal. There is nothing left to split it on, so
            # the part is marked rather than handed over as if it fitted.
            "over_hard_limit": estimate_tokens(text) > hard_limit,
        })
        start_index = end_index
    return parts


def build_packet(index, root, path, part_id, includes, findings, limits, neighbours):
    by_path = {r["path"]: r for r in index.get("files", ())}
    record = by_path.get(path)
    if record is None:
        return None, "%s is not in the index" % path

    source = read_source(root, path)
    if source is None:
        return None, "cannot read %s under the root (missing, or outside it)" % path

    out_edges, in_edges = edges_for(index, path)
    included, omitted = [], []

    snippets = []
    partitioned = False
    parts = []

    if part_id:
        parts = parts_of(record, source, limits["hard"])
        chosen = next((p for p in parts if p["id"] == part_id), None)
        if chosen is None:
            return None, "%s is not a part of %s" % (part_id, path)
        if chosen["over_hard_limit"]:
            return None, ("%s is a single definition estimated at %d tokens, over the "
                          "%d hard limit, and there is nothing inside it to split on. "
                          "Returning it would hand back more than the ceiling promises"
                          % (part_id, chosen["token_estimate"], limits["hard"]))
        lines = source.splitlines(True)
        text = "".join(lines[chosen["line_start"] - 1:chosen["line_end"]])
        snippets.append({"path": path, "line_start": chosen["line_start"],
                         "line_end": chosen["line_end"], "text": text})
        included.append(chosen["id"])
        omitted.extend(p["id"] for p in parts if p["id"] != part_id)
        scope_id = "module:%s#%s" % (path, part_id.split("#", 1)[1])
    else:
        whole = estimate_tokens(source)
        if whole > limits["hard"]:
            parts = parts_of(record, source, limits["hard"])
            if parts:
                partitioned = True
                omitted.append("%s source (%d parts, fetch each with --part)"
                               % (path, len(parts)))
            else:
                # No top-level anchors to split on. Say so and refuse; a caller that
                # gets no source is obliged to notice, one that gets half of it is not.
                return None, ("%s estimates %d tokens, over the %d hard limit, and has "
                              "no top-level definitions to partition on"
                              % (path, whole, limits["hard"]))
        else:
            snippets.append({"path": path, "line_start": 1,
                             "line_end": source.count("\n") + 1, "text": source})
            included.append(path)
        scope_id = "module:%s" % path

    neighbour_records = []
    for edge in out_edges + in_edges:
        other = edge["to"] if edge["from"] == path else edge["from"]
        if other in by_path and other not in [n["path"] for n in neighbour_records]:
            neighbour_records.append(by_path[other])

    interfaces = []
    for neighbour in neighbour_records:
        interfaces.append({"path": neighbour["path"],
                           "exact": neighbour.get("exact"),
                           "symbols": interface_of(neighbour, neighbours)})
        included.append("%s (interface only)" % neighbour["path"])
        omitted.append("%s body" % neighbour["path"])

    extra = []
    for wanted in includes:
        target = by_path.get(wanted)
        if target is None:
            omitted.append("%s (requested, but not in the index)" % wanted)
            continue
        text = read_source(root, wanted)
        if text is None:
            omitted.append("%s (requested, but unreadable)" % wanted)
            continue
        extra.append({"path": wanted, "line_start": 1,
                      "line_end": text.count("\n") + 1, "text": text})
        included.append("%s (requested)" % wanted)
    snippets.extend(extra)

    packet = {
        "packet_version": PACKET_VERSION,
        "packet_id": "packet:%s" % (part_id or ("module:%s" % path)),
        "task": "analyze_module",
        "source_revision": (index.get("source") or {}).get("revision"),
        "source_dirty": (index.get("source") or {}).get("dirty"),
        "scope": {
            "id": scope_id,
            "path": path,
            "lang": record.get("lang"),
            "loc": record.get("loc"),
            "exact_parse": record.get("exact"),
            "source_hash": record.get("source_hash"),
        },
        "symbols": [{"name": s["name"], "kind": s["kind"],
                     "cite": "%s:%d" % (path, s["line"])}
                    for s in record.get("symbols", ())],
        "classes": record.get("classes", []),
        "imports": [describe_edge(e, record, "out") for e in out_edges],
        "imported_by": [describe_edge(e, None, "in") for e in in_edges],
        "cross_directory_edges": [
            describe_edge(e, record, "out") for e in out_edges
            if os.path.dirname(e["from"]) != os.path.dirname(e["to"])],
        "neighbour_interfaces": interfaces,
        "source_snippets": snippets,
        "previous_findings": findings,
        "import_usage_coverage": usage_coverage(record),
        "partitioned": partitioned,
        "parts": parts if partitioned else [],
        "context_manifest": {
            "included": included,
            "omitted": omitted,
            "token_estimate": estimate_tokens(
                json.dumps(snippets) + json.dumps(interfaces)),
            "token_estimate_is_an_estimate": True,
            "soft_limit": limits["soft"],
            "hard_limit": limits["hard"],
            "required_coverage": 1.0,
        },
    }
    manifest = packet["context_manifest"]
    manifest["over_soft_limit"] = manifest["token_estimate"] > limits["soft"]
    return packet, None


def inheritance(index, path):
    record = next((r for r in index.get("files", ()) if r["path"] == path), None)
    if record is None:
        return None, "%s is not in the index" % path
    if "classes" not in record:
        # Absent, not empty: the file was never given detail, which is a different
        # statement from "this file has no classes".
        return {"path": path, "detail_available": False, "classes": []}, None
    rows = []
    for cls in record["classes"]:
        rows.append({
            "name": cls["name"],
            "cite": "%s:%d" % (path, cls["line"]),
            "bases": [{"name": b["name"],
                       "resolved": b.get("resolved"),
                       "cite": ("%s:%d" % (b["resolved"], b["line"]))
                                if b.get("resolved") else None}
                      for b in cls.get("bases", ())],
        })
    return {"path": path, "detail_available": True, "classes": rows}, None


def cross_dir_edges(index):
    rows = []
    for edge in index.get("edges", ()):
        if os.path.dirname(edge["from"]) != os.path.dirname(edge["to"]):
            rows.append({"from": edge["from"], "to": edge["to"],
                         "cite": "%s:%d" % (edge["from"], edge["line"]),
                         "edge_id": edge["edge_id"]})
    return {"count": len(rows), "edges": rows}


def clusters(index):
    grouped = {}
    for record in index.get("files", ()):
        grouped.setdefault(os.path.dirname(record["path"]) or ".", []).append(record["path"])
    fan_in = index.get("fan_in", {})
    return {"clusters": [
        {"directory": directory,
         "files": sorted(paths),
         "fan_in_total": sum(fan_in.get(p, 0) for p in paths)}
        for directory, paths in sorted(grouped.items())]}


def call_candidates(index, caller, callee):
    """Import evidence only. Never verified -- see the module docstring."""
    edges = [e for e in index.get("edges", ())
             if e["from"] == caller and e["to"] == callee]
    by_path = {r["path"]: r for r in index.get("files", ())}
    target = by_path.get(callee)
    bindings = sorted({b for e in edges for b in e.get("bindings", ())})
    return {
        "caller": caller,
        "callee": callee,
        "verified": False,
        "why": "an import edge proves a reference, not an invocation; read the call "
               "site and cite it to make this a verified claim",
        "import_evidence": [{"cite": "%s:%d" % (e["from"], e["line"]),
                             "edge_id": e["edge_id"]} for e in edges],
        "bindings": bindings,
        "callee_symbols": [] if target is None else
                          [{"name": s["name"], "kind": s["kind"],
                            "cite": "%s:%d" % (callee, s["line"])}
                           for s in target.get("symbols", ())],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", default="structure.json", help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository the index describes")
    parser.add_argument("--packet", metavar="PATH", help="build a context packet for this file")
    parser.add_argument("--part", metavar="ID", help="fetch one part of a partitioned scope")
    parser.add_argument("--include", action="append", default=[], metavar="PATH",
                        help="also include this file's source; repeatable")
    parser.add_argument("--findings", metavar="FILE",
                        help="JSON list of findings from a previous attempt")
    parser.add_argument("--inheritance", metavar="PATH", help="resolved bases for this file")
    parser.add_argument("--cross-dir-edges", action="store_true",
                        help="edges that leave their own directory")
    parser.add_argument("--clusters", action="store_true", help="directory groupings")
    parser.add_argument("--call-candidates", metavar="PATH", help="possible caller")
    parser.add_argument("--to", metavar="PATH", help="possible callee")
    parser.add_argument("--soft-limit", type=int, default=None)
    parser.add_argument("--hard-limit", type=int, default=HARD_LIMIT)
    parser.add_argument("--neighbours", type=int, default=12,
                        help="public symbols shown per neighbouring module")
    args = parser.parse_args()

    index, error = load_index(args.index)
    if error:
        return fail(error)
    if not os.path.isdir(args.root):
        return fail("--root is not a directory: %s" % args.root)
    if args.soft_limit is None:
        # Lowering only the ceiling is the common case; the default target follows it
        # down rather than becoming an error the caller has to work around.
        args.soft_limit = min(SOFT_LIMIT, args.hard_limit)
    elif args.soft_limit > args.hard_limit:
        return fail("--soft-limit %d is above --hard-limit %d"
                    % (args.soft_limit, args.hard_limit))

    if args.packet:
        findings = []
        if args.findings:
            # verify_doc.py writes findings.jsonl -- one object per line, which is what
            # references/context-policy.md tells the caller to pass here. json.load
            # chokes on the second line, so the documented retry never gets a packet.
            try:
                with open(args.findings, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as exc:
                return fail("cannot read --findings %s: %s" % (args.findings, exc))
            try:
                if text.lstrip().startswith("["):
                    findings = json.loads(text)
                else:
                    findings = [json.loads(line) for line in text.splitlines()
                                if line.strip()]
            except ValueError as exc:
                return fail("cannot parse --findings %s: %s" % (args.findings, exc))
        result, error = build_packet(
            index, args.root, args.packet, args.part, args.include, findings,
            {"soft": args.soft_limit, "hard": args.hard_limit}, args.neighbours)
    elif args.inheritance:
        result, error = inheritance(index, args.inheritance)
    elif args.cross_dir_edges:
        result, error = cross_dir_edges(index), None
    elif args.clusters:
        result, error = clusters(index), None
    elif args.call_candidates:
        if not args.to:
            return fail("--call-candidates needs --to")
        result, error = call_candidates(index, args.call_candidates, args.to), None
    else:
        return fail("nothing to do: pass --packet, --inheritance, --cross-dir-edges, "
                    "--clusters, or --call-candidates")

    if error:
        return fail(error)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
