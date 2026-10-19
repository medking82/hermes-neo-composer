"""Reuse the host's provider preparation/transport, without its recovery ladder.

The plugin is deployed against a pinned host revision; unknown adapters fail closed.
No credentials are exported or copied. Prediction has its own text-only route;
the primary session model/effort is never changed.
"""
from pathlib import Path
import hashlib
import json
import re

PREDICTION_EFFORT = 'low'

# Prediction transport/catalog and owner-resolution seams only. Native composer
# and Steering fingerprints remain in the separate legacy `pins` inventory.
PREDICTION_PIN_PATHS = (
    'agent/anthropic_credentials.py', 'hermes_constants.py', 'hermes_cli/auth.py',
    'hermes_cli/codex_models.py', 'hermes_cli/models.py',
    'hermes_cli/model_switch_providers.py', 'agent/models_dev.py',
    'agent/auxiliary_client.py', 'tui_gateway/server.py', 'tui_gateway/ws.py',
    'hermes_cli/web_server_dashboard.py', 'agent/agent_runtime_helpers.py',
)


def prediction_plan():
    from hermes_constants import get_hermes_home
    from .settings import load_settings
    from .inventory import load_catalog
    from .routing import select_route
    settings = load_settings(get_hermes_home())
    return {**select_route(settings, load_catalog() if settings['enabled'] else []), 'settings': settings}


def validate_host():
    """Unknown prediction dependencies fail closed without gating optional native code."""
    from agent import auxiliary_client as aux
    root = Path(aux.__file__).resolve().parents[1]
    expected = json.loads(Path(__file__).with_name('host-compat.json').read_text())
    pins = expected.get('prediction_pins')
    error = 'host prediction adapter changed; revalidation required'
    if not isinstance(pins, dict) or set(pins) != set(PREDICTION_PIN_PATHS):
        raise RuntimeError(error)
    for name in PREDICTION_PIN_PATHS:
        approved = pins[name]
        if (not isinstance(approved, list) or not approved
                or any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) for sha in approved)):
            raise RuntimeError(error)
        file = root / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() not in approved:
            raise RuntimeError(error)


def complete(snapshot, metrics=None, *, expected_plan=None, owner_home=None):
    validate_host()
    from hermes_constants import get_hermes_home
    from .routing import route_identity
    if owner_home is not None and Path(get_hermes_home()).resolve() != Path(owner_home).resolve():
        raise PermissionError('Prediction owner scope changed')
    from agent import auxiliary_client as aux
    from hermes_cli.config import load_config_readonly
    compatibility = json.loads(Path(__file__).with_name('host-compat.json').read_text())
    if hashlib.sha256(Path(aux.__file__).read_bytes()).hexdigest() != compatibility['auxiliary_client_sha256']:
        raise RuntimeError('host model adapter changed; revalidation required')
    raw_model = load_config_readonly().get('model', {})
    configured = raw_model if isinstance(raw_model, dict) else {'default': raw_model}
    current = prediction_plan()
    if expected_plan is not None and route_identity(current) != route_identity(expected_plan):
        raise ValueError('Prediction settings changed before dispatch')
    plan = expected_plan if expected_plan is not None else current
    route = plan['route']
    if not route:
        raise ValueError(plan['reason'])
    provider, model = route['provider'], route['model']
    from hermes_cli.auth import PROVIDER_REGISTRY
    aliases = {'openai': 'openai-api', 'google': 'gemini'}
    main_provider = configured.get('provider') or ''
    main_provider = aliases.get(main_provider, main_provider)
    prediction_provider = aliases.get(provider, provider)
    # A known, different main provider cannot veto an independently selected route.
    # A same-provider or unknown-provider custom endpoint still requires revalidation;
    # a configured base_url that already matches the main provider's official registry
    # inference URL is the normal default, not a custom destination. The prepared
    # prediction destination below must still match its official registry.
    main_registry = PROVIDER_REGISTRY.get(main_provider)
    official_main_url = (main_registry.inference_base_url or '').rstrip('/') if main_registry else ''
    configured_base = configured.get('base_url')
    main_base_url = configured_base.rstrip('/') if isinstance(configured_base, str) and configured_base else ''
    if main_base_url and (main_provider not in PROVIDER_REGISTRY
                          or (main_provider == prediction_provider
                              and (not official_main_url or main_base_url != official_main_url))):
        raise ValueError('custom endpoint requires explicit adapter revalidation')
    reasoning = {'enabled': True, 'effort': PREDICTION_EFFORT}
    messages = [
        {'role': 'system', 'content': Path(__file__).with_name('prediction.txt').read_text(encoding='utf-8')},
        {'role': 'user', 'content': __import__('json').dumps(snapshot['history'], ensure_ascii=False)},
    ]
    request, _, _ = aux._plan_aux_call(
        None, async_mode=False, provider=provider, model=model,
        base_url=None, api_key=None, main_runtime=None, messages=messages,
        temperature=None, max_tokens=2048, tools=None, timeout=20,
        extra_body=None, reasoning_config=reasoning,
        extra_headers=None, api_mode=None, route_info=None,
    )
    registry = PROVIDER_REGISTRY.get({'openai': 'openai-api', 'google': 'gemini'}.get(provider, provider))
    expected_url = registry.inference_base_url.rstrip('/') if registry else ''
    urls = [str(getattr(request.client, 'base_url', '') or ''), str(request.base_info or ''), str(request.resolved_base_url or '')]
    if (request.request_provider != provider or request.kwargs.get('model') != model or not expected_url
            or not urls[0] or any(url and url.rstrip('/') != expected_url for url in urls)):
        raise ValueError('Planned destination differs from approved prediction route')
    leaf = getattr(request.client, '_real_client', request.client)
    if getattr(leaf, 'max_retries', None) != 0:
        raise ValueError('Prediction transport must disable SDK retries')
    if request.kwargs.get('tools'):
        raise ValueError('unexpected tools on text-only suggestion request')
    # Same transport used by the host, but exactly one primary attempt. Do not
    # call call_llm(), whose default retries/fallback could switch this route.
    if route_identity(prediction_plan()) != route_identity(plan):
        raise ValueError('Prediction settings changed while preparing request')
    response = aux._relay_sync_completion(
        request.client, request.kwargs, provider=request.request_provider,
        api_mode=request.resolved_api_mode,
        create=lambda kwargs: request.client.chat.completions.create(**kwargs),
    )
    message = response.choices[0].message
    if metrics is not None:
        usage = getattr(response, 'usage', None)
        metrics.update(provider=request.request_provider, model=model, reasoning=reasoning)
        metrics['usage'] = {name: getattr(usage, name, None) for name in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens']}
    if getattr(message, 'tool_calls', None):
        raise ValueError('suggestion response attempted a tool call')
    text = getattr(message, 'content', None)
    return text if isinstance(text, str) else ''
