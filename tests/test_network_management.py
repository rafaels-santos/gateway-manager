import json
import sqlite3
import unittest
import tempfile
import io
from email.message import Message
from unittest.mock import patch

from services import network_management as nm
from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei import Gateway
from gateway_adapters.huawei.local_records import DNS_SOURCE, DNS_DOMAIN, IPV6_DOMAIN, interface_id, parse_allocations
from gateway_adapters.huawei.observed_readers import dhcpv6_leases, mesh_nodes, observed_fields


CURRENT = {'lan_ip': '192.168.50.254', 'mask': '255.255.255.0', 'start': '192.168.50.1', 'end': '192.168.50.200', 'enabled': True}
MAC = 'aa:bb:cc:dd:ee:fe'


class LocalGateway(Gateway):
    def __init__(self):
        super().__init__('192.168.50.254')
        self.rows, self.writes = [], []
        self.confirm_write = True
    def dhcp_config(self): return CURRENT
    def config_token(self): return 'x' * 32
    def request(self, path, data=None, **kwargs):
        if data is not None:
            self.writes.append((path, data))
            if self.confirm_write:
                if path.startswith('/del.cgi'): self.rows = []
                else: self.rows = [[DNS_DOMAIN+'.1', data['x.IPAddress'], data['x.DomainName']]]
            return 'OK'
        if path == DNS_SOURCE:
            entries = ','.join('new DnsHostsItemClass('+','.join(json.dumps(value) for value in row)+')' for row in self.rows)
            return 'function DnsHostsItemClass(domain, IPAddress, DomainName){} var DnsHostsListTemp = new Array('+entries+(',' if entries else '')+'null);'
        if path == '/html/bbsp/dhcp/dhcp.asp':
            return 'new stLanHostInfo("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.1","1","192.168.50.254","255.255.255.0","1"); x.IPInterfaceIPAddress x.IPInterfaceSubnetMask'
        if path == '/html/amp/ethinfo/ethinfo.asp':
            return 'new DeviceLanMAC("InternetGatewayDevice.DeviceInfo","02:00:00:00:00:01","")'
        return 'GetDnsHostsList(); OnApplyButtonClick(); x.IPAddress x.DomainName ' + DNS_DOMAIN


class LocalRecordsTests(unittest.TestCase):
    def test_dns_add_writes_only_local_fields_and_checks_entire_result(self):
        gateway = LocalGateway()
        snapshot = gateway.local_records('dns')
        updated = gateway.save_local_record({'kind':'dns','action':'save','name':'Printer.home.arpa','ip':'192.168.50.20','expected':snapshot['expected'],'confirm':'APLICAR'})
        self.assertEqual(updated['records'][0]['name'], 'printer.home.arpa')
        self.assertEqual(set(gateway.writes[0][1]), {'x.DomainName','x.IPAddress','x.X_HW_Token'})
        self.assertIn('x=InternetGatewayDevice.X_HW_DNS.HOSTS', gateway.writes[0][0])

    def test_dns_changed_snapshot_or_public_address_prevents_write(self):
        gateway = LocalGateway()
        body = {'kind':'dns','action':'save','name':'printer.home.arpa','ip':'192.168.50.20','expected':'stale','confirm':'APLICAR'}
        with self.assertRaises(GatewayError): gateway.save_local_record(body)
        body.update(expected=gateway.local_records('dns')['expected'], ip='8.8.8.8')
        with self.assertRaises(GatewayError): gateway.save_local_record(body)
        self.assertEqual(gateway.writes, [])

    def test_unconfirmed_dns_write_is_not_reported_as_success_and_is_not_retried(self):
        gateway = LocalGateway(); gateway.confirm_write = False
        with self.assertRaisesRegex(GatewayError, 'não confirmou'):
            gateway.save_local_record({'kind':'dns','action':'save','name':'printer.home.arpa','ip':'192.168.50.20','expected':gateway.local_records('dns')['expected'],'confirm':'APLICAR'})
        self.assertEqual(len(gateway.writes), 1)

    def test_dns_delete_requires_existing_id_and_preserves_expected_table(self):
        gateway = LocalGateway(); gateway.rows = [[DNS_DOMAIN+'.1','192.168.50.20','printer.home.arpa']]
        updated = gateway.save_local_record({'kind':'dns','action':'delete','id':DNS_DOMAIN+'.1','expected':gateway.local_records('dns')['expected'],'confirm':'APLICAR'})
        self.assertEqual(updated['records'], [])
        self.assertEqual(set(gateway.writes[0][1]), {DNS_DOMAIN+'.1','x.X_HW_Token'})

    def test_ipv6_64_bit_identifier_is_not_parsed_as_a_full_address(self):
        page = 'function stConfig(domain,InterfaceID,Chaddr){}\nvar Configs = new Array(new stConfig('+json.dumps(IPV6_DOMAIN+'.1')+',"0000:0000:0000:0001",'+json.dumps(MAC)+'),null);'
        rows, recognized = parse_allocations(page)
        self.assertTrue(recognized)
        self.assertEqual(rows[0]['identifier'], '0000:0000:0000:0001')
        for value in ('::1','0:0:0:0','ffff:ffff:ffff:ffff','2001:db8::1'):
            with self.assertRaises(GatewayError): interface_id(value)

    def test_slaac_prevents_ipv6_submission(self):
        gateway = LocalGateway()
        page = 'function stConfig(domain,InterfaceID,Chaddr){}\nvar Configs = new Array(null)\nvar RaConfigs = new Array(new RaConfigInfoClass("InternetGatewayDevice.LANDevice.1.X_HW_RouterAdvertisement","0","1"),null); x.InterfaceID x.Chaddr ' + IPV6_DOMAIN
        with patch.object(gateway, 'request', return_value=page):
            result = gateway.local_records('ipv6')
            self.assertTrue(result['recognized']); self.assertFalse(result['writable'])
            with self.assertRaises(GatewayError): gateway.save_local_record({'kind':'ipv6','action':'save','expected':result['expected'],'confirm':'APLICAR'})
        self.assertEqual(gateway.writes, [])


