#!/usr/bin/env python3
"""What is wrong with a documentation tree that every other check would pass.

    python3 scripts/publish/release_hygiene.py --docs docs

Every other check in this pipeline asks about content: is the claim supported, does the
markup parse, does the reference resolve. None of them looks at the *tree* -- and a tree
can be wrong in ways that leave every page correct:

    two indexes         a reader lands on one, the pipeline maintains the other, and
                        half the document is unreachable from where anyone starts
    two configurations  the build uses whichever it finds first, so a fix applied to one
                        does nothing and nobody can see why
    committed output    `_build/` in version control means the next reader's diff is
                        thousands of generated lines, and a stale HTML page outlives the
                        source it came from
    output in source    generated HTML beside the pages it was generated from, which the
                        next build reads as more source

Findings are `H0xx`. Each is a fact about the filesystem, so each is checkable in seconds
and none is a judgement about anybody's prose.

Exit codes: 0 clean, 1 findings, 2 bad input, 3 internal.
"""

import argparse
import json
import os
import sys


INDEX_NAMES = ("index.rst", "index.md")
CONFIG_NAME = "conf.py"
# Where a Sphinx build lands by default, plus the two other spellings in common use. A
# directory named like this inside the source tree is output, whatever it holds.
BUILD_NAMES = ("_build", "build", ".build", "html", "_site")
GENERATED_SUFFIXES = (".html", ".doctree", ".js.map")
# Sphinx writes these into a build directory and nowhere else, so finding one says the
# directory holding it is output rather than source.
BUILD_MARKERS = ("environment.pickle", ".buildinfo", "objects.inv", "searchindex.js")


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def add(findings, code, message, path=None):
    findings.append({"code": code, "message": message, "path": path})


def _walk(root):
    """Every (directory, filenames) under `root`, skipping nothing.

    Deliberately not pruned: a build directory nested three levels down is exactly the one
    a shallow check misses, and finding it is the point.
    """
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git",))
        yield base, sorted(names)


def build_dirs(docs):
    """Directories under `docs` that hold build output rather than source.

    By name or by marker, because both go wrong and only one of them is guessable. A
    directory called `_build` is output whatever is in it; one holding
    `environment.pickle` is output whatever it is called.

    **Every component is checked, not just the first.** A first attempt looked only at the
    top level, so `docs/a/b/_build` -- a nested build directory, which is exactly the one a
    shallow check misses -- went unreported while the stray HTML inside it was flagged as a
    leak. Its own test caught that.

    Only the outermost match is returned: the directories inside a build tree are build
    output too, and naming each of them says the same thing many times.
    """
    found = []
    for base, names in _walk(docs):
        if base == docs:
            continue
        if any(base.startswith(seen + os.sep) for seen in found):
            continue
        if (os.path.basename(base) in BUILD_NAMES
                or any(name in BUILD_MARKERS for name in names)):
            found.append(base)
    return sorted(found)


def indexes(docs):
    """Every index page in the tree, nearest the root first."""
    found = []
    for base, names in _walk(docs):
        for name in names:
            if name in INDEX_NAMES:
                found.append(os.path.relpath(os.path.join(base, name), docs))
    return sorted(found, key=lambda p: (p.count(os.sep), p))


def configs(docs):
    return sorted(os.path.relpath(os.path.join(base, CONFIG_NAME), docs)
                  for base, names in _walk(docs) if CONFIG_NAME in names)


