#!/usr/bin/env python3
"""Behavioural tests for writing generated pages into somebody else's Sphinx project.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Two things here edit or refuse to edit files this pipeline did not write, so the tests
are mostly about restraint: what is left alone, what is refused, and what happens twice
without happening twice.

    python3 tools/test_project_integration.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERER = os.path.join(REPO, "shared", "scripts", "render_docs.py")
sys.path.insert(0, os.path.join(REPO, "shared", "scripts"))

import sphinx_support                                        # noqa: E402
import wire_toctree                                          # noqa: E402

HAVE_SPHINX = shutil.which("sphinx-build") is not None
try:
    import myst_parser                                       # noqa: F401
    HAVE_MYST = True
except ImportError:
    HAVE_MYST = False

FAILURES = []

RST_INDEX = """Docs
====

Intro text.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting_started/introduction
   changelog

Some trailing prose.
"""

MYST_INDEX = """# Docs

```{toctree}
:maxdepth: 2

intro
```
"""


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def model():
    return {"format_version": 1, "generator_version": "t", "preset": "onboarding",
            "source_revision": None, "source_dirty": True, "coverage": {},
            "claims": [], "authored_pages": [],
            "pages": [{"id": "overview", "title": "Overview", "order": 1,
                       "mandatory": True,
                       "blocks": [{"id": "block:p", "type": "prose", "text": "x",
                                   "claim_refs": []}]}]}


def render(doc_path, out, *extra):
    proc = subprocess.run([sys.executable, RENDERER, "--doc", doc_path, "--out", out]
                          + list(extra), capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="project-integration-test-")
    try:
        doc_path = os.path.join(tmp, "doc.json")
        with open(doc_path, "w", encoding="utf-8") as fh:
            json.dump(model(), fh)

        # -- wiring an index somebody else wrote --------------------------------
        index = write(os.path.join(tmp, "a.rst"), RST_INDEX)
        changed, note = wire_toctree.wire(index, ["arch/key", "dev/reference"])
        body = read(index)
        check("new entries join the existing toctree", changed and "arch/key" in body, note)
        check("the entries already there are kept, in order",
              body.index("getting_started/introduction") < body.index("changelog")
              < body.index("arch/key"), body)
        check("the options stay directly under the directive",
              body.index(":maxdepth: 2") < body.index("getting_started/introduction"))
        check("prose around the directive is untouched",
              "Intro text." in body and "Some trailing prose." in body)

        before = read(index)
        changed, note = wire_toctree.wire(index, ["arch/key", "dev/reference"])
        check("wiring twice is wiring once", not changed and read(index) == before, note)

        myst_index = write(os.path.join(tmp, "a.md"), MYST_INDEX)
        changed, _ = wire_toctree.wire(myst_index, ["arch/key"])
        after = read(myst_index)
        check("a MyST toctree is wired too", changed and "arch/key" in after, after)
        check("and its fence is still closed", after.rstrip().endswith("```"), after)

        # Refusals. Each of these is a file the tool does not understand well enough to
        # rewrite, and rewriting it anyway is how a generator destroys someone's index.
        refusals = {
            "no toctree at all": "Docs\n====\n\nnothing here.\n",
            "two toctrees": "D\n=\n\n.. toctree::\n\n   a\n\n.. toctree::\n\n   b\n",
            "an unclosed fence": "# D\n\n```{toctree}\n\nintro\n",
        }
        for label, text in refusals.items():
            path = write(os.path.join(tmp, "refuse.rst"), text)
            original = read(path)
            try:
                wire_toctree.wire(path, ["arch/key"])
            except wire_toctree.Refused:
                check("%s is refused" % label, True)
            else:
                check("%s is refused" % label, False, read(path))
            check("and %s leaves the file byte for byte" % label,
                  read(path) == original)

        # A directive's options must be separated from its content by a blank line.
        # Where a toctree has options and no entries yet, appending straight onto the
        # last option produces markup that no longer parses.
        optioned = write(os.path.join(tmp, "optioned.rst"),
                         "Docs\n====\n\n.. toctree::\n   :maxdepth: 2\n")
        wire_toctree.wire(optioned, ["arch/key"])
        body = read(optioned)
        check("an entry added under bare options keeps the blank line between them",
              ":maxdepth: 2\n\n   arch/key" in body, repr(body))
        if HAVE_SPHINX:
            # The proof that the separator matters: without it Sphinx rejects the file.
            project = os.path.join(tmp, "optioned-build")
            os.makedirs(project)
            write(os.path.join(project, "index.rst"),
                  "Docs\n====\n\n.. toctree::\n   :maxdepth: 2\n")
            write(os.path.join(project, "arch.rst"), "A\n=\n\nx\n")
            wire_toctree.wire(os.path.join(project, "index.rst"), ["arch"])
            result = sphinx_support.check(project)
            check("and the result actually builds",
                  result.status in (sphinx_support.PASSED, sphinx_support.UNWIRED),
                  "%s: %s" % (result.status, result.detail[:200]))

        # Reading universally and writing "\n" converts a CRLF file line by line. The
        # promise is that everything outside the entry list survives byte for byte, and
        # a whole-file diff on a Windows checkout breaks that more thoroughly than a
        # wrong entry would.
        crlf = os.path.join(tmp, "crlf.rst")
        with open(crlf, "wb") as fh:
            fh.write(b"Docs\r\n====\r\n\r\n.. toctree::\r\n\r\n   a\r\n")
        wire_toctree.wire(crlf, ["b"])
        with open(crlf, "rb") as fh:
            raw = fh.read()
        check("a CRLF index keeps its line endings",
              raw.count(b"\n") == raw.count(b"\r\n") and b"   b" in raw, repr(raw))

        missing = os.path.join(tmp, "not-there.rst")
        try:
            wire_toctree.wire(missing, ["x"])
        except wire_toctree.Refused:
            check("an index that is not there is refused, not created", True)
        else:
            check("an index that is not there is refused, not created", False)
        check("and nothing was created", not os.path.isfile(missing))

        # -- a format the project cannot read -----------------------------------
        if HAVE_MYST:
            rst_only = os.path.join(tmp, "rst-only")
            os.makedirs(rst_only)
            write(os.path.join(rst_only, "conf.py"),
                  "project = 'p'\nextensions = []\nmaster_doc = 'index'\n")
            write(os.path.join(rst_only, "index.rst"),
                  "Docs\n====\n\n.. toctree::\n\n   placeholder\n")
            write(os.path.join(rst_only, "placeholder.rst"), "P\n=\n\nx\n")
            listing = sorted(os.listdir(rst_only))

            code, output = render(doc_path, rst_only, "--format", "myst")
            check("MyST into a project that never enabled the parser is refused",
                  code == 2 and "does not enable myst_parser" in output, output)
            check("and not one page was written first",
                  sorted(os.listdir(rst_only)) == listing,
                  "%r" % sorted(os.listdir(rst_only)))

            code, output = render(doc_path, rst_only, "--format", "myst",
                                  "--assume-parser")
            check("--assume-parser is the way past it, for a conf.py built at run time",
                  code == 0, output)

            enabled = os.path.join(tmp, "myst-ok")
            os.makedirs(enabled)
            write(os.path.join(enabled, "conf.py"),
                  "project = 'p'\nextensions = ['myst_parser']\nmaster_doc = 'index'\n")
            code, output = render(doc_path, enabled, "--format", "myst")
            check("a project that does enable it is written to without ceremony",
                  code == 0, output)

            commented = os.path.join(tmp, "commented")
            os.makedirs(commented)
            write(os.path.join(commented, "conf.py"),
                  "project = 'p'\n# extensions = ['myst_parser']\nextensions = []\n")
            code, output = render(doc_path, commented, "--format", "myst")
            check("an extension only mentioned in a comment does not count",
                  code == 2, output)

            # A substring search reads the disabling comment as an enabling one, which
            # is the wrong direction for a guard: it lets the pages through. The
            # assignment is parsed instead of grepped.
            trailing = write(os.path.join(tmp, "trailing-conf.py"),
                             "extensions = []  # myst_parser intentionally disabled\n")
            check("a trailing comment naming the extension does not enable it",
                  sphinx_support.parser_enabled(trailing, "myst_parser") is False)
            listed = write(os.path.join(tmp, "listed-conf.py"),
                           "extensions = ['sphinx.ext.autodoc', 'myst_parser']\n")
            check("an extension in the list does",
                  sphinx_support.parser_enabled(listed, "myst_parser") is True)
            computed = write(os.path.join(tmp, "computed-conf.py"),
                             "exts = ['myst_parser']\nextensions = exts\n")
            check("a list built at run time reads as not enabled, which is the safe way",
                  sphinx_support.parser_enabled(computed, "myst_parser") is False)

            # Rendering Markdown uses the standard library. With no conf.py there is no
            # configuration to be wrong, so refusing would make the format unavailable
            # on any machine that has not yet installed a builder it does not need.
            installed = sphinx_support.parser_installed
            try:
                sphinx_support.parser_installed = lambda name: False
                fresh = os.path.join(tmp, "fresh-tree")
                check("a directory with no project is not gated on the parser",
                      sphinx_support.missing_parsers(fresh, ("myst_parser",)) == [])
                check("a project that does not enable it still is",
                      sphinx_support.missing_parsers(commented, ("myst_parser",)) != [])
            finally:
                sphinx_support.parser_installed = installed

            # The author's master document is whichever one their project has, and that
            # has nothing to do with the suffix being emitted. Looking only for index.md
            # writes a second master beside index.rst and leaves the generated pages out
            # of the toctree anyone reads.
            mixed = os.path.join(tmp, "mixed-index")
            os.makedirs(mixed)
            write(os.path.join(mixed, "conf.py"),
                  "project = 'p'\nextensions = ['myst_parser']\nmaster_doc = 'index'\n")
            write(os.path.join(mixed, "index.rst"),
                  "Docs\n====\n\n.. toctree::\n\n   placeholder\n")
            write(os.path.join(mixed, "placeholder.rst"), "P\n=\n\nx\n")
            code, output = render(doc_path, mixed, "--format", "myst", "--wire-toctree")
            check("MyST into a tree with index.rst writes no second index",
                  code == 0 and not os.path.isfile(os.path.join(mixed, "index.md")),
                  output)
            check("and wires itself into the index the project already had",
                  "overview" in read(os.path.join(mixed, "index.rst")),
                  read(os.path.join(mixed, "index.rst")))

            # docutils reads reStructuredText and nothing else. A MyST tree has no .rst
            # in it, so a flat "parsed every page" would be a pass over a tree nothing
            # had looked at.
            real_tool = sphinx_support._tool
            try:
                sphinx_support._tool = lambda: "docutils"
                markdown_only = os.path.join(tmp, "md-only")
                os.makedirs(markdown_only)
                write(os.path.join(markdown_only, "index.md"), "# Docs\n")
                check("a Markdown tree is skipped by the docutils fallback, not passed",
                      sphinx_support.check(markdown_only).status
                      == sphinx_support.SKIPPED)
                check("and so is a tree it can only half read",
                      sphinx_support.check(mixed).status == sphinx_support.SKIPPED)
            finally:
                sphinx_support._tool = real_tool
        else:
            print("skip parser checks -- myst-parser is not installed")

        # RST needs no extension, so none of that applies to it.
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        write(os.path.join(plain, "conf.py"), "project = 'p'\nextensions = []\n")
        code, output = render(doc_path, plain, "--format", "rst")
        check("RST is never gated on an extension", code == 0, output)

        # -- the loop the whole commit exists to close ---------------------------
        if HAVE_SPHINX:
            project = os.path.join(tmp, "project")
            os.makedirs(project)
            write(os.path.join(project, "index.rst"),
                  "Docs\n====\n\n.. toctree::\n\n   placeholder\n")
            write(os.path.join(project, "placeholder.rst"), "P\n=\n\nx\n")

            code, output = render(doc_path, project, "--check")
            check("pages land unwired, and the check says so rather than failing",
                  code == 0 and "build check: unwired" in output, output[-300:])

            code, output = render(doc_path, project, "--wire-toctree", "--check")
            check("wiring them closes it", code == 0 and "build check: passed" in output,
                  output[-300:])
            check("and the author's own page is still in the toctree",
                  "placeholder" in read(os.path.join(project, "index.rst")))
        else:
            print("skip build-loop checks -- sphinx-build is not installed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
