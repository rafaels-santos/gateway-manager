import base64
import http.cookiejar
import http.client
import ipaddress
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from .errors import GatewayError
from .capabilities import new_session_capabilities


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GatewayTransport:
    label_store_factory = None

    @classmethod
    def set_label_store_factory(cls, factory):
        cls.label_store_factory = staticmethod(factory)

    def label_store_context(self):
        if self.label_store_factory is None:
            raise GatewayError('Armazenamento local indisponível nesta sessão.')
        return self.label_store_factory()

    def __init__(self, address):
        address = address.strip()
        if '://' not in address:
            address = 'http://' + address
        parsed = urllib.parse.urlsplit(address)
        try:
            ip = ipaddress.ip_address(parsed.hostname or '')
            port = parsed.port
        except ValueError:
            raise GatewayError('Informe um endereço IP válido do gateway.')
        if parsed.scheme not in ('http', 'https') or not ip.is_private or ip.is_loopback or ip.is_link_local or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise GatewayError('Informe o IP privado do gateway, opcionalmente com http:// ou https:// e porta.')
        self.base = '%s://%s%s' % (parsed.scheme, ('[' + str(ip) + ']') if ip.version == 6 else str(ip), ':' + str(port) if port else '')
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), NoRedirect())
        self.lock = threading.RLock()
        self.credentials = None
        self.capability_matrix = new_session_capabilities()
        self.dhcpv6_clients = []
        self.lan_port_statuses = {}
        self.network_pages = {}
        self.pending_lan_change = None
    def request(self, path, data=None, *, referer='/', xhr=False, timeout=12, max_redirects=3):
        payload = None if data is None else urllib.parse.urlencode(data).encode('utf-8')
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.base + referer, 'Accept': 'text/html,*/*'}
        if xhr:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        if data is not None:
            headers['Origin'] = self.base
        req = urllib.request.Request(self.base + path, data=payload, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.read(2_000_000).decode('utf-8-sig', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303) and e.headers.get('Location', '').startswith('/') and not e.headers.get('Location', '').startswith('//'):
                if max_redirects<=0: raise GatewayError('O gateway excedeu o limite de redirecionamentos.')
                return self.request(e.headers['Location'],timeout=timeout,max_redirects=max_redirects-1)
            stage = {'/': 'página inicial', '/asp/GetRandCount.asp': 'token de login', '/login.cgi': 'autenticação', '/index.asp': 'verificação da sessão', '/html/bbsp/dhcpstatic/dhcpstatic.asp': 'leitura das reservas', '/html/ssmp/common/GetRandToken.asp': 'token de configuração'}.get(urllib.parse.urlsplit(path).path, 'consulta de configuração' if data is None else 'alteração de configuração')
            raise GatewayError('Gateway recusou a etapa %s (HTTP %s).' % (stage, e.code))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GatewayError('Não foi possível acessar o gateway: %s' % e)
    def login(self, user, password):
        with self.lock:
            page = self.request('/')
            if 'EG8145X6' not in page:
                raise GatewayError('O gateway não foi identificado como Huawei EG8145X6.')
            # The gateway login page creates this language cookie before submitting.
            cookie = http.cookiejar.Cookie(version=0, name='Cookie', value='body:Language:english:id=-1', port=None, port_specified=False, domain=urllib.parse.urlsplit(self.base).hostname, domain_specified=False, domain_initial_dot=False, path='/', path_specified=True, secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False)
            self.cookies.set_cookie(cookie)
            token = self.request('/asp/GetRandCount.asp', {}, xhr=True).strip()
            if not token or len(token) > 256:
                raise GatewayError('O gateway não retornou um token de login válido.')
            self.request('/login.cgi', {'UserName': user, 'PassWord': base64.b64encode(password.encode()).decode(), 'Language': 'english', 'x.X_HW_Token': token})
            page = self.request('/index.asp')
            if not re.search(r'logout', page, re.I):
                raise GatewayError('Login não confirmado. Verifique usuário, senha e permissões.')
            self.credentials = (user, password)
    def config_token(self):
        token = self.request('/html/ssmp/common/GetRandToken.asp', {}, xhr=True).strip()
        if not re.fullmatch(r'[a-zA-Z0-9]{16,256}', token): raise GatewayError('Token de operação indisponível; nenhuma alteração foi feita.')
        return token
