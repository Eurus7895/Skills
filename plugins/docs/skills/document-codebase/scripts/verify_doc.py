#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/verify_doc.py
# Regenerate: python3 tools/materialize.py
"""Check every claim against the index and the source; report, never rewrite.

    python3 scripts/verify_doc.py --claims claims.jsonl --fragments fragments.jsonl \\
        --index structure.json --root . --out-dir .docs-build

A claim is a structural statement with a citation. This script decides whether the
citation holds -- the file exists, the line is inside it, the bytes still hash to what
was scanned, and the relationship is really in the graph or really in the syntax tree.

It never edits prose. A rejected claim comes back marked rejected, with a finding saying
why; rewriting the sentence around it belongs to whoever wrote the sentence. A verifier
that also revised would be marking its own homework.

Entity ids:

    module:<path>                     a file
    symbol:<path>:<name>              a top-level function or class
    class:<path>:<Name>               a class, where detail was extracted
    method:<path>:<Class>.<name>      a method on such a class

Claim kinds and how each is decided:

    defines     the symbol is in the file's symbol table
    contains    the method is on the class, in the extracted detail
    imports     the edge is in the dependency graph, at the cited line
    inherits    the base resolved to the named file
    calls       the cited line really holds a call to that name, *and* the name is
                bound by an import from the file the callee lives in. Python only:
                elsewhere there is no tree to check and the claim stays a candidate.
    responsibility  an inference; recorded as supported_inference, never as fact

Statuses out: verified, supported_inference, candidate, unsupported, needs_context,
rejected. Three of those are easy to confuse and are kept apart deliberately:

    needs_context  undecidable from what was supplied. Retry with more
    unsupported    undecidable in principle -- a call target computed at run time.
                   Retrying cannot help, so it never re-enters the loop
    rejected       the source contradicts the claim

Exit codes: 0 every claim decided without rejection, 1 something was rejected or needs
context, 2 input/schema error, 3 internal error.

Standard library only. Reads the inputs and the working tree; writes only --out-dir.
"""

import argparse
import ast
import hashlib
import json
import os
import sys

SUPPORTED_SCHEMA = {2}

KINDS = ("defines", "contains", "imports", "inherits", "calls", "responsibility")

# Worst status wins when a fragment's claims disagree: one rejected claim makes the
# whole fragment untrustworthy, however many verified ones surround it.
#
# `unsupported` sits above `candidate` and below `needs_context`: it is a permanent
# answer, not a temporary one -- more context will never resolve a call target that is
# computed at run time -- so it is worse than "undecided here" but is not a retry.
SEVERITY = {"verified": 0, "supported_inference": 1, "candidate": 2,
            "unsupported": 3, "needs_context": 4, "rejected": 5}


def parse_entity(entity):
    """'class:src/a.py:Repo' -> ('class', 'src/a.py', 'Repo'). None when unparseable."""
    if not isinstance(entity, str) or ":" not in entity:
        return None
    kind, rest = entity.split(":", 1)
    if kind == "module":
        return (kind, rest, None)
    if kind in ("symbol", "class", "method"):
        if ":" not in rest:
            return None
        path, name = rest.rsplit(":", 1)
        return (kind, path, name)
    return None


def file_hash(full):
    digest = hashlib.sha256()
    try:
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


