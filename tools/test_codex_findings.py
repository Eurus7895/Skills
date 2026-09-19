#!/usr/bin/env python3
"""Regression tests for the review findings on PR #34 that had no coverage.

Each case here is a defect a reviewer found in code this repository had already tested.
They are grouped in one file because what they have in common is how they were missed: a
check written against the shape its own author assumed, rather than against the shape the
rest of the pipeline produces.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import manual
import pipeline
import render_docs
import sphinx_support
import wire_toctree

PIPELINE = os.path.join(os.path.dirname(pipeline.__file__), "pipeline.py")


class TemplateOrderTests(unittest.TestCase):
    """The documentation review is last, after the authored appendix pages too.

    Generated pages were rotated so the review came last, then every authored page was
    given a position after all of them -- which put compliance, glossary, troubleshooting,
    FAQ, references and changelog after the review, so the final review was not final.
    """

    def setUp(self):
        self.places = manual.template_order()

    def test_the_review_is_last_of_everything(self):
        last = max(self.places, key=lambda page: self.places[page])
        self.assertEqual(last, manual.REVIEW_PAGE)

    def test_every_authored_page_comes_before_the_review(self):
        for page in manual.AUTHORED:
            self.assertLess(self.places[page["id"]],
                            self.places[manual.REVIEW_PAGE], page["id"])

    def test_the_appendix_keeps_the_template_interleaving(self):
        """`appendix/output_structure` sits between `references` and `changelog`, and that
        is the intended reading order rather than an accident to be sorted away."""
        self.assertLess(self.places["appendix/references"],
                        self.places["appendix/output_structure"])
        self.assertLess(self.places["appendix/output_structure"],
                        self.places["appendix/changelog"])

    def test_every_template_page_has_exactly_one_place(self):
        self.assertEqual(len(self.places), len(manual.QUESTIONS))
        self.assertEqual(sorted(self.places.values()),
                         list(range(1, len(manual.QUESTIONS) + 1)))

    def test_getting_started_still_comes_first(self):
        first = min(self.places, key=lambda page: self.places[page])
        self.assertEqual(first, "getting_started/introduction")


class AtomicWiringTests(unittest.TestCase):
    """A refusal leaves the index exactly as it was, not half wired.

    Each `wire` wrote the file as it succeeded, so a later group with no matching caption
    left earlier groups written while the message said the index was untouched -- and
    `unwired` does not fail a build, so that incomplete navigation could reach publication
    on the strength of a claim that was false.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "docs"
        self.out.mkdir()
        # Two captioned groups; `Usage` is deliberately absent.
        self.index = self.out / "index.rst"
        self.index.write_text(
            "Docs\n====\n\n"
            ".. toctree::\n   :maxdepth: 2\n   :caption: Getting Started\n\n"
            "   getting_started/intro\n\n"
            ".. toctree::\n   :maxdepth: 2\n   :caption: Architecture\n\n"
            "   architecture/overview\n")
        self.before = self.index.read_text()

    def doc(self, page_ids):
        return {"preset": "manual", "format_version": 2, "source_revision": "abc",
                "authored_pages": [],
                "pages": [{"id": page_id, "title": page_id, "order": number,
                           "blocks": [{"id": "b%d" % number, "type": "prose",
                                       "text": "Prose."}]}
                          for number, page_id in enumerate(page_ids, 1)]}

    def test_a_group_with_no_caption_rolls_the_others_back(self):
        pages = ["getting_started/quick_start", "architecture/data_flow", "usage/invoking"]
        model = self.root / "doc.json"
        model.write_text(json.dumps(self.doc(pages)))
        result = subprocess.run(
            [sys.executable, script("render_docs.py"), "--doc", str(model),
             "--out", str(self.out), "--wire-toctree"],
            capture_output=True, text=True)
        self.assertIn("REFUSED", result.stdout + result.stderr)
        # The promise the refusal makes is one the code now keeps.
        self.assertEqual(self.index.read_text(), self.before)

    def test_it_says_so_when_it_rolled_back(self):
        pages = ["getting_started/quick_start", "usage/invoking"]
        model = self.root / "doc.json"
        model.write_text(json.dumps(self.doc(pages)))
        result = subprocess.run(
            [sys.executable, script("render_docs.py"), "--doc", str(model),
             "--out", str(self.out), "--wire-toctree"],
            capture_output=True, text=True)
        self.assertIn("rolled back", result.stdout)
        self.assertEqual(self.index.read_text(), self.before)

    def test_every_group_matching_still_wires(self):
        pages = ["getting_started/quick_start", "architecture/data_flow"]
        model = self.root / "doc.json"
        model.write_text(json.dumps(self.doc(pages)))
        result = subprocess.run(
            [sys.executable, script("render_docs.py"), "--doc", str(model),
             "--out", str(self.out), "--wire-toctree"],
            capture_output=True, text=True)
        self.assertNotIn("REFUSED", result.stdout + result.stderr)
        body = self.index.read_text()
        self.assertIn("getting_started/quick_start", body)
        self.assertIn("architecture/data_flow", body)


