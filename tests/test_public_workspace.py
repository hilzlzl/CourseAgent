"""Public onboarding and export boundaries; no real model or platform actions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from courseagent.workspace_setup import initialize_workspace

ROOT = Path(__file__).resolve().parents[1]


class PublicWorkspaceTests(unittest.TestCase):
    def test_blank_workspace_is_usable_and_existing_work_is_preserved(self):
        from courseagent.questions import export_xlsx, NS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(len(initialize_workspace(root)), 3)
            state = root/'data/review.json'
            self.assertEqual(json.loads(state.read_text())['questions'], [])
            state.write_text('{"keep":true}')
            self.assertEqual(initialize_workspace(root), [])
            self.assertEqual(json.loads(state.read_text()), {'keep': True})
            fixture = json.loads((ROOT/'examples/offline-fixture.json').read_text())
            workbook = root/'example.xlsx'
            workbook.write_bytes(export_xlsx(fixture, False, root/'data/template.xlsx'))
            with ZipFile(workbook) as archive:
                self.assertIsNone(archive.testzip())
                sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                self.assertEqual(len(sheet.find(f'{{{NS}}}sheetData')), len(fixture['questions'])+1)

    def test_api_submission_defaults_to_local_even_without_classroom(self):
        from courseagent import app
        from courseagent.api_service import StartTask, create_app
        from fastapi.testclient import TestClient
        from courseagent.task_store import TaskStore
        self.assertFalse(StartTask(prompt='test').execute)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            initialize_workspace(root)
            with patch.object(app, 'ROOT', root), patch.object(app, 'STATE', root/'data/review.json'), patch.object(app, 'SOURCES', root/'data/sources.json'), TestClient(create_app(root)) as client:
                response = client.post('/api/agent-start', json={'prompt': '给排序算法布置两道单选题'})
                self.assertEqual(response.status_code, 202, response.text)
                job = TaskStore(root).get(response.json()['id'])
                self.assertFalse(job['execute'])
                self.assertFalse(job.get('import_id'))

    def test_ui_has_no_real_target_and_defaults_to_local(self):
        from html.parser import HTMLParser
        inputs = {}
        class Inputs(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'input': inputs[attrs.get('id')] = attrs
        Inputs().feed((ROOT/'src/courseagent/web/index.html').read_text())
        self.assertIn('checked', inputs['agent-local'])
        self.assertFalse(inputs['agent-classroom'].get('value'))
        self.assertFalse(inputs['classroom-url'].get('value'))

    def test_public_audit_rejects_private_paths_and_credentials(self):
        spec = importlib.util.spec_from_file_location('audit_public', ROOT/'scripts/audit_public.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'safe.py').write_text('print("hello")')
            self.assertEqual(module.audit(root, ['safe.py']), [])
            self.assertTrue(module.audit(root, ['data/review.json']))
            (root/'leak.py').write_text('KEY="sk-'+'x'*32+'"')
            report = module.audit(root, ['leak.py'])
            self.assertTrue(report)
            self.assertNotIn('x'*32, json.dumps(report))
