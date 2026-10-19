"""Prediction through the public, host-owned ctx.llm facade.

Host retries and configured fallback routes are permitted for prediction. No
provider clients, credentials, private planning methods, or source hashes here.
"""
import asyncio
import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .routing import route_identity

PREDICTION_EFFORT = 'low'
TASK = 'neo_next_prompt'
_completion_slot = threading.BoundedSemaphore(1)
_completion_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='neo-prediction')


async def run_completion(callback, snapshot):
    """One actual host call across service revisions, never the shared executor.

    Cancelling the asyncio waiter cannot stop sync SDK retries. Keep admission
    until the underlying concurrent future is actually done, not merely until
    its cancelled asyncio wrapper is done. No plugin queue or retry is added.
    """
    if not _completion_slot.acquire(blocking=False):
        raise RuntimeError('A host prediction is still in flight')
    try:
        owner_context = contextvars.copy_context()
        work = _completion_pool.submit(owner_context.run, callback, snapshot)
    except BaseException:
        # submit may enqueue before Thread.start fails. Revoke this pool and
        # discard pending work; never let a later request replay an orphan.
        _completion_pool.shutdown(wait=False, cancel_futures=True)
        _completion_slot.release()
        raise
    work.add_done_callback(lambda done: _completion_slot.release())
    return await asyncio.wrap_future(work)


def validate_context(context):
    if (context is None or getattr(context, 'plugin_id', None) != 'neo-next-prompt'
            or not callable(getattr(context, 'register_auxiliary_task', None))
            or not callable(getattr(getattr(context, 'llm', None), 'complete', None))):
        raise RuntimeError('Host plugin LLM capability is unavailable; prediction is disabled')


def complete(snapshot, *, context, owner_home, expected_plan, current_plan, metrics=None):
    from hermes_constants import get_hermes_home
    if Path(get_hermes_home()).resolve() != Path(owner_home).resolve():
        raise PermissionError('Prediction owner scope changed')
    validate_context(context)
    if route_identity(current_plan()) != route_identity(expected_plan):
        raise ValueError('Prediction settings changed before dispatch')
    route = expected_plan.get('route')
    if not route:
        raise ValueError(expected_plan.get('reason', 'Prediction route unavailable'))
    context.register_auxiliary_task(
        TASK, display_name='Neo Composer Prediction',
        description='Text-only suggestions; host credentials, retries and configured fallbacks.',
        defaults={'provider': route['provider'], 'model': route['model'],
                  'reasoning_effort': PREDICTION_EFFORT, 'timeout': 20},
    )
    messages = [
        {'role': 'system', 'content': Path(__file__).with_name('prediction.txt').read_text(encoding='utf-8')},
        {'role': 'user', 'content': json.dumps(snapshot['history'], ensure_ascii=False)},
    ]
    if route_identity(current_plan()) != route_identity(expected_plan):
        raise ValueError('Prediction settings changed while preparing request')
    if Path(get_hermes_home()).resolve() != Path(owner_home).resolve():
        raise PermissionError('Prediction owner scope changed before dispatch')
    response = context.llm.complete(messages=messages, task=TASK, max_tokens=2048,
                                    timeout=20, purpose='neo-next-prompt.prediction')
    if metrics is not None:
        usage = getattr(response, 'usage', None)
        metrics.update(provider=response.provider, model=response.model,
                       reasoning={'requested_effort': PREDICTION_EFFORT, 'managed_by': 'host'})
        metrics['usage'] = {key: getattr(usage, key, None)
                            for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    return response.text if isinstance(response.text, str) else ''
