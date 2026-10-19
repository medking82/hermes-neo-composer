"""Public SDK adapter regressions. Host retries/fallbacks are operator-permitted.

Private transport, byte pins and plugin-owned retry ladders are retired.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from .llm_once import complete


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.scope = patch('hermes_constants.get_hermes_home', return_value=self.home)
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.plan = {'route': {'provider': 'openai-codex', 'model': 'fixture-small', 'account_scope': 'owner'},
                     'settings': {'enabled': True}, 'reason': 'Explicit prediction route.'}
        self.sdk = Mock()
        self.sdk.complete.return_value = SimpleNamespace(text='{"suggestion":null}', provider='openai-codex',
            model='fixture-small', usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        self.context = SimpleNamespace(plugin_id='neo-next-prompt', llm=self.sdk, register_auxiliary_task=Mock())
        self.snapshot = {'history': [], 'model': 'fixture-main', 'reasoning_config': {'effort': 'max'}}

    def invoke(self, **changes):
        args = dict(context=self.context, owner_home=self.home, expected_plan=self.plan, current_plan=lambda: self.plan)
        args.update(changes)
        return complete(self.snapshot, **args)

    def test_uses_selected_low_cost_task_without_mutating_primary_session_or_using_tools(self):
        before = json.dumps(self.snapshot, sort_keys=True)
        self.assertEqual(self.invoke(), '{"suggestion":null}')
        self.assertEqual(before, json.dumps(self.snapshot, sort_keys=True))
        defaults = self.context.register_auxiliary_task.call_args.kwargs['defaults']
        self.assertEqual(defaults['model'], 'fixture-small')
        self.assertEqual(defaults['reasoning_effort'], 'low')
        request = self.sdk.complete.call_args.kwargs
        self.assertEqual(request['task'], 'neo_next_prompt')
        for key in ('tools', 'provider', 'model', 'profile', 'api_key', 'base_url'):
            self.assertNotIn(key, request)

    def test_missing_or_foreign_sdk_capability_fails_before_transport(self):
        for context in (None, SimpleNamespace(plugin_id='foreign'),
                        SimpleNamespace(plugin_id='neo-next-prompt', llm=None),
                        SimpleNamespace(plugin_id='neo-next-prompt', llm=self.sdk, register_auxiliary_task=None)):
            with self.subTest(context=context), self.assertRaises(RuntimeError):
                self.invoke(context=context)
        self.sdk.complete.assert_not_called()

    def test_sdk_failure_propagates_without_plugin_owned_retry(self):
        self.sdk.complete.side_effect = RuntimeError('fixture SDK failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture SDK failure'):
            self.invoke()
        self.sdk.complete.assert_called_once()

    def test_host_managed_fallback_result_is_allowed_and_attributed(self):
        self.sdk.complete.return_value.provider = 'fixture-host-fallback'
        self.sdk.complete.return_value.model = 'fixture-fallback-model'
        metrics = {}
        self.invoke(metrics=metrics)
        self.assertEqual(metrics['provider'], 'fixture-host-fallback')
        self.assertEqual(metrics['model'], 'fixture-fallback-model')
        self.assertEqual(metrics['reasoning']['requested_effort'], 'low')

    def test_stale_bound_plan_is_rejected_before_sdk(self):
        other = {**self.plan, 'route': {**self.plan['route'], 'model': 'changed'}}
        with self.assertRaises(ValueError):
            self.invoke(current_plan=lambda: other)
        self.sdk.complete.assert_not_called()

    def test_unavailable_prediction_route_fails_before_sdk(self):
        empty = {**self.plan, 'route': None, 'reason': 'unavailable'}
        with self.assertRaises(ValueError):
            self.invoke(expected_plan=empty, current_plan=lambda: empty)
        self.sdk.complete.assert_not_called()

    def test_foreign_owner_fails_before_any_sdk_access(self):
        with self.assertRaises(PermissionError):
            self.invoke(owner_home=self.home / 'foreign')
        self.context.register_auxiliary_task.assert_not_called()
        self.sdk.complete.assert_not_called()

    def test_route_change_during_task_preparation_prevents_dispatch(self):
        other = {**self.plan, 'route': {**self.plan['route'], 'account_scope': 'different-owner'}}
        with self.assertRaises(ValueError):
            self.invoke(current_plan=Mock(side_effect=[self.plan, other]))
        self.sdk.complete.assert_not_called()

    def test_unknown_host_source_hashes_are_not_a_public_sdk_requirement(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('source pin read forbidden')):
            self.assertEqual(self.invoke(), '{"suggestion":null}')


if __name__ == '__main__':
    unittest.main()
