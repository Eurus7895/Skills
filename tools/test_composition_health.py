#!/usr/bin/env python3
"""A section that replaces its answers instead of composing them must not publish."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import manual
import build_document_model as model


def note(text):
    return {"text": text, "facets_missing": [], "basis": "observed"}


REAL = ("The updater reads its options from the software root's build configuration and "
        "writes a merged file to the output path. It validates that the root exists and "
        "holds the build config before touching anything, so a wrong root fails "
        "immediately rather than producing an empty result. Options already present in "
        "the input are preserved.")


class MeasureTests(unittest.TestCase):
    """Calibration. Each case here is a section that was measured, not imagined."""

    def test_a_stub_over_many_answers_is_caught(self):
        health = manual.composition_health(
            "It works.", [note("Distinct note number %d." % i) for i in range(9)])
        self.assertTrue(health["problems"])
        self.assertIn("did not compose its answers", health["problems"][0])
        self.assertLess(health["words_per_answer"], 1)

    def test_a_proper_paragraph_passes(self):
        health = manual.composition_health(
            REAL, [note("n%d words here about the thing" % i) for i in range(7)])
        self.assertEqual(health["problems"], [])

    def test_well_compressed_prose_passes_despite_a_low_ratio(self):
        """The reason the ratio is not a verdict: good editing and discard look alike.

        1400 words of notes into a real paragraph retains under 5% -- almost exactly what
        the stub above retains. Only the prose itself tells them apart.
        """
        health = manual.composition_health(
            REAL, [note(" ".join(["detail"] * 200)) for _ in range(7)])
        self.assertLess(health["retained"], 0.10)
        self.assertEqual(health["problems"], [])

    def test_a_terse_but_honest_short_section_passes(self):
        health = manual.composition_health(
            "The tool is invoked as a Python API; there is no command line entry point.",
            [note("Invoked as a Python API."), note("No CLI entry point exists.")])
        self.assertEqual(health["problems"], [])

    def test_term_overlap_is_reported_never_a_verdict(self):
        """A section may paraphrase its answers completely and still be right."""
        health = manual.composition_health(
            "Every request is rejected unless the payload validates against the schema "
            "first, which keeps malformed submissions away from persistence entirely.",
            [note("Guards the boundary before the store is reached."),
             note("Refuses anything that fails verification.")])
        self.assertEqual(health["shared_terms"], 0)
        self.assertEqual(health["problems"], [])

    def test_the_measurements_are_recorded_either_way(self):
        health = manual.composition_health("It works.", [note("a b c d e f")])
        for field in ("body_words", "answer_words", "words_per_answer", "retained",
                      "shared_terms"):
            self.assertIn(field, health)


class GateTests(unittest.TestCase):
    """End to end: the draft still renders, and the gate refuses to publish it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'README.md').write_text(
            "\n".join("line %d" % i for i in range(1, 201)) + "\n")
        self.index = {'schema_version': 3, 'index_hash': 'scan', 'files': [],
                      'coverage': {}, 'assets': []}

    def manual_with(self, body):
        """Every question answered distinctly; one section per page, with `body`."""
        answers = manual.scaffold(self.index)
        count = 0
        for page in manual.GENERATED:
            for question in page['questions']:
                count += 1
                answers['answers'][question['id']].update(
                    basis='inferred', completeness='complete',
                    text='Distinct note number %d about %s.' % (count, question['id']),
                    evidence=[{'path': 'README.md', 'line_start': count,
                               'line_end': count}])
            answers['pages'][page['id']] = {'sections': [
                {'heading': 'About this', 'body': body,
                 'answers': [q['id'] for q in page['questions']]}]}
        return answers

    def build(self, body):
        return model.build(self.index, [], [], 'manual', analysis=model.Analysis(),
                           extra={'manual': self.manual_with(body),
                                  'root': str(self.root),
                                  'diagram_directory': str(self.root / 'd')})

    def report(self, doc):
        ix = self.root / 'index.json'; ix.write_text(json.dumps(self.index))
        out = self.root / 'doc.json'; out.write_text(json.dumps(doc))
        path = self.root / 'report.json'
        subprocess.run([sys.executable, script('quality_docs.py'), '--index', str(ix),
                        '--doc', str(out), '--out', str(path)],
                       capture_output=True, text=True)
        return json.loads(path.read_text())

    def test_the_thin_manual_that_used_to_reach_the_top_tier_is_now_held(self):
        """Measured before this check existed: validate clean, uncomposed 0,
        answer_mode `answered`, and a rendered page of nineteen words."""
        doc = self.build('It works.')
        # The draft is still produced -- a thin draft that renders is reviewable.
        self.assertEqual(model.validate(doc), [])
        self.assertEqual(doc['manual_coverage']['uncomposed'], [])
        self.assertEqual(len(doc['manual_coverage']['thin_sections']),
                         len(manual.GENERATED))
        report = self.report(doc)
        # Still the top answer tier: every question really was answered.
        self.assertEqual(report['manual']['answer_mode'], 'answered')
        # And still refused, for the separate reason.
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(any('discard the answers they name' in r
                            for r in report['reasons']), report['reasons'])

    def test_a_composed_manual_raises_no_composition_reason(self):
        doc = self.build(REAL)
        self.assertEqual(doc['manual_coverage']['thin_sections'], [])
        report = self.report(doc)
        self.assertFalse(any('discard the answers they name' in r
                             for r in report['reasons']), report['reasons'])

    def test_the_report_carries_the_figures(self):
        report = self.report(self.build('It works.'))
        self.assertEqual(report['manual']['prose_words'], 2 * len(manual.GENERATED))
        self.assertIsNotNone(report['manual']['retained'])
        self.assertEqual(len(report['manual']['thin_sections']), len(manual.GENERATED))

    def test_every_section_carries_its_own_measurements(self):
        doc = self.build(REAL)
        blocks = [b for p in doc['pages'] for b in p['blocks'] if b.get('manual_block')]
        self.assertTrue(blocks)
        for block in blocks:
            self.assertIn('composition', block)
            self.assertIn('words_per_answer', block['composition'])


if __name__ == '__main__':
    unittest.main()