class NetworkPlanningTests(unittest.TestCase):
    def test_lan_preview_finds_dhcp_reservation_and_occupied_address_conflicts(self):
        rows = [{'mac':MAC,'ip':'192.168.50.90','enabled':True}]
        result = nm.preview_lan(CURRENT, rows, [], {'ip':'192.168.101.254','mask':'255.255.255.0'})
        self.assertEqual(len(result['blockers']), 2)
        self.assertEqual(result['affected_reservations'][0]['mac'], MAC.upper())
        self.assertFalse(result['apply_available'])
        occupied = nm.preview_lan(CURRENT, [], [{'status':'online','ip':'192.168.50.220','mac':MAC}], {'ip':'192.168.50.220','mask':'255.255.255.0'})
        self.assertIn('Outro cliente', occupied['blockers'][0])

    def test_lan_preview_rejects_noncontiguous_host_and_public_masks(self):
        for ip, mask in [('192.168.50.2','0.0.0.255'), ('192.168.50.2','255.0.0.0'), ('8.8.8.8','255.255.255.0'), ('192.168.50.0','255.255.255.0')]:
            with self.assertRaises(GatewayError): nm.preview_lan(CURRENT, [], [], {'ip':ip,'mask':mask})

    def test_diagnostic_rejects_external_unknown_hosts_and_unapproved_ports_before_socket(self):
        with patch.object(nm.socket, 'create_connection') as connect:
            for ip, port in [('8.8.8.8',80),('192.168.50.12',80),('192.168.50.254',22),('127.0.0.1',80)]:
                with self.assertRaises(GatewayError): nm.tcp_diagnostic(CURRENT, [], ip, port)
            connect.assert_not_called()

    def test_refusal_is_not_presented_as_network_isolation(self):
        with patch.object(nm.socket,'create_connection',side_effect=ConnectionRefusedError()):
            result = nm.tcp_diagnostic(CURRENT, [], '192.168.50.254', 80)
        self.assertEqual(result['outcome'], 'refused')
        self.assertIn('não comprova isolamento', result['description'])


