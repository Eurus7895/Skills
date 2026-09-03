#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/sphinx_support.py
# Regenerate: python3 tools/materialize.py
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

import ast
import os
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


# An optional renderer that is wired up but has nothing behind it: the Python extension
# is installed, the command it shells out to is not. Sphinx reports that against the page
# holding the directive, so `-W` turns a missing tool into "this page does not build" --
# the misdiagnosis this module exists to prevent. It is the same case as the extension
# being absent altogether: the markup is fine and the picture was not drawn.
RENDERER_UNAVAILABLE = (("plantuml command", "cannot be run"),)


def renderer_advisory(line):
    """Whether a warning is an optional renderer missing, rather than a defect."""
    lowered = line.lower()
    return any(all(fragment in lowered for fragment in fragments)
               for fragments in RENDERER_UNAVAILABLE)


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


# A directive that comes from an extension the reader may never install. The `.puml`
# source is the deliverable; `sphinxcontrib-plantuml` only turns it into a picture. So a
# machine without it must still be able to check the markup: without the stub below,
# `uml` is an unknown directive, `-W` turns that into an error, and every page fails over
# a renderer that was optional all along.
OPTIONAL_DIRECTIVES = {"sphinxcontrib.plantuml": ("uml",)}

STUB_MODULE = "_optional_directives"
STUB_SOURCE = '''"""Written by sphinx_support for one check. Never part of a project."""
from docutils.parsers.rst import Directive, directives


class _Ignored(Directive):
    has_content = True
    optional_arguments = 9
    final_argument_whitespace = True
    option_spec = {"caption": directives.unchanged, "alt": directives.unchanged,
                   "align": directives.unchanged, "width": directives.unchanged,
                   "height": directives.unchanged, "scale": directives.unchanged}

    def run(self):
        return []


def setup(app):
    for name in %r:
        app.add_directive(name, _Ignored)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
'''