class ScaffoldDurabilityTests(unittest.TestCase):
    """An authored page survives the render that rebuilds the stage.

    `prepare_stage.py` deletes the staging directory and copies the source tree in again on
    every render, so a scaffold written into the stage -- and whatever an author had filled
    into it -- was destroyed by the next `document`/`render` cycle the ledger update needs.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "docs"
        self.stage = self.root / ".docs-build" / "rendered-docs"
        self.stage.mkdir(parents=True)
        self.model = self.root / "doc.json"
        self.model.write_text(json.dumps({
            "preset": "manual", "format_version": 2, "source_revision": "abc",
            "pages": [{"id": "getting_started/introduction", "title": "Introduction",
                       "order": 1, "blocks": [{"id": "b1", "type": "prose",
                                               "text": "Prose."}]}],
            "authored_pages": [{"id": "appendix/faq", "title": "FAQ", "order": 2,
                                "status": "scaffolded"}],
            "authored_ledger": [{"page_id": "appendix/faq", "status": "scaffolded",
                                 "title": "FAQ", "purpose": "Answer what users ask.",
                                 "audience": "A new user.", "questions": [],
                                 "evidence_offered": [], "evidence_absent": []}]}))

    def render(self):
        return subprocess.run(
            [sys.executable, script("render_docs.py"), "--doc", str(self.model),
             "--out", str(self.stage), "--source-docs", str(self.source)],
            capture_output=True, text=True)

    def test_the_scaffold_lands_in_the_source_tree(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.source / "appendix" / "faq.rst").is_file(),
                        "scaffold not in the durable tree")

    def test_it_is_also_staged_so_this_render_can_see_it(self):
        self.render()
        self.assertTrue((self.stage / "appendix" / "faq.rst").is_file())

    def test_an_authors_work_survives_re_staging(self):
        """The whole point: fill it in, re-stage, and it is still there."""
        self.render()
        page = self.source / "appendix" / "faq.rst"
        page.write_text("FAQ\n===\n\nWhat a person actually wrote.\n")
        prepared = subprocess.run(
            [sys.executable, script("prepare_stage.py"),
             "--source", str(self.source), "--out", str(self.stage)],
            capture_output=True, text=True)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertIn("What a person actually wrote", page.read_text())
        self.assertIn("What a person actually wrote",
                      (self.stage / "appendix" / "faq.rst").read_text())

    def test_a_filled_page_is_never_overwritten_by_a_later_render(self):
        self.render()
        page = self.source / "appendix" / "faq.rst"
        page.write_text("FAQ\n===\n\nMine.\n")
        self.render()
        self.assertEqual(page.read_text(), "FAQ\n===\n\nMine.\n")

    def test_without_source_docs_the_behaviour_is_unchanged(self):
        """Standalone use writes into --out, as it always did."""
        result = subprocess.run(
            [sys.executable, script("render_docs.py"), "--doc", str(self.model),
             "--out", str(self.stage)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.stage / "appendix" / "faq.rst").is_file())
        self.assertFalse(self.source.exists())


class BoundedCleanTests(unittest.TestCase):
    """A generated build file may not recursively delete whatever BUILDDIR points at."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "docs"
        sphinx_support.write_build_files(str(self.out))

    @staticmethod
    def recipes(body, comment):
        """The lines that actually run, with comments dropped.

        Checked rather than the whole file, because the file explains in prose why it does
        not use `rm -rf` -- and a test matching that sentence would pass on a file that
        still did.
        """
        return [line for line in body.splitlines()
                if line.strip() and not line.strip().startswith(comment)]

    def test_the_makefile_does_not_recursively_remove_builddir(self):
        body = (self.out / "Makefile").read_text()
        running = self.recipes(body, "#")
        self.assertFalse([line for line in running if "rm -rf" in line], running)
        self.assertTrue([line for line in running if "-M clean" in line])

    def test_the_batch_file_does_not_either(self):
        body = (self.out / "make.bat").read_text()
        running = self.recipes(body, "REM")
        self.assertFalse([line for line in running if "rmdir" in line], running)
        self.assertTrue([line for line in running if "-M clean" in line])


