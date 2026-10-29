import unittest
from unittest.mock import patch
from gateway_adapters.huawei import Gateway
from gateway_adapters.errors import GatewayError


class LogSourceTests(unittest.TestCase):
    def test_missing_user_log_folder_uses_fixed_alternate_get(self):
        gateway=Gateway('192.168.100.254')
        page="document.getElementById('logarea').value = 'SWVer:V5R024C10S106;HWVer:343D.D;';"
        with patch.object(gateway,'request',side_effect=[GatewayError('Gateway recusou consulta (HTTP 404).'),page]) as request:
            self.assertIn('SWVer:',gateway.logs()['raw'])
            self.assertEqual(request.call_args_list[-1].args,('/html/ssmp/logview/logview.asp',))
            self.assertTrue(all(len(call.args)==1 for call in request.call_args_list))

    def test_permission_denial_does_not_try_another_folder(self):
        gateway=Gateway('192.168.100.254')
        with patch.object(gateway,'request',side_effect=GatewayError('HTTP 403')) as request:
            with self.assertRaises(GatewayError):gateway.logs()
            self.assertEqual(request.call_count,1)
