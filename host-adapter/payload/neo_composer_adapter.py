"""Neo protocol 1: generation-fenced, withdrawable delivery at a pre-request tool boundary.

This optional adapter owns its pending slot; it never calls legacy steer/redirect,
changes busy policy, interrupts a tool, or falls back to a new admission.
"""
import asyncio
from functools import partial
from pathlib import Path
import threading
import time
from typing import Literal

from pydantic import Field

from gateway.session_busy_controls import authorize
from gateway.session_llm_oneshot import DeferredReply
from hermes_state_runtime import RuntimeStoreError
from tui_gateway.contracts.base import Params, Result
from tui_gateway.contracts.registry import canonical_method


class CapabilityParams(Params):
    session_id: str
    profile: str | None = None
    protocol: Literal[1]


class Image(Params):
    content_base64: str
    filename: str


class SteerParams(CapabilityParams):
    request_id: str
    execution_generation: int
    text: str = ''
    images: list[Image] = Field(default_factory=list)
    timeout_ms: int = 20000


class CapabilityResult(Result):
    protocol: Literal[1]
    strict_steer: bool
    execution_generation: int
    image_mode: Literal['vision_analyze_reference']
    max_images: int
    max_wait_ms: int


class SteerResult(Result):
    protocol: Literal[1]
    status: Literal['delivered', 'not_delivered']
    session_id: str
    execution_generation: int
    request_id: str
    image_count: int
    reason: str | None = None


canonical_method('neo.composer.capabilities', params=CapabilityParams, result=CapabilityResult)
canonical_method('neo.composer.steer', params=SteerParams, result=SteerResult)


def handlers(connection):
    return {'neo.composer.capabilities': partial(capabilities, connection),
            'neo.composer.steer': partial(steer, connection)}


async def capabilities(connection, ref, params):
    if params.get('protocol') != 1 or set(params) - {'session_id', 'profile', 'protocol'}:
        raise RuntimeStoreError('invalid_params')
    authorize(connection, ref, params, 'session:read')
    handle = connection.authority._handle(ref)
    return dict(protocol=1, strict_steer=handle.execution_state == 'running',
                execution_generation=handle.execution_generation, image_mode='vision_analyze_reference',
                max_images=8, max_wait_ms=20000)


class _Pending:
    def __init__(self, authority, ref, params, text):
        self.lock, self.done = threading.Lock(), threading.Event()
        self.authority, self.ref = authority, ref
        self.generation, self.text = params['execution_generation'], text
        self.deadline = time.monotonic() + params.get('timeout_ms', 20000) / 1000
        self.staged_paths = []
        self.status, self.reason = 'pending', None
        self.receipt = dict(protocol=1, session_id=ref.session_id, execution_generation=self.generation,
                            request_id=params['request_id'], image_count=len(params.get('images', [])))

    def finish(self, status, reason=None):
        # All transitions and message insertion share this lock. A timeout can never withdraw
        # an item already taken off a queue but not yet inserted into messages.
        self.status, self.reason = status, reason
        if status == 'not_delivered':
            for path in self.staged_paths:
                Path(path).unlink(missing_ok=True)
        self.done.set()

    def withdraw(self, agent, reason):
        with self.lock:
            if self.status == 'pending':
                self.finish('not_delivered', reason)
                if getattr(agent, '_neo_strict_pending', None) is self:
                    agent._neo_strict_pending = None
            return {**self.receipt, 'status': self.status, **({'reason': self.reason} if self.reason else {})}


class _Reply(DeferredReply):
    def __init__(self, pending, agent, timeout):
        self.pending, self.agent = pending, agent
        def wait():
            pending.done.wait(max(0, pending.deadline - time.monotonic()))
            return pending.withdraw(agent, 'boundary_timeout')
        super().__init__(wait)

    def start(self, *args, **kwargs):
        try:
            return super().start(*args, **kwargs)
        except BaseException:
            self.pending.withdraw(self.agent, 'reply_unavailable')
            raise


