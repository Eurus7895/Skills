#!/usr/bin/env python3
"""A build that passes says nothing about whether a diagram was drawn."""
from pathlib import Path
import sys
import tempfile
import unittest

from component_scripts import component_paths
sys.path[:0] = component_paths()
import sphinx_support as support


class StateTests(unittest.TestCase):
    def test_a_finished_build_that_drew_nothing_is_accepted_not_drawn(self):
        """The source parsed and no image came of it. A stub is one way to land here."""
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 0, complete=True),
            support.ACCEPTED)

    def test_a_picture_on_disk_is_what_makes_it_drawn(self):
        """Not the extension being installed, which is what this used to read.

        `drawn` is documented as the renderer having produced an image, and the old rule
        never looked for one: an extension that loaded and drew nothing -- an absent
        renderer binary, an unreadable `.puml` -- reported `drawn` all the same.
        """
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 1, complete=True),
            support.DRAWN)

    def test_a_picture_is_drawn_even_off_an_unfinished_build(self):
        """An observation needs no completion. The file is either there or it is not."""
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 2, complete=False),
            support.DRAWN)

    def test_no_picture_and_no_completion_establishes_nothing(self):
        """`accepted` here would claim the markup parsed, and it may never have been read."""
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 0, complete=False),
            support.UNKNOWN)

    def test_a_document_wanting_no_renderer_reports_none(self):
        """Saying `accepted` here would invent a caveat about pictures that do not exist."""
        self.assertEqual(support._diagram_state(("myst_parser",), 0, complete=True),
                         support.NO_DIAGRAMS)
        self.assertEqual(support._diagram_state((), 0, complete=True),
                         support.NO_DIAGRAMS)

    def test_a_tree_with_no_diagram_in_it_reports_none_though_the_renderer_was_asked_for(
            self):
        """`render_docs` asks for the extension on every run, diagram or not.

        So this is the common case, not the edge one, and it had the worst answer of any:
        nothing consulted the pages, so a manual holding no diagram at all reported `drawn`.
        """
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 0, complete=True,
                                   has_diagram=False),
            support.NO_DIAGRAMS)

    def test_that_stays_none_on_a_build_that_never_finished(self):
        """It is a fact about the source, which is readable without building anything."""
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), 0, complete=False,
                                   has_diagram=False),
            support.NO_DIAGRAMS)

    def test_a_tree_with_no_diagram_reports_none_end_to_end(self):
        """The unit rule above, through `check`, where the pages are read for real."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "index.rst").write_text("Docs\n====\n\n.. toctree::\n\n   p\n")
            (out / "p.rst").write_text("P\n=\n\nProse and no pictures.\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            if result.status == support.SKIPPED:
                self.skipTest("no builder installed: %s" % result.detail[:120])
            self.assertEqual(result.status, support.PASSED,
                             "%s: %s" % (result.status, result.detail[:200]))
            self.assertEqual(result.diagrams, support.NO_DIAGRAMS)

    def test_a_result_defaults_to_unknown(self):
        """`none` on a check that never ran is a claim, and wrong wherever a diagram
        exists. That conflation is the whole defect being fixed."""
        self.assertEqual(support.Result(support.PASSED, "x").diagrams, support.UNKNOWN)

    def test_a_check_that_established_nothing_does_not_claim_there_are_no_diagrams(self):
        """The invariant, on a document that holds a diagram and a build that cannot run.

        An earlier version of this branched on the environment -- `SKIPPED` means
        `unknown`, anything else means a real measurement -- and CI failed it, because a
        builder being installed does not mean the build succeeded. Here the referenced
        `.puml` is deliberately absent, so nothing can be established about the picture.

        The rewrite then failed CI too, and on a real defect rather than on itself: the two
        Sphinx majors in the matrix report the missing file differently -- 9 with its own
        fatal framing, which lands on `runner_failure`, and 7 as a plain warning, which
        landed on `invalid_markup` and reported `drawn` off a build that had aborted. The
        assertion below held on the machine it was written on and named the bug on the
        other one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "page.rst").write_text("Page\n====\n\n.. uml:: absent.puml\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            self.assertNotEqual(result.diagrams, support.NO_DIAGRAMS)
            self.assertEqual(result.diagrams, support.UNKNOWN)

    def test_a_failed_build_reports_only_what_it_can_show(self):
        """A failing status is not a verdict on the pictures, in either direction.

        This document fails on markup no version of Sphinx accepts, so the `invalid_markup`
        leg runs wherever a builder exists. What that leg may report was the thing this test
        got wrong once already: it asserted `unknown`, on the theory that `-W` stops before
        the renderer is reached. That is Sphinx 7's behaviour. Sphinx 9 runs to the end and
        draws the diagram, so `drawn` there is a fact about a file that exists, and the
        assertion was false on half the matrix -- passing only because the code it tested
        was also wrong, and wrong in the same direction.

        So the invariant is one-sided, and that is all it can be: whatever is reported must
        be backed by something. A picture that exists gives `drawn`; nothing found gives
        `unknown`; `none` is never available on a document holding a `uml` directive.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "index.rst").write_text(
                "Docs\n====\n\n.. toctree::\n\n   page\n")
            (out / "page.rst").write_text(
                "Page\n====\n\n.. uml:: shape.puml\n\n.. no-such-directive::\n\n   x\n")
            (out / "shape.puml").write_text("@startuml\nclass A\n@enduml\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            if result.status == support.SKIPPED:
                self.skipTest("no builder installed: %s" % result.detail[:120])
            self.assertTrue(result.failed, "%s: %s" % (result.status, result.detail[:200]))
            self.assertNotEqual(result.diagrams, support.NO_DIAGRAMS)
            self.assertIn(result.diagrams, (support.DRAWN, support.UNKNOWN),
                          "%s: %s" % (result.diagrams, result.detail[:200]))

    def test_an_unwired_build_reports_what_was_drawn_not_what_was_wanted(self):
        """The case that showed status is not evidence about pictures.

        An orphan page makes `-W` non-zero. Sphinx 7 stops there and draws nothing; Sphinx 9
        runs to the end and draws everything. Both report `unwired`, so any rule keyed on
        the status is right on one leg of the matrix and wrong on the other -- measured here
        rather than argued: with no renderer this is `unknown`, with one that drew it is
        `drawn`, and it is never `none` on a document holding a `uml` directive.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "index.rst").write_text("Docs\n====\n\n.. toctree::\n\n   wired\n")
            (out / "wired.rst").write_text("Wired\n=====\n\n.. uml:: a.puml\n")
            (out / "orphan.rst").write_text("Orphan\n======\n\nIn no toctree.\n")
            (out / "a.puml").write_text("@startuml\nclass A\n@enduml\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            if result.status == support.SKIPPED:
                self.skipTest("no builder installed: %s" % result.detail[:120])
            self.assertEqual(result.status, support.UNWIRED,
                             "%s: %s" % (result.status, result.detail[:300]))
            self.assertNotEqual(result.diagrams, support.NO_DIAGRAMS)
            self.assertIn(result.diagrams, (support.DRAWN, support.UNKNOWN),
                          "%s: %s" % (result.diagrams, result.detail[:200]))

    def test_the_invariant_holds_with_no_builder_at_all(self):
        """The one leg that needs no Sphinx, so it is pinned on every machine.

        A check that could not run reports `unknown`. Asserting this through `check` rather
        than through a bare `Result` covers the path a reader's machine actually takes.
        """
        original = support._tool
        support._tool = lambda: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "docs"
                out.mkdir()
                (out / "page.rst").write_text("Page\n====\n\n.. uml:: shape.puml\n")
                result = support.check(str(out),
                                       extensions=("sphinxcontrib.plantuml",))
        finally:
            support._tool = original
        self.assertEqual(result.status, support.SKIPPED)
        self.assertEqual(result.diagrams, support.UNKNOWN)

    def test_a_directory_that_is_not_there_reports_unknown_too(self):
        """A runner failure is not evidence that a project has no diagrams."""
        with tempfile.TemporaryDirectory() as tmp:
            result = support.check(str(Path(tmp) / "absent"),
                                   extensions=("sphinxcontrib.plantuml",))
        self.assertEqual(result.status, support.RUNNER_FAILURE)
        self.assertEqual(result.diagrams, support.UNKNOWN)

    def test_a_build_that_succeeds_reports_a_real_state(self):
        """A complete tree, so the measurement paths are exercised where tooling exists.

        `drawn` with the PlantUML command installed, `accepted` with only the extension or
        neither, `unknown` with no builder at all. What matters is that a successful build
        never leaves this at `unknown`, and never invents `none`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "index.rst").write_text(
                "Docs\n====\n\n.. toctree::\n   :maxdepth: 2\n\n   page\n")
            (out / "page.rst").write_text(
                "Page\n====\n\nProse about the system.\n\n.. uml:: shape.puml\n")
            (out / "shape.puml").write_text("@startuml\nclass A\n@enduml\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            if result.status == support.SKIPPED:
                self.assertEqual(result.diagrams, support.UNKNOWN)
            else:
                self.assertIn(result.diagrams, (support.ACCEPTED, support.DRAWN),
                              "%s: %s" % (result.status, result.detail[:200]))
            self.assertNotEqual(result.diagrams, support.NO_DIAGRAMS)

    def test_the_status_is_unchanged_by_the_diagram_state(self):
        """A build whose markup is sound is `passed`, and stays `passed`. Whether a
        picture exists is a separate question with a separate answer."""
        result = support.Result(support.PASSED, "fine", diagrams=support.ACCEPTED)
        self.assertEqual(result.status, support.PASSED)
        self.assertFalse(result.failed)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def page(self, name, body):
        path = self.root / name
        path.write_text(body)
        return str(path)

    def test_an_rst_directive_is_found(self):
        path = self.page("a.rst", "A\n=\n\n.. uml:: d.puml\n   :caption: c\n")
        self.assertTrue(support._has_diagram([path]))

    def test_a_myst_directive_is_found(self):
        path = self.page("b.md", "# B\n\n```{uml} d.puml\n```\n")
        self.assertTrue(support._has_diagram([path]))

    def test_a_page_without_one_is_not(self):
        path = self.page("c.rst", "C\n=\n\nJust prose about the system.\n")
        self.assertFalse(support._has_diagram([path]))

    def test_an_unreadable_page_is_skipped_not_raised(self):
        self.assertFalse(support._has_diagram([str(self.root / "missing.rst")]))


if __name__ == "__main__":
    unittest.main()
