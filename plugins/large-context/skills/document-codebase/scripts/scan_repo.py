#!/usr/bin/env python3
"""Extract a repository's structure without an LLM: symbols, imports, dependency graph.

    python3 scripts/scan_repo.py --root . --out structure.json --summary

Python files are parsed with `ast`, so their symbols and imports are exact. Other
languages are scanned with import-line regexes, which is approximate — every record
carries an `exact` flag saying which it is.

Emits JSON on --out and a short ranked digest on --summary. Read the digest; do not
read the JSON into context, query it with code.

Standard library only. Reads the working tree; writes only --out. No network.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
}

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", "site-packages",
}

# Approximate import extraction for non-Python languages.
IMPORT_PATTERNS = [
    re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""),      # js/ts
    re.compile(r"""^\s*import\s+['"]([^'"]+)['"]"""),                 # js/ts side-effect
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),             # cjs
    re.compile(r"""^\s*#include\s*[<"]([^>"]+)[>"]"""),               # c/cpp
    re.compile(r"""^\s*use\s+([A-Za-z_][\w:]*)"""),                   # rust
    re.compile(r"""^\s*import\s+([A-Za-z_][\w.]*)"""),                # java/go
]

SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)")),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),        # go
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)")),                # rust
    ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)")),              # rust
]

TEST_HINTS = ("test_", "_test.", ".test.", ".spec.", "/tests/", "/test/", "/spec/")


def list_files(root):
    """Prefer git's file list -- it already honours .gitignore."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0 and out.stdout.strip():
            return [p for p in out.stdout.splitlines() if p.strip()]
    except (OSError, subprocess.SubprocessError):
        pass

    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, root))
    return found


def scan_python(path, text):
    """Exact symbols and imports via ast. Returns (symbols, imports) or None on syntax error."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    symbols, imports = [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            symbols.append({"name": node.name, "kind": "class", "line": node.lineno})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # relative import
                imports.append("." * node.level + (node.module or ""))
            elif node.module:
                imports.append(node.module)
    return symbols, imports


def scan_generic(text):
    """Approximate symbols and imports by regex."""
    symbols, imports = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 500:
            continue
        for pattern in IMPORT_PATTERNS:
            match = pattern.search(line)
            if match:
                imports.append(match.group(1))
                break
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.match(line)
            if match:
                symbols.append({"name": match.group(1), "kind": kind, "line": lineno})
                break
    return symbols, imports


def module_key(path):
    """Repo-relative path -> dotted module name, for resolving Python imports."""
    stem = os.path.splitext(path)[0].replace(os.sep, ".")
    if stem.endswith(".__init__"):
        stem = stem[: -len(".__init__")]
    return stem


def resolve(imports, by_module, by_stem):
    """Map raw import strings onto repo files. Returns (targets, unresolved_count)."""
    targets, unresolved = set(), 0
    for raw in imports:
        name = raw.lstrip(".")
        if not name:
            unresolved += 1
            continue
        hit = by_module.get(name)
        if hit is None:
            # longest dotted prefix that names a repo module
            parts = name.split(".")
            while len(parts) > 1 and hit is None:
                parts.pop()
                hit = by_module.get(".".join(parts))
        if hit is None:
            hit = by_stem.get(os.path.basename(name).split(".")[0])
        if hit is None:
            unresolved += 1
        else:
            targets.add(hit)
    return targets, unresolved


def build(root):
    records, unresolved_total = [], 0

    for rel_path in list_files(root):
        ext = os.path.splitext(rel_path)[1].lower()
        lang = LANG_BY_EXT.get(ext)
        if not lang:
            continue
        full = os.path.join(root, rel_path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue

        exact = False
        if lang == "python":
            parsed = scan_python(rel_path, text)
            if parsed is not None:
                symbols, imports = parsed
                exact = True
            else:
                symbols, imports = scan_generic(text)
        else:
            symbols, imports = scan_generic(text)

        records.append({
            "path": rel_path.replace(os.sep, "/"),
            "lang": lang,
            "loc": text.count("\n") + 1,
            "exact": exact,
            "is_test": any(h in "/" + rel_path.replace(os.sep, "/") for h in TEST_HINTS),
            "symbols": symbols,
            "imports": sorted(set(imports)),
        })

    by_module = {module_key(r["path"]): r["path"] for r in records}
    by_stem = {}
    for record in records:
        by_stem.setdefault(os.path.splitext(os.path.basename(record["path"]))[0], record["path"])

    edges = []
    for record in records:
        targets, missed = resolve(record["imports"], by_module, by_stem)
        unresolved_total += missed
        for target in sorted(targets):
            if target != record["path"]:
                edges.append([record["path"], target])

    fan_in = Counter(target for _, target in edges)
    fan_out = Counter(source for source, _ in edges)

    return {
        "root": os.path.abspath(root),
        "files": records,
        "edges": edges,
        "fan_in": dict(fan_in),
        "fan_out": dict(fan_out),
        "unresolved_imports": unresolved_total,
        "totals": {
            "files": len(records),
            "loc": sum(r["loc"] for r in records),
            "symbols": sum(len(r["symbols"]) for r in records),
            "languages": dict(Counter(r["lang"] for r in records)),
            "exact_files": sum(1 for r in records if r["exact"]),
        },
    }


def digest(data, top):
    """Compact ranked text for the agent to read. The JSON stays on disk."""
    lines = []
    totals = data["totals"]
    lines.append("files %d  loc %d  symbols %d  edges %d" % (
        totals["files"], totals["loc"], totals["symbols"], len(data["edges"])))
    lines.append("languages: %s" % ", ".join(
        "%s=%d" % kv for kv in sorted(totals["languages"].items(), key=lambda kv: -kv[1])))
    lines.append("exact (ast-parsed): %d of %d files; unresolved imports: %d" % (
        totals["exact_files"], totals["files"], data["unresolved_imports"]))

    by_path = {r["path"]: r for r in data["files"]}
    fan_in = data["fan_in"]

    lines.append("")
    lines.append("most depended upon (fan-in):")
    for path, count in sorted(fan_in.items(), key=lambda kv: -kv[1])[:top]:
        record = by_path.get(path, {})
        lines.append("  %-4d %-60s %d loc" % (count, path, record.get("loc", 0)))

    roots = [r["path"] for r in data["files"]
             if not fan_in.get(r["path"]) and not r["is_test"]]
    lines.append("")
    lines.append("nothing imports these (entry points or dead code): %d" % len(roots))
    for path in sorted(roots, key=lambda p: -by_path[p]["loc"])[:top]:
        lines.append("  %-60s %d loc" % (path, by_path[path]["loc"]))

    orphans = [r["path"] for r in data["files"]
               if not r["imports"] and not fan_in.get(r["path"]) and not r["is_test"]]
    if orphans:
        lines.append("")
        lines.append("isolated (no imports in or out): %d -- %s" % (
            len(orphans), ", ".join(sorted(orphans)[:10])))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root to scan")
    parser.add_argument("--out", default="structure.json", help="where to write the JSON")
    parser.add_argument("--summary", action="store_true", help="print the ranked digest")
    parser.add_argument("--top", type=int, default=20, help="rows per digest section")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print("FAIL  --root is not a directory: %s" % args.root)
        return 1

    data = build(args.root)
    if not data["files"]:
        print("FAIL  no source files found under %s" % args.root)
        return 1

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)

    if args.summary:
        print(digest(data, args.top))
        print("")
    print("wrote %s (%d files, %d edges)" % (args.out, len(data["files"]), len(data["edges"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
