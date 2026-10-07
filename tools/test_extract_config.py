#!/usr/bin/env python3
"""The settings extractor finds what it claims to, and the validator catches a bad row."""
import json
import os
import subprocess
import sys
import tempfile

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import extract_config

failures = []


def check(label, ok, detail=""):
    print("%s   %s" % ("ok " if ok else "FAIL", label))
    if not ok:
        failures.append("%s: %s" % (label, detail))


SOURCE = '''\
import os
import argparse

PORT = int(os.environ.get("SERVICE_PORT", 8080))
TOKEN = os.environ["API_TOKEN"]
DEBUG = os.getenv("DEBUG", "0")
LATE = os.getenv("LATE", compute())


def cli():
    p = argparse.ArgumentParser()
    p.add_argument("-w", "--workers", default=4)
    p.add_argument("--config", required=True)
    return p
'''


def index_for(root, paths):
    return {"schema_version": 3, "index_hash": "sha256:test",
            "files": [{"path": p, "lang": "python", "is_test": False} for p in paths]}


tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as handle:
    handle.write(SOURCE)
rows = extract_config.extract(index_for(tmp, ["app.py"]), tmp)
by_name = {r["name"]: r for r in rows}

check("os.environ[...] is found", "API_TOKEN" in by_name, sorted(by_name))
check("os.environ.get(...) is found", "SERVICE_PORT" in by_name, sorted(by_name))
check("os.getenv(...) is found", "DEBUG" in by_name, sorted(by_name))
check("an argparse option is found", "--workers" in by_name, sorted(by_name))

check("a literal default is recorded", by_name.get("SERVICE_PORT", {}).get("default") == 8080,
      by_name.get("SERVICE_PORT"))
check("required is recorded", by_name.get("--config", {}).get("required") is True,
      by_name.get("--config"))

# A default the repository computes at run time is not a value, and writing the
# expression down would put something in the manual that is not one.
check("a non-literal default is left off", "default" not in by_name.get("LATE", {}),
      by_name.get("LATE"))
# `--help` names an option by its long flag, and so does the manual.
check("the long flag names the option", "-w" not in by_name, sorted(by_name))
check("every row carries a status the rest of the run understands",
      all(r.get("status") == "observed" for r in rows), rows[:1])
check("every row cites a line", all(r.get("evidence") for r in rows), rows[:1])

# One setting read in two files is one setting with two citations, not two settings:
# otherwise the count measures how often the code calls getenv.
second = os.path.join(tmp, "other.py")
with open(second, "w", encoding="utf-8") as handle:
    handle.write('import os\nTOKEN = os.environ["API_TOKEN"]\n')
merged = {r["name"]: r for r in
          extract_config.extract(index_for(tmp, ["app.py", "other.py"]), tmp)}
check("a setting read twice is one row with two citations",
      len(merged["API_TOKEN"]["evidence"]) == 2, merged["API_TOKEN"])

# Two call sites defaulting one setting differently is a fact about the code. Picking
# one silently would put a value in the manual that is right half the time.
with open(second, "w", encoding="utf-8") as handle:
    handle.write('import os\nP = os.getenv("SERVICE_PORT", 9090)\n')
clashed = {r["name"]: r for r in
           extract_config.extract(index_for(tmp, ["app.py", "other.py"]), tmp)}
check("disagreeing defaults are recorded, not resolved",
      clashed["SERVICE_PORT"].get("conflicting_defaults") == [9090],
      clashed["SERVICE_PORT"])

# The validator: C006 is the rule that lets a configuration answer be `confirmed`.
os.remove(second)
index = index_for(tmp, ["app.py"])
index_path = os.path.join(tmp, "index.json")
with open(index_path, "w", encoding="utf-8") as handle:
    json.dump(index, handle)
good = {"config_version": 1, "index_hash": "sha256:test",
        "settings": extract_config.extract(index, tmp)}


def validate(content):
    path = os.path.join(tmp, "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(content, handle)
    proc = subprocess.run([sys.executable, script("validate_config.py"), path,
                           "--index", index_path, "--root", tmp],
                          capture_output=True, text=True)
    try:
        return proc.returncode, [f["code"] for f in json.loads(proc.stdout)["findings"]]
    except ValueError:
        return proc.returncode, []


code, found = validate(good)
check("a freshly extracted analysis validates", code == 0 and not found, found)

import copy
bad = copy.deepcopy(good)
bad["settings"][0]["name"] = "NOT_IN_THE_SOURCE"
code, found = validate(bad)
check("C006: a name that is not in the lines it cites is refused",
      code == 1 and "C006" in found, found)

stale = copy.deepcopy(good)
stale["index_hash"] = "sha256:another-scan"
code, found = validate(stale)
check("an analysis from another scan is an input error, not a finding", code == 2, code)

if failures:
    for line in failures:
        print("   " + line)
    sys.exit(1)
print("\nall extract_config checks passed")
