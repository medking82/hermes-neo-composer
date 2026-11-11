"""Control-plane integration tests; run with WSL Python only."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import tempfile
from pathlib import Path

import neo_suggest as ns


def seed_host(root):
    files = {
        'gateway/session_busy_controls.py': 'def authorize(*a): pass\n',
        'gateway/session_llm_oneshot.py': 'class DeferredReply: pass\n',
        'tui_gateway/contracts/registry.py': 'def canonical_method(*a, **k): pass\n',
        'gateway/session_images.py': 'def _stage(*a): pass\n',
        'agent/prompt_builder.py': 'def steer_user_row(*a): pass\n',
        'gateway/session_authority.py': 'class A:\n    def steer_agent(self): pass\n    def check_approval_generation(self): pass\n',
        'hermes_state_runtime.py': 'class RuntimeStoreError(Exception): pass\n',
        'agent/turn_iteration_prep.py': 'def prepare_iteration(agent, messages, current_turn_user_idx=None):\n    # One-shot run-budget wrap-up notice at 80% of agent.run_budget_seconds\n    pass\n',
        'gateway/session_controls.py': 'class C:\n    def build(self, handlers):\n        handlers.update(busy_handlers(self))\n',
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return {rel: (root / rel).read_bytes() for rel in files}


class ControlHttpTests(unittest.TestCase):
    def start(self, **settings):
        cfg = ns.load_config({})
        cfg.update(settings)
        server = ThreadingHTTPServer(('127.0.0.1', 0), ns.make_handler(cfg, ns.Predictor(cfg)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def request(self, base, path, body=None, headers=None, method=None):
        request = urllib.request.Request(base + path,
            None if body is None else json.dumps(body).encode(),
            {'Content-Type': 'application/json', **(headers or {})}, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, dict(response.headers), json.loads(response.read() or b'null')

    def test_control_requires_configured_token_even_when_suggestions_are_public(self):
        base = self.start()
        code, _, body = self.request(base, '/v1/host-adapter/status')
        self.assertEqual(code, 503)
        self.assertIn('token', body['error'])
        self.assertEqual(self.request(base, '/healthz')[0], 200)

    def test_authenticated_click_installs_known_root_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = seed_host(root)
            base = self.start(token='service-secret', hermes_root=str(root))
            auth = {'Authorization': 'Bearer service-secret', 'Origin': 'null'}
            code, _, state = self.request(base, '/v1/host-adapter/check', headers=auth)
            self.assertEqual(code, 200)
            self.assertTrue(state['can_install'])
            self.assertFalse((root / '.neo-composer-host-adapter.json').exists())
            code, _, state = self.request(base, '/v1/host-adapter/install', {'confirm': True}, auth)
            self.assertEqual(code, 200)
            self.assertTrue(state['backend']['source_applied'])
            self.assertTrue(state['backend']['restart_required'])
            self.assertFalse(state['backend']['runtime_verified'])
            self.assertFalse(state['frontend']['automatic_rebuild'])
            self.assertEqual(state['frontend']['state'], 'source_missing')
            self.assertTrue(state['rollback_available'])
            self.assertEqual(self.request(base, '/v1/host-adapter/install', {'confirm': True}, auth)[0], 200)
            code, _, state = self.request(base, '/v1/host-adapter/rollback', {'confirm': True}, auth)
            self.assertEqual((code, state['action']), (200, 'rolled_back'))
            self.assertFalse((root / 'gateway/neo_composer_adapter.py').exists())
            self.assertEqual({rel: (root / rel).read_bytes() for rel in before}, before)

    def test_reapply_after_hermes_update_restores_consented_install(self):
        import subprocess
        from host_control import HostControl

        def git(root, *args):
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t',
                            '-c', 'core.autocrlf=false', *args], check=True, capture_output=True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_host(root)
            git(root, 'init', '-q')
            git(root, 'add', '-A')
            git(root, 'commit', '-qm', 'upstream')
            cfg = ns.load_config({})
            cfg.update(hermes_root=str(root))
            control = HostControl(cfg)
            self.assertIsNone(control.reapply_after_update())  # never installed: no consent, no action
            control.run('install')
            self.assertIsNone(control.reapply_after_update())  # nothing pending
            git(root, 'stash', 'push', '-q')  # what `hermes update --keep-stash` does
            self.assertNotIn('neo-composer', (root / 'gateway/session_controls.py').read_text())
            state = control.reapply_after_update()
            assert state is not None
            self.assertEqual(state['action'], 'installed')
            self.assertIn('neo-composer', (root / 'gateway/session_controls.py').read_text())

    def test_origin_token_host_and_input_gates_preserve_service_auth(self):
        base = self.start(token='prediction', control_token='admin', cors=['*'], control_origins=['*'])
        auth = {'Authorization': 'Bearer admin', 'Origin': 'null'}
        for headers in ({}, {'Authorization': 'Bearer prediction'},
                        {'Authorization': 'Bearer wrong'}):
            self.assertEqual(self.request(base, '/v1/host-adapter/check', headers=headers)[0], 401)
        for origin in ('https://evil.example', 'http://127.0.0.1.evil:5174', 'http://localhost:9999'):
            code, headers, _ = self.request(base, '/v1/host-adapter/install', {'confirm': True},
                                           {**auth, 'Origin': origin})
            self.assertEqual(code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request(base, '/v1/host-adapter/status', headers={**auth, 'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request(base, '/v1/host-adapter/install', headers=auth)[0], 405)
        self.assertEqual(self.request(base, '/v1/host-adapter/check', {}, auth)[0], 405)
        self.assertEqual(self.request(base, '/v1/host-adapter/shell', {'confirm': True}, auth)[0], 404)
        for body in ({}, {'confirm': False}, {'confirm': 1}, {'confirm': True, 'root': '/tmp/evil'},
                     {'confirm': True, 'command': 'run'}, {'confirm': True, 'id': '../evil'}):
            self.assertEqual(self.request(base, '/v1/host-adapter/install', body, auth)[0], 400)
        self.assertEqual(self.request(base, '/v1/host-adapter/install', {'confirm': True},
                                     {**auth, 'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request(base, '/v1/suggest', {}, {'Authorization': 'Bearer admin'})[0], 401)
        # Suggestion auth remains independent; the prediction token is still accepted there.
        self.assertEqual(self.request(base, '/v1/suggest', {}, {'Authorization': 'Bearer prediction'})[0], 200)
        code, headers, _ = self.request(base, '/v1/host-adapter/install', headers={'Origin': 'null'}, method='OPTIONS')
        self.assertEqual((code, headers.get('Access-Control-Allow-Origin')), (204, 'null'))
        self.assertEqual(self.request(base, '/v1/host-adapter/install', headers={'Origin': 'https://evil.example'}, method='OPTIONS')[0], 403)

    def test_restart_has_same_auth_confirmation_and_method_gates(self):
        base = self.start(token='secret')
        route = '/v1/host-adapter/restart'
        auth = {'Authorization': 'Bearer secret'}
        self.assertEqual(self.request(base, route, {'confirm': True})[0], 401)
        self.assertEqual(self.request(base, route, headers=auth)[0], 405)
        self.assertEqual(self.request(base, route, {}, auth)[0], 400)
        self.assertEqual(self.request(base, route, {'confirm': True, 'pid': 1}, auth)[0], 400)
        self.assertEqual(self.request(base, route, {'confirm': True},
                                     {**auth, 'Origin': 'https://evil.example'})[0], 403)
        from unittest.mock import patch
        import sys
        with patch.object(sys.modules['_neo_host_control'].HostControl, 'run',
                          return_value={'action': 'restart_scheduled'}) as run:
            self.assertEqual(self.request(base, route, {'confirm': True}, auth)[2]['action'], 'restart_scheduled')
            run.assert_called_once_with('restart')

    def test_nonloopback_bind_cannot_mutate_even_with_control_token(self):
        base = self.start(token='secret', host='0.0.0.0')
        self.assertEqual(self.request(base, '/v1/host-adapter/install', {'confirm': True},
                                     {'Authorization': 'Bearer secret'})[0], 403)

    def test_frontend_source_install_reports_rebuild_required_and_rollback_drift_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_host(root)
            base = self.start(token='secret', hermes_root=str(root))
            import sys
            installer = sys.modules['_neo_local_installer']
            by_file = {}
            for edit in installer.build_plan().edits:
                if edit.frontend:
                    by_file.setdefault(edit.file, []).append(edit.anchor)
            for relative, anchors in by_file.items():
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('\n'.join(anchors))
            auth = {'Authorization': 'Bearer secret'}
            code, _, state = self.request(base, '/v1/host-adapter/install', {'confirm': True}, auth)
            self.assertEqual(code, 200)
            self.assertTrue(state['frontend']['source_applied'])
            self.assertTrue(state['frontend']['rebuild_required'])
            self.assertFalse(state['frontend']['automatic_rebuild'])
            target = root / 'gateway/neo_composer_adapter.py'
            target.write_text('# upstream change\n')
            self.assertEqual(self.request(base, '/v1/host-adapter/rollback', {'confirm': True}, auth)[0], 409)
            self.assertEqual(target.read_text(), '# upstream change\n')

    def test_incompatible_source_and_symlink_refuse_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_host(root)
            (root / 'agent/prompt_builder.py').write_text('def unrelated(): pass\n')
            base = self.start(token='secret', hermes_root=str(root))
            auth = {'Authorization': 'Bearer secret'}
            self.assertEqual(self.request(base, '/v1/host-adapter/install', {'confirm': True}, auth)[0], 422)
            self.assertFalse((root / '.neo-backups').exists())
            seed_host(root)
            target = root / 'gateway/neo_composer_adapter.py'
            target.symlink_to(root / 'agent/prompt_builder.py')
            self.assertEqual(self.request(base, '/v1/host-adapter/install', {'confirm': True}, auth)[0], 409)
            self.assertFalse((root / '.neo-backups').exists())


if __name__ == '__main__':
    unittest.main()
