"""SDK prediction/settings are independent of optional native Steering seams."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from . import inventory, llm_once
from .dashboard import plugin_api as api


PREDICTION_PATHS = (
    'agent/anthropic_credentials.py', 'hermes_constants.py', 'hermes_cli/auth.py',
    'hermes_cli/codex_models.py', 'hermes_cli/models.py',
    'hermes_cli/model_switch_providers.py', 'agent/models_dev.py',
    'agent/auxiliary_client.py', 'tui_gateway/server.py', 'tui_gateway/ws.py',
    'hermes_cli/web_server_dashboard.py', 'agent/agent_runtime_helpers.py',
)


class ComponentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def host_fixture(self):
        root = self.home / 'host'
        pins = {}
        for name in (*PREDICTION_PATHS, 'agent/interrupt_control.py'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture-host-interface\n')
            pins[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = {'pins': pins, 'prediction_pins': {name: [pins[name]] for name in PREDICTION_PATHS}}
        package = self.home / 'plugin'
        package.mkdir()
        (package / 'host-compat.json').write_text(json.dumps(metadata))
        return root, package, metadata

    def test_native_drift_does_not_disable_verified_prediction_dependencies(self):
        from agent import auxiliary_client as aux
        root, package, metadata = self.host_fixture()
        (root / 'agent/interrupt_control.py').write_text('fixture-native-interface-changed\n')
        with patch.object(aux, '__file__', str(root / 'agent/auxiliary_client.py')), patch.object(llm_once, '__file__', str(package / 'llm_once.py')):
            error = None
            try:
                llm_once.validate_host()
            except RuntimeError as exc:
                error = str(exc)
            self.assertIsNone(error, 'Native-only changes must not block the verified prediction adapter')
        self.assertNotEqual(metadata['pins']['agent/interrupt_control.py'], hashlib.sha256((root / 'agent/interrupt_control.py').read_bytes()).hexdigest())

    def test_every_prediction_dependency_still_fails_closed_on_unknown_bytes(self):
        from agent import auxiliary_client as aux
        root, package, _metadata = self.host_fixture()
        for name in PREDICTION_PATHS:
            with self.subTest(path=name):
                file = root / name
                before = file.read_bytes()
                file.write_text('fixture-unapproved-prediction-interface\n')
                with patch.object(aux, '__file__', str(root / 'agent/auxiliary_client.py')), patch.object(llm_once, '__file__', str(package / 'llm_once.py')):
                    with self.assertRaises(RuntimeError):
                        llm_once.validate_host()
                file.write_bytes(before)

    def test_settings_survive_adapter_failure_but_reject_foreign_profile_and_stale_scope(self):
        package = sys.modules[__package__]
        root = self.home / 'plugins' / 'neo-next-prompt'
        name = '_neo_next_prompt_api_' + hashlib.sha256(str(root).encode()).hexdigest()
        app = FastAPI()
        app.include_router(api.router)
        with (
            patch.dict(sys.modules, {name: package}),
            patch.object(api, '__file__', str(root / 'dashboard' / 'plugin_api.py')),
            patch.object(package, '_owner_home', self.home),
            patch('hermes_constants.get_hermes_home', return_value=self.home),
            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
            patch.object(inventory, 'load_catalog', return_value=[]) as catalog,
            patch.object(llm_once, 'validate_host', side_effect=RuntimeError('fixture prediction adapter unavailable')) as adapter,
            TestClient(app) as client,
        ):
            response = client.get('/settings')
            self.assertEqual(response.status_code, 200)
            view = response.json()
            self.assertFalse(view['settings']['enabled'])
            self.assertEqual(client.post('/settings', json={'scope': view['scope'], 'settings': view['settings']}).status_code, 200)
            self.assertEqual(client.post('/settings', json={'scope': 'fixture-stale-scope', 'settings': view['settings']}).status_code, 422)
            catalog.assert_not_called()
            adapter.side_effect = None
            catalog.return_value = [{'provider': 'openai-codex', 'model': 'fixture-model', 'account_scope': 'fixture-owner'}]
            available = client.get('/settings')
            self.assertEqual(available.status_code, 200)
            self.assertEqual(available.json()['catalog'], [{'provider': 'openai-codex', 'model': 'fixture-model'}])
            catalog.assert_called_once()
            with patch('hermes_constants.get_hermes_home', return_value=self.home / 'other-profile'):
                with self.assertRaises(PermissionError):
                    package.validate_scope()
