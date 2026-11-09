"""Neo Composer plugin. No tools, injected messages, or automatic actions."""
import hashlib
import json
import uuid
from pathlib import Path

from .service import Service

_owner_home = None
_service = None
_scope = uuid.uuid4().hex


def register(ctx):
    global _owner_home
    from hermes_constants import get_hermes_home
    _owner_home = Path(get_hermes_home()).resolve()


def validate_scope():
    from hermes_constants import get_hermes_home
    from .llm_once import validate_host
    validate_host()
    if _owner_home is None or Path(get_hermes_home()).resolve() != _owner_home:
        raise PermissionError('next-prompt owner scope mismatch')


def settings_view():
    validate_scope()
    from .settings import load_settings
    from .inventory import load_catalog
    from .routing import select_route
    settings, catalog = load_settings(_owner_home), load_catalog()
    catalog = [{k: v for k, v in row.items() if k != 'account_scope'} for row in catalog]
    return {'scope': _scope, 'settings': settings, 'catalog': catalog, 'selection': select_route(settings, catalog),
            'note': 'Catalog availability is not a live inference guarantee. Refresh models in Hermes settings if the catalog is stale.'}


def update_settings(value, scope):
    validate_scope()
    if scope != _scope:
        raise ValueError('Profile or connection changed; reload settings before saving.')
    from .settings import save_settings, validate_settings
    from .inventory import load_catalog
    value = validate_settings(value)
    from .settings import load_settings
    previous = load_settings(_owner_home)
    added = set(value['providers']) - set(previous['providers'])
    if value['enabled'] and added and not added.issubset({row['provider'] for row in load_catalog()}):
        raise ValueError('Provider catalog unavailable. Refresh models in Hermes settings first.')
    return save_settings(_owner_home, value)


def get_service():
    global _service
    from .llm_once import validate_host, prediction_plan, PREDICTION_EFFORT
    validate_host()
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly
    if _owner_home is None or Path(get_hermes_home()).resolve() != _owner_home:
        raise PermissionError('next-prompt owner scope mismatch')
    cfg = load_config_readonly()
    raw_model = cfg.get('model', {})
    model = raw_model if isinstance(raw_model, dict) else {'default': raw_model}
    # Only non-secret routing settings are versioned. No credential copies.
    prompt_digest = hashlib.sha256(Path(__file__).with_name('prediction.txt').read_bytes()).hexdigest()
    plan = prediction_plan()
    from .routing import route_identity
    revision = hashlib.sha256(json.dumps([route_identity(plan), prompt_digest, PREDICTION_EFFORT], sort_keys=True).encode()).hexdigest()
    if _service is None or _service.route_revision != revision:
        from .llm_once import complete
        _service = Service(_owner_home, lambda snapshot, plan=plan, home=_owner_home: complete(snapshot, expected_plan=plan, owner_home=home), revision)
    _service.prediction_plan = plan
    return _service
