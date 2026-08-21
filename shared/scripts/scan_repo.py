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

An import that could name more than one file in the repository produces no edge. A
missing edge is recoverable; a confident wrong one is not.

Files whose extension has no parser here are counted and reported as unscanned, so a
caller cannot mistake "not looked at" for "nothing there".

`--detail` adds classes, methods, attributes and base classes, for Python only -- regex
can find a class name but not its bases, and a half-filled record reads like a complete
one. A base class links to the file defining it only when the import resolves *and* that
file defines a class by that name; otherwise it stays unresolved.

The JSON carries `schema_version`, the source snapshot it was taken from, and a sha256
per file, so a later step can prove a claim still points at the code that was scanned.

Emits JSON on --out and a short ranked digest on --summary. Read the digest; do not
read the JSON into context, query it with code.

Standard library only. Reads the working tree under --root and writes only --out.
Symlinks pointing outside --root are skipped, not followed. No network.
"""

import argparse
import ast
import fnmatch
import hashlib
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

SCHEMA_VERSION = 2

# The compared value matters: `if __name__ == "pkg.optional":` is a real pattern and is
# not a way into the program. Matching the whole comparison keeps it out.
MAIN_GUARD_RE = re.compile(r"""^if\s+__name__\s*==\s*(['"])__main__\1""", re.MULTILINE)

# Names that conventionally mean "this is how the program starts". Only consulted for a
# file nothing imports, so a `main.py` in the middle of a package does not qualify.
ENTRY_FILENAMES = {
    "__main__.py", "main.py", "cli.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
    "main.go", "main.rs", "Main.java", "index.js", "index.ts", "server.js", "server.ts",
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
    re.compile(r"""^\s*#include\s*<([^>]+)>"""),                      # c/cpp, angle form
    re.compile(r"""^\s*use\s+([A-Za-z_][\w:]*)"""),                   # rust
    re.compile(r"""^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*)"""),  # java, single-line go
]

# `#include "foo.h"` conventionally searches the including file's directory first, and
# the angle form does not. Kept separate so that preference can be honoured rather than
# both collapsing into one repository-wide stem search.
QUOTED_INCLUDE = re.compile(r"""^\s*#include\s*"([^"]+)\"""")

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


def file_hash(full):
    """sha256 of the bytes on disk, or None when they cannot be read."""
    digest_ = hashlib.sha256()
    try:
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest_.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest_.hexdigest()


def git_snapshot(root):
    """Which revision this scan describes, and whether the tree was clean.

    `dirty` is true when the answer is unknown as well as when the tree has changes --
    a revision that might not match the files is worth no more than no revision at all.
    """
    snapshot = {"root": os.path.abspath(root), "revision": None, "dirty": True}

    def git(*args):
        try:
            out = subprocess.run(["git", "-C", root] + list(args),
                                 capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout if out.returncode == 0 else None

    revision = git("rev-parse", "HEAD")
    if revision is None:
        return snapshot
    snapshot["revision"] = revision.strip()
    status = git("status", "--porcelain")
    if status is not None:
        snapshot["dirty"] = bool(status.strip())
    return snapshot


def entry_points_of(records, fan_in):
    """Files nothing in the repository imports that also look like a way in.

    Fan-in zero alone is not enough -- it is equally the signature of dead code. A
    `__main__` guard or a conventional launcher name is the part that says "start
    here", so each entry carries which of the two it was found by.
    """
    found = []
    for record in records:
        path = record["path"]
        if fan_in.get(path) or record["is_test"]:
            continue
        if record.get("main_guard"):
            found.append({"path": path, "reason": "main_guard"})
        elif os.path.basename(path) in ENTRY_FILENAMES:
            found.append({"path": path, "reason": "conventional_name"})
    return sorted(found, key=lambda e: e["path"])


def diagnostics_of(records, unresolved, skipped_symlinks, unscanned):
    """What the scan could not do, as rows rather than as prose in a digest.

    The digest already says these things to a reader. These rows say them to a script,
    so a coverage section can be generated rather than transcribed by hand.
    """
    found = []
    for record in records:
        if record["lang"] == "python" and not record["exact"]:
            found.append({"code": "D004", "severity": "warning", "path": record["path"],
                          "message": "Python file did not parse; imports are regex-approximated"})
        elif not record["exact"]:
            found.append({"code": "D005", "severity": "info", "path": record["path"],
                          "message": "no parser for %s; imports are regex-approximated"
                                     % record["lang"]})
    if unresolved:
        found.append({"code": "D001", "severity": "info", "path": None,
                      "message": "%d import(s) named nothing in this repository -- "
                                 "third-party or standard library" % unresolved})
    for ext, count in sorted(unscanned.items()):
        found.append({"code": "D002", "severity": "warning", "path": None,
                      "message": "%d file(s) with extension %s were not examined" % (count, ext)})
    for path in skipped_symlinks:
        found.append({"code": "D003", "severity": "warning", "path": path,
                      "message": "symlink resolves outside the root; skipped, not followed"})
    return found


def coverage_of(records, detail, unresolved, skipped_symlinks, unscanned):
    """What was covered, as numbers a report can cite without recomputing them."""
    return {
        "files_scanned": len(records),
        "files_exact": sum(1 for r in records if r["exact"]),
        "files_approximate": sum(1 for r in records if not r["exact"]),
        "files_unscanned": sum(unscanned.values()),
        "files_hashed": sum(1 for r in records if r["source_hash"]),
        "languages": dict(Counter(r["lang"] for r in records)),
        "unresolved_imports": unresolved,
        "skipped_symlinks": len(skipped_symlinks),
        "unscanned_extensions": dict(unscanned),
        "detail_requested": detail,
        "files_with_detail": sum(1 for r in records if "classes" in r),
    }


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
                # `import a.b.c` binds `a`; `import a.b as x` binds `x`. The bound name
                # is what a usage checker reports on, and it is not the module name.
                bound = alias.asname or alias.name.split(".")[0]
                imports.append({"name": alias.name, "line": node.lineno, "level": 0,
                                "bindings": [bound]})
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if node.module:
                imports.append({"name": node.module, "line": node.lineno, "level": level,
                                "bindings": [a.asname or a.name for a in node.names]})
            else:
                # `from . import helper` -- the module lives in the alias, not in
                # node.module. Recording only the dots would drop the edge entirely.
                for alias in node.names:
                    imports.append({"name": alias.name, "line": node.lineno, "level": level,
                                    "bindings": [alias.asname or alias.name]})
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


def base_name(node):
    """The written name of a base class, seeing through a subscript.

    `class Repo(Generic[T])` parses the base as a Subscript, so a plain dotted() call
    returns None and the base vanishes from the record entirely -- a class that reads
    as having no parent at all. Dropping the parameters keeps the name, which is what a
    reader and a diagram need; the parameters themselves are not a dependency.
    """
    if isinstance(node, ast.Subscript):
        node = node.value
    return dotted(node)


def decorator_name(node):
    return dotted(node.func) if isinstance(node, ast.Call) else dotted(node)


def visibility(name):
    if name.startswith("__") and name.endswith("__"):
        return "special"
    return "private" if name.startswith("_") else "public"


def params_of(func):
    """Parameter names, keeping the markers that say how each may be passed.

    `*` and `/` are part of the signature, not decoration: without the bare `*` a
    keyword-only argument reads as positional, and documentation built from that list
    would advertise a call the function rejects.
    """
    args = func.args
    names = [a.arg for a in args.posonlyargs]
    if args.posonlyargs:
        names.append("/")
    names.extend(a.arg for a in args.args)
    if args.vararg:
        names.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        names.append("*")
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def self_targets(node):
    """`self.x` inside an assignment target, unwrapping tuple and list unpacking.

    `self.x, self.y = point` binds both attributes; a check that only accepts a bare
    Attribute node records neither.
    """
    if isinstance(node, (ast.Tuple, ast.List)):
        found = []
        for element in node.elts:
            found.extend(self_targets(element))
        return found
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "self"):
        return [{"name": node.attr, "line": node.lineno}]
    return []


def annotation_names(node):
    """Every dotted name written inside a type annotation, outermost first.

    `Order` gives ['Order']; `Optional[Order]` gives ['Optional', 'Order']; `dict[str,
    Order]` gives ['dict', 'str', 'Order']. The container is kept alongside what it
    contains because neither can be assumed to be the interesting one -- a later pass
    keeps whichever resolves to a class in this repository and discards the rest.

    A string annotation is re-parsed, so `x: "Order"` under `from __future__ import
    annotations` is not silently invisible.
    """
    found = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except (SyntaxError, ValueError):
            return found

    if isinstance(node, (ast.Name, ast.Attribute)):
        name = dotted(node)
        if name:
            found.append(name)
    elif isinstance(node, ast.Subscript):
        found.extend(annotation_names(node.value))
        found.extend(annotation_names(node.slice))
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            found.extend(annotation_names(element))
    elif isinstance(node, ast.BinOp):
        # `Order | None`, the 3.10 union spelling.
        found.extend(annotation_names(node.left))
        found.extend(annotation_names(node.right))
    return found


def self_attributes(func):
    """`self.x = ...` inside one method, in source order, with any written type."""
    found = []
    for node in ast.walk(func):
        targets, annotation = [], None
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
            annotation = getattr(node, "annotation", None)
        types = annotation_names(annotation) if annotation is not None else []
        for target in targets:
            for attr in self_targets(target):
                found.append(dict(attr, type_names=types) if types else attr)
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
                targets, annotation = [], None
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                    annotation = stmt.annotation
                types = annotation_names(annotation) if annotation is not None else []
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in seen_attrs:
                        seen_attrs.add(target.id)
                        record = {"name": target.id, "line": target.lineno,
                                  "from": "class-body"}
                        if types:
                            record["type_names"] = types
                        attributes.append(record)

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
                          for b in map(base_name, node.bases) if b],
                "decorators": [d for d in map(decorator_name, node.decorator_list) if d],
                "methods": methods,
                "attributes": attributes,
            })

    return classes, functions


