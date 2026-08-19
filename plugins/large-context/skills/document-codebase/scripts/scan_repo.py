#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/scan_repo.py
# Regenerate: python3 tools/materialize.py
"""Extract a repository's structure without an LLM: symbols, imports, dependency graph.

    python3 scripts/scan_repo.py --root . --out structure.json --summary

Python files are parsed with `ast`, so their symbols and imports are exact. Other
languages are scanned with import-line regexes, which is approximate — every record
carries an `exact` flag saying which it is.

Every import carries the line it appears on, and every edge carries the line of the
import that created it, so a dependency claim can be cited as `path:line`.

Edges record imports, not calls. An import edge proves that A references B; it does
not prove that A invokes anything in B. There is no call graph here.

An import that could name more than one file in the repository produces no edge. A
missing edge is recoverable; a confident wrong one is not.

Files whose extension has no parser here are counted and reported as unscanned, so a
caller cannot mistake "not looked at" for "nothing there".

`--detail` adds classes, methods, attributes and base classes, for Python only -- regex
can find a class name but not its bases, and a half-filled record reads like a complete
one. A base class links to the file defining it only when the import resolves *and* that
file defines a class by that name; otherwise it stays unresolved.

Emits JSON on --out and a short ranked digest on --summary. Read the digest; do not
read the JSON into context, query it with code.

Standard library only. Reads the working tree under --root and writes only --out.
Symlinks pointing outside --root are skipped, not followed. No network.
"""

import argparse
import ast
import fnmatch
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

# Extensions that are not code, so their absence from LANG_BY_EXT is not a coverage gap
# worth reporting. Anything else that goes unparsed is surfaced in `unscanned`.
NON_SOURCE_EXT = {
    ".md", ".markdown", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".lock", ".csv", ".tsv", ".xml", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf",
    ".eot", ".otf", ".mp3", ".mp4", ".webm", ".mov", ".gitignore", ".editorconfig",
    ".env", ".log", ".map", ".min", ".snap", ".patch", ".diff", ".manifest",
}

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", "site-packages",
}

# Approximate import extraction for non-Python languages.
IMPORT_PATTERNS = [
    re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""),      # js/ts
    re.compile(r"""^\s*import\s+['"]([^'"]+)['"]"""),                 # js/ts side-effect
    re.compile(r"""require_relative\s+['"]([^'"]+)['"]"""),           # ruby
    re.compile(r"""^\s*require\s+['"]([^'"]+)['"]"""),                # ruby
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),             # cjs
    re.compile(r"""^\s*#include\s*[<"]([^>"]+)[>"]"""),               # c/cpp
    re.compile(r"""^\s*use\s+([A-Za-z_][\w:]*)"""),                   # rust
    re.compile(r"""^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*)"""),  # java, single-line go
]

SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)")),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),        # go
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)")),                # rust
    ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)")),              # rust
    ("method", re.compile(r"^\s*def\s+([A-Za-z_]\w*[?!=]?)")),                      # ruby
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
    """Exact symbols and imports via ast. Returns (symbols, imports, tree) or None.

    The tree comes back so `--detail` can reuse it instead of parsing the file twice.
    """
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
                imports.append({"name": alias.name, "line": node.lineno, "level": 0})
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if node.module:
                imports.append({"name": node.module, "line": node.lineno, "level": level})
            else:
                # `from . import helper` -- the module lives in the alias, not in
                # node.module. Recording only the dots would drop the edge entirely.
                for alias in node.names:
                    imports.append({"name": alias.name, "line": node.lineno, "level": level})
    return symbols, imports, tree


