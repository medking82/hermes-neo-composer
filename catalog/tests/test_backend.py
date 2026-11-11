import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from dashboard import plugin_api as api

ROWS = [{'role': 'user', 'content': 'Please make this report easier to scan'},
        {'role': 'assistant', 'content': 'The report is now grouped by topic.'}]


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'data.db')
        self.store = api.Store(self.path)

    def candidate(self, text, rows=ROWS):
        ticket = self.store.prepare('a', rows)
        ctx = SimpleNamespace(llm=SimpleNamespace(complete=lambda *a, **kw: SimpleNamespace(text=json.dumps({'suggestion': text}))))
        return api.generate(ctx, self.store, 'a', {'messages': rows, 'token': ticket['token']})

    def test_candidate_survives_another_process_without_transcript(self):
        result = self.candidate('Group the key findings into a short table')
        self.assertEqual(result['status'], 'ready')
        code = "import json,sys; from dashboard.plugin_api import Store; print(json.dumps(Store(sys.argv[1]).prepare('a', json.loads(sys.argv[2]))))"
        output = subprocess.check_output([sys.executable, '-c', code, self.path, json.dumps(ROWS)], text=True)
        self.assertEqual(json.loads(output)['text'], result['text'])
        self.assertNotIn(ROWS[0]['content'].encode(), Path(self.path).read_bytes())
        self.assertEqual(self.store.prepare('b', ROWS)['status'], 'pending')

    def test_stale_request_cannot_replace_newer_generation(self):
        old = self.store.prepare('a', ROWS)
        new = self.store.prepare('a', ROWS, refresh=True)
        self.assertEqual(self.store.publish('a', old['token'], 'Old')['status'], 'stale')
        self.assertEqual(self.store.publish('a', new['token'], 'New')['text'], 'New')

    def test_disable_and_reenable_during_llm_cannot_publish(self):
        token = self.store.prepare('a', ROWS)['token']
        def complete(*args, **kwargs):
            api.Store(self.path).configure(False)
            api.Store(self.path).configure(True)
            return SimpleNamespace(text='{"suggestion":"Shorten the report"}')
        result = api.generate(SimpleNamespace(llm=SimpleNamespace(complete=complete)), self.store,
                              'a', {'messages': ROWS, 'token': token})
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['text'], '')

    def test_new_turn_in_another_process_invalidates_pending(self):
        token = self.store.prepare('a', ROWS)['token']
        subprocess.check_call([sys.executable, '-c',
            "import sys; from dashboard.plugin_api import Store; Store(sys.argv[1]).invalidate('a')", self.path])
        self.assertEqual(self.store.publish('a', token, 'Old')['status'], 'stale')

    def test_token_is_bound_to_transcript_and_session(self):
        token = self.store.prepare('a', ROWS)['token']
        ctx = SimpleNamespace(llm=SimpleNamespace(complete=lambda *a, **kw: self.fail('Must not call model')))
        for session, rows in [('b', ROWS), ('a', [{'role': 'user', 'content': 'different'}])]:
            self.assertEqual(api.generate(ctx, self.store, session, {'token': token, 'messages': rows})['status'], 'stale')

    def test_dismiss_is_durable_and_refresh_explicitly_reopens(self):
        result = self.candidate('Shorten the report')
        self.store.dismiss('a', result['token'])
        self.assertEqual(api.Store(self.path).prepare('a', ROWS)['status'], 'dismissed')
        self.assertEqual(self.store.prepare('a', ROWS, refresh=True)['status'], 'pending')

    def test_old_dismiss_does_not_remove_new_candidate(self):
        old = self.candidate('Shorten the report')
        new = self.store.prepare('a', ROWS, refresh=True)
        self.store.publish('a', new['token'], 'New candidate')
        self.store.dismiss('a', old['token'])
        self.assertEqual(self.store.prepare('a', ROWS)['text'], 'New candidate')

    def test_model_uses_host_default_without_override_or_tools(self):
        token = self.store.prepare('a', ROWS)['token']
        def complete(messages, **kwargs):
            self.assertEqual(messages[0]['role'], 'system')
            self.assertEqual(json.loads(messages[1]['content'])['conversation'], ROWS)
            self.assertEqual(set(kwargs), {'max_tokens', 'temperature', 'timeout', 'purpose'})
            return SimpleNamespace(text='{"suggestion":null}')
        result = api.generate(SimpleNamespace(llm=SimpleNamespace(complete=complete)), self.store, 'a', {'token': token, 'messages': ROWS})
        self.assertEqual(result['text'], '')

    def test_safety_guards_reject_upstream_values_before_storage(self):
        for value in ["I've restarted it", 'I saved the file', 'Tests all passed', 'It works now',
                      'Please git push the branch', 'Now deploy the fix', 'commit this',
                      'delete the logs', 'pay the invoice', 'publish the release',
                      '我已经重启了', '测试通过了', '请部署更新', '請刪除資料', 'hello\nworld', 'bad\u202econtrol']:
            with self.subTest(value=value):
                result = self.candidate(value)
                self.assertEqual(result['text'], '')
                self.store.invalidate('a')

    def test_language_guard_matching_mixed_switch_ambiguous(self):
        zh = [{'role': 'user', 'content': '请检查 API 的响应格式'}]
        self.assertEqual(api.clean('{"suggestion":"Add a table"}', zh), '')
        self.assertTrue(api.clean('{"suggestion":"请把 API 结果整理成表格"}', zh))
        self.assertEqual(api.clean('{"suggestion":"请加表格"}', ROWS), '')
        switched = zh + [{'role': 'user', 'content': 'Please use English from here'}]
        self.assertTrue(api.clean('{"suggestion":"Add a table"}', switched))
        self.assertTrue(api.clean('{"suggestion":"OK"}', zh))
        ja = [{'role': 'user', 'content': 'この結果を確認してください'}]
        self.assertTrue(api.clean('{"suggestion":"結果確認"}', ja))
        ko = [{'role': 'user', 'content': '결과를 확인해 주세요'}]
        self.assertEqual(api.clean('{"suggestion":"Add a table"}', ko), '')

    def test_malformed_model_output_and_oversized_input(self):
        for raw in ['garbage', '{}', '[]', '{"suggestion":42}', '{"suggestion":"' + 'x' * 241 + '"}']:
            self.assertEqual(api.clean(raw, ROWS), '')
        for rows in [[], [{'role': 'tool', 'content': 'x'}], [{'role': 'user', 'content': 'x' * 4001}]]:
            with self.assertRaises(ValueError):
                api.normalize(rows)

    def test_http_routes_validation_and_settings(self):
        app = FastAPI()
        app.include_router(api.router, prefix='/api/plugins/neo-composer')
        with patch.object(api, 'Store', return_value=self.store), TestClient(app) as client:
            root = '/api/plugins/neo-composer'
            self.assertTrue(client.get(root + '/settings').json()['enabled'])
            token = client.post(root + '/prepare', json={'session_id': 'a', 'messages': ROWS}).json()['token']
            self.assertEqual(client.post(root + '/prepare', json={'session_id': '', 'messages': ROWS}).status_code, 422)
            self.assertEqual(client.post(root + '/prepare', json={'session_id': 'a', 'messages': [{'role': 'tool'}]}).status_code, 422)
            self.assertFalse(client.post(root + '/settings', json={'enabled': False}).json()['enabled'])
            self.assertEqual(self.store.publish('a', token, 'late')['status'], 'stale')
            self.assertEqual(client.post(root + '/prepare', json={'session_id': 'a', 'messages': ROWS}).json()['status'], 'disabled')


if __name__ == '__main__':
    unittest.main()
