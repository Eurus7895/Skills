#!/usr/bin/env python3
"""`asserted`: the one basis with no evidence, and the two things that keep it honest."""
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
import render_docs


REAL = ("Pipeline.run drives one normalisation from end to end. It reads the input file, "
        "builds a Record from the shared record shape, and hands that record to put in "
        "the store, which is the only module that persists anything. A missing input file "
        "raises FileNotFoundError before any record is built, so a wrong path fails "
        "immediately rather than producing an empty result. A record carrying no key is "
        "refused by the store rather than written, and the output directory is taken from "
        "the constructor while the backend is chosen at import time.")


class AnswerTests(unittest.TestCase):
    """What `read_answer` will and will not accept for the new basis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text("a\nb\nc\n")
        self.origins = {"claim:verified": "claim"}

    def answer(self, **kw):
        base = {"basis": "asserted", "completeness": "complete",
                "text": "An RTE option is a switch passed to the generator.",
                "evidence": [], "verified_ids": [], "facets_missing": []}
        base.update(kw)
        return base

    def read(self, **kw):
        return manual.read_answer("5.2.2", self.answer(**kw), self.root, self.origins)

    def test_it_needs_no_evidence(self):
        """The point of it. A definition has no file:line anywhere in any repository."""
        note = self.read(reviewer="docs@example.com")
        self.assertEqual(note["basis"], "asserted")
        self.assertEqual(note["evidence"], [])

    def test_it_is_composable(self):
        """Without this the content still could not reach a page, which was the problem."""
        self.assertTrue(manual.composable(self.read(reviewer="docs@example.com")))

    def test_it_may_not_be_anonymous(self):
        """It is the one answer a reader cannot check, so it is the one that needs a name."""
        with self.assertRaises(ValueError) as caught:
            self.read()
        self.assertIn("stands behind it", str(caught.exception))

    def test_it_may_not_name_a_verified_id(self):
        """An id a validator passed is evidence; an answer holding one is not an assertion."""
        with self.assertRaises(ValueError) as caught:
            self.read(reviewer="x", verified_ids=["claim:verified"])
        self.assertIn("not an assertion", str(caught.exception))

    def test_the_other_bases_still_require_evidence(self):
        """The boundary moved for one basis, not for all of them."""
        for basis in ("observed", "declared", "inferred"):
            with self.assertRaises(ValueError) as caught:
                self.read(basis=basis, reviewer="x", verified_ids=[])
            self.assertIn("requires repository evidence", str(caught.exception), basis)

    def test_the_refusal_points_at_the_new_basis(self):
        """A writer hitting the evidence rule should learn what to do instead."""
        with self.assertRaises(ValueError) as caught:
            self.read(basis="inferred")
        self.assertIn("`asserted`", str(caught.exception))


class SectionTests(unittest.TestCase):
    """How an assertion travels into a composed section."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text(
            "\n".join("line %d" % i for i in range(1, 201)) + "\n")
        self.index = {"schema_version": 3, "index_hash": "scan", "files": [],
                      "coverage": {}, "assets": []}

    def build(self, asserted_ids=(), body=REAL):
        answers = manual.scaffold(self.index)
        for position, qid in enumerate(sorted(answers["answers"])):
            if qid in asserted_ids:
                answers["answers"][qid].update(
                    basis="asserted", completeness="complete",
                    text="Stated from experience, not from the code, number %d." % position,
                    evidence=[], verified_ids=[], reviewer="docs@example.com")
            else:
                answers["answers"][qid].update(
                    basis="inferred", completeness="complete",
                    text="Reading %d of the source, distinct from every other." % position,
                    evidence=[{"path": "README.md",
                               "line_start": (position % 199) + 1,
                               "line_end": (position % 199) + 1}])
        for page in manual.GENERATED:
            answers["pages"][page["id"]] = {"sections": [
                {"heading": "How a run works", "body": body,
                 "answers": [q["id"] for q in page["questions"]]}]}
        return model.build(self.index, [], [], "manual", analysis=model.Analysis(),
                           extra={"manual": answers, "root": str(self.root),
                                  "diagram_directory": str(self.root / "d")})

    def first_block(self, doc, page_id="getting_started/introduction"):
        page = next(p for p in doc["pages"] if p["id"] == page_id)
        return next(b for b in page["blocks"] if b.get("manual_block"))

    def test_one_assertion_makes_the_section_asserted(self):
        """It outranks `inferred`: it is the only basis with nothing cited under it."""
        doc = self.build(asserted_ids={"1.1.1"})
        self.assertEqual(self.first_block(doc)["answer_basis"], "asserted")

    def test_a_section_with_no_assertion_is_unaffected(self):
        doc = self.build()
        self.assertEqual(self.first_block(doc)["answer_basis"], "inferred")

    def test_the_reader_is_told_and_by_whom(self):
        """Not the `Inferred:` label that was removed -- that was prose a reader could
        check. Here there is nothing to check, so the name is the only provenance."""
        doc = self.build(asserted_ids={"1.1.1"})
        titles = {p["id"]: p["title"] for p in doc["pages"]}
        page = next(p for p in doc["pages"]
                    if p["id"] == "getting_started/introduction")
        rendered = render_docs.render_page(page, titles, render_docs.Rst())
        self.assertIn("Not documented in the source", rendered)
        self.assertIn("docs@example.com", rendered)

    def test_an_evidenced_section_carries_no_such_line(self):
        doc = self.build()
        titles = {p["id"]: p["title"] for p in doc["pages"]}
        page = next(p for p in doc["pages"]
                    if p["id"] == "getting_started/introduction")
        rendered = render_docs.render_page(page, titles, render_docs.Rst())
        self.assertNotIn("Not documented in the source", rendered)

    # -- the ceiling -------------------------------------------------------------

    def test_a_minority_of_assertions_builds(self):
        ids = sorted(manual.scaffold(self.index)["answers"])
        doc = self.build(asserted_ids=set(ids[:int(len(ids) * 0.15)]))
        coverage = doc["manual_coverage"]
        self.assertEqual(len(coverage["asserted"]), int(len(ids) * 0.15))
        self.assertEqual(coverage["answered"], len(ids))

    def test_a_manual_leaning_on_assertions_is_refused(self):
        """Without the ceiling this basis becomes the answer to every hard question."""
        ids = sorted(manual.scaffold(self.index)["answers"])
        with self.assertRaises(ValueError) as caught:
            self.build(asserted_ids=set(ids[:int(len(ids) * 0.30)]))
        message = str(caught.exception)
        self.assertIn("ceiling", message)
        self.assertIn("not documenting this repository", message)

    def test_the_ceiling_is_a_fifth(self):
        self.assertEqual(manual.ASSERTED_LIMIT, 0.20)


class GateTests(unittest.TestCase):
    """The count reaches the report even when it is under the ceiling."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_report_names_the_assertions(self):
        index = {"schema_version": 3, "index_hash": "scan", "files": [], "coverage": {}}
        doc = {"preset": "manual", "pages": [], "authored_pages": [],
               "authored_ledger": [], "claims": [], "statements": [],
               "manual_coverage": {"total": 10, "answered": 10, "unresolved": [],
                                   "uncomposed": [], "sections": 2,
                                   "missing_diagrams": [], "thin_sections": [],
                                   "asserted": ["5.2.1", "5.2.2"],
                                   "brevity_exceptions": [],
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
        self.assertEqual(report["manual"]["asserted"], 2)
        self.assertTrue(any("asserted answer(s)" in r for r in report["reasons"]),
                        report["reasons"])


if __name__ == "__main__":
    unittest.main()
