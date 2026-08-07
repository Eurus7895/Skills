#!/usr/bin/env python3
"""Extract a repository's structure without an LLM: symbols, imports, dependency graph.

    python3 scripts/scan_repo.py --root . --out structure.json --summary

Python files are parsed with `ast`, so their symbols and imports are exact. Other
languages are scanned with import-line regexes, which is approximate — every record
carries an `exact` flag saying which it is.

Every import carries the line it appears on, and every edge carries the line of the
import that created it, so a dependency claim can be cited as `path:line`.

Edges record imports, not calls. An import edge proves that A references B; it does
not prove that A invokes anything in B. There is no call graph here.

Emits JSON on --out and a short ranked digest on --summary. Read the digest; do not
read the JSON into context, query it with code.

Standard library only. Reads the working tree under --root and writes only --out.
Symlinks pointing outside --root are skipped, not followed. No network.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter

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
    re.compile(r"""^\s*import\s+([A-Za-z_][\w.]*)"""),                # java, single-line go
]

SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)")),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),        # go
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)")),                # rust
    ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)")),              # rust
]

# gofmt groups imports in a parenthesised block whose entries carry no keyword.
GO_BLOCK_OPEN = re.compile(r"^\s*import\s*\(\s*$")
GO_BLOCK_CLOSE = re.compile(r"^\s*\)\s*$")
GO_BLOCK_ENTRY = re.compile(r"""^\s*(?:[A-Za-z_.]\w*\s+)?['"]([^'"]+)['"]\s*$""")

TEST_DIR_NAMES = {"test", "tests", "spec", "specs", "__tests__", "testing"}
TEST_BASENAME_RE = re.compile(
    r"""(?:^test_)|(?:^test\.)|(?:_test$)|(?:\.test$)|(?:\.spec$)|(?:^conftest$)|(?:Test$)"""
)


def list_files(root):
    """Prefer git's file list -- it honours .gitignore and still sees new files."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0 and out.stdout.strip():
            return sorted({p for p in out.stdout.splitlines() if p.strip()})
    except (OSError, subprocess.SubprocessError):
        pass

    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found)


def within(root_real, candidate):
    """True when candidate resolves to somewhere at or beneath root_real."""
    target = os.path.realpath(candidate)
    return target == root_real or target.startswith(root_real + os.sep)


def is_test_path(rel_path):
    parts = rel_path.replace(os.sep, "/").split("/")
    if any(p.lower() in TEST_DIR_NAMES for p in parts[:-1]):
        return True
    stem = os.path.splitext(parts[-1])[0]
    # Handle doubled suffixes such as foo.test.ts -> stem "foo.test".
    return bool(TEST_BASENAME_RE.search(stem))


