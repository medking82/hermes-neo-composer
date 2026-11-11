import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('neo_desktop_install', Path(__file__).with_name('install_desktop.py'))
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_backend_and_advanced_ui_are_separate_and_preserve_control_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            desktop = home / 'desktop-plugins' / 'neo-composer'
            desktop.mkdir(parents=True)
            control = desktop / 'control.json'
            control.write_text('retained')
            for _ in range(2):
                backend, ui = installer.install(home)
                self.assertFalse((backend / 'desktop').exists())
                self.assertTrue((backend / 'dashboard' / 'plugin_api.py').exists())
                self.assertEqual((ui / 'plugin.js').read_bytes(),
                                 (installer.ROOT / 'desktop-plugin/neo-composer/plugin.js').read_bytes())
                self.assertEqual(control.read_text(), 'retained')

    def test_catalog_install_is_refused_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'plugins/neo-composer/desktop').mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                installer.install(home)
            self.assertFalse((home / 'desktop-plugins').exists())


if __name__ == '__main__':
    unittest.main()
