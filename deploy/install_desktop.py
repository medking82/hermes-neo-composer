"""Install the advanced Desktop UI plus the host-owned Hermes model backend.

Run with Hermes' Python environment; no catalog UI is installed. Existing
service settings and host-adapter receipts are preserved. Backend enablement
uses the official CLI, which reloads supported live gateways.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def install(home, app_root=None):
    home = Path(home)
    app_root = Path(app_root) if app_root else home
    backend = home / 'plugins' / 'neo-composer'
    desktop = app_root / 'desktop-plugins' / 'neo-composer'
    # Do not turn an existing catalog install into a different distribution.
    if (backend / 'desktop').exists() or (desktop / '.hermes-package.json').exists():
        raise RuntimeError('Unified/catalog package detected; remove it before installing the advanced edition')
    files = {'__init__.py': '__init__.py', 'plugin.yaml': 'plugin.yaml',
             'LICENSE': 'LICENSE', 'dashboard/plugin_api.py': 'dashboard/plugin_api.py',
             'dashboard/manifest.json': 'dashboard/manifest.json'}
    for source, target in files.items():
        dest = backend / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'catalog' / source, dest)
    desktop.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'desktop-plugin' / 'neo-composer' / 'plugin.js', desktop / 'plugin.js')
    return backend, desktop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--app-root', type=Path)
    args = parser.parse_args()
    if args.home is None:
        from hermes_cli.config import get_hermes_home
        args.home = get_hermes_home()
    backend, desktop = install(args.home, args.app_root)
    env = {**os.environ, 'HERMES_HOME': str(args.home)}
    subprocess.run([sys.executable, '-m', 'hermes_cli.main', 'plugins', 'enable', 'neo-composer'],
                   env=env, check=True)
    print(f'Advanced UI installed: {desktop}')
    print(f'Hermes model backend installed: {backend}')
    print('Neo Composer settings → model source → Hermes; choose Auxiliary → Neo Composer.')


if __name__ == '__main__':
    main()
