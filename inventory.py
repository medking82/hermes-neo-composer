"""Read account-bound host catalogs, not a hard-coded model ranking.

No catalog fetch, model probe, paid request, or background refresh is started here.
Users refresh model availability through Hermes' existing model settings.
"""
import os
import time
import json
import sys
from pathlib import Path

MAX_AGE = 86400
# Transport support, not model/cost preferences. Unvalidated custom routes stay closed.
SUPPORTED = {'openai-codex', 'openai', 'anthropic', 'google', 'gemini', 'deepseek', 'xai', 'openrouter'}
DIRECT_USD = {'openai', 'anthropic', 'google', 'gemini', 'deepseek', 'xai'}


def catalog_rows(provider, entry, fingerprint, metadata, *, now, price_fresh, billing):
    if (not isinstance(fingerprint, str) or not fingerprint or not isinstance(entry, dict) or entry.get('fp') != fingerprint or entry.get('fallback')
            or not isinstance(entry.get('at'), (int, float)) or not 0 <= now - entry['at'] <= MAX_AGE
            or not isinstance(entry.get('models'), list)):
        return []
    rows = []
    for model in dict.fromkeys(m for m in entry['models'] if isinstance(m, str)):
        meta = metadata.get(model, {})
        meta = meta if isinstance(meta, dict) else {}
        mods, limits, costs = [meta.get(k) if isinstance(meta.get(k), dict) else {} for k in ('modalities', 'limit', 'cost')]
        # Account catalog is chat-filtered by the host. Unknown capability cannot auto-rank.
        verified_text = all(isinstance(mods.get(k), list) and 'text' in mods[k] for k in ('input', 'output'))
        text = not mods or verified_text
        priced = billing == 'usd' and price_fresh and 'input' in costs and 'output' in costs
        rows.append(dict(provider=provider, model=model, available=True, text=text, verified_text=verified_text, account_scope=fingerprint,
                         billing=billing, priced=priced, input_cost=costs.get('input') if priced else None,
                         output_cost=costs.get('output') if priced else None,
                         context=limits.get('context', 0), max_output=limits.get('output', 0),
                         price_source='models.dev cached estimate' if priced else 'Unknown / subscription quota'))
    return rows


def billing_kind(provider, key, other_credentials):
    # A pool/stored login can override an env key; uncertain billing remains unknown.
    # Positive API-key families only: JWT, cc-, future OAuth and unknown forms are not prices.
    oauth = provider == 'anthropic' and not str(key).startswith(('sk-ant-api', 'sk-ant-usr', 'sk-ant-svc', 'sk-ant-admin'))
    return 'usd' if provider in DIRECT_USD and key and not oauth and not other_credentials else 'unknown'


def load_catalog():
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly, get_env_value_prefer_dotenv
    from hermes_cli.models import _load_provider_models_cache, _credential_fingerprint, _chat_catalog_rows
    from hermes_cli.auth import PROVIDER_REGISTRY, _load_auth_store, _global_auth_file_path, _env_secret
    from agent.models_dev import PROVIDER_TO_MODELS_DEV
    config = load_config_readonly()
    model_config = config.get('model', {})
    model_config = model_config if isinstance(model_config, dict) else {}
    provider_config = config.get('providers', {})
    provider_config = provider_config if isinstance(provider_config, dict) else {}
    # Read data and freshness from the same file descriptor, never memory/bundled fallback.
    data, price_fresh = {}, False
    now = time.time()
    try:
        with (get_hermes_home() / 'models_dev_cache.json').open(encoding='utf-8-sig') as stream:
            data = json.load(stream)
            price_fresh = 0 <= now - os.fstat(stream.fileno()).st_mtime <= MAX_AGE
    except (OSError, ValueError):
        pass
    data = data if isinstance(data, dict) else {}
    cached = _load_provider_models_cache()
    auth = _load_auth_store()
    auth = auth if isinstance(auth, dict) else {}
    root_auth_path = _global_auth_file_path()
    root_auth = {}
    if root_auth_path and root_auth_path.is_file():
        # Metadata only; do not seed a pool, refresh, or rewrite a credential file.
        root_auth = json.loads(root_auth_path.read_text(encoding='utf-8-sig'))
        if not isinstance(root_auth, dict): raise ValueError('Invalid inherited credential metadata')
    rows = []
    for provider in sorted(set(cached) & SUPPORTED):
        pcfg = provider_config.get(provider, {})
        canonical = {'openai': 'openai-api', 'google': 'gemini'}.get(provider, provider)
        registry = PROVIDER_REGISTRY.get(canonical)
        if registry is None:
            continue
        base_env = registry.base_url_env_var
        if (isinstance(pcfg, dict) and (pcfg.get('enabled') is False or any(pcfg.get(k) for k in ('base_url', 'api', 'url', 'extra_headers')))
                or (base_env and _env_secret(base_env))
                or model_config.get('provider') == provider and model_config.get('base_url')):
            continue
        keys = [get_env_value_prefer_dotenv(name) for name in registry.api_key_env_vars if _env_secret(name)]
        key = keys[0] if keys else ''
        # The pinned host fingerprint reads raw env; reject when profile-scoped keys differ.
        if any((os.environ.get(name) or '') != (get_env_value_prefer_dotenv(name) or '') for name in registry.api_key_env_vars):
            continue
        local_credential = any(isinstance(auth.get(section), dict) and any(auth[section].get(alias) for alias in {provider, canonical}) for section in ('providers', 'credential_pool'))
        inherited = any(isinstance(root_auth.get(section), dict) and any(root_auth[section].get(alias) for alias in {provider, canonical}) for section in ('providers', 'credential_pool'))
        if provider != 'openai-codex' and inherited and not local_credential:
            continue  # The host API-key fingerprint does not bind a borrowed root account.
        other = len(keys) > 1 or local_credential
        if provider == 'anthropic':
            from agent.anthropic_credentials import claude_code_credentials_path, _root_hermes_oauth_file
            external = claude_code_credentials_path()
            root_oauth = _root_hermes_oauth_file()
            # These sources are not represented by the pinned host catalog fingerprint.
            if sys.platform == 'darwin' or root_oauth and root_oauth.exists() or external != Path.home() / '.claude/.credentials.json' and external.exists():
                continue
            other = other or any(path.exists() for path in (get_hermes_home() / '.anthropic_oauth.json', external))
        if provider == 'openai-codex':
            from hermes_cli.codex_models import codex_catalog_credential_identity
            if codex_catalog_credential_identity() == 'missing':
                continue
        elif not key and not local_credential:
            continue
        entry = cached.get(provider)
        if isinstance(entry, dict) and isinstance(entry.get('models'), list):
            entry = {**entry, 'models': _chat_catalog_rows(entry['models'])}
        provider_meta = data.get(PROVIDER_TO_MODELS_DEV.get(provider, provider), {})
        metadata = provider_meta.get('models', {}) if isinstance(provider_meta, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        # Legacy alias fingerprints omit API-key values on this host: refuse those caches.
        rows.extend(catalog_rows(provider, entry, _credential_fingerprint(canonical), metadata, now=now,
                                 price_fresh=price_fresh, billing=billing_kind(provider, key, other)))
    return rows
