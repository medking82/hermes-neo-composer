"""Main-session routing is not rewritten by a prediction's host-owned task."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from .llm_once import complete


class PredictionIndependenceTests(unittest.TestCase):
    def test_other_main_provider_config_is_neither_forwarded_nor_modified(self):
        config = {'model': {'provider': 'anthropic', 'default': 'fixture-main',
                           'base_url': 'https://unrelated-main.invalid/v1', 'reasoning_effort': 'max'}}
        original = copy.deepcopy(config)
        sdk = Mock()
        sdk.complete.return_value = SimpleNamespace(text='{"suggestion":null}')
        ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=sdk, register_auxiliary_task=Mock())
        plan = {'route': {'provider': 'openai-codex', 'model': 'fixture-small'}, 'settings': {}}
        with (
            TemporaryDirectory() as temp,
            patch('hermes_constants.get_hermes_home', return_value=Path(temp)),
            patch('hermes_cli.config.load_config_readonly', return_value=config),
        ):
            complete({'history': []}, context=ctx, owner_home=Path(temp), expected_plan=plan, current_plan=lambda: plan)
        self.assertEqual(config, original)
        self.assertEqual(ctx.register_auxiliary_task.call_args.kwargs['defaults']['provider'], 'openai-codex')
        for key in ('provider', 'model', 'base_url', 'api_key', 'profile', 'agent_id'):
            self.assertNotIn(key, sdk.complete.call_args.kwargs)

    def test_host_trust_denial_is_not_retried_with_a_private_or_main_model_fallback(self):
        sdk = Mock()
        sdk.complete.side_effect = PermissionError('fixture host trust gate denied')
        ctx = SimpleNamespace(plugin_id='neo-next-prompt', llm=sdk, register_auxiliary_task=Mock())
        plan = {'route': {'provider': 'openai-codex', 'model': 'fixture-small'}, 'settings': {}}
        with TemporaryDirectory() as temp, patch('hermes_constants.get_hermes_home', return_value=Path(temp)):
            with self.assertRaises(PermissionError):
                complete({'history': []}, context=ctx, owner_home=Path(temp), expected_plan=plan, current_plan=lambda: plan)
        sdk.complete.assert_called_once()


if __name__ == '__main__':
    unittest.main()
