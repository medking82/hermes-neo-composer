import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .service import Service
from .test_prompt_core import PromptTests


class ServiceTests(PromptTests):
    def test_one_model_call_and_restart_reuses_result(self):
        calls = []
        def complete(snapshot):
            calls.append(snapshot)
            return '{"suggestion":"运行解析器回归测试"}'
        svc = Service(self.home, complete, 'route-v1')
        first = asyncio.run(svc.generate('s', 's'))
        again = asyncio.run(Service(self.home, complete, 'route-v1').generate('s', 's'))
        self.assertEqual(first, again)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['reasoning_config']['effort'], 'high')
        self.assertTrue(svc.decide(first, 'dismissed'))
        self.assertEqual(asyncio.run(svc.generate('s', 's'))['status'], 'dismissed')
        self.assertEqual(len(calls), 1)

    def test_sibling_contexts_do_not_evict_each_other(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            for i, child in enumerate(['a', 'b']):
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)', (child, 's', 'desktop', 'model-x', '{}', 'provider-x', 0, 0))
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (3 + i * 2, child, 'user', child, None, 1, 0))
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (4 + i * 2, child, 'assistant', child, None, 1, 0))
        calls = []
        def completion(snapshot):
            calls.append(snapshot['session_id'])
            return '{"suggestion":"运行回归测试"}'
        svc = Service(self.home, completion, 'route')
        async def scenario():
            a = await svc.generate('a', 's')
            self.assertTrue(svc.decide(a, 'consumed'))
            await svc.generate('b', 's')
            self.assertEqual((await svc.generate('a', 's'))['status'], 'consumed')
            await svc.generate('b', 's')
            await svc.generate('a', 'a')
        asyncio.run(scenario())
        self.assertEqual(calls, ['a', 'b'])

    def test_concurrent_readers_share_finished_result_not_pending_row(self):
        import threading
        start, release = threading.Event(), threading.Event()
        calls = []
        def completion(snapshot):
            calls.append(snapshot)
            start.set()
            release.wait(1)
            return '{"suggestion":"运行回归测试"}'
        async def scenario():
            svc = Service(self.home, completion, 'route')
            first = asyncio.create_task(svc.generate('s', 's'))
            await asyncio.to_thread(start.wait, 1)
            second = asyncio.create_task(svc.generate('s', 's'))
            asyncio.get_running_loop().call_later(0.05, release.set)
            results = await asyncio.gather(first, second)
            self.assertEqual([r['status'] for r in results], ['ready', 'ready'])
        asyncio.run(scenario())
        self.assertEqual(len(calls), 1)

    def test_failure_is_terminal_and_has_no_fallback(self):
        calls = []
        def fail(snapshot):
            calls.append(snapshot)
            raise RuntimeError('fixture failure')
        svc = Service(self.home, fail, 'route-v1')
        self.assertEqual(asyncio.run(svc.generate('s', 's'))['status'], 'error')
        asyncio.run(svc.generate('s', 's'))
        self.assertEqual(len(calls), 1)

    def test_timeout_returns_without_late_publication(self):
        import threading
        gate = threading.Event()
        def delayed(snapshot):
            gate.wait(1)
            return '{"suggestion":"迟到的建议"}'
        async def scenario():
            svc = Service(self.home, delayed, 'route-v1', deadline=0.01)
            result = await svc.generate('s', 's')
            self.assertEqual(result['status'], 'timeout')
            gate.set()
            await asyncio.sleep(0.03)
            self.assertEqual((await svc.generate('s', 's'))['status'], 'timeout')
        asyncio.run(scenario())

    def test_new_user_message_during_generation_discards_result(self):
        import sqlite3
        from contextlib import closing
        def change(snapshot):
            with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
                db.execute('INSERT INTO messages VALUES(3,?,?,?,?,?,?)', ('s', 'user', '先停', None, 1, 0))
            return '{"suggestion":"不该出现的建议"}'
        self.assertIsNone(asyncio.run(Service(self.home, change, 'route-v1').generate('s', 's')))


if __name__ == '__main__':
    unittest.main()
