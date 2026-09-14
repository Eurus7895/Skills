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

    def test_template_questions_are_preserved(self):
        source = Path(__file__).resolve().parents[1] / 'plugins/docs/skills/document-codebase/references/documentation-template.md'
        text = source.read_text()
        sections = re.findall(r'^## (\d+\.\d+) [^\n]+\n(.*?)(?=^## |^# |\Z)', text, re.M | re.S)
        actual = [q['text'] for page in manual.QUESTIONS[1:] for q in page['questions']]
        expected = [q for _, body in sections for _, q in re.findall(r'^(\d+)\. (.+)$', body, re.M)]
        self.assertEqual(actual, expected)

    def test_answers_reach_rst_and_review(self):
        answer = self.answers['answers']['1.1.1']
        answer.update(status='confirmed', text='This tool normalizes input so consumers receive cleaned output.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}],
                      verified_ids=['claim:verified', 'stmt:observed'])
        doc = self.build()
        self.assertEqual(model.validate(doc), [])
        # The cited rows travel with the document, so the reference resolves in it.
        self.assertEqual([c['id'] for c in doc['claims']], ['claim:verified'])
        self.assertEqual([s['id'] for s in doc['statements']], ['stmt:observed'])
        self.assertEqual(len(doc['pages']), 26)
        self.assertFalse(doc['authored_pages'])
        titles = {p['id']: p['title'] for p in doc['pages']}
        rst = render_docs.render_page(doc['pages'][0], titles, render_docs.Rst())
        self.assertIn(answer['text'], rst)
        self.assertIn('What is the product or system', rst)
        self.assertIn('README.md:1-2', rst)
        self.assertNotIn('source file(s)', rst)
        checker = check_prose.Checker(doc)
        checker.check(doc)
        self.assertIn({'page': 'getting_started/introduction', 'block': 'answer:1.1.1'}, checker.queue)
        self.assertEqual(len(doc['manual_coverage']['unresolved']), len(self.answers['answers']) - 1)

    def test_absent_stale_and_invalid_evidence_refused(self):
        del self.answers['answers']['1.1.1']
        with self.assertRaises(ValueError): self.build()
        self.answers = manual.scaffold(self.index)
        self.answers['index_hash'] = 'old'
        with self.assertRaises(ValueError): self.build()
        self.answers['index_hash'] = 'scan'
        self.answers['answers']['1.1.1'].update(status='confirmed', text='A factual answer.',
            evidence=[{'path':'README.md','line_start':1,'line_end':99}])
        with self.assertRaises(ValueError): self.build()
        self.answers['answers']['1.1.1']['evidence'] = [{'path':'../outside','line_start':1,'line_end':1}]
        with self.assertRaises(ValueError): self.build()

    def test_confirmed_must_borrow_standing_from_a_check(self):
        """Location is not support: `confirmed` names something that could have failed."""
        answer = self.answers['answers']['1.1.1']
        answer.update(status='confirmed', text='A factual answer.',
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}])
        # Evidence that resolves, and nothing that was ever checked.
        with self.assertRaises(ValueError): self.build()
        # The same answer as a reading is fine, and says so on the page.
        answer['status'] = 'inferred'
        doc = self.build()
        block = next(b for p in doc['pages'] for b in p['blocks']
                     if b.get('manual_question') == '1.1.1')
        self.assertTrue(block['text'].startswith('Inferred: '))

    def test_unverified_ids_are_refused_not_downgraded(self):
        """A claim that did not verify is an unchecked citation, not a weaker one."""
        answer = self.answers['answers']['1.1.1']
        answer.update(status='confirmed', text='A factual answer.',
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
        for question, ref in (('2.2.1', 'op:test'), ('2.1.1', 'flow:record'),
                              ('2.1.2', 'component:edge')):
            self.answers['answers'][question].update(
                status='confirmed', text='An answer resting on a validated analysis.',
                evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 1}],
                verified_ids=[ref])
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
        answer.update(status='confirmed', text='An answer resting on an analysis.',
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

    def test_prefill_answers_what_the_analyses_settled(self):
        """The commands reach the page exactly as validate_operations matched them."""
        # `status` is required by the operations schema, and is what decides whether a
        # row may confirm: these are `declared`, as a validated analysis records them.
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
        self.assertEqual(draft['prefilled'], ['1.2.1', '4.2.3'])
        commands = draft['answers']['4.2.3']
        self.assertEqual(commands['status'], 'confirmed')
        self.assertIn('`python3 -m pytest`', commands['text'])
        self.assertEqual(commands['verified_ids'], ['op:test'])
        # A citation with no line_end is one line, not a range guessed outwards.
        self.assertEqual(commands['evidence'], [{'path': 'README.md', 'line_start': 2,
                                                 'line_end': 2}])
        self.assertIn('Python >=3.9', draft['answers']['1.2.1']['text'])
        # Everything the analyses do not settle stays unknown rather than guessed.
        self.assertEqual(draft['answers']['1.1.1']['status'], 'unknown')
        # And the draft builds: a prefilled answer passes the rule it was written for.
        self.answers = draft
        self.extra = {'operations': operations}
        self.assertEqual(model.validate(self.build()), [])

    def test_prefill_skips_a_kind_the_analysis_never_recorded(self):
        """An absent procedure leaves the question open, it does not invent a heading."""
        draft = manual.scaffold(self.index, {'operations': {'procedures': [], 'requirements': []}})
        self.assertEqual(draft['prefilled'], [])
        self.assertEqual(draft['answers']['3.1.1']['status'], 'unknown')

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
        self.assertEqual(len(list((self.root/'docs').rglob('*.rst'))),27)
        self.assertTrue((self.root/'docs/architecture/class_diagram.rst').exists())
        self.assertTrue((self.root/'docs/architecture/data_flow.rst').exists())


if __name__ == '__main__': unittest.main()
