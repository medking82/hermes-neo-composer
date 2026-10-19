"""Bind a REST-loaded package to the host's public PluginContext facade.

The Python REST loader imports a separate module rather than passing register's
context. Reconstruct only this enabled package's public context in its active
profile; never instantiate PluginLlm or access manager internals/credentials.
"""
from pathlib import Path


def create_context(root):
    from hermes_constants import get_hermes_home
    from hermes_cli.config import load_config_readonly
    home, root = Path(get_hermes_home()).resolve(), Path(root).resolve()
    plugins = load_config_readonly().get('plugins', {})
    if (root != home / 'plugins' / 'neo-next-prompt' or not isinstance(plugins, dict)
            or 'neo-next-prompt' not in plugins.get('enabled', [])
            or 'neo-next-prompt' in plugins.get('disabled', [])):
        raise PermissionError('Host SDK context must belong to this enabled profile package')
    try:
        from hermes_cli.plugins import PluginContext, get_plugin_manager, parse_manifest_file
        manifest = parse_manifest_file(root / 'plugin.yaml', root, 'user', '')
        if manifest is None:
            return None
        if manifest.name != 'neo-next-prompt':
            raise PermissionError('Host SDK context identity does not match this package')
        manager = get_plugin_manager()
        if manager is None:
            return None
        context = PluginContext(manifest, manager)
        if context.plugin_id != 'neo-next-prompt':
            raise PermissionError('Host SDK context identity does not match this package')
    except (ImportError, TypeError, AttributeError):
        return None  # Public context contract changed; keep profile settings usable.
    return context
