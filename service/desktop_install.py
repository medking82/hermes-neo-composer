"""Windows Desktop staging and restart handoff for the fixed-root Neo installer.

Build using the installed Hermes scripts, never WSL, never overwrite a running
app. The service promotes verified resources after Hermes exits, then reopens it.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager

STATE = '.neo-desktop-install.json'
STAGE = '.neo-desktop-stage'
BACKUP = '.neo-desktop-resources-backup'


def bootstrap_token(cfg):
    """Share a random local credential only through the plugin's private file door."""
    if os.name != 'nt':
        return
    user_data = Path(os.environ.get('HERMES_DESKTOP_USER_DATA_DIR') or
                     str(Path(os.environ['APPDATA']) / ('Hermes' + os.environ.get('HERMES_DATA_DIR_SUFFIX', ''))))
    folder = user_data / 'plugin-files/data/neo-composer'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'control.json'
    if path.is_symlink():
        raise RuntimeError('refusing symlinked control credential')
    token = cfg.get('control_token') or cfg.get('token')
    if not token:
        if path.exists():
            token = json.loads(path.read_text(encoding='utf-8'))['token']
        else:
            token = secrets.token_urlsafe(48)
    if not isinstance(token, str) or len(token) < 16:
        raise RuntimeError('invalid local control credential')
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps({'token': token}), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)
    cfg['control_token'] = token


