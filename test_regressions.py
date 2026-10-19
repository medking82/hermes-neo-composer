"""Regressions from independent review; use isolated settings and no live inference."""
import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RegressionTests(unittest.TestCase):
    def test_public_catalog_never_reads_credentials_or_infers_oauth_billing(self):
        import builtins
        import json
        import os
        from .inventory import load_catalog
        with TemporaryDirectory() as directory:
            home = Path(directory)
            auth = home / 'auth.json'
            auth.write_text('fixture-first-auth')
            original_stat = auth.stat()
            meta = {'anthropic': {'models': {'small': {'modalities': {'input': ['text'], 'output': ['text']}, 'limit': {'context': 16000, 'output': 2048}, 'cost': {'input': 1, 'output': 1}}}}}
            home.joinpath('models_dev_cache.json').write_text(json.dumps(meta))
            payload = {'providers': [{'slug': 'anthropic', 'authenticated': True, 'models': ['small'], 'source': 'hermes'}]}
            protected = {path.resolve() for path in (auth, home / '.env', home / '.anthropic_oauth.json',
                         Path.home() / '.codex/auth.json', Path.home() / '.claude/.credentials.json')}
            path_open, builtin_open = Path.open, builtins.open
            def guard(original):
                def open_file(path, *args, **kwargs):
                    if isinstance(path, (str, os.PathLike)) and Path(path).resolve() in protected:
                        raise AssertionError('Plugin opened credential contents')
                    return original(path, *args, **kwargs)
                return open_file
            def catalog():
                with patch.object(Path, 'open', guard(path_open)), patch('builtins.open', guard(builtin_open)):
                    return load_catalog()[0]
            with patch('hermes_constants.get_hermes_home', return_value=home), patch('hermes_cli.config.load_config_readonly', return_value={}), patch('hermes_cli.inventory.build_models_payload', return_value=payload):
                first = catalog()
                self.assertEqual(first['billing'], 'unknown')
                self.assertFalse(first['priced'])
                auth.write_text('fixture-other-auth')
                self.assertEqual(auth.stat().st_size, original_stat.st_size)
                os.utime(auth, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                second = catalog()
                self.assertEqual(first['account_scope'], second['account_scope'])
                auth.write_text('fixture-auth-metadata-change-is-longer')
                third = catalog()
                self.assertNotEqual(first['account_scope'], third['account_scope'])
                self.assertNotIn('fixture-other-auth', json.dumps(third))

    def test_settings_refuse_symlinked_profile_data(self):
        from .settings import save_settings, DEFAULTS
        with TemporaryDirectory() as directory:
            home = Path(directory) / 'home'; outside = Path(directory) / 'outside'
            home.mkdir(); outside.mkdir(); (home / 'plugin-data').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): save_settings(home, DEFAULTS)
            self.assertEqual(list(outside.iterdir()), [])

    def test_price_metadata_does_not_invalidate_service_and_plan_is_bound(self):
        package = importlib.import_module(__package__)
        from types import SimpleNamespace
        from unittest.mock import Mock
        with TemporaryDirectory() as directory:
            home = Path(directory)
            a = {'provider': 'api', 'model': 'small', 'account_scope': 'owner', 'input_cost': 1, 'available': True, 'text': True}
            b = {**a, 'input_cost': None}
            settings = {'enabled': True, 'providers': ['api'], 'model': 'api/small', 'fallback': ''}
            ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()), register_auxiliary_task=Mock())
            with patch.object(package, '_owner_home', home), patch.object(package, '_context', ctx), patch.object(package, '_service', None), patch('hermes_constants.get_hermes_home', return_value=home), patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}), patch(__package__ + '.settings.load_settings', return_value=settings), patch.object(package, '_settings_catalog', side_effect=[[a], [b]]), patch(__package__ + '.sdk_llm.complete') as completion:
                first = package.get_service()
                self.assertIs(first, package.get_service())
                first.complete({'history': []})
                self.assertEqual(completion.call_args.kwargs['expected_plan']['route'], a)
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