def python_aliases(tree):
    """Local name -> every module-level import that bound it, oldest first.

    `import a.b` binds `a`; `from a import b as c` binds `c`, points at module `a`, and
    remembers that the thing imported is really called `b` -- the target file defines
    `b`, not `c`, so dropping the original name loses the class.

    Only module-level imports are collected. Walking the whole tree would let an import
    inside a function overwrite the binding that was in force where a class was defined,
    and emit exactly the confidently wrong link this resolver exists to avoid. A name
    bound more than once keeps every binding, because which one applies depends on where
    the class sits in the file.
    """
    aliases = defaultdict(list)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local].append({"name": alias.name, "line": node.lineno,
                                       "level": 0, "symbol": None})
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            for alias in node.names:
                local = alias.asname or alias.name
                target = node.module if node.module else alias.name
                symbol = alias.name if node.module else None
                aliases[local].append({"name": target, "line": node.lineno,
                                       "level": level, "symbol": symbol})
    return dict(aliases)


def binding_before(bindings, line):
    """The import in force at `line` -- the latest one above it, or None."""
    candidates = [b for b in bindings if b["line"] < line]
    return max(candidates, key=lambda b: b["line"]) if candidates else None


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

        quoted = QUOTED_INCLUDE.match(line)
        if quoted:
            imports.append({"name": quoted.group(1), "line": lineno, "level": 0,
                            "quoted": True})
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
    """Four lookups. Ambiguous keys are dropped, so they can never make an edge."""
    module_hits, suffix_hits = defaultdict(set), defaultdict(set)
    stem_hits, path_hits = defaultdict(set), defaultdict(set)

    for record in records:
        path = record["path"]
        key = module_key(path)
        # Accumulated, not assigned. `foo.py` and `foo.ts` both key on `foo`, and
        # assigning would hand every `import foo` to whichever was scanned last -- a
        # confident edge into an arbitrary language. Ambiguity drops the key here for
        # the same reason it does in the three indexes below.
        module_hits[key].add(path)

        parts = key.split(".")
        for i in range(len(parts)):
            suffix_hits[".".join(parts[i:])].add(path)

        stem_hits[os.path.splitext(os.path.basename(path))[0]].add(path)

        # Keyed on the path with its extension dropped, because `./util` is written
        # without one. Both spellings are kept: `a/b.h` is included as "a/b.h" too.
        path_hits[os.path.splitext(path)[0]].add(path)
        path_hits[path].add(path)

    by_module = {k: next(iter(v)) for k, v in module_hits.items() if len(v) == 1}
    by_suffix = {k: next(iter(v)) for k, v in suffix_hits.items() if len(v) == 1}
    by_stem = {k: next(iter(v)) for k, v in stem_hits.items() if len(v) == 1}
    by_path = {k: next(iter(v)) for k, v in path_hits.items() if len(v) == 1}
    return by_module, by_suffix, by_stem, by_path


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