def dotted(node):
    """Name or Attribute chain -> 'a.b.c'. Anything else -> None, never a guess."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def decorator_name(node):
    return dotted(node.func) if isinstance(node, ast.Call) else dotted(node)


def visibility(name):
    if name.startswith("__") and name.endswith("__"):
        return "special"
    return "private" if name.startswith("_") else "public"


def params_of(func):
    args = func.args
    names = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def self_attributes(func):
    """`self.x = ...` inside one method, in source order."""
    found = []
    for node in ast.walk(func):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                found.append({"name": target.attr, "line": target.lineno})
    return found


def detail_python(tree):
    """Class and function detail from an already-parsed tree.

    Top-level definitions only, matching what `scan_python` records as symbols. Base
    classes are captured by written name here; resolving them to files needs the whole
    repository index, so that happens in a later pass.
    """
    classes, functions = [], []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "params": params_of(node),
                "decorators": [d for d in map(decorator_name, node.decorator_list) if d],
            })
        elif isinstance(node, ast.ClassDef):
            methods, attributes, seen_attrs = [], [], set()

            for stmt in node.body:
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in seen_attrs:
                        seen_attrs.add(target.id)
                        attributes.append({"name": target.id, "line": target.lineno,
                                           "from": "class-body"})

            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                methods.append({
                    "name": stmt.name,
                    "line": stmt.lineno,
                    "params": params_of(stmt),
                    "visibility": visibility(stmt.name),
                    "decorators": [d for d in map(decorator_name, stmt.decorator_list) if d],
                })
                for attr in self_attributes(stmt):
                    if attr["name"] not in seen_attrs:
                        seen_attrs.add(attr["name"])
                        attributes.append(dict(attr, **{"from": stmt.name}))

            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": [{"name": b, "resolved": None, "line": None}
                          for b in map(dotted, node.bases) if b],
                "decorators": [d for d in map(decorator_name, node.decorator_list) if d],
                "methods": methods,
                "attributes": attributes,
            })

    return classes, functions


def python_aliases(tree):
    """Local name -> the import entry that introduced it.

    `import a.b` binds `a`; `from a import b as c` binds `c` and points at module `a`.
    Without this map a base class written as `Base` cannot be traced to the file that
    defines it.
    """
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = {"name": alias.name, "line": node.lineno, "level": 0}
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            for alias in node.names:
                local = alias.asname or alias.name
                target = node.module if node.module else alias.name
                aliases[local] = {"name": target, "line": node.lineno, "level": level}
    return aliases


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
                imports.append({"name": entry.group(1), "line": lineno, "level": 0})
            continue
        if GO_BLOCK_OPEN.match(line):
            in_go_block = True
            continue

        for pattern in IMPORT_PATTERNS:
            match = pattern.search(line)
            if match:
                imports.append({"name": match.group(1), "line": lineno, "level": 0})
                break
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.match(line)
            if match:
                symbols.append({"name": match.group(1), "kind": kind, "line": lineno})
                break
    return symbols, imports


def module_key(path):
    """Repo-relative path -> dotted module name, for resolving imports."""
    stem = os.path.splitext(path)[0].replace("/", ".")
    if stem.endswith(".__init__"):
        stem = stem[: -len(".__init__")]
    return stem


def build_indexes(records):
    """Three lookups. Ambiguous keys are dropped, so they can never make an edge."""
    by_module, suffix_hits, stem_hits = {}, defaultdict(set), defaultdict(set)

    for record in records:
        path = record["path"]
        key = module_key(path)
        by_module[key] = path

        parts = key.split(".")
        for i in range(len(parts)):
            suffix_hits[".".join(parts[i:])].add(path)

        stem_hits[os.path.splitext(os.path.basename(path))[0]].add(path)

    by_suffix = {k: next(iter(v)) for k, v in suffix_hits.items() if len(v) == 1}
    by_stem = {k: next(iter(v)) for k, v in stem_hits.items() if len(v) == 1}
    return by_module, by_suffix, by_stem


def stem_candidates(name):
    """Plausible file stems for a slash- or dot-separated import name."""
    base = os.path.basename(name.replace("\\", "/"))
    root, ext = os.path.splitext(base)
    if ext.lower() in LANG_BY_EXT:
        return [root]
    out = [base]
    if "." in base:
        out.append(base.split(".")[-1])
    return out


def resolve_relative(importer, name, level):
    """Python relative import -> dotted module key, anchored at the importing package.

    Stripping the dots and searching globally is what makes `from . import helper`
    in pkg2 resolve to pkg1/helper.py. The package the import was written in is the
    only correct starting point.
    """
    package = os.path.dirname(importer).replace("/", ".")
    parts = [p for p in package.split(".") if p]
    for _ in range(level - 1):
        if not parts:
            return None
        parts.pop()
    if name:
        parts.append(name)
    return ".".join(parts) if parts else None


def resolve_one(entry, importer, by_module, by_suffix, by_stem):
    """Map one import onto a repo file, or None when unknown or ambiguous."""
    name = entry["name"]
    level = entry.get("level", 0)

    if level:
        key = resolve_relative(importer, name, level)
        # A relative import names something inside this repository or nothing at all,
        # so there is no global fallback here.
        return by_module.get(key) if key else None

    hit = by_module.get(name)
    if hit is not None:
        return hit

    # Dotted suffix: `com.acme.Util` under src/main/java/, `pkg.mod` under a src root.
    hit = by_suffix.get(name)
    if hit is not None:
        return hit

    parts = name.split(".")
    while len(parts) > 1:
        parts.pop()
        hit = by_module.get(".".join(parts)) or by_suffix.get(".".join(parts))
        if hit is not None:
            return hit

    for candidate in stem_candidates(name):
        hit = by_stem.get(candidate)
        if hit is not None:
            return hit
    return None


def wanted(path, patterns):
    """No patterns means every file. Otherwise the path must match one of them."""
    return not patterns or any(fnmatch.fnmatch(path, p) for p in patterns)


def resolve_bases(records, aliases_by_path, by_module, by_suffix, by_stem):
    """Point each base class at the file that defines it, or leave it unresolved.

    Two steps, because a name alone is not an answer: find the file the base name was
    imported from, then confirm that file actually defines a class by that name. A base
    that fails either step keeps `resolved: null` -- a missing link is recoverable, a
    confidently wrong one is not.
    """
    classes_by_path = {r["path"]: {c["name"]: c["line"] for c in r.get("classes", [])}
                       for r in records if "classes" in r}

    for record in records:
        path = record["path"]
        local = classes_by_path.get(path, {})
        aliases = aliases_by_path.get(path, {})

        for cls in record.get("classes", []):
            for base in cls["bases"]:
                head = base["name"].split(".")[0]
                leaf = base["name"].split(".")[-1]

                if base["name"] in local:
                    base["resolved"], base["line"] = path, local[base["name"]]
                    continue

                entry = aliases.get(head)
                if entry is None:
                    continue
                target = resolve_one(entry, path, by_module, by_suffix, by_stem)
                if target is None:
                    continue

                # The import resolved, but only a matching class name proves this is
                # where the base is defined -- the module may merely re-export it.
                line = classes_by_path.get(target, {}).get(leaf)
                if line is not None:
                    base["resolved"], base["line"] = target, line


def build(root, detail=False, detail_match=None):
    root_real = os.path.realpath(root)
    records, skipped_symlinks = [], []
    unscanned = Counter()
    aliases_by_path = {}

    for rel_path in list_files(root):
        ext = os.path.splitext(rel_path)[1].lower()
        lang = LANG_BY_EXT.get(ext)
        if not lang:
            if ext and ext not in NON_SOURCE_EXT:
                unscanned[ext] += 1
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

        exact, tree = False, None
        if lang == "python":
            parsed = scan_python(text)
            if parsed is not None:
                symbols, imports, tree = parsed
                exact = True
            else:
                symbols, imports = scan_generic(text)
        else:
            symbols, imports = scan_generic(text)

        seen, unique = set(), []
        for entry in imports:
            key = (entry["name"], entry["line"], entry.get("level", 0))
            if key not in seen:
                seen.add(key)
                unique.append(entry)

        path = rel_path.replace(os.sep, "/")
        record = {
            "path": path,
            "lang": lang,
            "loc": text.count("\n") + 1,
            "exact": exact,
            "parser": "ast" if exact else "regex",
            "is_test": is_test_path(rel_path),
            "symbols": symbols,
            "imports": sorted(unique, key=lambda e: (e["line"], e["name"])),
        }

        # Detail needs an exact tree. A regex pass can find a class name but not its
        # bases or attributes, and a half-filled record reads like a complete one.
        if detail and tree is not None and wanted(path, detail_match):
            record["classes"], record["functions"] = detail_python(tree)
            aliases_by_path[path] = python_aliases(tree)

        records.append(record)

    by_module, by_suffix, by_stem = build_indexes(records)
    if detail:
        resolve_bases(records, aliases_by_path, by_module, by_suffix, by_stem)

    edges, unresolved_total = [], 0
    for record in records:
        seen_targets = set()
        for entry in record["imports"]:
            target = resolve_one(entry, record["path"], by_module, by_suffix, by_stem)
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
                "import": ("." * entry.get("level", 0)) + entry["name"],
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
        "unscanned_extensions": dict(unscanned),
        "totals": {
            "files": len(records),
            "loc": sum(r["loc"] for r in records),
            "symbols": sum(len(r["symbols"]) for r in records),
            "languages": dict(Counter(r["lang"] for r in records)),
            "exact_files": sum(1 for r in records if r["exact"]),
            "unscanned_files": sum(unscanned.values()),
            "detailed_files": sum(1 for r in records if "classes" in r),
            "classes": sum(len(r.get("classes", ())) for r in records),
            "methods": sum(len(c["methods"]) for r in records for c in r.get("classes", ())),
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

    if totals["detailed_files"]:
        bases = [b for r in data["files"] for c in r.get("classes", ()) for b in c["bases"]]
        linked = sum(1 for b in bases if b["resolved"])
        skipped = totals["files"] - totals["detailed_files"]
        lines.append("detail: %d file(s), %d class(es), %d method(s); "
                     "base classes linked to a defining file: %d of %d" % (
                         totals["detailed_files"], totals["classes"], totals["methods"],
                         linked, len(bases)))
        if skipped:
            lines.append("  %d file(s) carry no detail -- not Python, unparseable, or "
                         "outside --detail-match; they have no class records at all" % skipped)

    if totals["unscanned_files"]:
        top_ext = sorted(data["unscanned_extensions"].items(), key=lambda kv: -kv[1])[:8]
        lines.append("NOT SCANNED -- no parser for these extensions: %d file(s): %s" % (
            totals["unscanned_files"], ", ".join("%s=%d" % kv for kv in top_ext)))
        lines.append("  say so in the coverage section; these files were not examined")
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
    parser.add_argument("--detail", action="store_true",
                        help="also extract classes, methods, attributes and base classes")
    parser.add_argument("--detail-match", action="append", metavar="GLOB",
                        help="limit --detail to paths matching this glob; repeatable")
    args = parser.parse_args()

    if args.detail_match and not args.detail:
        sys.stderr.write("FAIL  --detail-match needs --detail\n")
        return 1

    if not os.path.isdir(args.root):
        sys.stderr.write("FAIL  --root is not a directory: %s\n" % args.root)
        return 1

    data = build(args.root, detail=args.detail, detail_match=args.detail_match)
    if not data["files"]:
        sys.stderr.write("FAIL  no source files found under %s\n" % args.root)
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
