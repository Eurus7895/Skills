#!/usr/bin/env python3
"""A documentation template is the user's choice, and a document is checked against it.

Covers `document/template.py` (reading an outline, selecting sections, validating, checking
a written tree), the manual builder configured with a template other than the built-in one,
the gate judging a document by the template it carries, and the authored-page rule that a
`complete` row is a claim a page exists.

    python3 tools/test_templates.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import authored  # noqa: E402
import build_document_model as model  # noqa: E402
import manual  # noqa: E402
import quality_docs  # noqa: E402
import template  # noqa: E402

OUTLINE = """# Acme Manual

Intro prose under the title is not a section.

## Overview
- What does the product do, and for whom?
- What are its main limitations?

## Setup
### Installation (Linux)
- What must be installed first?
  Include the versions.
### Configuration
Describe every setting the product reads, with its default.

## Architecture (diagram: class)
- Which components exist?

## Changelog (authored)
- What changed in each release?

```text
## not a heading
- not a question
```
"""


def run(*args, cwd=None):
    proc = subprocess.run([sys.executable] + [str(a) for a in args], capture_output=True,
                          text=True, cwd=cwd)
    return proc.returncode, proc.stdout + proc.stderr


class OutlineTests(unittest.TestCase):
    def test_headings_become_pages_and_groups(self):
        body = template.parse_outline(OUTLINE)
        ids = [p["id"] for p in body["pages"]]
        self.assertEqual(ids, ["overview", "setup/installation_linux", "setup/configuration",
                               "architecture", "changelog"])
        self.assertEqual(body["groups"], [["setup/", "Setup"]])

    def test_questions_guidance_and_markers(self):
        pages = {p["id"]: p for p in template.parse_outline(OUTLINE)["pages"]}
        install = pages["setup/installation_linux"]
        # Ordinary parentheses stay in the title; only known markers are read.
        self.assertEqual(install["title"], "Installation (Linux)")
        self.assertEqual(install["questions"][0]["text"],
                         "What must be installed first? Include the versions.")
        self.assertEqual(pages["setup/configuration"]["questions"][0]["text"],
                         "Describe every setting the product reads, with its default.")
        self.assertEqual(pages["architecture"]["diagram"], "class")
        self.assertTrue(pages["changelog"]["authored"])
        texts = [q["text"] for p in pages.values() for q in p["questions"]]
        self.assertNotIn("not a question", texts)

    def test_a_bare_heading_still_asks_something(self):
        pages = template.parse_outline("## Running\n## Upgrading\n")["pages"]
        self.assertEqual(pages[0]["questions"][0]["text"],
                         "What does a reader need to know about Running?")

    def test_question_ids_are_unique(self):
        body = template.parse_outline(OUTLINE)
        ids = [q["id"] for p in body["pages"] for q in p["questions"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_headings_is_refused(self):
        with self.assertRaises(template.TemplateError):
            template.parse_outline("- just a list\n")

    def test_unknown_diagram_kind_is_refused(self):
        with self.assertRaises(template.TemplateError):
            template.parse_outline("## Flow (diagram: gantt)\n- What happens?\n")


class SelectionTests(unittest.TestCase):
    def test_sections_and_drop_select_from_the_builtin(self):
        record = template.resolve("manual", sections=["getting_started/", "usage/configuration"],
                                  drop=["getting_started/quick_start"])
        self.assertEqual([p["id"] for p in record["pages"]],
                         ["getting_started/introduction", "getting_started/installation",
                          "usage/configuration"])
        self.assertEqual([g[0] for g in record["groups"]], ["getting_started/", "usage/"])

    def test_an_unknown_section_is_refused(self):
        with self.assertRaises(template.TemplateError):
            template.resolve("manual", sections=["getting_started/nope"])

    def test_a_preset_takes_no_selection(self):
        self.assertEqual(template.resolve("architecture")["kind"], "preset")
        with self.assertRaises(template.TemplateError):
            template.resolve("architecture", drop=["overview"])

    def test_the_whole_builtin_hashes_like_the_default(self):
        self.assertEqual(template.resolve("manual")["template_hash"],
                         manual.TEMPLATE["template_hash"])


class ValidationTests(unittest.TestCase):
    def page(self, page_id, **extra):
        page = {"id": page_id, "title": page_id.title(),
                "questions": [{"id": page_id + ".1", "text": "What?"}]}
        page.update(extra)
        return page

    def test_structural_problems_are_named(self):
        problems = template.validate({"pages": [
            self.page("intro"), self.page("intro"), self.page("index"),
            self.page("a", diagram="class"), self.page("b", diagram="class"),
            {"id": "Bad Id", "title": "x", "questions": []}]})
        text = "\n".join(problems)
        for expected in ("used twice", "Sphinx owns", "both claim the class diagram",
                         "lowercase words", "has no questions"):
            self.assertIn(expected, text)

    def test_an_all_authored_template_is_refused(self):
        problems = template.validate({"pages": [self.page("a", authored=True)]})
        self.assertTrue(any("nothing for the run to write" in p for p in problems))

    def test_cli_refuses_a_choice_without_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "template.json")
            code, text = run(script("template.py"), "--use", "manual", "--note", "fine",
                             "--out", out)
            self.assertEqual(code, 2, text)
            self.assertFalse(os.path.exists(out))
            code, text = run(script("template.py"), "--use", "manual", "--note",
                             "the user chose the whole built-in manual", "--out", out)
            self.assertEqual(code, 0, text)
            self.assertEqual(template.load(out)["note"],
                             "the user chose the whole built-in manual")


class CheckDocsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = Path(self.tmp.name) / "docs"
        (self.docs / "setup").mkdir(parents=True)
        self.outline = Path(self.tmp.name) / "outline.md"
        self.outline.write_text(OUTLINE)
        words = " ".join(["word"] * 30)
        (self.docs / "overview.md").write_text("# Overview\n\n%s\n" % words)
        (self.docs / "setup" / "installation_linux.rst").write_text(
            "Installation\n============\n\nTODO write this.\n")
        (self.docs / "setup" / "configuration.md").write_text(
            "# Configuration\n\nShort.\n")
        # Found by its heading inside another page, not as a file of its own.
        (self.docs / "guide.md").write_text(
            "# Guide\n\n## Architecture\n\n%s\n" % words)

    def test_each_page_gets_a_verdict(self):
        record = template.resolve(str(self.outline))
        report = template.check_docs(record, self.docs)
        rows = {r["page"]: r for r in report["rows"]}
        self.assertEqual(rows["overview"]["status"], "present")
        self.assertEqual(rows["setup/installation_linux"]["status"], "incomplete")
        self.assertIn("placeholder", " ".join(rows["setup/installation_linux"]["problems"]))
        self.assertEqual(rows["setup/configuration"]["status"], "incomplete")
        self.assertEqual(rows["architecture"]["status"], "present")
        self.assertIn("found as a heading", rows["architecture"]["problems"][0])
        self.assertEqual(rows["changelog"]["status"], "missing")
        self.assertFalse(report["passed"])
        self.assertEqual(report["authored_owed"], ["changelog"])

    def test_a_copied_questionnaire_is_not_an_answer(self):
        record = template.resolve(str(self.outline))
        (self.docs / "overview.md").write_text(
            "# Overview\n\n## What does the product do, and for whom?\n\n"
            "## What are its main limitations?\n\n%s\n" % " ".join(["word"] * 30))
        rows = {r["page"]: r for r in template.check_docs(record, self.docs)["rows"]}
        self.assertIn("copied, not answered", " ".join(rows["overview"]["problems"]))

    def test_cli_exit_code_follows_the_verdict(self):
        code, text = run(script("template.py"), "--check-docs", self.docs,
                         "--template", self.outline)
        self.assertEqual(code, 1, text)
        self.assertIn("owed:", text)


class ExternalManualTests(unittest.TestCase):
    """The manual machinery, pointed at the user's outline instead of the built-in one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(model.use_template, None)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text("Install with make.\nSet MODE to fast.\n")
        outline = self.root / "outline.md"
        outline.write_text(OUTLINE)
        self.record = template.resolve(str(outline))
        self.index = {"schema_version": 3, "index_hash": "scan", "files": [], "coverage": {}}

    def answer_everything(self, draft):
        for qid, note in draft["answers"].items():
            note.update(basis="inferred", completeness="complete",
                        text="The README says how to handle question %s here." % qid,
                        evidence=[{"path": "README.md", "line_start": 1, "line_end": 2}])
        for page in manual.GENERATED:
            draft["pages"][page["id"]] = {"sections": [{
                "heading": "About %s" % page["title"],
                "body": " ".join(["Composed reader-facing prose about this subject."] * 4),
                "answers": [q["id"] for q in page["questions"]]}]}
        return draft

    def build(self, draft, ledger=()):
        return model.build(self.index, [], [], "manual", analysis=model.Analysis(),
                           extra={"manual": draft, "root": str(self.root),
                                  "diagram_directory": str(self.root / "diagrams"),
                                  "authored": list(ledger)})

    def test_the_draft_asks_the_outlines_questions(self):
        model.use_template(self.record)
        draft = manual.scaffold(self.index)
        self.assertEqual(sorted(draft["pages"]),
                         ["architecture", "overview", "setup/configuration",
                          "setup/installation_linux"])
        self.assertEqual(draft["template_hash"], self.record["template_hash"])
        self.assertEqual([row[0] for row in model.PRESETS["manual"]],
                         [p["id"] for p in self.record["pages"]])

    def test_a_manual_built_from_the_outline_validates_and_carries_it(self):
        model.use_template(self.record)
        doc = self.build(self.answer_everything(manual.scaffold(self.index)))
        self.assertEqual(model.validate(doc), [])
        # No review page in this outline, so nothing is moved to the end.
        self.assertEqual([p["id"] for p in doc["pages"]],
                         ["overview", "setup/installation_linux", "setup/configuration",
                          "architecture"])
        self.assertEqual(doc["template"]["name"], "outline")
        self.assertEqual([p["id"] for p in doc["authored_pages"]], ["changelog"])
        # The gate, reading only the document, judges it by the template it carries.
        model.use_template(None)
        model.use_template(doc["template"])
        report = quality_docs.page_report(doc)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["authored_unsettled"], ["changelog"])
        self.assertEqual(sorted(manual.DIAGRAMS), ["architecture"])

    def test_answers_to_another_template_are_refused_by_name(self):
        draft = manual.scaffold(self.index)            # drafted against the built-in
        model.use_template(self.record)
        with self.assertRaises(ValueError) as caught:
            self.build(draft)
        self.assertIn("drafted against template 'manual'", str(caught.exception))


