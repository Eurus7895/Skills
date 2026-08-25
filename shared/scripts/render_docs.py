#!/usr/bin/env python3
"""Render doc.json to reStructuredText. The model decides what; this decides how.

    python3 scripts/render_docs.py --doc .docs-build/doc.json --out docs --check

One page per `doc.json` page, plus an `index.rst` whose toctree names every one of them
-- a page missing from the toctree is a page Sphinx warns about and nobody reads.
Headings, tables, references and escaping are this script's business and nobody else's;
an agent writing directives by hand produces markup that builds today and breaks on the
next directive it half-remembers.

--check validates the result as far as the machine allows, through `sphinx_support.py`:
`sphinx-build -W` when Sphinx is installed, docutils failing that, and `skipped` failing
both -- said out loud rather than passed over quietly. Its six outcomes separate a page
that does not parse from a reference that does not resolve from a page nobody has wired
into a toctree yet.

This script never creates or edits a Sphinx `conf.py`. Wiring the output into a project's
own documentation build is a separate, explicitly authorized step.

Exit codes: 0 rendered (and checked, if asked), 1 the check failed, 2 input error,
3 internal error.

Standard library only, plus Sphinx or docutils when --check finds them. Writes only
under --out.
"""

import argparse
import json
import os
import re
import shutil
import sys

import sphinx_support

SUPPORTED_FORMAT = {1}

# Underline characters by depth. Sphinx infers the hierarchy from order of first use,
# so these must stay consistent across every page in one build.
TITLE_CHAR = "="
SECTION_CHAR = "-"

# `word_` is a reference in RST and `[1]_` a footnote, and an undefined one fails the
# build. Mid-word underscores are not references, so `snake_case` -- which is most of
# what this pipeline writes -- is left alone rather than peppered with backslashes.
TRAILING_UNDERSCORE = re.compile(r"(?<=[\w\]])_(?![\w])")


def escape_inline(text):
    """Neutralise the characters that change meaning mid-sentence in RST.

    Backslash first, or escaping the others would be undone by the pass that follows.
    `*` opens emphasis and a lone `` ` `` opens a role; both swallow the rest of the
    line when a path or an identifier happens to contain one. `|` opens a substitution
    reference, and an undefined one is a build error rather than a cosmetic slip -- a
    docstring mentioning `|x|` failed the build before this, and only in table cells
    was it ever escaped.
    """
    text = (text.replace("\\", "\\\\")
                .replace("*", "\\*")
                .replace("`", "\\`")
                .replace("|", "\\|"))
    return TRAILING_UNDERSCORE.sub(r"\\_", text)


def escape_cell(text):
    """A table cell additionally cannot span lines: the row would end early."""
    return escape_inline(text).replace("\n", " ")


def heading(text, char):
    line = escape_inline(text)
    return "%s\n%s\n" % (line, char * max(len(line), 3))


def render_table(block):
    """A list-table, because a grid table has to be re-drawn whenever a cell changes."""
    lines = [".. list-table::", "   :header-rows: 1", ""]
    for row in [block["columns"]] + block["rows"]:
        for position, cell in enumerate(row):
            marker = "   * - " if position == 0 else "     - "
            value = escape_cell(str(cell)) if str(cell).strip() else "\\-"
            lines.append(marker + value)
    lines.append("")
    return "\n".join(lines)


def absolute(target):
    """A reference from the source root, not from the page that carries it.

    Sphinx resolves a relative `:doc:` target and a relative image path against the
    directory of the document they appear in. A preset whose page ids contain a
    separator therefore emits references that resolve to `architecture/architecture/...`
    and fail -- correct for a flat layout, wrong for a nested one. The leading slash
    means "from the source root" and is right for both.
    """
    return target if str(target).startswith("/") else "/" + str(target)


def render_block(block, titles):
    kind = block["type"]
    if kind == "prose":
        return escape_inline(block["text"]) + "\n"
    if kind == "table":
        return render_table(block)
    if kind == "image":
        return ".. figure:: %s\n   :alt: %s\n" % (
            absolute(block["src"]), escape_inline(block.get("alt", "")))
    if kind == "ref":
        target = block["target"]
        if target not in titles:
            # Rendering it anyway produces `:doc:` pointing at nothing -- a link that
            # looks right in the source and 404s for the reader. The model is supposed
            # to have resolved this; a renderer that papers over it hides the defect
            # until someone clicks.
            raise ValueError("block %r references page %r, which is not in this document"
                             % (block["id"], target))
        return "Next: :doc:`%s <%s>`\n" % (escape_inline(titles[target]),
                                           absolute(target))
    raise ValueError("unknown block type %r in %r" % (kind, block["id"]))


def render_page(page, titles):
    parts = [heading(page["title"], TITLE_CHAR)]
    for block in page["blocks"]:
        parts.append(render_block(block, titles))
    return "\n".join(parts).rstrip() + "\n"


