#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/render_docs.py
# Regenerate: python3 tools/materialize.py
"""Render doc.json to reStructuredText or MyST. The model decides what; this decides how.

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
import wire_toctree

SUPPORTED_FORMAT = {1}

# `word_` is a reference in RST and `[1]_` a footnote, and an undefined one fails the
# build. Mid-word underscores are not references, so `snake_case` -- which is most of
# what this pipeline writes -- is left alone rather than peppered with backslashes.
TRAILING_UNDERSCORE = re.compile(r"(?<=[\w\]])_(?![\w])")


def absolute(target):
    """A reference from the source root, not from the page that carries it.

    Both formats resolve a relative document target and a relative image path against
    the directory of the page they appear in. A preset whose page ids contain a
    separator therefore emits references that resolve to `architecture/architecture/...`
    and fail -- correct for a flat layout, wrong for a nested one. The leading slash
    means "from the source root" and is right for both.
    """
    return target if str(target).startswith("/") else "/" + str(target)


class Rst(object):
    """reStructuredText.

    Scheduled to be retired in favour of MyST. Everything both formats need lives
    outside these classes, so retiring it is deleting this class and one table entry.
    """

    extension = ".rst"
    build_extensions = ()

    def escape(self, text):
        """Neutralise the characters that change meaning mid-sentence.

        Backslash first, or escaping the others would be undone by the pass that
        follows. `*` opens emphasis and a lone `` ` `` opens a role; both swallow the
        rest of the line when a path or an identifier happens to contain one. `|` opens
        a substitution reference, and an undefined one is a build error rather than a
        cosmetic slip. So is `word_`, and so is `[1]_`.
        """
        text = (str(text).replace("\\", "\\\\")
                         .replace("*", "\\*")
                         .replace("`", "\\`")
                         .replace("|", "\\|"))
        return TRAILING_UNDERSCORE.sub(r"\\_", text)

    def cell(self, text):
        """A table cell additionally cannot span lines: the row would end early."""
        return self.escape(text).replace("\n", " ")

    def heading(self, text):
        line = self.escape(text)
        return "%s\n%s\n" % (line, "=" * max(len(line), 3))

    def prose(self, text):
        return self.escape(text) + "\n"

    def table(self, columns, rows):
        """A list-table, because a grid table has to be redrawn whenever a cell changes."""
        lines = [".. list-table::", "   :header-rows: 1", ""]
        for row in [columns] + rows:
            for position, value in enumerate(row):
                marker = "   * - " if position == 0 else "     - "
                text = self.cell(str(value)) if str(value).strip() else "\\-"
                lines.append(marker + text)
        lines.append("")
        return "\n".join(lines)

    def image(self, src, alt):
        return ".. figure:: %s\n   :alt: %s\n" % (absolute(src), self.escape(alt))

    def plantuml(self, src, alt):
        return ".. uml:: %s\n   :caption: %s\n" % (absolute(src), self.escape(alt))

    def ref(self, title, target):
        return "Next: :doc:`%s <%s>`\n" % (self.escape(title), absolute(target))

    def toctree(self, entries):
        return (".. toctree::\n   :maxdepth: 2\n   :caption: Contents\n\n"
                + "\n".join("   %s" % entry for entry in entries) + "\n")


class Myst(object):
    """MyST Markdown, through myst-parser.

    Sphinx will not read these pages unless the target project enables `myst_parser`,
    which is why the build check has to be told to load it and why writing MyST into a
    project that has not enabled it is a configuration error rather than a rendering
    one.
    """

    extension = ".md"
    build_extensions = ("myst_parser",)

    def escape(self, text):
        """Markdown's inline markup, plus the brace that opens a MyST role.

        Escaping the backtick is what stops a role forming, so `{doc}` in prose is
        inert once the backtick after it cannot open. `#` and `>` only matter at the
        start of a line, and prose here is emitted as one paragraph, so both are
        escaped rather than reasoned about position by position.
        """
        out = str(text).replace("\\", "\\\\")
        for char in ("`", "*", "_", "[", "]", "<", ">", "#", "|"):
            out = out.replace(char, "\\" + char)
        return out

    def cell(self, text):
        return self.escape(text).replace("\n", " ")

    def heading(self, text):
        return "# %s\n" % self.escape(text)

    def prose(self, text):
        return self.escape(text) + "\n"

    def table(self, columns, rows):
        """The same list-table, as a MyST directive.

        A pipe table would be shorter and cannot hold a cell containing a newline or a
        pipe; the directive form keeps both formats rendering the same document.
        """
        lines = ["```{list-table}", ":header-rows: 1", ""]
        for row in [columns] + rows:
            for position, value in enumerate(row):
                marker = "* - " if position == 0 else "  - "
                text = self.cell(str(value)) if str(value).strip() else "\\-"
                lines.append(marker + text)
        lines.extend(["```", ""])
        return "\n".join(lines)

    def image(self, src, alt):
        return "```{figure} %s\n:alt: %s\n```\n" % (absolute(src), self.escape(alt))

    def plantuml(self, src, alt):
        return "```{uml} %s\n:caption: %s\n```\n" % (absolute(src), self.escape(alt))

    def ref(self, title, target):
        return "Next: {doc}`%s <%s>`\n" % (self.escape(title), absolute(target))

    def toctree(self, entries):
        return ("```{toctree}\n:maxdepth: 2\n:caption: Contents\n\n"
                + "\n".join(entries) + "\n```\n")


EMITTERS = {"rst": Rst, "myst": Myst}


def render_block(block, titles, emitter):
    """One block, in whichever markup. Which blocks and in what order is not decided
    here -- that is the document model's business, and it is the same either way."""
    kind = block["type"]
    if kind == "prose":
        return emitter.prose(block["text"])
    if kind == "table":
        return emitter.table(block["columns"], block["rows"])
    if kind == "image":
        return emitter.image(block["src"], block.get("alt", ""))
    if kind == "plantuml":
        return emitter.plantuml(block["src"], block.get("alt", ""))
    if kind == "ref":
        target = block["target"]
        if target not in titles:
            # Rendering it anyway produces a link that looks right in the source and
            # 404s for the reader. The model is supposed to have resolved this; a
            # renderer that papers over it hides the defect until someone clicks.
            raise ValueError("block %r references page %r, which is not in this document"
                             % (block["id"], target))
        return emitter.ref(titles[target], target)
    raise ValueError("unknown block type %r in %r" % (kind, block["id"]))


