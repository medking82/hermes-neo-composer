"""Strict delivery changes only the next request tail of the captured generation."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import pytest

from gateway.session_contract import SessionRef
from hermes_state_runtime import RuntimeStoreError
from gateway.neo_composer_adapter import capabilities, steer, deliver

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8MsAAAAASUVORK5CYII=')


class Authority:
    def __init__(self, home):
        self.profile_id = str(home)
        self.agent = NS()
        self.generation = 7
        self.sessions = {'s': NS(event_stream=NS(lock=threading.RLock()))}
        self.allowed = True

    def authorize(self, actor, ref, capability):
        if not self.allowed or ref.session_id != 's':
            raise RuntimeStoreError('permission_denied')

    def _handle(self, ref):
        return NS(execution_generation=self.generation, execution_state='running')

    def check_approval_generation(self, sid, generation):
        if generation != self.generation:
            raise RuntimeStoreError('stale_generation')

    def steer_agent(self, ref, generation, text):
        assert text is None  # Never latch for a later adoption.
        return self.agent, False


@pytest.fixture
def context(tmp_path):
    authority = Authority(tmp_path)
    connection = NS(authority=authority, actor=object(), subscriptions={'s'})
    ref = SessionRef(str(tmp_path), 's')
    params = dict(session_id='s', protocol=1, request_id='strict-1', execution_generation=7, text='correct', images=[], timeout_ms=200)
    return connection, ref, params


def test_delivered_receipt_follows_safe_boundary_and_real_image_bytes(context):
    c, ref, p = context
    p['images'] = [{'content_base64': base64.b64encode(PNG).decode(), 'filename': 'pixel.png'}]
    pending = asyncio.run(steer(c, ref, p))
    messages = [{'role': 'user', 'content': 'original'}, {'role': 'assistant', 'tool_calls': [{'id': 't'}]},
                {'role': 'tool', 'tool_call_id': 't', 'content': 'original tool result'}]
    before = [dict(m) for m in messages]
    with ThreadPoolExecutor(1) as pool:
        answer = pool.submit(pending.work)
        assert not answer.done()
        assert deliver(c.authority.agent, messages, current_turn_user_idx=0)
        receipt = answer.result(2)
    assert receipt == dict(protocol=1, status='delivered', session_id='s', execution_generation=7,
                           request_id='strict-1', image_count=1)
    assert messages[:3] == before
    assert messages[-1]['role'] == 'user'
    assert 'vision_analyze' in messages[-1]['content']
    path = next((Path(c.authority.profile_id) / 'cache' / 'images').glob('*'))
    assert path.read_bytes() == PNG
    assert str(path) in messages[-1]['content']
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=0)


def test_timeout_withdraws_and_cannot_arrive_at_later_boundary(context):
    c, ref, p = context
    p['timeout_ms'] = 10
    pending = asyncio.run(steer(c, ref, p))
    receipt = pending.work()
    assert receipt['status'] == 'not_delivered'
    assert receipt['reason'] == 'boundary_timeout'
    messages = [{'role': 'user', 'content': 'new'}, {'role': 'tool', 'content': 'result'}]
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=0)
    assert len(messages) == 2


def test_missing_tool_in_current_turn_does_not_rewrite_historical_prefix(context):
    c, ref, p = context
    p['timeout_ms'] = 10
    pending = asyncio.run(steer(c, ref, p))
    messages = [{'role': 'tool', 'content': 'historic'}, {'role': 'user', 'content': 'current'}]
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=1)
    assert pending.work()['status'] == 'not_delivered'


def test_generation_rechecked_at_delivery(context):
    c, ref, p = context
    pending = asyncio.run(steer(c, ref, p))
    c.authority.generation = 8
    messages = [{'role': 'user', 'content': 'new'}, {'role': 'tool', 'content': 'result'}]
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=0)
    assert pending.work()['reason'] == 'stale_generation'
    assert len(messages) == 2


@pytest.mark.parametrize('mutation,reason', [({'execution_generation': 6}, 'stale_generation'),
    ({'protocol': 2}, 'invalid_params'), ({'execution_generation': True}, 'invalid_params'),
    ({'images': [{'content_base64': 'garbage', 'filename': 'x.png'}]}, 'invalid_params')])
def test_refuses_before_enqueue(context, mutation, reason):
    c, ref, p = context
    with pytest.raises(RuntimeStoreError, match=reason):
        asyncio.run(steer(c, ref, {**p, **mutation}))
    assert not getattr(c.authority.agent, '_neo_strict_pending', None)


def test_permission_and_missing_agent_fail_closed(context):
    c, ref, p = context
    c.authority.allowed = False
    with pytest.raises(RuntimeStoreError, match='permission_denied'):
        asyncio.run(steer(c, ref, p))
    c.authority.allowed = True
    c.authority.agent = None
    with pytest.raises(RuntimeStoreError, match='steer_unavailable'):
        asyncio.run(steer(c, ref, p))


def test_expired_before_reply_worker_starts_never_delivers_and_removes_images(context, monkeypatch):
    c, ref, p = context
    p['images'] = [{'content_base64': base64.b64encode(PNG).decode(), 'filename': 'pixel.png'}]
    reply = asyncio.run(steer(c, ref, p))
    from gateway import neo_composer_adapter as adapter
    monkeypatch.setattr(adapter.time, 'monotonic', lambda: reply.pending.deadline + 1)
    messages = [{'role': 'user', 'content': 'original'},
                {'role': 'assistant', 'tool_calls': [{'id': 't'}]},
                {'role': 'tool', 'tool_call_id': 't', 'content': 'result'}]
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=0)
    assert reply.work()['reason'] == 'boundary_timeout'
    assert not list((Path(c.authority.profile_id) / 'cache' / 'images').glob('*'))
    assert len(messages) == 3


def test_repeated_request_id_does_not_insert_twice(context):
    c, ref, p = context
    reply = asyncio.run(steer(c, ref, p))
    messages = [{'role': 'user', 'content': 'original'},
                {'role': 'assistant', 'tool_calls': [{'id': 't'}]},
                {'role': 'tool', 'tool_call_id': 't', 'content': 'result'}]
    assert deliver(c.authority.agent, messages, current_turn_user_idx=0)
    assert reply.work()['status'] == 'delivered'
    with pytest.raises(RuntimeStoreError, match='steer_duplicate'):
        asyncio.run(steer(c, ref, p))
    assert len(messages) == 4


def test_native_steer_tail_is_not_followed_by_second_user_row(context):
    c, ref, p = context
    reply = asyncio.run(steer(c, ref, p))
    messages = [{'role': 'user', 'content': 'original'},
                {'role': 'assistant', 'tool_calls': [{'id': 't'}]},
                {'role': 'tool', 'tool_call_id': 't', 'content': 'result'},
                {'role': 'user', 'content': 'native steer'}]
    assert not deliver(c.authority.agent, messages, current_turn_user_idx=0)
    assert messages[-1]['content'] == 'native steer'
    reply.pending.withdraw(c.authority.agent, 'test_cleanup')


def test_contract_capability_has_protocol_not_hermes_release_gate(context):
    c, ref, p = context
    cap = asyncio.run(capabilities(c, ref, dict(session_id='s', protocol=1)))
    assert cap['protocol'] == 1
    assert cap['execution_generation'] == 7
    assert cap['strict_steer'] and cap['image_mode'] == 'vision_analyze_reference'