class WifiPlanningTests(unittest.TestCase):
    def test_wpa3_requires_wps_to_be_confirmed_disabled(self):
        gateway = LocalGateway()
        target = {'id':'InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','ssid':'Office','expected':'snapshot','writable':True,'profiles':[{'id':'wpa3'}],'wps_enabled':True}
        with patch.object(gateway,'wifi_security',return_value=[target]),patch.object(gateway,'request') as request:
            with self.assertRaisesRegex(GatewayError,'WPS'): gateway.save_wifi_security({'id':target['id'],'mode':'wpa3','expected':'snapshot','confirm':'WIFI'})
            request.assert_not_called()

    def test_security_reader_never_returns_keys_or_radius_secrets(self):
        gateway = LocalGateway()
        names=['domain','ssid','BeaconType','WPAAuthenticationMode','IEEE11iAuthenticationMode','X_HW_WPAand11iAuthenticationMode','IEEE11iEncryptionModes','RadiusKey']
        values=['InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','Office','11i','PSKAuthentication','PSKAuthentication','PSKAuthentication','AESEncryption','SECRET_MUST_NOT_ESCAPE']
        page='function stWlan('+','.join(names)+'){} var WlanArr = new Array(new stWlan('+','.join(json.dumps(value) for value in values)+'),null); y.IEEE11iAuthenticationMode'
        with patch.object(gateway,'request',return_value=page): result=gateway.wifi_security()
        self.assertEqual(result[0]['mode'],'wpa2')
        self.assertNotIn('SECRET_MUST_NOT_ESCAPE',json.dumps(result))
        self.assertNotIn('RadiusKey',json.dumps(result))

    def test_authentication_write_preserves_keys_and_checks_readback(self):
        gateway=LocalGateway()
        original={'id':'InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','ssid':'Office','expected':'snapshot','mode':'transition','writable':True,'profiles':[{'id':'wpa2'}]}
        updated={**original,'mode':'wpa2','encryption':'AESEncryption'}
        with patch.object(gateway,'wifi_security',side_effect=[[original],[updated]]),patch.object(gateway,'request',return_value='OK') as request:
            gateway.save_wifi_security({'id':original['id'],'mode':'wpa2','expected':'snapshot','confirm':'WIFI'})
            self.assertEqual(set(request.call_args.args[1]),{'y.BeaconType','y.IEEE11iAuthenticationMode','y.IEEE11iEncryptionModes','x.X_HW_Token'})
            self.assertFalse(any('PreSharedKey' in key for key in request.call_args.args[1]))

    def test_radio_power_write_does_not_send_channel_or_regulatory_settings(self):
        gateway=LocalGateway()
        original={'id':'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5','expected':'snapshot','writable':True,'power':'100','power_options':['100','80'],'country':'BR','standard':'11ax','auto_channel':True,'width_code':'4','channel':'40'}
        updated={**original,'power':'80'}
        with patch.object(gateway,'radio_config',side_effect=[[original],[updated]]),patch.object(gateway,'request',return_value='OK') as request:
            gateway.save_radio({'id':original['id'],'power':'80','expected':'snapshot','confirm':'WIFI'})
            self.assertEqual(set(request.call_args.args[1]),{'y.TransmitPower','x.X_HW_Token'})

    def test_unrecognized_radio_customization_is_read_only(self):
        gateway=LocalGateway()
        row=['InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','ath0','1','Office','1','11ax','11','100','BR','1','0']
        page='var CfgMode = "OTHER"; y.TransmitPower; new stWlanWifi('+','.join(json.dumps(v) for v in row)+')'
        with patch.object(gateway,'request',return_value=page):
            result=gateway.radio_config()
            self.assertFalse(result[0]['writable']);self.assertEqual(result[0]['power_options'],[])

    def test_client_limit_requires_fresh_snapshot_and_verifies_readback(self):
        gateway = LocalGateway()
        original = {'id':'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5','ssid':'Office','enabled':True,'broadcast':True,'max_clients':'64','max_clients_writable':True}
        updated = {**original,'max_clients':'24'}
        body = {**original,'max_clients':'24','expected':original,'confirm':'WIFI'}
        with patch.object(gateway,'wifi_config',side_effect=[[original],[updated]]),patch.object(gateway,'request',return_value='OK') as request:
            result = gateway.save_wifi(body)
            self.assertEqual(result['max_clients'],'24')
            self.assertEqual(request.call_args.args[1]['y.X_HW_AssociateNum'],24)
            self.assertTrue(request.call_args.kwargs['referer'].endswith('?5G'))
            self.assertFalse(any('WAN' in key for key in request.call_args.args[1]))

    def test_stale_wifi_state_and_backhaul_are_rejected_without_writes(self):
        gateway = LocalGateway()
        original = {'id':'InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','ssid':'Office','enabled':True,'broadcast':True,'max_clients':'64'}
        for target,body in [(original,{**original,'expected':{**original,'ssid':'Old'}}),({**original,'managed_by_mesh':True},original)]:
            with patch.object(gateway,'wifi_config',return_value=[target]),patch.object(gateway,'request') as request:
                with self.assertRaises(GatewayError): gateway.save_wifi(body)
                request.assert_not_called()


