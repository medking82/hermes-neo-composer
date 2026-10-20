"""Read the host's public model inventory; never open credential contents.

Unknown billing provenance remains unknown: a provider name or API list price
is not proof of what the selected account will pay. Explicit choices still work.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from .inventory import SUPPORTED, catalog_rows


def routing_metadata(value):
    """Only non-secret routing fields may enter an opaque revision.

    Config/credential file metadata supplies the change epoch for inline keys,
    extra bodies and other opaque settings; never hash those contents.
    """
    if not isinstance(value, dict):
        return {}
    fields = ('provider', 'model', 'default', 'name', 'id', 'type', 'api_mode',
              'api_key_ref', 'api_key_env', 'auth_profile', 'timeout',
              'reasoning_effort', 'max_tokens', 'temperature')
    result = {key: value[key] for key in fields if key in value
              and isinstance(value[key], (str, int, float, bool, type(None)))}
    endpoint = value.get('base_url')
    if isinstance(endpoint, str):
        try:
            parsed = urlsplit(endpoint)
            # Userinfo, path, query and fragment can carry credentials. Their
            # saved changes bind through config-file metadata, not contents.
            result['base_url'] = (parsed.scheme, parsed.hostname, parsed.port)
        except ValueError:
            result['base_url'] = 'invalid-endpoint'
    return result


def load_catalog():
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly
    from hermes_cli.inventory import ConfigContext, build_models_payload
    from agent.models_dev import PROVIDER_TO_MODELS_DEV
    home = Path(get_hermes_home()).resolve()
    config = load_config_readonly()
    model = config.get('model', {})
    model = model if isinstance(model, dict) else {'default': model}
    providers = config.get('providers', {})
    custom = config.get('custom_providers', [])
    excluded = config.get('model_catalog', {}).get('excluded_providers', []) if isinstance(config.get('model_catalog'), dict) else []
    context = ConfigContext(
        current_provider=str(model.get('provider') or ''), current_model=str(model.get('default') or ''),
        current_base_url=str(model.get('base_url') or ''),
        user_providers=providers if isinstance(providers, dict) else {},
        custom_providers=custom if isinstance(custom, list) else [],
        excluded_providers=excluded if isinstance(excluded, list) else [],
    )
    payload = build_models_payload(
        context, explicit_only=True, include_unconfigured=False, refresh=False,
        probe_custom_providers=False, probe_current_custom_provider=False,
        non_blocking_catalogs=True, picker_hints=True,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get('providers'), list):
        raise RuntimeError('Host model inventory contract is unavailable')
    # File metadata invalidates offers on local credential/config changes without
    # reading, hashing, returning, or copying the credentials themselves.
    versions = []
    for path in (home / 'config.yaml', home / 'auth.json', home / '.env', home / '.anthropic_oauth.json',
                 Path.home() / '.codex/auth.json', Path.home() / '.claude/.credentials.json'):
        try:
            stat = path.stat()
            versions.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
        except FileNotFoundError:
            versions.append((str(path), None))
    metadata, fresh = {}, False
    now = time.time()
    try:
        with (home / 'models_dev_cache.json').open(encoding='utf-8-sig') as stream:
            import os
            metadata = json.load(stream)
            fresh = 0 <= now - os.fstat(stream.fileno()).st_mtime <= 86400
    except (OSError, ValueError):
        pass
    metadata = metadata if isinstance(metadata, dict) else {}
    result = []
    for row in payload['providers']:
        if (not isinstance(row, dict) or row.get('authenticated') is not True or row.get('is_user_defined')
                or row.get('source') in ('canonical', 'configured-current') or row.get('native_catalog_empty')):
            continue
        provider = row.get('slug')
        if not isinstance(provider, str):
            continue
        provider = {'openai-api': 'openai', 'gemini': 'google'}.get(provider, provider)
        if provider not in SUPPORTED or not isinstance(row.get('models'), list):
            continue
        unavailable = row.get('unavailable_models', [])
        if not isinstance(unavailable, list):
            continue
        models = [value for value in row['models'] if isinstance(value, str) and 0 < len(value) <= 200
                  and not re.search(r'[\s\x00-\x1f]', value) and value not in unavailable]
        routing_config = [routing_metadata(model),
                          {key: routing_metadata(value) for key, value in providers.items()} if isinstance(providers, dict) else {},
                          [routing_metadata(value) for value in custom] if isinstance(custom, list) else [],
                          routing_metadata(config.get('auxiliary', {}).get('neo_next_prompt', {}))
                          if isinstance(config.get('auxiliary'), dict) else {}]
        scope = hashlib.sha256(json.dumps([str(home), provider, models, versions, routing_config], sort_keys=True).encode()).hexdigest()
        entry = {'fp': scope, 'at': now, 'models': models}
        data = metadata.get(PROVIDER_TO_MODELS_DEV.get(provider, provider), {})
        data = data.get('models', {}) if isinstance(data, dict) else {}
        data = data if isinstance(data, dict) else {}
        # Only explicit host billing provenance permits USD ranking. Current hosts
        # may omit it; never infer API billing from the provider or a token prefix.
        billing = 'usd' if row.get('billing') == 'usd' else 'unknown'
        result.extend(catalog_rows(provider, entry, scope, data, now=now, price_fresh=fresh, billing=billing))
    return result
