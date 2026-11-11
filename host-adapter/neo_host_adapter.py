#!/usr/bin/env python3
"""Install/verify/rollback the Neo strict-steer host adapter (contract protocol 1).

Compatibility is by STRUCTURE, never by Hermes release number: every required file,
symbol and anchor is checked first; if anything is missing or ambiguous nothing is
written. Edits are anchor insertions wrapped in `neo-composer:strict-steer:v1` markers,
so reinstall is a no-op and a half-applied file is refused rather than guessed at.

  neo_host_adapter.py check     --root HERMES_ROOT [--frontend auto|skip|require]
  neo_host_adapter.py install   --root HERMES_ROOT [--frontend ...]
  neo_host_adapter.py rollback  --root HERMES_ROOT [--id BACKUP_ID]
  neo_host_adapter.py uninstall --root HERMES_ROOT
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

CONTRACT = 1
MARK = 'neo-composer:strict-steer:v1'
HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / 'payload'
BACKUPS = '.neo-backups'
MANIFEST = '.neo-composer-host-adapter.json'


class Refuse(Exception):
    """Structure is incompatible or ambiguous; nothing was modified."""


@dataclass
class Edit:
    file: str
    anchor: str            # must occur exactly once
    text: str              # inserted text (contains MARK)
    where: str = 'after'   # 'after' | 'before'
    frontend: bool = False


@dataclass
class Plan:
    copies: dict[str, str] = field(default_factory=dict)      # root-relative dest -> payload file
    copies_frontend: dict[str, str] = field(default_factory=dict)
    edits: list[Edit] = field(default_factory=list)
    requires: list[tuple[str, str]] = field(default_factory=list)  # (file, regex)


def _block(name: str) -> str:
    return (PAYLOAD / name).read_text(encoding='utf-8')


def build_plan() -> Plan:
    p = Plan()
    p.copies['gateway/neo_composer_adapter.py'] = 'neo_composer_adapter.py'
    p.copies_frontend['apps/desktop/src/app/chat/composer/neo-strict-steer.ts'] = 'neo-strict-steer.ts'
    # Symbols the adapter imports/uses. Missing => refuse; we never shim them.
    p.requires += [
        ('gateway/session_busy_controls.py', r'^def authorize\b'),
        ('gateway/session_llm_oneshot.py', r'^class DeferredReply\b'),
        ('tui_gateway/contracts/registry.py', r'^def canonical_method\b'),
        ('gateway/session_images.py', r'^def _stage\b'),
        ('agent/prompt_builder.py', r'^def steer_user_row\b'),
        ('gateway/session_authority.py', r'def steer_agent\b'),
        ('gateway/session_authority.py', r'def check_approval_generation\b'),
        ('agent/turn_iteration_prep.py', r'^def prepare_iteration\b'),
        ('agent/turn_iteration_prep.py', r'current_turn_user_idx'),
        ('hermes_state_runtime.py', r'class RuntimeStoreError\b'),
    ]
    p.edits += [
        Edit('gateway/session_controls.py', '        handlers.update(busy_handlers(self))\n',
             f'        from gateway.neo_composer_adapter import handlers as neo_composer_handlers  # {MARK}\n'
             f'        handlers.update(neo_composer_handlers(self))  # {MARK}\n'),
        Edit('agent/turn_iteration_prep.py', '    # One-shot run-budget wrap-up notice at 80% of agent.run_budget_seconds',
             f'    # {MARK} begin\n'
             "    # Optional Neo contract: insert only a matching, still-pending strict steer.\n"
             "    if getattr(agent, '_neo_strict_pending', None) is not None:\n"
             '        from gateway.neo_composer_adapter import deliver\n'
             '        deliver(agent, messages, current_turn_user_idx=current_turn_user_idx)\n'
             f'    # {MARK} end\n\n', where='before'),
        Edit('apps/desktop/src/sdk/composer.ts', "import { freshDraftScope, takeSessionDraft } from '@/store/composer'\n",
             f"import {{ requestNeoStrictSteer }} from '@/app/chat/composer/neo-strict-steer' // {MARK}\n",
             where='before', frontend=True),
        Edit('apps/desktop/src/sdk/composer.ts', 'export const composerHost = {\n',
             f'  steerStrict: (sessionId: string) => requestNeoStrictSteer(resolveComposerAddress(sessionId).target, sessionId), // {MARK}\n',
             frontend=True),
        Edit('apps/desktop/src/app/chat/composer/hooks/use-composer-submit.ts',
             "import { usePaneVisible } from '@/components/pane-shell/pane-visibility'\n",
             f"import {{ captureSubmissionDestination }} from '@/app/session/hooks/use-prompt-actions/submission-destination' // {MARK}\n"
             f"import {{ $gateway }} from '@/store/gateway' // {MARK}\n", frontend=True),
        Edit('apps/desktop/src/app/chat/composer/hooks/use-composer-submit.ts',
             "import { onComposerSubmitRequest } from '../focus'\n",
             f"import {{ onNeoStrictSteer, performNeoStrictSteer, type NeoSteerReceipt }} from '../neo-strict-steer' // {MARK}\n",
             frontend=True),
        Edit('apps/desktop/src/app/chat/composer/hooks/use-composer-submit.ts', '  // Shared send primitive:',
             _block('use-composer-submit.block.ts'), where='before', frontend=True),
    ]
    return p


def _read(root: Path, rel: str) -> str:
    f = root / rel
    if not f.is_file():
        raise Refuse(f'missing required file: {rel}')
    return f.read_bytes().decode('utf-8')


def _applied(text: str, e: Edit) -> bool:
    return e.text in text


def _apply(text: str, e: Edit) -> str:
    if text.count(e.anchor) != 1:
        raise Refuse(f'{e.file}: anchor found {text.count(e.anchor)}x (need exactly 1): {e.anchor.strip()[:60]!r}')
    i = text.index(e.anchor)
    i = i + len(e.anchor) if e.where == 'after' else i
    return text[:i] + e.text + text[i:]


def _use_frontend(root: Path, mode: str) -> bool:
    present = (root / 'apps/desktop/src').is_dir()
    if mode == 'skip':
        return False
    if mode == 'require' and not present:
        raise Refuse('--frontend require: apps/desktop/src not present')
    return present


def _known_paths() -> set[str]:
    plan = build_plan()
    return set(plan.copies) | set(plan.copies_frontend) | {edit.file for edit in plan.edits}


def _safe(root: Path, rel: str) -> Path:
    if Path(rel).is_absolute() or '..' in Path(rel).parts:
        raise Refuse(f'unsafe adapter path: {rel}')
    path = root / rel
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise Refuse(f'symlink/junction in adapter path: {item}')
        if item == root:
            break
    return path


def _hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _owned(root: Path) -> dict:
    for rel in [*_known_paths(), MANIFEST, BACKUPS]:
        _safe(root, rel)
    path = root / MANIFEST
    if not path.exists():
        return {}
    manifest = json.loads(path.read_text(encoding='utf-8'))
    installed = manifest.get('installed')
    if not isinstance(installed, dict) or not set(installed).issubset(_known_paths()):
        raise Refuse('ownership manifest missing installed digests; inspect older installation manually')
    reverted = []
    for rel, expected in installed.items():
        if _hash(_safe(root, rel)) != expected:
            if not _reverted_by_host_update(root, rel):
                raise Refuse(f'{rel}: source changed since install (ownership digest mismatch)')
            reverted.append(rel)
    # A Hermes update (`hermes update --keep-stash`, the desktop updater's mode) stashes our edits
    # and checks out clean upstream files. Those files are provably upstream (byte-equal to git
    # HEAD, no marker), so ownership of them lapses and the plan simply re-applies on new anchors.
    return {rel: digest for rel, digest in installed.items() if rel not in reverted}


def _git_head_blob(root: Path, rel: str):
    import subprocess
    try:
        r = subprocess.run(['git', '-C', str(root), 'show', f'HEAD:{rel}'], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _reverted_by_host_update(root: Path, rel: str) -> bool:
    """True when a host update put the pristine upstream file back: it is tracked, byte-equal to
    git HEAD and carries no adapter marker. Anything else (hand edits, partial state) stays refused."""
    path = root / rel
    if not path.is_file():
        return False
    data = path.read_bytes()
    if MARK.encode() in data:
        return False
    head = _git_head_blob(root, rel)
    return head is not None and head == data


def plan_changes(root: Path, frontend: str = 'auto') -> dict[str, str]:
    """Compute new contents for every touched file without writing. Raises Refuse."""
    plan = build_plan()
    owned = _owned(root)
    use_fe = _use_frontend(root, frontend)
    for rel, rx in plan.requires:
        if not re.search(rx, _read(root, rel), re.M):
            raise Refuse(f'{rel}: required structure not found: /{rx}/')
    out: dict[str, str] = {}
    copies = dict(plan.copies, **(plan.copies_frontend if use_fe else {}))
    for dest, src in copies.items():
        want = (PAYLOAD / src).read_text(encoding='utf-8')
        cur = (root / dest).read_text(encoding='utf-8') if (root / dest).exists() else None
        if cur is not None and dest not in owned:
            raise Refuse(f'{dest}: unmanaged destination conflict; ownership not established')
        if cur != want:
            out[dest] = want
    by_file: dict[str, list[Edit]] = {}
    for e in plan.edits:
        if e.frontend and not use_fe:
            continue
        by_file.setdefault(e.file, []).append(e)
    for rel, edits in by_file.items():
        text = _read(root, rel)
        done = [_applied(text, e) for e in edits]
        if any(done) and not all(done):
            raise Refuse(f'{rel}: partially applied adapter markers; refusing (run uninstall/rollback first)')
        if all(done):
            if text.count(MARK) < len(edits):
                raise Refuse(f'{rel}: marker count mismatch')
            continue
        if MARK in text:
            raise Refuse(f'{rel}: foreign {MARK} content present; refusing')
        for e in edits:
            text = _apply(text, e)
        if rel.endswith('.py'):
            try:
                ast.parse(text)
            except SyntaxError as exc:
                raise Refuse(f'{rel}: patched file would not parse: {exc}') from exc
        out[rel] = text
    if 'gateway/neo_composer_adapter.py' in out:
        ast.parse(out['gateway/neo_composer_adapter.py'])
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def _transaction(root: Path, changes: dict, status: str, frontend=None) -> dict:
    owned = _owned(root)
    if not changes:
        return {'status': 'unchanged', 'contract': CONTRACT}
    bid = time.strftime('%Y%m%d-%H%M%S') + f'-{time.monotonic_ns() % 10**6:06d}'
    bdir = _safe(root, BACKUPS + '/' + bid)
    bdir.mkdir(parents=True, exist_ok=False)
    previous = (root / MANIFEST).read_bytes() if (root / MANIFEST).exists() else None
    if previous is not None:
        (bdir / 'previous-manifest.json').write_bytes(previous)
    installed = {**owned}
    manifest = {'contract': CONTRACT, 'id': bid, 'files': {}, 'originals': {},
                'previous_manifest': previous is not None}
    try:
        for rel, content in changes.items():
            f = _safe(root, rel)
            if f.exists():
                (bdir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, bdir / rel)
                manifest['files'][rel] = 'modified'
                manifest['originals'][rel] = _hash(bdir / rel)
            else:
                manifest['files'][rel] = 'created'
            installed[rel] = hashlib.sha256(content.encode('utf-8')).hexdigest() if content is not None else None
        manifest['installed'] = installed
        (bdir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        for rel, content in changes.items():
            if content is None:
                (root / rel).unlink(missing_ok=True)
            else:
                _write(root / rel, content)
        if status == 'uninstalled':
            (root / MANIFEST).unlink(missing_ok=True)
        else:
            (root / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        if frontend is not None and plan_changes(root, frontend):
            raise Refuse('post-install verification failed (not idempotent)')
    except BaseException:
        _restore(root, bdir, manifest)
        if previous is None:
            (root / MANIFEST).unlink(missing_ok=True)
        else:
            (root / MANIFEST).write_bytes(previous)
        # Failed transactions are not offered as rollbacks.
        shutil.rmtree(bdir)
        raise
    return {'status': status, 'contract': CONTRACT, 'backup': bid, 'files': sorted(changes)}


def install(root: Path, frontend: str = 'auto') -> dict:
    return _transaction(root, plan_changes(root, frontend), 'installed', frontend)


def _restore(root: Path, bdir: Path, manifest: dict) -> None:
    for rel, kind in manifest['files'].items():
        if kind == 'created':
            (root / rel).unlink(missing_ok=True)
        elif (bdir / rel).exists():
            shutil.copy2(bdir / rel, root / rel)


def rollback(root: Path, backup_id: str | None = None) -> dict:
    base = _safe(root, BACKUPS)
    ids = sorted(d.name for d in base.iterdir()
                 if re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', d.name)
                 and _safe(root, BACKUPS + '/' + d.name + '/manifest.json').is_file()) if base.is_dir() else []
    if not ids:
        raise Refuse('no backups')
    bid = backup_id or ids[-1]
    if bid not in ids:
        raise Refuse(f'unknown backup {bid}')
    bdir = base / bid
    manifest = json.loads((bdir / 'manifest.json').read_text(encoding='utf-8'))
    files = manifest.get('files', {})
    if not files or not set(files).issubset(_known_paths()) or not isinstance(manifest.get('installed'), dict):
        raise Refuse('backup ownership digests missing or invalid')
    for rel, kind in files.items():
        if kind not in {'modified', 'created'} or _hash(_safe(root, rel)) != manifest['installed'].get(rel):
            raise Refuse(f'{rel}: source changed since install; refusing rollback')
        if kind == 'modified' and _hash(_safe(root, BACKUPS + '/' + bid + '/' + rel)) != manifest.get('originals', {}).get(rel):
            raise Refuse(f'{rel}: backup digest mismatch')
    previous = _safe(root, BACKUPS + '/' + bid + '/previous-manifest.json')
    if manifest.get('previous_manifest') and not previous.is_file():
        raise Refuse('previous ownership manifest missing')
    _restore(root, bdir, manifest)
    if manifest.get('previous_manifest'):
        (root / MANIFEST).write_bytes(previous.read_bytes())
    else:
        (root / MANIFEST).unlink(missing_ok=True)
    return {'status': 'rolled_back', 'backup': bid, 'files': sorted(files)}


def uninstall(root: Path) -> dict:
    """Plan removal before writing; copied modules always need ownership digests."""
    plan, owned = build_plan(), _owned(root)
    changes = {}
    for dest in [*plan.copies, *plan.copies_frontend]:
        if (root / dest).exists():
            if dest not in owned:
                raise Refuse(f'{dest}: unmanaged destination conflict; refusing delete')
            changes[dest] = None
    for edit in plan.edits:
        file = root / edit.file
        if not file.is_file():
            continue
        text = changes.get(edit.file, file.read_bytes().decode('utf-8'))
        if edit.text in text:
            changes[edit.file] = text.replace(edit.text, '', 1)
        elif MARK in text:
            raise Refuse(f'{edit.file}: modified adapter markers; refusing uninstall')
    for rel, content in changes.items():
        if rel.endswith('.py') and content is not None:
            ast.parse(content)
    return _transaction(root, changes, 'uninstalled')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['check', 'install', 'rollback', 'uninstall'])
    ap.add_argument('--root', required=True)
    ap.add_argument('--frontend', choices=['auto', 'skip', 'require'], default='auto')
    ap.add_argument('--id')
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        if a.cmd == 'check':
            changes = plan_changes(root, a.frontend)
            res = {'status': 'compatible', 'contract': CONTRACT, 'pending': sorted(changes)}
        elif a.cmd == 'install':
            res = install(root, a.frontend)
        elif a.cmd == 'rollback':
            res = rollback(root, a.id)
        else:
            res = uninstall(root)
    except Refuse as exc:
        print(json.dumps({'status': 'refused', 'reason': str(exc)}))
        return 2
    print(json.dumps(res))
    return 0


if __name__ == '__main__':
    sys.exit(main())