def ignored(root, path):
    """Whether git ignores `path`. False when git cannot answer, rather than a guess."""
    import subprocess                                        # noqa: PLC0415
    try:
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def tracked(root, path):
    """Whether git has `path` in the index. False when git cannot answer."""
    import subprocess                                        # noqa: PLC0415
    try:
        result = subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def check(docs, root=".", expected_pages=()):
    """Every hygiene finding for the tree at `docs`."""
    findings = []
    if not os.path.isdir(docs):
        raise ValueError("%s is not a directory" % docs)

    found_indexes = indexes(docs)
    if not found_indexes:
        add(findings, "H001",
            "no index page: a reader has no entry point and Sphinx has no root document",
            docs)
    elif len(found_indexes) > 1:
        # Not a warning. A reader lands on one of them and the pipeline maintains the
        # other; which one wins is decided by whoever typed the URL.
        add(findings, "H002",
            "%d index pages, and nothing says which one a reader starts from: %s"
            % (len(found_indexes), ", ".join(found_indexes)), docs)

    found_configs = configs(docs)
    if len(found_configs) > 1:
        add(findings, "H003",
            "%d Sphinx configurations: a build uses whichever it is pointed at, so a "
            "change to the other one silently does nothing: %s"
            % (len(found_configs), ", ".join(found_configs)), docs)

    trees = build_dirs(docs)
    for directory in trees:
        relative = os.path.relpath(directory, root)
        if tracked(root, relative):
            add(findings, "H004",
                "build output is committed: every later diff carries generated lines, and "
                "a stale page outlives the source it came from", relative)
        elif not ignored(root, relative):
            add(findings, "H005",
                "build output is neither committed nor ignored, so it will be committed "
                "by the first `git add -A`", relative)

    # The build directories actually found, not the names they might have had: with a
    # fixed prefix list a nested build tree looked like source, and its output read as a
    # leak into the source tree rather than as output sitting where it belongs.
    inside_build = tuple(trees)
    for base, names in _walk(docs):
        if base in inside_build or any(base.startswith(seen + os.sep)
                                       for seen in inside_build):
            continue                     # inside the build tree, where output belongs
        for name in names:
            if name.endswith(GENERATED_SUFFIXES):
                add(findings, "H006",
                    "generated output sits in the source tree, where the next build reads "
                    "it as more source",
                    os.path.relpath(os.path.join(base, name), root))

    # A page the model produced that is not on disk is a toctree entry pointing at
    # nothing; `render_docs` writes them all, so this catches a tree edited afterwards.
    #
    # A settled authored page is the exception, and the caller removes it before getting
    # here. A waived page is one somebody decided the document does not need -- notably
    # `appendix/compliance`, which is waived by default -- and `render_docs` writes no
    # scaffold for it on purpose. Flagging that absence reported a deliberate decision as
    # a defect, which a real run showed immediately.
    for page in expected_pages:
        if not any(os.path.isfile(os.path.join(docs, page + ext))
                   for ext in (".rst", ".md")):
            add(findings, "H007",
                "the document model has a page that is not in the tree", page)
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", required=True, help="the rendered documentation tree")
    parser.add_argument("--root", default=".", help="repository root, for git questions")
    parser.add_argument("--doc", help="doc.json, so a page it names that is not on disk "
                                      "is reported")
    parser.add_argument("--out", help="write the findings here as JSON")
    args = parser.parse_args()

    expected = []
    if args.doc:
        try:
            with open(args.doc, encoding="utf-8") as fh:
                model = json.load(fh)
        except (OSError, ValueError) as exc:
            return fail("cannot read %s: %s" % (args.doc, exc))
        # A waived authored page is deliberately not in the tree, so it is not expected in
        # it. The ledger is the authority on which ones those are.
        settled = {row.get("page_id") for row in model.get("authored_ledger", ()) or ()
                   if row.get("status") == "waived"}
        expected = [p["id"] for p in model.get("pages", ())] + \
                   [p["id"] for p in model.get("authored_pages", ())
                    if p["id"] not in settled]

    try:
        findings = check(args.docs, args.root, expected)
    except ValueError as exc:
        return fail(str(exc))

    report = {"hygiene_version": 1, "docs": args.docs, "findings": findings,
              "passed": not findings}
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    for finding in findings:
        sys.stderr.write("%s  %s%s\n" % (finding["code"], finding["message"],
                                         " [%s]" % finding["path"]
                                         if finding["path"] else ""))
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
