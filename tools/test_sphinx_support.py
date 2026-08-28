#!/usr/bin/env python3
"""Behavioural tests for sphinx_support.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Every outcome is produced by causing it rather than by asserting a mapping: a page in no
toctree, a reference to a document that is not there, a directive nobody defined. The
classifier is tested separately against warning text, because the two Sphinx majors CI
installs word the same warning differently and only one of them tags it.

    python3 tools/test_sphinx_support.py
"""

import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "shared", "scripts"))

import sphinx_support                                        # noqa: E402

HAVE_SPHINX = shutil.which("sphinx-build") is not None
try:
    import docutils                                          # noqa: F401
    HAVE_DOCUTILS = True
except ImportError:
    HAVE_DOCUTILS = False

FAILURES = []

INDEX = "Docs\n====\n\n.. toctree::\n\n   a\n"


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def tree(root, name, files):
    where = os.path.join(root, name)
    for path, body in files.items():
        full = os.path.join(where, path)
        os.makedirs(os.path.dirname(full) or where, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(body)
    return where


def main():
    tmp = tempfile.mkdtemp(prefix="sphinx-support-test-")
    try:
        good = {"index.rst": INDEX, "a.rst": "A\n=\n\nfine\n"}
        cases = {
            "passed": good,
            "unwired": dict(good, **{"orphan.rst": "B\n=\n\nnobody links here\n"}),
            "broken_reference": {"index.rst": INDEX,
                                 "a.rst": "A\n=\n\n:doc:`/nowhere`\n"},
            "invalid_markup": {"index.rst": INDEX,
                               "a.rst": "A\n=\n\n.. nosuchdirective::\n\n   x\n"},
        }

        if HAVE_SPHINX:
            for expected, files in cases.items():
                result = sphinx_support.check(tree(tmp, expected, files))
                check("a real build reports %s" % expected,
                      result.status == expected, "%r: %s" % (result.status,
                                                             result.detail[:160]))
            # The distinction the whole module exists for: two of these are defects and
            # two are not, and before this they were all "failed".
            check("only the two real defects fail the run",
                  sphinx_support.Result("unwired", "").failed is False
                  and sphinx_support.Result("skipped", "").failed is False
                  and sphinx_support.Result("invalid_markup", "").failed is True
                  and sphinx_support.Result("broken_reference", "").failed is True)
        else:
            print("skip real-build checks -- sphinx-build is not installed")

        # Sphinx tags a warning with its type only when show_warning_types is on, which
        # is the default from Sphinx 8 and not before. CI installs Sphinx 7 on the older
        # Python leg and Sphinx 9 on the newer, so matching the tag alone classifies
        # correctly on one leg and misfiles every warning on the other.
        untagged = ["/x/b.rst: WARNING: document isn't included in any toctree"]
        tagged = ["/x/b.rst: WARNING: document isn't included in any toctree "
                  "[toc.not_included]"]
        check("the toctree gap is recognised without the warning-type tag",
              sphinx_support.classify(untagged) == sphinx_support.UNWIRED)
        check("and with it", sphinx_support.classify(tagged) == sphinx_support.UNWIRED)
        check("an unresolved reference is not called bad markup",
              sphinx_support.classify(["WARNING: unknown document: 'nope' [ref.doc]"])
              == sphinx_support.BROKEN_REFERENCE)
        check("a page that will not parse outranks the gap it causes",
              sphinx_support.classify(untagged + ["WARNING: Title underline too short"])
              == sphinx_support.INVALID_MARKUP)
        check("no warnings at all is a pass",
              sphinx_support.classify([]) == sphinx_support.PASSED)

        # The two majors do not agree on the shape of a failing -W build, and Sphinx 7's
        # does not contain the word WARNING anywhere. Filtering on that token reads it as
        # a builder that failed silently -- which is what CI reported before this.
        sphinx7 = ("Warning, treated as error:\n"
                   "/x/orphan.rst:document isn't included in any toctree")
        sphinx9 = ("/x/orphan.rst: WARNING: document isn't included in any toctree "
                   "[toc.not_included]")
        for label, output in (("7", sphinx7), ("9", sphinx9)):
            lines = sphinx_support.warning_lines(output)
            check("a Sphinx %s failure yields its warning, not silence" % label,
                  len(lines) == 1 and "toctree" in lines[0], "%r" % lines)
            check("and Sphinx %s's toctree gap classifies as unwired" % label,
                  sphinx_support.classify(lines) == sphinx_support.UNWIRED)

        # Sphinx reports its own breakage in the same shape as a warning. Reading
        # "Could not import extension" as bad markup sends the reader to a page that is
        # fine.
        for fatal in ("Extension error:\nCould not import extension nope",
                      "Configuration error:\nconf.py is unreadable"):
            check("%r is the builder failing, not the document"
                  % fatal.splitlines()[0],
                  any(marker in fatal.lower()
                      for marker in sphinx_support.FATAL_FRAMING))

        # A missing builder and a broken one are different answers. Collapsing them
        # turns a broken installation into "not installed" and hides it.
        real = sphinx_support._tool
        try:
            sphinx_support._tool = lambda: None
            check("no builder is skipped, not passed",
                  sphinx_support.check(tree(tmp, "nb", good)).status
                  == sphinx_support.SKIPPED)
            check("and under --policy required it is a runner failure",
                  sphinx_support.check(tree(tmp, "nb", good),
                                       policy="required").status
                  == sphinx_support.RUNNER_FAILURE)
            sphinx_support._tool = lambda: "docutils"
            check("docutils cannot satisfy a required check either",
                  sphinx_support.check(tree(tmp, "nb", good),
                                       policy="required").status
                  == sphinx_support.RUNNER_FAILURE)
        finally:
            sphinx_support._tool = real

        if HAVE_DOCUTILS:
            # docutils has never heard of `toctree` or `:doc:`, so without the stubs it
            # rejects every page this pipeline produces -- accusing correct output,
            # which is worse than not running at all.
            fallback = sphinx_support._with_docutils(tree(tmp, "fb", good))
            check("the docutils fallback accepts the pipeline's own markup",
                  fallback.status == sphinx_support.PASSED, fallback.detail[:200])
            broken = sphinx_support._with_docutils(
                tree(tmp, "fbbad", cases["invalid_markup"]))
            check("and still rejects a directive nobody defined",
                  broken.status == sphinx_support.INVALID_MARKUP, broken.detail[:200])
            nested = sphinx_support._with_docutils(tree(tmp, "fbnest", {
                "index.rst": INDEX,
                "deep/a.rst": "A\n=\n\n.. alsonotreal::\n\n   x\n"}))
            check("and reaches pages in subdirectories",
                  nested.status == sphinx_support.INVALID_MARKUP, nested.detail[:200])
        else:
            print("skip docutils fallback checks -- docutils is not installed")

        # `uml` comes from an optional extension. Whether or not it is installed, a page
        # carrying it has to come back as good markup: with the extension Sphinx draws
        # the diagram, without it the directive is accepted and nothing is drawn. The one
        # answer that must never appear is "this page does not parse".
        usable, stubbed = sphinx_support._resolve(("myst_parser",
                                                   "sphinxcontrib.plantuml"))
        installed = sphinx_support.parser_installed("sphinxcontrib.plantuml")
        check("an installed optional extension is loaded, a missing one is stubbed",
              ("sphinxcontrib.plantuml" in usable) == installed
              and (stubbed == [] if installed else stubbed == ["uml"]),
              "%r / %r (installed=%r)" % (usable, stubbed, installed))
        illustrated = {"index.rst": INDEX,
                       "a.rst": "A\n=\n\n.. uml:: full-repository.puml\n"
                                "   :caption: Class diagram\n",
                       "full-repository.puml": "@startuml\nclass A\n@enduml\n"}
        if HAVE_SPHINX:
            result = sphinx_support.check(tree(tmp, "uml", illustrated),
                                          extensions=("sphinxcontrib.plantuml",))
            check("a diagram directive builds whether or not its extension is there",
                  result.status == sphinx_support.PASSED,
                  "%r: %s" % (result.status, result.detail[:200]))
        if HAVE_DOCUTILS:
            fallback = sphinx_support._with_docutils(tree(tmp, "umlfb", illustrated))
            check("and the docutils fallback does not reject it either",
                  fallback.status == sphinx_support.PASSED, fallback.detail[:200])

        # The extension installed with no working command behind it. Sphinx reports that
        # against the page holding the directive, so without this it reads as "the page
        # does not build" -- blaming markup for a tool nobody installed.
        unavailable = ("/x/overview.rst:: WARNING: plantuml command 'plantuml' "
                       "cannot be run [plantuml]")
        check("a renderer with nothing behind it is not a markup defect",
              sphinx_support.renderer_advisory(unavailable)
              and not sphinx_support.renderer_advisory(
                  "a.rst:3: WARNING: Unknown directive type \"nosuch\""),
              unavailable)
        check("and on its own it would otherwise have been called invalid markup",
              sphinx_support.classify([unavailable]) == sphinx_support.INVALID_MARKUP)

        result = sphinx_support.check(os.path.join(tmp, "not-a-directory"))
        check("a directory that is not there does not pass",
              result.status != sphinx_support.PASSED, "%r" % result.status)
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
