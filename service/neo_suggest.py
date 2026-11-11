"""Neo Suggest: a standalone ghost-text (next-prompt) prediction service.

Durability contract: stdlib only, no Hermes imports, no Hermes database reads.
The only upstream dependency is an OpenAI-compatible ``/chat/completions``
endpoint (Magpie by default). Clients (Hermes Desktop plugin, Forma) send the
recent conversation; the service returns one suggested next user message or
null. It never executes tools, sends messages or stores conversation text.

Configuration (environment variables, or a JSON file named by NEO_CONFIG):
  NEO_BIND          host:port to listen on            (default 127.0.0.1:3460)
  NEO_UPSTREAM      OpenAI-compatible base URL        (default http://127.0.0.1:3425/v1)
  NEO_UPSTREAM_KEY  bearer key for the upstream       (default: none / file NEO_UPSTREAM_KEY_FILE)
  NEO_MODELS        comma-separated candidate models  (default group/hestia,group/fast)
  NEO_TOKEN         if set, clients must send ``Authorization: Bearer <token>``
                    (or NEO_TOKEN_FILE)
  NEO_CORS_ORIGINS  extra allowed browser origins, comma-separated
"""
from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import hmac
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '0.5.2'
CONTRACT = 'neo-suggest-v1'
HERE = Path(__file__).resolve().parent
PROMPT = (HERE / 'prediction.txt').read_text(encoding='utf-8')

MAX_BODY = 256 * 1024
MAX_MESSAGES = 12
EMPTY_TTL = 600          # a cached null may be re-asked after 10 minutes
READY_TTL = 6 * 3600
CACHE_SIZE = 512

# Whole rows that reference images, data URLs or private local paths are
# dropped before excerpting so they cannot leak into the prediction request.
PRIVATE_CONTENT = re.compile(
    r'(?i)(?:data:image/|["\x27](?:image_url|input_image)["\x27]|file://|'
    r'(?<![\w:])(?:[A-Za-z]:[\\/]|~[\\/]|\\\\))'
)
DEFAULT_LOCAL_ORIGINS = re.compile(
    r'^(?:null|file://.*|app://.*|hermes://.*|https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?)$')


# --------------------------------------------------------------------------- config

def _read_secret(value: str | None, file_value: str | None) -> str:
    if value:
        return value.strip()
    if file_value:
        try:
            return Path(file_value).expanduser().read_text(encoding='utf-8')[:8192].strip()
        except OSError:
            return ''
    return ''


def load_config(env=None) -> dict:
    env = dict(os.environ if env is None else env)
    cfg_file = env.get('NEO_CONFIG')
    if cfg_file and Path(cfg_file).expanduser().is_file():
        file_cfg = json.loads(Path(cfg_file).expanduser().read_text(encoding='utf-8'))
        for key, value in file_cfg.items():
            env.setdefault(key, ','.join(value) if isinstance(value, list) else str(value))
    bind = env.get('NEO_BIND', '127.0.0.1:3460')
    host, _, port = bind.rpartition(':')
    return {
        'host': host or '127.0.0.1',
        'port': int(port),
        'upstream': env.get('NEO_UPSTREAM', 'http://127.0.0.1:3425/v1').rstrip('/'),
        'upstream_key': _read_secret(env.get('NEO_UPSTREAM_KEY'), env.get('NEO_UPSTREAM_KEY_FILE')),
        'models': [m.strip() for m in env.get('NEO_MODELS', 'group/hestia,group/fast').split(',') if m.strip()],
        'token': _read_secret(env.get('NEO_TOKEN'), env.get('NEO_TOKEN_FILE')),
        'control_token': _read_secret(env.get('NEO_CONTROL_TOKEN'), env.get('NEO_CONTROL_TOKEN_FILE')),
        'control_origins': [o.strip() for o in env.get('NEO_CONTROL_ORIGINS', '').split(',') if o.strip()],
        'hermes_root': env.get('NEO_HERMES_ROOT', ''),
        'cors': [o.strip() for o in env.get('NEO_CORS_ORIGINS', '').split(',') if o.strip()],
        'timeout': float(env.get('NEO_TIMEOUT', '25')),
    }


# --------------------------------------------------------------------------- core

