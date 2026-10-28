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
    def test_logs_reads_only_and_preserves_levels_and_boot_order(self):
        gw=FakeGateway()
        raw='2026-10-28 10:00:00 [Warning][Alarm-Log] Link down\n1981-01-01 00:00:13 [Error][Alarm-Log] Device reset. Cause: [29999]\n2026-10-28 10:01:00 [Critical][Config-Log] Result:Success\n2026-10-28 10:02:00 [Info][Run-Log] Ready'
        encoded=''.join('\\x%02x'%ord(c) for c in raw)
        gw.page="<script>document.getElementById(\"logarea\").value='"+encoded+"';</script>"
        result=gw.logs()
        self.assertEqual(result['total'],4)
        self.assertEqual([e['level'] for e in result['events']],['INFO','ERROR','ERROR','WAR'])
        self.assertEqual(result['events'][1]['source_level'],'Critical')
        self.assertIn('Device reset',result['events'][2]['message'])
        self.assertEqual(gw.writes,[])

    def test_logs_rejects_login_page_and_bounds_events(self):
        gw=FakeGateway();gw.page='<html>Login</html>'
        with self.assertRaises(GatewayError):gw.logs()
        gw.page="document.getElementById('logarea').value='"+r'\x0a'.join('2026-10-28 10:00:00 [Notice][Run-Log] Event %s'%i for i in range(1002))+"';"
        result=gw.logs()
        self.assertTrue(result['limited'])
        self.assertEqual(len(result['events']),1000)
        self.assertEqual(result['events'][0]['message'],'Event 1001')

    def test_blocked_clients_includes_clients_missing_from_device_list(self):
        gw=FakeGateway()
        gw.block_policy=lambda:{'enabled':True,'blacklist':True,'rules':[['InternetGatewayDevice.X_HW_Security.WLANMacFilter.1','SSID-2','Phone','aa:bb:cc:dd:ee:ff']]}
        result=gw.blocked_clients([])
        self.assertEqual((result[0]['mac'],result[0]['status'],result[0]['port']),('aa:bb:cc:dd:ee:ff','blocked','SSID2'))
        gw.block_policy=lambda:{'enabled':False,'blacklist':True,'rules':[]}
        self.assertEqual(gw.blocked_clients([]),[])
    def test_unblock_removes_only_selected_rule_and_verifies(self):
        gw=FakeGateway(); domain='InternetGatewayDevice.X_HW_Security.WLANMacFilter.1'
        policies=iter([{'rules':[[domain,'SSID-1','Phone','aa:bb:cc:dd:ee:ff']]},{'rules':[]}])
        gw.block_policy=lambda:next(policies);gw.config_token=lambda:'a'*32
        with patch.object(gw,'request') as write:
            gw.unblock_client({'rule':domain,'mac':'aa:bb:cc:dd:ee:ff','confirm':'DESBLOQUEAR'})
        self.assertEqual(write.call_args.args[1],{domain:'','x.X_HW_Token':'a'*32})
    def test_unblock_rejects_different_mac_without_writes(self):
        gw=FakeGateway();domain='InternetGatewayDevice.X_HW_Security.WLANMacFilter.1'
        gw.block_policy=lambda:{'rules':[[domain,'SSID-1','Phone','aa:bb:cc:dd:ee:ff']]}
        with patch.object(gw,'request') as write:
            with self.assertRaises(GatewayError):gw.unblock_client({'rule':domain,'mac':'aa:bb:cc:dd:ee:00','confirm':'DESBLOQUEAR'})
            write.assert_not_called()
    def test_block_refuses_whitelist_and_existing_disabled_rules(self):
        gw=FakeGateway()
        gw.devices=lambda:[{'mac':'aa:bb:cc:dd:ee:ff','type':'wifi','port':'SSID1'}]
        for policy in ({'enabled':True,'blacklist':False,'rules':[]},{'enabled':False,'blacklist':True,'rules':[['old']]}):
            gw.block_policy=lambda:policy
            with patch.object(gw,'request') as write:
                with self.assertRaises(GatewayError): gw.block_client({'mac':'aa:bb:cc:dd:ee:ff','confirm':'BLOQUEAR','activate':True})
                write.assert_not_called()
    def test_gateway_registry_rejects_unknown_model_before_connecting(self):
        with self.assertRaises(GatewayError):
            app.create_gateway('outro-modelo', '192.168.100.254')
    def test_gateway_registry_supports_new_adapters(self):
        class Adapter:
            model_label = 'Modelo de teste'
            def __init__(self, address): self.address = address
        with patch.dict(app.GATEWAY_ADAPTERS, {'teste': Adapter}):
            self.assertEqual(app.create_gateway('teste', '192.168.1.1').address, '192.168.1.1')
    def test_device_tag_persists_and_can_be_removed(self):
        import io, json
        from pathlib import Path
        class Session:
            base = 'http://192.168.1.1'
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(app, 'DATA_DIR', Path(tmp)):
            def submit(tag):
                payload = json.dumps({'mac':'aa:bb:cc:dd:ee:ff','tag':tag}).encode()
                h = app.Handler.__new__(app.Handler)
                h.path = '/api/tag'; h.headers = {'Origin':'http://localhost','Host':'localhost','Content-Type':'application/json','Content-Length':str(len(payload))}
                h.rfile = io.BytesIO(payload); h.session = lambda: Session()
                with patch.object(h, 'send_json') as send:
                    h.do_POST()
                return send.call_args.args[0]
            self.assertEqual(submit('IoT'), 200)
            with app.labels() as db:
                self.assertEqual(db.execute('SELECT tag FROM device_tags').fetchone()[0], 'IoT')
            self.assertEqual(submit('inexistente'), 400)
            self.assertEqual(submit(''), 200)
            with app.labels() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM device_tags').fetchone()[0], 0)
    def test_fixed_ip_requires_matching_mac_and_ip(self):
        devices = [{'mac':'aa:bb:cc:dd:ee:ff','ip':'192.168.1.10','ip_type':'DHCP'}, {'mac':'aa:bb:cc:dd:ee:01','ip':'192.168.1.11','ip_type':'Static'}]
        app.mark_fixed_addresses(devices, [{'mac':'AA:BB:CC:DD:EE:FF','ip':'192.168.1.20'}])
        self.assertEqual([d['ip_fixed'] for d in devices], [False, False])
        self.assertEqual([d['ip_static'] for d in devices], [False, True])
        app.mark_fixed_addresses(devices, [{'mac':'AA:BB:CC:DD:EE:FF','ip':'192.168.1.10'}])
        self.assertTrue(devices[0]['ip_fixed'])
        app.mark_fixed_addresses(devices, [])
        self.assertFalse(devices[0]['ip_fixed'])
        app.mark_fixed_addresses(devices, [{'mac':'aa:bb:cc:dd:ee:ff','ip':'192.168.1.10','enabled':False}])
        self.assertFalse(devices[0]['ip_fixed'])
    def test_dhcp_parser_preserves_dns_and_network(self):
        gw = FakeGateway()
        gw.request = lambda path: '''var MainDhcpRange = new Array(new dhcpmainst("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement","1","192.168.1.2","192.168.1.200","86400","1","","","","","","","","","","","1.1.1.1,8.8.8.8","1","","0",""),null); var LanIpInfos = new Array(new stipaddr("domain","1","192.168.1.1","255.255.255.0"),null); onttoken'''
        c = gw.dhcp_config()
        self.assertEqual((c['start'], c['end'], c['lease'], c['dns_primary'], c['dns_secondary'], c['lan_ip']), ('192.168.1.2','192.168.1.200','86400','1.1.1.1','8.8.8.8','192.168.1.1'))
    def test_dns_write_only_changes_dns_and_verifies(self):
        gw = FakeGateway()
        base = {'enabled': True, 'start':'192.168.1.2', 'end':'192.168.1.200', 'lease':'86400', 'dns_primary':'1.1.1.1', 'dns_secondary':'', 'lan_ip':'192.168.1.1', 'mask':'255.255.255.0'}
        gw.dhcp_config = lambda: dict(base)
        gw.config_token = lambda: 'a'*32
        def request(path, data=None, **kw):
            self.assertEqual(set(data), {'z.X_HW_DNSList','x.X_HW_Token'})
            base['dns_primary'] = data['z.X_HW_DNSList']
        gw.request = request
        gw.save_dhcp({'dns_primary':'8.8.8.8','dns_secondary':''}, dns_only=True)
        self.assertEqual(base['dns_primary'], '8.8.8.8')
    def test_wifi_parser_only_reads_public_fields(self):
        gw=FakeGateway()
        gw.request=lambda path: '''var WlanArr = new Array(new stWlan("InternetGatewayDevice.LANDevice.1.WLANConfiguration.1","ath0","1","Rede","1","64","1"),null); onttoken; function t(){new stWlan(x,y)}'''
        networks=gw.wifi_config()
        self.assertEqual((networks[0]['ssid'],networks[0]['enabled'],networks[0]['broadcast']), ('Rede',True,True))
    def test_reboot_uses_observed_command(self):
        gw=FakeGateway(); gw.config_token=lambda:'a'*32
        with patch.object(gw, 'request') as request:
            gw.reboot()
        self.assertIn('ResetBoard', request.call_args.args[0])
        self.assertEqual(request.call_args.args[1], {'x.X_HW_Token':'a'*32})
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
        self.assertEqual(rows, [{'id': DOMAIN + '.1', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.100.100', 'enabled': True}])
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