async def steer(connection, ref, params):
    allowed = {'session_id', 'profile', 'protocol', 'request_id', 'execution_generation', 'text', 'images', 'timeout_ms'}
    images, text = params.get('images', []), params.get('text', '')
    timeout = params.get('timeout_ms', 20000)
    if (set(params) - allowed or params.get('protocol') != 1 or isinstance(params.get('protocol'), bool)
            or type(params.get('execution_generation')) is not int
            or not isinstance(params.get('request_id'), str) or not 1 <= len(params['request_id']) <= 128
            or not isinstance(text, str) or len(text) > 100000
            or not isinstance(images, list) or len(images) > 8 or not (text.strip() or images)
            or type(timeout) is not int or not 10 <= timeout <= 20000
            or any(not isinstance(i, dict) or set(i) != {'content_base64', 'filename'}
                   or any(not isinstance(v, str) for v in i.values()) for i in images)):
        raise RuntimeStoreError('invalid_params')
    authorize(connection, ref, params, 'session:control')
    authority = connection.authority
    generation = params['execution_generation']
    live = authority.sessions[ref.session_id]
    with live.event_stream.lock:
        authority.check_approval_generation(ref.session_id, generation)
        agent, _ = authority.steer_agent(ref, generation, None)
        if agent is None:
            raise RuntimeStoreError('steer_unavailable')
        if getattr(agent, '_neo_strict_pending', None) is not None:
            raise RuntimeStoreError('steer_busy')
        seen_generation, seen_ids = getattr(agent, '_neo_strict_seen', (generation, set()))
        if seen_generation != generation:
            seen_ids = set()
        if params['request_id'] in seen_ids:
            raise RuntimeStoreError('steer_duplicate')
        if len(seen_ids) >= 256:
            raise RuntimeStoreError('steer_limit')
        seen_ids.add(params['request_id'])
        agent._neo_strict_seen = (generation, seen_ids)
    received_at = time.monotonic()
    # Stage immutable bytes in the owning profile, never trust a client-supplied path.
    # This staging-only API does not put images in any legacy next-turn pending list.
    from gateway.session_images import _stage
    directory = Path(authority.profile_id) / 'cache' / 'images'
    staged = []
    try:
        for image in images:
            staged.append(await asyncio.to_thread(_stage, directory, image))
        references = '\n'.join(f'[User attached image: {i["path"]}]\nUse vision_analyze with image_url={i["path"]!r} to inspect this image.' for i in staged)
        content = text.strip() + ('\n\n' + references if references else '')
        pending = _Pending(authority, ref, params, content)
        pending.deadline = received_at + timeout / 1000
        pending.staged_paths = [image['path'] for image in staged]
        with live.event_stream.lock:
            authority.check_approval_generation(ref.session_id, generation)
            current, _ = authority.steer_agent(ref, generation, None)
            if current is not agent:
                raise RuntimeStoreError('steer_unavailable')
            if getattr(agent, '_neo_strict_pending', None) is not None:
                raise RuntimeStoreError('steer_busy')
            agent._neo_strict_pending = pending
    except BaseException:
        for image in staged:
            Path(image['path']).unlink(missing_ok=True)
        raise
    return _Reply(pending, agent, timeout / 1000)


def deliver(agent, messages, *, current_turn_user_idx):
    """Called by prepare_iteration, after a completed tool batch, before request construction.

    A receipt proves insertion in this running loop, not provider comprehension or a vision
    tool call. The immutable image files remain available to that tool after receipt.
    """
    pending = getattr(agent, '_neo_strict_pending', None)
    if pending is None or type(current_turn_user_idx) is not int:
        return False
    # Never insert before a historical tool, or into an unresolved assistant tool-call batch.
    if not 0 <= current_turn_user_idx < len(messages):
        return False
    if messages[-1].get('role') != 'tool':
        return False
    if not any(m.get('role') == 'tool' for m in messages[current_turn_user_idx + 1:]):
        return False
    tail_assistant = next((m for m in reversed(messages) if m.get('role') == 'assistant'), {})
    expected = {t.get('id') for t in tail_assistant.get('tool_calls', [])}
    results = {m.get('tool_call_id') for m in messages[current_turn_user_idx + 1:] if m.get('role') == 'tool'}
    if not expected <= results:
        return False
    live = pending.authority.sessions.get(pending.ref.session_id)
    if live is None:
        pending.withdraw(agent, 'stale_generation')
        return False
    with live.event_stream.lock, pending.lock:
        if pending.status != 'pending':
            return False
        if time.monotonic() >= pending.deadline:
            pending.finish('not_delivered', 'boundary_timeout')
            agent._neo_strict_pending = None
            return False
        try:
            pending.authority.check_approval_generation(pending.ref.session_id, pending.generation)
            current, _ = pending.authority.steer_agent(pending.ref, pending.generation, None)
            if current is not agent:
                raise RuntimeStoreError('stale_generation')
        except RuntimeStoreError:
            pending.finish('not_delivered', 'stale_generation')
            agent._neo_strict_pending = None
            return False
        from agent.prompt_builder import steer_user_row
        messages.append(steer_user_row(pending.text))
        agent._turn_user_intervened = True
        pending.finish('delivered')
        agent._neo_strict_pending = None
        return True
