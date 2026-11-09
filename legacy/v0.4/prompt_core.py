"""Deterministic, profile-local next-prompt state. No tools or model calls."""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

CONTRACT = 'neo-next-prompt-v1'
VALID_ID = re.compile(r'[A-Za-z0-9_:.-]{1,160}\Z')
# A cached valid-null may be re-asked once this many seconds after it landed.
EMPTY_RETRY_AFTER = 600

# Prediction is a separate request: omit whole image/path-bearing rows, before
# excerpting, so captions, data URLs and private local paths cannot escape in a
# head/tail window. This deliberately favors privacy over prediction context.
PRIVATE_PREDICTION_CONTENT = re.compile(
    r'(?i)(?:Neo Composer image references|data:image/|["\x27](?:image_url|input_image)["\x27]|file://|'
    r'(?<![\w:])(?:[A-Za-z]:[\\/]|~[\\/]|/[\w.~]|\\\\))'
)


def parse_suggestion(raw):
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != {'suggestion'}:
        return None
    text = obj['suggestion']
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not 2 <= len(text) <= 240 or any(unicodedata.category(c) in {'Cc', 'Cf'} or c in '\u2028\u2029' for c in text):
        return None
    # Conservative heuristics, not a semantic truth/authorization verifier.
    if re.search(r"(?i)(我(?:已|已经|(?:重启|保存|完成|测试)[^，。,;；]{0,12}了)|(?:测试|验证)(?:已)?(?:通过|成功)了|\bI(?:['’]ve| have| already|\s+(?:restarted|saved|finished|completed))\b|\bit works now\b|^(?:restarted|saved|已(?:经)?(?:重启|保存|完成|测试)))", text):
        return None
    if re.match(r'(?i)^(git\s+(?:commit|push)|(?:请)?(?:提交|推送|部署|发布|删除|付款))', text):
        return None
    if re.match(r'(?i)^(?:(?:please|now)\s+)*(?:git\s+)?(?:commit|push|deploy|publish|delete|pay)\b', text):
        return None
    return text


def read_snapshot(home, session_id, stored_id, route_revision=''):
    if not all(isinstance(x, str) and VALID_ID.fullmatch(x) for x in [session_id, stored_id]):
        return None
    dbfile = Path(home) / 'state.db'
    if not dbfile.is_file():
        return None
    with closing(sqlite3.connect(dbfile.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        session = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if not session or session['source'] != 'desktop' or session['archived']:
            return None
        lineage, current = [], session
        while current and len(lineage) < 128:
            if current['id'] in lineage:
                return None
            lineage.append(current['id'])
            parent = current['parent_session_id']
            if not parent:
                break
            current = db.execute('SELECT * FROM sessions WHERE id=?', (parent,)).fetchone()
        if not current or len(lineage) >= 128 or stored_id not in lineage:
            return None
        last = db.execute('SELECT id,role,tool_calls FROM messages WHERE session_id=? AND active=1 ORDER BY id DESC LIMIT 1', (session_id,)).fetchone()
        if not last or last['role'] != 'assistant' or last['tool_calls'] not in (None, '', '[]'):
            return None
        rows = db.execute("SELECT id,role,content FROM messages WHERE session_id=? AND active=1 AND (role='user' OR (role='assistant' AND (tool_calls IS NULL OR tool_calls='' OR tool_calls='[]'))) ORDER BY id DESC LIMIT 10", (session_id,)).fetchall()[::-1]
        first = db.execute("SELECT id,role,content FROM messages WHERE session_id=? AND active=1 AND role='user' ORDER BY id LIMIT 1", (session_id,)).fetchone()
        if first and rows and first['id'] != rows[0]['id']:
            rows = [first, *rows]
        cfg = json.loads(session['model_config'] or '{}')
        reasoning = cfg.get('reasoning_config')
        identity = [CONTRACT, lineage, last['id'], session['model'], reasoning, session['billing_provider'], session['rewind_count'], route_revision,
                    [[row['id'], row['role'], row['content']] for row in rows]]
        version = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        history = []
        for row in rows:
            text = row['content'] or ''
            if not isinstance(text, str) or PRIVATE_PREDICTION_CONTENT.search(text):
                continue
            if len(text) > 1800:
                text = text[:600] + '\n[long message excerpt]\n' + text[-1200:]
            history.append({'role': row['role'], 'content': text})
        return {'root': stored_id, 'version': version, 'session_id': session_id, 'stored_id': stored_id,
                'model': session['model'], 'provider': session['billing_provider'], 'reasoning_config': reasoning,
                'history': history, 'contract': CONTRACT}


class PromptStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS prompts_v2(root TEXT NOT NULL, version TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL, text TEXT, created REAL NOT NULL, session_id TEXT NOT NULL)')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, snapshot):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM prompts_v2 WHERE version=?', (snapshot['version'],)).fetchone()
            if row:
                if row['status'] == 'pending' and time.time() - row['created'] > 35:
                    db.execute("UPDATE prompts_v2 SET status='timeout',text=NULL WHERE version=?", (snapshot['version'],))
                    row = db.execute('SELECT * FROM prompts_v2 WHERE version=?', (snapshot['version'],)).fetchone()
                elif row['status'] == 'empty' and time.time() - row['created'] > EMPTY_RETRY_AFTER:
                    # Same context, still empty: allow one bounded re-ask. The old
                    # request id is rotated so a late finish cannot overwrite it.
                    record = (row['root'], row['version'], uuid.uuid4().hex, 'pending', None, time.time(), row['session_id'])
                    db.execute("UPDATE prompts_v2 SET request_id=?, status='pending', text=NULL, created=? WHERE version=? AND status='empty'",
                               (record[2], record[5], snapshot['version']))
                    row = db.execute('SELECT * FROM prompts_v2 WHERE version=?', (snapshot['version'],)).fetchone()
                    return dict(row), True
                return dict(row), False
            db.execute("UPDATE prompts_v2 SET status='stale',text=NULL WHERE session_id=? AND status='pending'", (snapshot['session_id'],))
            record = (snapshot['root'], snapshot['version'], uuid.uuid4().hex, 'pending', None, time.time(), snapshot['session_id'])
            db.execute('INSERT INTO prompts_v2 VALUES(?,?,?,?,?,?,?)', record)
            return dict(zip(['root', 'version', 'request_id', 'status', 'text', 'created', 'session_id'], record)), True

    def finish(self, row, status, text=None):
        if status not in {'ready', 'empty', 'error', 'timeout', 'stale'}:
            raise ValueError('invalid terminal status')
        if status == 'ready' and parse_suggestion(json.dumps({'suggestion': text})) != text:
            raise ValueError('invalid candidate')
        with self.connect() as db:
            result = db.execute("UPDATE prompts_v2 SET status=?,text=? WHERE root=? AND version=? AND request_id=? AND status='pending'",
                                (status, text, row['root'], row['version'], row['request_id']))
            return result.rowcount == 1

    def decide(self, root, version, request_id, status):
        if status not in {'consumed', 'dismissed'}:
            raise ValueError('invalid decision')
        with self.connect() as db:
            result = db.execute("UPDATE prompts_v2 SET status=?,text=NULL WHERE root=? AND version=? AND request_id=? AND status='ready'", (status, root, version, request_id))
            return result.rowcount == 1
