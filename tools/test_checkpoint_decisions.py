#!/usr/bin/env python3
"""What a checkpoint asks, and what counts as having answered it.

A checkpoint's value is not in the question. It is in whether anybody answered it, and two
things decided that and were not enforced: a decision could be recorded in one word, and the
question could be so large that answering it honestly was impractical.
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
DIGEST = "sha256:abcdef123456789"


def run(cwd, *args):
    return subprocess.run([sys.executable, PIPELINE] + list(args),
                          cwd=str(cwd), capture_output=True, text=True)


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / ".docs-build"
        self.build.mkdir()
        (self.build / "structure.json").write_text(json.dumps(
            {"schema_version": 3, "index_hash": DIGEST, "files": [],
             "source": {"revision": "abc123"}}))

    def units(self, *paths):
        (self.build / "units.txt").write_text("".join(p + "\n" for p in paths))

    def opened(self, checkpoint):
        directory = self.build / "checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ("%s.json" % checkpoint)).write_text(json.dumps(
            {"checkpoint": checkpoint, "state": "pending", "index_hash": DIGEST}))

    def statement(self, kind, status="observed"):
        return {"id": "s:%s" % kind, "kind": kind, "status": status, "text": "t"}

    def analysis(self, rows):
        (self.build / "module-analysis.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def settled(self, path):
        return {"path": path,
                "statements": [self.statement(k) for k in pipeline.READ_KINDS]}

    def out(self, result):
        return result.stdout + result.stderr


class NoteTests(Build):
    """A decision recorded in one word is a signature, not a judgement."""

    def decide(self, note, checkpoint="P1"):
        self.opened(checkpoint)
        return run(self.root, "decide", "--checkpoint", checkpoint, "--note", note)

    def test_a_one_word_note_is_refused(self):
        result = self.decide("ok")
        self.assertEqual(result.returncode, 2)

    def test_the_refusal_says_how_many_words_and_quotes_what_was_given(self):
        result = self.decide("ok")
        text = self.out(result)
        self.assertIn("at least %d words" % pipeline.DECISION_NOTE_WORDS, text)
        self.assertIn("'ok'", text)
        self.assertIn("signature", text)

    def test_it_names_the_checkpoint_it_refused(self):
        result = self.decide("looks fine", checkpoint="P1")
        self.assertIn("P1", self.out(result))

    def test_nothing_is_recorded_when_the_note_is_refused(self):
        self.decide("ok")
        self.assertIsNone(pipeline.decision_for(str(self.build), "P1", DIGEST))

    def test_a_note_that_says_something_is_accepted(self):
        result = self.decide("top 25 by fan-in, agreed as the scope")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(pipeline.decision_for(str(self.build), "P1", DIGEST))

    def test_exactly_the_floor_is_enough(self):
        """A floor refuses what is under it, not what reaches it."""
        note = " ".join(["word"] * pipeline.DECISION_NOTE_WORDS)
        self.assertEqual(self.decide(note).returncode, 0)

    def test_one_word_under_the_floor_is_not(self):
        note = " ".join(["word"] * (pipeline.DECISION_NOTE_WORDS - 1))
        self.assertEqual(self.decide(note).returncode, 2)

    def test_deciding_unattended_is_still_allowed_when_it_says_so(self):
        """The skill tells a reader that running unattended is a decision too.

        The floor must not turn that into something only a human at a keyboard can record,
        or the honest answer becomes the one the tool refuses.
        """
        result = self.decide("no reviewer available, accepted the default scope")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_empty_note_keeps_its_own_message(self):
        """Nothing at all is a different mistake from too little, and reads differently."""
        self.opened("P1")
        result = run(self.root, "decide", "--checkpoint", "P1", "--note", "   ")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--note is required", self.out(result))

    def test_the_note_reaches_the_record_stripped(self):
        self.decide("  top 25 by fan-in, agreed as the scope  ")
        decided = pipeline.decision_for(str(self.build), "P1", DIGEST)
        self.assertEqual(decided["note"], "top 25 by fan-in, agreed as the scope")


class UncertainModuleTests(Build):
    """P2 asked about every module, which is the review load that produces a habitual yes."""

    def test_nothing_written_yet_has_nothing_to_show(self):
        """The ordinary state at the moment P2 opens: analyze opens it, hands write after."""
        self.assertIsNone(pipeline.uncertain_modules(str(self.build)))

    def test_a_module_recording_an_unknown_is_named_first(self):
        self.analysis([
            self.settled("src/a.py"),
            {"path": "src/murky.py",
             "statements": [self.statement(k) for k in pipeline.READ_KINDS[:3]]
                           + [self.statement("failure", "unknown")]}])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("src/murky.py", shown)
        self.assertLess(shown.index("src/murky.py"), shown.index("src/a.py"))
        self.assertIn("`unknown`", shown)

    def test_a_module_with_fewer_than_four_kinds_is_named_too(self):
        self.analysis([self.settled("src/a.py"),
                       {"path": "src/thin.py",
                        "statements": [self.statement("responsibility")]}])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("fewer than the four kinds", shown)
        self.assertIn("src/thin.py", shown)

    def test_a_module_is_not_named_twice(self):
        """An `unknown` on a thin module is one module, reported once."""
        self.analysis([{"path": "src/both.py",
                        "statements": [self.statement("responsibility", "unknown")]}])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertEqual(shown.count("src/both.py"), 1, shown)

    def test_the_settled_ones_are_sampled_not_listed(self):
        """A run where nothing is uncertain is spot-checked rather than waved through."""
        self.analysis([self.settled("src/%d.py" % n) for n in range(20)])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("as a sample", shown)
        named = sum(1 for n in range(20) if "src/%d.py" % n in shown)
        self.assertEqual(named, pipeline.SHOW_SAMPLE, shown)

    def test_a_long_list_is_capped_and_says_how_many_it_left_out(self):
        """The whole point is a bounded ask; an uncapped list is the old behaviour back."""
        self.analysis([
            {"path": "src/u%02d.py" % n,
             "statements": [self.statement("responsibility", "unknown")]}
            for n in range(20)])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("and %d more" % (20 - pipeline.SHOW_CAP), shown)
        self.assertLessEqual(sum(1 for n in range(20) if "src/u%02d.py" % n in shown),
                             pipeline.SHOW_CAP)

    def test_a_malformed_row_does_not_stop_it(self):
        """The ledger is written by hand, so a half-written line is an ordinary state."""
        (self.build / "module-analysis.jsonl").write_text(
            json.dumps(self.settled("src/a.py")) + "\n{ not json\n"
            + json.dumps({"statements": []}) + "\n")
        self.assertIsNotNone(pipeline.uncertain_modules(str(self.build)))


class ShownAtTheRefusalTests(Build):
    """The list has to appear where it can be acted on."""

    def p2(self):
        return [c for c in pipeline.CHECKPOINTS if c["id"] == "P2"][0]

    def test_the_static_description_stands_when_there_is_no_material(self):
        """A checkpoint never loses its question to an empty list."""
        self.assertEqual(pipeline.checkpoint_show(self.p2(), str(self.build)),
                         self.p2()["show"])

    def test_the_computed_list_replaces_it_once_there_is(self):
        self.analysis([{"path": "src/murky.py",
                        "statements": [self.statement("responsibility", "unknown")]}])
        self.assertIn("src/murky.py",
                      pipeline.checkpoint_show(self.p2(), str(self.build)))

    def test_a_check_held_at_p2_shows_the_uncertain_modules(self):
        """End to end, at the moment the reader is actually blocked and looking."""
        self.units("src/murky.py")
        self.opened("P2")
        self.analysis([{"path": "src/murky.py",
                        "statements": [self.statement("responsibility", "unknown")]}])
        result = run(self.root, "check", "--root", ".")
        text = self.out(result)
        self.assertIn("held at checkpoint P2", text)
        self.assertIn("src/murky.py", text)
        self.assertEqual(result.returncode, 1)

    def test_a_checkpoint_with_no_computed_list_is_unaffected(self):
        """P1, P3 and P4 keep the descriptions they had."""
        for checkpoint in pipeline.CHECKPOINTS:
            if checkpoint.get("show_from"):
                continue
            self.assertEqual(pipeline.checkpoint_show(checkpoint, str(self.build)),
                             checkpoint["show"])


class CodexRoundTwoTests(Build):
    """The second review's findings on the P2 list and the owed-work count.

    Four of them, all real. Three were holes in code this branch had just added, and the
    fourth was the conformance test missing the likeliest form of the bug it exists to catch.
    """

    def test_a_row_that_recorded_nothing_is_in_the_p2_list(self):
        """`statements: []` initialised no kinds, so the module was in neither group.

        It fell out of the list entirely, which meant P2 showed the settled modules and hid
        the one nothing was written about -- while blocking `check`, so the validator that
        would have reported it could not run yet.
        """
        self.analysis([self.settled("src/a.py"),
                       {"path": "src/empty.py", "statements": []}])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("src/empty.py", shown)
        self.assertIn("no reading recorded at all", shown)

    def test_a_module_in_scope_with_no_row_at_all_is_in_it_too(self):
        """The list never compared itself against `units.txt`, so an unstarted module was
        invisible to the question about whether the roles are right."""
        self.units("src/a.py", "src/never.py")
        self.analysis([self.settled("src/a.py")])
        shown = pipeline.uncertain_modules(str(self.build))
        self.assertIn("src/never.py", shown)

    def test_a_row_that_is_not_an_object_does_not_stop_the_run(self):
        """`[]` is valid JSON and not a row, and `row.get` raised on it.

        Reporting a run's position then exited 3 before `validate_analysis` could report the
        malformed line as the finding it is -- and every component carried the same banner,
        so nothing could run at all. Saying where a run is must never be able to stop the
        validator that would explain it.
        """
        (self.build / "module-analysis.jsonl").write_text("[]\n")
        self.assertEqual(pipeline.module_kinds(str(self.build)), {})
        scope, read, touched, untouched = pipeline.analysis_progress(str(self.build))
        self.assertEqual(read, [])

    def test_a_module_answering_three_of_four_kinds_is_still_owed(self):
        """`read` is the gate's two-of-four floor, and answered is four of four.

        Reusing `read` told a run whose every module was three-quarters written that it had
        the inputs it needs, while the work it owed was exactly those modules and the gate
        was going to call the run partial.
        """
        self.units("src/h.py")
        self.analysis([{"path": "src/h.py",
                        "statements": [self.statement(k)
                                       for k in pipeline.READ_KINDS[:3]]}])
        self.assertEqual(pipeline.unanswered_modules(str(self.build)), ["src/h.py"])
        _, read, _, _ = pipeline.analysis_progress(str(self.build))
        self.assertEqual(read, ["src/h.py"], "still read against the gate's floor")
        owed = pipeline.next_step(str(self.build), DIGEST,
                                 pipeline.unanswered_modules(str(self.build)))
        self.assertIn("remaining module(s)", owed)

    def test_a_fully_answered_module_is_not_owed(self):
        """The floor refuses what is under it, not what reaches it."""
        self.units("src/a.py")
        self.analysis([self.settled("src/a.py")])
        self.assertEqual(pipeline.unanswered_modules(str(self.build)), [])


class RecoveryCommandTests(Build):
    """A suggested command has to act on the build the failure was about."""

    def args(self, **kwargs):
        class Args(object):
            root = "."
            build = pipeline.DEFAULT_BUILD
            staging = None
            component = "document"
        args = Args()
        for key, value in kwargs.items():
            setattr(args, key, value)
        return args

    def test_a_default_build_is_not_named(self):
        """A suggestion cluttered with every flag is one nobody copies."""
        self.assertEqual(pipeline.invocation_args(self.args(), "survey"), " --root .")

    def test_a_custom_build_is_carried(self):
        """Dropping it pointed the reader at `.docs-build` while their build was elsewhere,
        so the command appeared to do nothing and the tool looked wrong."""
        shown = pipeline.invocation_args(self.args(build="mybuild"), "survey")
        self.assertIn("--build mybuild", shown)

    def test_status_carries_it_too(self):
        shown = pipeline.invocation_args(self.args(build="mybuild"), "status")
        self.assertIn("--build mybuild", shown)

    def test_a_custom_staging_rides_the_commands_that_use_it(self):
        args = self.args(staging="draft")
        self.assertIn("--staging draft", pipeline.invocation_args(args, "render"))
        self.assertIn("--staging draft", pipeline.invocation_args(args, "publish"))
        self.assertNotIn("--staging", pipeline.invocation_args(args, "survey"))


if __name__ == "__main__":
    unittest.main()
