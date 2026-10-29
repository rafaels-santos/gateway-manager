from ..errors import GatewayError
from ..parsers import parse_devices_page
from .constants import SSID_MAP


class HuaweiClientOperations:
    def devices(self):
        page = self.request('/html/bbsp/common/GetLanUserDevInfo.asp')
        if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
            if not self.credentials:
                raise GatewayError('Não foi possível ler os dispositivos; a sessão pode ter expirado.')
            self.login(*self.credentials)
            page = self.request('/html/bbsp/common/GetLanUserDevInfo.asp')
            if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
                raise GatewayError('Não foi possível ler os dispositivos após reconectar ao gateway.')
        return parse_devices_page(page, SSID_MAP)
