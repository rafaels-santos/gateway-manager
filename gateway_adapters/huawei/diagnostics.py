import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_logs_page
from ..inspection import inspect_network_pages


class HuaweiDiagnostics:
    def inspect_network_pages(self, features=None):
        return inspect_network_pages(self, features)

    def reboot(self):
        with self.lock:
            token = self.config_token()
            url = '/set.cgi?' + urllib.parse.urlencode({'x': 'InternetGatewayDevice.X_HW_DEBUG.SMP.DM.ResetBoard', 'RequestFile': '../CustomApp/mainpage.asp'})
            self.request(url, {'x.X_HW_Token': token}, referer='/CustomApp/mainpage.asp')
    def logs(self, source='user'):
        paths={'user':'/html/ssmp/userlog/logview.asp','ap':'/html/ssmp/aplog/aplogview.asp'}
        if source not in paths: raise GatewayError('Origem de logs não suportada.')
        # Read the same page as Maintenance > User Log; never change logging settings.
        return parse_logs_page(self.request(paths[source]), source)
