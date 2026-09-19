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
        `.puml` is deliberately absent, so `sphinx-build -W` reports `runner_failure` where
        Sphinx exists and `skipped` where it does not. Both establish nothing, both are
        `unknown`, and neither may say `none`: that would be a claim, and false on a
        document that plainly holds a `uml` directive.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            out.mkdir()
            (out / "page.rst").write_text("Page\n====\n\n.. uml:: absent.puml\n")
            result = support.check(str(out), extensions=("sphinxcontrib.plantuml",))
            self.assertNotEqual(result.diagrams, support.NO_DIAGRAMS)
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
