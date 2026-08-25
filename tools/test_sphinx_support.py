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