class Verifier(object):
    def __init__(self, index, root):
        self.index = index
        self.root = root
        self.by_path = {r["path"]: r for r in index.get("files", ())}
        self.edges = {}
        for edge in index.get("edges", ()):
            self.edges.setdefault((edge["from"], edge["to"]), []).append(edge)
        self.findings = []
        self._trees = {}

    # -- helpers ---------------------------------------------------------------

    def finding(self, claim_id, code, message, retryable=False):
        self.findings.append({"claim_id": claim_id, "code": code, "message": message,
                              "retryable": retryable})

    def tree(self, path):
        """Parsed module, cached. None when the file is not parseable Python."""
        if path in self._trees:
            return self._trees[path]
        record = self.by_path.get(path)
        parsed = None
        if record is not None and record.get("lang") == "python":
            full = os.path.join(self.root, path)
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    parsed = ast.parse(fh.read())
            except (OSError, SyntaxError, ValueError):
                parsed = None
        self._trees[path] = parsed
        return parsed

    def check_evidence(self, claim):
        """Every claim must be citable. Returns True when the citations hold."""
        claim_id = claim.get("id")
        evidence = claim.get("evidence") or []
        if not evidence:
            self.finding(claim_id, "V001", "claim carries no evidence")
            return False
        ok = True
        for item in evidence:
            path = item.get("path")
            record = self.by_path.get(path)
            if record is None:
                self.finding(claim_id, "V002", "evidence names %r, which is not in the "
                                               "index" % path)
                ok = False
                continue
            start, end = item.get("line_start"), item.get("line_end", item.get("line_start"))
            if not isinstance(start, int) or start < 1 or start > record.get("loc", 0):
                self.finding(claim_id, "V003", "evidence cites %s:%r, outside a %d-line "
                             "file" % (path, start, record.get("loc", 0)))
                ok = False
                continue
            if isinstance(end, int) and end < start:
                self.finding(claim_id, "V003", "evidence range %s:%d-%d runs backwards"
                             % (path, start, end))
                ok = False
                continue
            recorded = item.get("source_hash") or record.get("source_hash")
            current = file_hash(os.path.join(self.root, path))
            if current is None:
                self.finding(claim_id, "V004", "evidence file %s cannot be read" % path)
                ok = False
            elif recorded and recorded != current:
                # Not "wrong", but no longer checkable: the line may now say anything.
                self.finding(claim_id, "V005", "%s changed since it was scanned; the "
                             "citation no longer proves anything" % path, retryable=True)
                ok = False
        return ok

    # -- per-kind verification -------------------------------------------------

    def verify_defines(self, claim, subject, obj):
        record = self.by_path.get(obj[1])
        if record is None:
            return "rejected", "%s is not in the index" % obj[1]
        if subject[1] != obj[1]:
            return "rejected", ("%s cannot define something in %s -- a definition is in "
                                "one file" % (subject[1], obj[1]))
        names = {s["name"] for s in record.get("symbols", ())}
        if obj[2] in names:
            return "verified", None
        if not record.get("exact"):
            return "needs_context", ("%s was regex-scanned, so its symbol table is "
                                     "incomplete; %r may exist" % (obj[1], obj[2]))
        return "rejected", "%s defines no top-level %r" % (obj[1], obj[2])

    def verify_contains(self, claim, subject, obj):
        record = self.by_path.get(subject[1])
        if record is None:
            return "rejected", "%s is not in the index" % subject[1]
        if "classes" not in record:
            return "needs_context", ("%s carries no class detail; rerun the scanner "
                                     "with --detail" % subject[1])
        cls = next((c for c in record["classes"] if c["name"] == subject[2]), None)
        if cls is None:
            return "rejected", "%s defines no class %r" % (subject[1], subject[2])
        wanted = obj[2].split(".")[-1]
        if any(m["name"] == wanted for m in cls.get("methods", ())):
            return "verified", None
        return "rejected", "%s.%s has no method %r" % (subject[1], subject[2], wanted)

    def verify_imports(self, claim, subject, obj):
        edges = self.edges.get((subject[1], obj[1]))
        if not edges:
            record = self.by_path.get(subject[1])
            if record is not None and not record.get("exact"):
                return "needs_context", ("%s was regex-scanned; its import list is "
                                         "approximate, so a missing edge is not proof"
                                         % subject[1])
            return "rejected", "the graph has no import edge %s -> %s" % (subject[1], obj[1])
        lines = {e["line"] for e in edges}
        cited = {i.get("line_start") for i in claim.get("evidence", ())}
        if cited and not (cited & lines):
            return "rejected", ("the import %s -> %s is at line(s) %s, not %s"
                                % (subject[1], obj[1], sorted(lines), sorted(cited)))
        return "verified", None

    def verify_inherits(self, claim, subject, obj):
        record = self.by_path.get(subject[1])
        if record is None:
            return "rejected", "%s is not in the index" % subject[1]
        if "classes" not in record:
            return "needs_context", ("%s carries no class detail; rerun the scanner "
                                     "with --detail" % subject[1])
        cls = next((c for c in record["classes"] if c["name"] == subject[2]), None)
        if cls is None:
            return "rejected", "%s defines no class %r" % (subject[1], subject[2])
        for base in cls.get("bases", ()):
            if base.get("resolved") == obj[1] and base["name"].split(".")[-1] == obj[2]:
                return "verified", None
        written = [b["name"] for b in cls.get("bases", ())]
        if any(b["name"].split(".")[-1] == obj[2] and not b.get("resolved")
               for b in cls.get("bases", ())):
            # The name is there but the scanner could not prove where it comes from.
            # Inventing the link is exactly the failure this pipeline exists to stop.
            return "needs_context", ("%s names %r as a base but it did not resolve to a "
                                     "defining file" % (subject[2], obj[2]))
        return "rejected", "%s's bases are %s, not %r" % (subject[2], written, obj[2])

    def verify_calls(self, claim, subject, obj):
        """A call is verified only when the cited line really holds one, by that name,
        bound by an import from the file the callee lives in.

        Both halves are needed. A matching name alone would verify `handle()` against
        any local function of the same name; an import alone is what an edge already
        says. Together they are as close to a call graph as reading one line can get.
        """
        caller_path = subject[1]
        record = self.by_path.get(caller_path)
        if record is None:
            return "rejected", "%s is not in the index" % caller_path
        if record.get("lang") != "python":
            return "candidate", ("%s is %s; there is no tree to check a call site "
                                 "against, so this stays a candidate"
                                 % (caller_path, record.get("lang")))
        tree = self.tree(caller_path)
        if tree is None:
            return "needs_context", "%s did not parse; the call site cannot be read" % caller_path

        wanted = obj[2].split(".")[-1]
        lines = {i.get("line_start") for i in claim.get("evidence", ())
                 if i.get("path") == caller_path}
        if not lines:
            return "needs_context", ("no evidence line inside %s, so there is no call "
                                     "site to read" % caller_path)

        bindings = {b for edge in self.edges.get((caller_path, obj[1]), ())
                    for b in edge.get("bindings", ())}

        near_miss, computed = None, False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.lineno not in lines:
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name, base = func.id, None
            elif isinstance(func, ast.Attribute):
                name = func.attr
                base = func.value.id if isinstance(func.value, ast.Name) else None
            else:
                # A call through a variable, a subscript, or the result of another call.
                # There *is* a call here; its target is decided at run time. Saying "no
                # call at that line" would be false, and saying "verified" would be a
                # guess -- so neither, and the claim is recorded as unsupportable.
                computed = True
                continue
            if name != wanted:
                near_miss = near_miss or name
                continue
            # Direct: `from callee import wanted` bound the name itself.
            if base is None and wanted in bindings:
                return "verified", None
            # Qualified: `import callee as base` bound the module the call goes through.
            if base is not None and base in bindings:
                return "verified", None
            if not bindings:
                # No direct edge at all. The call could still reach that file through a
                # re-export, which this script cannot see -- so ask, rather than deny.
                return "needs_context", ("%s calls %r at that line, but imports nothing "
                                         "from %s; if it arrives by re-export, supply "
                                         "the chain" % (caller_path, wanted, obj[1]))
            # The file *is* imported, and this is not one of the names it brought in.
            # The call at that line is to something else -- a local definition, or an
            # import from somewhere else entirely.
            return "rejected", ("%s calls %r at that line, but the import from %s binds "
                                "%s -- not that name"
                                % (caller_path, wanted, obj[1], sorted(bindings)))
        if near_miss:
            return "rejected", ("the cited line in %s calls %r, not %r"
                                % (caller_path, near_miss, wanted))
        if computed:
            return "unsupported", ("the cited line in %s calls something computed at run "
                                   "time -- through a variable, a subscript, or another "
                                   "call. Static analysis cannot name the target, and no "
                                   "further context will change that" % caller_path)
        return "rejected", "there is no call at %s:%s" % (caller_path, sorted(lines))

    # -- driver ----------------------------------------------------------------

    def verify(self, claim):
        claim_id = claim.get("id")
        kind = claim.get("kind")
        if kind not in KINDS:
            self.finding(claim_id, "V006", "unknown claim kind %r" % kind)
            return "rejected"

        if kind == "responsibility":
            # An inference about meaning. There is nothing deterministic to check, and
            # pretending otherwise is how an opinion becomes a fact.
            return "supported_inference"

        if not self.check_evidence(claim):
            return "needs_context" if any(
                f["retryable"] for f in self.findings if f["claim_id"] == claim_id
            ) else "rejected"

        subject = parse_entity(claim.get("subject"))
        obj = parse_entity(claim.get("object"))
        if subject is None or obj is None:
            self.finding(claim_id, "V007", "subject %r or object %r is not a valid "
                         "entity id" % (claim.get("subject"), claim.get("object")))
            return "rejected"

        status, message = getattr(self, "verify_" + kind)(claim, subject, obj)
        if message:
            code = {"rejected": "V010", "needs_context": "V011",
                    "candidate": "V012", "unsupported": "V014"}.get(status, "V013")
            self.finding(claim_id, code, message, retryable=(status == "needs_context"))
        return status


