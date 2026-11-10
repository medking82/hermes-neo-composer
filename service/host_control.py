"""Fixed-root, source-only host adapter control. No subprocess or client paths.

The HTTP server supplies authentication/origin gates. This module never launches
builds or restarts a gateway. A source patch is not evidence of runtime support.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / 'host-adapter' / 'neo_host_adapter.py'
RECEIPT = '.neo-host-control.json'
LOCK = '.neo-host-control.lock'


def load_installer():
    name = '_neo_local_installer'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, INSTALLER)
        if spec is None or spec.loader is None:
            raise RuntimeError('host adapter installer unavailable')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def installed_root(cfg):
    """Only service-operator config may override the standard installation root."""
    if cfg.get('hermes_root'):
        return Path(cfg['hermes_root']).expanduser().absolute()
    if os.name == 'nt':
        home = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'hermes'
    else:
        home = Path.home() / '.hermes'
    return home / 'hermes-agent'


class ControlError(Exception):
    def __init__(self, message, code=409):
        super().__init__(message)
        self.code = code


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class HostControl:
    def __init__(self, cfg):
        self.root = installed_root(cfg)
        self.mutex = threading.Lock()
        self.installer = load_installer()

    def _paths(self):
        plan = self.installer.build_plan()
        return set(plan.copies) | set(plan.copies_frontend) | {edit.file for edit in plan.edits}

    def _safe(self, relative):
        path = self.root / relative
        if not path.is_relative_to(self.root) or '..' in Path(relative).parts:
            raise ControlError('unsafe adapter path')
        for part in (path, *path.parents):
            if part.is_symlink():
                raise ControlError('symlink in adapter path: ' + str(part))
            if part == self.root:
                break
        return path

    def _validate(self):
        if not self.root.is_dir():
            raise ControlError('installed Hermes source root not found', 422)
        for rel in [*self._paths(), RECEIPT, LOCK, self.installer.MANIFEST, self.installer.BACKUPS]:
            self._safe(rel)

    def _receipt(self):
        path = self._safe(RECEIPT)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def _view(self):
        self._validate()
        backend = self.installer.plan_changes(self.root, 'skip')
        all_changes = self.installer.plan_changes(self.root, 'auto')
        has_frontend = (self.root / 'apps/desktop/src').is_dir()
        frontend_changes = [rel for rel in all_changes if rel.startswith('apps/desktop/')]
        backend_applied = not backend
        frontend_applied = has_frontend and not frontend_changes
        return {
            'contract': 1, 'root': str(self.root), 'compatible': True,
            'can_install': bool(all_changes), 'pending': sorted(all_changes),
            'backend': {'source_applied': backend_applied, 'restart_required': backend_applied,
                        'runtime_verified': False},
            'frontend': {'state': ('rebuild_required' if frontend_applied else 'source_pending')
                         if has_frontend else 'source_missing',
                         'source_applied': frontend_applied, 'automatic_rebuild': False,
                         'rebuild_required': frontend_applied,
                         'reason': 'Source patches require a rebuilt source Desktop and gateway restart. '
                                   'Neo cannot replace a packaged/MSIX/app.asar renderer. '
                                   'Use deploy/rebuild-host-wsl.sh in WSL on PC; launch its source Desktop. '
                                   'Capability availability must be checked in that running app.'},
            'rollback_available': bool(self._receipt()),
        }

    @contextmanager
    def _mutation(self):
        path = self._safe(LOCK)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ControlError('another adapter operation owns the lock; inspect ' + str(path)) from None
        try:
            os.close(fd)
            yield
        finally:
            path.unlink(missing_ok=True)

    def _save_receipt(self, result):
        bid = result['backup']
        manifest = json.loads(self._safe(self.installer.MANIFEST).read_text())
        files = manifest['files']
        receipt = {'backup': bid, 'files': files,
                   'installed': {rel: digest(self._safe(rel)) for rel in files},
                   'originals': {rel: digest(self._safe(f'{self.installer.BACKUPS}/{bid}/{rel}'))
                                 for rel, kind in files.items() if kind == 'modified'}}
        path = self._safe(RECEIPT)
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')

    def _rollback(self):
        receipt = self._receipt()
        if not receipt:
            raise ControlError('no click-install rollback receipt; use the installer CLI for older installs')
        bid = receipt['backup']
        if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', bid):
            raise ControlError('invalid rollback receipt')
        base = f'{self.installer.BACKUPS}/{bid}'
        manifest = json.loads(self._safe(base + '/manifest.json').read_text())
        files = manifest['files']
        if files != receipt['files'] or not set(files).issubset(self._paths()):
            raise ControlError('rollback manifest does not match the installed receipt')
        for rel, kind in files.items():
            if kind not in {'modified', 'created'} or digest(self._safe(rel)) != receipt['installed'].get(rel):
                raise ControlError('source changed since install; refusing rollback: ' + rel)
            if kind == 'modified' and digest(self._safe(base + '/' + rel)) != receipt['originals'].get(rel):
                raise ControlError('backup changed since install; refusing rollback: ' + rel)
        result = self.installer.rollback(self.root, bid)
        self._safe(RECEIPT).unlink()
        return result

    def run(self, action):
        if action not in {'check', 'status', 'install', 'rollback'}:
            raise ControlError('unknown host-adapter action', 404)
        if not self.mutex.acquire(blocking=False):
            raise ControlError('host-adapter operation in progress')
        try:
            self._validate()
            result = None
            if action in {'install', 'rollback'}:
                with self._mutation():
                    if action == 'install':
                        result = self.installer.install(self.root, 'auto')
                        if result['status'] == 'installed':
                            self._save_receipt(result)
                    else:
                        result = self._rollback()
            state = self._view()
            if result:
                state['action'] = result['status']
                state['result'] = result
                if action == 'rollback':
                    state['backend']['restart_required'] = True
                    state['frontend']['rebuild_required'] = (self.root / 'apps/desktop/src').is_dir()
                    state['frontend']['state'] = 'rollback_rebuild_required'
            return state
        except self.installer.Refuse as exc:
            raise ControlError(str(exc), 422) from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ControlError('host-adapter operation refused: ' + str(exc), 422) from exc
        finally:
            self.mutex.release()
