"""Deterministic selection; no model names, credentials, or speculative prices."""
from decimal import Decimal, InvalidOperation


def _rate(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def route_identity(plan):
    route = plan.get('route') or {}
    identity = [[route.get(key) for key in ('provider', 'model', 'account_scope')], plan.get('settings', {})]
    if 'scope' in plan:
        identity.append(['sdk_scope', plan['scope']])
    return identity


def select_route(settings, catalog):
    """Only compare verified USD estimates. Subscription quota is not a dollar price."""
    if not settings.get('enabled'):
        return {'route': None, 'reason': 'Predictions are disabled.'}
    rows = [r for r in catalog if r.get('available') and r.get('text')
            and r['provider'] in settings.get('providers', [])]
    by_id = {r['provider'] + '/' + r['model']: r for r in rows}
    explicit = settings.get('model')
    if explicit:
        row = by_id.get(explicit)
        return {'route': row, 'reason': 'Explicit prediction model.' if row else 'Selected model is unavailable. No fallback was attempted.'}
    known = []
    for row in rows:
        inp, out = _rate(row.get('input_cost')), _rate(row.get('output_cost'))
        if (row.get('billing') == 'usd' and row.get('priced') and inp is not None and out is not None
                and row.get('verified_text', row.get('text'))
                and (_rate(row.get('context')) or 0) >= 8192 and (_rate(row.get('max_output')) or 0) >= 2048):
            # Same bounded task budget for each model. This is an estimate, not an invoice.
            known.append(((inp * 2048 + out * 2048) / 1000000, row['provider'], row['model'], row))
    if known:
        score, _, _, row = min(known, key=lambda item: item[:3])
        return {'route': row, 'reason': 'Lowest verified USD estimate among eligible approved models.', 'estimated_usd': str(score)}
    fallback = by_id.get(settings.get('fallback'))
    if fallback:
        return {'route': fallback, 'reason': 'No comparable verified price; using your explicit low-cost fallback.'}
    return {'route': None, 'reason': 'No comparable verified prices. Select a low-cost fallback or an explicit model; no request will be sent.'}