class ObservationTests(unittest.TestCase):
    def setUp(self): self.db = sqlite3.connect(':memory:'); nm.schema(self.db)
    def tearDown(self): self.db.close()
    def test_baseline_and_unchanged_samples_produce_no_events(self):
        sample = [{'mac':MAC,'status':'online','ip':'192.168.50.12','port':'SSID1'}]
        nm.observe_devices(self.db,'gw',sample); nm.observe_devices(self.db,'gw',sample)
        self.assertEqual(nm.history(self.db,'gw')['events'], [])
        sample[0]['ip'] = '192.168.50.13'; nm.observe_devices(self.db,'gw',sample)
        nm.observe_devices(self.db,'gw',[]); nm.observe_devices(self.db,'gw',[])
        self.assertEqual([row['kind'] for row in nm.history(self.db,'gw')['events']], ['disconnected','ip_changed'])
        self.assertEqual(nm.history(self.db,'other')['events'], [])

    def test_history_filters_pagination_and_gateway_boundaries(self):
        for i in range(5): nm.event(self.db,'gw','diagnostic',f'Test {i}',level='WAR')
        nm.event(self.db,'other','diagnostic','private')
        first = nm.history(self.db,'gw',level='WAR',limit=2)
        second = nm.history(self.db,'gw',before=first['next_before'],limit=2)
        self.assertFalse(set(row['id'] for row in first['events']) & set(row['id'] for row in second['events']))
        self.assertEqual(len(nm.history(self.db,'gw',query='Test 3')['events']),1)

    def test_failed_page_does_not_create_configuration_change(self):
        first = {'id':'lan_address','label':'LAN','status':'available','recognized':True,'observations':[{'label':'IP','value':'192.168.50.254','field':'ip'}]}
        nm.observe_pages(self.db,'gw',[first]);nm.observe_pages(self.db,'gw',[{'id':'lan_address','status':'unavailable'}]);nm.observe_pages(self.db,'gw',[first])
        self.assertEqual(nm.history(self.db,'gw')['events'], [])

    def test_failed_ethernet_refresh_discards_previous_port_status(self):
        gateway = LocalGateway(); gateway.lan_port_statuses = {'LAN1':{'status':'Up'}}
        with patch.object(gateway,'request',side_effect=GatewayError('HTTP 403')):
            pages = gateway.inspect_network_pages(['system_information'])
        self.assertEqual(gateway.lan_port_statuses,{})
        self.assertEqual(pages[0]['status'],'denied')
        self.assertIn('sampled_at',pages[0])

    def test_dhcpv6_duid_is_kept_separate_from_mac(self):
        page = 'function DhcpInfoClass(domain, DUID, IPAddress, PrefixLen, Duration){} var RecordList = new Array(new DhcpInfoClass("local","0001:0001:aabbccddeeff","2001:db8::20","64","600"),null);'
        leases, recognized = dhcpv6_leases(page)
        self.assertTrue(recognized); self.assertEqual(leases[0]['duid'],'0001:0001:AABBCCDDEEFF'); self.assertNotIn('mac',leases[0])

    def test_topology_distinguishes_stations_from_agents_and_discards_unknown_fields(self):
        tree = [{'mac_address':'aabbccddeefe','password':'must not escape','station_info':[{'station_mac':'102030405060','link':'5G'}],'child_devices':[{'mac_address':'203040506070','station_info':[]}]}]
        nodes, recognized = mesh_nodes('var staInfo = '+"'"+json.dumps(tree)+"';")
        self.assertTrue(recognized); self.assertEqual([node['role'] for node in nodes],['Controller','Station','Agent'])
        self.assertNotIn('password',json.dumps(nodes))

    def test_layer3_checkboxes_are_read_from_actual_constructor_values(self):
        page = 'new stLayer3Enable("InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.1","1")'
        values = observed_fields('port_mode',page)
        self.assertEqual(values[0]['value'],'Layer 3')

    def test_ethernet_reader_excludes_pon_and_combines_64_bit_lan_counters(self):
        page='new GEInfo("InternetGatewayDevice.X_HW_DEBUG.AMP.LANPort.2.CommonConfig","1","2","1","1"); new LANStats("InternetGatewayDevice.X_HW_DEBUG.AMP.LANPort.2.Statistics","4","1","10","0","0","0","2","0","20","0","0","0"); new PONStats("optical","secret")'
        values=observed_fields('system_information',page)
        self.assertEqual(values[0]['status'],'Up');self.assertEqual(values[0]['port'],'LAN2')
        self.assertTrue(any('4294967300 pacotes' in value['value'] for value in values))
        self.assertNotIn('secret',json.dumps(values))

    def test_uptime_decrease_is_marked_as_inference_not_confirmed_cause(self):
        def sample(value):
            return {'id':'system_information','label':'System Information','status':'available','recognized':True,'observations':observed_fields('system_information',f'<table><tr><td>System Uptime</td><td>{value}</td></tr></table>')}
        nm.observe_pages(self.db,'gw',[sample('2 days 01:02:03')])
        nm.observe_pages(self.db,'gw',[sample('00:02:03')])
        events = nm.history(self.db,'gw')['events']
        self.assertEqual(events[0]['kind'],'possible_restart')
        self.assertEqual(events[0]['evidence'],'inferred')


