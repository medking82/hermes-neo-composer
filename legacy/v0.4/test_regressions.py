"""Regressions from independent review; use isolated settings and no live inference."""
import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RegressionTests(unittest.TestCase):
    def test_real_catalog_path_reads_token_type_not_presence_boolean(self):
        import json, time
        from .inventory import load_catalog
        with TemporaryDirectory() as directory:
            home = Path(directory)
            home.joinpath('auth.json').write_text('{}')
            meta = {'anthropic': {'models': {'small': {'modalities': {'input': ['text'], 'output': ['text']}, 'limit': {'context': 16000, 'output': 2048}, 'cost': {'input': 1, 'output': 1}}}}}
            home.joinpath('models_dev_cache.json').write_text(json.dumps(meta))
            cache = {'anthropic': {'fp': 'owner', 'at': time.time(), 'models': ['small']}}
            token = 'sk-ant-' + 'oat-fixture'
            with patch('hermes_constants.get_hermes_home', return_value=home), patch('hermes_cli.config.load_config_readonly', return_value={}), patch('hermes_cli.config.get_env_value_prefer_dotenv', side_effect=lambda name: token if name == 'ANTHROPIC_API_KEY' else ''), patch('hermes_cli.models._load_provider_models_cache', return_value=cache), patch('hermes_cli.models._credential_fingerprint', return_value='owner'), patch('hermes_cli.auth._load_auth_store', return_value={}), patch.dict('os.environ', {'ANTHROPIC_API_KEY': token, 'ANTHROPIC_TOKEN': '', 'CLAUDE_CODE_OAUTH_TOKEN': ''}):
                self.assertEqual(load_catalog()[0]['billing'], 'unknown')
                with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'different-launch-profile'}):
                    self.assertEqual(load_catalog(), [], 'Host raw-env fingerprint cannot certify another profile key')

    def test_settings_refuse_symlinked_profile_data(self):
        from .settings import save_settings, DEFAULTS
        with TemporaryDirectory() as directory:
            home = Path(directory) / 'home'; outside = Path(directory) / 'outside'
            home.mkdir(); outside.mkdir(); (home / 'plugin-data').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): save_settings(home, DEFAULTS)
            self.assertEqual(list(outside.iterdir()), [])

    def test_price_metadata_does_not_invalidate_service_and_plan_is_bound(self):
        package = importlib.import_module(__package__)
        with TemporaryDirectory() as directory:
            home = Path(directory)
            a = {'route': {'provider': 'api', 'model': 'small', 'account_scope': 'owner', 'input_cost': 1}, 'settings': {'enabled': True}, 'reason': 'price fresh'}
            b = {**a, 'route': {**a['route'], 'input_cost': None}, 'reason': 'price stale'}
            with patch.object(package, '_owner_home', home), patch.object(package, '_service', None), patch('hermes_constants.get_hermes_home', return_value=home), patch(__package__ + '.llm_once.validate_host'), patch('hermes_cli.config.load_config_readonly', return_value={}), patch(__package__ + '.llm_once.prediction_plan', side_effect=[a, b]), patch(__package__ + '.llm_once.complete') as completion:
                first = package.get_service()
                self.assertIs(first, package.get_service())
                first.complete({'history': []})
                self.assertEqual(completion.call_args.kwargs['expected_plan'], a)
                self.assertEqual(completion.call_args.kwargs['owner_home'], home)

    def test_billing_never_infers_subscription_or_pool_as_dollar_price(self):
        inventory = importlib.import_module(__package__ + '.inventory')
        self.assertTrue(hasattr(inventory, 'billing_kind'))
        for key, other, expected in [('', False, 'unknown'), ('sk-ant-' + 'oat-test', False, 'unknown'), ('fixture-key', True, 'unknown'), ('sk-ant-api-synthetic', False, 'usd')]:
            self.assertEqual(inventory.billing_kind('anthropic', key, other), expected)
        self.assertEqual(inventory.billing_kind('openai-codex', 'fixture-key', False), 'unknown')

    def test_unbound_or_unknown_capability_catalog_is_not_ranked(self):
        from .inventory import catalog_rows
        entry = {'fp': '', 'at': 100, 'models': ['small']}
        meta = {'small': {'limit': {'context': 16000, 'output': 2048}, 'cost': {'input': 1, 'output': 1}}}
        self.assertEqual(catalog_rows('api', entry, '', meta, now=101, price_fresh=True, billing='usd'), [])
        rows = catalog_rows('api', {**entry, 'fp': 'owner'}, 'owner', meta, now=101, price_fresh=True, billing='usd')
        self.assertFalse(rows[0]['verified_text'])
        from .routing import select_route
        self.assertIsNone(select_route({'enabled': True, 'providers': ['api']}, rows)['route'])

    def test_disabled_plan_never_reads_account_catalog(self):
        from .llm_once import prediction_plan
        from .settings import DEFAULTS
        with patch(__package__ + '.settings.load_settings', return_value=DEFAULTS), patch(__package__ + '.inventory.load_catalog', side_effect=AssertionError('Disabled feature read catalog')):
            self.assertIsNone(prediction_plan()['route'])

    def test_disable_remains_available_when_saved_provider_disappears(self):
        package = importlib.import_module(__package__)
        from .settings import load_settings, save_settings
        with TemporaryDirectory() as directory:
            home = Path(directory)
            old = {'enabled': True, 'providers': ['missing'], 'model': '', 'fallback': ''}
            save_settings(home, old)
            with patch.object(package, '_owner_home', home), patch.object(package, 'validate_scope'), patch(__package__ + '.inventory.load_catalog', return_value=[]):
                package.update_settings({**old, 'enabled': False}, package._scope)
            self.assertFalse(load_settings(home)['enabled'])
