import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .prompt_core import PromptStore, parse_suggestion, read_snapshot


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY, parent_session_id TEXT, source TEXT, model TEXT, model_config TEXT, billing_provider TEXT, archived INTEGER, rewind_count INTEGER);
            CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, active INTEGER, _compressed_summary INTEGER);''')
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)', ('s', None, 'desktop', 'model-x', json.dumps({'reasoning_config': {'effort': 'high'}}), 'provider-x', 0, 0))
            db.execute('INSERT INTO messages VALUES(1,?,?,?,?,?,?)', ('s', 'user', '修复解析器，不要发布', None, 1, 0))
            db.execute('INSERT INTO messages VALUES(2,?,?,?,?,?,?)', ('s', 'assistant', '解析器已修复，尚未运行测试', None, 1, 0))
        self.store = PromptStore(self.home / 'cache.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidate_persists_and_consumption_is_durable(self):
        snap = read_snapshot(self.home, 's', 's')
        row, claimed = self.store.claim(snap)
        self.assertTrue(claimed)
        self.assertTrue(self.store.finish(row, 'ready', '运行解析器回归测试'))
        again, claimed = PromptStore(self.home / 'cache.sqlite3').claim(snap)
        self.assertFalse(claimed)
        self.assertEqual(again['text'], '运行解析器回归测试')
        self.assertTrue(self.store.decide(again['root'], again['version'], again['request_id'], 'consumed'))
        after, claimed = PromptStore(self.home / 'cache.sqlite3').claim(snap)
        self.assertFalse(claimed)
        self.assertEqual(after['status'], 'consumed')
        self.assertIsNone(after['text'])

    def test_new_turn_and_late_result_cannot_overwrite(self):
        snap = read_snapshot(self.home, 's', 's')
        old, _ = self.store.claim(snap)
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('INSERT INTO messages VALUES(3,?,?,?,?,?,?)', ('s', 'user', '现在先解释改动', None, 1, 0))
        self.assertIsNone(read_snapshot(self.home, 's', 's'))
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('INSERT INTO messages VALUES(4,?,?,?,?,?,?)', ('s', 'assistant', '改动解释', None, 1, 0))
        new, _ = self.store.claim(read_snapshot(self.home, 's', 's'))
        self.assertNotEqual(old['version'], new['version'])
        self.assertFalse(self.store.finish(old, 'ready', '旧建议'))
        self.assertFalse(self.store.decide(old['root'], old['version'], old['request_id'], 'dismissed'))

    def test_stale_empty_result_regenerates_after_retry_window(self):
        import time
        from unittest.mock import patch
        snap = read_snapshot(self.home, 's', 's')
        row, claimed = self.store.claim(snap)
        self.assertTrue(claimed)
        self.assertTrue(self.store.finish(row, 'empty'))
        with patch('package.prompt_core.time.time', return_value=time.time() + 700):
            again, retry = self.store.claim(snap)
        self.assertTrue(retry, 'stale empty result must regenerate')
        self.assertEqual(again['status'], 'pending')
        self.assertNotEqual(again['request_id'], row['request_id'])
        self.assertFalse(self.store.finish(row, 'ready', '旧建议'))

    def test_fresh_empty_result_stays_cached(self):
        snap = read_snapshot(self.home, 's', 's')
        row, claimed = self.store.claim(snap)
        self.assertTrue(claimed)
        self.assertTrue(self.store.finish(row, 'empty'))
        again, retry = self.store.claim(snap)
        self.assertFalse(retry)
        self.assertEqual(again['status'], 'empty')

    def test_ready_and_consumed_never_regenerate(self):
        import time
        from unittest.mock import patch
        snap = read_snapshot(self.home, 's', 's')
        row, _ = self.store.claim(snap)
        self.assertTrue(self.store.finish(row, 'ready', '运行回归测试'))
        with patch('package.prompt_core.time.time', return_value=time.time() + 7200):
            again, retry = self.store.claim(snap)
        self.assertFalse(retry)
        self.assertEqual(again['status'], 'ready')
        self.assertTrue(self.store.decide(again['root'], again['version'], again['request_id'], 'consumed'))
        with patch('package.prompt_core.time.time', return_value=time.time() + 14400):
            after, retry = self.store.claim(snap)
        self.assertFalse(retry)
        self.assertEqual(after['status'], 'consumed')

    def test_duplicate_requests_and_timeout_do_not_regenerate(self):
        snap = read_snapshot(self.home, 's', 's')
        row, claimed = self.store.claim(snap)
        self.assertTrue(claimed)
        self.assertFalse(self.store.claim(snap)[1])
        self.store.finish(row, 'timeout')
        self.assertFalse(self.store.finish(row, 'ready', '迟到建议'))
        self.assertEqual(PromptStore(self.home / 'cache.sqlite3').claim(snap)[0]['status'], 'timeout')

    def test_lineage_scope_and_config_revision(self):
        self.assertIsNone(read_snapshot(self.home, 's', 'someone-else'))
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)', ('child', 's', 'desktop', 'model-x', '{}', 'provider-x', 0, 0))
            db.execute('INSERT INTO messages VALUES(3,?,?,?,?,?,?)', ('child', 'user', '继续原任务', None, 1, 0))
            db.execute('INSERT INTO messages VALUES(4,?,?,?,?,?,?)', ('child', 'assistant', '还需要验证结果', None, 1, 0))
        child = read_snapshot(self.home, 'child', 's')
        self.assertEqual(child['root'], 's')
        old = child['version']
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('UPDATE sessions SET model_config=? WHERE id=?', ('{"reasoning_config":{"effort":"medium"}}', 'child'))
        self.assertNotEqual(read_snapshot(self.home, 'child', 's')['version'], old)
        self.assertIsNone(read_snapshot(self.home, '../state.db', 's'))

    def test_chinese_and_invalid_outputs(self):
        self.assertEqual(parse_suggestion('{"suggestion":"运行解析器回归测试"}'), '运行解析器回归测试')
        for text in ['{"suggestion":null}', '{"suggestion":"我已经重启，正常了"}', '{"suggestion":"部署到生产"}', '{"suggestion":"a\\nb"}', '{"suggestion":"好","extra":1}', 'plain text']:
            self.assertIsNone(parse_suggestion(text), text)

    def test_confirmation_and_explicit_side_effect_examples_are_rejected(self):
        for text in ['我重启了，正常了', '测试通过了', 'It works now', 'I restarted it', 'I’ve saved it', '好的，我已经重启', 'push to main', 'deploy to prod', 'delete the branch', 'Now git push', 'ab\u202ecd']:
            self.assertIsNone(parse_suggestion(json.dumps({'suggestion': text})), text)
        self.assertIsNotNone(parse_suggestion(json.dumps({'suggestion': '继续运行回归测试，告诉我测试结果；不要提交或部署。'})))

    def test_read_only_and_non_desktop_suppression(self):
        before = (self.home / 'state.db').read_bytes()
        self.assertIsNotNone(read_snapshot(self.home, 's', 's'))
        self.assertEqual(before, (self.home / 'state.db').read_bytes())
        with __import__('contextlib').closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute("UPDATE sessions SET source='telegram'")
        self.assertIsNone(read_snapshot(self.home, 's', 's'))


if __name__ == '__main__':
    unittest.main()