class StatusRobustnessTests(unittest.TestCase):
    """`status` answers while things are broken, which is the only reason it exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / ".docs-build"
        self.build.mkdir()
        (self.build / "structure.json").write_text(json.dumps(
            {"schema_version": 3, "index_hash": "sha256:aaa", "files": []}))

    def run_status(self):
        return subprocess.run([sys.executable, PIPELINE, "status"], cwd=str(self.root),
                              capture_output=True, text=True)

    def test_a_half_written_ledger_line_does_not_crash_it(self):
        """The ledger is edited by a person, so a partial line is an ordinary state."""
        (self.build / "authored.jsonl").write_text(
            json.dumps({"page_id": "appendix/faq", "status": "scaffolded"}) + "\n"
            + '{"page_id": "appendix/glo\n')
        result = self.run_status()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("appendix/faq", result.stdout)
        self.assertIn("could not be read", result.stdout)

    def test_every_uncomposed_page_is_counted_not_just_the_first(self):
        """`any(...)` called the run finished as soon as one page had a section."""
        (self.build / "manual-analysis.json").write_text(json.dumps(
            {"answers": {"1.1.1": {"completeness": "complete"}},
             "pages": {"getting_started/introduction": {"sections": [{"heading": "H"}]},
                       "usage/invoking": {"sections": []},
                       "usage/configuration": {"sections": []}}}))
        result = self.run_status()
        self.assertIn("2 remaining page(s)", result.stdout)

    def test_an_empty_pages_map_means_nothing_is_composed(self):
        (self.build / "manual-analysis.json").write_text(json.dumps(
            {"answers": {"1.1.1": {"completeness": "complete"}}, "pages": {}}))
        self.assertIn("compose each page", self.run_status().stdout)

    def test_p1_is_advised_before_module_work_because_it_blocks_analyze(self):
        """While P1 is open no packet can be produced, so the modules are not the step."""
        (self.build / "units.txt").write_text("src/a.py\n")
        checkpoints = self.build / "checkpoints"
        checkpoints.mkdir()
        (checkpoints / "P1.json").write_text(json.dumps(
            {"checkpoint": "P1", "state": "pending", "index_hash": "sha256:aaa",
             "show": "s", "ask": "is this the right scope"}))
        self.assertIn("decide P1", self.run_status().stdout)

    def test_p2_waits_for_the_module_analysis_it_asks_about(self):
        """`analyze` opens P2 before the roles it asks about have been written."""
        (self.build / "units.txt").write_text("src/a.py\n")
        checkpoints = self.build / "checkpoints"
        checkpoints.mkdir()
        (checkpoints / "P2.json").write_text(json.dumps(
            {"checkpoint": "P2", "state": "pending", "index_hash": "sha256:aaa",
             "show": "s", "ask": "do these roles match"}))
        out = self.run_status().stdout
        self.assertIn("write the analysis for 1 remaining module", out)
        self.assertNotIn("decide P2 (", out)


if __name__ == "__main__":
    unittest.main()