def load_rows(path, label):
    """JSONL of objects. Returns (rows, error)."""
    if not os.path.isfile(path):
        return None, "no such %s file: %s" % (label, path)
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


def duplicate_fingerprints(findings):
    """A finding seen twice means the retry loop is not making progress."""
    seen, repeated = set(), []
    for row in findings:
        key = (row["claim_id"], row["code"], row["message"])
        if key in seen:
            repeated.append(key)
        seen.add(key)
    return repeated


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claims", required=True, help="JSONL of claims")
    parser.add_argument("--fragments", help="JSONL of fragments referencing those claims")
    parser.add_argument("--index", default="structure.json", help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository the index describes")
    parser.add_argument("--out-dir", default=".docs-build", help="where to write results")
    args = parser.parse_args()

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
    if not os.path.isdir(args.root):
        sys.stderr.write("FAIL  --root is not a directory: %s\n" % args.root)
        return 2

    claims, error = load_rows(args.claims, "claims")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    fragments = []
    if args.fragments:
        fragments, error = load_rows(args.fragments, "fragments")
        if error:
            sys.stderr.write("FAIL  %s\n" % error)
            return 2

    verifier = Verifier(index, args.root)
    seen_ids = set()
    for claim in claims:
        claim_id = claim.get("id")
        if claim_id in seen_ids:
            verifier.finding(claim_id, "V008", "claim id appears more than once")
            claim["status"] = "rejected"
            continue
        seen_ids.add(claim_id)
        claim["status"] = verifier.verify(claim)

    # A fragment is only as good as its worst claim, and a reference to a claim that
    # was never supplied is itself a defect.
    status_by_claim = {c.get("id"): c["status"] for c in claims}
    for fragment in fragments:
        statuses = []
        for claim_id in fragment.get("claim_ids", ()) or ():
            if claim_id not in status_by_claim:
                verifier.finding(claim_id, "V009", "fragment %r references a claim that "
                                 "was not supplied" % fragment.get("fragment_id"))
                statuses.append("rejected")
            else:
                statuses.append(status_by_claim[claim_id])
        fragment["status"] = max(statuses, key=lambda s: SEVERITY[s]) if statuses \
            else "supported_inference"

    repeated = duplicate_fingerprints(verifier.findings)
    for key in repeated:
        verifier.findings.append({
            "claim_id": key[0], "code": "V020", "retryable": False,
            "message": "this finding has already been reported for this claim; the "
                       "retry loop is not making progress -- stop and report it"})

    if not os.path.isdir(args.out_dir):
        os.makedirs(args.out_dir)

    def dump(name, rows):
        with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    dump("claims.verified.jsonl", claims)
    if args.fragments:
        dump("fragments.verified.jsonl", fragments)
    dump("findings.jsonl", verifier.findings)

    counts = {}
    for claim in claims:
        counts[claim["status"]] = counts.get(claim["status"], 0) + 1
    print("claims: " + ", ".join("%d %s" % (n, s) for s, n in sorted(counts.items())))
    print("findings: %d (%d retryable)" % (
        len(verifier.findings), sum(1 for f in verifier.findings if f["retryable"])))
    for row in verifier.findings:
        print("  %s  %-24s %s" % (row["code"], row["claim_id"], row["message"]))
    print("wrote %s" % args.out_dir)

    # A fragment can be blocked by something no claim status shows: a reference to a
    # claim that was never supplied. Counting only claims there would exit 0 and let the
    # document builder drop the fragment without anyone being told.
    blocked = (counts.get("rejected", 0) + counts.get("needs_context", 0)
               + sum(1 for f in fragments
                     if f["status"] in ("rejected", "needs_context")))
    return 1 if blocked else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
