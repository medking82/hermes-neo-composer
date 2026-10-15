import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from .llm_once import complete


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.plan = patch('package.llm_once.prediction_plan', create=True, return_value={
            'route': {'provider': 'openai-codex', 'model': 'selected-small'},
            'reason': 'Explicit low-cost fallback', 'settings': {}})
        self.plan.start()
        self.addCleanup(self.plan.stop)

    def test_uses_selected_low_cost_route_without_mutating_primary_session_or_using_tools(self):
        from agent import auxiliary_client as aux
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"suggestion":"运行回归测试"}', tool_calls=None))])
        request = SimpleNamespace(client=SimpleNamespace(max_retries=0, base_url='https://chatgpt.com/backend-api/codex'), kwargs={'model': 'selected-small'}, request_provider='openai-codex', resolved_api_mode='chat_completions', base_info='https://chatgpt.com/backend-api/codex', resolved_base_url='https://chatgpt.com/backend-api/codex')
        snapshot = {'model': 'model-x', 'provider': 'openai-codex', 'reasoning_config': {'enabled': True, 'effort': 'high'}, 'history': [{'role': 'user', 'content': '修复然后测试'}]}
        with patch('hermes_cli.config.load_config_readonly', return_value={'model': {'provider': 'openai-codex'}}), patch.object(aux, '_plan_aux_call', autospec=True, return_value=(request, {}, {})) as prepare, patch.object(aux, '_relay_sync_completion', autospec=True, return_value=response) as transport, patch.object(aux, 'call_llm', side_effect=AssertionError('recovery ladder forbidden')):
            self.assertEqual(complete(snapshot), '{"suggestion":"运行回归测试"}')
            self.assertEqual(prepare.call_args.kwargs['model'], 'selected-small')
            self.assertEqual(prepare.call_args.kwargs['reasoning_config'], {'enabled': True, 'effort': 'low'})
            self.assertEqual(snapshot['model'], 'model-x')
            self.assertEqual(snapshot['reasoning_config']['effort'], 'high')
            self.assertIsNone(prepare.call_args.kwargs['tools'])
            self.assertEqual(transport.call_count, 1)
            transport.side_effect = RuntimeError('fixture failure')
            with self.assertRaises(RuntimeError): complete(snapshot)
            self.assertEqual(transport.call_count, 2)

    def test_changed_destination_or_sdk_retry_fails_before_transport(self):
        from agent import auxiliary_client as aux
        for change in ['provider', 'model', 'endpoint', 'retries']:
            client = SimpleNamespace(max_retries=0, base_url='https://chatgpt.com/backend-api/codex')
            request = SimpleNamespace(client=client, kwargs={'model': 'selected-small'}, request_provider='openai-codex', base_info=client.base_url, resolved_base_url=client.base_url, resolved_api_mode='chat_completions')
            if change == 'provider': request.request_provider = 'unapproved'
            if change == 'model': request.kwargs['model'] = 'other'
            if change == 'endpoint': client.base_url = request.base_info = 'https://unapproved.invalid'
            if change == 'retries': client.max_retries = 2
            with self.subTest(change=change), patch('hermes_cli.config.load_config_readonly', return_value={'model': {}}), patch.object(aux, '_plan_aux_call', return_value=(request, {}, {})), patch.object(aux, '_relay_sync_completion') as transport:
                with self.assertRaises(ValueError): complete({'history': []})
                transport.assert_not_called()

    def test_no_credit_or_stream_fallback_wrapper_is_used(self):
        from agent import auxiliary_client as aux
        create = Mock(side_effect=RuntimeError('402 fixture affordable tokens: 10'))
        client = SimpleNamespace(max_retries=0, base_url='https://chatgpt.com/backend-api/codex', chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        request = SimpleNamespace(client=client, kwargs={'model': 'selected-small', 'messages': []}, request_provider='openai-codex', base_info=client.base_url, resolved_base_url=client.base_url, resolved_api_mode='chat_completions')
        with patch('hermes_cli.config.load_config_readonly', return_value={'model': {}}), patch.object(aux, '_plan_aux_call', return_value=(request, {}, {})), patch.object(aux, '_create_with_progress', side_effect=AssertionError('retrying wrapper forbidden')):
            with self.assertRaises(RuntimeError): complete({'history': []})
        self.assertEqual(create.call_count, 1)

    def test_stale_bound_plan_is_rejected_before_planning(self):
        from agent import auxiliary_client as aux
        from .llm_once import prediction_plan
        old = prediction_plan()
        old = {**old, 'route': {**old['route'], 'model': 'previous'}}
        with patch('hermes_cli.config.load_config_readonly', return_value={}), patch.object(aux, '_plan_aux_call') as prepare:
            with self.assertRaises(ValueError): complete({'history': []}, expected_plan=old)
            prepare.assert_not_called()

    def test_unvalidated_custom_endpoint_fails_before_planning(self):
        from agent import auxiliary_client as aux
        request = SimpleNamespace(client=object(), kwargs={'model': 'model-x'}, request_provider='provider-x', resolved_api_mode='chat_completions')
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"suggestion":null}', tool_calls=None))])
        with patch('hermes_cli.config.load_config_readonly', return_value={'model': {'provider': 'provider-x', 'base_url': 'https://unvalidated.example.invalid/v1'}}), patch.object(aux, '_plan_aux_call', autospec=True, return_value=(request, {}, {})) as prepare, patch.object(aux, '_relay_sync_completion', autospec=True, return_value=response):
            with self.assertRaises(ValueError):
                complete({'model': 'model-x', 'provider': 'provider-x', 'history': [], 'reasoning_config': None})
            prepare.assert_not_called()

    def test_unavailable_prediction_route_fails_before_any_transport(self):
        from agent import auxiliary_client as aux
        with patch('package.llm_once.prediction_plan', return_value={'route': None, 'reason': 'unavailable'}), patch.object(aux, '_plan_aux_call') as prepare:
            with self.assertRaises(ValueError):
                complete({'model': 'model-x', 'provider': 'provider-x'})
            prepare.assert_not_called()



    def test_runtime_registry_pin_drift_is_rejected_before_planning(self):
        import hashlib
        from pathlib import Path
        from agent import auxiliary_client as aux
        from . import llm_once
        metadata={'auxiliary_client_sha256':hashlib.sha256(Path(aux.__file__).read_bytes()).hexdigest(),'pins':{'tui_gateway/server.py':'0'*64}}
        with patch.object(llm_once.json,'loads',return_value=metadata),patch('hermes_cli.config.load_config_readonly',return_value={'model':{'provider':'openai-codex'}}),patch.object(aux,'_plan_aux_call',side_effect=AssertionError('planning reached despite runtime drift')) as plan:
            with self.assertRaisesRegex(RuntimeError,'host.*changed'):
                complete({'model':'model-x','provider':'openai-codex','history':[],'reasoning_config':None})
            plan.assert_not_called()

    def test_real_relay_executes_the_actual_create_callback_once(self):
        from agent import auxiliary_client as aux
        response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"suggestion":null}',tool_calls=None))])
        create=Mock(return_value=response)
        client=SimpleNamespace(max_retries=0, base_url='https://chatgpt.com/backend-api/codex', chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        request=SimpleNamespace(client=client,kwargs={'model':'selected-small','messages':[{'role':'user','content':'test'}]},request_provider='openai-codex',resolved_api_mode='chat_completions',base_info='https://chatgpt.com/backend-api/codex',resolved_base_url='https://chatgpt.com/backend-api/codex')
        with patch('hermes_cli.config.load_config_readonly',return_value={'model':{'provider':'openai-codex'}}),patch.object(aux,'_plan_aux_call',autospec=True,return_value=(request,{},{})),patch.object(aux,'call_llm',side_effect=AssertionError('fallback forbidden')):
            self.assertEqual(complete({'model':'model-x','provider':'openai-codex','history':[],'reasoning_config':None}),'{"suggestion":null}')
        self.assertEqual(create.call_count,1)
        self.assertNotIn('tools',create.call_args.kwargs)

if __name__ == '__main__':
    unittest.main()
