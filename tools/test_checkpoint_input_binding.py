#!/usr/bin/env python3
"""Checkpoint decisions must stay bound to what the reviewer actually saw."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import pipeline
from build_document_model import PRESETS

CONTRACTS = Path(__file__).resolve().parent.parent / "tests" / "contracts"


class CheckpointBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / ".docs-build"
        self.build.mkdir()

    def run_script(self, name, *args):
        return subprocess.run(
            [sys.executable, script(name), *map(str, args)],
            cwd=self.root, capture_output=True, text=True)

    def pipeline(self, *args):
        return self.run_script("pipeline.py", *args, "--root", self.root,
                               "--build", self.build)

    def write(self, name, content):
        path = self.build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_scope_change_on_same_scan_reopens_p1(self):
        (self.root / "a.py").write_text("def a(): return 1\n")
        (self.root / "b.py").write_text("def b(): return 2\n")
        self.assertEqual(self.pipeline("survey", "--top", "1").returncode, 0)
        digest = pipeline.index_hash_of(self.build)
        self.assertEqual(self.pipeline("decide", "--checkpoint", "P1", "--note",
                                       "Approved the initial one module scope").returncode, 0)
        self.assertEqual(self.pipeline("survey", "--top", "2").returncode, 0)
        self.assertEqual(digest, pipeline.index_hash_of(self.build))
        self.assertEqual(len((self.build / "units.txt").read_text().splitlines()), 2)
        self.assertIsNone(pipeline.decision_for(self.build, "P1", digest))
        self.assertIsNotNone(pipeline.blocking_checkpoint(self.build, "analyze", digest))

    def test_selection_option_change_reopens_p1_even_with_same_units(self):
        (self.root / "a.py").write_text("def a(): return 1\n")
        self.assertEqual(self.pipeline("survey", "--top", "2").returncode, 0)
        units = (self.build / "units.txt").read_text()
        digest = pipeline.index_hash_of(self.build)
        self.assertEqual(self.pipeline("decide", "--checkpoint", "P1", "--note",
                                       "Approved this selected module and cutoff").returncode, 0)
        self.assertEqual(self.pipeline("survey", "--top", "3").returncode, 0)
        self.assertEqual((self.build / "units.txt").read_text(), units)
        self.assertIsNone(pipeline.decision_for(self.build, "P1", digest))

    def test_reading_progress_does_not_change_scope_approval(self):
        self.write("structure.json", {"index_hash": "sha256:abc"})
        self.write("units.txt", "a.py\n")
        scope = {"product_roots": ["src"], "required_topics": ["usage"],
                 "files": [{"path": "a.py", "disposition": "product",
                            "reading": "unread"}]}
        self.write("scope.json", scope)
        checkpoint = pipeline.CHECKPOINTS[0]
        pipeline.open_checkpoint(self.build, checkpoint, "sha256:abc")
        self.assertEqual(self.pipeline("decide", "--checkpoint", "P1", "--note",
                                       "Approved the product scope and cutoff").returncode, 0)
        scope["files"][0]["reading"] = "analyzed"
        self.write("scope.json", scope)
        self.assertIsNotNone(pipeline.decision_for(self.build, "P1", "sha256:abc"))
        scope["files"][0]["disposition"] = "test"
        self.write("scope.json", scope)
        self.assertIsNone(pipeline.decision_for(self.build, "P1", "sha256:abc"))

    def test_roles_and_architecture_changes_expire_decisions(self):
        self.write("structure.json", {"index_hash": "sha256:abc"})
        self.write("units.txt", "a.py\n")
        self.write("module-analysis.jsonl", '{"path":"a.py","statements":[]}\n')
        self.write("architecture-analysis.json", {"components": []})
        for name in ("P2", "P3"):
            checkpoint = next(c for c in pipeline.CHECKPOINTS if c["id"] == name)
            pipeline.open_checkpoint(self.build, checkpoint, "sha256:abc")
            result = self.pipeline("decide", "--checkpoint", name, "--note",
                                   "Reviewed the current analysis and boundaries")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNotNone(pipeline.decision_for(self.build, name, "sha256:abc"))
        self.write("architecture-analysis.json", {"components": ["changed"]})
        self.assertIsNotNone(pipeline.decision_for(self.build, "P2", "sha256:abc"))
        self.assertIsNone(pipeline.decision_for(self.build, "P3", "sha256:abc"))
        self.write("module-analysis.jsonl", '{"path":"a.py","statements":[{"kind":"state"}]}\n')
        self.assertIsNone(pipeline.decision_for(self.build, "P2", "sha256:abc"))

    def test_review_required_opens_p4_and_self_review_cannot_publish(self):
        shutil.copyfile(CONTRACTS / "structure-v2-minimal.json",
                        self.build / "structure.json")
        shutil.copyfile(CONTRACTS / "module-analysis-v1-valid.jsonl",
                        self.build / "module-analysis.jsonl")
        self.write("units.txt", "app.py\npkg/store.py\n")
        self.write("claims.verified.jsonl", "")
        doc = {"format_version": 2, "preset": "onboarding",
               "index_hash": pipeline.index_hash_of(self.build),
               "claims": [], "statements": [], "authored_pages": [], "pages": []}
        for i, (pid, title, mandatory, covers) in enumerate(PRESETS["onboarding"]):
            doc["pages"].append({"id": pid, "title": title, "order": i,
                                 "mandatory": mandatory, "covers": covers, "blocks": []})
        doc["pages"][0]["blocks"] = [{
            "id": "block:probe", "type": "prose", "manual_block": True,
            "text": "Read the repository configuration before starting the application.",
            "claim_refs": [], "analysis_refs": []}]
        self.write("doc.json", doc)
        # The user's template choice, which a real run records before `document`; publish
        # refuses a document whose template nobody chose.
        self.write("template.json", {"template_version": 1, "kind": "preset",
                                     "name": "onboarding", "source": "built-in",
                                     "note": "the user chose the onboarding tour"})
        staging = self.build / "rendered-docs"
        self.assertEqual(self.run_script("render_docs.py", "--doc", self.build / "doc.json",
                                         "--out", staging).returncode, 0)
        self.write("rendered-docs/_diagrams/diagram-manifest.json", {
            "schema_version": 3, "views": [{"scope": {"kind": "repository"}}]})
        self.assertEqual(self.run_script("snapshot_draft.py", "--draft", staging,
                                         "--doc", self.build / "doc.json", "--out",
                                         self.build / "render-manifest.json").returncode, 0)

        first = self.pipeline("review")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        report = json.loads((self.build / "prose-report.json").read_text())
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["coverage"]["queued"], 1)
        self.assertEqual(json.loads((self.build / "checkpoints/P4.json").read_text())
                         ["state"], "pending")

        rows = [dict(q, review_version=2, review_id="review:probe",
                     verdict="confirmed", review_mode="self_review",
                     reviewer="model-probe", findings=[])
                for q in report["review_queue"]]
        review = self.write("prose-review.jsonl",
                            "".join(json.dumps(row) + "\n" for row in rows))
        held = self.pipeline("review", "--review", review)
        self.assertEqual(held.returncode, 1, held.stdout + held.stderr)
        self.assertFalse((self.build / "publish-seal.json").exists())
        self.assertNotEqual(self.pipeline("publish", "--docs",
                                          self.root / "published").returncode, 0)

        accepted = self.pipeline("decide", "--checkpoint", "P4",
                                 "--user-response", "These readings are approved",
                                 "--p4-verdict", "accepted")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        reviewed = self.pipeline("review", "--review", review)
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        published = self.pipeline("publish", "--docs", self.root / "published")
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)


if __name__ == "__main__":
    unittest.main()
