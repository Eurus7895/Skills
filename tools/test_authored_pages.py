#!/usr/bin/env python3
"""The authored-page ledger: the obligation is recorded, and nothing is invented for it."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import authored
import manual
import build_document_model as model
import render_docs


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.index = {'schema_version': 3, 'index_hash': 'scan', 'files': [],
                      'coverage': {}, 'assets': [
                          {'path': 'CHANGELOG.md', 'kind': 'changelog', 'lines': 40},
                          {'path': 'LICENSE', 'kind': 'licence', 'lines': 21}]}
        self.analysis = model.Analysis([
            {'path': 'src/api.py', 'statements': [
                {'id': 'api-s1', 'kind': 'failure', 'status': 'observed',
                 'text': 'Raises on a malformed payload before the store is touched.',
                 'evidence': [{'path': 'src/api.py', 'line_start': 34, 'line_end': 51}]},
                {'id': 'api-s2', 'kind': 'failure', 'status': 'inferred',
                 'text': 'Probably retries.',
                 'evidence': [{'path': 'src/api.py', 'line_start': 60, 'line_end': 61}]}]},
            {'path': 'src/store.py', 'statements': [
                {'id': 'st-s1', 'kind': 'responsibility', 'status': 'observed',
                 'text': 'Owns persistence.', 'evidence': []}]}])

    # -- routing -----------------------------------------------------------------

    def test_failure_statements_reach_troubleshooting(self):
        rows = authored.offered('appendix/troubleshooting', self.index, self.analysis)
        self.assertEqual([r['ref'] for r in rows], ['api-s1'])
        self.assertEqual(rows[0]['cite'], 'src/api.py:34-51')

    def test_an_inferred_statement_is_not_offered_as_evidence(self):
        """The model's own reading, on a page whose problem is that evidence is thin."""
        rows = authored.offered('appendix/troubleshooting', self.index, self.analysis)
        self.assertNotIn('api-s2', [r['ref'] for r in rows])

    def test_assets_reach_the_pages_that_need_them(self):
        changelog = authored.offered('appendix/changelog', self.index, self.analysis)
        self.assertEqual([r['ref'] for r in changelog], ['CHANGELOG.md'])
        self.assertEqual(changelog[0]['cite'], 'CHANGELOG.md:1-40')
        references = authored.offered('appendix/references', self.index, self.analysis)
        self.assertEqual([r['ref'] for r in references], ['LICENSE'])

    def test_procedures_reach_the_operational_pages(self):
        extra = {'operations': {'procedures': [
            {'id': 'op:install', 'kind': 'install', 'name': 'Installing',
             'status': 'declared',
             'evidence': [{'path': 'README.md', 'line_start': 3, 'line_end': 9}]},
            {'id': 'op:guess', 'kind': 'run', 'name': 'Guessed', 'status': 'inferred'}]}}
        rows = authored.offered('appendix/faq', self.index, self.analysis, extra)
        self.assertIn('op:install', [r['ref'] for r in rows])
        self.assertNotIn('op:guess', [r['ref'] for r in rows])

    def test_a_page_nothing_bears_on_is_offered_nothing(self):
        self.assertEqual(authored.offered('appendix/glossary', self.index, self.analysis), [])

    # -- absences ----------------------------------------------------------------

    def test_silent_modules_are_named_not_hidden(self):
        """A thin troubleshooting page and a thin repository must not look alike."""
        absent = authored.absences('appendix/troubleshooting', self.index, self.analysis)
        self.assertTrue(any('src/store.py' in line for line in absent), absent)
        self.assertTrue(any('carry no failure statement' in line for line in absent))

    def test_a_missing_asset_is_reported(self):
        index = dict(self.index, assets=[])
        absent = authored.absences('appendix/changelog', index, self.analysis)
        self.assertTrue(any('no changelog file' in line for line in absent), absent)

    def test_a_page_with_no_source_says_so(self):
        absent = authored.absences('appendix/glossary', self.index, self.analysis)
        self.assertTrue(any('knowledge the source does not hold' in l for l in absent))

    # -- the ledger --------------------------------------------------------------

    def test_a_fresh_ledger_owes_every_page_but_the_default_waiver(self):
        rows = authored.ledger(manual.AUTHORED, self.index, self.analysis)
        self.assertEqual(len(rows), len(manual.AUTHORED))
        owed = dict(authored.unsettled(rows))
        self.assertNotIn('appendix/compliance', owed)
        self.assertIn('appendix/troubleshooting', owed)

    def test_compliance_starts_waived_and_says_nobody_looked(self):
        rows = {r['page_id']: r for r in authored.ledger(manual.AUTHORED, self.index)}
        row = rows['appendix/compliance']
        self.assertEqual(row['status'], authored.WAIVED)
        self.assertTrue(row['default_waiver'])
        self.assertIsNone(row['owner'])
        self.assertIn('No owner has claimed this page', row['waiver_reason'])

    def test_a_waiver_without_an_owner_is_refused(self):
        known = {p['id']: p for p in manual.AUTHORED}
        row = {'authored_version': 1, 'page_id': 'appendix/faq', 'status': 'waived',
               'waiver_reason': 'Not needed.'}
        with self.assertRaises(ValueError) as caught:
            authored.read_row(row, known)
        self.assertIn('names the owner', str(caught.exception))

    def test_a_waiver_without_a_reason_is_refused(self):
        known = {p['id']: p for p in manual.AUTHORED}
        row = {'authored_version': 1, 'page_id': 'appendix/faq', 'status': 'waived',
               'owner': 'ops@example.com'}
        with self.assertRaises(ValueError):
            authored.read_row(row, known)

    def test_a_complete_waiver_is_accepted(self):
        known = {p['id']: p for p in manual.AUTHORED}
        row = authored.read_row(
            {'authored_version': 1, 'page_id': 'appendix/faq', 'status': 'waived',
             'owner': 'ops@example.com', 'waiver_reason': 'Internal tool; no users ask.'},
            known)
        self.assertEqual(row['owner'], 'ops@example.com')

    def test_an_unknown_page_is_refused(self):
        with self.assertRaises(ValueError):
            authored.read_row({'authored_version': 1, 'page_id': 'appendix/nope',
                               'status': 'scaffolded'},
                              {p['id']: p for p in manual.AUTHORED})

    def test_a_versionless_row_is_refused(self):
        with self.assertRaises(ValueError):
            authored.read_row({'page_id': 'appendix/faq', 'status': 'scaffolded'},
                              {p['id']: p for p in manual.AUTHORED})

    def test_drafted_does_not_settle_a_page(self):
        """A draft is what gets reviewed; treating it as done publishes the input."""
        rows = authored.ledger(manual.AUTHORED, self.index, self.analysis, None, [
            {'authored_version': 1, 'page_id': 'appendix/faq', 'status': 'drafted'}])
        self.assertIn('appendix/faq', dict(authored.unsettled(rows)))

    def test_recorded_state_survives_and_evidence_is_recomputed(self):
        """The file holds what a person owns; the view is this run's."""
        rows = authored.ledger(manual.AUTHORED, self.index, self.analysis, None, [
            {'authored_version': 1, 'page_id': 'appendix/troubleshooting',
             'status': 'complete', 'owner': 'docs@example.com'}])
        row = next(r for r in rows if r['page_id'] == 'appendix/troubleshooting')
        self.assertEqual(row['status'], 'complete')
        self.assertEqual([r['ref'] for r in row['evidence_offered']], ['api-s1'])

    def test_the_file_persists_only_what_a_person_owns(self):
        rows = authored.ledger(manual.AUTHORED, self.index, self.analysis)
        path = self.root / 'authored.jsonl'
        authored.dump(rows, path)
        stored = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(stored), len(manual.AUTHORED))
        self.assertNotIn('evidence_offered', stored[0])
        self.assertNotIn('evidence_absent', stored[0])
        self.assertIn('status', stored[0])
        # And it round-trips: reading it back is not a schema error.
        again = authored.load(path, manual.AUTHORED, self.index, self.analysis)
        self.assertEqual([r['page_id'] for r in again],
                         [p['id'] for p in manual.AUTHORED])

    def test_authored_mode_separates_settled_from_written(self):
        self.assertEqual(authored.authored_mode([])[0], 'complete')
        rows = [{'page_id': 'a', 'status': 'scaffolded'}, {'page_id': 'b', 'status': 'complete'}]
        self.assertEqual(authored.authored_mode(rows)[0], 'partial')
        rows = [{'page_id': 'a', 'status': 'waived'}, {'page_id': 'b', 'status': 'complete'}]
        self.assertEqual(authored.authored_mode(rows)[0], 'settled')
        rows = [{'page_id': 'a', 'status': 'complete'}]
        self.assertEqual(authored.authored_mode(rows)[0], 'written')


