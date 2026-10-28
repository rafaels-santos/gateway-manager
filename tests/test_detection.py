import unittest
from unittest.mock import patch
import app


class DetectionTests(unittest.TestCase):
    def test_public_huawei_title_and_escaped_firmware(self):
        identity=app.parse_gateway_identity(r'''<title>EG8145X6-10</title><script>var SWVersion='V5R024C10S106';var HWVersion='343D\x2eD';</script>''')
        self.assertEqual(identity['adapter_id'],app.Gateway.model_id)
        self.assertTrue(identity['supported'])
        self.assertEqual(identity['firmware'],'V5R024C10S106')
        self.assertEqual(identity['hardware'],'343D.D')

    def test_missing_version_is_not_guessed(self):
        identity=app.parse_gateway_identity('<title>EG8145X6-10</title>Login')
        self.assertTrue(identity['detected'])
        self.assertIsNone(identity['firmware'])

    def test_unrelated_text_does_not_select_supported_adapter(self):
        identity=app.parse_gateway_identity('<title>Login</title>Help: supports EG8145X6-10')
        self.assertFalse(identity['detected']);self.assertFalse(identity['supported'])
        identity=app.parse_gateway_identity("var ProductClass='HG8145V5';var SoftwareVersion='V1.2.3';")
        self.assertEqual(identity['model'],'HG8145V5')
        self.assertFalse(identity['supported'])
        self.assertIsNone(identity['adapter_id'])

    def test_probe_is_get_only_without_login_and_private_ip_required(self):
        with patch.object(app.Gateway,'request',return_value='<title>EG8145X6-10</title>') as request,patch.object(app.Gateway,'login') as login:
            self.assertTrue(app.detect_gateway('192.168.100.254')['supported'])
            request.assert_called_once_with('/',timeout=5,max_redirects=1)
            login.assert_not_called()
        for address in ('8.8.8.8','127.0.0.1','http://192.168.1.1@evil.example','http://192.168.1.1/path'):
            with self.assertRaises(app.GatewayError):app.detect_gateway(address)

    def test_authenticated_header_version_and_unavailable_logs(self):
        gateway=app.Gateway('192.168.100.254')
        with patch.object(gateway,'logs',return_value={'raw':'Manufacturer:Huawei;\nProductClass:EG8145X6-10;\nSWVer:V5R024C10S106;\nHWVer:343D.D;'}):
            self.assertEqual(app.session_identity(gateway),{'firmware':'V5R024C10S106','hardware':'343D.D'})
        with patch.object(gateway,'logs',side_effect=app.GatewayError('Sem permissão')):
            self.assertIsNone(app.session_identity(gateway)['firmware'])


if __name__=='__main__':unittest.main()
