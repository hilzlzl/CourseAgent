"""Deterministic offline fixtures: never read real model keys or make model API calls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

@contextmanager
def offline_models():
    with tempfile.TemporaryDirectory() as folder:
        config=Path(folder)/'model.json'
        config.write_text(json.dumps({'api_key':'offline-placeholder','model':'offline-fixture','base_url':'https://provider.example/v1','backend':'langchain'}))
        with patch.dict(os.environ,{'EDUCODER_TRACE_MODE':'offline_tests'}),patch('courseagent.model_client.CONFIG',config),patch('courseagent.model_client.urlopen',side_effect=AssertionError('Offline suite must mock model transport')),patch('langchain_openai.ChatOpenAI',side_effect=AssertionError('Offline suite must mock model transport')):
            yield
