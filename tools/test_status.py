#!/usr/bin/env python3
"""`pipeline.py status`: where a run is, answerable without running any of it."""
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


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / '.docs-build'

    def scan(self, index_hash='sha256:aaa', **source):
        self.build.mkdir(exist_ok=True)
        (self.build / 'structure.json').write_text(json.dumps(
            {'schema_version': 3, 'index_hash': index_hash, 'files': [],
             'source': source or {'revision': 'abc123'}}))

    def units(self, *paths):
        (self.build / 'units.txt').write_text("\n".join(paths) + "\n")

    def analysis(self, rows):
        (self.build / 'module-analysis.jsonl').write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def statement(self, sid, kind):
        return {'id': sid, 'kind': kind, 'status': 'observed', 'text': 't',
                'evidence': [{'path': 'x.py', 'line_start': 1, 'line_end': 1}]}

    # -- it must never start what it reports on ----------------------------------

    def test_no_build_directory_is_reported_and_nothing_is_created(self):
        """Creating the build directory to say there is none would change the answer."""
        result = run(self.root, 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no scan yet', result.stdout)
        self.assertFalse(self.build.exists(), 'status wrote a build directory')

    def test_status_writes_nothing_at_all(self):
        self.scan()
        self.units('src/a.py')
        before = {p: p.stat().st_mtime_ns for p in self.build.rglob('*')}
        run(self.root, 'status')
        after = {p: p.stat().st_mtime_ns for p in self.build.rglob('*')}
        self.assertEqual(before, after)

    def test_status_answers_while_a_checkpoint_is_open(self):
        """The state of a run must not be reported only by something that may decline."""
        self.scan()
        self.units('src/a.py')
        (self.build / 'checkpoints').mkdir()
        (self.build / 'checkpoints' / 'P1.json').write_text(json.dumps(
            {'checkpoint': 'P1', 'state': 'pending', 'index_hash': 'sha256:aaa',
             'show': 's', 'ask': 'is this the right scope'}))
        blocked = run(self.root, 'analyze')
        self.assertNotEqual(blocked.returncode, 0)
        result = run(self.root, 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('P1', result.stdout)
        self.assertIn('OPEN', result.stdout)
        self.assertIn('decide P1', result.stdout)

    # -- the number a resumed session needs --------------------------------------

    def test_a_partly_written_module_is_told_apart_from_an_untouched_one(self):
        """Reporting them together invites someone to write the first one twice."""
        self.scan()
        self.units('src/read.py', 'src/partial.py', 'src/none.py')
        self.analysis([
            {'path': 'src/read.py', 'index_hash': 'sha256:aaa', 'statements': [
                self.statement('r1', 'responsibility'), self.statement('r2', 'interface')]},
            {'path': 'src/partial.py', 'index_hash': 'sha256:aaa', 'statements': [
                self.statement('p1', 'responsibility')]}])
        out = run(self.root, 'status').stdout
        self.assertIn('3 in scope, 1 read, 1 partly written, 1 not started', out)
        self.assertIn('finish src/partial.py', out)
        self.assertIn('start  src/none.py', out)
        self.assertNotIn('src/read.py', out)

    def test_the_read_floor_matches_the_gate(self):
        """One statement is touched, not read -- the same bar quality_docs applies."""
        self.scan()
        self.units('src/a.py')
        self.analysis([{'path': 'src/a.py', 'index_hash': 'sha256:aaa',
                        'statements': [self.statement('s1', 'responsibility')]}])
        self.assertIn('0 read, 1 partly written', run(self.root, 'status').stdout)
        self.analysis([{'path': 'src/a.py', 'index_hash': 'sha256:aaa', 'statements': [
            self.statement('s1', 'responsibility'), self.statement('s2', 'failure')]}])
        self.assertIn('1 read, 0 partly written', run(self.root, 'status').stdout)

    def test_a_corrupt_analysis_line_does_not_stop_the_report(self):
        """validate_analysis owns that verdict; status still has to answer."""
        self.scan()
        self.units('src/a.py')
        (self.build / 'module-analysis.jsonl').write_text('{not json\n')
        result = run(self.root, 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 in scope', result.stdout)

    # -- the rest of the run -----------------------------------------------------

    def test_manual_authored_and_review_progress(self):
        self.scan()
        (self.build / 'manual-analysis.json').write_text(json.dumps(
            {'manual_version': 2, 'index_hash': 'sha256:aaa',
             'answers': {'1.1.1': {'completeness': 'complete'},
                         '1.1.2': {'completeness': 'unanswered'}},
             'pages': {'getting_started/introduction': {'sections': [{'heading': 'H'}]}}}))
        (self.build / 'authored.jsonl').write_text(
            json.dumps({'page_id': 'appendix/faq', 'status': 'scaffolded'}) + "\n"
            + json.dumps({'page_id': 'appendix/compliance', 'status': 'waived'}) + "\n")
        # The shape `check_prose` actually writes: counts under `coverage`, the undecided
        # blocks in `unreviewed`, the queue in `review_queue`. This test used to fabricate
        # `{'queue': [...], 'reviewed': 1}` -- the same wrong shape the reader assumed --
        # so it passed while `status` and `prose_queued` both read the wrong keys.
        (self.build / 'prose-report.json').write_text(json.dumps(
            {'schema_version': 1, 'status': 'review_required',
             'review_queue': [{'block': 'b1'}, {'block': 'b2'}],
             'unreviewed': ['b2'],
             'coverage': {'blocks_checked': 3, 'queued': 2, 'reviewed': 1}}))
        out = run(self.root, 'status').stdout
        self.assertIn('1 of 2 question(s) answered, 1 section(s) composed', out)
        self.assertIn('1 of 2 page(s) settled', out)
        self.assertIn('appendix/faq (scaffolded)', out)
        self.assertIn('2 block(s) queued, 1 reviewed, 1 undecided', out)

    def test_a_checkpoint_from_an_earlier_scan_is_marked_stale(self):
        """A scope approved against one scan says nothing about a tree that has moved."""
        self.scan(index_hash='sha256:new')
        (self.build / 'checkpoints').mkdir()
        (self.build / 'checkpoints' / 'P1.json').write_text(json.dumps(
            {'checkpoint': 'P1', 'state': 'decided', 'index_hash': 'sha256:old',
             'note': 'approved last week', 'show': 's', 'ask': 'a'}))
        out = run(self.root, 'status').stdout
        self.assertIn('earlier scan', out)
        self.assertNotIn('approved last week', out)

    def test_next_names_the_work_before_the_component(self):
        self.scan()
        self.units('src/a.py')
        self.assertIn('write the analysis for 1 remaining module',
                      run(self.root, 'status').stdout)

    def test_next_asks_for_answers_once_the_modules_are_answered(self):
        """All four kinds, not two.

        The fixture supplied two and called the module read, which is the gate's floor for
        telling a module somebody worked on from one nobody touched. What the run *owes* is
        four of four, so with two the honest advice is to finish the module -- and advising
        the manual questions there was the defect, not this assertion.
        """
        self.scan()
        self.units('src/a.py')
        self.analysis([{'path': 'src/a.py', 'index_hash': 'sha256:aaa', 'statements': [
            self.statement('s1', 'responsibility'), self.statement('s2', 'state'),
            self.statement('s3', 'interface'), self.statement('s4', 'failure')]}])
        (self.build / 'manual-analysis.json').write_text(json.dumps(
            {'answers': {'1.1.1': {'completeness': 'unanswered'}}, 'pages': {}}))
        self.assertIn('answer 1 remaining question', run(self.root, 'status').stdout)

    def test_next_asks_for_composition_once_everything_is_answered(self):
        self.scan()
        (self.build / 'manual-analysis.json').write_text(json.dumps(
            {'answers': {'1.1.1': {'completeness': 'complete'}}, 'pages': {}}))
        self.assertIn('compose each page', run(self.root, 'status').stdout)


if __name__ == '__main__':
    unittest.main()
