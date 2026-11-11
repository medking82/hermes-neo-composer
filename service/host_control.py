"""Fixed-root host adapter control with verified Windows Desktop staging."""
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
        self.restart_pending = False
        self.installer = load_installer()
        name = '_neo_desktop_install'
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('desktop_install.py'))
            if spec is None or spec.loader is None:
                raise RuntimeError('desktop installer unavailable')
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        self.desktop = sys.modules[name].DesktopInstall(self.root)
        self.desktop.monitor(self.mutex)

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
        for rel in [*self._paths(), RECEIPT, LOCK, self.installer.MANIFEST, self.installer.BACKUPS,
                    '.neo-desktop-install.json', '.neo-desktop-stage', '.neo-desktop-resources-backup',
                    '.neo-desktop-swap-old', '.neo-desktop-build.log']:
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
        desktop = self.desktop.read()
        return {
            'desktop': desktop,
            'contract': 1, 'root': str(self.root), 'compatible': True,
            'can_install': bool(all_changes), 'pending': sorted(all_changes),
            'backend': {'source_applied': backend_applied, 'restart_required': backend_applied,
                        'runtime_verified': False},
            'frontend': {'state': ('rebuild_required' if frontend_applied else 'source_pending')
                         if has_frontend else 'source_missing',
                         'source_applied': frontend_applied, 'automatic_rebuild': self.desktop.available,
                         'rebuild_required': frontend_applied,
                         'reason': 'On Windows, Install builds and verifies a staged Desktop. Close Hermes after '
                                   'the build completes; the local service applies it and reopens Hermes.'},
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

    def _validate_rollback(self):
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
        return bid

    def _rollback(self):
        bid = self._validate_rollback()
        result = self.installer.rollback(self.root, bid)
        self._safe(RECEIPT).unlink()
        return result

    def reapply_after_update(self):
        """Re-apply a consented one-click install that a Hermes update reverted.

        `hermes update` (desktop updater: --keep-stash) stashes the adapter's tracked edits, so
        Ctrl+Enter loses `steerStrict` after every update. Only acts when a click-install receipt
        exists (the user already chose to install) and the adapter plan is pending again; the
        installer still refuses anything that is not provably pristine upstream.
        """
        if not self._receipt():
            return None
        try:
            if not self._view()['pending']:
                return None
            return self.run('install')
        except (ControlError, self.installer.Refuse) as exc:
            return {'action': 'refused', 'reason': str(exc)}

    def _restart_worker(self):
        # Allow the HTTP acknowledgement and UI status to arrive before shutdown.
        threading.Event().wait(2)
        with self.mutex:
            try:
                with self._mutation(), self.desktop.custody():
                    self.desktop.restart()
            except Exception as exc:
                state = self.desktop.read()
                self.desktop.write({**state, 'restart_error': str(exc)})
            finally:
                self.restart_pending = False

    def run(self, action):
        if action not in {'check', 'status', 'install', 'rollback', 'restart'}:
            raise ControlError('unknown host-adapter action', 404)
        if not self.mutex.acquire(blocking=False):
            raise ControlError('host-adapter operation in progress')
        try:
            self._validate()
            result = None
            if action == 'restart':
                if self.restart_pending:
                    raise ControlError('Desktop restart already scheduled')
                with self._mutation(), self.desktop.custody():
                    if not self.desktop.available:
                        raise ControlError('automatic restart requires the installed Windows Desktop', 422)
                    self.desktop.validate_handoff()
                self.restart_pending = True
                try:
                    threading.Thread(target=self._restart_worker, name='neo-desktop-restart', daemon=True).start()
                except Exception:
                    self.restart_pending = False
                    raise
                return {'action': 'restart_scheduled', 'desktop': self.desktop.read()}
            if action in {'install', 'rollback'}:
                with self._mutation(), self.desktop.custody():
                    if action == 'install':
                        if self.desktop.read().get('state') == 'waiting_for_exit':
                            raise ControlError('Desktop is ready; close Hermes to finish installation')
                        result = self.installer.install(self.root, 'auto')
                        if result['status'] == 'installed':
                            self._save_receipt(result)
                        desktop_state = self.desktop.read()
                        already_built = (self.desktop.available and result['status'] != 'installed' and desktop_state.get('state') == 'installed'
                                         and self.desktop.tree_hash(self.desktop.resources) == desktop_state.get('stage_hash'))
                        if self.desktop.available and not already_built:
                            try:
                                self.desktop.prepare()
                            except Exception:
                                if result['status'] == 'installed':
                                    self._rollback()
                                raise
                    else:
                        # Refuse drift before touching either Desktop or source files.
                        self._validate_rollback()
                        if self.desktop.available:
                            self.desktop.prepare_rollback()
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
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise ControlError('host-adapter operation refused: ' + str(exc), 422) from exc
        finally:
            self.mutex.release()
