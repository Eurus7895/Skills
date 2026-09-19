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
    def test_a_stubbed_directive_is_accepted_not_drawn(self):
        """The stub swallowed the source. All that is known is that it parsed."""
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), ["uml"]),
            support.ACCEPTED)

    def test_the_real_renderer_means_drawn(self):
        self.assertEqual(
            support._diagram_state(("sphinxcontrib.plantuml",), []), support.DRAWN)

    def test_a_document_wanting_no_renderer_reports_none(self):
        """Saying `accepted` here would invent a caveat about pictures that do not exist."""
        self.assertEqual(support._diagram_state(("myst_parser",), []),
                         support.NO_DIAGRAMS)
        self.assertEqual(support._diagram_state((), []), support.NO_DIAGRAMS)

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

    def test_a_failed_build_reports_no_diagram_measurement(self):
        """`-W` stops at the first error, so the renderer may never have been reached.

        Unlike the case above, this document fails on markup no version of Sphinx accepts,
        so it exercises the `invalid_markup` leg wherever a builder exists rather than
        depending on which major reports what. `drawn` here would be a measurement nobody
        took -- the build that would have taken it never finished.
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
            self.assertEqual(result.diagrams, support.UNKNOWN,
                             "%s: %s" % (result.status, result.detail[:200]))

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
        result = support.check("/nonexistent/docs/tree",
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
