#!/usr/bin/env python3
"""The retention floor's escape valve, and the ceiling that stops it replacing the floor."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import manual
import build_document_model as model


REASON = "This system has exactly one entry point and nothing further to explain here."
REAL = ("Pipeline.run drives one normalisation from end to end. It reads the input file, "
        "builds a Record from the shared record shape, and hands that record to put in "
        "the store, which is the only module that persists anything. A missing input file "
        "raises FileNotFoundError before any record is built, so a wrong path fails "
        "immediately rather than producing an empty result. A record carrying no key is "
        "refused by the store rather than written, and the output directory is taken from "
        "the constructor while the backend is chosen at import time.")


class ValidationTests(unittest.TestCase):
    """A malformed exception is refused rather than quietly ignored."""

    def read(self, brevity):
        return manual.read_brevity("page section 1", {"brevity": brevity})

    def test_none_means_no_exception(self):
        self.assertIsNone(manual.read_brevity("x", {}))

    def test_a_complete_exception_is_accepted(self):
        got = self.read({"reason": REASON, "reviewer": "docs@example.com"})
        self.assertEqual(got["reviewer"], "docs@example.com")
        self.assertEqual(got["reason"], REASON)

    def test_it_needs_a_reviewer(self):
        with self.assertRaises(ValueError) as caught:
            self.read({"reason": REASON})
        self.assertIn("names the reviewer", str(caught.exception))

    def test_it_needs_a_reason_not_a_label(self):
        """`Short.` says nothing about why this subject needs no more words."""
        with self.assertRaises(ValueError) as caught:
            self.read({"reason": "Short.", "reviewer": "x"})
        self.assertIn("is a label", str(caught.exception))

    def test_a_non_object_is_refused(self):
        with self.assertRaises(ValueError):
            self.read("because I said so")

    def test_the_reason_floor_is_five_words(self):
        self.assertEqual(manual.BREVITY_REASON_WORDS, 5)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text(
            "\n".join("line %d" % i for i in range(1, 201)) + "\n")
        self.index = {"schema_version": 3, "index_hash": "scan", "files": [],
                      "coverage": {}, "assets": []}

    def build(self, stub_pages=0, excused_pages=0):
        answers = manual.scaffold(self.index)
        for position, qid in enumerate(sorted(answers["answers"])):
            answers["answers"][qid].update(
                basis="inferred", completeness="complete",
                text="Reading %d of the source, distinct from every other." % position,
                evidence=[{"path": "README.md", "line_start": (position % 199) + 1,
                           "line_end": (position % 199) + 1}])
        for number, page in enumerate(manual.GENERATED):
            section = {"heading": "How a run works",
                       "body": "It works." if number < stub_pages else REAL,
                       "answers": [q["id"] for q in page["questions"]]}
            if number < excused_pages:
                section["brevity"] = {"reason": REASON, "reviewer": "docs@example.com"}
            answers["pages"][page["id"]] = {"sections": [section]}
        return model.build(self.index, [], [], "manual", analysis=model.Analysis(),
                           extra={"manual": answers, "root": str(self.root),
                                  "diagram_directory": str(self.root / "d")})

    def test_proper_prose_needs_no_exception(self):
        coverage = self.build()["manual_coverage"]
        self.assertEqual(coverage["thin_sections"], [])
        self.assertEqual(coverage["brevity_exceptions"], [])

    def test_a_stub_without_an_exception_still_holds_the_draft(self):
        coverage = self.build(stub_pages=2)["manual_coverage"]
        self.assertEqual(len(coverage["thin_sections"]), 2)

    def test_an_exception_clears_the_blocking_problem(self):
        coverage = self.build(stub_pages=2, excused_pages=2)["manual_coverage"]
        self.assertEqual(coverage["thin_sections"], [])
        self.assertEqual(len(coverage["brevity_exceptions"]), 2)

    def test_what_it_excused_is_kept_not_discarded(self):
        """An exception nobody can see afterwards is a check that was never there."""
        coverage = self.build(stub_pages=1, excused_pages=1)["manual_coverage"]
        excused = coverage["brevity_exceptions"][0]
        self.assertEqual(excused["reviewer"], "docs@example.com")
        self.assertEqual(excused["reason"], REASON)
        self.assertTrue(any("per question, floor" in line
                            for line in excused["excused"]), excused["excused"])

    def test_the_reported_figures_are_untouched_by_an_exception(self):
        """Only the blocking problem is excused. `retained` still says what happened."""
        doc = self.build(stub_pages=1, excused_pages=1)
        # `stub_pages` counts from the start of the template, whose first page is the
        # documentation review, not the introduction.
        stubbed = manual.GENERATED[0]["id"]
        page = next(p for p in doc["pages"] if p["id"] == stubbed)
        block = next(b for b in page["blocks"] if b.get("manual_block"))
        self.assertEqual(block["composition"]["body_words"], 2)
        self.assertLess(block["composition"]["words_per_answer"], 4)

    # -- the ceiling -------------------------------------------------------------

    def test_exceptions_past_the_ceiling_are_refused(self):
        """Unbounded, the override does not soften the floor -- it deletes it."""
        with self.assertRaises(ValueError) as caught:
            self.build(stub_pages=8, excused_pages=8)
        message = str(caught.exception)
        self.assertIn("ceiling", message)
        self.assertIn("one section at a time", message)

    def test_the_ceiling_is_a_quarter_of_the_sections(self):
        self.assertEqual(manual.BREVITY_LIMIT, 0.25)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_report_names_the_excused_sections(self):
        """Published under an exception is not the same as having met the floor."""
        index = {"schema_version": 3, "index_hash": "scan", "files": [], "coverage": {}}
        doc = {"preset": "manual", "pages": [], "authored_pages": [],
               "authored_ledger": [], "claims": [], "statements": [],
               "manual_coverage": {"total": 10, "answered": 10, "unresolved": [],
                                   "uncomposed": [], "sections": 2,
                                   "missing_diagrams": [], "thin_sections": [],
                                   "asserted": [],
                                   "brevity_exceptions": [
                                       {"page": "usage/invoking",
                                        "block": "section:usage/invoking:1",
                                        "reviewer": "docs@example.com",
                                        "reason": REASON, "excused": ["covers 3 in 2"]}],
                                   "prose_words": 100, "answer_words": 200,
                                   "retained": 0.5, "verified_ids_cited": {}}}
        index_path = self.root / "index.json"
        index_path.write_text(json.dumps(index))
        doc_path = self.root / "doc.json"
        doc_path.write_text(json.dumps(doc))
        out = self.root / "report.json"
        subprocess.run([sys.executable, script("quality_docs.py"),
                        "--index", str(index_path), "--doc", str(doc_path),
                        "--out", str(out)], capture_output=True, text=True)
        report = json.loads(out.read_text())
        self.assertEqual(report["manual"]["brevity_exceptions"],
                         ["section:usage/invoking:1"])
        self.assertTrue(any("brevity exception" in r for r in report["reasons"]),
                        report["reasons"])


if __name__ == "__main__":
    unittest.main()
