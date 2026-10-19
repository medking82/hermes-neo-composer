"""Public SDK compatibility and optional native enhancements are independent."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from . import sdk_catalog, llm_once
from .dashboard import plugin_api as api


class ComponentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def context(self):
        return SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()),
                               register_auxiliary_task=Mock())

    def test_native_and_prediction_source_drift_do_not_gate_a_supported_public_sdk(self):
        ctx = self.context()
        # Public SDK capability, not any 12/21-file private-source byte inventory.
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('source byte pin reached')):
            llm_once.validate_host(ctx)
        ctx.llm.complete.assert_not_called()

    def test_missing_changed_or_foreign_sdk_contract_still_fails_closed(self):
        for change in ('identity', 'llm', 'complete', 'task_registration'):
            ctx = self.context()
            if change == 'identity': ctx.plugin_id = 'foreign'
            if change == 'llm': ctx.llm = None
            if change == 'complete': ctx.llm.complete = None
            if change == 'task_registration': ctx.register_auxiliary_task = None
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                llm_once.validate_host(ctx)

    def test_settings_survive_adapter_failure_but_reject_foreign_profile_and_stale_scope(self):
        package = sys.modules[__package__]
        root = self.home / 'plugins' / 'neo-next-prompt'
        name = '_neo_next_prompt_api_' + hashlib.sha256(str(root).encode()).hexdigest()
        app = FastAPI()
        app.include_router(api.router)
        with (
            patch.dict(sys.modules, {name: package}),
            patch.object(api, '__file__', str(root / 'dashboard' / 'plugin_api.py')),
            patch.object(package, '_owner_home', self.home), patch.object(package, '_context', None),
            patch('hermes_constants.get_hermes_home', return_value=self.home),
            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
            patch.object(sdk_catalog, 'load_catalog', side_effect=RuntimeError('fixture SDK catalog unavailable')) as catalog,
            TestClient(app) as client,
        ):
            response = client.get('/settings')
            self.assertEqual(response.status_code, 200)
            view = response.json()
            self.assertFalse(view['settings']['enabled'])
            self.assertEqual(client.post('/settings', json={'scope': view['scope'], 'settings': view['settings']}).status_code, 200)
            self.assertEqual(client.post('/settings', json={'scope': 'fixture-stale-scope', 'settings': view['settings']}).status_code, 422)
            catalog.side_effect = None
            catalog.return_value = [{'provider': 'openai-codex', 'model': 'fixture-model', 'account_scope': 'fixture-owner'}]
            available = client.get('/settings')
            self.assertEqual(available.status_code, 200)
            self.assertEqual(available.json()['catalog'], [{'provider': 'openai-codex', 'model': 'fixture-model'}])
            self.assertNotIn('fixture-owner', json.dumps(available.json()))
            with patch('hermes_constants.get_hermes_home', return_value=self.home / 'other-profile'):
                with self.assertRaises(PermissionError):
                    package.validate_scope()
