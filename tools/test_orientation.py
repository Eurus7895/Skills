#!/usr/bin/env python3
"""Every component says where the run is, without being asked.

`status` answers this and answers it better. But it answers only when someone thinks to
ask, and the reader who most needs it -- an agent resuming with no memory of starting --
has no reason to ask: it has a task, and the pipeline looks like a sequence of commands.
So the orientation is on every invocation instead of being one more thing to remember.
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


def run(cwd, *args):
    return subprocess.run([sys.executable, PIPELINE] + list(args),
                          cwd=str(cwd), capture_output=True, text=True)


class OrientationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / ".docs-build"

    def scan(self, index_hash="sha256:abcdef123456789"):
        self.build.mkdir(exist_ok=True)
        (self.build / "structure.json").write_text(json.dumps(
            {"schema_version": 3, "index_hash": index_hash, "files": [],
             "source": {"revision": "abc123"}}))

    def units(self, *paths):
        (self.build / "units.txt").write_text("\n".join(paths) + "\n")

    def decided(self, checkpoint, index_hash="sha256:abcdef123456789"):
        directory = self.build / "checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ("%s.json" % checkpoint)).write_text(json.dumps(
            {"checkpoint": checkpoint, "state": "decided", "index_hash": index_hash,
             "note": "recorded", "ask": "?"}))

    def opened(self, checkpoint, index_hash="sha256:abcdef123456789"):
        directory = self.build / "checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ("%s.json" % checkpoint)).write_text(json.dumps(
            {"checkpoint": checkpoint, "state": "pending", "index_hash": index_hash}))

    def out(self, result):
        return result.stdout + result.stderr

    # -- the position, on every command ------------------------------------------

    def test_a_component_says_which_step_it_is(self):
        self.scan()
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertIn("step 2 of 7: analyze", text)

    def test_every_component_has_a_position(self):
        """A reader who lands on any one of them gets the same frame."""
        self.scan()
        for position, component in enumerate(pipeline.ORDER, 1):
            text = self.out(run(self.root, component, "--root", "."))
            self.assertIn("step %d of 7: %s" % (position, component), text,
                          "%s printed no position" % component)

    def test_it_names_the_scan_so_two_runs_are_not_confused(self):
        self.scan(index_hash="sha256:deadbeefcafe0001")
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertIn("sha256:deadb", text)

    # -- and before the first survey, nothing ------------------------------------

    def test_there_is_nothing_to_orient_against_before_the_first_survey(self):
        """A first run is not a resumed one. The preflight names the survey anyway."""
        text = self.out(run(self.root, "survey", "--root", "."))
        self.assertNotIn("step 1 of 7", text)

    # -- what the run owes that no script can produce ----------------------------

    def test_it_names_unread_modules_because_no_script_writes_those(self):
        """The gap a refusal cannot cover.

        Ordering is enforced by refusing to run, and that works for an artifact a component
        produces. It cannot work for the reading: nothing downstream can tell an absent
        module analysis from a thin one until the gate, so the only pressure available is
        saying on every command that it is still owed.
        """
        self.scan()
        self.units("src/a.py", "src/b.py")
        self.decided("P1")
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertIn("still owed:", text)
        self.assertIn("2 remaining module(s)", text)

    def test_an_open_checkpoint_is_what_is_owed_when_there_is_one(self):
        self.scan()
        self.units("src/a.py")
        self.opened("P1")
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertIn("still owed: decide P1", text)

    def test_a_run_that_owes_nothing_by_hand_says_only_the_position(self):
        """A banner that repeats "proceed" on every command is a banner nobody reads."""
        self.scan()
        self.units()
        for checkpoint in ("P1", "P2", "P3"):
            self.decided(checkpoint)
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertIn("step 2 of 7", text)
        self.assertNotIn("still owed:", text)

    # -- it survives the refusals, which is when it matters most -----------------

    def test_a_component_held_at_a_checkpoint_still_says_where_the_run_is(self):
        """The refusal names one undecided question; this names the position."""
        self.scan()
        self.units("src/a.py")
        self.opened("P2")
        result = run(self.root, "check", "--root", ".")
        text = self.out(result)
        self.assertIn("step 3 of 7: check", text)
        self.assertIn("held at checkpoint P2", text)
        self.assertEqual(result.returncode, 1)

    def test_a_component_refused_for_a_missing_input_does_too(self):
        self.scan()
        self.units()
        for checkpoint in ("P1", "P2", "P3"):
            self.decided(checkpoint)
        result = run(self.root, "render", "--root", ".")
        text = self.out(result)
        self.assertIn("step 5 of 7: render", text)
        self.assertIn("which document produces", text)
        self.assertEqual(result.returncode, 2)

    def test_the_orientation_comes_before_the_reason(self):
        """Read top to bottom: where you are, then what is wrong with it."""
        self.scan()
        self.units("src/a.py")
        self.opened("P1")
        text = self.out(run(self.root, "analyze", "--root", "."))
        self.assertLess(text.index("step 2 of 7"), text.index("held at checkpoint"))

    # -- it reports, and never acts ----------------------------------------------

    def test_it_writes_nothing_and_decides_nothing(self):
        """Orientation that changed the run would be a side effect on every command.

        Called directly rather than through the command, because the command legitimately
        writes: `build_dir.ensure` creates the directory and its `.gitignore`. Asserting the
        whole invocation touches nothing would be asserting the wrong thing, and it passed
        for the wrong reason until it did not.
        """
        self.scan()
        self.units("src/a.py")
        self.opened("P1")

        class Args(object):
            build = str(self.build)
            component = "analyze"

        before = sorted(os.listdir(str(self.build)))
        checkpoint = self.build / "checkpoints" / "P1.json"
        held = checkpoint.read_text()
        lines = pipeline.orientation(Args())
        self.assertTrue(lines, "it reported nothing at all")
        self.assertEqual(sorted(os.listdir(str(self.build))), before)
        self.assertEqual(checkpoint.read_text(), held)


if __name__ == "__main__":
    unittest.main()
