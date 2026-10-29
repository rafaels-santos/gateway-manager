import unittest
from unittest.mock import patch
from gateway_adapters.huawei import Gateway
from gateway_adapters.errors import GatewayError


class LogSourceTests(unittest.TestCase):
    def test_missing_user_log_folder_uses_fixed_alternate_get(self):
        gateway=Gateway('192.168.100.254')
        page="document.getElementById('logarea').value = 'SWVer:V5R024C10S106;HWVer:343D.D;';"
        with patch.object(gateway,'request',side_effect=[GatewayError('Gateway recusou consulta (HTTP 404).'),'',page]) as request:
            self.assertIn('SWVer:',gateway.logs()['raw'])
            self.assertEqual(request.call_args_list[-1].args,('/html/ssmp/logview/logview.asp',))
            self.assertTrue(all(len(call.args)==1 for call in request.call_args_list))

    def test_permission_denial_does_not_try_another_folder(self):
        gateway=Gateway('192.168.100.254')
        with patch.object(gateway,'request',side_effect=GatewayError('HTTP 403')) as request:
            with self.assertRaises(GatewayError):gateway.logs()
            self.assertEqual(request.call_count,1)

    def test_discovered_native_menu_path_is_used_and_cached(self):
        gateway=Gateway('192.168.100.254')
        page="document.getElementById('logarea').value = 'entry';"
        menu='var item="html/ssmp/userlog/userlogview.asp";'
        with patch.object(gateway,'request',side_effect=[GatewayError('(HTTP 404)'),menu,page,page]) as request:
            self.assertEqual(gateway.logs()['raw'],'entry')
            self.assertEqual(gateway.logs()['raw'],'entry')
            self.assertEqual(request.call_args.args,('/html/ssmp/userlog/userlogview.asp',))

    def test_only_read_only_local_menu_links_are_accepted(self):
        from gateway_adapters.huawei.log_discovery import log_links
        self.assertEqual(log_links('<a href="html/ssmp/userlog/userlogview.asp">User Log</a>'),{'user':'/html/ssmp/userlog/userlogview.asp'})
        self.assertEqual(log_links(r'"html\x2fssmp\x2fuserlog\x2fuserlogview.asp"'),{'user':'/html/ssmp/userlog/userlogview.asp'})
        for href in ('https://other.example/html/ssmp/userlog/log.asp','//other.example/html/ssmp/userlog/log.asp','html/ssmp/userlog/deletelog.asp','html/ssmp/userlog/log.asp?apply=1','html/ssmp/debug/log.asp'):
            self.assertEqual(log_links('<a href="'+href+'">Log</a>'),{})

    def test_only_observed_menu_scripts_are_followed_using_document_base(self):
        from gateway_adapters.huawei.log_discovery import discover_log_paths
        gateway=Gateway('192.168.100.254')
        source='<script src="/Cusjs/InitMenu.js?v=1"></script><script src="https://external.example/menu.js"></script>'
        with patch.object(gateway,'request',side_effect=[source,'var url="html/ssmp/userlog/userlogview.asp";']) as request:
            self.assertEqual(discover_log_paths(gateway),{'user':'/html/ssmp/userlog/userlogview.asp'})
            self.assertEqual(request.call_args.args,('/Cusjs/InitMenu.js?v=1',))

    def test_menu_permission_failure_does_not_trigger_another_log_path(self):
        gateway=Gateway('192.168.100.254')
        with patch.object(gateway,'request',side_effect=[GatewayError('(HTTP 404)'),GatewayError('(HTTP 403)')]) as request:
            with self.assertRaisesRegex(GatewayError,'403'):gateway.logs()
            self.assertEqual(request.call_count,2)
