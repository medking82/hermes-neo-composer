"""Exercise the real REST/context/auxiliary-task/ctx.llm chain offline.

Only the account catalog and final provider-client construction are fixtures.
Plugin discovery, trust gate, task defaults, host request construction and result
projection are real. This is not a live provider request or production install.
"""
import asyncio
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class PublicHostBridgeTests(unittest.TestCase):
    def test_rest_owned_context_reaches_real_host_sdk_and_uses_its_task_defaults(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        from agent import auxiliary_client as aux
        package = sys.modules[__package__]
        self.assertIsNotNone(package.__file__)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / 'plugins' / 'neo-next-prompt'
            shutil.copytree(Path(package.__file__).parent, root,
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            home.joinpath('config.yaml').write_text(
                'model:\n  provider: openrouter\n  default: fixture-main\nplugins:\n  enabled:\n    - neo-next-prompt\n')
            settings = home / 'plugin-data/neo-next-prompt/settings.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({'enabled': True, 'providers': ['openrouter'],
                                           'model': 'openrouter/fixture-small', 'fallback': ''}))
            config_before = home.joinpath('config.yaml').read_bytes()
            response = SimpleNamespace(model='fixture-small', choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"suggestion":null}', tool_calls=None), finish_reason='stop')],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))
            create = Mock(return_value=response)
            client = SimpleNamespace(base_url='https://openrouter.ai/api/v1', max_retries=0,
                                     chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            name = 'fixture_owned_rest_api'
            spec = importlib.util.spec_from_file_location(name, root / 'dashboard/plugin_api.py')
            api = importlib.util.module_from_spec(spec)
            sys.modules[name] = api
            token = set_hermes_home_override(home)
            try:
                spec.loader.exec_module(api)
                with (
                    patch('hermes_cli.inventory.build_models_payload', return_value={'providers': [
                        {'slug': 'openrouter', 'models': ['fixture-small'], 'authenticated': True, 'source': 'hermes'}]}),
                    patch.object(aux, '_get_cached_client', return_value=(client, 'fixture-small')),
                ):
                    loaded = api._package()
                    active = loaded.get_service()
                    self.assertEqual(asyncio.run(active.completion_runner(active.complete,
                                     {'history': [{'role': 'user', 'content': 'Offline test.'}]})), '{"suggestion":null}')
                create.assert_called_once()
                self.assertEqual(create.call_args.kwargs['model'], 'fixture-small')
                self.assertNotIn('tools', create.call_args.kwargs)
                self.assertEqual(home.joinpath('config.yaml').read_bytes(), config_before)
            finally:
                reset_hermes_home_override(token)
                sys.modules.pop(name, None)
                for key in list(sys.modules):
                    if key.startswith('_neo_next_prompt_api_') and (getattr(sys.modules[key], '__file__', '') or '').startswith(str(root)):
                        sys.modules.pop(key, None)
