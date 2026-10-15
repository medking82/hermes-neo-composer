"""Prediction must not inherit or be vetoed by an unrelated main-provider endpoint."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from .llm_once import complete


class PredictionIndependenceTests(unittest.TestCase):
    def test_other_known_main_provider_endpoint_does_not_block_explicit_prediction(self):
        from agent import auxiliary_client as aux
        config = {'model': {'provider': 'anthropic', 'default': 'main-only-model',
                            'base_url': 'https://unrelated-main.invalid/v1'}}
        original = copy.deepcopy(config)
        plan = {'route': {'provider': 'openai-codex', 'model': 'selected-small'},
                'reason': 'Explicit prediction model.', 'settings': {}}
        endpoint = 'https://chatgpt.com/backend-api/codex'
        request = SimpleNamespace(client=SimpleNamespace(max_retries=0, base_url=endpoint),
                                  kwargs={'model': 'selected-small'}, request_provider='openai-codex',
                                  resolved_api_mode='chat_completions', base_info=endpoint,
                                  resolved_base_url=endpoint)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"suggestion":"Explain one test example"}', tool_calls=None))])
        with patch('hermes_cli.config.load_config_readonly', return_value=config), \
             patch('package.llm_once.prediction_plan', return_value=plan), \
             patch.object(aux, '_plan_aux_call', return_value=(request, {}, {})) as prepare, \
             patch.object(aux, '_relay_sync_completion', return_value=response) as send:
            self.assertEqual(complete({'history': []}), '{"suggestion":"Explain one test example"}')
        self.assertEqual(config, original)
        self.assertEqual(prepare.call_args.kwargs['provider'], 'openai-codex')
        self.assertIsNone(prepare.call_args.kwargs['base_url'])
        self.assertIsNone(prepare.call_args.kwargs['api_key'])
        self.assertIsNone(prepare.call_args.kwargs['main_runtime'])
        send.assert_called_once()


    def test_same_or_ambiguous_main_endpoint_still_fails_closed(self):
        from agent import auxiliary_client as aux
        cases = [('openai-codex', 'openai-codex'), ('openai', 'openai-api'),
                 ('openai-api', 'openai'), ('google', 'gemini'), ('gemini', 'google'),
                 ('', 'openai-codex'), ('auto', 'openai-codex'), ('custom', 'openai-codex'),
                 ('unknown-provider', 'openai-codex')]
        for main, prediction in cases:
            plan = {'route': {'provider': prediction, 'model': 'selected-small'},
                    'reason': 'Explicit prediction model.', 'settings': {}}
            with self.subTest(main=main, prediction=prediction), \
                 patch('hermes_cli.config.load_config_readonly', return_value={
                     'model': {'provider': main, 'base_url': 'https://custom.invalid/v1'}}), \
                 patch('package.llm_once.prediction_plan', return_value=plan), \
                 patch.object(aux, '_plan_aux_call') as prepare, \
                 patch.object(aux, '_relay_sync_completion') as send:
                with self.assertRaisesRegex(ValueError, 'custom endpoint'):
                    complete({'history': []})
                prepare.assert_not_called()
                send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
