"""Bind generation to the real host context, never a credential or surrogate context."""
from .dashboard.plugin_api import Store, generate


def register(ctx):
    def suggest(params, *, session_id=None, **kwargs):
        if not session_id:
            raise ValueError('A session is required')
        key = params.get('stored_session_id') or session_id
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError('Invalid stored session id')
        return generate(ctx, Store(), key, params)

    ctx.register_rpc('suggest', suggest)
