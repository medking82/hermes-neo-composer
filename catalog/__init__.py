"""Bind generation to the real host context, never a credential or surrogate context."""
from .dashboard.plugin_api import MODEL_TASK, Store, generate, normalize


def register(ctx):
    ctx.register_auxiliary_task(
        MODEL_TASK, display_name='Neo Composer',
        description='Predict the next user message using your chosen Hermes model.')

    def suggest(params, *, session_id=None, **kwargs):
        if not session_id:
            raise ValueError('A session is required')
        key = params.get('stored_session_id') or session_id
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError('Invalid stored session id')
        return generate(ctx, Store(), key, params)

    def predict(params, *, session_id=None, **kwargs):
        """Advanced Desktop transport; routing and credentials remain host-owned."""
        if not session_id:
            raise ValueError('A session is required')
        messages = normalize(params.get('messages'))
        if not messages or messages[-1]['role'] != 'assistant':
            return {'suggestion': None, 'status': 'skipped'}
        store = Store()
        prepared = store.prepare(session_id, messages, refresh=True)
        if prepared['status'] != 'pending':
            return {'suggestion': None, 'status': prepared['status']}
        result = generate(ctx, store, session_id, {
            'messages': messages, 'token': prepared['token']})
        return {'suggestion': result.get('text') or None,
                'status': result['status'], 'source': 'hermes', 'task': MODEL_TASK}

    ctx.register_rpc('suggest', suggest)
    ctx.register_rpc('predict', predict)
