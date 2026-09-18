#!/usr/bin/env python3
"""P4, the prose pause, which had no test of any kind.

Two defects put it here, both found by running the pipeline against a real repository and
both since corrected in the driver:

    `prose_queued` read `report["queued"]` and `report["reviewed"]`. `check_prose` has
    never written them there -- the counts are under `coverage`, beside `blocks_checked` --
    so the predicate returned False on every report the pipeline has ever produced.

    The opening loop required a clean exit. P4 opens exactly when prose is queued, and
    queued prose is what makes the gate report `review_required` and the component exit 1,
    so the condition for opening the checkpoint guaranteed the exit code that skipped it.

Neither was caught by a test because there was none: no file mentioned `prose_queued` or
`P4`, and the report each fix was tried against by hand had been written to match the
reader rather than the producer. That is what these tests exist to stop. Every report here
uses the shape `check_prose` actually writes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths
sys.path[:0] = component_paths()
import pipeline

PIPELINE = os.path.join(os.path.dirname(pipeline.__file__), "pipeline.py")


# What `check_prose.py` writes, verified against a real run: counts under `coverage`,
# the undecided blocks in `unreviewed`, and the queue itself in `review_queue`.
def report(queued=20, reviewed=0, undecided=20):
    return {"schema_version": 1, "status": "review_required", "passed": False,
            "findings": [], "review_queue": [{"block": "b%d" % i}
                                             for i in range(queued)],
            "unreviewed": ["b%d" % i for i in range(undecided)],
            "coverage": {"blocks_checked": queued + 1, "blocks_uncited": 1,
                         "queued": queued, "reviewed": reviewed}}


class PredicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.build = Path(self.tmp.name)

    def write(self, data):
        (self.build / "prose-report.json").write_text(json.dumps(data))

    def test_the_real_report_shape_opens_it(self):
        """The bug: counts live under `coverage`, and the reader looked at the top level."""
        self.write(report())
        self.assertTrue(pipeline.prose_queued(str(self.build)))

    def test_top_level_counts_are_not_where_it_looks_any_more(self):
        """A report with the counts only at the top level is not one anything writes."""
        self.write({"queued": 20, "reviewed": 0})
        self.assertFalse(pipeline.prose_queued(str(self.build)))

    def test_a_fully_reviewed_queue_does_not_open_it(self):
        self.write(report(queued=20, reviewed=20, undecided=0))
        self.assertFalse(pipeline.prose_queued(str(self.build)))

    def test_an_empty_queue_does_not_open_it(self):
        """A checkpoint that opens with no question teaches people to decide blind."""
        self.write(report(queued=0, reviewed=0, undecided=0))
        self.assertFalse(pipeline.prose_queued(str(self.build)))

    def test_undecided_blocks_open_it_even_when_the_counts_agree(self):
        self.write(report(queued=5, reviewed=5, undecided=2))
        self.assertTrue(pipeline.prose_queued(str(self.build)))

    def test_a_missing_report_does_not_open_it(self):
        self.assertFalse(pipeline.prose_queued(str(self.build)))

    def test_an_unreadable_report_does_not_open_it(self):
        (self.build / "prose-report.json").write_text("{not json")
        self.assertFalse(pipeline.prose_queued(str(self.build)))


class ConditionalOpeningTests(unittest.TestCase):
    """A conditional checkpoint opens on the exit that produces its material.

    The second defect was structural: the opening loop ran under `if code == 0`, and P4
    opens exactly when prose is queued -- which is what makes the gate report
    `review_required` and the component exit 1. The condition for opening the checkpoint
    guaranteed the exit code that skipped the opening.

    The rule now is that a checkpoint carrying an `opens_when` predicate is exempt from
    needing a clean exit, because its predicate reads the report the stage just wrote and
    is the authority on whether there is anything to ask about.
    """

    def test_p4_is_the_conditional_one(self):
        p4 = next(c for c in pipeline.CHECKPOINTS if c["id"] == "P4")
        self.assertEqual(p4["opens_when"], "prose_queued")
        self.assertIn(p4["opens_when"], pipeline.OPENS_WHEN)

    def test_p4_is_owned_by_review_on_both_sides(self):
        """It is the review that queues the blocks, and the review that is held."""
        p4 = next(c for c in pipeline.CHECKPOINTS if c["id"] == "P4")
        self.assertEqual(p4["opened_by"], "review")
        self.assertEqual(p4["blocks"], "review")

    def test_the_earlier_checkpoints_are_unconditional(self):
        """A failed survey has no scope to approve, so those still need a clean exit."""
        for name in ("P1", "P2", "P3"):
            checkpoint = next(c for c in pipeline.CHECKPOINTS if c["id"] == name)
            self.assertIsNone(checkpoint.get("opens_when"), name)

    def test_every_checkpoint_naming_a_condition_has_it_registered(self):
        for checkpoint in pipeline.CHECKPOINTS:
            name = checkpoint.get("opens_when")
            if name:
                self.assertIn(name, pipeline.OPENS_WHEN, checkpoint["id"])


class BlockingTests(unittest.TestCase):
    """An open P4 holds publish, and a decision releases it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / ".docs-build"
        self.build.mkdir()
        (self.build / "structure.json").write_text(json.dumps(
            {"schema_version": 3, "index_hash": "sha256:aaa", "files": []}))
        (self.build / "prose-report.json").write_text(json.dumps(report()))

    def run_pipeline(self, *args):
        return subprocess.run([sys.executable, PIPELINE] + list(args),
                              cwd=str(self.root), capture_output=True, text=True)

    def open_p4(self):
        checkpoints = self.build / "checkpoints"
        checkpoints.mkdir(exist_ok=True)
        (checkpoints / "P4.json").write_text(json.dumps(
            {"checkpoint": "P4", "state": "pending", "index_hash": "sha256:aaa",
             "show": "the queued blocks", "ask": "are these the intended readings"}))

    def test_an_open_p4_holds_publish(self):
        self.open_p4()
        result = self.run_pipeline("publish", "--docs", "docs")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("P4", result.stdout + result.stderr)
        self.assertIn("held at checkpoint", result.stdout + result.stderr)

    def test_a_decision_releases_it(self):
        self.open_p4()
        decided = self.run_pipeline("decide", "--checkpoint", "P4",
                                    "--note", "readings confirmed")
        self.assertEqual(decided.returncode, 0, decided.stderr)
        self.assertIsNotNone(
            pipeline.decision_for(str(self.build), "P4", "sha256:aaa"))
        # No longer the thing standing in front of publish.
        blocking = pipeline.blocking_checkpoint(str(self.build), "publish", "sha256:aaa")
        self.assertIsNone(blocking)

    def test_status_reports_the_queue_from_coverage(self):
        """`status` had the same class of bug: it read `queue`, not `review_queue`."""
        result = self.run_pipeline("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20 block(s) queued", result.stdout)
        self.assertIn("20 undecided", result.stdout)


if __name__ == "__main__":
    unittest.main()
