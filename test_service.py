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

    def test_sdk_failed_worker_start_revokes_pool_without_replaying_queued_work(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        from . import sdk_llm
        callback = Mock(return_value='fixture-result')
        pool = ThreadPoolExecutor(max_workers=1)
        async def scenario():
            with patch.object(sdk_llm, '_completion_pool', pool), patch.object(sdk_llm, '_completion_slot', threading.BoundedSemaphore(1)):
                with patch.object(threading.Thread, 'start', side_effect=RuntimeError('fixture worker start failed')):
                    with self.assertRaises(RuntimeError):
                        await sdk_llm.run_completion(callback, {})
                # submit() can enqueue before Thread.start raises. That abandoned
                # callback must never run when a later request reaches the pool.
                with self.assertRaises(RuntimeError):
                    await sdk_llm.run_completion(callback, {})
                callback.assert_not_called()
        try:
            asyncio.run(scenario())
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def test_sdk_retries_cannot_block_storage_or_readmit_after_deadline(self):
        import sys
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        from unittest.mock import Mock
        package = sys.modules[__package__]
        release = threading.Event()
        entered = asyncio.Event()
        selected = {'enabled': True, 'providers': ['openai-codex'],
                    'model': 'openai-codex/fixture-small', 'fallback': ''}
        rows = [{'provider': 'openai-codex', 'model': model, 'available': True,
                 'text': True, 'account_scope': 'fixture-owner'}
                for model in ['fixture-small', 'fixture-other', 'fixture-third']]
        calls = []
        async def scenario():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            def sdk_call(**kwargs):
                calls.append(threading.current_thread().name)
                loop.call_soon_threadsafe(entered.set)
                release.wait(2)
                return SimpleNamespace(text='{"suggestion":"迟到的建议"}',
                                       provider='openai-codex', model='fixture-small')
            ctx = SimpleNamespace(plugin_id='neo-next-prompt',
                                  llm=SimpleNamespace(complete=Mock(side_effect=sdk_call)),
                                  register_auxiliary_task=Mock())
            with (
                patch.object(package, '_context', None), patch.object(package, '_service', None),
                patch.object(package, '_owner_home', None), patch.object(package, '_scope', 'fixture-scope'),
                patch('hermes_constants.get_hermes_home', return_value=self.home),
                patch('hermes_cli.config.load_config_readonly', return_value={'plugins': {'enabled': ['neo-next-prompt']}}),
                patch(__package__ + '.settings.load_settings', return_value=selected),
                patch.object(package, '_settings_catalog', return_value=rows),
            ):
                package.register(ctx)
                first = package.get_service()
                first.deadline = 0.01
                task = asyncio.create_task(first.generate('s', 's'))
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    try:
                        result = await asyncio.wait_for(asyncio.shield(task), 0.25)
                    except TimeoutError:
                        self.fail('SDK retry blocked the shared storage executor beyond the deadline')
                    self.assertEqual(result['status'], 'timeout')
                    self.assertFalse(release.is_set())
                    self.assertFalse(calls[0].startswith('asyncio_'))
                    # A new service/revision shares the still-running physical-call cap.
                    selected['model'] = 'openai-codex/fixture-other'
                    second = package.get_service()
                    blocked = await asyncio.wait_for(second.generate('s', 's'), 0.25)
                    self.assertEqual(blocked['status'], 'error')
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(ctx.register_auxiliary_task.call_count, 1)
                finally:
                    release.set()
                    await asyncio.gather(task, *list(first.inflight.values()), return_exceptions=True)
                from . import sdk_llm
                # Test-only physical-worker barrier, not the cancelled waiter.
                await asyncio.wrap_future(sdk_llm._completion_pool.submit(lambda: None))
                self.assertEqual((await first.generate('s', 's'))['status'], 'timeout')
                selected['model'] = 'openai-codex/fixture-third'
                recovered = await package.get_service().generate('s', 's')
                self.assertEqual(recovered['status'], 'ready')
                self.assertEqual(len(calls), 2)
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
