#!/usr/bin/env python3
"""A conflict in a bundled reference must fail marketplace validation."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import validate


class MergeMarkerTests(unittest.TestCase):
    def check_file(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "plugins" / "docs" / "skills" / "document-codebase" / "references" / "pipeline.md"
            reference.parent.mkdir(parents=True)
            reference.write_text(text)
            with patch.object(validate, "REPO", tmp), \
                 patch.object(validate, "PLUGINS", str(root / "plugins")), \
                 patch.object(validate, "FAILURES", []):
                validate.check_merge_markers()
                return list(validate.FAILURES)

    def test_conflicted_reference_is_rejected(self):
        failures = self.check_file("# Pipeline\n<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> branch\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("pipeline.md: unresolved merge marker at line 2", failures[0])

    def test_setext_heading_is_not_a_conflict(self):
        self.assertEqual(self.check_file("Title\n=======\n\nNormal prose.\n"), [])

    def test_separator_without_both_sides_is_not_a_conflict(self):
        self.assertEqual(self.check_file("=======\nNo conflict blocks here.\n"), [])


if __name__ == "__main__":
    unittest.main()