def resolve_path_relative(importer, name, by_path):
    """`./helper` in src/main.ts -> src/helper.ts, or None.

    A specifier written `./x` or `../x` names a file next to the importer and nowhere
    else. Falling through to a repository-wide stem search would happily bind it to
    `test/helper.ts` -- a confident edge that is simply wrong, and one that then feeds
    the fan-in ranking the document is built from.
    """
    joined = os.path.normpath(os.path.join(os.path.dirname(importer), name))
    joined = joined.replace(os.sep, "/")
    if joined.startswith("../"):
        return None
    # `./util` may be util.ts, and `./util/` may be util/index.ts; both are written
    # without the extension, so the index is keyed on the extension-stripped path.
    return by_path.get(joined) or by_path.get(joined + "/index")


def resolve_one(entry, importer, by_module, by_suffix, by_stem, by_path=None):
    """Map one import onto a repo file, or None when unknown or ambiguous."""
    name = entry["name"]
    level = entry.get("level", 0)

    # An explicitly relative specifier resolves against the importing file or not at
    # all. No global fallback: a missing edge is recoverable, a wrong one is not.
    if not level and by_path is not None and name.startswith(("./", "../")):
        return resolve_path_relative(importer, name, by_path)

    # A quoted include conventionally searches the including file's directory first;
    # unlike ./ it may also be written against a project root, so the usual chain
    # still runs when that fails.
    if not level and by_path is not None and entry.get("quoted"):
        hit = resolve_path_relative(importer, name, by_path)
        if hit is not None:
            return hit

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