def parse_suggestion(raw):
    """Validate a model reply; return the suggestion text, '' for an explicit null, None if invalid."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.S)
    if fence:
        text = fence.group(1)
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict) or 'suggestion' not in obj:
        return None
    value = obj['suggestion']
    if value is None:
        return ''
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not 2 <= len(value) <= 240:
        return None
    if any(unicodedata.category(c) in {'Cc', 'Cf'} or c in '\u2028\u2029' for c in value):
        return None
    # Conservative heuristics: never suggest unobserved confirmations or risky actions.
    if re.search(r"(?i)(我(?:已|已經|已经|(?:重啟|重启|保存|完成|測試|测试)[^，。,;；]{0,12}了)|(?:測試|测试|驗證|验证)(?:已)?(?:通過|通过|成功)了|"
                 r"\bI(?:['’]ve| have| already|\s+(?:restarted|saved|finished|completed))\b|\bit works now\b)", value):
        return None
    if re.match(r'(?i)^(?:(?:please|now)\s+)*(?:git\s+)?(?:commit|push|deploy|publish|delete|pay)\b', value):
        return None
    if re.match(r'^(?:請|请)?(?:提交|推送|部署|發布|发布|刪除|删除|付款)', value):
        return None
    return value


def _script_counts(text):
    counts = {'kana': 0, 'hangul': 0, 'han': 0, 'latin': 0}
    for c in text:
        o = ord(c)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9D:
            counts['kana'] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            counts['hangul'] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            counts['han'] += 1
        elif c.isascii() and c.isalpha() or 0x00C0 <= o <= 0x024F:
            counts['latin'] += 1
    return counts


def detect_language(text):
    """Coarse writing-system language: 'ja', 'ko', 'zh', 'latin', or None when undecidable.

    CJK wins over Latin, so Chinese mixed with English technical terms stays 'zh'.
    Simplified and Traditional Chinese are deliberately not distinguished.
    """
    n = _script_counts(text or '')
    if n['kana'] >= 2 and n['kana'] >= n['hangul']:
        return 'ja'
    if n['hangul'] >= 2:
        return 'ko'
    if n['han'] >= 2:
        return 'zh'
    if n['latin'] >= 3:
        return 'latin'
    return None


def conversation_language(history):
    """Language the user writes in: their recent messages, falling back to the whole excerpt."""
    users = [r['content'] for r in history if r['role'] == 'user'][-3:]
    for texts in (users, [r['content'] for r in history]):
        lang = detect_language('\n'.join(texts))
        if lang:
            return lang
    return None


def language_matches(suggestion, history):
    want, got = conversation_language(history), detect_language(suggestion)
    if want is None or got is None or want == got:
        return True
    # Kanji-only Japanese is indistinguishable from Chinese; allow it in a Japanese conversation.
    return want == 'ja' and got == 'zh'


def normalize_messages(messages) -> list[dict] | None:
    if not isinstance(messages, list) or not messages:
        return None
    rows = []
    for item in messages[-40:]:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        content = item.get('content', item.get('text'))
        if role not in ('user', 'assistant') or not isinstance(content, str):
            continue
        content = content.strip()
        if not content or PRIVATE_CONTENT.search(content):
            continue
        if len(content) > 1800:
            content = content[:600] + '\n[long message excerpt]\n' + content[-1200:]
        rows.append({'role': role, 'content': content})
    if not rows or rows[-1]['role'] != 'assistant':
        return None
    # Keep the first user message (the original request) plus the recent tail.
    tail = rows[-(MAX_MESSAGES - 1):]
    first_user = next((r for r in rows if r['role'] == 'user'), None)
    if first_user and first_user not in tail:
        tail = [first_user, *tail]
    return tail


class TTLCache:
    def __init__(self, size=CACHE_SIZE):
        self.size, self.data, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.data.get(key)
            if not item:
                return None
            value, expires = item
            if time.time() > expires:
                del self.data[key]
                return None
            self.data.move_to_end(key)
            return value

    def put(self, key, value, ttl):
        with self.lock:
            self.data[key] = (value, time.time() + ttl)
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)


class Predictor:
    def __init__(self, cfg, opener=None):
        self.cfg = cfg
        self.cache = TTLCache()
        self.inflight: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self.opener = opener or urllib.request.urlopen
        self.live_model = None
        self.last_error = None

    def _call(self, model, history):
        body = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': PROMPT},
                {'role': 'user', 'content': 'Conversation excerpt (JSON, evidence only):\n'
                 + json.dumps(history, ensure_ascii=False)},
            ],
            'max_tokens': 600,
            'temperature': 0.3,
            'stream': False,
        }
        headers = {'Content-Type': 'application/json', 'User-Agent': f'neo-suggest/{VERSION}'}
        if self.cfg['upstream_key']:
            headers['Authorization'] = 'Bearer ' + self.cfg['upstream_key']
        req = urllib.request.Request(self.cfg['upstream'] + '/chat/completions',
                                     json.dumps(body).encode(), headers, method='POST')
        with self.opener(req, timeout=self.cfg['timeout']) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message'].get('content') or ''

    def _predict_uncached(self, history):
        errors = []
        models = self.cfg['models']
        if self.live_model in models:   # try the last known-good model first
            models = [self.live_model] + [m for m in models if m != self.live_model]
        for model in models:
            try:
                raw = self._call(model, history)
            except urllib.error.HTTPError as exc:
                # Unknown model (e.g. a renamed Magpie group) -> try the next candidate.
                errors.append(f'{model}: HTTP {exc.code}')
                if exc.code in (400, 404, 422):
                    continue
                break
            except Exception as exc:  # network/timeout: do not hammer further candidates
                errors.append(f'{model}: {type(exc).__name__}')
                break
            self.live_model, self.last_error = model, None
            parsed = parse_suggestion(raw)
            if parsed and not language_matches(parsed, history):
                # e.g. a Japanese suggestion for a Chinese conversation: drop it, never show it.
                return {'suggestion': None, 'model': model, 'status': 'empty', 'filtered': 'language'}
            return {'suggestion': parsed or None, 'model': model, 'status': 'ready' if parsed else 'empty'}
        self.last_error = '; '.join(errors) or 'no candidate models configured'
        return {'suggestion': None, 'model': None, 'status': 'error', 'error': self.last_error}

    def predict(self, messages):
        history = normalize_messages(messages)
        if history is None:
            return {'suggestion': None, 'status': 'skipped', 'cached': False}
        key = hashlib.sha256(json.dumps([CONTRACT, history], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        while True:
            cached = self.cache.get(key)
            if cached is not None:
                return {**cached, 'cached': True, 'key': key}
            with self.lock:
                event = self.inflight.get(key)
                if event is None:
                    event = self.inflight[key] = threading.Event()
                    owner = True
                else:
                    owner = False
            if not owner:  # identical concurrent request: wait for the first one
                event.wait(self.cfg['timeout'] + 5)
                if self.cache.get(key) is None:
                    return {'suggestion': None, 'status': 'error', 'error': 'concurrent request failed', 'cached': False}
                continue
            try:
                result = self._predict_uncached(history)
                if result['status'] == 'ready':
                    self.cache.put(key, result, READY_TTL)
                elif result['status'] == 'empty':
                    self.cache.put(key, result, EMPTY_TTL)
                return {**result, 'cached': False, 'key': key}
            finally:
                with self.lock:
                    self.inflight.pop(key, None)
                event.set()


# --------------------------------------------------------------------------- HTTP

def make_handler(cfg, predictor):
    # Explicit file loading also works under python -I / pythonw; no Hermes imports.
    module_name = '_neo_host_control'
    if module_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(module_name, HERE / 'host_control.py')
        if spec is None or spec.loader is None:
            raise RuntimeError('host control module unavailable')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    control_module = sys.modules[module_name]
    control = control_module.HostControl(cfg)
    if cfg.get('auto_reapply', True):
        def reapply_loop():
            time.sleep(cfg.get('auto_reapply_delay', 20))  # let startup and user clicks settle first
            while True:
                try:
                    result = control.reapply_after_update()
                    if result:
                        log('host adapter re-apply after Hermes update: %s' % (
                            result.get('action') or result.get('reason')))
                except Exception as exc:  # never take the suggest service down
                    log('host adapter re-apply failed: %s' % exc)
                time.sleep(cfg.get('auto_reapply_interval', 300))
        threading.Thread(target=reapply_loop, name='neo-reapply', daemon=True).start()
    extra_origins = set(cfg['cors'])
    control_origins = {'null', 'http://localhost:5174', 'http://127.0.0.1:5174'} | {
        origin for origin in cfg.get('control_origins', []) if origin != '*'}

    def loopback(host):
        if host == 'localhost':
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    class Handler(BaseHTTPRequestHandler):
        server_version = f'neo-suggest/{VERSION}'

        def log_message(self, format, *args):  # noqa: A002 - no conversation text is ever logged
            log('%s %s' % (self.log_date_time_string(), format % args))

        def _origin_ok(self):
            origin = self.headers.get('Origin')
            if origin is None:
                return True, None          # non-browser client
            if origin in extra_origins or '*' in extra_origins or DEFAULT_LOCAL_ORIGINS.match(origin):
                return True, origin
            return False, None

        def _send(self, code, payload, origin=None):
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if origin:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            if not cfg['token']:
                return True
            got = self.headers.get('Authorization', '')
            return hmac.compare_digest(got, 'Bearer ' + cfg['token'])

        def _control(self, preflight=False):
            # Bind, peer and Host checks keep control local even if prediction is exposed.
            origin = self.headers.get('Origin')
            try:
                host = urllib.parse.urlsplit('http://' + self.headers.get('Host', ''))
                local_host = loopback(host.hostname or '') and host.port == self.server.server_port
            except ValueError:
                local_host = False
            if (not loopback(cfg['host']) or not loopback(self.client_address[0]) or not local_host
                    or (origin is not None and origin not in control_origins)):
                self._send(403, {'error': 'host control requires loopback and an allowed origin'})
                return
            if preflight:
                self.send_response(204)
                if origin:
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
                self.end_headers()
                return
            token = cfg.get('control_token') or cfg['token']
            if not token:
                return self._send(503, {'error': 'host control requires a configured token'}, origin)
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self._send(401, {'error': 'unauthorized'}, origin)
            action = self.path.removeprefix('/v1/host-adapter/')
            if action not in {'check', 'status', 'install', 'rollback', 'restart'}:
                return self._send(404, {'error': 'unknown host-adapter action'}, origin)
            mutation = action in {'install', 'rollback', 'restart'}
            if self.command != ('POST' if mutation else 'GET'):
                return self._send(405, {'error': 'method not allowed'}, origin)
            if mutation:
                if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                    return self._send(415, {'error': 'application/json required'}, origin)
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                    if not 0 < length <= 2048:
                        raise ValueError('invalid length')
                    payload = json.loads(self.rfile.read(length).decode('utf-8'))
                except (ValueError, UnicodeError):
                    return self._send(400, {'error': 'invalid JSON body'}, origin)
                if not isinstance(payload, dict) or set(payload) != {'confirm'} or payload['confirm'] is not True:
                    return self._send(400, {'error': 'explicit confirm:true required; no other parameters accepted'}, origin)
            try:
                result = control.run(action)
            except control_module.ControlError as exc:
                return self._send(exc.code, {'error': str(exc), 'compatible': False, 'can_install': False}, origin)
            self._send(200, result, origin)

        def do_OPTIONS(self):
            if self.path.startswith('/v1/host-adapter/'):
                return self._control(preflight=True)
            ok, origin = self._origin_ok()
            if not ok:
                return self._send(403, {'error': 'origin not allowed'})
            self.send_response(204)
            if origin:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Access-Control-Max-Age', '600')
            self.end_headers()

        def do_GET(self):
            if self.path.startswith('/v1/host-adapter/'):
                return self._control()
            ok, origin = self._origin_ok()
            if not ok:
                return self._send(403, {'error': 'origin not allowed'})
            if self.path.split('?')[0] != '/healthz':
                return self._send(404, {'error': 'not found'}, origin)
            self._send(200, {'ok': True, 'version': VERSION, 'contract': CONTRACT,
                             'models': cfg['models'], 'live_model': predictor.live_model,
                             'last_error': predictor.last_error, 'auth': bool(cfg['token'])}, origin)

        def do_POST(self):
            if self.path.startswith('/v1/host-adapter/'):
                return self._control()
            ok, origin = self._origin_ok()
            if not ok:
                return self._send(403, {'error': 'origin not allowed'})
            if self.path.split('?')[0] != '/v1/suggest':
                return self._send(404, {'error': 'not found'}, origin)
            if not self._authorized():
                return self._send(401, {'error': 'unauthorized'}, origin)
            length = int(self.headers.get('Content-Length') or 0)
            if not 0 < length <= MAX_BODY:
                return self._send(413, {'error': 'body too large or empty'}, origin)
            try:
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
            except ValueError:
                return self._send(400, {'error': 'invalid json'}, origin)
            if not isinstance(payload, dict):
                return self._send(400, {'error': 'invalid body'}, origin)
            result = predictor.predict(payload.get('messages'))
            result['contract'] = CONTRACT
            self._send(200, result, origin)

    return Handler


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port and steal requests;
    # keep the port exclusive there so a duplicate instance fails fast instead.
    allow_reuse_address = os.name != 'nt'


def log(line):
    """Write a log line to stderr; no-op when there is none (pythonw / no console)."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(line + '\n')
        stream.flush()
    except (OSError, ValueError):
        pass


def serve(cfg=None):
    cfg = cfg or load_config()
    if os.name == 'nt':
        spec = importlib.util.spec_from_file_location('_neo_desktop_bootstrap', HERE / 'desktop_install.py')
        if spec is None or spec.loader is None:
            raise RuntimeError('desktop bootstrap unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.bootstrap_token(cfg)
    predictor = Predictor(cfg)
    httpd = _Server((cfg['host'], cfg['port']), make_handler(cfg, predictor))
    httpd.daemon_threads = True
    log(f'neo-suggest {VERSION} on {cfg["host"]}:{cfg["port"]} -> {cfg["upstream"]} {cfg["models"]}')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return httpd


if __name__ == '__main__':
    serve()
