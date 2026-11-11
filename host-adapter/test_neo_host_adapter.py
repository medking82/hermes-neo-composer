import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import neo_host_adapter as h  # noqa: E402

SRC = os.environ.get('NEO_HERMES_TAR') or os.environ.get('NEO_HERMES_SRC')  # tar of Hermes HEAD, or a git checkout


def _fake_host(root: Path) -> Path:
    files = {
        'gateway/session_busy_controls.py': 'def authorize(*a):\n    pass\n',
        'gateway/session_llm_oneshot.py': 'class DeferredReply:\n    pass\n',
        'tui_gateway/contracts/registry.py': 'def canonical_method(*a, **k):\n    pass\n',
        'gateway/session_images.py': 'def _stage(*a): pass\n',
        'agent/prompt_builder.py': 'def steer_user_row(*a): pass\n',
        'gateway/session_authority.py': 'class A:\n    def steer_agent(self): pass\n    def check_approval_generation(self): pass\n',
        'hermes_state_runtime.py': 'class RuntimeStoreError(Exception):\n    pass\n',
        'agent/turn_iteration_prep.py': (
            'def prepare_iteration(agent, messages, current_turn_user_idx=None):\n'
            '    x = 1\n\n'
            '    # One-shot run-budget wrap-up notice at 80% of agent.run_budget_seconds, appended\n'
            '    return x\n'),
        'gateway/session_controls.py': (
            'class C:\n    def build(self, handlers):\n'
            '        from gateway.session_busy_controls import handlers as busy_handlers\n'
            '        handlers.update(busy_handlers(self))\n'
            '        return handlers\n'),
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


@pytest.fixture
def host(tmp_path):
    return _fake_host(tmp_path)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and h.BACKUPS not in p.parts and p.name != h.MANIFEST}


def test_check_does_not_write_and_install_is_idempotent(host):
    before = snapshot(host)
    assert h.plan_changes(host)
    assert snapshot(host) == before
    r = h.install(host)
    assert r['status'] == 'installed'
    assert 'gateway/neo_composer_adapter.py' in r['files']
    for rel in r['files']:
        if rel.endswith('.py'):
            ast.parse((host / rel).read_text())
    after = snapshot(host)
    assert h.install(host)['status'] == 'unchanged'
    assert snapshot(host) == after


def test_rollback_restores_exact_bytes(host):
    before = snapshot(host)
    h.install(host)
    h.rollback(host)
    assert snapshot(host) == before


def test_uninstall_restores_originals(host):
    before = snapshot(host)
    h.install(host)
    h.uninstall(host)
    assert snapshot(host) == before


def test_refuses_ambiguous_anchor_without_writing(host):
    f = host / 'gateway/session_controls.py'
    f.write_text(f.read_text() + '        handlers.update(busy_handlers(self))\n')
    before = snapshot(host)
    with pytest.raises(h.Refuse, match='anchor found 2x'):
        h.install(host)
    assert snapshot(host) == before
    assert not (host / h.BACKUPS).exists()


def test_refuses_missing_structure(host):
    (host / 'gateway/session_images.py').write_text('def other(): pass\n')
    with pytest.raises(h.Refuse, match='required structure'):
        h.install(host)


def test_refuses_partial_application(host):
    h.install(host)
    f = host / 'agent/turn_iteration_prep.py'
    f.write_text(f.read_text().replace(h.MARK + ' end', 'tampered'))
    with pytest.raises(h.Refuse):
        h.install(host)


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def test_reinstalls_after_host_update_stashed_edits(host):
    _git(host, 'init', '-q')
    _git(host, '-c', 'core.autocrlf=false', 'add', '-A')
    _git(host, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'upstream')
    h.install(host)
    # `hermes update --keep-stash`: tracked edits stashed, untracked adapter files left in place.
    _git(host, '-c', 'user.name=t', '-c', 'user.email=t@t', 'stash', 'push', '-q')
    assert h.MARK not in (host / 'gateway/session_controls.py').read_text()
    assert sorted(h.plan_changes(host)) == ['agent/turn_iteration_prep.py', 'gateway/session_controls.py']
    assert h.install(host)['status'] == 'installed'
    assert h.MARK in (host / 'gateway/session_controls.py').read_text()
    assert h.install(host)['status'] == 'unchanged'


