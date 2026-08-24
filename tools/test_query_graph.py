#!/usr/bin/env python3
"""Behavioural tests for query_graph.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The cases that matter are the ones where the honest answer is "not this": a base class
that did not resolve, a call that cannot be traced, a file too big to send whole. Each
of those must come back as an absence the caller can see, never as a plausible guess.

    python3 tools/test_query_graph.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
SCRIPT = os.path.join(REPO, "shared", "scripts", "query_graph.py")

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


def run(index, root, *args):
    proc = subprocess.run([sys.executable, SCRIPT, "--index", index, "--root", root]
                          + list(args), capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_stdout": proc.stdout, "_stderr": proc.stderr}


BASE = "class Base:\n    def run(self):\n        return 1\n"
MIDDLE = "from base import Base\n\n\nclass Middle(Base):\n    def step(self):\n        return 2\n"
LEAF = "from middle import Middle\nfrom unknown_package import Foreign\n\n\n" \
       "class Leaf(Middle):\n    pass\n\n\nclass Adopted(Foreign):\n    pass\n"
APP = """\
import helpers
from middle import Middle


def go():
    thing = Middle()
    return helpers.assist() + thing.step()


def indirect(fn):
    return fn()
"""


def build_fixture(tmp):
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "base.py", BASE)
    write(root, "middle.py", MIDDLE)
    write(root, "leaf.py", LEAF)
    write(root, "helpers.py", "def assist():\n    return 3\n")
    write(root, "app.py", APP)
    write(root, "plain.py", "VALUE = 1\n")
    write(root, "sub/deep.py", "from base import Base\n\n\nclass Deep(Base):\n    pass\n")

    index = os.path.join(tmp, "structure.json")
    proc = subprocess.run([sys.executable, SCANNER, "--root", root, "--out", index,
                           "--detail"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    return root, index


def main():
    tmp = tempfile.mkdtemp(prefix="query-graph-test-")
    try:
        root, index = build_fixture(tmp)

        code, packet = run(index, root, "--packet", "app.py")
        check("a packet builds", code == 0, "%r" % packet)
        check("the packet names its scope and revision",
              packet.get("scope", {}).get("id") == "module:app.py"
              and "source_revision" in packet, "%r" % packet.get("scope"))
        check("the packet carries the scope's own source",
              any(s["path"] == "app.py" for s in packet["source_snippets"]))
        check("neighbours arrive as interfaces, not bodies",
              all(s["path"] == "app.py" for s in packet["source_snippets"])
              and any(n["path"] == "helpers.py" for n in packet["neighbour_interfaces"]),
              "%r" % [s["path"] for s in packet["source_snippets"]])
        check("the manifest lists what was left out",
              any("helpers.py body" in o for o in packet["context_manifest"]["omitted"]),
              "%r" % packet["context_manifest"]["omitted"])
        check("the token count is labelled an estimate",
              packet["context_manifest"]["token_estimate_is_an_estimate"] is True)
        check("import edges arrive already citable",
              all(":" in e["cite"] for e in packet["imports"]), "%r" % packet["imports"])

        code, packet = run(index, root, "--packet", "sub/deep.py")
        check("a cross-directory import is called out",
              any(e["path"] == "base.py" for e in packet["cross_directory_edges"]),
              "%r" % packet["cross_directory_edges"])

        code, packet = run(index, root, "--packet", "plain.py")
        check("a file with no classes has no class section", packet["classes"] == [],
              "%r" % packet["classes"])
        check("a file nothing imports still builds a packet", code == 0)

        # Inheritance: three levels resolve, an unresolvable base stops.
        code, chain = run(index, root, "--inheritance", "leaf.py")
        by_name = {c["name"]: c for c in chain["classes"]}
        check("a base in another file resolves",
              by_name["Leaf"]["bases"][0]["resolved"] == "middle.py",
              "%r" % by_name["Leaf"]["bases"])
        code, middle = run(index, root, "--inheritance", "middle.py")
        check("the next level up resolves too",
              middle["classes"][0]["bases"][0]["resolved"] == "base.py",
              "%r" % middle["classes"])
        check("a base from outside the repository stays unresolved rather than guessed",
              by_name["Adopted"]["bases"][0]["resolved"] is None
              and by_name["Adopted"]["bases"][0]["name"] == "Foreign",
              "%r" % by_name["Adopted"]["bases"])

        # Call candidates are evidence, never a verdict.
        code, candidates = run(index, root, "--call-candidates", "app.py",
                               "--to", "helpers.py")
        check("a call candidate is never verified here", candidates["verified"] is False)
        check("a call candidate carries its import evidence",
              candidates["import_evidence"] and candidates["bindings"] == ["helpers"],
              "%r" % candidates)
        code, none_ = run(index, root, "--call-candidates", "app.py", "--to", "base.py")
        check("no import means no candidate evidence, not an invented one",
              none_["import_evidence"] == [] and none_["verified"] is False)

        code, _ = run(index, root, "--call-candidates", "app.py")
        check("--call-candidates without --to exits 2", code == 2, "exit %d" % code)

        code, groups = run(index, root, "--clusters")
        check("clusters group by directory",
              {c["directory"] for c in groups["clusters"]} == {".", "sub"},
              "%r" % groups)

        # Oversize: partition, never truncate.
        big_root = os.path.join(tmp, "big")
        os.makedirs(big_root)
        body = "".join("def f%d():\n    return %d  # %s\n\n\n" % (i, i, "x" * 200)
                       for i in range(400))
        write(big_root, "huge.py", body)
        big_index = os.path.join(tmp, "big.json")
        subprocess.run([sys.executable, SCANNER, "--root", big_root, "--out", big_index],
                       capture_output=True, text=True)
        code, packet = run(big_index, big_root, "--packet", "huge.py",
                           "--hard-limit", "2000")
        check("an oversized scope is partitioned", packet.get("partitioned") is True,
              "%r" % packet.get("partitioned"))
        check("no source is sent with the partition list",
              packet["source_snippets"] == [], "%r" % len(packet["source_snippets"]))
        check("the parts cover the whole file with no gap",
              packet["parts"][0]["line_start"] == 1
              and all(b["line_start"] == a["line_end"] + 1
                      for a, b in zip(packet["parts"], packet["parts"][1:])),
              "%r" % [(p["line_start"], p["line_end"]) for p in packet["parts"][:4]])
        first = packet["parts"][0]["id"]
        code, part = run(big_index, big_root, "--packet", "huge.py", "--part", first,
                         "--hard-limit", "2000")
        check("a part comes back with its own source",
              code == 0 and part["source_snippets"][0]["line_start"] == 1)
        check("a part says which other parts it is missing",
              len(part["context_manifest"]["omitted"]) >= len(packet["parts"]) - 1,
              "%r" % part["context_manifest"]["omitted"])
        code, _ = run(big_index, big_root, "--packet", "huge.py", "--part", "huge.py#L1-L2",
                      "--hard-limit", "2000")
        check("an unknown part id exits 2", code == 2, "exit %d" % code)

        # Paths and inputs.
        # context-policy.md tells the caller to pass findings.jsonl here, and
        # verify_doc.py writes one object per line. json.load would choke on line two.
        findings = os.path.join(tmp, "findings.jsonl")
        with open(findings, "w", encoding="utf-8") as fh:
            fh.write('{"claim_id": "c:1", "code": "V011", "message": "first"}\n')
            fh.write('{"claim_id": "c:2", "code": "V011", "message": "second"}\n')
        code, packet = run(index, root, "--packet", "app.py", "--findings", findings)
        check("a JSONL findings file is read as a list of findings",
              code == 0 and [f["claim_id"] for f in packet["previous_findings"]]
              == ["c:1", "c:2"], "%r" % packet.get("previous_findings"))

        # A single definition larger than the ceiling cannot be split further, so
        # handing it back would return more than the ceiling promises.
        huge_root = os.path.join(tmp, "one-big")
        os.makedirs(huge_root)
        write(huge_root, "one.py",
              "def small():\n    return 0\n\n\ndef enormous():\n"
              + "".join("    x%d = %d  # %s\n" % (i, i, "y" * 200) for i in range(200)))
        huge_index = os.path.join(tmp, "one-big.json")
        subprocess.run([sys.executable, SCANNER, "--root", huge_root, "--out", huge_index],
                       capture_output=True, text=True)
        code, packet = run(huge_index, huge_root, "--packet", "one.py",
                           "--hard-limit", "1000")
        oversized = [p for p in packet.get("parts", ()) if p.get("over_hard_limit")]
        check("a part that is over the ceiling is marked as such",
              code == 0 and oversized, "%r" % packet.get("parts"))
        if oversized:
            code, _ = run(huge_index, huge_root, "--packet", "one.py",
                          "--part", oversized[0]["id"], "--hard-limit", "1000")
            check("and fetching it is refused rather than truncated", code == 2,
                  "exit %d" % code)

        code, _ = run(index, root, "--packet", "../outside.py")
        check("a traversing path exits 2", code == 2, "exit %d" % code)
        code, _ = run(index, root, "--packet", "nosuch.py")
        check("a path not in the index exits 2", code == 2, "exit %d" % code)
        code, _ = run(os.path.join(tmp, "absent.json"), root, "--clusters")
        check("a missing index exits 2", code == 2, "exit %d" % code)

        stale = os.path.join(tmp, "v1.json")
        with open(index, encoding="utf-8") as fh:
            data = json.load(fh)
        data["schema_version"] = 1
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, _ = run(stale, root, "--clusters")
        check("an unsupported schema_version exits 2", code == 2, "exit %d" % code)

        code, _ = run(index, root)
        check("no query at all exits 2", code == 2, "exit %d" % code)

        # A symlink out of the tree must not become a source snippet.
        link_root = os.path.join(tmp, "linked")
        shutil.copytree(root, link_root)
        secret = os.path.join(tmp, "secret.py")
        write(tmp, "secret.py", "TOKEN = 'nope'\n")
        os.symlink(secret, os.path.join(link_root, "escape.py"))
        link_index = os.path.join(tmp, "linked.json")
        subprocess.run([sys.executable, SCANNER, "--root", link_root, "--out", link_index],
                       capture_output=True, text=True)
        code, _ = run(link_index, link_root, "--packet", "escape.py")
        check("a symlink leaving the root is refused", code == 2, "exit %d" % code)
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
