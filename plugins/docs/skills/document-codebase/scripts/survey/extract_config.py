#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/survey/extract_config.py
# Regenerate: python3 tools/materialize.py
"""Every setting this repository reads, with the line that reads it.

    python3 extract_config.py --index structure.json --root . --out config.json

**This is the artefact a module packet cannot be.** A packet answers "what is this
module for" by handing over one file and its neighbours, which is the right shape for a
question about a module. "What configuration values does this project take?" is not a
question about a module: the answer is spread across every file that reads one, and no
amount of per-module context assembles it. Without this, the only way to answer the
configuration questions in the manual template is to read the whole tree and hope.

What it finds, in Python source the index already lists:

    os.environ["NAME"]         os.environ.get("NAME", default)
    os.getenv("NAME", default) parser.add_argument("--name", default=..., required=...)

**It lists settings; it does not know what they mean.** The name, where it is read, and
a literal default if there is one -- that is the whole claim. What a setting *does*, what
values are legal, what happens when it is absent: none of that is here, because none of
it is mechanically true. Those remain the model's to answer, and this file is what it
answers them *from* rather than instead of.

Standard library only. Reads; writes only the file named by --out.
"""

import argparse
import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import build_dir  # noqa: E402

CONFIG_VERSION = 1

ENV = "env"
OPTION = "option"
KINDS = (ENV, OPTION)


def literal(node):
    """A default worth recording, or None.

    Only literals. `os.getenv("PORT", compute_default())` has a default the repository
    decides at run time, and writing down the expression would put something in the
    document that is not a value.
    """
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, (str, int, float, bool)) else None


def string_of(node):
    value = literal(node)
    return value if isinstance(value, str) else None


def span(node):
    start = getattr(node, "lineno", None)
    return start, getattr(node, "end_lineno", None) or start


class Reader(ast.NodeVisitor):
    """One file's settings. Names are collected with the line that reads them."""

    def __init__(self, path):
        self.path = path
        self.found = []

    def record(self, kind, name, node, default=None, required=None):
        start, end = span(node)
        if not name or start is None:
            return
        # `observed` in the statement vocabulary the rest of the run uses: a parser saw
        # this in the code and the repository gave no reason for it. Never `declared` --
        # that is for what the repository says about itself, and a call site says nothing.
        row = {"kind": kind, "name": name, "status": "observed",
               "evidence": [{"path": self.path, "line_start": start, "line_end": end}]}
        if default is not None:
            row["default"] = default
        if required is not None:
            row["required"] = required
        self.found.append(row)

    def visit_Subscript(self, node):
        # os.environ["NAME"]
        if isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
            self.record(ENV, string_of(node.slice), node)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and node.args:
            # os.environ.get("NAME", default) and os.getenv("NAME", default)
            is_environ_get = (func.attr == "get" and isinstance(func.value, ast.Attribute)
                              and func.value.attr == "environ")
            is_getenv = func.attr == "getenv"
            if is_environ_get or is_getenv:
                self.record(ENV, string_of(node.args[0]), node,
                            default=literal(node.args[1]) if len(node.args) > 1 else None)
            elif func.attr == "add_argument":
                self.add_argument(node)
        elif isinstance(func, ast.Name) and func.id == "getenv" and node.args:
            self.record(ENV, string_of(node.args[0]), node,
                        default=literal(node.args[1]) if len(node.args) > 1 else None)
        self.generic_visit(node)

    def add_argument(self, node):
        """An argparse option. The longest flag names it, as `--help` output does."""
        flags = [s for s in (string_of(a) for a in node.args) if s]
        if not flags:
            return
        long_flags = [f for f in flags if f.startswith("--")] or flags
        keywords = {k.arg: k.value for k in node.keywords if k.arg}
        self.record(OPTION, max(long_flags, key=len), node,
                    default=literal(keywords["default"]) if "default" in keywords else None,
                    required=literal(keywords.get("required")) if "required" in keywords
                    else None)


def settings_in(root, path):
    full = os.path.join(root, path)
    try:
        with open(full, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        # A file the scanner already flagged as unparsed. Nothing to add, and the
        # scanner's own diagnostic is where that belongs.
        return []
    reader = Reader(path)
    reader.visit(tree)
    return reader.found


def merge(rows):
    """One row per (kind, name), carrying every line that reads it.

    A setting read in four places is one setting. Four rows would make the count a
    measure of how often the code calls `getenv` rather than of what the project takes.
    """
    merged = {}
    for row in rows:
        key = (row["kind"], row["name"])
        if key not in merged:
            row = dict(row)
            row["id"] = "config:%s:%s" % (row["kind"], row["name"])
            merged[key] = row
            continue
        into = merged[key]
        for item in row["evidence"]:
            if item not in into["evidence"]:
                into["evidence"].append(item)
        # The first default wins and disagreement is recorded rather than resolved:
        # two call sites defaulting a setting differently is a fact about the code, and
        # picking one silently would put a value in the manual that is right half the time.
        if "default" in row and "default" in into and row["default"] != into["default"]:
            into.setdefault("conflicting_defaults", []).append(row["default"])
        elif "default" in row and "default" not in into:
            into["default"] = row["default"]
        if row.get("required") and not into.get("required"):
            into["required"] = True
    return sorted(merged.values(), key=lambda r: (r["kind"], r["name"]))


def extract(index, root):
    rows = []
    for record in index.get("files", ()):
        if record.get("lang") != "python" or record.get("is_test"):
            continue
        rows.extend(settings_in(root, record["path"]))
    return merge(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--out", required=True, help="where to write config-analysis.json")
    args = parser.parse_args()

    try:
        with open(args.index, encoding="utf-8") as handle:
            index = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("FAIL  cannot read %s: %s\n" % (args.index, exc))
        return 2
    if index.get("schema_version") not in (2, 3):
        sys.stderr.write("FAIL  unsupported index schema_version %r\n"
                         % index.get("schema_version"))
        return 2

    settings = extract(index, args.root)
    out = {"config_version": CONFIG_VERSION, "index_hash": index.get("index_hash"),
           "settings": settings}
    build_dir.ensure_parent(args.out)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    by_kind = {}
    for row in settings:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
    print("wrote %s: %d setting(s)%s" % (
        args.out, len(settings),
        (" -- " + ", ".join("%d %s" % (n, k) for k, n in sorted(by_kind.items())))
        if settings else " -- this repository reads none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
