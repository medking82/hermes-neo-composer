"""Public ctx.llm prediction contract; synthetic fixtures, never live inference.

The operator permits host-managed retries and configured fallbacks for prediction.
No primary session changes or compatibility checks based on host source hashes.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class HostedPredictionTests(unittest.TestCase):
    def test_registered_public_sdk_replaces_private_transport_without_changing_main_effort(self):
        package = sys.modules[__package__]
        from . import inventory, llm_once, settings
        selected = {'enabled': True, 'providers': ['openai-codex'],
                    'model': 'openai-codex/fixture-small', 'fallback': ''}
        rows = [{'provider': 'openai-codex', 'model': 'fixture-small', 'account_scope': 'fixture-owner',
                 'available': True, 'text': True}]
        sdk = Mock()
        sdk.complete.return_value = SimpleNamespace(
            text='{"suggestion":null}', provider='fixture-configured-fallback', model='fixture-fallback',
            usage=SimpleNamespace(input_tokens=2, output_tokens=2, total_tokens=4))
        ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=sdk, register_auxiliary_task=Mock())
        snapshot = {'history': [{'role': 'user', 'content': 'Run the relevant tests.'}],
                    'model': 'fixture-main', 'provider': 'openai-codex',
                    'reasoning_config': {'enabled': True, 'effort': 'max'}}
        before = json.dumps(snapshot, sort_keys=True)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(package, '_service', None), patch.object(package, '_owner_home', None),
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
            patch.object(settings, 'load_settings', return_value=selected),
            patch.object(inventory, 'load_catalog', return_value=rows),
            patch.object(package, '_settings_catalog', return_value=rows),
            patch.object(llm_once, 'validate_host', side_effect=AssertionError('legacy byte-pinned adapter reached')),
        ):
            package.register(ctx)
            active = package.get_service()
            self.assertEqual(active.complete(snapshot), '{"suggestion":null}')
        self.assertEqual(before, json.dumps(snapshot, sort_keys=True))
        sdk.complete.assert_called_once()
        request = sdk.complete.call_args.kwargs
        self.assertEqual(request['task'], 'neo_next_prompt')
        self.assertNotIn('provider', request)
        self.assertNotIn('model', request)
        self.assertNotIn('profile', request)
        self.assertNotIn('tools', request)
        self.assertEqual(request['timeout'], 20)
        ctx.register_auxiliary_task.assert_called_once()
        defaults = ctx.register_auxiliary_task.call_args.kwargs['defaults']
        self.assertEqual(defaults['provider'], 'openai-codex')
        self.assertEqual(defaults['model'], 'fixture-small')
        self.assertEqual(defaults['reasoning_effort'], 'low')

    def test_settings_catalog_uses_host_public_inventory_not_private_auth_or_source_pins(self):
        package = sys.modules[__package__]
        from . import inventory, llm_once
        payload = {'providers': [{'slug': 'openai-codex', 'authenticated': True,
                                  'models': ['fixture-small'], 'source': 'provider',
                                  'api_key': 'synthetic-do-not-export'}]}
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(package, '_owner_home', Path(temp)),
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
            patch('hermes_cli.inventory.build_models_payload', return_value=payload) as build,
            patch.object(llm_once, 'validate_host', side_effect=AssertionError('private source hash gate forbidden')),
        ):
            rows = package._settings_catalog()
        self.assertEqual([(r['provider'], r['model']) for r in rows], [('openai-codex', 'fixture-small')])
        self.assertNotIn('synthetic-do-not-export', json.dumps(rows))
        build.assert_called_once()
        self.assertFalse(build.call_args.kwargs['refresh'])
        self.assertFalse(build.call_args.kwargs['probe_custom_providers'])
        self.assertFalse(build.call_args.kwargs['probe_current_custom_provider'])
        self.assertTrue(build.call_args.kwargs['non_blocking_catalogs'])

    def test_api_binds_real_public_context_only_to_its_enabled_profile_package(self):
        import hashlib
        import shutil
        from .dashboard import plugin_api as api
        from hermes_cli.plugins import PluginManager
        package = sys.modules[__package__]
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / 'plugins' / 'neo-next-prompt'
            shutil.copytree(Path(package.__file__).parent, root,
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            name = '_neo_next_prompt_api_' + hashlib.sha256(str(root).encode()).hexdigest()
            manager = PluginManager(scope_key=str(home))
            try:
                with (
                    patch.object(api, '__file__', str(root / 'dashboard' / 'plugin_api.py')),
                    patch('hermes_constants.get_hermes_home', return_value=home),
                    patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
                    patch('hermes_cli.plugins.get_plugin_manager', return_value=manager),
                ):
                    loaded = api._package()
                    self.assertIsNotNone(loaded._context, 'REST entry must not discard the host SDK context')
                    self.assertEqual(loaded._context.plugin_id, 'neo-next-prompt')
                    self.assertEqual(type(loaded._context.llm).__name__, 'PluginLlm')
                    self.assertEqual(loaded._owner_home, home)
                    with patch('hermes_constants.get_hermes_home', return_value=home / 'foreign'):
                        with self.assertRaises(Exception):
                            api._package()
            finally:
                for key in list(sys.modules):
                    if key == name or key.startswith(name + '.'):
                        sys.modules.pop(key, None)

    def test_host_disabling_plugin_revokes_a_captured_service_before_dispatch(self):
        package = sys.modules[__package__]
        selected = {'enabled': True, 'providers': ['openai-codex'], 'model': 'openai-codex/fixture-small', 'fallback': ''}
        rows = [{'provider': 'openai-codex', 'model': 'fixture-small', 'available': True, 'text': True, 'account_scope': 'owner'}]
        cfg = {'plugins': {'enabled': ['neo-next-prompt']}}
        ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()), register_auxiliary_task=Mock())
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value=cfg),
            patch(__package__ + '.settings.load_settings', return_value=selected),
            patch.object(package, '_settings_catalog', return_value=rows),
            patch.object(package, '_context', None), patch.object(package, '_service', None),
            patch.object(package, '_owner_home', None), patch.object(package, '_scope', 'fixture-scope'),
        ):
            package.register(ctx)
            active = package.get_service()
            cfg['plugins']['enabled'].clear()
            with self.assertRaises(PermissionError):
                active.complete({'history': []})
        ctx.llm.complete.assert_not_called()
        ctx.register_auxiliary_task.assert_not_called()

    def test_rest_settings_survive_missing_parser_manager_or_context_capability(self):
        import hashlib
        import shutil
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from .dashboard import plugin_api as api
        package = sys.modules[__package__]
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / 'plugins' / 'neo-next-prompt'
            shutil.copytree(Path(package.__file__).parent, root,
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            name = '_neo_next_prompt_api_' + hashlib.sha256(str(root).encode()).hexdigest()
            app = FastAPI()
            app.include_router(api.router)
            cases = [
                ('parse_manifest_file', {'side_effect': TypeError('fixture parser signature changed')}),
                ('parse_manifest_file', {'return_value': None}),
                ('get_plugin_manager', {'side_effect': AttributeError('fixture manager unavailable')}),
                ('get_plugin_manager', {'side_effect': TypeError('fixture manager signature changed')}),
                ('get_plugin_manager', {'return_value': None}),
                ('PluginContext', {'side_effect': TypeError('fixture context signature changed')}),
            ]
            for target, effect in cases:
                with self.subTest(capability=target, effect=str(effect)):
                    try:
                        with (
                            patch.object(api, '__file__', str(root / 'dashboard' / 'plugin_api.py')),
                            patch('hermes_constants.get_hermes_home', return_value=home),
                            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
                            patch('hermes_cli.inventory.build_models_payload', return_value={'providers': []}),
                            patch('hermes_cli.plugins.' + target, **effect),
                            TestClient(app, raise_server_exceptions=False) as client,
                        ):
                            response = client.get('/settings')
                            self.assertEqual(response.status_code, 200, response.text)
                            view = response.json()
                            response = client.post('/settings', json={'scope': view['scope'],
                                                   'settings': {**view['settings'], 'enabled': False}})
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertFalse(response.json()['settings']['enabled'])
                            self.assertEqual(client.get('/health').status_code, 404)
                    finally:
                        for key in list(sys.modules):
                            if key == name or key.startswith(name + '.'):
                                sys.modules.pop(key, None)

    def test_rest_host_without_context_constructor_keeps_profile_settings_available(self):
        from . import sdk_host
        from .settings import save_settings
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / 'plugins' / 'neo-next-prompt'
            root.mkdir(parents=True)
            root.joinpath('plugin.yaml').write_text('name: neo-next-prompt\nversion: fixture\n')
            with (
                patch('hermes_constants.get_hermes_home', return_value=home),
                patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
                patch('hermes_cli.plugins.PluginContext', side_effect=TypeError('fixture missing public constructor contract')),
            ):
                self.assertIsNone(sdk_host.create_context(root))

    def test_owner_change_during_task_preparation_refuses_dispatch(self):
        from . import sdk_llm
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            plan = {'route': {'provider': 'openai-codex', 'model': 'fixture-small'}, 'settings': {}}
            ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()), register_auxiliary_task=Mock())
            with patch('hermes_constants.get_hermes_home', side_effect=[home, home / 'foreign']):
                with self.assertRaises(PermissionError):
                    sdk_llm.complete({'history': []}, context=ctx, owner_home=home,
                                     expected_plan=plan, current_plan=lambda: plan)
            ctx.llm.complete.assert_not_called()

    def test_reregistered_context_revokes_old_service_dispatch(self):
        package = sys.modules[__package__]
        selected = {'enabled': True, 'providers': ['openai-codex'], 'model': 'openai-codex/fixture-small', 'fallback': ''}
        rows = [{'provider': 'openai-codex', 'model': 'fixture-small', 'available': True, 'text': True, 'account_scope': 'owner'}]
        old = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()), register_auxiliary_task=Mock())
        new = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()), register_auxiliary_task=Mock())
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
            patch(__package__ + '.settings.load_settings', return_value=selected),
            patch.object(package, '_settings_catalog', return_value=rows),
            patch.object(package, '_context', None), patch.object(package, '_service', None),
            patch.object(package, '_owner_home', None), patch.object(package, '_scope', 'fixture-scope'),
        ):
            package.register(old)
            active = package.get_service()
            package.register(new)
            with self.assertRaises(ValueError):
                active.complete({'history': []})
        old.llm.complete.assert_not_called()
        new.llm.complete.assert_not_called()

    def test_routing_metadata_excludes_opaque_url_credentials_and_paths(self):
        from .sdk_catalog import routing_metadata
        first = routing_metadata({'provider': 'fixture-provider',
                                  'base_url': 'https://user:fixture-password@fixture.invalid/fixture-path-key?key=fixture-query',
                                  'api_key': 'fixture-inline-key',
                                  'extra_body': {'headers': {'X-Fixture': 'fixture-private-header'}}})
        second = routing_metadata({'provider': 'fixture-provider',
                                   'base_url': 'https://other:fixture-rotated@fixture.invalid/fixture-rotated-path?key=fixture-new-query',
                                   'api_key': 'fixture-new-inline',
                                   'extra_body': {'headers': {'X-Fixture': 'fixture-new-header'}}})
        self.assertEqual(first, second)
        self.assertNotIn('fixture-password', json.dumps(first))
        self.assertNotIn('fixture-path-key', json.dumps(first))
        self.assertNotEqual(first, routing_metadata({'provider': 'fixture-provider',
                                                     'base_url': 'https://other.invalid/v1'}))

    def test_inline_credentials_never_feed_catalog_scope_or_service_revision(self):
        from . import sdk_catalog
        package = sys.modules[__package__]
        config = {
            'plugins': {'enabled': ['neo-next-prompt']},
            'model': {'provider': 'openai-codex', 'api_key': 'fixture-inline-model'},
            'providers': {'openai-codex': {'api_key': 'fixture-inline-provider'}},
            'custom_providers': [{'name': 'fixture-custom', 'api_key': 'fixture-inline-custom'}],
            'auxiliary': {'neo_next_prompt': {'model': 'fixture-small', 'api_key': 'fixture-inline-task',
                                            'extra_body': {'headers': {'X-Fixture': 'fixture-inline-body'}}}},
        }
        payload = {'providers': [{'slug': 'openai-codex', 'models': ['fixture-small'],
                                  'authenticated': True, 'source': 'hermes'}]}
        selected = {'enabled': True, 'providers': ['openai-codex'],
                    'model': 'openai-codex/fixture-small', 'fallback': ''}
        ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=SimpleNamespace(complete=Mock()),
                              register_auxiliary_task=Mock())
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value=config),
            patch('hermes_cli.inventory.build_models_payload', return_value=payload),
            patch(__package__ + '.settings.load_settings', return_value=selected),
            patch.object(package, '_context', None), patch.object(package, '_service', None),
            patch.object(package, '_owner_home', None), patch.object(package, '_scope', 'fixture-scope'),
        ):
            home = Path(temp)
            home.joinpath('config.yaml').write_text('fixture-metadata-epoch-one')
            package.register(ctx)
            fixed_rows = sdk_catalog.load_catalog()
            first_scope = fixed_rows[0]['account_scope']
            with patch.object(package, '_settings_catalog', return_value=fixed_rows):
                first_revision = package.get_service().route_revision
                blocks = [config['model'], config['providers']['openai-codex'],
                          config['custom_providers'][0], config['auxiliary']['neo_next_prompt']]
                for index, block in enumerate(blocks):
                    block['api_key'] = 'fixture-replaced-inline-' + str(index)
                    with self.subTest(boundary='catalog', location=index):
                        self.assertEqual(first_scope, sdk_catalog.load_catalog()[0]['account_scope'])
                    with self.subTest(boundary='revision', location=index):
                        self.assertEqual(first_revision, package.get_service().route_revision)
                config['auxiliary']['neo_next_prompt']['extra_body']['headers']['X-Fixture'] = 'fixture-body-replaced'
                self.assertEqual(first_scope, sdk_catalog.load_catalog()[0]['account_scope'])
                self.assertEqual(first_revision, package.get_service().route_revision)
            # Real saved-config changes still invalidate, through metadata only.
            home.joinpath('config.yaml').write_text('fixture-metadata-epoch-two-is-longer')
            self.assertNotEqual(first_scope, sdk_catalog.load_catalog()[0]['account_scope'])

    def test_native_endpoint_and_policy_reference_changes_invalidate_opaque_catalog_scope(self):
        from . import sdk_catalog
        config = {'model': {'provider': 'openai-codex', 'base_url': 'https://fixture-one.invalid'},
                  'providers': {'openai-codex': {'api_key_ref': 'fixture-reference-one'}}}
        payload = {'providers': [{'slug': 'openai-codex', 'models': ['fixture-small'], 'authenticated': True, 'source': 'hermes'}]}
        with (
            tempfile.TemporaryDirectory() as temp,
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value=config),
            patch('hermes_cli.inventory.build_models_payload', return_value=payload),
        ):
            first = sdk_catalog.load_catalog()[0]
            config['model']['base_url'] = 'https://fixture-two.invalid'
            second = sdk_catalog.load_catalog()[0]
            self.assertNotEqual(first['account_scope'], second['account_scope'])
            config['providers']['openai-codex']['api_key_ref'] = 'fixture-reference-two'
            third = sdk_catalog.load_catalog()[0]
            self.assertNotEqual(second['account_scope'], third['account_scope'])
            self.assertNotIn('fixture-reference-two', json.dumps(third))
            self.assertNotIn('fixture-two.invalid', json.dumps(third))


if __name__ == '__main__':
    unittest.main()