def test_hand_edit_after_install_still_refused(host):
    _git(host, 'init', '-q')
    _git(host, '-c', 'core.autocrlf=false', 'add', '-A')
    _git(host, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'upstream')
    h.install(host)
    _git(host, '-c', 'user.name=t', '-c', 'user.email=t@t', 'stash', 'push', '-q')
    f = host / 'gateway/session_controls.py'
    f.write_text(f.read_text() + '# local edit\n')
    with pytest.raises(h.Refuse, match='digest mismatch'):
        h.plan_changes(host)


def test_failed_install_rolls_back(host, monkeypatch):
    before = snapshot(host)
    real = h._write
    calls = []

    def boom(path, text):
        calls.append(path)
        if len(calls) == 2:
            raise OSError('disk')
        real(path, text)

    monkeypatch.setattr(h, '_write', boom)
    with pytest.raises(OSError):
        h.install(host)
    assert snapshot(host) == before


def test_arbitrary_hermes_version_does_not_gate_structural_compatibility(tmp_path):
    _fake_host(tmp_path)
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "999.123.456+future"\n')
    (tmp_path / 'package.json').write_text('{"version":"0.0.0-unknown-fork"}')
    assert h.install(tmp_path)['status'] == 'installed'


def test_unmanaged_copy_conflict_refuses_without_touching_host(tmp_path):
    _fake_host(tmp_path)
    target = tmp_path / 'gateway/neo_composer_adapter.py'
    target.write_text('# unrelated upstream module\n')
    with pytest.raises(h.Refuse, match='unmanaged|ownership|conflict'):
        h.install(tmp_path)
    assert target.read_text() == '# unrelated upstream module\n'
    assert not (tmp_path / h.BACKUPS).exists()


def test_uninstall_preserves_unmanaged_module(tmp_path):
    _fake_host(tmp_path)
    target = tmp_path / 'gateway/neo_composer_adapter.py'
    target.write_text('# upstream implementation\n')
    with pytest.raises(h.Refuse, match='unmanaged|ownership|conflict'):
        h.uninstall(tmp_path)
    assert target.read_text() == '# upstream implementation\n'


def test_upgrade_and_rollback_refuse_postinstall_edits(tmp_path):
    _fake_host(tmp_path)
    result = h.install(tmp_path)
    target = tmp_path / 'gateway/neo_composer_adapter.py'
    target.write_text('# edited after installation\n')
    for action in (lambda: h.install(tmp_path), lambda: h.uninstall(tmp_path),
                   lambda: h.rollback(tmp_path, result['backup'])):
        with pytest.raises(h.Refuse, match='changed|modified|digest|ownership'):
            action()
        assert target.read_text() == '# edited after installation\n'


def test_manifest_failure_restores_entire_transaction(tmp_path, monkeypatch):
    _fake_host(tmp_path)
    before = snapshot(tmp_path)
    original = Path.write_text
    def fail_manifest(path, *args, **kwargs):
        if path == tmp_path / h.MANIFEST:
            raise OSError('simulated manifest write failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', fail_manifest)
    with pytest.raises(OSError, match='simulated manifest'):
        h.install(tmp_path)
    assert {rel: (tmp_path / rel).read_bytes() for rel in before} == before
    assert not (tmp_path / 'gateway/neo_composer_adapter.py').exists()
    assert not (tmp_path / h.MANIFEST).exists()


@pytest.mark.skipif(not SRC, reason='set NEO_HERMES_SRC to a Hermes checkout')
def test_real_hermes_tree(tmp_path):
    tar = tmp_path / 'h.tar'
    if SRC.endswith('.tar'):
        tar = Path(SRC)
    else:
        subprocess.run(['git', '-C', SRC, 'archive', '-o', str(tar), 'HEAD'], check=True)
    root = tmp_path / 'root'
    root.mkdir()
    subprocess.run(['tar', '-xf', str(tar), '-C', str(root), '--wildcards', 'gateway', 'agent', 'tui_gateway',
                    'hermes_state_runtime.py', 'apps/desktop/src'], check=True)
    pristine = snapshot(root)
    assert h.install(root, 'require')['status'] == 'installed'
    assert h.install(root, 'require')['status'] == 'unchanged'
    for rel in ('gateway/session_controls.py', 'agent/turn_iteration_prep.py', 'gateway/neo_composer_adapter.py'):
        ast.parse((root / rel).read_text())
    assert 'steerStrict' in (root / 'apps/desktop/src/sdk/composer.ts').read_text()
    h.rollback(root)
    assert snapshot(root) == pristine