class GateTests(unittest.TestCase):
    """The publication gate, end to end through the scripts that run it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'README.md').write_text('Normalizes input.\nWrites cleaned output.\n')
        self.index = {'schema_version': 3, 'index_hash': 'scan', 'files': [],
                      'coverage': {}, 'assets': []}
        self.answers = manual.scaffold(self.index)
        self.answers['answers']['1.1.1'].update(
            basis='inferred', completeness='complete', text='A reading of the README.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}])
        self.answers['pages']['getting_started/introduction'] = {'sections': [
            {'heading': 'What this is', 'body': 'Composed prose.', 'answers': ['1.1.1']}]}

    def build(self, recorded=()):
        extra = {'manual': self.answers, 'root': str(self.root),
                 'diagram_directory': str(self.root / 'diagrams')}
        if recorded:
            extra['authored'] = list(recorded)
        return model.build(self.index, [], [], 'manual', analysis=model.Analysis(),
                           extra=extra)

    def report(self, doc):
        ix = self.root / 'index.json'; ix.write_text(json.dumps(self.index))
        out = self.root / 'doc.json'; out.write_text(json.dumps(doc))
        path = self.root / 'report.json'
        subprocess.run([sys.executable, script('quality_docs.py'), '--index', str(ix),
                        '--doc', str(out), '--out', str(path)],
                       capture_output=True, text=True)
        return json.loads(path.read_text())

    def test_unsettled_authored_pages_hold_publication(self):
        report = self.report(self.build())
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(any('nobody has written or waived' in r
                            for r in report['reasons']), report['reasons'])

    def test_an_authored_page_is_owed_under_one_heading_not_two(self):
        """It was reported as both an unwritten page and an ungenerated one, with two
        different remedies for the same five names."""
        report = self.report(self.build())
        self.assertEqual(report['pages']['missing'], [])
        self.assertEqual(len(report['pages']['authored_unsettled']),
                         len(manual.AUTHORED) - len(authored.DEFAULT_WAIVED))
        self.assertFalse(any('requires pages that were not generated' in r
                             for r in report['reasons']), report['reasons'])

    def test_a_settled_ledger_clears_the_authored_reason(self):
        """And the old unconditional `missing pages` failure goes with it."""
        recorded = [{'authored_version': 1, 'page_id': page['id'], 'status': 'waived',
                     'owner': 'docs@example.com', 'waiver_reason': 'Not needed here.'}
                    for page in manual.AUTHORED
                    if page['id'] not in authored.DEFAULT_WAIVED]
        report = self.report(self.build(recorded))
        self.assertFalse(any('nobody has written or waived' in r
                             for r in report['reasons']), report['reasons'])
        self.assertFalse(any('requires pages that were not generated' in r
                             for r in report['reasons']), report['reasons'])
        self.assertEqual(report['pages']['missing'], [])

    def test_the_authored_count_is_reported_separately_from_answers(self):
        report = self.report(self.build())
        self.assertIn('authored_mode', report['manual'])
        self.assertIn('answer_mode', report['manual'])
        self.assertEqual(report['manual']['authored_total'], len(manual.AUTHORED))

    def test_a_scaffold_is_never_written_over(self):
        doc = self.build()
        out = self.root / 'docs'
        (out / 'appendix').mkdir(parents=True)
        page = out / 'appendix' / 'faq.rst'
        page.write_text('Frequently Asked Questions\n==========================\n\nMine.\n')
        fresh = render_docs.scaffolds(doc, str(out), render_docs.Rst())
        self.assertNotIn('appendix/faq.rst', fresh)
        self.assertIn('Mine.', page.read_text())

    def test_a_scaffold_composes_no_prose_for_the_page(self):
        """It hands over evidence and questions. It never writes the answer."""
        doc = self.build()
        fresh = render_docs.scaffolds(doc, str(self.root / 'docs'), render_docs.Rst())
        body = fresh['appendix/troubleshooting.rst']
        self.assertIn('DRAFT', body)
        self.assertIn('5.3.1', body)
        self.assertIn('did not find', body)
        # No symptom/cause table invented out of nothing.
        self.assertNotIn('Likely cause', body)

    def test_a_waived_page_gets_no_scaffold(self):
        doc = self.build()
        fresh = render_docs.scaffolds(doc, str(self.root / 'docs'), render_docs.Rst())
        self.assertNotIn('appendix/compliance.rst', fresh)


if __name__ == '__main__':
    unittest.main()
