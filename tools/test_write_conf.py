#!/usr/bin/env python3
"""Behavioural tests for the generated conf.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Generated pages are not a document until something can build them, and a project that
has never used Sphinx has no conf.py to build them with. So this writes one. The risk in
doing that is the obvious one, and it is what most of these tests are about: a generator
that touches somebody's configuration can destroy work no rerun can restore. It writes
once, only when asked, and only when there is nothing there.

    python3 tools/test_write_conf.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")

sys.path.insert(0, SCRIPTS)
import sphinx_support                                         # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def page(page_id, title, order, text):
    return {"id": page_id, "title": title, "order": order, "mandatory": True,
            "blocks": [{"id": "block:%s" % page_id, "type": "prose", "text": text,
                        "claim_refs": []}]}


def doc_model(tmp, name="doc.json"):
    """A minimal valid document model -- this suite is about conf.py, not content."""
    doc = {"format_version": 1, "generator_version": "test", "preset": "onboarding",
           "source_revision": None, "source_dirty": True,
           "pages": [page("overview", "Overview", 1, "A repository."),
                     page("limitations", "Coverage and limitations", 2, "Very little.")],
           "authored_pages": [], "claims": [], "coverage": {}}
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    tmp = tempfile.mkdtemp(prefix="write-conf-test-")
    try:
        doc = doc_model(tmp)

        # --- The point of the feature: the output builds.
        out = os.path.join(tmp, "docs")
        code, output = run("render_docs.py", "--doc", doc, "--out", out,
                           "--write-conf", "--project", "Order Service",
                           "--author", "Eurus")
        check("rendering with --write-conf succeeds", code == 0, output)
        conf = os.path.join(out, "conf.py")
        check("a conf.py appears beside the pages", os.path.isfile(conf), output)
        check("and the run says what to do with it",
              "sphinx-build" in output, output)

        body = read(conf)
        check("it carries the project name given", "'Order Service'" in body, body)
        check("and the author", "'Eurus'" in body, body)
        check("it says it will never be regenerated",
              "leave it exactly as you leave it" in body, body)

        if shutil.which("sphinx-build"):
            build = subprocess.run(["sphinx-build", "-W", out, os.path.join(out, "_build")],
                                   capture_output=True, text=True)
            check("sphinx-build -W actually builds the generated tree",
                  build.returncode == 0, build.stdout + build.stderr)
            check("and produces the pages",
                  os.path.isfile(os.path.join(out, "_build", "overview.html")))
        else:
            print("ok   (sphinx-build absent: the build itself is not exercised here)")

        # --- The risk. An existing conf.py is somebody's work.
        mine = "# hand-written\nproject = 'Kept'\nextensions = ['myst_parser']\n"
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write(mine)
        code, output = run("render_docs.py", "--doc", doc, "--out", out, "--write-conf")
        check("a second run leaves an existing conf.py byte for byte", read(conf) == mine)
        check("and says so rather than staying silent",
              "kept the existing" in output, output)

        # --- Without the flag, nothing is written -- but the reader is told why the
        #     pages do not build yet, which is not visible from the files.
        bare = os.path.join(tmp, "bare")
        code, output = run("render_docs.py", "--doc", doc, "--out", bare)
        check("no conf.py is written without the flag",
              not os.path.isfile(os.path.join(bare, "conf.py")))
        check("but the run says the pages cannot be built until there is one",
              "cannot be built" in output, output)

        with_conf = os.path.join(tmp, "with-conf")
        os.makedirs(with_conf)
        with open(os.path.join(with_conf, "conf.py"), "w", encoding="utf-8") as fh:
            fh.write("project = 'Theirs'\nextensions = []\n")
        code, output = run("render_docs.py", "--doc", doc, "--out", with_conf)
        check("and stays quiet when the project already has one",
              "cannot be built" not in output, output)

        # --- Extensions follow the pages, not the machine.
        outcome, path = sphinx_support.write_conf(
            os.path.join(tmp, "myst"), ("myst_parser",), "P")
        check("a MyST document declares its parser", outcome == "written" and
              "'myst_parser'" in read(path), outcome)
        check("and says the parser is required, not optional",
              "required, not optional" in read(path), read(path))

        outcome, path = sphinx_support.write_conf(
            os.path.join(tmp, "uml"), ("sphinxcontrib.plantuml",), "P")
        check("a document with diagrams declares the diagram extension",
              "'sphinxcontrib.plantuml'" in read(path))
        check("and says that one is optional",
              "every page still builds" in read(path), read(path))

        # The extension list is for the reader's machine. `_resolve` is what the build
        # check uses to decide what this machine can load; a conf.py filtered through it
        # would silently drop a directive that works everywhere else.
        usable, stubbed = sphinx_support._resolve(("sphinxcontrib.plantuml",))
        check("an extension this machine cannot load is still declared",
              "'sphinxcontrib.plantuml'" in read(path),
              "usable=%r stubbed=%r" % (usable, stubbed))

        outcome, detail = sphinx_support.write_conf(os.path.join(tmp, "uml"), (), "P")
        check("write_conf reports `exists` rather than overwriting", outcome == "exists",
              "%s %s" % (outcome, detail))

        # --- The same tree, rendered twice, is the same conf.py.
        first = read(path)
        shutil.rmtree(os.path.join(tmp, "uml"))
        sphinx_support.write_conf(os.path.join(tmp, "uml"),
                                  ("sphinxcontrib.plantuml",), "P")
        check("the same inputs give the same conf.py", read(path) == first)
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
