import unittest
from unittest.mock import patch

from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei import Gateway
from gateway_adapters.huawei.radio_options import options_for, preview_radio


IDENTITY = {'hardware': '343D.D', 'firmware': 'V5R024C10S106'}
RADIO = {'id': 'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5',
         'country': 'BR', 'standard': '11ax', 'band': '5 GHz', 'expected': 'snapshot'}


class RadioOptionsTests(unittest.TestCase):
    def test_two_ghz_only_offers_observed_widths_and_channels(self):
        choices = options_for(IDENTITY, True, {**RADIO, 'id': RADIO['id'][:-1]+'1'})
        self.assertEqual([row['value'] for row in choices], ['0', '1', '2'])
        self.assertTrue(all([c['value'] for c in row['channels']] == [str(n) for n in range(14)] for row in choices))

    def test_five_ghz_channel_165_only_for_twenty_mhz(self):
        choices = options_for(IDENTITY, True, RADIO)
        self.assertEqual(len(choices), 5)
        for row in choices:
            channels = [c['value'] for c in row['channels']]
            self.assertEqual('165' in channels, row['value'] == '1')
            self.assertIn('-1', channels)
            self.assertIn('0', channels)

    def test_unknown_profile_cannot_reuse_regulatory_choices(self):
        for identity, supported, radio in (({}, True, RADIO), ({**IDENTITY, 'firmware': 'other'}, True, RADIO),
                (IDENTITY, False, RADIO), (IDENTITY, True, {**RADIO, 'country': 'US'}),
                (IDENTITY, True, {**RADIO, 'standard': '11ac'})):
            self.assertEqual(options_for(identity, supported, radio), [])

    def test_invalid_combination_and_stale_snapshot_are_rejected(self):
        target = {**RADIO, 'channel_options': options_for(IDENTITY, True, RADIO)}
        for body in ({'width_code': '4', 'channel': '165', 'expected': 'snapshot'},
                     {'width_code': '1', 'channel': '165', 'expected': 'old'},
                     {'width_code': '999', 'channel': '36', 'expected': 'snapshot'}):
            with self.assertRaises(GatewayError): preview_radio(target, body)

    def test_preview_never_calls_write_and_never_advertises_apply(self):
        gateway = Gateway('192.168.100.254')
        target = {**RADIO, 'channel_options': options_for(IDENTITY, True, RADIO)}
        with patch.object(gateway, 'radio_config', return_value=[target]), patch.object(gateway, 'request') as request:
            result = gateway.preview_radio_change({'id': RADIO['id'], 'expected': 'snapshot', 'width_code': '1', 'channel': '165'})
            self.assertFalse(result['apply_available'])
            request.assert_not_called()

    def test_channel_fields_cannot_be_smuggled_into_power_write(self):
        gateway = Gateway('192.168.100.254')
        with patch.object(gateway, 'radio_config',return_value=[]), patch.object(gateway, 'request') as request:
            with self.assertRaisesRegex(GatewayError, 'Contrato de rádio'):
                gateway.save_radio({'confirm': 'WIFI', 'power': '80', 'channel': '36'})
            request.assert_not_called()
