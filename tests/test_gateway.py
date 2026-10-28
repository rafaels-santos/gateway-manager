import unittest
from unittest.mock import patch
from email.message import Message
from app import Gateway, GatewayError, DOMAIN

PAGE = r'''<script>var Dhcps = new Array(new stDhcp("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1","1","192\x2e168\x2e100\x2e100","aa\x3abb\x3acc\x3add\x3aee\x3aff"),null); getValue('onttoken');</script>'''

class FakeGateway(Gateway):
    def __init__(self):
        super().__init__('192.168.100.254')
        self.page = PAGE
        self.writes = []
    def request(self, path, data=None, **kwargs):
        if path.endswith('GetRandToken.asp'): return 'a' * 32
        if path.startswith('/set.cgi'):
            self.writes.append((path, data))
            self.page = self.page.replace(r'192\x2e168\x2e100\x2e100', r'192\x2e168\x2e100\x2e101')
            return 'ok'
        return self.page

class GatewayTests(unittest.TestCase):
    def test_parse_encoded_values(self):
        rows, _ = FakeGateway().reservations()
        self.assertEqual(rows, [{'id': DOMAIN + '.1', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.100.100'}])
    def test_update_and_verify(self):
        gw = FakeGateway()
        gw.save({'id': DOMAIN + '.1', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.100.101'})
        self.assertEqual(gw.writes[0][1]['x.Yiaddr'], '192.168.100.101')
    def test_invalid_target_does_not_write(self):
        gw = FakeGateway()
        with self.assertRaises(GatewayError):
            gw.save({'id': DOMAIN + '.99', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.100.101'})
        self.assertEqual(gw.writes, [])
    def test_utf8_bom_removed_from_gateway_token(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b"\xef\xbb\xbf" + b"a" * 64
        class Opener:
            def open(self, req, timeout): return Response()
        gw = Gateway('192.168.100.254')
        gw.opener = Opener()
        self.assertEqual(gw.request('/asp/GetRandCount.asp', {}, xhr=True), 'a' * 64)
    def test_login_uses_one_connection_and_installs_session_cookie(self):
        class Response:
            status = 200
            def __init__(self, body, cookie=None):
                self.body = body
                self.headers = Message()
                if cookie: self.headers.add_header('Set-Cookie', cookie)
            def read(self, limit): return self.body
        class Connection:
            def __init__(self, host, port, timeout): self.calls = []
            def request(self, method, path, body=None, headers=None): self.calls.append((method, path, headers))
            def getresponse(self):
                if len(self.calls) == 1: return Response(b"\xef\xbb\xbf" + b"a" * 64)
                return Response(b'ok', 'Cookie=sid=abc:Language:english:id=1; Path=/')
            def close(self): pass
        gw = Gateway('192.168.100.254')
        gw.request = lambda path: 'EG8145X6' if path == '/' else 'Logout'
        with patch('app.http.client.HTTPConnection', Connection) as constructor:
            gw.login('user', 'pass')
        self.assertEqual(next(iter(gw.cookies)).value, 'sid=abc:Language:english:id=1')

    def test_public_address_rejected(self):
        with self.assertRaises(GatewayError): Gateway('8.8.8.8')

if __name__ == '__main__': unittest.main()
