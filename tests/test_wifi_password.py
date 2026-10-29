import hashlib
import json
import unittest
import urllib.parse

from gateway_adapters.huawei import Gateway
from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei.radio_security import password_matches


ROOT = 'InternetGatewayDevice.LANDevice.1.WLANConfiguration.'
OLD = 'PreviousKey!456'
NEW = 'ReplacementKey!789'


class PasswordGateway(Gateway):
    def __init__(self):
        super().__init__('192.168.100.254')
        self.keys = {ROOT+'1': OLD, ROOT+'5': OLD}
        self.writes = []
        self.partial = self.timeout = False

    def config_token(self):
        return 'fixture-token'

    def request(self, path, data=None, **kwargs):
        if data is not None:
            self.writes.append((path, data))
            if self.timeout:
                raise GatewayError('Resposta interrompida.')
            aliases = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            for alias, domain in aliases.items():
                if alias.startswith('k'):
                    ident = domain[0].removesuffix('.PreSharedKey.1')
                    if not self.partial or ident.endswith('.1'):
                        self.keys[ident] = data[alias+'.KeyPassphrase']
            return 'OK'
        names = 'domain,ssid,BeaconType,WPAAuthenticationMode,IEEE11iAuthenticationMode,X_HW_WPAand11iAuthenticationMode,IEEE11iEncryptionModes'
        page = 'function stWlan('+names+'){} y.IEEE11iAuthenticationMode k.KeyPassphrase\n'
        for ident, key in self.keys.items():
            fields = [ident, 'Office', '11i', 'PSKAuthentication', 'PSKAuthentication', 'PSKAuthentication', 'AESEncryption']
            page += 'new stWlan('+','.join(map(json.dumps, fields))+');\n'
            page += 'new stPreSharedKey('+','.join(map(json.dumps, [ident+'.PreSharedKey.1', key, '']))+');\n'
            page += 'new stWpsPin('+','.join(map(json.dumps, [ident+'.WPS', 'PBC', '', '', '0']))+');\n'
        return page

    def body(self):
        row = self.wifi_security()[0]
        return {'id': row['id'], 'expected': row['password_expected'], 'password': NEW,
                'password_confirmation': NEW, 'confirm': 'WIFI'}


class PasswordTests(unittest.TestCase):
    def test_group_write_is_scoped_and_never_returns_keys(self):
        gateway = PasswordGateway()
        public = gateway.wifi_security()
        self.assertEqual(len(public[0]['affected_ssids']), 2)
        self.assertNotIn(OLD, json.dumps(public))
        result = gateway.save_wifi_password(gateway.body())
        self.assertTrue(result['verified'])
        self.assertEqual(set(gateway.keys.values()), {NEW})
        self.assertEqual(len(gateway.writes), 1)
        path, data = gateway.writes[0]
        self.assertEqual(set(data), {'k0.KeyPassphrase', 'k1.KeyPassphrase', 'x.X_HW_Token'})
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['k1'], [ROOT+'5.PreSharedKey.1'])
        self.assertNotIn(NEW, json.dumps(result))

    def test_changed_password_snapshot_prevents_write(self):
        gateway = PasswordGateway()
        body = gateway.body()
        gateway.keys[ROOT+'5'] = 'ChangedKey!123'
        with self.assertRaisesRegex(GatewayError, 'mudou'):
            gateway.save_wifi_password(body)
        self.assertEqual(gateway.writes, [])

    def test_partial_group_change_never_reports_success_or_retries(self):
        gateway = PasswordGateway()
        gateway.partial = True
        with self.assertRaisesRegex(GatewayError, 'todo o grupo'):
            gateway.save_wifi_password(gateway.body())
        self.assertEqual(len(gateway.writes), 1)

    def test_timeout_does_not_resend_the_password(self):
        gateway = PasswordGateway()
        gateway.timeout = True
        with self.assertRaises(GatewayError):
            gateway.save_wifi_password(gateway.body())
        self.assertEqual(len(gateway.writes), 1)

    def test_invalid_or_unconfirmed_passwords_cannot_be_sent(self):
        for changes in ({'password': 'weak'}, {'password': 'Replacement Key!789'},
                        {'password_confirmation': 'Different!123'}, {'confirm': ''}):
            gateway = PasswordGateway()
            with self.assertRaises(GatewayError):
                gateway.save_wifi_password({**gateway.body(), **changes})
            self.assertEqual(gateway.writes, [])

    def test_masked_member_disables_entire_group(self):
        gateway = PasswordGateway()
        gateway.keys[ROOT+'5'] = '************'
        self.assertTrue(all(not row['password_writable'] for row in gateway.wifi_security()))
        with self.assertRaises(GatewayError):
            gateway.save_wifi_password(gateway.body())
        self.assertEqual(gateway.writes, [])

    def test_derived_psk_is_checked_against_ssid(self):
        derived = hashlib.pbkdf2_hmac('sha1', NEW.encode(), b'Office', 4096, 32).hex()
        self.assertTrue(password_matches((derived,), NEW, 'Office'))
        self.assertFalse(password_matches((derived,), NEW, 'Other'))