def resolve_attribute_types(records, aliases_by_path, by_module, by_suffix, by_stem,
                            by_path):
    """Point an attribute's written type at the file defining that class, or drop it.

    Same two steps as `resolve_bases`, and the same refusal to guess: a type name that
    does not resolve to a file defining a class by that name leaves no link at all. Most
    annotations are `str`, `int`, `Optional` and other names this repository does not
    define, and every one of those must resolve to nothing rather than to something
    plausible.

    Only attributes are resolved. A parameter type says a function is passed something;
    an attribute type says the class holds one, which is what composition means.
    """
    classes_by_path = {r["path"]: {c["name"] for c in r.get("classes", [])}
                       for r in records if "classes" in r}

    for record in records:
        path = record["path"]
        local = classes_by_path.get(path, set())
        aliases = aliases_by_path.get(path, {})

        for cls in record.get("classes", []):
            for attribute in cls.get("attributes", []):
                resolved = []
                for name in attribute.get("type_names", ()):
                    head, leaf = name.split(".")[0], name.split(".")[-1]
                    if name in local:
                        resolved.append({"name": name, "resolved": path})
                        continue
                    entry = binding_before(aliases.get(head, ()), cls["line"])
                    if entry is None:
                        continue
                    target = resolve_one(entry, path, by_module, by_suffix, by_stem,
                                         by_path)
                    if target is None:
                        continue
                    wanted = entry["symbol"] if head == name and entry["symbol"] else leaf
                    if wanted in classes_by_path.get(target, set()):
                        resolved.append({"name": wanted, "resolved": target})
                if resolved:
                    attribute["types"] = resolved


