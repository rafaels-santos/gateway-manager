import unittest
from app import Gateway, GatewayError, DOMAIN

PAGE = r'''<script>var Dhcps = new Array(new stDhcp("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1","1","192\x2e168\x2e100\x2e100","aa\x3abb\x3acc\x3add\x3aee\x3aff"),null); getValue('onttoken');</script>'''

class FakeGateway(Gateway):
    def __init__(self):
        super().__init__('192.168.100.254')
        self.page = PAGE
        self.writes = []
    def request(self, path, data=None):
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
    def test_public_address_rejected(self):
        with self.assertRaises(GatewayError): Gateway('8.8.8.8')

if __name__ == '__main__': unittest.main()
