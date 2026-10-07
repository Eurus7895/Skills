#!/usr/bin/env python3
"""The intermediate directory ignores itself; the delivered document does not."""
import os
import subprocess
import sys
import tempfile

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import build_dir

failures = []


def check(label, ok, detail=""):
    print("%s   %s" % ("ok " if ok else "FAIL", label))
    if not ok:
        failures.append("%s: %s" % (label, detail))


tmp = tempfile.mkdtemp()
target = os.path.join(tmp, ".docs-build")
marker = os.path.join(target, build_dir.IGNORE_NAME)

check("the first call creates the directory", build_dir.ensure(target) is True)
check("and gives it a .gitignore", os.path.isfile(marker))

with open(marker, encoding="utf-8") as handle:
    body = handle.read()
# `*` and not `*` + `!.gitignore`: the whole directory is disposable, so the marker
# should not reach a commit either.
check("the rule is bare `*`, covering the marker itself",
      any(line.strip() == "*" for line in body.splitlines())
      and "!.gitignore" not in body, body)

check("a second call does not report creating it", build_dir.ensure(target) is False)

# Someone who edited it wanted something the default does not do. Rewriting that on
# every run would be the pipeline arguing with them once per invocation.
with open(marker, "w", encoding="utf-8") as handle:
    handle.write("# mine\n")
build_dir.ensure(target)
with open(marker, encoding="utf-8") as handle:
    check("an edited .gitignore is left alone", handle.read() == "# mine\n")

nested = os.path.join(tmp, "deep", "build", "structure.json")
build_dir.ensure_parent(nested)
check("ensure_parent makes the file's directory",
      os.path.isfile(os.path.join(tmp, "deep", "build", build_dir.IGNORE_NAME)))

# The whole point, end to end: a real repository sees nothing after a run.
repo = tempfile.mkdtemp()
with open(os.path.join(repo, "app.py"), "w", encoding="utf-8") as handle:
    handle.write("import os\nTOKEN = os.environ['API_TOKEN']\n")


def git(*args):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True, text=True)


git("init", "-q", ".")
git("add", "-A")
git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "init")
proc = subprocess.run([sys.executable, script("scan_repo.py"), "--root", repo,
                       "--out", os.path.join(repo, ".docs-build", "structure.json")],
                      capture_output=True, text=True)
check("the scanner wrote its index", proc.returncode == 0, proc.stderr[-200:])
status = git("status", "--porcelain").stdout
check("git sees nothing after a run", status.strip() == "", status)

# And the delivered document is not swept up with it: `docs/` is meant to be committed.
source = open(os.path.join(os.path.dirname(script("render_docs.py")), "render_docs.py"),
              encoding="utf-8").read()
check("the renderer does not ignore the output directory", "build_dir" not in source)

if failures:
    for line in failures:
        print("   " + line)
    sys.exit(1)
print("\nall build_dir checks passed")
