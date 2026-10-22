import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from courseagent import app as legacy
from courseagent.api_service import create_app
from courseagent.task_store import TaskStore

class ApiTests(unittest.TestCase):
    def test_health_ui_and_compatible_routes_do_not_read_key_values(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get('/').status_code,200)
            for path, content_type in (('/styles.css', 'text/css'), ('/workspace.js', 'text/javascript')):
                asset=client.get(path)
                self.assertEqual(asset.status_code,200)
                self.assertIn(content_type,asset.headers['content-type'])
                self.assertEqual(asset.headers['cache-control'],'no-store')
            health=client.get('/api/health').json()
            self.assertEqual(health['task_backend'],'sqlite');self.assertFalse(health['published'])
            with patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'test'}):
                self.assertEqual(client.get('/api/model-status').json()['model'],'test')
            self.assertEqual(client.get('/not-exist').status_code,404)
    def test_typed_submission_queues_and_origin_guard_preserves_review(self):
        from tests.test_autonomous_agent import document
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);review=root/'review.json';review.write_text(json.dumps(document()))
            before=review.read_bytes()
            with patch.object(legacy,'STATE',review),patch.object(legacy,'ROOT',root),patch.object(legacy,'SOURCES',root/'sources.json'),TestClient(create_app(root)) as client:
                response=client.post('/api/agent-start',json={'prompt':'栈作业','execute':False})
                self.assertEqual(response.status_code,202)
                job=response.json();self.assertEqual(job['status'],'queued')
                self.assertIsNotNone(TaskStore(root).get(job['id']))
                denied=client.post('/api/agent-start',json={'prompt':'bad','execute':False},headers={'Origin':'https://external.example'})
                self.assertEqual(denied.status_code,403);self.assertIn('error',denied.json())
                self.assertEqual(client.post('/api/agent-start',json={'prompt':''}).status_code,422)
                self.assertEqual(client.get('/api/agent-tasks').json()['tasks'][0]['id'],job['id'])
            self.assertEqual(review.read_bytes(),before)
    def test_compatible_mutation_route_keeps_origin_protection(self):
        with TestClient(create_app()) as client:
            response=client.post('/api/validate',json={},headers={'Origin':'https://external.example'})
            self.assertEqual(response.status_code,403)
