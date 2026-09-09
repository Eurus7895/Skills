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

    def build(self):
        return model.build(self.index, [], [], 'manual', extra={
            'manual': self.answers, 'root': str(self.root),
            'diagram_directory': str(self.root / 'diagrams')})

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
                      evidence=[{'path': 'README.md', 'line_start': 1, 'line_end': 2}])
        doc = self.build()
        self.assertEqual(model.validate(doc), [])
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