def render_index(doc, pages):
    parts = [heading("Documentation", TITLE_CHAR)]
    revision = doc.get("source_revision")
    parts.append(
        "Generated from the %s preset at revision %s%s.\n"
        % (escape_inline(doc["preset"]), escape_inline(revision or "an untracked tree"),
           " (working tree had uncommitted changes)" if doc.get("source_dirty") else ""))
    parts.append(".. toctree::\n   :maxdepth: 2\n   :caption: Contents\n")
    # Every page, in the model's order. This is the check a renderer can actually make:
    # a page that exists but is not listed here is unreachable.
    parts.append("\n".join("   %s" % page["id"] for page in pages) + "\n")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", default=".docs-build/doc.json", help="the document model")
    parser.add_argument("--out", default="docs", help="directory to write pages into")
    parser.add_argument("--format", default="rst", choices=("rst",),
                        help="output markup; only rst is implemented")
    parser.add_argument("--check", action="store_true",
                        help="validate the rendered markup after writing it")
    parser.add_argument("--replace-index", action="store_true",
                        help="overwrite an existing index.rst; without this an index "
                             "already in the output directory is left as the author "
                             "wrote it")
    parser.add_argument("--diagrams", metavar="DIR",
                        help="copy this directory in as _diagrams/ and resolve figures "
                             "against it")
    args = parser.parse_args()

    if not os.path.isfile(args.doc):
        sys.stderr.write("FAIL  no such document model: %s\n" % args.doc)
        return 2
    try:
        with open(args.doc, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("FAIL  cannot read %s: %s\n" % (args.doc, exc))
        return 2
    if doc.get("format_version") not in SUPPORTED_FORMAT:
        sys.stderr.write("FAIL  %s declares format_version %r; this renderer supports %s\n"
                         % (args.doc, doc.get("format_version"), sorted(SUPPORTED_FORMAT)))
        return 2

    pages = sorted(doc.get("pages", ()), key=lambda p: p.get("order", 0))
    if not pages:
        sys.stderr.write("FAIL  the model has no pages\n")
        return 2
    titles = {page["id"]: page["title"] for page in pages}

    # Resolve before writing: a half-written docs/ directory is worse than none.
    rendered = {}
    try:
        for page in pages:
            rendered[page["id"] + ".rst"] = render_page(page, titles)
    except ValueError as exc:
        sys.stderr.write("FAIL  %s\n" % exc)
        return 2
    rendered["index.rst"] = render_index(doc, pages)

    # A figure pointing at a file that is not there renders as a broken image and
    # fails a Sphinx build with a message about the page, not about the picture. Check
    # it here, where the message can name what is missing and nothing has been written.
    wanted = [b["src"] for page in pages for b in page["blocks"] if b["type"] == "image"]
    if wanted and not args.diagrams:
        sys.stderr.write("FAIL  the model references %d figure(s) but --diagrams was "
                         "not given: %s\n" % (len(wanted), ", ".join(wanted[:3])))
        return 2
    missing = [src for src in wanted
               if not os.path.isfile(os.path.join(args.diagrams,
                                                  os.path.basename(src)))]
    if missing:
        sys.stderr.write("FAIL  %d figure(s) are not in %s: %s\n"
                         % (len(missing), args.diagrams, ", ".join(missing[:3])))
        return 2

    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    if args.diagrams:
        destination = os.path.join(args.out, "_diagrams")
        # The documented invocation is `--out docs --diagrams docs/_diagrams`, where the
        # diagrams are already where they belong. Deleting the destination first would
        # delete the source and then copy from nothing.
        already_there = (os.path.isdir(destination)
                         and os.path.realpath(destination)
                         == os.path.realpath(args.diagrams))
        if not already_there:
            if os.path.isdir(destination):
                shutil.rmtree(destination)
            shutil.copytree(args.diagrams, destination)
    # An index.rst that is already there is the author's table of contents, listing
    # pages this run knows nothing about. Replacing it silently is how a documentation
    # run deletes the navigation of the tree it was pointed at.
    kept_index = False
    if "index.rst" in rendered and os.path.isfile(os.path.join(args.out, "index.rst")) \
            and not args.replace_index:
        del rendered["index.rst"]
        kept_index = True

    for name, text in sorted(rendered.items()):
        path = os.path.join(args.out, name)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    print("wrote %d page(s) to %s" % (len(rendered), args.out))
    if kept_index:
        print("kept the existing index.rst; add these pages to its toctree yourself, "
              "or rerun with --replace-index")
    for page in doc.get("authored_pages", ()):
        print("not generated: %s.rst (%s) -- no evidence in the graph for this page"
              % (page["id"], page["title"]))

    if not args.check:
        return 0
    result = sphinx_support.check(args.out)
    print("build check: %s -- %s" % (result.status, result.detail))
    # `unwired` and `skipped` are outcomes, not failures: one means an integration step
    # has not run, the other that no builder was installed. Both are reported.
    return 1 if result.failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
