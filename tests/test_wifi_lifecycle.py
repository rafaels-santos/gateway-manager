import json
import sqlite3
import unittest
import urllib.parse

from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei import Gateway
from gateway_adapters.huawei.wifi_lifecycle import ROOT, PARALLEL

KEY = 'FixtureNewKey!123'


class LifecycleGateway(Gateway):
    def __init__(self):
        super().__init__('192.168.50.254')
        self.identity = {'hardware': '343D.D', 'firmware': 'V5R024C10S106'}
        self.db = sqlite3.connect(':memory:')
        self.label_store_factory = lambda: self.db
        self.rows = {ROOT+'.'+str(n): {'ssid': 'Guest' if n == 2 else 'Office'+str(n), 'enabled': True,
                     'broadcast': True, 'max_clients': '32', 'mode': '11i', 'key': 'FixturePrevious!123', 'wps': False}
                     for n in (1, 2, 5)}
        self.guest = ROOT+'.2'
        self.writes = []
        self.fail_security = self.fail_parallel = self.timeout_create = self.ap = False

    def label_store_context(self): return self.db
    def config_token(self): return 'fixture-token'

    def request(self, path, data=None, **kwargs):
        if data is not None:
            self.writes.append((path, data.copy()))
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            if path.startswith('/addcfg.cgi'):
                five = data['y.LowerLayers'].endswith('.2')
                index = next(n for n in ((6, 7) if five else (2, 3)) if ROOT+'.'+str(n) not in self.rows)
                self.rows[ROOT+'.'+str(index)] = {'ssid': data['y.SSID'], 'enabled': False, 'broadcast': False,
                                                  'max_clients': str(data['y.X_HW_AssociateNum']), 'mode': 'Basic', 'key': '', 'wps': True}
                if self.timeout_create: raise GatewayError('Resposta interrompida.')
            elif path.startswith('/del.cgi'):
                for ident in list(self.rows):
                    if ident in data: del self.rows[ident]
            elif query.get('y') == [PARALLEL]:
                if self.fail_parallel: raise GatewayError('Resposta interrompida.')
                if 'z.SSID_IDX' in data: self.guest = ''
            else:
                row = self.rows[query['y'][0]]
                if 'k.KeyPassphrase' in data:
                    if not self.fail_security:
                        row.update(mode='11i', key=data['k.KeyPassphrase'], wps=False)
                else:
                    row.update(ssid=data['y.SSID'], enabled=bool(data['y.Enable']), broadcast=bool(data['y.SSIDAdvertisementEnabled']))
            return 'OK'
        names = 'domain,name,enable,ssid,wlHide,DeviceNum,BeaconType,WPAAuthenticationMode,IEEE11iAuthenticationMode,X_HW_WPAand11iAuthenticationMode,IEEE11iEncryptionModes,LowerLayers'
        page = "var CfgMode='BREBG2';var ssidMaxNum='4';var SsidNum='"+','.join(str(sum(int(ident.split('.')[-1]) in nums for ident in self.rows)+1) for nums in (range(1,5), range(5,9)))+",0,';\n"
        page += 'function stWlan('+names+'){} function StApDevice(domain,type,serial,status,uptime,mode,sync,modes,bands,count,ssid){}\n'
        items = []
        for ident, row in self.rows.items():
            layer = 'InternetGatewayDevice.LANDevice.1.WiFi.Radio.'+('1' if int(ident.split('.')[-1]) < 5 else '2')
            values = [ident, 'ath', str(int(row['enabled'])), row['ssid'], str(int(row['broadcast'])), row['max_clients'], row['mode'],
                      'PSKAuthentication', 'PSKAuthentication', 'PSKAuthentication', 'AESEncryption', layer]
            items.append('new stWlan('+','.join(map(json.dumps, values))+')')
            page += 'new stPreSharedKey('+','.join(map(json.dumps, [ident+'.PreSharedKey.1', row['key'], '']))+');\n'
            page += 'new stWpsPin('+','.join(map(json.dumps, [ident+'.WPS', 'PBC', '', '', str(int(row['wps']))]))+');\n'
        page += 'var WlanArr = new Array('+','.join(items)+',null);\n'
        page += 'new stGuestSsid("InternetGatewayDevice.LANDevice.1.X_HW_WLANForGuest.1","'+(self.guest.split('.')[-1] if self.guest else '0')+'","1");\n'
        if self.ap: page += 'new StApDevice("AP","bridge","","1","0","","","","","","2");\n'
        return page + ' onttoken addcfg.cgi? y.LowerLayers y.SSID y.Enable y.SSIDAdvertisementEnabled y.WMMEnable y.X_HW_AssociateNum y.IEEE11iAuthenticationMode y.IEEE11iEncryptionModes k.KeyPassphrase z.Enable y.DeleteInstArray '+PARALLEL+' del.cgi?RequestFile SubmitForm.addParameter(wlandomain'

    def create_body(self):
        return {'action':'create', 'ssid':'New network', 'band':'2G', 'password':KEY, 'password_confirmation':KEY,
                'max_clients':16, 'confirm':'CRIAR REDE', 'expected':self.wifi_lifecycle()['expected']}

    def delete_body(self):
        return {'id':ROOT+'.2', 'confirm':'EXCLUIR REDE', 'confirm_ssid':'Guest', 'disconnect_clients':True,
                'clear_guest':True, 'expected':self.wifi_lifecycle()['expected']}


