"""Regression: an official default endpoint is not a custom destination.

The main config may carry model.base_url that equals the provider's official
registry inference URL. That is the normal default, not a custom endpoint, and
must not exclude the provider from the prediction catalog (inventory) nor veto
same-provider prediction dispatch (llm_once). Custom, unknown-registry and
env-var endpoints stay closed.
"""
import json
import os
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

OFFICIAL = 'https://chatgpt.com/backend-api/codex'


class OfficialDefaultEndpointTests(unittest.TestCase):
    def catalog(self, model_config, provider='openai-codex'):
        from .inventory import load_catalog
        with TemporaryDirectory() as directory, ExitStack() as stack:
            home = Path(directory)
            stack.enter_context(patch('hermes_constants.get_hermes_home', return_value=home))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch('hermes_cli.config.load_config_readonly', return_value={'model': model_config}))
            stack.enter_context(patch('hermes_cli.config.get_env_value_prefer_dotenv', return_value=''))
            stack.enter_context(patch('hermes_cli.models._load_provider_models_cache',
                                      return_value={provider: {'fp': 'owner', 'at': time.time(), 'models': ['gpt-6-luna']}}))
            stack.enter_context(patch('hermes_cli.models._credential_fingerprint', return_value='owner'))
            stack.enter_context(patch('hermes_cli.auth._load_auth_store', return_value={}))
            stack.enter_context(patch('hermes_cli.auth._env_secret', return_value=False))
            stack.enter_context(patch('hermes_cli.auth._global_auth_file_path', return_value=None))
            stack.enter_context(patch('hermes_cli.codex_models.codex_catalog_credential_identity', return_value='active'))
            return load_catalog()

    def test_official_default_base_url_keeps_main_provider_catalog(self):
        rows = self.catalog({'provider': 'openai-codex', 'base_url': OFFICIAL})
        self.assertTrue(rows, 'Official default endpoint must not exclude the main provider catalog')
        self.assertEqual(rows[0]['provider'], 'openai-codex')
        self.assertEqual(rows[0]['model'], 'gpt-6-luna')

    def test_custom_same_provider_base_url_stays_closed(self):
        self.assertEqual(self.catalog({'provider': 'openai-codex', 'base_url': 'https://custom.example.invalid/v1'}), [])

    def test_official_default_trailing_slash_variant_is_not_custom(self):
        rows = self.catalog({'provider': 'openai-codex', 'base_url': OFFICIAL + '/'})
        self.assertTrue(rows, 'Trailing-slash variant of the official URL is still the default')

    def test_complete_accepts_official_default_endpoint(self):
        from types import SimpleNamespace
        from agent import auxiliary_client as aux
        from .llm_once import complete
        plan = {'route': {'provider': 'openai-codex', 'model': 'selected-small'},
                'reason': 'Explicit prediction model.', 'settings': {}}
        request = SimpleNamespace(client=SimpleNamespace(max_retries=0, base_url=OFFICIAL, chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: None))),
                                  kwargs={'model': 'selected-small'}, request_provider='openai-codex',
                                  resolved_api_mode='chat_completions', base_info=OFFICIAL, resolved_base_url=OFFICIAL)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"suggestion":"运行回归测试"}', tool_calls=None))])
        with patch('package.llm_once.prediction_plan', return_value=plan), patch('package.llm_once.validate_host'), \
                patch('hermes_cli.config.load_config_readonly', return_value={'model': {'provider': 'openai-codex', 'base_url': OFFICIAL}}), \
                patch.object(aux, '_plan_aux_call', autospec=True, return_value=(request, {}, {})), \
                patch.object(aux, '_relay_sync_completion', autospec=True, return_value=response):
            self.assertEqual(complete({'history': [{'role': 'user', 'content': '修复然后测试'}]}, expected_plan=plan),
                             '{"suggestion":"运行回归测试"}')

    def test_complete_still_rejects_custom_same_provider_endpoint(self):
        from types import SimpleNamespace
        from agent import auxiliary_client as aux
        from .llm_once import complete
        plan = {'route': {'provider': 'openai-codex', 'model': 'selected-small'},
                'reason': 'Explicit prediction model.', 'settings': {}}
        with patch('package.llm_once.prediction_plan', return_value=plan), patch('package.llm_once.validate_host'), \
                patch('hermes_cli.config.load_config_readonly',
                      return_value={'model': {'provider': 'openai-codex', 'base_url': 'https://custom.example.invalid/v1'}}), \
                patch.object(aux, '_plan_aux_call', autospec=True) as prepare:
            with self.assertRaises(ValueError):
                complete({'history': []}, expected_plan=plan)
            prepare.assert_not_called()

    def test_complete_still_rejects_unknown_main_provider_endpoint(self):
        from types import SimpleNamespace
        from agent import auxiliary_client as aux
        from .llm_once import complete
        plan = {'route': {'provider': 'openai-codex', 'model': 'selected-small'},
                'reason': 'Explicit prediction model.', 'settings': {}}
        with patch('package.llm_once.prediction_plan', return_value=plan), patch('package.llm_once.validate_host'), \
                patch('hermes_cli.config.load_config_readonly',
                      return_value={'model': {'provider': 'unknown-provider-x', 'base_url': 'https://anything.example/v1'}}), \
                patch.object(aux, '_plan_aux_call', autospec=True) as prepare:
            with self.assertRaises(ValueError):
                complete({'history': []}, expected_plan=plan)
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
