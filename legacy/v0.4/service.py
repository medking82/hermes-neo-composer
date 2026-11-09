"""One bounded generation per profile/session/context, independent of chat turns."""
import asyncio

from .prompt_core import PromptStore, parse_suggestion, read_snapshot


class Service:
    def __init__(self, home, complete, route_revision, deadline=25):
        self.home = home
        self.complete = complete
        self.route_revision = route_revision
        self.deadline = deadline
        self.inflight = {}
        self.store = PromptStore(home / 'plugin-data' / 'neo-next-prompt' / 'state.sqlite3')

    def snapshot(self, session, stored):
        return read_snapshot(self.home, session, stored, self.route_revision)

    async def generate(self, session, stored):
        snapshot = await asyncio.to_thread(self.snapshot, session, stored)
        if snapshot is None:
            return None
        key = snapshot['version']
        task = self.inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._generate(snapshot, session, stored))
            self.inflight[key] = task
            task.add_done_callback(lambda done: self.inflight.pop(key, None) if self.inflight.get(key) is done else None)
        # Reconnects share the existing bounded prediction, never a new model call.
        return await asyncio.shield(task)

    async def _generate(self, snapshot, session, stored):
        row, claimed = await asyncio.to_thread(self.store.claim, snapshot)
        if not claimed:
            return row
        try:
            raw = await asyncio.wait_for(asyncio.to_thread(self.complete, snapshot), timeout=self.deadline)
            fresh = await asyncio.to_thread(self.snapshot, session, stored)
            if fresh is None or fresh['version'] != snapshot['version']:
                await asyncio.to_thread(self.store.finish, row, 'stale')
                return None
            text = parse_suggestion(raw)
            status = 'ready' if text else 'empty'
            if not await asyncio.to_thread(self.store.finish, row, status, text):
                return None
        except (TimeoutError, asyncio.CancelledError):
            status, text = 'timeout', None
            await asyncio.to_thread(self.store.finish, row, status)
        except Exception:
            status, text = 'error', None
            await asyncio.to_thread(self.store.finish, row, status)
        return {**row, 'status': status, 'text': text}

    def decide(self, record, status):
        return self.store.decide(record['root'], record['version'], record['request_id'], status)
