#!/usr/bin/env python3
"""Behavioural tests for annotate_import_usage.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

The load-bearing test here is not that Ruff is read correctly; it is that reading Ruff
changes nothing else. An annotation that quietly dropped an edge would turn "this name
is never read" into "this dependency does not exist", which is a different and false
claim. `strip_usage` below reverses every field this script is allowed to touch, and the
result must equal the index it started from.

    python3 tools/test_annotate_import_usage.py
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(REPO, "shared", "scripts", "scan_repo.py")
SCRIPT = os.path.join(REPO, "shared", "scripts", "annotate_import_usage.py")

HAVE_RUFF = shutil.which("ruff") is not None

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


def run(index, root, *args, **kwargs):
    env = dict(os.environ)
    if kwargs.get("no_ruff"):
        env["PATH"] = os.path.join(root, "empty-bin")
        os.makedirs(env["PATH"], exist_ok=True)
    proc = subprocess.run([sys.executable, SCRIPT, index, "--root", root] + list(args),
                          capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def strip_usage(index):
    """Undo everything this script is permitted to write."""
    clean = copy.deepcopy(index)
    for record in clean.get("files", []):
        for entry in record.get("imports", []):
            entry.pop("usage", None)
    clean.get("coverage", {}).pop("import_usage", None)
    clean["diagnostics"] = [d for d in clean.get("diagnostics", [])
                            if d["code"] not in ("D006", "D007")]
    return clean


API = """\
import os
import sys as system
from pkg.service import handle, retire
from pkg import helper  # noqa: F401
from pkg import registry  # noqa

if True:
    from pkg import late


def go():
    return handle() + late.run()
"""

INIT = """\
from pkg.service import handle

