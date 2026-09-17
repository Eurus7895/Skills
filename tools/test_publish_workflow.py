#!/usr/bin/env python3
"""Behavioral contract for isolated render, final review, and publication."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import script


class PublishWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docs = self.root / "docs"
        self.draft = self.root / "build/rendered-docs"
        self.build = self.root / "build"
        self.docs.mkdir()
        (self.docs / "authored.rst").write_text("keep me\n")
        self.doc = self.build / "doc.json"
        self.report = self.build / "generation-report.json"
        self.seal = self.build / "publish-seal.json"
        self.render_manifest = self.build / "render-manifest.json"
        self.build.mkdir(exist_ok=True)
        self.doc.write_text(json.dumps({"format_version": 2, "pages": []}))
        self.report.write_text(json.dumps({"status": "passed"}))

    def invoke(self, name, *args):
        return subprocess.run([sys.executable, script(name), *map(str, args)],
                              capture_output=True, text=True)

    def test_draft_is_isolated_and_only_a_sealed_revision_is_promoted(self):
        prepared = self.invoke("prepare_stage.py", "--source", self.docs,
                            "--out", self.draft)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        (self.draft / "generated.rst").write_text("reviewed draft\n")
        snapshot = self.invoke("snapshot_draft.py", "--draft", self.draft,
                               "--doc", self.doc, "--out", self.render_manifest)
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        self.assertFalse((self.docs / "generated.rst").exists())
        self.assertEqual((self.draft / "authored.rst").read_text(), "keep me\n")

        refused = self.invoke("promote_docs.py", "--draft", self.draft,
                           "--target", self.docs, "--doc", self.doc,
                           "--report", self.report, "--seal", self.seal)
        self.assertEqual(refused.returncode, 2)
        self.assertFalse((self.docs / "generated.rst").exists())

        sealed = self.invoke("seal_draft.py", "--draft", self.draft,
                          "--doc", self.doc, "--report", self.report,
                          "--render-manifest", self.render_manifest,
                          "--out", self.seal)
        self.assertEqual(sealed.returncode, 0, sealed.stderr)
        published = self.invoke("promote_docs.py", "--draft", self.draft,
                             "--target", self.docs, "--doc", self.doc,
                             "--report", self.report, "--seal", self.seal)
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual((self.docs / "generated.rst").read_text(), "reviewed draft\n")
        self.assertEqual((self.docs / "authored.rst").read_text(), "keep me\n")

    def test_edit_after_review_invalidates_publication(self):
        self.invoke("prepare_stage.py", "--source", self.docs, "--out", self.draft)
        self.invoke("snapshot_draft.py", "--draft", self.draft, "--doc", self.doc,
                    "--out", self.render_manifest)
        self.invoke("seal_draft.py", "--draft", self.draft, "--doc", self.doc,
                    "--report", self.report, "--render-manifest", self.render_manifest,
                    "--out", self.seal)
        (self.draft / "authored.rst").write_text("changed after review\n")
        result = self.invoke("promote_docs.py", "--draft", self.draft,
                          "--target", self.docs, "--doc", self.doc,
                          "--report", self.report, "--seal", self.seal)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.docs / "authored.rst").read_text(), "keep me\n")

    def test_nonpassing_review_cannot_be_sealed(self):
        self.invoke("prepare_stage.py", "--source", self.docs, "--out", self.draft)
        self.invoke("snapshot_draft.py", "--draft", self.draft, "--doc", self.doc,
                    "--out", self.render_manifest)
        self.report.write_text(json.dumps({"status": "review_required"}))
        result = self.invoke("seal_draft.py", "--draft", self.draft,
                          "--doc", self.doc, "--report", self.report,
                          "--render-manifest", self.render_manifest,
                          "--out", self.seal)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.seal.exists())

    def test_manual_edit_between_render_and_review_is_refused(self):
        self.invoke("prepare_stage.py", "--source", self.docs, "--out", self.draft)
        self.invoke("snapshot_draft.py", "--draft", self.draft, "--doc", self.doc,
                    "--out", self.render_manifest)
        (self.draft / "authored.rst").write_text("patched directly\n")
        result = self.invoke("validate_draft.py", "--draft", self.draft,
                             "--doc", self.doc, "--manifest", self.render_manifest)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
