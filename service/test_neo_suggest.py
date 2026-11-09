import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import neo_suggest as ns


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(replies, calls):
    """replies: model -> str content | int HTTP error code."""
    def opener(req, timeout=None):
        body = json.loads(req.data)
        calls.append(body['model'])
        reply = replies[body['model']]
        if isinstance(reply, int):
            raise urllib.error.HTTPError(req.full_url, reply, 'err', {}, None)
        return FakeResp(json.dumps({'choices': [{'message': {'content': reply}}]}).encode())
    return opener


CONV = [{'role': 'user', 'content': '幫我安裝 neo composer'},
        {'role': 'assistant', 'content': '已找到 repo，需要改用官方 SDK。'}]


def cfg(**kw):
    base = ns.load_config({'NEO_MODELS': 'group/a,group/b'})
    base.update(kw)
    return base


class LogTests(unittest.TestCase):
    def test_log_without_stderr(self):
        # pythonw (Windows, no console) sets sys.stderr to None; logging must not crash the service.
        import sys
        saved = sys.stderr
        try:
            sys.stderr = None
            ns.log('x')
        finally:
            sys.stderr = saved


class ParseTests(unittest.TestCase):
    def test_valid_and_fenced(self):
        self.assertEqual(ns.parse_suggestion('{"suggestion":"幫我裝到 GA401"}'), '幫我裝到 GA401')
        self.assertEqual(ns.parse_suggestion('```json\n{"suggestion":"run the tests"}\n```'), 'run the tests')

    def test_null_is_empty_string(self):
        self.assertEqual(ns.parse_suggestion('{"suggestion":null}'), '')

    def test_rejections(self):
        for bad in ['not json', '{"x":1}', '{"suggestion":"a"}', '{"suggestion":"git push now"}',
                    '{"suggestion":"我已經重啟了"}', '{"suggestion":"請部署到正式機"}',
                    '{"suggestion":"bad\u2028line"}', json.dumps({'suggestion': 'x' * 241})]:
            self.assertIsNone(ns.parse_suggestion(bad), bad)

    def test_spaces_allowed(self):
        self.assertEqual(ns.parse_suggestion('{"suggestion":"check the GA401 logs"}'), 'check the GA401 logs')


class NormalizeTests(unittest.TestCase):
    def test_requires_assistant_last(self):
        self.assertIsNone(ns.normalize_messages(CONV[:1]))
        self.assertIsNone(ns.normalize_messages([]))

    def test_private_rows_dropped_and_first_user_kept(self):
        rows = [{'role': 'user', 'content': 'original ask'}]
        rows += [{'role': 'assistant' if i % 2 else 'user', 'content': f'm{i}'} for i in range(1, 30)]
        rows.insert(5, {'role': 'user', 'content': 'see C:\\Users\\Marck\\secret.txt'})
        out = ns.normalize_messages(rows)
        self.assertEqual(out[0]['content'], 'original ask')
        self.assertFalse(any('secret' in r['content'] for r in out))
        self.assertLessEqual(len(out), ns.MAX_MESSAGES)

    def test_accepts_text_field(self):
        out = ns.normalize_messages([{'role': 'user', 'text': 'q'}, {'role': 'assistant', 'text': 'a'}])
        self.assertEqual(out[-1], {'role': 'assistant', 'content': 'a'})


class PredictorTests(unittest.TestCase):
    def test_fallback_on_unknown_model_and_sticky_live_model(self):
        calls = []
        p = ns.Predictor(cfg(), opener_for({'group/a': 404, 'group/b': '{"suggestion":"幫我裝到 GA401"}'}, calls))
        r = p.predict(CONV)
        self.assertEqual((r['status'], r['suggestion'], r['model']), ('ready', '幫我裝到 GA401', 'group/b'))
        self.assertEqual(calls, ['group/a', 'group/b'])
        calls.clear()
        r2 = p.predict(CONV + [{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': 'y'}])
        self.assertEqual(calls[0], 'group/b')
        self.assertEqual(r2['status'], 'ready')

    def test_cache_hit(self):
        calls = []
        p = ns.Predictor(cfg(), opener_for({'group/a': '{"suggestion":"next step please"}'}, calls))
        p.predict(CONV)
        r = p.predict(CONV)
        self.assertTrue(r['cached'])
        self.assertEqual(len(calls), 1)

    def test_empty_cached_error_not_cached(self):
        calls = []
        p = ns.Predictor(cfg(), opener_for({'group/a': 500, 'group/b': 'x'}, calls))
        r = p.predict(CONV)
        self.assertEqual(r['status'], 'error')
        self.assertEqual(calls, ['group/a'])  # 5xx does not fan out
        p.predict(CONV)
        self.assertEqual(len(calls), 2)       # errors are retried, not cached

    def test_skipped_when_not_after_assistant(self):
        p = ns.Predictor(cfg(), opener_for({}, []))
        self.assertEqual(p.predict(CONV[:1])['status'], 'skipped')


class HttpTests(unittest.TestCase):
    def start(self, **kw):
        c = cfg(port=0, **kw)
        calls = []
        pred = ns.Predictor(c, opener_for({'group/a': '{"suggestion":"show me the diff"}'}, calls))
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), ns.make_handler(c, pred))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return f'http://127.0.0.1:{httpd.server_address[1]}'

    def req(self, url, data=None, headers=None, method=None):
        r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None,
                                   {'Content-Type': 'application/json', **(headers or {})}, method=method)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, dict(resp.headers), json.loads(resp.read() or b'null')
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read() or b'null')

    def test_health_and_suggest(self):
        base = self.start()
        code, _, body = self.req(base + '/healthz')
        self.assertEqual((code, body['contract']), (200, 'neo-suggest-v1'))
        code, _, body = self.req(base + '/v1/suggest', {'messages': CONV})
        self.assertEqual((code, body['suggestion']), (200, 'show me the diff'))

    def test_token_required(self):
        base = self.start(token='s3cret')
        self.assertEqual(self.req(base + '/v1/suggest', {'messages': CONV})[0], 401)
        self.assertEqual(self.req(base + '/v1/suggest', {'messages': CONV}, {'Authorization': 'Bearer s3cret'})[0], 200)

    def test_cors(self):
        base = self.start(cors=['https://forma.example'])
        code, headers, _ = self.req(base + '/v1/suggest', {'messages': CONV}, {'Origin': 'https://evil.example'})
        self.assertEqual(code, 403)
        code, headers, _ = self.req(base + '/v1/suggest', {'messages': CONV}, {'Origin': 'https://forma.example'})
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), 'https://forma.example')
        code, headers, _ = self.req(base + '/v1/suggest', None, {'Origin': 'http://localhost:5173'}, method='OPTIONS')
        self.assertEqual(code, 204)


if __name__ == '__main__':
    unittest.main()