def resolve_bases(records, aliases_by_path, by_module, by_suffix, by_stem, by_path):
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

                entry = binding_before(aliases.get(head, ()), cls["line"])
                if entry is None:
                    continue
                target = resolve_one(entry, path, by_module, by_suffix, by_stem, by_path)
                if target is None:
                    continue

                # `from pkg import Base as Parent` defines `Base` in the target file,
                # not `Parent`, so the written name is the wrong thing to look up.
                wanted_name = entry["symbol"] if head == base["name"] and entry["symbol"] else leaf

                # The import resolved, but only a matching class name proves this is
                # where the base is defined -- the module may merely re-export it.
                line = classes_by_path.get(target, {}).get(wanted_name)
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
            # Hashing the bytes on disk, not the decoded text: a later step compares
            # this against the file it reads, and errors="replace" above would make a
            # non-UTF-8 file hash to something no reader can reproduce.
            "source_hash": file_hash(full),
            "main_guard": bool(lang == "python" and MAIN_GUARD_RE.search(text)),
            "symbols": symbols,
            "imports": sorted(unique, key=lambda e: (e["line"], e["name"])),
        }

        # Detail needs an exact tree. A regex pass can find a class name but not its
        # bases or attributes, and a half-filled record reads like a complete one.
        if detail and tree is not None and wanted(path, detail_match):
            record["classes"], record["functions"] = detail_python(tree)
            aliases_by_path[path] = python_aliases(tree)

        records.append(record)

    by_module, by_suffix, by_stem, by_path = build_indexes(records)
    if detail:
        resolve_bases(records, aliases_by_path, by_module, by_suffix, by_stem, by_path)
        resolve_attribute_types(records, aliases_by_path, by_module, by_suffix, by_stem,
                                by_path)

    edges, unresolved_total = [], 0
    for record in records:
        # One edge per (from, to), keeping the first import line -- but every binding
        # that produced it, because a usage checker reports on bindings and would
        # otherwise have nothing in the edge to attach itself to.
        by_target, order = {}, []
        for entry in record["imports"]:
            target = resolve_one(entry, record["path"], by_module, by_suffix, by_stem, by_path)
            if target is None:
                unresolved_total += 1
                continue
            if target == record["path"]:
                continue
            if target not in by_target:
                by_target[target] = {
                    "edge_id": "import:%s:%d:%s" % (record["path"], entry["line"], target),
                    "from": record["path"],
                    "to": target,
                    "line": entry["line"],
                    "import": ("." * entry.get("level", 0)) + entry["name"],
                }
                order.append(target)
            for name in entry.get("bindings", ()):
                bound = by_target[target].setdefault("bindings", [])
                if name not in bound:
                    bound.append(name)
        edges.extend(by_target[target] for target in order)

    fan_in = Counter(e["to"] for e in edges)
    fan_out = Counter(e["from"] for e in edges)

    return {
        "schema_version": SCHEMA_VERSION,
        "source": git_snapshot(root),
        "root": root_real,
        "edges_are": "imports, not calls -- an edge does not prove an invocation",
        "detail_requested": detail,
        "files": records,
        "edges": edges,
        "fan_in": dict(fan_in),
        "fan_out": dict(fan_out),
        "entry_points": entry_points_of(records, fan_in),
        "diagnostics": diagnostics_of(records, unresolved_total, skipped_symlinks, unscanned),
        "coverage": coverage_of(records, detail, unresolved_total, skipped_symlinks, unscanned),
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

    # Reported whenever detail was asked for, including the zero case: a mistyped glob
    # otherwise produces a silent digest that looks like a repository with no classes.
    if data.get("detail_requested"):
        bases = [b for r in data["files"] for c in r.get("classes", ()) for b in c["bases"]]
        linked = sum(1 for b in bases if b["resolved"])
        skipped = totals["files"] - totals["detailed_files"]
        lines.append("detail: %d file(s), %d class(es), %d method(s); "
                     "base classes linked to a defining file: %d of %d" % (
                         totals["detailed_files"], totals["classes"], totals["methods"],
                         linked, len(bases)))
        if not totals["detailed_files"]:
            lines.append("  NO FILE PRODUCED DETAIL -- check --detail-match, or the "
                         "repository has no parseable Python")
        elif skipped:
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