def _resolve(extensions):
    """Split the extensions Sphinx can load here from the directives to stub instead."""
    usable, stubbed = [], []
    for extension in extensions:
        if extension in OPTIONAL_DIRECTIVES and not parser_installed(extension):
            stubbed.extend(OPTIONAL_DIRECTIVES[extension])
        else:
            usable.append(extension)
    return usable, sorted(set(stubbed))


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
    usable, stubbed = _resolve(extensions)
    settings = ["import os, sys",
                "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))",
                "project = 'check'",
                "master_doc = 'index'",
                "exclude_patterns = ['_build']"]
    if stubbed:
        with open(os.path.join(source, STUB_MODULE + ".py"), "w", encoding="utf-8") as fh:
            fh.write(STUB_SOURCE % (list(stubbed),))
        usable = usable + [STUB_MODULE]
    settings.insert(2, "extensions = %r" % (list(usable),))
    with open(os.path.join(source, "conf.py"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(settings) + "\n")
    return source, stubbed


CONF_TEMPLATE = '''\
# Sphinx configuration.
#
# Generated once, because the pages beside it had nowhere to be built from. Nothing
# regenerates or edits this file: it is yours now, and a later documentation run will
# leave it exactly as you leave it.

project = %(project)r
author = %(author)r

extensions = %(extensions)r

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "alabaster"
%(notes)s'''

PLANTUML_NOTE = '''
# `sphinxcontrib.plantuml` renders the .puml sources under _diagrams/ as pictures. It is
# optional: without it every page still builds and the diagrams are simply not drawn. To
# turn them on, `pip install sphinxcontrib-plantuml`, make sure a `plantuml` command is
# on PATH, and point this at it if it is not found automatically:
#
#     plantuml = "plantuml"
'''

MYST_NOTE = '''
# The pages are MyST Markdown, so `myst_parser` is required, not optional: without it
# Sphinx does not read .md files at all and the build fails for a reason that has nothing
# to do with what the pages say. `pip install myst-parser`.
'''


def write_conf(out_dir, extensions=(), project="Documentation", author=""):
    """Create a `conf.py` beside the rendered pages, when there is none.

    Generated pages are not a document until something can build them, and a project
    that has never used Sphinx has no `conf.py` to build them with. So this writes one --
    once, only when asked, and only when the directory has none.

    It **never** overwrites or edits an existing file. The reason is the same one that
    makes `parser_enabled` read a `conf.py` as text rather than importing it: a
    configuration is somebody's, it can contain anything, and a generator that rewrites
    it destroys work no rerun can restore. Returns (outcome, detail) where outcome is
    `written`, `exists` or `failed`.
    """
    path = os.path.join(out_dir, "conf.py")
    if os.path.isfile(path):
        return "exists", path
    notes = ""
    if "sphinxcontrib.plantuml" in extensions:
        notes += PLANTUML_NOTE
    if "myst_parser" in extensions:
        notes += MYST_NOTE
    body = CONF_TEMPLATE % {"project": project, "author": author,
                            # Every extension the pages need, including the ones not
                            # installed here: this file is for the reader's machine, not
                            # for the one that happened to generate it.
                            "extensions": sorted(set(extensions)), "notes": notes}
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError as exc:
        return "failed", "cannot write %s: %s" % (path, exc)
    return "written", path


def _note(detail, stubbed):
    if not stubbed:
        return detail
    return ("%s. The %s directive(s) were accepted without rendering: %s is not "
            "installed here, so the diagram source was checked as markup and not drawn"
            % (detail, ", ".join("`%s`" % name for name in stubbed),
               ", ".join(sorted(OPTIONAL_DIRECTIVES))))


def _with_sphinx(out_dir, extensions):
    work = tempfile.mkdtemp(prefix="sphinx-support-")
    try:
        source, stubbed = _stage(out_dir, work, extensions)
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
            return Result(PASSED, _note("sphinx-build -W reported no warnings", stubbed))
        warnings = warning_lines(output)
        if any(marker in output.lower() for marker in FATAL_FRAMING):
            return Result(RUNNER_FAILURE,
                          "sphinx-build could not build: %s" % output[:800])
        advisories = [line for line in warnings if renderer_advisory(line)]
        warnings = [line for line in warnings if not renderer_advisory(line)]
        if advisories and not warnings:
            return Result(PASSED, _note("sphinx-build -W reported no defect", stubbed)
                          + ". A diagram was not drawn: %s" % advisories[0])
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

    `uml` joins them for the same reason one step further out: it comes from an optional
    extension, and a machine with neither Sphinx nor that extension would otherwise fail
    a page over a picture it was never going to draw.

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
    for name in sorted(set(sum((list(v) for v in OPTIONAL_DIRECTIVES.values()), []))):
        directives.register_directive(name, Ignored)
    for role in ("doc", "ref", "any", "download"):
        roles.register_local_role(role, reference)


def _with_docutils(out_dir):
    from docutils.core import publish_doctree                # noqa: PLC0415
    from docutils.utils import SystemMessage                 # noqa: PLC0415

    _teach_docutils_about_sphinx()

    # docutils reads reStructuredText and nothing else. A MyST tree has no `.rst` in it
    # at all, so the loop below would find no page, report that every page parsed, and
    # pass a document nothing had looked at. Zero pages parsed is not a pass.
    markdown = [name for _, _, names in os.walk(out_dir)
                for name in names if name.endswith(".md")]

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
    if not pages:
        return Result(SKIPPED,
                      "nothing here is reStructuredText%s, and docutils reads nothing "
                      "else. Install sphinx-build to check this tree."
                      % (" -- %d Markdown page(s) went unread" % len(markdown)
                         if markdown else ""))
    if markdown:
        return Result(SKIPPED,
                      "docutils parsed %d reStructuredText page(s) and cannot read the "
                      "%d Markdown one(s) beside them, so this is not a check of the "
                      "tree. Install sphinx-build." % (len(pages), len(markdown)))
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


def project_at(directory):
    """The project's own conf.py, or None. Read, never written."""
    path = os.path.join(directory, "conf.py")
    return path if os.path.isfile(path) else None


def parser_enabled(conf_path, extension):
    """Whether `conf.py` loads a parser extension.

    Parsed, not executed and not grepped. Importing a stranger's `conf.py` runs whatever
    it contains, and this is a read-only inspection of somebody else's project; but a
    substring search is worse than useless in the other direction -- `extensions = []
    # myst_parser intentionally disabled` would read as enabled and defeat the whole
    check. `ast` gives the literal assignment without running a line of it.

    A conf.py that builds its extension list at run time has no literal to read and
    comes back "not enabled". That is the safe direction: a diagnostic asking for
    confirmation rather than files Sphinx will not read.
    """
    try:
        with open(conf_path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "extensions" for t in targets):
            continue
        for element in ast.walk(node.value):
            if isinstance(element, ast.Constant) and element.value == extension:
                return True
    return False


def parser_installed(extension):
    try:
        __import__(extension)
    except ImportError:
        return False
    return True


def missing_parsers(directory, extensions):
    """What stands between these pages and the project they are being written into.

    Writing MyST into a project that never enabled `myst_parser` produces files Sphinx
    does not parse at all: the pages land, the toctree names them, and the build fails
    over documents it cannot read. Nothing about the pages is wrong, so the diagnostic
    has to name the configuration instead.

    **Only a project can be misconfigured.** With no `conf.py` there is nothing to be
    wrong with: rendering Markdown uses the standard library, and whoever builds the
    tree later installs what they need. Refusing on a bare directory would make the
    output format unavailable on any machine without a build-time dependency it does
    not yet need.
    """
    conf_path = project_at(directory)
    if not conf_path:
        return []
    problems = []
    for extension in extensions:
        if not parser_enabled(conf_path, extension):
            problems.append(
                "%s does not enable %s%s"
                % (os.path.relpath(conf_path, directory), extension,
                   "" if parser_installed(extension)
                   else " (and %s is not installed here either)" % extension))
    return problems


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
