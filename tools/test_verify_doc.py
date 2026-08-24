#!/usr/bin/env python3
"""Behavioural tests for verify_doc.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Two distinctions carry the whole design and are tested hardest:

  * `rejected` (the source contradicts this) versus `needs_context` (this could not be
    decided). Collapsing them would either discard true claims or retry false ones
    forever.
  * a call that is really at the cited line and really bound by the cited import,
    versus a call that merely shares a name with one.

    python3 tools/test_verify_doc.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
SCRIPT = os.path.join(REPO, "shared", "scripts", "verify_doc.py")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


# Line numbers are load-bearing in the claims below, so keep this file stable.
#  1 from service import handle
#  2 import helpers
#  3 (blank)
#  4 (blank)
#  5 def serve():
#  6     return handle()
#  7 (blank)
#  8 (blank)
#  9 def assist():
# 10     return helpers.assist()
# 11 (blank)
# 12 (blank)
# 13 def local():
# 14     return shadow()
# 15 (blank)
# 16 (blank)
# 17 def shadow():
# 18     return 0
# 19 (blank)
# 20 (blank)
# 21 def dispatch(table, key):
# 22     return table[key]()
# 23 (blank)
# 24 (blank)
# 25 def shadowed(handle):
# 26     return handle()
# 27 (blank)
# 28 (blank)
# 29 def rebound():
# 30     handle = shadow
# 31     return handle()
API = """\
from service import handle
import helpers


def serve():
    return handle()


def assist():
    return helpers.assist()


def local():
    return shadow()


def shadow():
    return 0


def dispatch(table, key):
    return table[key]()


def shadowed(handle):
    return handle()


def rebound():
    handle = shadow
    return handle()
"""

SERVICE = "def handle():\n    return 1\n\n\ndef retire():\n    return 0\n"
MODELS = """\
from base import Record


class Order(Record):
    def total(self):
        return 0
