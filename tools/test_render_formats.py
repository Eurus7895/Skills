#!/usr/bin/env python3
"""Behavioural tests for the two markup emitters in render_docs.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

RST is to be retired in favour of MyST, so the thing being tested here is not really
"MyST works" but "the two formats differ only in the emitter". One `doc.json` renders in
both; the page set, the ordering and every reference are the same; only the file
extension and the markup change. If a test here starts needing to know which format it
is looking at, something format-specific has leaked above the split.

Escaping is asserted through a real build rather than by reading the source, because the
two formats disagree about which characters are dangerous and the source only shows what
the renderer already believed.

    python3 tools/test_render_formats.py
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

HAVE_SPHINX = shutil.which("sphinx-build") is not None
try:
    import myst_parser                                       # noqa: F401
    HAVE_MYST = True
except ImportError:
    HAVE_MYST = False

FAILURES = []

FORMATS = {"rst": ".rst", "myst": ".md"}

# Every one of these has a meaning in at least one of the two markups, and several have
# different meanings in each. `|x|` is a substitution in RST and a table separator in
# Markdown; `_y_` is a reference in RST and emphasis in Markdown; `<z>` is a target in
# RST and a tag in Markdown.
HOSTILE = "a*b `c` |d| \\e <f> _g_ [h] :i: **j** [1]_ ref_ {doc} 2*3*4"


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def model(pages):
    return {"format_version": 1, "generator_version": "t", "preset": "onboarding",
            "source_revision": None, "source_dirty": True, "coverage": {},
            "claims": [], "authored_pages": [], "pages": pages}


def prose(text):
    return {"id": "block:p", "type": "prose", "text": text, "claim_refs": []}


def render(tmp, doc, name, fmt, *extra):
    path = os.path.join(tmp, "%s.json" % name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    out = os.path.join(tmp, "%s-%s" % (name, fmt))
    proc = subprocess.run([sys.executable, RENDERER, "--doc", path, "--out", out,
                           "--format", fmt] + list(extra),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr, out


def pages_in(directory):
    found = set()
    for base, _, names in os.walk(directory):
        for name in names:
            stem, extension = os.path.splitext(name)
            if extension in (".rst", ".md"):
                found.add(os.path.relpath(os.path.join(base, stem), directory))
    return found


def main():
    tmp = tempfile.mkdtemp(prefix="render-formats-test-")
    try:
        doc = model([
            {"id": "overview", "title": "Overview", "order": 1, "mandatory": True,
             "blocks": [prose("plain"),
                        {"id": "block:t", "type": "table", "columns": ["Name", "Note"],
                         "rows": [["a", ""], ["b", "two\nlines"]], "claim_refs": []},
                        {"id": "block:r", "type": "ref", "target": "deep/second"}]},
            {"id": "deep/second", "title": "Second", "order": 2, "mandatory": True,
             "blocks": [prose("also plain")]},
        ])

        written = {}
        for fmt, extension in FORMATS.items():
            code, output, out = render(tmp, doc, "same", fmt)
            check("the model renders as %s" % fmt, code == 0, output)
            written[fmt] = out
            check("%s pages carry the %s extension" % (fmt, extension),
                  all(name.endswith(extension)
                      for base, _, names in os.walk(out) for name in names
                      if name.endswith((".rst", ".md"))),
                  "%r" % sorted(os.listdir(out)))

        check("both formats produce the same set of pages",
              pages_in(written["rst"]) == pages_in(written["myst"]),
              "%r vs %r" % (sorted(pages_in(written["rst"])),
                            sorted(pages_in(written["myst"]))))
        check("a nested page is nested in both",
              os.path.isfile(os.path.join(written["rst"], "deep", "second.rst"))
              and os.path.isfile(os.path.join(written["myst"], "deep", "second.md")))

        # The reference from a nested page has to leave that page's directory in either
        # markup. This is the defect A1 fixed for RST; MyST inherits the rule rather
        # than rediscovering it.
        with open(os.path.join(written["rst"], "overview.rst"), encoding="utf-8") as fh:
            check("the RST reference addresses the source root", "</deep/second>" in fh.read())
        with open(os.path.join(written["myst"], "overview.md"), encoding="utf-8") as fh:
            check("so does the MyST one", "</deep/second>" in fh.read())

        # A ref to a page that is not in the model is refused before anything is
        # written, in both formats, because that check lives above the split.
        dangling = model([{"id": "only", "title": "Only", "order": 1, "mandatory": True,
                           "blocks": [{"id": "block:r", "type": "ref",
                                       "target": "nowhere"}]}])
        for fmt in FORMATS:
            code, output, out = render(tmp, dangling, "dangling", fmt)
            check("a dangling reference is refused in %s" % fmt, code == 2, output)
            check("and nothing was written for %s" % fmt,
                  not os.path.isdir(out) or not os.listdir(out))

        if HAVE_SPHINX:
            for fmt in FORMATS:
                if fmt == "myst" and not HAVE_MYST:
                    continue
                code, output, out = render(tmp, doc, "built", fmt, "--check")
                check("a %s document builds clean" % fmt,
                      code == 0 and "build check: passed" in output, output[-300:])

                hostile = model([{"id": "overview", "title": "T " + HOSTILE, "order": 1,
                                  "mandatory": True,
                                  "blocks": [prose(HOSTILE),
                                             {"id": "block:t", "type": "table",
                                              "columns": ["c"], "rows": [[HOSTILE]],
                                              "claim_refs": []}]}])
                code, output, out = render(tmp, hostile, "hostile", fmt, "--check")
                check("%s survives markup characters in heading, prose and cell" % fmt,
                      code == 0 and "build check: passed" in output, output[-400:])
        else:
            print("skip build checks -- sphinx-build is not installed")

        if HAVE_SPHINX and HAVE_MYST:
            # The reason A5 has to inspect the target project rather than trust it.
            # Markdown pages in a project that never enabled myst_parser are files
            # Sphinx will not read: the build fails, and not because of anything in
            # them. A fixture with the extension enabled cannot show this.
            markdown = written["myst"]
            with_parser = sphinx_support.check(markdown, extensions=("myst_parser",))
            without = sphinx_support.check(markdown, extensions=())
            check("MyST pages build where the parser is enabled",
                  with_parser.status == sphinx_support.PASSED, with_parser.detail[:200])
            check("and fail where it is not, which is a configuration problem",
                  without.status != sphinx_support.PASSED, without.detail[:200])
        else:
            print("skip myst_parser checks -- sphinx-build or myst-parser is missing")

        # Keeping the author's index is a rule about the output directory, not about
        # RST. A project already holding index.md must keep it too.
        for fmt, extension in FORMATS.items():
            out = os.path.join(tmp, "kept-" + fmt)
            os.makedirs(out)
            index = os.path.join(out, "index" + extension)
            with open(index, "w", encoding="utf-8") as fh:
                fh.write("mine\n")
            path = os.path.join(tmp, "kept-%s.json" % fmt)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            subprocess.run([sys.executable, RENDERER, "--doc", path, "--out", out,
                            "--format", fmt], capture_output=True, text=True)
            with open(index, encoding="utf-8") as fh:
                check("an existing index%s is left alone" % extension,
                      fh.read() == "mine\n")
            subprocess.run([sys.executable, RENDERER, "--doc", path, "--out", out,
                            "--format", fmt, "--replace-index"],
                           capture_output=True, text=True)
            with open(index, encoding="utf-8") as fh:
                check("and --replace-index replaces it", fh.read() != "mine\n")

        # The diagram extension is optional in a way a parser is not: without it every
        # page still builds and one picture is missing, and the `.puml` beside the page
        # is the artifact either way. A project that has not enabled it yet -- or never
        # will -- must still get its documentation.
        diagrams = os.path.join(tmp, "_diagrams")
        os.makedirs(diagrams)
        with open(os.path.join(diagrams, "full-repository.puml"), "w",
                  encoding="utf-8") as fh:
            fh.write("@startuml\n@enduml\n")
        illustrated = model([
            {"id": "overview", "title": "Overview", "order": 1, "mandatory": True,
             "blocks": [prose("plain"),
                        {"id": "block:d", "type": "plantuml",
                         "src": "_diagrams/full-repository.puml",
                         "alt": "Class diagram"}]}])
        plain_project = os.path.join(tmp, "optional-rst")
        os.makedirs(plain_project)
        with open(os.path.join(plain_project, "conf.py"), "w", encoding="utf-8") as fh:
            fh.write("project = 'p'\nextensions = []\n")
        code, output, out = render(tmp, illustrated, "optional", "rst",
                                   "--diagrams", diagrams)
        check("a project without the diagram extension still gets its pages",
              code == 0 and pages_in(out) == {"overview", "index"}, output)
        check("and is told what to enable to see the picture",
              "sphinxcontrib.plantuml" in output and "WARN" in output, output)
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