class NetworkHttpTests(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        self.directory = tempfile.TemporaryDirectory(dir=app.ROOT)
        self.storage = patch.object(app,'DATA_DIR',app.Path(self.directory.name)); self.storage.start()
        self.gateway = LocalGateway()
        self.gateway.devices = lambda: []
        self.gateway.reservations = lambda: ([], '')
        self.sessions = patch.dict(app.SESSIONS, {'network-unit':self.gateway}); self.sessions.start()
        self.origin = 'http://127.0.0.1:8765'
    def tearDown(self):
        self.sessions.stop(); self.storage.stop(); self.directory.cleanup()
    def request(self,path,body=None,authenticated=True,origin=None):
        headers = {'Origin':origin or self.origin,'Host':'127.0.0.1:8765','Content-Type':'application/json'}
        if authenticated: headers['Cookie'] = 'session=network-unit'
        payload = json.dumps(body).encode() if body is not None else b''
        headers['Content-Length'] = str(len(payload))
        handler = self.app.Handler.__new__(self.app.Handler)
        handler.headers = Message()
        for key, value in headers.items(): handler.headers[key] = value
        handler.path = path; handler.request_version = 'HTTP/1.1'; handler.requestline = 'TEST '+path
        handler.rfile = io.BytesIO(payload); handler.wfile = io.BytesIO()
        handler.do_POST() if body is not None else handler.do_GET()
        head, data = handler.wfile.getvalue().split(b'\r\n\r\n',1)
        return int(head.split(b' ')[1]), data
    def test_new_frontend_bundle_is_served_and_loaded_by_home(self):
        status, data = self.request('/'); self.assertEqual(status,200); self.assertIn(b'/network.js',data)
        status, data = self.request('/network.js'); self.assertEqual(status,200); self.assertIn(b'networkPageLoaders',data)
    def test_preview_route_reads_current_state_without_sending_a_router_command(self):
        status, data = self.request('/api/network/lan-preview',{'ip':'192.168.101.254','mask':'255.255.255.0'})
        self.assertEqual(status,200); result = json.loads(data)
        self.assertFalse(result['apply_available']); self.assertTrue(result['blockers']); self.assertEqual(self.gateway.writes,[])
    def test_local_records_and_history_require_authenticated_app_session(self):
        for path in ('/api/network/history','/api/local-records?kind=dns','/api/network/export'):
            status, data = self.request(path,authenticated=False)
            self.assertEqual(status,400); self.assertIn('error',json.loads(data))
        self.assertEqual(self.gateway.writes,[])
    def test_records_save_route_preserves_csrf_check(self):
        body={'kind':'dns','action':'save','name':'printer.home.arpa','ip':'192.168.50.20','expected':self.gateway.local_records('dns')['expected'],'confirm':'APLICAR'}
        status, data = self.request('/api/local-records',body,origin='http://other.invalid')
        self.assertEqual(status,400)
        self.assertEqual(self.gateway.writes,[])


if __name__ == '__main__': unittest.main()
