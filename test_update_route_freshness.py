"""Current route/owner validation must precede SDK draft insertion, without inference."""
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from . import test_prompt_core as fixtures
from .dashboard import plugin_api as api
from .prompt_core import read_snapshot
from .service import Service


class UpdateRouteFreshnessTests(unittest.TestCase):
    setUp = fixtures.PromptTests.setUp
    tearDown = fixtures.PromptTests.tearDown

    def test_endpoint_and_secret_reference_changes_invalidate_without_exporting_them(self):
        before = read_snapshot(self.home, 's', 's', 'prediction-route')
        self.assertEqual(before['version'], 'cf96d5dcfc9aa75e911f17448faaa901e790aae25ea8f97a852b455568639d32')
        original = {'reasoning_config': {'effort': 'high'}}
        for field, value in [('base_url', 'https://fresh-profile.invalid/v1'),
                             ('config_secret_ref', 'fixture-selected-provider-reference')]:
            with self.subTest(field=field), closing(sqlite3.connect(self.home / 'state.db')) as db, db:
                db.execute('UPDATE sessions SET model_config=? WHERE id=?', (json.dumps({**original, field: value}), 's'))
                db.commit()
                changed = read_snapshot(self.home, 's', 's', 'prediction-route')
                self.assertNotEqual(changed['version'], before['version'])
                self.assertNotIn(value, json.dumps(changed))
                db.execute('UPDATE sessions SET model_config=? WHERE id=?', (json.dumps(original), 's'))
            self.assertEqual(read_snapshot(self.home, 's', 's', 'prediction-route')['version'], before['version'])

    def test_validation_rechecks_current_route_owner_and_ready_state_without_generation(self):
        from tui_gateway import server
        calls = []
        active = Service(self.home, lambda snapshot: calls.append(snapshot['session_id']) or '{"suggestion":"Review One Regression"}', 'prediction-route')
        active.prediction_plan = {'route': {'provider': 'approved-provider', 'model': 'approved-model'}}
        record = {'source': 'desktop', 'running': False, 'session_key': 's', 'profile_home': str(self.home)}
        app = FastAPI()
        app.include_router(api.router)
        with patch.object(api, 'service', return_value=active), patch.dict(server._sessions, {'rpc-live': record}, clear=True), TestClient(app) as client:
            candidate = client.post('/suggestion', json={'session_id': 'rpc-live', 'stored_id': 's'}).json()['candidate']
            body = {'session_id': 'rpc-live', 'stored_id': 's', 'version': candidate['version'], 'request_id': candidate['request_id']}
            check = lambda value=body: client.post('/validate', json=value)
            self.assertEqual(check().status_code, 200)
            self.assertTrue(check().json()['current'])
            with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
                db.execute('UPDATE sessions SET model=? WHERE id=?', ('newly-picked-model', 's'))
            self.assertFalse(check().json()['current'])
            with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
                db.execute('UPDATE sessions SET model=? WHERE id=?', ('model-x', 's'))
            self.assertTrue(check().json()['current'])
            active.route_revision = 'current-profile-account-changed'
            self.assertFalse(check().json()['current'])
            active.route_revision = 'prediction-route'
            active.prediction_plan = {'route': None}
            self.assertFalse(check().json()['current'])
            active.prediction_plan = {'route': True}
            record['profile_home'] = str(self.home / 'foreign-profile')
            self.assertFalse(check().json()['current'])
            record['profile_home'] = str(self.home)
            record['running'] = True
            self.assertFalse(check().json()['current'])
            record['running'] = False
            self.assertFalse(check({**body, 'request_id': '0' * 32}).json()['current'])
            self.assertEqual(check({**body, 'version': 'invalid'}).status_code, 422)
            self.assertTrue(active.decide(candidate, 'dismissed'))
            self.assertFalse(check().json()['current'])
            self.assertEqual(calls, ['s'], 'Validation must never generate, retry or dispatch a model request')
