#!/usr/bin/env python3
"""Verify template answers survive RST rendering and incomplete manuals cannot pass."""
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import manual
import build_document_model as model
import render_docs
import check_prose


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'README.md').write_text('The example normalizes input.\nRun normalize to write cleaned output.\n')
        self.index = {'schema_version': 3, 'index_hash': 'scan', 'files': [], 'coverage': {}}
        self.answers = manual.scaffold(self.index)
        # What a `confirmed` answer is allowed to stand on: one verified claim and one
        # observed statement. The unverified pair beside them is what the rule refuses.
        self.claims = [{'id': 'claim:verified', 'status': 'verified'},
                       {'id': 'claim:candidate', 'status': 'candidate'}]
        self.analysis = model.Analysis([
            {'path': 'README.md', 'statements': [
                {'id': 'stmt:observed', 'kind': 'responsibility', 'status': 'observed'},
                {'id': 'stmt:guessed', 'kind': 'responsibility', 'status': 'inferred'}]}])

        self.extra = {}

    def build(self):
        extra = dict(self.extra, manual=self.answers, root=str(self.root),
                     diagram_directory=str(self.root / 'diagrams'))
        return model.build(self.index, [], self.claims, 'manual', analysis=self.analysis,
                           extra=extra)

    def compose(self, page_id, heading, *answers):
        """Write one section of a page from the answers behind it.

        Answers are notes; a page is what someone composed from them. Every test that
        wants prose on a page has to go through this, which is the point.
        """
        self.answers['pages'].setdefault(page_id, {'sections': []})['sections'].append(
            {'heading': heading, 'body': 'Composed prose about %s.' % heading.lower(),
             'answers': list(answers)})

    def test_template_questions_are_preserved(self):
        source = Path(__file__).resolve().parents[1] / 'plugins/docs/skills/document-codebase/references/documentation-template.md'
        text = source.read_text()
        sections = re.findall(r'^## (\d+\.\d+) [^\n]+\n(.*?)(?=^## |^# |\Z)', text, re.M | re.S)
        actual = [q['text'] for page in manual.QUESTIONS[1:] for q in page['questions']]
        expected = [q for _, body in sections for _, q in re.findall(r'^(\d+)\. (.+)$', body, re.M)]
        self.assertEqual(actual, expected)

    def test_the_page_carries_composed_prose_not_the_questions(self):
        """The template question is the prompt. It must not reach the reader."""
        self.answers['answers']['1.1.1'].update(
            basis='observed', completeness='complete', text='Raw note: normalizes input, writes cleaned output.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}],
            verified_ids=['claim:verified', 'stmt:observed'])
        self.compose('getting_started/introduction', 'What OrderLog is for', '1.1.1')
        doc = self.build()
        self.assertEqual(model.validate(doc), [])
        self.assertEqual([c['id'] for c in doc['claims']], ['claim:verified'])
        self.assertEqual([s['id'] for s in doc['statements']], ['stmt:observed'])
        # 20 generated; the six a repository cannot answer are named, never written.
        self.assertEqual(len(doc['pages']), len(manual.GENERATED))
        self.assertEqual([p['id'] for p in doc['authored_pages']],
                         [p['id'] for p in manual.AUTHORED])
        self.assertNotIn('appendix/glossary', [p['id'] for p in doc['pages']])
        page = next(p for p in doc['pages'] if p['id'] == 'getting_started/introduction')
        titles = {p['id']: p['title'] for p in doc['pages']}
        rst = render_docs.render_page(page, titles, render_docs.Rst())
        self.assertIn('What OrderLog is for', rst)
        self.assertIn('Composed prose about', rst)
        self.assertIn('README.md:1-2', rst)
        # Neither the question nor the raw note reaches the page.
        self.assertNotIn('What is the product or system', rst)
        self.assertNotIn('Raw note:', rst)
        checker = check_prose.Checker(doc)
        checker.check(doc)
        self.assertIn({'page': 'getting_started/introduction',
                       'block': 'section:getting_started/introduction:1'}, checker.queue)

    def test_a_heading_may_not_be_a_question(self):
        self.answers['answers']['1.1.1'].update(
            basis='inferred', completeness='complete', text='A reading.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}])
        self.compose('getting_started/introduction',
                     'What is the product or system, and what problem does it solve?',
                     '1.1.1')
        with self.assertRaises(ValueError): self.build()

    def test_composition_may_narrow_what_an_answer_rests_on_never_add(self):
        """Prose citing evidence no answer earned carries provenance nothing checked."""
        self.answers['answers']['1.1.1'].update(
            basis='observed', completeness='complete', text='A note.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
            verified_ids=['claim:verified'])
        self.compose('getting_started/introduction', 'Purpose', '1.1.1')
        section = self.answers['pages']['getting_started/introduction']['sections'][0]
        section['evidence'] = [{'path': 'README.md', 'line_start': 2, 'line_end': 2}]
        with self.assertRaises(ValueError): self.build()
        section['verified_ids'] = ['stmt:observed']
        section['evidence'] = [{'path': 'README.md', 'line_start': 1, 'line_end': 1}]
        with self.assertRaises(ValueError): self.build()

    def test_one_inferred_answer_makes_the_section_inferred(self):
        """Composition cannot launder a reading into a fact by surrounding it."""
        for qid, basis in (('1.1.1', 'observed'), ('1.1.2', 'inferred')):
            self.answers['answers'][qid].update(
                basis=basis, completeness='complete', text='A note.',
                evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                verified_ids=['claim:verified'] if basis == 'observed' else [])
        self.compose('getting_started/introduction', 'Purpose', '1.1.1', '1.1.2')
        doc = self.build()
        block = next(b for p in doc['pages'] for b in p['blocks'] if b.get('manual_block'))
        self.assertEqual(block['answer_basis'], 'inferred')
        self.assertTrue(block['text'].startswith('Inferred: '))

    def test_an_answered_question_no_section_uses_fails_the_gate(self):
        """Content the run paid for and then dropped is a defect, not a gap."""
        self.answers['answers']['1.1.1'].update(
            basis='inferred', completeness='complete', text='A note nobody composed.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}])
        doc = self.build()
        self.assertEqual(doc['manual_coverage']['uncomposed'], ['1.1.1'])
        ix = self.root / 'index.json'; ix.write_text(json.dumps(self.index))
        out = self.root / 'doc.json'; out.write_text(json.dumps(doc))
        report = self.root / 'report.json'
        subprocess.run([sys.executable, script('quality_docs.py'), '--index', str(ix),
                        '--doc', str(out), '--out', str(report)],
                       capture_output=True, text=True)
        data = json.loads(report.read_text())
        self.assertEqual(data['status'], 'failed')
        self.assertTrue(any('no section uses' in r for r in data['reasons']))

    def test_absent_stale_and_invalid_evidence_refused(self):
        del self.answers['answers']['1.1.1']
        with self.assertRaises(ValueError): self.build()
        self.answers = manual.scaffold(self.index)
        self.answers['index_hash'] = 'old'
        with self.assertRaises(ValueError): self.build()
        self.answers['index_hash'] = 'scan'
        self.answers['answers']['1.1.1'].update(basis='observed', completeness='complete', text='A factual answer.',
            evidence=[{'path':'README.md','line_start':1,'line_end':99}])
        with self.assertRaises(ValueError): self.build()
        self.answers['answers']['1.1.1']['evidence'] = [{'path':'../outside','line_start':1,'line_end':1}]
        with self.assertRaises(ValueError): self.build()

    def test_confirmed_must_borrow_standing_from_a_check(self):
        """Location is not support: `confirmed` names something that could have failed."""
        answer = self.answers['answers']['1.1.1']
        answer.update(basis='observed', completeness='complete', text='A factual answer.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}])
        # Evidence that resolves, and nothing that was ever checked.
        with self.assertRaises(ValueError): self.build()
        # The same answer as a reading is fine, and any section built on it says so.
        answer['basis'] = 'inferred'
        self.compose('getting_started/introduction', 'Purpose', '1.1.1')
        doc = self.build()
        block = next(b for p in doc['pages'] for b in p['blocks'] if b.get('manual_block'))
        self.assertTrue(block['text'].startswith('Inferred: '))

    def test_unverified_ids_are_refused_not_downgraded(self):
        """A claim that did not verify is an unchecked citation, not a weaker one."""
        answer = self.answers['answers']['1.1.1']
        answer.update(basis='observed', completeness='complete', text='A factual answer.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}],
                      verified_ids=['claim:candidate'])
        with self.assertRaises(ValueError): self.build()
        # `inferred` is the model's own reading; a statement recorded as one cannot
        # stand in for a check either.
        answer.update(verified_ids=['stmt:guessed'])
        with self.assertRaises(ValueError): self.build()
        # An id nothing in either file holds.
        answer['verified_ids'] = ['stmt:invented']
        with self.assertRaises(ValueError): self.build()

    def test_the_three_analyses_can_confirm_an_answer(self):
        """A validated procedure, flow or component is a check that could have failed.

        It is the same bar a verified claim clears, reached by a different validator --
        validate_operations matched the command character for character, validate_flows
        proved every step is a call read at its call site, validate_architecture checked
        the shape and the evidence. Without this the operations analysis renders nowhere
        in `manual` and the commands it quoted are spent.
        """
        self.extra = {
            'operations': {'procedures': [
                {'id': 'op:test', 'kind': 'test', 'status': 'declared',
                 'steps': [{'text': 'CI runs it.', 'command': 'python3 -m pytest'}]}]},
            'flows': {'flows': [{'id': 'flow:record', 'status': 'observed',
                                 'steps': [{'id': 'step:1'}]}]},
            'architecture': {'components': [{'id': 'component:edge', 'status': 'observed',
                                             'modules': ['src/api.py']}]}}
        for question, ref, page in (('2.2.1', 'op:test', 'architecture/data_flow'),
                                    ('2.1.1', 'flow:record', 'architecture/overview'),
                                    ('2.1.2', 'component:edge', 'architecture/overview')):
            self.answers['answers'][question].update(
                basis='observed', completeness='complete', text='An answer resting on a validated analysis.',
                evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                verified_ids=[ref])
            self.compose(page, 'Section for ' + question, question)
        doc = self.build()
        self.assertEqual(model.validate(doc), [])
        cited = doc['manual_coverage']['verified_ids_cited']
        self.assertEqual(cited, {'component': ['component:edge'],
                                 'flow': ['flow:record'], 'procedure': ['op:test']})
        # These resolve against their own analyses, not against the claim set, so
        # neither list grows.
        self.assertEqual(doc['claims'], [])
        self.assertEqual(doc['statements'], [])

    def test_a_row_that_only_validated_cannot_confirm(self):
        """Validation is not confirmation: the schema passing says nothing was checked.

        `validate_operations.py` accepts an `inferred` procedure, and a step whose status
        is `unknown` need carry no command at all — so such a row cleared its schema with
        nothing mechanically matched against the source.
        """
        answer = self.answers['answers']['2.2.1']
        answer.update(basis='observed', completeness='complete', text='An answer resting on an analysis.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                      verified_ids=['op:loose'])
        for procedure in (
                {'id': 'op:loose', 'kind': 'run', 'status': 'inferred',       # reading
                 'steps': [{'text': 'x', 'command': 'python3 -m pytest'}]},
                {'id': 'op:loose', 'kind': 'run', 'status': 'declared',       # no command
                 'steps': [{'text': 'Deployment is mostly prose.'}]}):
            self.extra = {'operations': {'procedures': [procedure]}}
            with self.assertRaises(ValueError):
                self.build()
        # Declared, and carrying the command O006 matched: this one qualifies.
        self.extra = {'operations': {'procedures': [
            {'id': 'op:loose', 'kind': 'run', 'status': 'declared',
             'steps': [{'text': 'x', 'command': 'python3 -m pytest'}]}]}}
        self.assertEqual(model.validate(self.build()), [])

    def test_an_extracted_setting_can_confirm_an_answer(self):
        """`C006` matched the name against its lines, so the row may stand behind prose.

        This is the whole point of extracting settings: a configuration question is
        cross-cutting, so a module packet cannot serve it, and without an extracted row
        the answer could only ever be `inferred` — the model's reading of a search it
        did itself.
        """
        self.extra = {'config': {'settings': [
            {'id': 'config:env:API_TOKEN', 'kind': 'env', 'name': 'API_TOKEN',
             'status': 'observed',
             'evidence': [{'path': 'README.md', 'line_start': 1, 'line_end': 1}]},
            {'id': 'config:env:LOOSE', 'kind': 'env', 'name': 'LOOSE',
             'status': 'observed', 'evidence': []}]}}
        answer = self.answers['answers']['1.2.6']
        answer.update(basis='observed', completeness='complete', text='The service reads API_TOKEN.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                      verified_ids=['config:env:API_TOKEN'])
        self.compose('getting_started/installation', 'Environment', '1.2.6')
        doc = self.build()
        self.assertEqual(model.validate(doc), [])
        self.assertEqual(doc['manual_coverage']['verified_ids_cited'],
                         {'setting': ['config:env:API_TOKEN']})
        # A row citing nothing had nothing matched against the source, so it cannot
        # confirm — the same gate every other analysis row goes through.
        answer['verified_ids'] = ['config:env:LOOSE']
        with self.assertRaises(ValueError): self.build()

    def test_the_initializer_writes_no_prose_and_no_confirmation(self):
        """A draft is a to-do list. It used to arrive part-written and part-approved.

        `prefill` turned an analysis row into a sentence and marked it answered, so the
        manual carried text nobody wrote and nobody reviewed — and it looked decided,
        which is worse than looking empty. What the initializer hands over now is a
        reading list: the ids this run verified, for the model to read and write from.
        """
        operations = {'index_hash': 'scan', 'procedures': [
            {'id': 'op:test', 'kind': 'test', 'name': 'Running the tests',
             'status': 'declared', 'steps': [
                {'text': 'CI runs the suite.', 'status': 'declared',
                 'command': 'python3 -m pytest',
                 'evidence': [{'path': 'README.md', 'line_start': 2}]}]}],
            'requirements': [{'id': 'req:python', 'name': 'Python', 'value': '>=3.9',
                              'status': 'declared',
                              'evidence': [{'path': 'README.md', 'line_start': 1}]}]}
        draft = manual.scaffold(self.index, {'operations': operations})

        # Every slot is unanswered, whatever the analyses hold.
        self.assertTrue(all(a['basis'] == 'unknown' and a['completeness'] == 'unanswered'
                            for a in draft['answers'].values()))
        self.assertTrue(all(a['content_review'] == 'pending'
                            for a in draft['answers'].values()))
        # No sentence quoting an analysis reached any slot.
        self.assertFalse(any('pytest' in a['text'] or 'Python' in a['text']
                             for a in draft['answers'].values()))
        # But the facts are listed, so the model knows what it may cite.
        self.assertEqual(draft['facts'], {'procedure': ['op:test'],
                                          'requirement': ['req:python']})
        self.assertNotIn('prefilled', draft)
        # And every page is seeded empty: composing is the work.
        self.assertTrue(all(p['sections'] == [] for p in draft['pages'].values()))

    def test_a_v1_draft_is_refused_rather_than_relabelled(self):
        """A v1 `confirmed` was mechanical. Carrying it over would forge an approval."""
        self.answers['manual_version'] = 1
        with self.assertRaises(ValueError) as caught:
            self.build()
        self.assertIn('manual_version 1', str(caught.exception))

    def test_a_writer_cannot_set_its_own_review_verdict(self):
        """The verdict lives in the review channel, bound to the revision it judged."""
        self.answers['answers']['1.1.1'].update(
            basis='inferred', completeness='complete', text='A reading.',
            evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
            content_review='confirmed')
        with self.assertRaises(ValueError) as caught:
            self.build()
        self.assertIn('only a bound review row may say', str(caught.exception))

    def test_partial_must_name_what_is_missing(self):
        """`partial` is a promise about the gap; an empty list makes it a label.

        This is the configuration case: names and defaults answered, types and
        constraints not. Naming a validator id cannot close the gap it does not cover.
        """
        answer = self.answers['answers']['3.2.2']
        answer.update(basis='inferred', completeness='partial', text='Defaults only.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}])
        with self.assertRaises(ValueError): self.build()
        answer['facets_missing'] = ['type', 'constraints', 'precedence']
        self.compose('usage/configuration', 'Defaults', '3.2.2')
        doc = self.build()
        block = next(b for p in doc['pages'] for b in p['blocks']
                     if b.get('manual_block'))
        # A section is as incomplete as its least complete answer, and says which facets.
        self.assertEqual(block['answer_completeness'], 'partial')
        self.assertEqual(block['facets_missing'], ['constraints', 'precedence', 'type'])

    def test_only_two_diagram_pages(self):
        d = self.root / 'diagrams'; d.mkdir()
        for name in ('class', 'flow'): (d / (name+'.puml')).write_text('@startuml\n@enduml\n')
        (d / 'diagram-manifest.json').write_text(json.dumps({'schema_version':3,'views':[{'file':'class.puml'}]}))
        (d / 'flow-diagram-manifest.json').write_text(json.dumps({'index_hash':'scan','validated':True,'views':[{'file':'flow.puml'}]}))
        doc = self.build()
        homes = {p['id'] for p in doc['pages'] if any(b['type']=='plantuml' for b in p['blocks'])}
        self.assertEqual(homes, set(manual.DIAGRAMS))
        self.assertFalse(doc['manual_coverage']['missing_diagrams'])

    def test_unknowns_remain_incomplete_in_quality_report(self):
        doc = self.build()
        ix = self.root/'index.json'; ix.write_text(json.dumps(self.index))
        out = self.root/'doc.json'; out.write_text(json.dumps(doc))
        report = self.root/'report.json'
        proc = subprocess.run([sys.executable, script('quality_docs.py'), '--index',str(ix),
                               '--doc',str(out),'--out',str(report)],capture_output=True,text=True)
        self.assertTrue(report.exists(), proc.stdout+proc.stderr)
        data = json.loads(report.read_text())
        self.assertTrue(data['manual']['unresolved'])
        self.assertEqual(len(data['manual']['missing_diagrams']),2)
        self.assertNotEqual(data['status'],'passed')
        # A manual of unknowns satisfies every other check: the schema holds, each answer
        # is honest, nothing is overstated. It used to report `partial` and exit 0, which
        # told the run that answering nothing had worked.
        self.assertEqual(data['manual']['answer_mode'], 'unanswered')
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any('answer mode is unanswered' in r for r in data['reasons']))

    def test_the_unanswered_count_is_never_masked(self):
        """Each manual defect is reported on its own, not first-one-wins.

        These were an `elif` chain, so a composition problem hid the unanswered count
        and a report with 197 unanswered questions never mentioned them.
        """
        answer = self.answers['answers']['1.1.1']
        answer.update(basis='observed', completeness='complete', text='An answer no section uses.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                      verified_ids=['claim:verified'])
        doc = self.build()
        ix = self.root/'index.json'; ix.write_text(json.dumps(self.index))
        out = self.root/'doc.json'; out.write_text(json.dumps(doc))
        report = self.root/'report.json'
        subprocess.run([sys.executable, script('quality_docs.py'), '--index',str(ix),
                        '--doc',str(out),'--out',str(report)],capture_output=True,text=True)
        reasons = json.loads(report.read_text())['reasons']
        self.assertTrue(any('answer mode is unanswered' in r for r in reasons), reasons)
        self.assertTrue(any('no section uses' in r for r in reasons), reasons)

    def test_handbook_authored_pages_remain_reachable(self):
        # Preserve the upstream renderer regression after manual stops using authored pages.
        doc = model.build(self.index, [], [], 'handbook')
        existing, absent = doc['authored_pages'][:2]
        out = self.root / 'docs'
        authored = out / (existing['id'] + '.rst')
        authored.parent.mkdir(parents=True)
        original = 'Project introduction\n====================\n\nAuthored content.\n'
        authored.write_text(original)
        path = self.root / 'handbook.json'
        path.write_text(json.dumps(doc))
        proc = subprocess.run([sys.executable, script('render_docs.py'), '--doc', str(path),
                               '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        index = (out / 'index.rst').read_text()
        self.assertIn(existing['id'], index)
        self.assertNotIn(absent['id'], index)
        self.assertEqual(authored.read_text(), original)
        expected = sorted(doc['pages'] + [existing], key=lambda page: page['order'])
        positions = [index.index(page['id']) for page in expected]
        self.assertEqual(positions, sorted(positions))

    def test_cli_writes_all_pages(self):
        for name, data in [('index.json',self.index),('manual.json',self.answers)]:
            (self.root/name).write_text(json.dumps(data))
        (self.root/'empty.jsonl').write_text('')
        doc = self.root/'doc.json'
        proc = subprocess.run([sys.executable, script('build_document_model.py'),'--preset','manual',
            '--index',str(self.root/'index.json'),'--claims',str(self.root/'empty.jsonl'),
            '--fragments',str(self.root/'empty.jsonl'),'--manual-analysis',str(self.root/'manual.json'),
            '--root',str(self.root),'--out',str(doc)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        proc = subprocess.run([sys.executable,script('render_docs.py'),'--doc',str(doc),
            '--out',str(self.root/'docs')],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        # Generated pages plus index.rst. An authored page is never written over.
        self.assertEqual(len(list((self.root/'docs').rglob('*.rst'))),
                         len(manual.GENERATED) + 1)
        self.assertFalse((self.root/'docs/appendix/glossary.rst').exists())
        self.assertTrue((self.root/'docs/architecture/class_diagram.rst').exists())
        self.assertTrue((self.root/'docs/architecture/data_flow.rst').exists())


if __name__ == '__main__': unittest.main()