def scan_python(text):
    """Exact symbols and imports via ast. Returns (symbols, imports) or None."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    symbols, imports = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            symbols.append({"name": node.name, "kind": "class", "line": node.lineno})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"name": alias.name, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            if node.module:
                imports.append({"name": prefix + node.module, "line": node.lineno})
            else:
                # `from . import helper` -- the module lives in the alias, not in
                # node.module. Recording only the dots would drop the edge entirely.
                for alias in node.names:
                    imports.append({"name": prefix + alias.name, "line": node.lineno})
    return symbols, imports


def scan_generic(text):
    """Approximate symbols and imports by regex, with Go import blocks handled."""
    symbols, imports = [], []
    in_go_block = False

    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 500:
            continue

        if in_go_block:
            if GO_BLOCK_CLOSE.match(line):
                in_go_block = False
                continue
            entry = GO_BLOCK_ENTRY.match(line)
            if entry:
                imports.append({"name": entry.group(1), "line": lineno})
            continue
        if GO_BLOCK_OPEN.match(line):
            in_go_block = True
            continue

        for pattern in IMPORT_PATTERNS:
            match = pattern.search(line)
            if match:
                imports.append({"name": match.group(1), "line": lineno})
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


def resolve_one(raw, by_module, by_stem):
    """Map one import string onto a repo file, or None."""
    name = raw.lstrip(".")
    if not name:
        return None
    hit = by_module.get(name)
    if hit is None:
        parts = name.split(".")
        while len(parts) > 1 and hit is None:
            parts.pop()
            hit = by_module.get(".".join(parts))
    if hit is None:
        hit = by_stem.get(os.path.basename(name).split(".")[0])
    return hit


def build(root):
    root_real = os.path.realpath(root)
    records, skipped_symlinks = [], []

    for rel_path in list_files(root):
        ext = os.path.splitext(rel_path)[1].lower()
        lang = LANG_BY_EXT.get(ext)
        if not lang:
            continue

        full = os.path.join(root, rel_path)
        if not within(root_real, full):
            skipped_symlinks.append(rel_path.replace(os.sep, "/"))
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue

        exact = False
        if lang == "python":
            parsed = scan_python(text)
            if parsed is not None:
                symbols, imports = parsed
                exact = True
            else:
                symbols, imports = scan_generic(text)
        else:
            symbols, imports = scan_generic(text)

        seen, unique = set(), []
        for entry in imports:
            key = (entry["name"], entry["line"])
            if key not in seen:
                seen.add(key)
                unique.append(entry)

        records.append({
            "path": rel_path.replace(os.sep, "/"),
            "lang": lang,
            "loc": text.count("\n") + 1,
            "exact": exact,
            "is_test": is_test_path(rel_path),
            "symbols": symbols,
            "imports": sorted(unique, key=lambda e: (e["line"], e["name"])),
        })

    by_module = {module_key(r["path"]): r["path"] for r in records}
    by_stem = {}
    for record in records:
        by_stem.setdefault(os.path.splitext(os.path.basename(record["path"]))[0], record["path"])

    edges, unresolved_total = [], 0
    for record in records:
        seen_targets = set()
        for entry in record["imports"]:
            target = resolve_one(entry["name"], by_module, by_stem)
            if target is None:
                unresolved_total += 1
                continue
            if target == record["path"] or target in seen_targets:
                continue
            seen_targets.add(target)
            edges.append({
                "from": record["path"],
                "to": target,
                "line": entry["line"],
                "import": entry["name"],
            })

    fan_in = Counter(e["to"] for e in edges)
    fan_out = Counter(e["from"] for e in edges)

    return {
        "root": root_real,
        "edges_are": "imports, not calls -- an edge does not prove an invocation",
        "files": records,
        "edges": edges,
        "fan_in": dict(fan_in),
        "fan_out": dict(fan_out),
        "unresolved_imports": unresolved_total,
        "skipped_symlinks": skipped_symlinks,
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
    lines.append("files %d  loc %d  symbols %d  import-edges %d" % (
        totals["files"], totals["loc"], totals["symbols"], len(data["edges"])))
    lines.append("languages: %s" % ", ".join(
        "%s=%d" % kv for kv in sorted(totals["languages"].items(), key=lambda kv: -kv[1])))
    lines.append("exact (ast-parsed): %d of %d files; unresolved imports: %d" % (
        totals["exact_files"], totals["files"], data["unresolved_imports"]))
    if data["skipped_symlinks"]:
        lines.append("skipped symlinks leaving the root: %d -- %s" % (
            len(data["skipped_symlinks"]), ", ".join(data["skipped_symlinks"][:5])))

    by_path = {r["path"]: r for r in data["files"]}
    fan_in = data["fan_in"]

    lines.append("")
    lines.append("most depended upon (fan-in):")
    for path, count in sorted(fan_in.items(), key=lambda kv: -kv[1])[:top]:
        lines.append("  %-4d %-60s %d loc" % (count, path, by_path.get(path, {}).get("loc", 0)))

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
    print("wrote %s (%d files, %d import-edges)" % (
        args.out, len(data["files"]), len(data["edges"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
