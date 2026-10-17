"""Bundle the documented-SDK-only disk plugin, never the host installation."""
import hashlib
import json
from pathlib import Path
BASE = Path(__file__).resolve().parent
entry = (BASE / 'plugin/index.mjs').read_text()
imports, body = [], []
for line in entry.splitlines():
    if line.startswith('import '):
        if "from './" not in line:
            if not any("from '" + allowed + "'" in line for allowed in ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime']):
                raise ValueError('Unsupported import')
            imports.append(line)
    else:
        body.append(line)
modules = []
for name in ['controller.mjs', 'settings.mjs']:
    source = (BASE / 'plugin' / name).read_text()
    if 'import ' in source:
        raise ValueError('Unsupported module dependency')
    modules.append('\n'.join(line.removeprefix('export ') for line in source.splitlines()))
text = '\n'.join(imports + modules + body) + '\n'
out = BASE / 'dist'; out.mkdir(exist_ok=True)
(out / 'plugin.js').write_text(text)
manifest = {'id': 'neo-next-prompt', 'version': '0.4.5-rc.1', 'composer_protocol': 2,
            'strict_steering_protocol': 1,
            'supported_host_heads': ['d923a5eb487a17c0a68801bba9ef0f56c81040a8'],
            'plugin_sha256': hashlib.sha256(text.encode()).hexdigest()}
(out / 'compatibility.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest))
