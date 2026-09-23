#!/usr/bin/env python3
"""A conflict in a bundled reference must fail marketplace validation."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import validate


class MergeMarkerTests(unittest.TestCase):
    def test_conflicted_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "plugins" / "docs" / "skills" / "document-codebase" / "references" / "pipeline.md"
            reference.parent.mkdir(parents=True)
            reference.write_text("# Pipeline\n<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> branch\n")
            with patch.object(validate, "REPO", tmp), \
                 patch.object(validate, "PLUGINS", str(root / "plugins")), \
                 patch.object(validate, "FAILURES", []):
                validate.check_merge_markers()
                self.assertEqual(len(validate.FAILURES), 1)
                self.assertIn("pipeline.md: unresolved merge marker at line 2",
                              validate.FAILURES[0])


if __name__ == "__main__":
    unittest.main()
