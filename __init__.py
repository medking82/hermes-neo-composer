"""Neo Composer plugin. No tools, injected messages, or automatic actions."""
import hashlib
import json
import uuid
from pathlib import Path

from .service import Service

_owner_home = None
_context = None
_service = None
_scope = uuid.uuid4().hex


def register(ctx):
    global _owner_home, _context, _service, _scope
    from hermes_constants import get_hermes_home
    _owner_home = Path(get_hermes_home()).resolve()
    _context = ctx
    _service = None
    _scope = uuid.uuid4().hex


def validate_scope():
    # Keep profile-owned settings reachable even if an optional adapter is unavailable.
    from hermes_constants import get_hermes_home
    if _owner_home is None or Path(get_hermes_home()).resolve() != _owner_home:
        raise PermissionError('next-prompt owner scope mismatch')


def _settings_catalog():
    # Public host inventory is optional; failure must not hide profile settings.
    try:
        from .sdk_catalog import load_catalog
        return load_catalog()
    except Exception:
        return []


def settings_view():
    validate_scope()
    from .settings import load_settings
    from .routing import select_route
    settings, catalog = load_settings(_owner_home), _settings_catalog()
    catalog = [{k: v for k, v in row.items() if k != 'account_scope'} for row in catalog]
    return {'scope': _scope, 'settings': settings, 'catalog': catalog, 'selection': select_route(settings, catalog),
            'note': 'Catalog availability is not a live inference guarantee. Refresh models in Hermes settings if the catalog is stale.'}


def update_settings(value, scope):
    validate_scope()
    if scope != _scope:
        raise ValueError('Profile or connection changed; reload settings before saving.')
    from .settings import save_settings, validate_settings
    value = validate_settings(value)
    from .settings import load_settings
    previous = load_settings(_owner_home)
    added = set(value['providers']) - set(previous['providers'])
    if value['enabled'] and added and not added.issubset({row['provider'] for row in _settings_catalog()}):
        raise ValueError('Provider catalog unavailable. Refresh models in Hermes settings first.')
    return save_settings(_owner_home, value)


def get_service():
    global _service
    from .sdk_llm import validate_context, complete, run_completion, PREDICTION_EFFORT
    from .sdk_catalog import routing_metadata
    from .settings import load_settings
    from .routing import route_identity, select_route
    from hermes_cli.config import load_config_readonly
    validate_scope()
    validate_context(_context)
    cfg = load_config_readonly()
    def prediction_plan():
        plugins = load_config_readonly().get('plugins', {})
        if (not isinstance(plugins, dict) or 'neo-next-prompt' not in plugins.get('enabled', [])
                or 'neo-next-prompt' in plugins.get('disabled', [])):
            raise PermissionError('Prediction plugin is no longer enabled in this profile')
        settings = load_settings(_owner_home)
        return {**select_route(settings, _settings_catalog() if settings['enabled'] else []), 'settings': settings, 'scope': _scope}
    prompt_digest = hashlib.sha256(Path(__file__).with_name('prediction.txt').read_bytes()).hexdigest()
    plan = prediction_plan()
    # A host auxiliary override is operator-owned. Bind it opaquely so changing
    # its route invalidates cached offers without exporting endpoints or keys.
    task_config = routing_metadata(cfg.get('auxiliary', {}).get('neo_next_prompt', {})) if isinstance(cfg.get('auxiliary'), dict) else {}
    revision = hashlib.sha256(json.dumps([route_identity(plan), prompt_digest, PREDICTION_EFFORT, task_config], sort_keys=True).encode()).hexdigest()
    if _service is None or _service.route_revision != revision:
        _service = Service(_owner_home, lambda snapshot, plan=plan, home=_owner_home, context=_context: complete(
            snapshot, context=context, expected_plan=plan, owner_home=home, current_plan=prediction_plan), revision,
            completion_runner=run_completion)
    _service.prediction_plan = plan
    return _service
