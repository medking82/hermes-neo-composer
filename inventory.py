"""Catalog projection helpers; the public host inventory owns authentication.

These pure functions keep conservative price/capability handling. No credential
file, environment secret, private auth helper or provider client is read here.
"""
MAX_AGE = 86400
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
    # Historical pure compatibility helper; the SDK catalog never reads tokens.
    oauth = provider == 'anthropic' and not str(key).startswith(('sk-ant-api', 'sk-ant-usr', 'sk-ant-svc', 'sk-ant-admin'))
    return 'usd' if provider in DIRECT_USD and key and not oauth and not other_credentials else 'unknown'


def load_catalog():
    from .sdk_catalog import load_catalog as public_catalog
    return public_catalog()