class DesktopInstall:
    def __init__(self, root):
        self.root = Path(root)
        self.app = self.root / 'apps/desktop'
        self.resources = self.app / 'release/win-unpacked/resources'
        self.stage = self.root / STAGE
        self.backup = self.root / BACKUP
        self.state_file = self.root / STATE

    @property
    def available(self):
        return os.name == 'nt' and (self.resources / 'app.asar').is_file()

    def read(self):
        return json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {}

    def write(self, state):
        temp = self.state_file.with_suffix('.new')
        temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temp.replace(self.state_file)

    @contextmanager
    def custody(self):
        """Use Hermes' own update/build locks, including concurrent updater exclusion."""
        if not self.available:
            yield
            return
        sys.path.insert(0, str(self.root))
        dependencies = None
        try:
            # The standalone service is stdlib-only; Hermes' shared locks use its
            # selected dependency environment. Resolve it through Hermes' PM API.
            from pm.environments import project_python
            dependencies = str(project_python(self.root).parents[1] / 'Lib/site-packages')
            if not Path(dependencies).is_dir():
                raise RuntimeError('Hermes selected Python environment is unavailable')
            sys.path.insert(0, dependencies)
            from hermes_cli.desktop_build_lock import DesktopBuildLock
            lock = DesktopBuildLock(self.root)
            if not lock.acquire():
                raise RuntimeError('Hermes update or desktop build is already running')
            try:
                yield
            finally:
                lock.release()
        finally:
            if dependencies and dependencies in sys.path:
                sys.path.remove(dependencies)
            sys.path.remove(str(self.root))

    def verify(self, resources):
        sys.path.insert(0, str(self.root))
        try:
            from hermes_cli.desktop_update_verify import _verify_packaged_entry
            _verify_packaged_entry(resources)
        finally:
            sys.path.remove(str(self.root))
        dist = resources / 'app.asar.unpacked/dist'
        # Verify local renderer assets as well as the archive's Electron entry.
        import re
        html = (dist / 'index.html').read_text(encoding='utf-8-sig')
        for name in re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']', html):
            if name.startswith(('http:', 'https:', 'data:', '#')):
                continue
            target = (dist / name.removeprefix('/')).resolve()
            if not target.is_relative_to(dist.resolve()) or not target.is_file():
                raise RuntimeError('missing packaged renderer asset: ' + name)

    def tree_hash(self, folder):
        digest = hashlib.sha256()
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('symlink in Desktop resources')
            if path.is_file():
                digest.update(path.relative_to(folder).as_posix().encode())
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
        return digest.hexdigest()

    def prepare(self):
        state = self.read()
        if state.get('state') == 'waiting_for_exit':
            raise RuntimeError('a verified Desktop build is already waiting for Hermes to close')
        if self.stage.exists():
            shutil.rmtree(self.stage)
        self.write({'state': 'building'})
        tools = Path(os.environ['LOCALAPPDATA']) / 'hermes/tools'
        def tool(name):
            # Hermes owns these installations; do not use arbitrary PATH tools.
            matches = sorted(tools.glob(name + '-*/' + name + '.exe'))
            if not matches:
                raise RuntimeError('Hermes managed ' + name + ' is unavailable')
            return matches[-1]
        pnpm, node = tool('pnpm'), tool('node')
        env = {**os.environ, 'CI': '1', 'PATH': str(node.parent) + os.pathsep + str(pnpm.parent) + os.pathsep + os.environ.get('PATH', '')}
        log = self.root / '.neo-desktop-build.log'
        try:
            with log.open('w', encoding='utf-8') as output:
                for args in ([str(pnpm), 'run', 'build'],
                             [str(pnpm), 'run', 'builder', '--dir', '--publish', 'never',
                              '-c.directories.output=' + str(self.stage)]):
                    process = subprocess.Popen(args, cwd=self.app, env=env, stdout=output, stderr=subprocess.STDOUT,
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    try:
                        code = process.wait(timeout=1800)
                    except subprocess.TimeoutExpired:
                        if os.name == 'nt':
                            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                                           stdout=output, stderr=subprocess.STDOUT, check=False,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        else:
                            process.kill()
                        process.wait()
                        raise
                    if code:
                        raise RuntimeError(f'Desktop build exited with code {code}')
            resources = self.stage / 'win-unpacked/resources'
            self.verify(resources)
            source_receipt = self.root / '.neo-host-control.json'
            source_files = json.loads(source_receipt.read_text(encoding='utf-8'))['installed'] if source_receipt.exists() else {}
            state = {'source_files': source_files, 'state': 'waiting_for_exit', 'operation': 'install',
                     'stage_hash': self.tree_hash(resources), 'previous_hash': self.tree_hash(self.resources)}
            self.write(state)
            return state
        except Exception as exc:
            self.write({'state': 'failed', 'error': str(exc), 'log': str(log)})
            shutil.rmtree(self.stage, ignore_errors=True)
            raise RuntimeError(f'Desktop build failed; see {log}: {exc}') from exc

    def prepare_rollback(self):
        state = self.read()
        if state.get('state') == 'waiting_for_exit' and state.get('operation') == 'install':
            shutil.rmtree(self.stage, ignore_errors=True)
            self.write({'state': 'cancelled'})
            return
        if state.get('state') != 'installed' or not self.backup.is_dir():
            raise RuntimeError('no installed Desktop backup to restore')
        if self.tree_hash(self.resources) != state['stage_hash']:
            raise RuntimeError('Desktop changed since install; refusing rollback')
        self.verify(self.backup)
        self.write({**state, 'state': 'waiting_for_exit', 'operation': 'rollback'})

    def running(self):
        result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq Hermes.exe', '/FO', 'CSV', '/NH'],
                                capture_output=True, text=True, check=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return any(row and row[0].lower() == 'hermes.exe' for row in csv.reader(result.stdout.splitlines()))

    def promote(self):
        state = self.read()
        if state.get('state') != 'waiting_for_exit' or self.running():
            return False
        rollback = state['operation'] == 'rollback'
        if not rollback:
            for relative, expected in state.get('source_files', {}).items():
                path = self.root / relative
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise RuntimeError('Hermes source changed after staging; run Check before reinstalling')
        source = self.backup if rollback else self.stage / 'win-unpacked/resources'
        wanted = state['previous_hash'] if rollback else state['stage_hash']
        current = state['stage_hash'] if rollback else state['previous_hash']
        if self.tree_hash(source) != wanted or self.tree_hash(self.resources) != current:
            raise RuntimeError('Desktop resources changed after staging; refusing promotion')
        self.verify(source)
        saved = self.root / '.neo-desktop-swap-old'
        if saved.exists():
            raise RuntimeError('incomplete Desktop swap requires recovery')
        self.resources.rename(saved)
        try:
            source.rename(self.resources)
            self.verify(self.resources)
        except Exception:
            if self.resources.exists():
                self.resources.rename(source)
            saved.rename(self.resources)
            raise
        if rollback:
            shutil.rmtree(saved)
        else:
            if self.backup.exists():
                shutil.rmtree(self.backup)
            saved.rename(self.backup)
        self.write({**state, 'state': 'rolled_back' if rollback else 'installed'})
        shutil.rmtree(self.stage, ignore_errors=True)
        subprocess.Popen([str(self.resources.parent / 'Hermes.exe')], cwd=self.root,
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        return True

    def monitor(self, mutex):
        if not self.available:
            return
        def work():
            while True:
                threading.Event().wait(3)
                if not mutex.acquire(blocking=False):
                    continue
                try:
                    if self.read().get('state') == 'waiting_for_exit' and not self.running():
                        with self.custody():
                            self.promote()
                except Exception as exc:
                    state = self.read()
                    self.write({**state, 'state': 'promotion_failed', 'error': str(exc)})
                finally:
                    mutex.release()
        threading.Thread(target=work, name='neo-desktop-handoff', daemon=True).start()
