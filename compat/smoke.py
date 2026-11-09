"""Neo Composer compatibility smoke test — run after every Hermes or Magpie update.

    python compat/smoke.py [--hermes-src DIR] [--service URL] [--magpie URL] [--live]

Exit code 0 = every REQUIRED seam is present. Enhancer seams (in-box ghost text)
are reported as WARN: when they break, the underside pill still works.
stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_SRC = [
    Path(os.environ.get('LOCALAPPDATA', '')) / 'hermes/hermes-agent',
    Path.home() / '.hermes/hermes-agent',
]

# (label, file relative to hermes-agent, regex, required)
SEAMS = [
    ('sdk: COMPOSER_AREAS export', 'apps/desktop/src/sdk/index.ts', r'\bCOMPOSER_AREAS\b', True),
    ('sdk: underside area', 'apps/desktop/src/app/chat/composer/contrib.ts', r"underside", True),
    ('sdk: KEYBINDS_AREA / PALETTE_AREA', 'apps/desktop/src/sdk/index.ts', r'\bKEYBINDS_AREA\b[\s\S]*\bPALETTE_AREA\b|\bPALETTE_AREA\b[\s\S]*\bKEYBINDS_AREA\b', True),
    ('sdk: context clipboard', 'apps/desktop/src/contrib', r'writeClipboard', True),
    ('sdk: composer host setDraft/focus', 'apps/desktop/src/sdk', r'setDraft[\s\S]*focus', True),
    ('sdk: focusedSessionId / busyBySession', 'apps/desktop/src/sdk/index.ts', r'focusedSessionId[\s\S]*busyBySession|busyBySession[\s\S]*focusedSessionId', True),
    ('gateway: session.history RPC', 'tui_gateway', r'"session\.history"', True),
    ('gateway: history rows carry role+text', 'tui_gateway/session_history.py', r'\{"role": role, "text"', True),
    ('enhancer: composer-rich-input slot', 'apps/desktop/src/styles.css', r"\[data-slot='composer-rich-input'\][^{]*::before[\s\S]{0,80}attr\(data-placeholder\)", False),
]


def grep(base: Path, rel: str, pattern: str) -> bool:
    target = base / rel
    files = [target] if target.is_file() else [p for p in target.rglob('*') if p.suffix in {'.ts', '.tsx', '.py', '.css'}] if target.is_dir() else []
    rx = re.compile(pattern)
    for f in files:
        try:
            if rx.search(f.read_text(encoding='utf-8', errors='ignore')):
                return True
        except OSError:
            continue
    return False


def http_json(url, body=None, timeout=60):
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hermes-src', type=Path)
    ap.add_argument('--service', default=os.environ.get('NEO_SERVICE', 'http://127.0.0.1:3460'))
    ap.add_argument('--live', action='store_true', help='also request a real suggestion (uses one model call)')
    a = ap.parse_args(argv)

    fails = warns = 0
    src = a.hermes_src or next((p for p in DEFAULT_SRC if (p / 'apps/desktop').is_dir()), None)
    if src is None:
        print('SKIP  hermes source not found (headless host?) — SDK seams not checked')
    else:
        print(f'hermes source: {src}')
        for label, rel, pat, required in SEAMS:
            ok = grep(src, rel, pat)
            tag = 'OK  ' if ok else ('FAIL' if required else 'WARN')
            fails += (not ok) and required
            warns += (not ok) and not required
            print(f'{tag}  {label}')

    try:
        h = http_json(a.service.rstrip('/') + '/healthz', timeout=5)
        ok = h.get('contract') == 'neo-suggest-v1'
        print(f"{'OK  ' if ok else 'FAIL'}  service {h.get('version')} contract={h.get('contract')} models={h.get('models')} live={h.get('live_model')}")
        fails += not ok
        if a.live:
            conv = [{'role': 'user', 'content': 'Help me check the deploy logs.'},
                    {'role': 'assistant', 'content': 'The service logs show two timeouts. Want me to restart it or dig into the upstream first?'}]
            r = http_json(a.service.rstrip('/') + '/v1/suggest', {'messages': conv})
            ok = r.get('status') in ('ready', 'empty')
            print(f"{'OK  ' if ok else 'FAIL'}  live suggest status={r.get('status')} model={r.get('model')} -> {r.get('suggestion')!r} {r.get('error') or ''}")
            fails += not ok
    except Exception as exc:  # noqa: BLE001
        print(f'FAIL  service unreachable at {a.service}: {exc}')
        fails += 1

    print(f'\n{"PASS" if not fails else "FAIL"}  ({fails} failed, {warns} warnings)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
