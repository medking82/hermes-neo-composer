"""Resource handoff and installer failure regression tests (run in WSL)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_install import DesktopInstall, bootstrap_token
from host_control import HostControl, ControlError
from test_host_control import seed_host


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.d = DesktopInstall(self.root)
        self.d.resources.mkdir(parents=True)
        (self.d.resources / 'app.asar').write_text('old')
        self.staged = self.d.stage / 'win-unpacked/resources'
        self.staged.mkdir(parents=True)
        (self.staged / 'app.asar').write_text('new')
        self.d.write({'state': 'waiting_for_exit', 'operation': 'install',
                      'stage_hash': self.d.tree_hash(self.staged),
                      'previous_hash': self.d.tree_hash(self.d.resources)})

    def test_wait_for_exit_then_promote_and_restore_backup(self):
        with patch.object(self.d, 'running', return_value=True):
            self.assertFalse(self.d.promote())
        self.assertEqual((self.d.resources / 'app.asar').read_text(), 'old')
        with patch.object(self.d, 'running', return_value=False), patch.object(self.d, 'verify'), \
                patch('desktop_install.subprocess.Popen') as launch:
            self.assertTrue(self.d.promote())
            self.assertEqual((self.d.resources / 'app.asar').read_text(), 'new')
            self.assertEqual((self.d.backup / 'app.asar').read_text(), 'old')
            self.assertEqual(self.d.read()['state'], 'installed')
            launch.assert_called_once()
            self.d.prepare_rollback()
            self.assertTrue(self.d.promote())
        self.assertEqual((self.d.resources / 'app.asar').read_text(), 'old')
        self.assertEqual(self.d.read()['state'], 'rolled_back')

    def test_tampered_stage_or_updated_live_resources_refuse(self):
        for target in (self.staged, self.d.resources):
            before = (target / 'app.asar').read_text()
            (target / 'app.asar').write_text('changed')
            with patch.object(self.d, 'running', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'changed'):
                    self.d.promote()
            (target / 'app.asar').write_text(before)
        self.assertFalse(self.d.backup.exists())

    def test_failed_final_verification_restores_original_resources(self):
        with patch.object(self.d, 'running', return_value=False), \
                patch.object(self.d, 'verify', side_effect=[None, RuntimeError('bad asset')]), \
                patch('desktop_install.subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'bad asset'):
                self.d.promote()
            launch.assert_not_called()
        self.assertEqual((self.d.resources / 'app.asar').read_text(), 'old')
        self.assertEqual((self.staged / 'app.asar').read_text(), 'new')

    def test_cancel_pending_install_leaves_original_desktop(self):
        self.d.prepare_rollback()
        self.assertEqual(self.d.read()['state'], 'cancelled')
        self.assertFalse(self.d.stage.exists())
        self.assertEqual((self.d.resources / 'app.asar').read_text(), 'old')

    def test_generated_token_persists_and_is_only_in_private_plugin_data(self):
        from types import SimpleNamespace
        fake_os = SimpleNamespace(name='nt', environ={'APPDATA': str(self.root)})
        with patch('desktop_install.os', fake_os):
            first = {}
            bootstrap_token(first)
            second = {}
            bootstrap_token(second)
        self.assertEqual(first['control_token'], second['control_token'])
        self.assertGreaterEqual(len(first['control_token']), 48)
        credential = self.root / 'Hermes/plugin-files/data/neo-composer/control.json'
        self.assertEqual(json.loads(credential.read_text())['token'], first['control_token'])

    def test_build_failure_restores_patched_sources(self):
        self.d.state_file.unlink()
        before = seed_host(self.root)
        control = HostControl({'hermes_root': str(self.root)})
        with patch.object(type(control.desktop), 'available', new_callable=lambda: property(lambda _: True)), \
                patch.object(control.desktop, 'custody') as custody, \
                patch.object(control.desktop, 'prepare', side_effect=RuntimeError('compiler failed')):
            with self.assertRaisesRegex(ControlError, 'compiler failed'):
                control.run('install')
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in before}, before)
        self.assertFalse((self.root / 'gateway/neo_composer_adapter.py').exists())
        self.assertFalse((self.root / '.neo-host-control.json').exists())


if __name__ == '__main__':
    unittest.main()
