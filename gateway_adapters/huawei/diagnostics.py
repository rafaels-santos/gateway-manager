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
        paths.update(getattr(self,'discovered_log_paths',{}))
        # Read the same page as Maintenance > User Log; never change logging settings.
        try:
            page = self.request(paths[source], referer='/index.asp', max_redirects=0)
        except GatewayError as error:
            # Firmware families expose User Log under different fixed folders.
            # Never use a fallback to circumvent a permission/session denial.
            if source != 'user' or '(HTTP 404)' not in str(error): raise
            from .log_discovery import discover_log_paths
            discovered=discover_log_paths(self)
            self.discovered_log_paths=discovered
            alternate=discovered.get('user')
            if not alternate or alternate==paths[source]:
                raise GatewayError('User Log indisponível nesta sessão (HTTP 404). Confirme o acesso com Epadmin; o firmware pode ocultar a página para outros perfis.') from error
            page = self.request(alternate, referer='/index.asp', max_redirects=0)
        return parse_logs_page(page, source)
