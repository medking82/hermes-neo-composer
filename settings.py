"""Prediction-only settings. Never rewrite Hermes config or copy credentials."""
import json
import os
import re
import tempfile
from pathlib import Path

DEFAULTS = {'enabled': False, 'providers': [], 'model': '', 'fallback': ''}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Expected enabled, providers, model and fallback only.')
    if type(value['enabled']) is not bool:
        raise ValueError('enabled must be boolean')
    providers = value['providers']
    if (not isinstance(providers, list) or len(providers) > 16 or
            any(not isinstance(p, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', p) for p in providers)):
        raise ValueError('Invalid provider selection')
    for name in ('model', 'fallback'):
        token = value[name]
        if not isinstance(token, str) or len(token) > 240 or (token and not re.fullmatch(r'[a-z][a-z0-9-]*/[^\s\x00-\x1f]+', token)):
            raise ValueError('Invalid model selection')
        if token and token.split('/', 1)[0] not in providers:
            raise ValueError('Selected model must belong to an approved provider')
    return {**value, 'providers': sorted(set(providers))}


def settings_path(home):
    home = Path(home).resolve()
    path = home / 'plugin-data' / 'neo-next-prompt' / 'settings.json'
    if any(p.is_symlink() for p in [path, path.parent, path.parent.parent]) or not path.resolve().is_relative_to(home):
        raise ValueError('Prediction settings must stay inside the owning profile')
    return path


def load_settings(home):
    path = settings_path(home)
    if not path.exists():
        return {**DEFAULTS, 'providers': []}
    return validate_settings(json.loads(path.read_text(encoding='utf-8')))


def save_settings(home, value):
    value = validate_settings(value)
    path = settings_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return value
