import io
import os
import unittest
from email.parser import BytesParser
from unittest.mock import patch

import app
from tools.check_repository import scan


class SecurityTests(unittest.TestCase):
    def response(self, secure):
        handler = app.Handler.__new__(app.Handler)
        handler.request_version = 'HTTP/1.1'
        handler.requestline = 'TEST'
        handler.wfile = io.BytesIO()
        with patch.dict(os.environ, {'COOKIE_SECURE': secure}):
            handler.send_json(200, {'ok': True}, 'test-session')
        raw = handler.wfile.getvalue().split(b'\r\n', 1)[1].split(b'\r\n\r\n')[0]
        return BytesParser().parsebytes(raw)

    def test_authenticated_json_is_not_cached_and_does_not_leak_runtime_version(self):
        headers = self.response('0')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('Python', headers['Server'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def test_secure_cookie_is_explicit_to_preserve_local_http_installations(self):
        self.assertNotIn('; Secure', self.response('0')['Set-Cookie'])
        self.assertIn('; Secure', self.response('1')['Set-Cookie'])

    def test_repository_scan_reports_location_without_secret_content(self):
        token = b'ghp_' + b'x' * 36
        findings = scan('sample.py', b'\n' + token)
        self.assertEqual(findings, [('sample.py', 2, 'GitHub token')])
        self.assertNotIn(token.decode(), str(findings))

    def test_repository_scan_rejects_runtime_and_credential_files(self):
        for name in ('data/labels.db', '.env', 'local.env.key', 'backup.sqlite', 'trace.log', 'compose.local.yml'):
            self.assertTrue(scan(name, b''), name)
        self.assertEqual(scan('static/app.js', b'const value = "normal";'), [])