class AuthoredCompleteTests(unittest.TestCase):
    def test_complete_names_who_wrote_it(self):
        row = {"authored_version": authored.AUTHORED_VERSION, "page_id": "appendix/faq",
               "status": "complete", "owner": None}
        with self.assertRaises(ValueError):
            authored.read_row(row, {"appendix/faq"})
        row["owner"] = "Dana"
        self.assertEqual(authored.read_row(row, {"appendix/faq"})["owner"], "Dana")

    def test_complete_without_a_written_page_is_caught(self):
        with tempfile.TemporaryDirectory() as draft:
            doc = {"authored_ledger": [
                {"page_id": "appendix/faq", "status": "complete"},
                {"page_id": "appendix/glossary", "status": "complete"},
                {"page_id": "appendix/references", "status": "complete"},
                {"page_id": "changelog", "status": "waived"}]}
            os.makedirs(os.path.join(draft, "appendix"))
            with open(os.path.join(draft, "appendix", "glossary.rst"), "w") as fh:
                fh.write("Glossary\n========\n\nDRAFT -- this page is written by a person, "
                         "not generated.\n")
            with open(os.path.join(draft, "appendix", "references.md"), "w") as fh:
                fh.write("# References\n\nThe RFCs this tool implements.\n")
            self.assertEqual(quality_docs.authored_unwritten(doc, draft),
                             ["appendix/faq", "appendix/glossary"])


class RootRelativeTests(unittest.TestCase):
    def test_build_lands_in_the_documented_repository(self):
        """Run from elsewhere, the build still belongs to --root, not to the current dir."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, elsewhere = os.path.join(tmp, "repo"), os.path.join(tmp, "elsewhere")
            os.makedirs(repo)
            os.makedirs(elsewhere)
            with open(os.path.join(repo, "app.py"), "w") as fh:
                fh.write("import os\n\n\ndef main():\n    return os.getcwd()\n")
            code, text = run(script("pipeline.py"), "survey", "--root", repo,
                             cwd=elsewhere)
            self.assertEqual(code, 0, text[-600:])
            self.assertTrue(os.path.isfile(os.path.join(repo, ".docs-build",
                                                        "structure.json")))
            self.assertFalse(os.path.exists(os.path.join(elsewhere, ".docs-build")))


if __name__ == "__main__":
    unittest.main()
