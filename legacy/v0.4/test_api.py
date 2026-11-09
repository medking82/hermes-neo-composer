import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from . import test_prompt_core as fixtures
from .dashboard import plugin_api as api
from .service import Service


class ApiTests(unittest.TestCase):
    setUp = fixtures.PromptTests.setUp
    tearDown = fixtures.PromptTests.tearDown

    def test_runtime_rotation_during_generation_discards_response(self):
        from tui_gateway import server
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        record = {'source': 'desktop', 'running': False, 'session_key': 's', 'profile_home': str(self.home)}
        async def rotate(*args):
            record['session_key'] = 'other-tip'
            return {'root': 's', 'status': 'ready', 'text': '旧上下文建议'}
        app = FastAPI()
        app.include_router(api.router)
        active = SimpleNamespace(home=self.home, generate=AsyncMock(side_effect=rotate))
        with patch.object(api, 'service', return_value=active), patch.dict(server._sessions, {'rpc-live': record}, clear=True), TestClient(app) as client:
            self.assertIsNone(client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'}).json()['candidate'])

    def test_runtime_handle_resolves_to_owned_persistent_session(self):
        from tui_gateway import server
        calls = []
        def completion(snapshot):
            calls.append(snapshot['session_id'])
            return '{"suggestion":"运行解析器回归测试"}'
        active = Service(self.home, completion, 'route')
        app = FastAPI()
        app.include_router(api.router)
        record = {'source': 'desktop', 'running': False, 'session_key': 's', 'profile_home': str(self.home)}
        with patch.object(api, 'service', return_value=active), patch.dict(server._sessions, {'rpc-live': record}, clear=True):
            with TestClient(app) as client:
                first = client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'})
                self.assertEqual(first.status_code, 200)
                data = first.json()
                self.assertEqual(data['candidate']['text'], '运行解析器回归测试')
                self.assertEqual(data['session_id'], 'rpc-live')
                self.assertEqual(calls, ['s'])
                record['profile_home'] = str(self.home / 'another-profile')
                self.assertIsNone(client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'}).json()['candidate'])
                record['profile_home'] = str(self.home)
                record['running'] = True
                self.assertIsNone(client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'}).json()['candidate'])
                record['running'] = False
                self.assertIsNone(client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 'unrelated'}).json()['candidate'])
                self.assertEqual(calls, ['s'])
                candidate = data['candidate']
                response = client.post('/decision', json={k: candidate[k] for k in ['root', 'version', 'request_id']} | {'status': 'consumed'})
                self.assertTrue(response.json()['recorded'])
                self.assertEqual(client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'}).json()['candidate']['status'], 'consumed')

    def test_disabled_predictions_make_no_generation_call(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        active = SimpleNamespace(home=self.home, prediction_plan={'route': None, 'reason': 'disabled'}, generate=AsyncMock())
        app = FastAPI(); app.include_router(api.router)
        with patch.object(api, 'service', return_value=active), patch.object(api, 'resolve_runtime_session', return_value='s'), TestClient(app) as client:
            result = client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'})
            self.assertIsNone(result.json()['candidate'])
            active.generate.assert_not_called()

    def test_settings_endpoints_read_back_the_profile_owned_write(self):
        from types import SimpleNamespace
        from .settings import load_settings, save_settings
        package = SimpleNamespace(settings_view=lambda: {'settings': load_settings(self.home)},
                                  update_settings=lambda body, scope: save_settings(self.home, body))
        app = FastAPI(); app.include_router(api.router)
        with patch.object(api, '_package', create=True, return_value=package), TestClient(app) as client:
            response = client.get('/settings')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['settings']['enabled'])
            value = {'enabled': True, 'providers': ['api'], 'model': 'api/small', 'fallback': ''}
            self.assertEqual(client.post('/settings', json={'scope': 'fixture', 'settings': value}).status_code, 200)
            self.assertEqual(client.get('/settings').json()['settings'], value)
            self.assertEqual(client.post('/settings', json={**value, 'api_key': 'forbidden'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