class LifecycleTests(unittest.TestCase):
    def test_creation_never_enables_or_broadcasts_before_or_after_security(self):
        gateway = LifecycleGateway(); result = gateway.create_wifi_network(gateway.create_body())
        self.assertTrue(result['verified'])
        self.assertEqual(len(gateway.writes), 2)
        self.assertEqual(gateway.writes[0][1]['y.Enable'], '0')
        self.assertEqual(gateway.writes[1][1]['y.Enable'], '0')
        self.assertEqual(gateway.writes[1][1]['z.Enable'], '0')
        row = gateway.rows[result['id']]
        self.assertFalse(row['enabled']); self.assertFalse(row['broadcast']); self.assertFalse(row['wps'])
        self.assertEqual(row['key'], KEY)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertNotIn(KEY, str(list(gateway.db.execute('SELECT * FROM wifi_provisioning'))))

    def test_unconfirmed_security_blocks_activation_and_can_resume_without_allocating(self):
        gateway = LifecycleGateway(); gateway.fail_security = True
        result = gateway.create_wifi_network(gateway.create_body()); self.assertFalse(result['verified'])
        ident = result['id']; before = len(gateway.writes)
        with self.assertRaisesRegex(GatewayError, 'recuperação'):
            gateway.save_wifi({'id':ident, 'ssid':'New network', 'enabled':True, 'broadcast':True})
        with self.assertRaisesRegex(GatewayError, 'recuperação'):
            gateway.save_wifi({'id':ident, 'ssid':'Renamed', 'enabled':False, 'broadcast':False})
        self.assertEqual(len(gateway.writes), before)
        gateway.fail_security = False
        result = gateway.resume_wifi_network({'id':ident,'password':KEY,'password_confirmation':KEY,
                    'confirm':'RECUPERAR REDE','expected':gateway.wifi_lifecycle()['expected']})
        self.assertTrue(result['verified'])
        self.assertEqual(sum(path.startswith('/addcfg.cgi') for path, _ in gateway.writes), 1)
        self.assertEqual(gateway.provisioning_rows(), [])

    def test_timeout_after_allocation_reuses_observed_object_without_duplicate_create(self):
        gateway = LifecycleGateway(); gateway.timeout_create = True
        self.assertTrue(gateway.create_wifi_network(gateway.create_body())['verified'])
        self.assertEqual(sum(path.startswith('/addcfg.cgi') for path, _ in gateway.writes), 1)

    def test_stale_snapshot_invalid_password_duplicate_name_and_profile_prevent_creation(self):
        for changes in ({'expected':'old'}, {'password':'weak'}, {'ssid':'Guest'}, {'band':'6G'}):
            gateway = LifecycleGateway()
            with self.assertRaises(GatewayError): gateway.create_wifi_network({**gateway.create_body(), **changes})
            self.assertEqual(gateway.writes, [])
        gateway = LifecycleGateway(); body = gateway.create_body(); gateway.identity['firmware'] = 'different'
        with self.assertRaises(GatewayError): gateway.create_wifi_network(body)
        self.assertEqual(gateway.writes, [])

    def test_exclusion_uses_two_scoped_phases_and_clears_only_selected_guest_reference(self):
        gateway = LifecycleGateway(); result = gateway.delete_wifi_network(gateway.delete_body())
        self.assertTrue(result['verified']); self.assertNotIn(ROOT+'.2', gateway.rows)
        self.assertEqual(len(gateway.writes), 2)
        self.assertEqual(set(gateway.writes[0][1]), {'y.DeleteInstArray','z.SSID_IDX','x.X_HW_Token'})
        self.assertEqual(gateway.writes[0][1]['y.DeleteInstArray'], '2')
        self.assertEqual(set(gateway.writes[1][1]), {ROOT+'.2','x.X_HW_Token'})
        self.assertEqual(set(gateway.rows), {ROOT+'.1', ROOT+'.5'})

    def test_parallel_timeout_stops_before_second_phase_and_does_not_retry(self):
        gateway = LifecycleGateway(); gateway.fail_parallel = True
        with self.assertRaisesRegex(GatewayError, 'interrompida'): gateway.delete_wifi_network(gateway.delete_body())
        self.assertEqual(len(gateway.writes), 1)

    def test_primary_ap_dependency_and_missing_guest_confirmation_block_deletion(self):
        gateway = LifecycleGateway()
        for changes in ({'id':ROOT+'.1','confirm_ssid':'Office1'}, {'clear_guest':False}, {'confirm_ssid':'wrong'}):
            with self.assertRaises(GatewayError): gateway.delete_wifi_network({**gateway.delete_body(), **changes})
        gateway.ap = True
        with self.assertRaises(GatewayError): gateway.delete_wifi_network(gateway.delete_body())
        self.assertEqual(gateway.writes, [])

    def test_journal_survives_new_adapter_and_keeps_gateway_scope(self):
        gateway = LifecycleGateway(); gateway.fail_security = True; gateway.create_wifi_network(gateway.create_body())
        replacement = LifecycleGateway(); replacement.db = gateway.db
        self.assertEqual(len(replacement.provisioning_rows()), 1)
        replacement.base = 'http://192.168.101.254'
        self.assertEqual(replacement.provisioning_rows(), [])
