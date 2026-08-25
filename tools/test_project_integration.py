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
                  code == 2 and "does not enable it" in output, output)
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