def render_page(page, titles, emitter):
    parts = [emitter.heading(page["title"])]
    for block in page["blocks"]:
        parts.append(render_block(block, titles, emitter))
    return "\n".join(parts).rstrip() + "\n"


def render_index(doc, pages, emitter):
    revision = doc.get("source_revision")
    parts = [emitter.heading("Documentation"),
             emitter.prose(
                 "Generated from the %s preset at revision %s%s."
                 % (doc["preset"], revision or "an untracked tree",
                    " (working tree had uncommitted changes)"
                    if doc.get("source_dirty") else "")),
             # Every page, in the model's order. This is the check a renderer can
             # actually make: a page that exists but is not listed here is unreachable.
             emitter.toctree([page["id"] for page in pages])]
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", default=".docs-build/doc.json", help="the document model")
    parser.add_argument("--out", default="docs", help="directory to write pages into")
    parser.add_argument("--format", default="rst", choices=tuple(sorted(EMITTERS)),
                        help="output markup. `myst` needs the target project to enable "
                             "myst_parser; see references/presets.md")
    parser.add_argument("--check", action="store_true",
                        help="validate the rendered markup after writing it")
    parser.add_argument("--replace-index", action="store_true",
                        help="overwrite an existing index page; without this an index "
                             "already in the output directory is left as the author "
                             "wrote it")
    parser.add_argument("--assume-parser", action="store_true",
                        help="write this format even though the target conf.py does "
                             "not visibly enable its parser. For a project that builds "
                             "its extension list at run time")
    parser.add_argument("--wire-toctree", action="store_true",
                        help="add the generated pages to an index the author already "
                             "wrote. Without this the pages are written and the run "
                             "says which toctree lines are missing")
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
    emitter = EMITTERS[args.format]()
    index_name = "index" + emitter.extension

    # Resolve before writing: a half-written docs/ directory is worse than none.
    rendered = {}
    try:
        for page in pages:
            rendered[page["id"] + emitter.extension] = render_page(page, titles, emitter)
    except ValueError as exc:
        sys.stderr.write("FAIL  %s\n" % exc)
        return 2
    rendered[index_name] = render_index(doc, pages, emitter)

    # A figure pointing at a file that is not there renders as a broken image and
    # fails a Sphinx build with a message about the page, not about the picture. Check
    # it here, where the message can name what is missing and nothing has been written.
    wanted = [b["src"] for page in pages for b in page["blocks"]
              if b["type"] in ("image", "plantuml")]
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

    # A format the target project cannot read is a configuration problem, and writing
    # the pages anyway leaves a build failing over documents that are not at fault.
    has_plantuml = any(b["type"] == "plantuml" for page in pages for b in page["blocks"])
    required_extensions = emitter.build_extensions + (("sphinxcontrib.plantuml",)
                                                       if has_plantuml else ())
    blockers = sphinx_support.missing_parsers(args.out, required_extensions)
    if blockers and not args.assume_parser:
        sys.stderr.write("FAIL  %s cannot be read by the project at %s:\n"
                         % (args.format, args.out))
        for blocker in blockers:
            sys.stderr.write("        %s\n" % blocker)
        sys.stderr.write("      Enable it in conf.py, or pass --assume-parser if the "
                         "project configures extensions somewhere this cannot see.\n")
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
    # The author's index is whichever master document their project already has, and
    # that has nothing to do with the suffix being emitted now. Looking only for
    # `index.md` while a tree holds `index.rst` writes a second master document beside
    # the real one, leaves the generated pages out of the toctree anyone reads, and --
    # with both suffixes enabled -- gives Sphinx two documents called `index`.
    kept_index = False
    existing_index = None
    for candidate in ("index" + emitter.extension, "index.rst", "index.md"):
        if os.path.isfile(os.path.join(args.out, candidate)):
            existing_index = candidate
            break
    if existing_index and not args.replace_index:
        del rendered[index_name]
        kept_index = True
        index_name = existing_index

    for name, text in sorted(rendered.items()):
        path = os.path.join(args.out, name)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    print("wrote %d page(s) to %s" % (len(rendered), args.out))
    if kept_index:
        entries = [page["id"] for page in pages]
        if args.wire_toctree:
            try:
                changed, note = wire_toctree.wire(os.path.join(args.out, index_name),
                                                  entries)
            except wire_toctree.Refused as exc:
                # The index is the author's, so a refusal leaves it untouched and the
                # pages stand unwired rather than the file being guessed at.
                sys.stderr.write("REFUSED  %s\n" % exc)
                print("kept the existing %s unchanged; wire these in by hand: %s"
                      % (index_name, ", ".join(entries)))
            else:
                print(note)
        else:
            print("kept the existing %s. Add these to its toctree, or rerun with "
                  "--wire-toctree: %s" % (index_name, ", ".join(entries)))
    for page in doc.get("authored_pages", ()):
        print("not generated: %s%s (%s) -- no evidence in the graph for this page"
              % (page["id"], emitter.extension, page["title"]))

    if not args.check:
        return 0
    result = sphinx_support.check(args.out, extensions=required_extensions)
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
