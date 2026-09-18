#!/usr/bin/env python3
"""A tree can be wrong while every page in it is right."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import release_hygiene as hygiene


class HygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        subprocess.run(["git", "init", "-q", "."], cwd=str(self.root),
                       capture_output=True)

    def sound(self):
        (self.docs / "index.rst").write_text("Docs\n====\n")
        (self.docs / "conf.py").write_text("project = 'x'\n")

    def codes(self, **kwargs):
        return [f["code"] for f in hygiene.check(str(self.docs), str(self.root), **kwargs)]

    def add(self, *paths):
        subprocess.run(["git", "add", "-A"], cwd=str(self.root), capture_output=True)

    # -- the clean case ----------------------------------------------------------

    def test_a_sound_tree_has_no_findings(self):
        self.sound()
        self.assertEqual(self.codes(), [])

    def test_an_ignored_build_directory_is_fine(self):
        self.sound()
        (self.root / ".gitignore").write_text("docs/_build/\n")
        (self.docs / "_build").mkdir()
        (self.docs / "_build" / "page.html").write_text("<html></html>")
        self.assertEqual(self.codes(), [])

    # -- one entry point, one configuration --------------------------------------

    def test_no_index_is_reported(self):
        (self.docs / "conf.py").write_text("project = 'x'\n")
        self.assertIn("H001", self.codes())

    def test_two_indexes_are_reported(self):
        """A reader lands on one and the pipeline maintains the other."""
        self.sound()
        (self.docs / "nested").mkdir()
        (self.docs / "nested" / "index.rst").write_text("Other\n=====\n")
        self.assertIn("H002", self.codes())

    def test_two_configurations_are_reported(self):
        self.sound()
        (self.docs / "nested").mkdir()
        (self.docs / "nested" / "conf.py").write_text("project = 'y'\n")
        self.assertIn("H003", self.codes())

    # -- output where it does not belong -----------------------------------------

    def test_committed_build_output_is_reported(self):
        self.sound()
        (self.docs / "_build").mkdir()
        (self.docs / "_build" / "page.html").write_text("<html></html>")
        self.add()
        self.assertIn("H004", self.codes())

    def test_build_output_neither_committed_nor_ignored_is_reported(self):
        """It will be committed by the first `git add -A`."""
        self.sound()
        (self.docs / "_build").mkdir()
        (self.docs / "_build" / "page.html").write_text("<html></html>")
        self.assertIn("H005", self.codes())

    def test_a_build_directory_is_found_by_its_marker_not_only_its_name(self):
        """`environment.pickle` means output whatever the directory is called."""
        self.sound()
        (self.docs / "out").mkdir()
        (self.docs / "out" / "environment.pickle").write_text("x")
        self.assertTrue(set(self.codes()) & {"H004", "H005"}, self.codes())

    def test_generated_html_in_the_source_tree_is_reported(self):
        self.sound()
        (self.docs / "leaked.html").write_text("<html></html>")
        self.assertIn("H006", self.codes())

    def test_output_inside_the_build_tree_is_not_reported_as_leaked(self):
        """That is where output belongs."""
        self.sound()
        (self.root / ".gitignore").write_text("docs/_build/\n")
        (self.docs / "_build" / "html").mkdir(parents=True)
        (self.docs / "_build" / "html" / "page.html").write_text("<html></html>")
        self.assertNotIn("H006", self.codes())

    def test_a_nested_build_directory_is_still_found(self):
        """The one a shallow check misses is the point of walking the whole tree."""
        self.sound()
        (self.docs / "a" / "b" / "_build").mkdir(parents=True)
        (self.docs / "a" / "b" / "_build" / "p.html").write_text("<html></html>")
        self.assertTrue(set(self.codes()) & {"H004", "H005"}, self.codes())

    # -- the model against the tree ----------------------------------------------

    def test_a_page_the_model_names_that_is_not_on_disk_is_reported(self):
        self.sound()
        self.assertIn("H007", self.codes(expected_pages=["usage/invoking"]))

    def test_a_page_that_is_on_disk_is_not(self):
        self.sound()
        (self.docs / "usage").mkdir()
        (self.docs / "usage" / "invoking.rst").write_text("Invoking\n========\n")
        self.assertNotIn("H007", self.codes(expected_pages=["usage/invoking"]))

    def test_a_markdown_page_counts_too(self):
        self.sound()
        (self.docs / "usage").mkdir()
        (self.docs / "usage" / "invoking.md").write_text("# Invoking\n")
        self.assertNotIn("H007", self.codes(expected_pages=["usage/invoking"]))

    # -- the command and the gate ------------------------------------------------

    def test_the_command_exits_one_on_findings_and_zero_when_clean(self):
        self.sound()
        out = self.root / "hygiene.json"
        clean = subprocess.run(
            [sys.executable, script("release_hygiene.py"), "--docs", str(self.docs),
             "--root", str(self.root), "--out", str(out)],
            capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertTrue(json.loads(out.read_text())["passed"])

        (self.docs / "leaked.html").write_text("<html></html>")
        dirty = subprocess.run(
            [sys.executable, script("release_hygiene.py"), "--docs", str(self.docs),
             "--root", str(self.root), "--out", str(out)],
            capture_output=True, text=True)
        self.assertEqual(dirty.returncode, 1)
        self.assertIn("H006", dirty.stderr)
        self.assertFalse(json.loads(out.read_text())["passed"])

    def test_a_missing_docs_directory_is_input_error_not_a_crash(self):
        result = subprocess.run(
            [sys.executable, script("release_hygiene.py"), "--docs",
             str(self.root / "nope")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_the_gate_fails_on_hygiene_findings(self):
        index = self.root / "index.json"
        index.write_text(json.dumps({"schema_version": 3, "index_hash": "h",
                                     "files": [], "coverage": {}}))
        report = self.root / "hygiene.json"
        report.write_text(json.dumps(
            {"hygiene_version": 1, "docs": "docs", "passed": False,
             "findings": [{"code": "H002", "message": "2 index pages", "path": "docs"}]}))
        out = self.root / "gen.json"
        subprocess.run([sys.executable, script("quality_docs.py"), "--index", str(index),
                        "--hygiene", str(report), "--out", str(out)],
                       capture_output=True, text=True)
        gate = json.loads(out.read_text())
        self.assertEqual(gate["status"], "failed")
        self.assertTrue(any("hygiene problem" in r for r in gate["reasons"]),
                        gate["reasons"])
        self.assertEqual(gate["hygiene"]["findings"], ["H002"])


if __name__ == "__main__":
    unittest.main()
