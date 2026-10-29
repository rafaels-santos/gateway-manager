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
            self.assertTrue(app.detect_gateway('192.168.50.254')['supported'])
            request.assert_called_once_with('/',timeout=5,max_redirects=1)
            login.assert_not_called()
        for address in ('8.8.8.8','127.0.0.1','http://192.168.1.1@evil.example','http://192.168.1.1/path'):
            with self.assertRaises(app.GatewayError):app.detect_gateway(address)

    def test_authenticated_header_version_and_unavailable_logs(self):
        gateway=app.Gateway('192.168.50.254')
        with patch.object(gateway,'logs',return_value={'raw':'Manufacturer:Huawei;\nProductClass:EG8145X6-10;\nSWVer:V5R024C10S106;\nHWVer:343D.D;'}):
            self.assertEqual(app.session_identity(gateway),{'firmware':'V5R024C10S106','hardware':'343D.D'})
        with patch.object(gateway,'logs',side_effect=app.GatewayError('Sem permissão')),patch.object(gateway,'request',side_effect=app.GatewayError('Sem leitura')):
            self.assertIsNone(app.session_identity(gateway)['firmware'])

    def test_authenticated_semicolon_header_and_event_text_are_distinct(self):
        gateway=app.Gateway('192.168.50.254')
        with patch.object(gateway,'logs',return_value={'raw':'\ufeffManufacturer:Huawei;ProductClass:EG8145X6-10; HWVer:343D.D; SWVer:V5R024C10S106;\n2026-10-29 10:00:00 [Info][Config-Log] name;SWVer:FAKE;'}):
            self.assertEqual(app.session_identity(gateway),{'firmware':'V5R024C10S106','hardware':'343D.D'})
        with patch.object(gateway,'logs',return_value={'raw':'2026-10-29 10:00:00 [Info][Config-Log] name;SWVer:FAKE;HWVer:FAKE;'}),patch.object(gateway,'request',side_effect=app.GatewayError('Sem leitura')):
            self.assertEqual(app.session_identity(gateway),{'firmware':None,'hardware':None})

    def test_device_information_fallback_uses_explicit_fields_without_returning_serial(self):
        gateway=app.Gateway('192.168.50.254')
        page='function stDevInfo(domain,HWVer,SWVer,SerialNumber){} new stDevInfo("InternetGatewayDevice.DeviceInfo","343D.D","V5R024C10S106","SECRET_SERIAL");'
        with patch.object(gateway,'logs',side_effect=app.GatewayError('HTTP 404')),patch.object(gateway,'request',return_value=page) as request:
            result=app.session_identity(gateway)
            self.assertEqual(result,{'hardware':'343D.D','firmware':'V5R024C10S106'})
            self.assertNotIn('SECRET_SERIAL',str(result))
            request.assert_called_once_with('/html/ssmp/deviceinfo/deviceinfo.asp',max_redirects=0)


if __name__=='__main__':unittest.main()
