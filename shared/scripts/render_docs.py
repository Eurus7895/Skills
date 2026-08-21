#!/usr/bin/env python3
"""Render doc.json to reStructuredText. The model decides what; this decides how.

    python3 scripts/render_docs.py --doc .docs-build/doc.json --out docs --check

One page per `doc.json` page, plus an `index.rst` whose toctree names every one of them
-- a page missing from the toctree is a page Sphinx warns about and nobody reads.
Headings, tables, references and escaping are this script's business and nobody else's;
an agent writing directives by hand produces markup that builds today and breaks on the
next directive it half-remembers.

--check validates the result as far as the machine allows. `sphinx-build -W` is used
when Sphinx is installed; failing that, docutils parses each page; failing both, the
check reports `skipped` and says so rather than passing quietly.

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
import shutil
import subprocess
import sys
import tempfile

SUPPORTED_FORMAT = {1}

# Underline characters by depth. Sphinx infers the hierarchy from order of first use,
# so these must stay consistent across every page in one build.
TITLE_CHAR = "="
SECTION_CHAR = "-"


def escape_inline(text):
    """Neutralise the two characters that change meaning mid-sentence in RST.

    Backslash first, or escaping the others would be undone by the pass that follows.
    `*` opens emphasis and a lone `` ` `` opens a role; both swallow the rest of the
    line when a path or an identifier happens to contain one.
    """
    return (text.replace("\\", "\\\\")
                .replace("*", "\\*")
                .replace("`", "\\`"))


def escape_cell(text):
    """Table cells additionally cannot contain the row separator or a newline."""
    return escape_inline(text).replace("|", "\\|").replace("\n", " ")


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


def render_block(block, titles):
    kind = block["type"]
    if kind == "prose":
        return escape_inline(block["text"]) + "\n"
    if kind == "table":
        return render_table(block)
    if kind == "image":
        return ".. figure:: %s\n   :alt: %s\n" % (
            block["src"], escape_inline(block.get("alt", "")))
    if kind == "ref":
        return "Next: :doc:`%s <%s>`\n" % (
            escape_inline(titles.get(block["target"], block["target"])), block["target"])
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


def check_build(out_dir):
    """Return (status, detail). status is 'passed', 'failed' or 'skipped'."""
    if shutil.which("sphinx-build"):
        work = tempfile.mkdtemp(prefix="render-docs-check-")
        try:
            # A conf.py of our own, in a temp directory: the target project's
            # configuration is never read, created or modified by this check.
            with open(os.path.join(out_dir, "conf.py"), "w", encoding="utf-8") as fh:
                fh.write("project = 'check'\nextensions = []\n"
                         "master_doc = 'index'\nexclude_patterns = ['_build']\n")
            try:
                proc = subprocess.run(
                    ["sphinx-build", "-W", "-q", "-b", "html", out_dir, work],
                    capture_output=True, text=True, timeout=300)
                if proc.returncode == 0:
                    return "passed", "sphinx-build -W reported no warnings"
                return "failed", (proc.stderr or proc.stdout).strip()[:2000]
            finally:
                os.remove(os.path.join(out_dir, "conf.py"))
        except (OSError, subprocess.SubprocessError) as exc:
            return "failed", "sphinx-build could not be run: %s" % exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

    try:
        from docutils.core import publish_doctree            # noqa: PLC0415
        from docutils.utils import SystemMessage             # noqa: PLC0415
    except ImportError:
        return "skipped", ("neither sphinx-build nor docutils is installed; the markup "
                           "was not parsed. Install either one to validate it.")

    problems = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".rst"):
            continue
        with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
            text = fh.read()
        try:
            publish_doctree(text, settings_overrides={
                "report_level": 2, "halt_level": 2, "warning_stream": False})
        except SystemMessage as exc:
            problems.append("%s: %s" % (name, exc))
    if problems:
        return "failed", "\n".join(problems)[:2000]
    return "passed", ("docutils parsed every page with no warnings. Note this is not a "
                      "Sphinx build: cross-page references were not resolved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", default=".docs-build/doc.json", help="the document model")
    parser.add_argument("--out", default="docs", help="directory to write pages into")
    parser.add_argument("--format", default="rst", choices=("rst",),
                        help="output markup; only rst is implemented")
    parser.add_argument("--check", action="store_true",
                        help="validate the rendered markup after writing it")
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

    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    for name, text in sorted(rendered.items()):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    print("wrote %d page(s) to %s" % (len(rendered), args.out))

    if not args.check:
        return 0
    status, detail = check_build(args.out)
    print("build check: %s -- %s" % (status, detail))
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
