"""Authenticated, profile-scoped endpoints mounted by Hermes plugin API."""
from typing import Literal
from pathlib import Path
import importlib.util
import hashlib
import sys
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
_load_lock = threading.RLock()


class Generate(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    stored_id: str = Field(min_length=1, max_length=160)


class Decision(BaseModel):
    root: str = Field(min_length=1, max_length=160)
    version: str = Field(pattern=r'^[0-9a-f]{64}$')
    request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    status: Literal['consumed', 'dismissed']


def _package():
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly
    home = Path(get_hermes_home()).resolve()
    root = Path(__file__).resolve().parents[1]
    settings = load_config_readonly().get('plugins', {})
    if not isinstance(settings, dict) or home != root.parents[1] or 'neo-next-prompt' not in settings.get('enabled', []) or 'neo-next-prompt' in settings.get('disabled', []):
        raise HTTPException(404, 'next-prompt is not enabled in this profile')
    # API hot-mount must not force-reload every other plugin or restart a live
    # chat. Import only this package, in a scope-specific namespace.
    name = '_neo_next_prompt_api_' + hashlib.sha256(str(root).encode()).hexdigest()
    with _load_lock:
        module = sys.modules.get(name)
        if module is None:
            spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
                module.register(None)
            except BaseException:
                sys.modules.pop(name, None)
                raise
        try:
            module.validate_scope()
            return module
        except RuntimeError as exc:
            raise HTTPException(404, 'next-prompt host requires revalidation') from exc


def service():
    return _package().get_service()


@router.get('/settings')
def settings_get():
    return _package().settings_view()


@router.post('/settings')
def settings_set(body: dict):
    try:
        package = _package()
        if set(body) != {'scope', 'settings'}:
            raise ValueError('Expected scope and settings')
        package.update_settings(body['settings'], body['scope'])
        return package.settings_view()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/health')
def health():
    service()
    return {'contract': 'neo-next-prompt-v1', 'enabled': True}


@router.post('/suggestion')
async def suggestion(body: Generate):
    active = service()
    if not getattr(active, 'prediction_plan', {'route': True})['route']:
        return {'session_id': body.session_id, 'stored_id': body.stored_id, 'candidate': None}
    key = resolve_runtime_session(body.session_id, active.home)
    result = await active.generate(key, body.stored_id) if key else None
    if result and (resolve_runtime_session(body.session_id, active.home) != key
                   or getattr(service(), 'route_revision', None) != getattr(active, 'route_revision', None)):
        result = None
    return {'session_id': body.session_id, 'stored_id': body.stored_id, 'candidate': result}


def resolve_runtime_session(runtime_id, home):
    # Desktop runtime ids are short RPC handles, NOT state.db session ids.
    # Read the live binding under its lock; do not reattach or select by recency.
    from tui_gateway import server
    from hermes_constants import get_process_hermes_home
    with server._sessions_lock:
        record = server._sessions.get(runtime_id)
        if not record or record.get('running') or record.get('source') != 'desktop':
            return None
        owner = Path(record.get('profile_home') or get_process_hermes_home()).resolve()
        if owner != home.resolve():
            return None
        return record.get('session_key')


@router.post('/decision')
def decision(body: Decision):
    return {'recorded': service().decide(body.model_dump(), body.status)}
