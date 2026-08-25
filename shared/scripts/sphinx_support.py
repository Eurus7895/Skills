#!/usr/bin/env python3
"""Build a rendered documentation tree and say precisely what went wrong.

    import sphinx_support
    result = sphinx_support.check(out_dir)
    print(result.status, result.detail)

Imported by the renderers; it has no command line of its own beyond a diagnostic
`python3 scripts/sphinx_support.py <dir>` that prints what a check would say.

**Six outcomes, not one.** "The build failed" is the answer least useful to whoever has
to act on it, because the four ways it fails call for four different moves:

    passed             the markup builds and every reference resolves
    unwired            the markup builds; some pages are in no toctree yet. That is
                       what an existing documentation tree looks like before the
                       generated pages are wired into its index -- an integration step
                       that has not run, not a defect in a page
    invalid_markup     a page does not parse. Fix the renderer or the content
    broken_reference   a page parses and points at something that is not there: a
                       missing document, an unresolved label, an image that is not
                       where the figure says. Fix the target or the reference
    runner_failure     the builder could not be run at all -- a crash, a timeout, a
                       permission error. Nothing was learned about the markup
    skipped            neither Sphinx nor docutils is installed, so nothing was
                       parsed. Never reported as a pass

`skipped` and `runner_failure` are kept apart on purpose. One means the check was never
possible on this machine; the other means it was possible and broke. Collapsing them
turns a broken installation into "not installed" and hides it.

**The target project's configuration is never touched.** Pages are copied into a
temporary tree and built there against a `conf.py` written for the occasion. The
documented invocation is `--out docs`, which is exactly where a project keeps its real
Sphinx configuration; a check must not be able to destroy the thing it checks.

Standard library only, plus Sphinx or docutils when they are installed.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

PASSED = "passed"
UNWIRED = "unwired"
INVALID_MARKUP = "invalid_markup"
BROKEN_REFERENCE = "broken_reference"
RUNNER_FAILURE = "runner_failure"
SKIPPED = "skipped"

# A status that means the document is not usable as it stands. `unwired` is deliberately
# absent: the pages are correct and one integration step has not run.
FAILING = (INVALID_MARKUP, BROKEN_REFERENCE, RUNNER_FAILURE)

BUILD_TIMEOUT = 300

# Sphinx tags a warning with its type only when `show_warning_types` is on, which is the
# default from Sphinx 8 and not before it. The CI matrix installs Sphinx 7 on the older
# Python and Sphinx 9 on the newer, so classifying on the tag alone works on one leg and
# silently misfiles every warning on the other. Both the tag and the wording are matched.
TOCTREE_GAP = (
    "toc.not_included",
    "isn't included in any toctree",
    "is not included in any toctree",
)

# The two majors report a failing `-W` build differently, and neither format is
# guaranteed to contain the word WARNING:
#
#   Sphinx 9   /x/orphan.rst: WARNING: document isn't included in any toctree [toc.…]
#   Sphinx 7   Warning, treated as error:
#              /x/orphan.rst:document isn't included in any toctree
#
# So the framing line is dropped and whatever remains is the warning. Filtering on the
# literal "WARNING" instead reads Sphinx 7 as a builder that failed silently.
FRAMING = ("warning, treated as error", "warnings, treated as errors")

# Sphinx uses the same shape for its own failures. These are the builder not running,
# not the document being wrong, and nothing was learned about the markup either way.
FATAL_FRAMING = ("extension error", "configuration error", "theme error",
                 "application error", "sphinx error", "exception occurred",
                 "recursion error", "traceback (most recent call last)")

REFERENCE_MARKERS = (
    "ref.doc", "ref.ref", "ref.any", "ref.python", "ref.undefined",
    "toc.not_readable", "image.not_readable", "download.not_readable",
    "unknown document", "nonexisting document", "undefined label",
    "image file not readable", "toctree contains reference to",
)


class Result(object):
    """One outcome, its explanation, and the warning lines behind it."""

    def __init__(self, status, detail, warnings=()):
        self.status = status
        self.detail = detail
        self.warnings = list(warnings)

    @property
    def failed(self):
        return self.status in FAILING

    def __repr__(self):
        return "Result(%r, %r)" % (self.status, self.detail[:60])


def _tool():
    """Which checker is available: 'sphinx', 'docutils', or None."""
    if shutil.which("sphinx-build"):
        return "sphinx"
    try:
        import docutils                                    # noqa: F401,PLC0415
    except ImportError:
        return None
    return "docutils"


def warning_lines(output):
    """The complaints in a failing build's output, in either major's format."""
    lines = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.lower().startswith(marker) for marker in FRAMING):
            continue
        lines.append(stripped)
    return lines


def classify(warnings):
    """Which outcome a set of Sphinx warnings amounts to.

    Precedence is invalid markup, then broken reference, then the toctree gap. A page
    that does not parse can produce the other two as consequences, so reporting the
    parse failure first points at the cause rather than at its symptoms.
    """
    kinds = set()
    for line in warnings:
        lowered = line.lower()
        if any(marker in lowered for marker in TOCTREE_GAP):
            kinds.add(UNWIRED)
        elif any(marker in lowered for marker in REFERENCE_MARKERS):
            kinds.add(BROKEN_REFERENCE)
        else:
            kinds.add(INVALID_MARKUP)
    for status in (INVALID_MARKUP, BROKEN_REFERENCE, UNWIRED):
        if status in kinds:
            return status
    return PASSED


def _stage(out_dir, work, extensions):
    """Copy the pages somewhere they can be built without touching the original."""
    source = os.path.join(work, "source")
    os.makedirs(source)
    for name in sorted(os.listdir(out_dir)):
        origin = os.path.join(out_dir, name)
        if os.path.isdir(origin):
            shutil.copytree(origin, os.path.join(source, name))
        elif name != "conf.py":
            shutil.copyfile(origin, os.path.join(source, name))
    settings = ["project = 'check'",
                "extensions = %r" % (list(extensions),),
                "master_doc = 'index'",
                "exclude_patterns = ['_build']"]
    with open(os.path.join(source, "conf.py"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(settings) + "\n")
    return source


def _with_sphinx(out_dir, extensions):
    work = tempfile.mkdtemp(prefix="sphinx-support-")
    try:
        source = _stage(out_dir, work, extensions)
        build = os.path.join(work, "build")
        try:
            proc = subprocess.run(
                ["sphinx-build", "-W", "-q", "-b", "html", source, build],
                capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            return Result(RUNNER_FAILURE,
                          "sphinx-build did not finish within %ds" % BUILD_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            return Result(RUNNER_FAILURE, "sphinx-build could not be run: %s" % exc)

        output = (proc.stderr or proc.stdout).strip()
        if proc.returncode == 0:
            return Result(PASSED, "sphinx-build -W reported no warnings")
        warnings = warning_lines(output)
        if any(marker in output.lower() for marker in FATAL_FRAMING):
            return Result(RUNNER_FAILURE,
                          "sphinx-build could not build: %s" % output[:800])
        if not warnings:
            # Non-zero with nothing to read is the builder itself failing, not the
            # document. Reporting it as bad markup sends the reader to the wrong file.
            return Result(RUNNER_FAILURE,
                          "sphinx-build exited %d without reporting a warning: %s"
                          % (proc.returncode, output[:400] or "no output"))
        status = classify(warnings)
        return Result(status, _explain(status, warnings), warnings)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _explain(status, warnings):
    head = "\n".join(warnings)[:1600]
    if status == UNWIRED:
        return ("the markup builds, but %d page(s) are in no toctree yet:\n%s"
                % (len(warnings), head))
    if status == BROKEN_REFERENCE:
        return "a reference does not resolve:\n%s" % head
    return "the markup does not build:\n%s" % head


def _teach_docutils_about_sphinx():
    """Stub out the Sphinx constructs the renderers emit, and only those.

    docutils has never heard of `toctree`, `:doc:` or `:ref:`, so without this it
    rejects every page this pipeline produces -- `Unknown directive type "toctree"` on
    the index of a document that is perfectly good. The fallback then fails whatever it
    is given, which is worse than not running: it accuses correct output.

    The list is deliberately short. It covers what the renderers write and nothing else,
    so a directive nobody meant to emit still comes back as an error.
    """
    from docutils import nodes                              # noqa: PLC0415
    from docutils.parsers.rst import Directive, directives, roles   # noqa: PLC0415

    class Ignored(Directive):
        has_content = True
        optional_arguments = 9
        final_argument_whitespace = True
        option_spec = {"maxdepth": directives.unchanged, "caption": directives.unchanged,
                       "hidden": directives.flag, "glob": directives.flag,
                       "titlesonly": directives.flag}

        def run(self):
            return []

    def reference(name, rawtext, text, lineno, inliner, options=None, content=None):
        return [nodes.literal(rawtext, text)], []

    directives.register_directive("toctree", Ignored)
    for role in ("doc", "ref", "any", "download"):
        roles.register_local_role(role, reference)


def _with_docutils(out_dir):
    from docutils.core import publish_doctree                # noqa: PLC0415
    from docutils.utils import SystemMessage                 # noqa: PLC0415

    _teach_docutils_about_sphinx()

    # Recursive: a preset whose page ids contain a separator writes pages into
    # subdirectories, and a flat listing parses none of them while reporting a pass.
    pages = []
    for base, _, names in os.walk(out_dir):
        pages.extend(os.path.join(base, name) for name in names if name.endswith(".rst"))

    problems = []
    for path in sorted(pages):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            publish_doctree(text, settings_overrides={
                "report_level": 2, "halt_level": 2, "warning_stream": False})
        except SystemMessage as exc:
            problems.append("%s: %s" % (os.path.relpath(path, out_dir), exc))
    if problems:
        return Result(INVALID_MARKUP, "\n".join(problems)[:1600], problems)
    return Result(PASSED, "docutils parsed %d page(s) with no warnings. This is not a "
                          "Sphinx build: cross-page references were not resolved, so a "
                          "broken one would not have been seen." % len(pages))


def check(out_dir, extensions=(), policy="optional"):
    """Build `out_dir` and report one of the six outcomes.

    `policy` is `required` when the caller insists a real build happened: with no
    builder installed that is an error rather than a skip.
    """
    if not os.path.isdir(out_dir):
        # A caller that points at nothing gets an outcome, not a traceback: this runs at
        # the end of a pipeline, and an exception here reads as the checker crashing
        # rather than as the argument being wrong.
        return Result(RUNNER_FAILURE, "nothing to check: %s is not a directory" % out_dir)
    tool = _tool()
    if tool is None:
        detail = ("neither sphinx-build nor docutils is installed; the markup was not "
                  "parsed. Install either one to validate it.")
        if policy == "required":
            return Result(RUNNER_FAILURE, detail)
        return Result(SKIPPED, detail)
    if tool == "sphinx":
        return _with_sphinx(out_dir, extensions)
    if policy == "required":
        return Result(RUNNER_FAILURE,
                      "only docutils is installed, which cannot resolve references; "
                      "a required check needs sphinx-build")
    return _with_docutils(out_dir)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: sphinx_support.py <rendered-docs-directory>\n")
        return 2
    if not os.path.isdir(sys.argv[1]):
        sys.stderr.write("FAIL  not a directory: %s\n" % sys.argv[1])
        return 2
    result = check(sys.argv[1])
    print("%s -- %s" % (result.status, result.detail))
    return 1 if result.failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
