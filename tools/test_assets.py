#!/usr/bin/env python3
"""Behavioural tests for the asset inventory in structure.json v3.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Assets are availability, not content: a path, a kind, a hash. So there is very little to
get wrong, and exactly three ways to get it badly wrong. Filing a file under the wrong
question sends a run looking in the wrong place. Letting the scan index its own output
makes `index_hash` change on a tree that did not, which quietly invalidates every
fragment from the previous run. And a stale asset is worse than a stale source record,
because a run cites an asset precisely where it cannot derive the answer, so nothing
downstream would catch the citation being wrong.

    python3 tools/test_assets.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
FIXTURE = os.path.join(REPO, "tests", "contracts", "layered-repo")

sys.path.insert(0, SCRIPTS)
import scan_repo                                              # noqa: E402
import validate_index                                         # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def write(root, rel, body="x\n"):
    path = os.path.join(root, rel)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def scan(root, out):
    code, output = run("scan_repo.py", "--root", root, "--out", out, "--detail")
    if code != 0:
        return code, {}, output
    with open(out, encoding="utf-8") as fh:
        return code, json.load(fh), output


def kinds_of(index):
    return {a["path"]: a["kind"] for a in index.get("assets", ())}


def main():
    tmp = tempfile.mkdtemp(prefix="assets-test-")
    try:
        # --- Classification. A table of conventions, so the test is a table too.
        expected = {
            "README.md": "readme",
            "LICENSE": "licence",
            "CHANGELOG.md": "changelog",
            "CONTRIBUTING.md": "contributing",
            "AGENTS.md": "contributing",
            "pyproject.toml": "packaging",
            "package.json": "packaging",
            "go.mod": "packaging",
            "Makefile": "packaging",
            "poetry.lock": "packaging",
            "Dockerfile": "container",
            "docker-compose.yml": "container",
            ".github/workflows/ci.yml": "ci",
            "Jenkinsfile": "ci",
            "docs/adr/0001-why-layers.md": "adr",
            "docs/usage.md": "documentation",
            "examples/basic.yaml": "example",
            "config/settings.yaml": "configuration",
            ".gitignore": "configuration",
            "data/seed.csv": "data",
        }
        root = os.path.join(tmp, "conventions")
        os.makedirs(root)
        write(root, "src/app.py", "def main():\n    return 1\n")
        for rel in expected:
            write(root, rel)
        # Files nothing could quote, which must not dilute the list.
        write(root, "docs/logo.png", "\x89PNG")
        write(root, "assets/font.woff2", "x")
        code, index, output = scan(root, os.path.join(tmp, "conventions.json"))
        check("the scan succeeds", code == 0, output)
        found = kinds_of(index)
        wrong = {p: (found.get(p), k) for p, k in expected.items() if found.get(p) != k}
        check("every convention lands under the question it answers", not wrong,
              repr(wrong))
        check("binaries are left out, not filed under `other`",
              "docs/logo.png" not in found and "assets/font.woff2" not in found,
              repr(sorted(found)))

        # Location beats basename where location is the better signal: an ADR is not
        # just another documentation file, and a workflow is not just another YAML.
        check("an ADR is an adr, not documentation", found.get(
            "docs/adr/0001-why-layers.md") == "adr")
        check("a workflow is ci, not configuration",
              found.get(".github/workflows/ci.yml") == "ci")

        # --- Availability only. Nothing is parsed, nothing is read into the index.
        row = [a for a in index["assets"] if a["path"] == "README.md"][0]
        check("an asset row carries a path, a kind, a hash and a size, and nothing else",
              set(row) == {"path", "kind", "source_hash", "bytes"}, repr(sorted(row)))
        check("the hash is of the bytes on disk",
              row["source_hash"] == scan_repo.file_hash(os.path.join(root, "README.md")))

        # --- One file, one home.
        paths = {r["path"] for r in index["files"]}
        check("no path is both a source file and an asset",
              not (paths & set(found)), repr(paths & set(found)))

        # --- The defect that only shows up on the second run.
        inside = os.path.join(root, ".docs-build", "structure.json")
        os.makedirs(os.path.dirname(inside), exist_ok=True)
        _, first, _ = scan(root, inside)
        _, second, _ = scan(root, inside)
        _, third, _ = scan(root, inside)
        check("a scan does not index its own output",
              first["index_hash"] == second["index_hash"] == third["index_hash"],
              "%s / %s / %s" % (first["index_hash"][:20], second["index_hash"][:20],
                                third["index_hash"][:20]))
        check("and its working directory is nowhere in the assets",
              not any(a["path"].startswith(".docs-build/") for a in second["assets"]),
              repr([a["path"] for a in second["assets"]
                    if a["path"].startswith(".docs-build/")]))

        # Writing the index to the repository root is still allowed; only that one file
        # is excluded, not the repository it names.
        at_root = os.path.join(root, "structure.json")
        _, one, _ = scan(root, at_root)
        _, two, _ = scan(root, at_root)
        check("an index written at the root excludes itself and nothing else",
              one["index_hash"] == two["index_hash"] and len(one["assets"]) > 10,
              "%d asset(s)" % len(one["assets"]))

        # --- Coverage, and the digest line that makes it visible without opening JSON.
        code, output = run("scan_repo.py", "--root", root, "--out",
                           os.path.join(tmp, "digest.json"), "--summary")
        check("the digest says how many assets are available to cite",
              "assets (not parsed, available to cite):" in output, output)
        check("coverage counts them by kind",
              index["coverage"]["assets"]["count"] == len(index["assets"])
              and index["coverage"]["assets"]["by_kind"]["readme"] == 1,
              repr(index["coverage"].get("assets")))

        # --- Absence is an answer too.
        bare = os.path.join(tmp, "bare")
        os.makedirs(bare)
        write(bare, "only.py", "x = 1\n")
        _, bare_index, _ = scan(bare, os.path.join(tmp, "bare.json"))
        check("a repository with nothing to cite says so with an empty list",
              bare_index["assets"] == [] and bare_index["coverage"]["assets"]["count"] == 0,
              repr(bare_index.get("assets")))

        # --- The validator asks assets the same questions it asks source files.
        target = os.path.join(tmp, "validated")
        shutil.copytree(FIXTURE, target)
        index_path = os.path.join(tmp, "validated.json")
        code, valid, _ = scan(target, index_path)
        code, output = run("validate_index.py", index_path, "--root", target)
        check("a fresh index validates", code == 0, output)
        check("the fixture's own evidence is in it",
              {"README.md", "pyproject.toml", ".github/workflows/ci.yml"}
              <= set(kinds_of(valid)), repr(sorted(kinds_of(valid))))

        with open(os.path.join(target, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("\nedited after the scan\n")
        code, output = run("validate_index.py", index_path, "--root", target)
        check("an asset edited after the scan is caught as stale",
              code == 1 and "E007" in output, output)

        os.remove(os.path.join(target, "README.md"))
        code, output = run("validate_index.py", index_path, "--root", target)
        check("an asset deleted after the scan is caught as absent",
              code == 1 and "E008" in output, output)

        # Malformed rows, which the scanner cannot produce but a hand-edited or
        # third-party index can.
        for broken, why in (
            ({"path": "../outside.md", "kind": "readme", "source_hash": "sha256:x"},
             "a path escaping the repository"),
            ({"path": "README.md", "kind": "vibes", "source_hash": "sha256:x"},
             "an unknown kind"),
        ):
            findings = validate_index.Findings()
            validate_index.check_assets({"assets": [broken]}, target, {}, findings)
            check("%s is E011" % why,
                  any(f["code"] == "E011" for f in findings.rows), repr(findings.rows))

        findings = validate_index.Findings()
        validate_index.check_assets(
            {"assets": [{"path": "src/app.py", "kind": "documentation",
                         "source_hash": "sha256:x"}]},
            target, {"src/app.py": {}}, findings)
        check("a path claimed as both source and asset is E011",
              any(f["code"] == "E011" for f in findings.rows), repr(findings.rows))

        check("the validator and the scanner agree on the kinds",
              set(validate_index.ASSET_KINDS) == set(scan_repo.ASSET_KINDS),
              "%r vs %r" % (sorted(validate_index.ASSET_KINDS),
                            sorted(scan_repo.ASSET_KINDS)))

        # --- v3 must still load everywhere v2 did.
        for script, args in (
            ("query_graph.py", ["--index", index_path, "--clusters"]),
            ("build_class_graph.py", ["--index", index_path, "--out",
                                      os.path.join(tmp, "graph.json")]),
        ):
            code, output = run(script, *args)
            check("%s accepts a v3 index" % script, code == 0, output)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