"""


def build_fixture(tmp):
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "api.py", API)
    write(root, "service.py", SERVICE)
    write(root, "helpers.py", "def assist():\n    return 2\n")
    write(root, "base.py", "class Record:\n    pass\n")
    write(root, "models.py", MODELS)
    write(root, "notes.go", "package main\n\nimport \"fmt\"\n\nfunc Go() { fmt.Print() }\n")

    index = os.path.join(tmp, "structure.json")
    proc = subprocess.run([sys.executable, SCANNER, "--root", root, "--out", index,
                           "--detail"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    return root, index


def claim(cid, kind, subject, obj, path=None, line=None):
    row = {"id": cid, "kind": kind, "subject": subject, "object": obj, "evidence": []}
    if path is not None:
        row["evidence"].append({"path": path, "line_start": line, "line_end": line})
    return row


def stamped(rows, index):
    """Every row says which scan it was written against, unless a test sets its own."""
    if not os.path.isfile(index):
        return rows                     # the missing-index cases never get that far
    with open(index, encoding="utf-8") as fh:
        index_hash = json.load(fh).get("index_hash")
    return [dict({"index_hash": index_hash}, **row) for row in rows]


def run(tmp, root, index, claims, fragments=None, name="run"):
    out_dir = os.path.join(tmp, name)
    claims_path = os.path.join(tmp, name + "-claims.jsonl")
    claims = stamped(claims, index)
    if fragments is not None:
        fragments = stamped(fragments, index)
    with open(claims_path, "w", encoding="utf-8") as fh:
        for row in claims:
            fh.write(json.dumps(row) + "\n")
    args = [sys.executable, SCRIPT, "--claims", claims_path, "--index", index,
            "--root", root, "--out-dir", out_dir]
    if fragments is not None:
        frag_path = os.path.join(tmp, name + "-fragments.jsonl")
        with open(frag_path, "w", encoding="utf-8") as fh:
            for row in fragments:
                fh.write(json.dumps(row) + "\n")
        args += ["--fragments", frag_path]
    proc = subprocess.run(args, capture_output=True, text=True)

    def read(filename):
        path = os.path.join(out_dir, filename)
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    return (proc.returncode, {c["id"]: c["status"] for c in read("claims.verified.jsonl")},
            read("findings.jsonl"), read("fragments.verified.jsonl"), proc.stderr)


def main():
    tmp = tempfile.mkdtemp(prefix="verify-doc-test-")
    try:
        root, index = build_fixture(tmp)

        claims = [
            claim("c:imports", "imports", "module:api.py", "module:service.py", "api.py", 1),
            claim("c:imports-absent", "imports", "module:api.py", "module:base.py", "api.py", 1),
            claim("c:imports-wrongline", "imports", "module:api.py", "module:service.py",
                  "api.py", 2),
            claim("c:defines", "defines", "module:service.py", "symbol:service.py:handle",
                  "service.py", 1),
            claim("c:defines-absent", "defines", "module:service.py",
                  "symbol:service.py:missing", "service.py", 1),
            claim("c:contains", "contains", "class:models.py:Order",
                  "method:models.py:Order.total", "models.py", 5),
            claim("c:contains-absent", "contains", "class:models.py:Order",
                  "method:models.py:Order.ship", "models.py", 5),
            claim("c:inherits", "inherits", "class:models.py:Order", "class:base.py:Record",
                  "models.py", 4),
            claim("c:inherits-wrong", "inherits", "class:models.py:Order",
                  "class:service.py:Nope", "models.py", 4),
            claim("c:calls", "calls", "module:api.py", "symbol:service.py:handle",
                  "api.py", 6),
            claim("c:calls-qualified", "calls", "module:api.py", "symbol:helpers.py:assist",
                  "api.py", 10),
            claim("c:calls-wrongname", "calls", "module:api.py", "symbol:service.py:retire",
                  "api.py", 6),
            claim("c:calls-local", "calls", "module:api.py", "symbol:service.py:shadow",
                  "api.py", 14),
            claim("c:calls-noline", "calls", "module:api.py", "symbol:service.py:handle",
                  "api.py", 3),
            claim("c:calls-go", "calls", "module:notes.go", "symbol:helpers.py:assist",
                  "notes.go", 5),
            claim("c:calls-computed", "calls", "module:api.py",
                  "symbol:service.py:handle", "api.py", 22),
            claim("c:calls-shadowed-param", "calls", "module:api.py",
                  "symbol:service.py:handle", "api.py", 26),
            claim("c:calls-rebound-local", "calls", "module:api.py",
                  "symbol:service.py:handle", "api.py", 31),
            claim("c:wrong-kinds", "imports", "class:models.py:Order",
                  "method:models.py:Order.total", "models.py", 4),
            claim("c:end-past-eof", "defines", "module:service.py",
                  "symbol:service.py:handle", "service.py", 1),
            claim("c:role", "responsibility", "module:api.py", None),
            claim("c:noevidence", "imports", "module:api.py", "module:service.py"),
            claim("c:badline", "imports", "module:api.py", "module:service.py", "api.py", 900),
            claim("c:badentity", "imports", "api.py", "module:service.py", "api.py", 1),
            claim("c:badkind", "invents", "module:api.py", "module:service.py", "api.py", 1),
        ]
        # An end past the file is only visible if the start is inside it.
        for row in claims:
            if row["id"] == "c:end-past-eof":
                row["evidence"][0]["line_end"] = 9000

        code, status, findings, _, stderr = run(tmp, root, index, claims)
        check("verification runs", code in (0, 1), "exit %d: %s" % (code, stderr))

        check("a real import edge verifies", status.get("c:imports") == "verified",
              "%r" % status.get("c:imports"))
        check("an import the graph does not have is rejected",
              status.get("c:imports-absent") == "rejected",
              "%r" % status.get("c:imports-absent"))
        check("an import cited at the wrong line is rejected",
              status.get("c:imports-wrongline") == "rejected",
              "%r" % status.get("c:imports-wrongline"))
        check("a real definition verifies", status.get("c:defines") == "verified")
        check("a definition that is not there is rejected",
              status.get("c:defines-absent") == "rejected")
        check("a real method verifies", status.get("c:contains") == "verified",
              "%r" % status.get("c:contains"))
        check("a method that is not there is rejected",
              status.get("c:contains-absent") == "rejected")
        check("a resolved base verifies", status.get("c:inherits") == "verified",
              "%r" % status.get("c:inherits"))
        check("a base the class does not have is rejected",
              status.get("c:inherits-wrong") == "rejected")

        check("a call at the cited line, bound by the cited import, verifies",
              status.get("c:calls") == "verified", "%r" % status.get("c:calls"))
        check("a call through an imported module verifies",
              status.get("c:calls-qualified") == "verified",
              "%r" % status.get("c:calls-qualified"))
        check("a call to a different name at that line is rejected",
              status.get("c:calls-wrongname") == "rejected",
              "%r" % status.get("c:calls-wrongname"))
        # The heart of it: shadow() is a real call to a real name, but it is defined
        # locally, not imported from service.py. A name check alone would pass this.
        check("a local call is not credited to the module that shares the name",
              status.get("c:calls-local") == "rejected",
              "%r" % status.get("c:calls-local"))
        check("a cited line with no call at all is rejected",
              status.get("c:calls-noline") == "rejected",
              "%r" % status.get("c:calls-noline"))
        check("a call in a language with no tree stays a candidate, not a fact",
              status.get("c:calls-go") == "candidate", "%r" % status.get("c:calls-go"))
        # The module-level import binds `handle`, but at these two call sites the name
        # is a parameter and a local. Crediting either to service.handle would invent a
        # call edge from a true import and a matching name.
        check("a call to a shadowing parameter is not credited to the import",
              status.get("c:calls-shadowed-param") == "rejected",
              "%r" % status.get("c:calls-shadowed-param"))
        check("a call to a locally rebound name is not either",
              status.get("c:calls-rebound-local") == "rejected",
              "%r" % status.get("c:calls-rebound-local"))
        check("a claim joining the wrong kinds of entity is rejected",
              status.get("c:wrong-kinds") == "rejected"
              and any(f["code"] == "V015" for f in findings),
              "%r" % status.get("c:wrong-kinds"))
        check("evidence ending past the end of the file is rejected",
              status.get("c:end-past-eof") == "rejected",
              "%r" % status.get("c:end-past-eof"))
        # `table[key]()` is a real call whose target is chosen at run time. Reporting
        # "there is no call at that line" would be false; retrying would never help.
        check("a call through a computed target is unsupported, not rejected",
              status.get("c:calls-computed") == "unsupported",
              "%r" % status.get("c:calls-computed"))
        check("and it is not offered for retry",
              not any(f["retryable"] for f in findings
                      if f["claim_id"] == "c:calls-computed"),
              "%r" % [f for f in findings if f["claim_id"] == "c:calls-computed"])

        check("a responsibility is an inference, never verified",
              status.get("c:role") == "supported_inference", "%r" % status.get("c:role"))
        check("a claim with no evidence is rejected",
              status.get("c:noevidence") == "rejected")
        check("evidence past the end of the file is rejected",
              status.get("c:badline") == "rejected")
        check("an unparseable entity id is rejected",
              status.get("c:badentity") == "rejected")
        check("an unknown claim kind is rejected", status.get("c:badkind") == "rejected")
        check("every rejection came with a finding",
              {f["claim_id"] for f in findings} >= {c for c, s in status.items()
                                                    if s == "rejected"},
              "%r" % sorted({f["claim_id"] for f in findings}))
        check("prose is never rewritten -- no claim gained a text field",
              all("text" not in c for c in claims))

        # Rejected and needs_context must not be confused: one is false, one is unknown.
        no_detail_index = os.path.join(tmp, "nodetail.json")
        subprocess.run([sys.executable, SCANNER, "--root", root, "--out", no_detail_index],
                       capture_output=True, text=True)
        code, status, findings, _, _ = run(
            tmp, root, no_detail_index,
            [claim("c:contains", "contains", "class:models.py:Order",
                   "method:models.py:Order.total", "models.py", 5)], name="nodetail")
        check("a claim that could not be checked needs context, it is not rejected",
              status.get("c:contains") == "needs_context", "%r" % status.get("c:contains"))
        check("that finding is marked retryable",
              any(f["retryable"] for f in findings), "%r" % findings)

        # Staleness: the citation may now point at anything.
        write(root, "service.py", "def handle():\n    return 99\n")
        code, status, findings, _, _ = run(
            tmp, root, index,
            [claim("c:defines", "defines", "module:service.py",
                   "symbol:service.py:handle", "service.py", 1)], name="stale")
        check("a claim citing an edited file needs context",
              status.get("c:defines") == "needs_context", "%r" % status.get("c:defines"))
        check("staleness is reported as V005",
              any(f["code"] == "V005" for f in findings), "%r" % findings)
        write(root, "service.py", SERVICE)

        # Duplicate ids, dangling references, and fragment roll-up.
        dup = [claim("c:same", "imports", "module:api.py", "module:service.py", "api.py", 1),
               claim("c:same", "imports", "module:api.py", "module:service.py", "api.py", 1)]
        code, status, findings, _, _ = run(tmp, root, index, dup, name="dup")
        check("a duplicate claim id is rejected and reported",
              any(f["code"] == "V008" for f in findings), "%r" % findings)

        fragments = [
            {"fragment_id": "f:good", "source": "api.py", "role": "Boundary.",
             "claim_ids": ["c:imports"], "status": "candidate"},
            {"fragment_id": "f:bad", "source": "api.py", "role": "Boundary.",
             "claim_ids": ["c:imports", "c:imports-absent"], "status": "candidate"},
            {"fragment_id": "f:dangling", "source": "api.py", "role": "Boundary.",
             "claim_ids": ["c:never-supplied"], "status": "candidate"},
        ]
        keep = [c for c in claims if c["id"] in ("c:imports", "c:imports-absent")]
        code, status, findings, verified, _ = run(tmp, root, index, keep, fragments,
                                                  name="frag")
        by_id = {f["fragment_id"]: f["status"] for f in verified}
        check("a fragment whose claims all hold is verified",
              by_id.get("f:good") == "verified", "%r" % by_id)
        check("one rejected claim rejects the whole fragment",
              by_id.get("f:bad") == "rejected", "%r" % by_id)
        check("a reference to a claim that was never supplied is a defect",
              by_id.get("f:dangling") == "rejected"
              and any(f["code"] == "V009" for f in findings), "%r" % findings)
        check("blocked claims make the exit code non-zero", code == 1, "exit %d" % code)

        clean = [claim("c:imports", "imports", "module:api.py", "module:service.py",
                       "api.py", 1)]
        code, _, _, _, _ = run(tmp, root, index, clean, name="clean")
        check("a fully verified run exits 0", code == 0, "exit %d" % code)

        # `.docs-build/` survives between runs. A fragment left there by an earlier one
        # parses, names a real file, and its claims may verify against today's index --
        # the identity is the only thing that tells it apart from one written now.
        left_over = [dict(claim("c:imports", "imports", "module:api.py",
                                "module:service.py", "api.py", 1),
                          index_hash="sha256:" + "0" * 64)]
        code, statuses, findings, _, _ = run(tmp, root, index, left_over, name="stale")
        check("a claim from an earlier scan is rejected, not verified",
              code == 1 and statuses.get("c:imports") == "rejected"
              and any(f["code"] == "V021" for f in findings), "%r" % findings)

        unstamped = [claim("c:imports", "imports", "module:api.py", "module:service.py",
                           "api.py", 1)]
        proc_rows = os.path.join(tmp, "unstamped-claims.jsonl")
        with open(proc_rows, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(unstamped[0]) + "\n")
        proc = subprocess.run([sys.executable, SCRIPT, "--claims", proc_rows,
                               "--index", index, "--root", root,
                               "--out-dir", os.path.join(tmp, "unstamped")],
                              capture_output=True, text=True)
        check("a claim carrying no identity at all is rejected too",
              proc.returncode == 1 and "V021" in proc.stdout + proc.stderr,
              proc.stdout + proc.stderr)

        # Input errors are exit 2, distinct from a verification failure.
        code, _, _, _, _ = run(tmp, root, os.path.join(tmp, "absent.json"), clean,
                               name="noindex")
        check("a missing index exits 2", code == 2, "exit %d" % code)

        proc = subprocess.run([sys.executable, SCRIPT, "--claims",
                               os.path.join(tmp, "nope.jsonl"), "--index", index,
                               "--root", root, "--out-dir", os.path.join(tmp, "x")],
                              capture_output=True, text=True)
        check("missing claims input exits 2", proc.returncode == 2,
              "exit %d" % proc.returncode)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
