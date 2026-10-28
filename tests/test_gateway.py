import unittest
import tempfile
from unittest.mock import patch
import app
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
    def test_device_deep_link_serves_app(self):
        import io
        handler = app.Handler.__new__(app.Handler)
        handler.path = '/?device=aa%3Abb%3Acc%3Add%3Aee%3Aff'
        handler.wfile = io.BytesIO()
        with patch.object(handler, 'send_response') as response, patch.object(handler, 'send_header'), patch.object(handler, 'end_headers'):
            handler.do_GET()
        response.assert_called_once_with(200)
        self.assertIn(b'device-dialog', handler.wfile.getvalue())
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
    def test_device_list_deduplicates_branches_and_decodes_fields(self):
        row = r'new USERDevice("InternetGatewayDevice.LANDevice.1.X_HW_UserDev.1","192\x2e168\x2e1\x2e7","aa\x3abb\x3acc\x3add\x3aee\x3aff","SSID5","DHCP","","Online","WIFI","1\x3a2","Laptop\x2d1","1","0","0","Sala","","100","","","")'
        gw = FakeGateway()
        gw.request = lambda path: 'function USERDevice(){} var UserDevinfo = new Array(' + row + ',null); var UserDevinfo = new Array(' + row + ',null);'
        devices = gw.devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual((devices[0]['ip'], devices[0]['mac'], devices[0]['hostname'], devices[0]['gateway_name'], devices[0]['type'], devices[0]['status']), ('192.168.1.7','aa:bb:cc:dd:ee:ff','Laptop-1','Sala','wifi','online'))
        self.assertEqual((devices[0]['network'], devices[0]['duration'], devices[0]['ip_type']), ('5 GHz', '1:2', 'DHCP'))
    def test_discord_device_message_contains_direct_link(self):
        requests = []
        class Response:
            status = 200
            def read(self, size): return b'{}'
        class Connection:
            def __init__(self, host, timeout): pass
            def request(self, method, path, body, headers): requests.append(__import__('json').loads(body))
            def getresponse(self): return Response()
            def close(self): pass
        with patch.object(app.http.client, 'HTTPSConnection', Connection):
            app.send_discord('https://discord.com/api/webhooks/123456789012345678/' + 'a'*30,
                             {'mac':'aa:bb:cc:dd:ee:ff','ip':'192.168.1.2'}, 'Sala', 'http://192.168.1.10:8081')
        self.assertIn('Um novo dispositivo foi conectado ao roteador,\nNome: Sala\nIP: 192.168.1.2\nMAC: aa:bb:cc:dd:ee:ff', requests[0]['content'])
        self.assertIn('http://192.168.1.10:8081/?device=aa%3Abb%3Acc%3Add%3Aee%3Aff', requests[0]['content'])
    def test_device_list_rejects_session_error(self):
        gw = FakeGateway(); gw.request = lambda path: '<html>login</html>'
        with self.assertRaises(GatewayError): gw.devices()
    def test_devices_deduplicated_by_mac_preferring_online(self):
        def row(domain, status):
            return 'new USERDevice("%s","192.168.1.7","aa:bb:cc:dd:ee:ff","SSID1","DHCP","","%s","WIFI","","PC","1","0","0","","","","","")' % (domain, status)
        gw = FakeGateway()
        gw.request = lambda path: 'function USERDevice(){} var UserDevinfo = new Array(' + row('one','Offline') + ',' + row('two','Online') + ',null);'
        devices = gw.devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['status'], 'online')
        self.assertEqual(devices[0]['id'], 'two')
    def test_devices_reconnects_after_session_expires(self):
        gw = FakeGateway(); gw.credentials = ('user', 'secret')
        responses = iter(['login page', 'function USERDevice(){} var UserDevinfo = new Array(null);'])
        gw.request = lambda path: next(responses)
        with patch.object(gw, 'login') as login:
            self.assertEqual(gw.devices(), [])
            login.assert_called_once_with('user', 'secret')
    def test_discord_test_message_excludes_device_data(self):
        class Response:
            status = 200
            def read(self, size): return b'{}'
        class Connection:
            def __init__(self, host, timeout): pass
            def request(self, method, path, body, headers):
                data = __import__('json').loads(body)
                self.content = data['content']
                self_outer.assertIn('Teste de notificação', self.content)
                self_outer.assertNotIn('MAC:', self.content)
            def getresponse(self): return Response()
            def close(self): pass
        self_outer = self
        with patch.object(app.http.client, 'HTTPSConnection', Connection):
            app.send_discord('https://discord.com/api/webhooks/123456789012345678/' + 'a' * 30)
    def test_webhook_validates_discord_destination(self):
        token = 'a' * 30
        self.assertTrue(app.validate_webhook('https://discord.com/api/webhooks/123456789012345678/' + token))
        for bad in ('http://discord.com/api/webhooks/123456789012345678/' + token,
                    'https://discord.com.evil.test/api/webhooks/123456789012345678/' + token,
                    'https://discord.com/api/webhooks/123456789012345678/' + token + '?x=1'):
            with self.assertRaises(GatewayError): app.validate_webhook(bad)
    def test_webhook_baseline_new_device_and_retry(self):
        devices = [{'mac':'aa:bb:cc:dd:ee:01','status':'online','hostname':'PC','ip':'192.168.1.10','port':'LAN1'}]
        devices.append({'mac':'aa:bb:cc:dd:ee:03','status':'offline','hostname':'Known','ip':'192.168.1.12','port':'SSID1'})
        class MonitorGateway:
            base = 'http://192.168.1.1'
            lock = __import__('threading').RLock()
            def devices(self): return devices
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(app, 'DATA_DIR', __import__('pathlib').Path(tmp)):
            with app.labels() as db:
                db.execute('INSERT INTO webhook_config VALUES (?,?,?,?)', (MonitorGateway.base,'https://discord.com/api/webhooks/123456789012345678/'+'a'*30,1,0))
            with patch.object(app, 'send_discord') as send:
                app.monitor_once(MonitorGateway()); send.assert_not_called()
                devices[1]['status'] = 'online'
                app.monitor_once(MonitorGateway()); send.assert_not_called()
                devices.append({'mac':'aa:bb:cc:dd:ee:02','status':'online','hostname':'Phone','ip':'192.168.1.11','port':'SSID1'})
                send.side_effect=GatewayError('Erro simulado')
                with self.assertRaises(GatewayError): app.monitor_once(MonitorGateway())
                send.side_effect=None
                app.monitor_once(MonitorGateway())
                app.monitor_once(MonitorGateway())
                self.assertEqual(send.call_count,2)
    def test_reservations_show_gateway_names_and_shared_labels_by_mac(self):
        reservations = [{'mac': 'AA:BB:CC:DD:EE:FF', 'ip': '192.168.1.10'}]
        devices = [{'mac':'aa:bb:cc:dd:ee:ff','hostname':'Notebook','gateway_name':'Escritório','status':'online'}]
        result = app.enrich_reservations(reservations, devices, {'aa:bb:cc:dd:ee:ff':'Trabalho'})
        self.assertEqual((result[0]['hostname'], result[0]['gateway_name'], result[0]['name']), ('Notebook','Escritório','Trabalho'))
    def test_reservations_keep_local_labels_without_device_data(self):
        result = app.enrich_reservations([{'mac':'aa:bb:cc:dd:ee:ff'}], [], {'aa:bb:cc:dd:ee:ff':'Sala'})
        self.assertEqual((result[0]['hostname'],result[0]['name']), ('','Sala'))
    def test_public_address_rejected(self):
        with self.assertRaises(GatewayError): Gateway('8.8.8.8')

if __name__ == '__main__': unittest.main()