__all__ = ["handle"]
"""


def build_fixture(tmp):
    root = os.path.join(tmp, "lib")
    os.makedirs(root)
    write(root, "api.py", API)
    write(root, "pkg/__init__.py", INIT)
    write(root, "pkg/service.py", "def handle():\n    return 1\n\n\ndef retire():\n    return 0\n")
    write(root, "pkg/helper.py", "def helper():\n    return 2\n")
    write(root, "pkg/registry.py", "REGISTERED = True\n")
    write(root, "pkg/late.py", "def run():\n    return 3\n")

    index = os.path.join(tmp, "structure.json")
    proc = subprocess.run([sys.executable, SCANNER, "--root", root, "--out", index],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("fixture scan failed: %s" % proc.stderr)
    return root, index


def file_state(root):
    """Path -> (mtime, size), to prove the tree was not touched.

    Nothing is filtered out. Ruff's default cache directory would land inside the
    repository being documented, and a test that ignored it would have let that
    through as "unchanged".
    """
    state = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            info = os.stat(full)
            state[full] = (info.st_mtime_ns, info.st_size)
    return state


def main():
    tmp = tempfile.mkdtemp(prefix="import-usage-test-")
    try:
        root, index = build_fixture(tmp)
        before_index = load(index)
        before_tree = file_state(root)

        out = os.path.join(tmp, "annotated.json")
        report_path = os.path.join(tmp, "report.json")
        code, stdout, stderr = run(index, root, "--policy", "optional",
                                   "--out", out, "--report", report_path)
        check("annotating succeeds", code == 0, "exit %d: %s" % (code, stderr))
        annotated = load(out)
        report = load(report_path)

        check("the index it was given is left alone", load(index) == before_index)
        check("the target tree is not modified", file_state(root) == before_tree)
        check("the report says so too", report["source_modified"] is False
              and report["mode"] == "report_only")

        # The whole point: annotation is additive and reversible.
        check("removing the usage metadata restores the original index",
              strip_usage(annotated) == before_index,
              "diff in %r" % [k for k in annotated
                              if strip_usage(annotated).get(k) != before_index.get(k)])

        usage, records = {}, {}
        for record in annotated["files"]:
            for entry in record["imports"]:
                for binding, verdict in (entry.get("usage") or {}).items():
                    key = (record["path"], entry["line"], binding)
                    usage[key] = verdict["status"]
                    records[key] = verdict

        check("every verdict carries the full record, not a bare status",
              all(set(v) == {"status", "source", "diagnostic_path", "diagnostic_line",
                             "auto_fix"} for v in records.values()),
              "%r" % list(records.values())[:1])
        check("no verdict ever claims an automatic fix",
              all(v["auto_fix"] is False for v in records.values()))

        if HAVE_RUFF:
            check("an unused plain import is unused_binding",
                  usage.get(("api.py", 1, "os")) == "unused_binding", "got %r" % usage)
            # Ruff reports this one as `sys`, but the name actually bound is `system`.
            check("an unused aliased import is matched to its alias, not its module",
                  usage.get(("api.py", 2, "system")) == "unused_binding", "got %r" % usage)
            check("one line can be part used and part unused",
                  usage.get(("api.py", 3, "handle")) == "used"
                  and usage.get(("api.py", 3, "retire")) == "unused_binding",
                  "got %r" % usage)
            check("a targeted noqa reads as suppressed, not used",
                  usage.get(("api.py", 4, "helper")) == "suppressed", "got %r" % usage)
            check("a bare noqa reads as suppressed too",
                  usage.get(("api.py", 5, "registry")) == "suppressed", "got %r" % usage)
            check("a conditional import that is used reads as used",
                  usage.get(("api.py", 8, "late")) == "used", "got %r" % usage)
            # A verdict has to be traceable back to the diagnostic that produced it.
            check("an unused binding records where the diagnostic was raised",
                  records[("api.py", 1, "os")]["source"] == "ruff:F401"
                  and records[("api.py", 1, "os")]["diagnostic_path"] == "api.py"
                  and records[("api.py", 1, "os")]["diagnostic_line"] == 1,
                  "got %r" % records.get(("api.py", 1, "os")))
            check("a suppressed binding points at the noqa line",
                  records[("api.py", 4, "helper")]["diagnostic_line"] == 4,
                  "got %r" % records.get(("api.py", 4, "helper")))
            check("a used binding has no diagnostic to point at",
                  records[("api.py", 3, "handle")]["diagnostic_path"] is None,
                  "got %r" % records.get(("api.py", 3, "handle")))
            # A re-export is the case this script must not turn into an accusation.
            check("an __all__ re-export is not reported unused",
                  usage.get(("pkg/__init__.py", 1, "handle")) != "unused_binding",
                  "got %r" % usage.get(("pkg/__init__.py", 1, "handle")))
            check("unmatched diagnostics are counted, not dropped",
                  report["unmatched"] == len(report["findings"]))
            check("coverage carries the summary the document cites",
                  annotated["coverage"]["import_usage"]["tool_available"] is True
                  and annotated["coverage"]["import_usage"]["unused_bindings"] > 0,
                  "got %r" % annotated["coverage"].get("import_usage"))
            check("an unused binding raises D006",
                  "D006" in [d["code"] for d in annotated["diagnostics"]],
                  "got %r" % [d["code"] for d in annotated["diagnostics"]])
        else:
            print("skip ruff-dependent checks -- ruff is not on PATH")

        # Policy. `disabled` must not shell out at all; the other two differ only in
        # whether a missing tool is fatal.
        off = os.path.join(tmp, "off.json")
        code, stdout, _ = run(index, root, "--policy", "disabled", "--out", off)
        check("--policy disabled succeeds", code == 0, "exit %d" % code)
        disabled = load(off)
        check("--policy disabled leaves every binding unknown",
              all(verdict["status"] == "unknown"
                  for record in disabled["files"] for entry in record["imports"]
                  for verdict in (entry.get("usage") or {}).values()),
              "got a non-unknown status")
        check("--policy disabled names no tool as the source",
              all(verdict["source"] is None
                  for record in disabled["files"] for entry in record["imports"]
                  for verdict in (entry.get("usage") or {}).values()),
              "a verdict claimed a source when no tool ran")
        check("--policy disabled records that the tool was not available",
              disabled["coverage"]["import_usage"]["tool_available"] is False)
        check("--policy disabled is still reversible",
              strip_usage(disabled) == before_index)

        missing = os.path.join(tmp, "missing.json")
        code, _, stderr = run(index, root, "--policy", "optional", "--out", missing,
                              no_ruff=True)
        check("missing ruff under optional warns and continues",
              code == 0 and "WARN" in stderr, "exit %d: %s" % (code, stderr))
        check("missing ruff under optional still writes an index",
              os.path.isfile(missing) and load(missing)["coverage"]["import_usage"]
              ["tool_available"] is False)

        code, _, stderr = run(index, root, "--policy", "required",
                              "--out", os.path.join(tmp, "req.json"), no_ruff=True)
        check("missing ruff under required exits 2", code == 2, "exit %d: %s" % (code, stderr))

        # An index the script cannot vouch for must be refused, not annotated blindly.
        old = os.path.join(tmp, "v1.json")
        data = copy.deepcopy(before_index)
        data["schema_version"] = 1
        with open(old, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, _, _ = run(old, root, "--policy", "disabled")
        check("an unsupported schema_version exits 2", code == 2, "exit %d" % code)

        code, _, _ = run(os.path.join(tmp, "nope.json"), root, "--policy", "disabled")
        check("a missing index exits 2", code == 2, "exit %d" % code)
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
