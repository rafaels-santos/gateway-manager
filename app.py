import base64
import html
import http.cookiejar
import http.client
import ipaddress
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import notifications

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
SESSIONS = {}
LOCK = threading.Lock()
MONITORS = {}
MONITOR_LOCKS = {}
PATH = '/html/bbsp/dhcpstatic/dhcpstatic.asp'
DHCP_PATH = '/html/bbsp/dhcpservercfg/dhcp2.asp'
WIFI_PATH = '/html/amp/wlanbasic/WlanBasic.asp'
LAN_DOMAIN = 'InternetGatewayDevice.LANDevice.1.LANHostConfigManagement'
DOMAIN = 'InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress'
DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))
# Observed on this gateway; override if the SSID assignments change.
SSID_MAP = {'SSID1': '2,4 GHz', 'SSID2': '2,4 GHz · Convidados', 'SSID5': '5 GHz'}

@contextmanager
def labels():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / 'labels.db')
    db.execute('CREATE TABLE IF NOT EXISTS labels (gateway TEXT, mac TEXT, name TEXT, PRIMARY KEY (gateway, mac))')
    db.execute('CREATE TABLE IF NOT EXISTS webhook_config (gateway TEXT PRIMARY KEY, url TEXT NOT NULL, enabled INTEGER NOT NULL, baseline INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS seen_devices (gateway TEXT NOT NULL, mac TEXT NOT NULL, PRIMARY KEY (gateway, mac))')
    db.execute('CREATE TABLE IF NOT EXISTS app_origins (gateway TEXT PRIMARY KEY, origin TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS device_tags (gateway TEXT NOT NULL, mac TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (gateway, mac))')
    db.execute('CREATE TABLE IF NOT EXISTS webhook_options (gateway TEXT PRIMARY KEY, options TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS webhook_state (gateway TEXT, mac TEXT, state TEXT NOT NULL, PRIMARY KEY(gateway,mac))')
    notifications.schema(db)
    try:
        if os.name != 'nt': os.chmod(DATA_DIR / 'labels.db', 0o600)
        with db:
            yield db
    finally:
        db.close()

class GatewayError(ValueError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def parse_constructors(page, name):
    result = []
    for raw in re.findall(r'new\s+' + re.escape(name) + r'\s*\(([^)]*)\)', page):
        raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), raw)
        try: result.append(json.loads('[' + raw + ']'))
        except (ValueError, TypeError): raise GatewayError('Formato de configuração do gateway não reconhecido.')
    return result

class Gateway:
    model_id = 'huawei-eg8145x6-10'
    model_label = 'Huawei EG8145X6-10'
    detection_models = ['EG8145X6-10']
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
                if urllib.parse.urlsplit(path).path == '/login.cgi':
                    print('Diagnóstico HTTP: etapa=/login.cgi; status=%s; cookies=%s; Set-Cookie=%s' % (response.status, ','.join(c.name for c in self.cookies) or 'nenhum', bool(response.headers.get_all('Set-Cookie'))), flush=True)
                return response.read(2_000_000).decode('utf-8-sig', errors='replace')
        except urllib.error.HTTPError as e:
            if urllib.parse.urlsplit(path).path in ('/login.cgi', '/index.asp'):
                location = urllib.parse.urlsplit(e.headers.get('Location', '')).path or 'nenhum'
                print('Diagnóstico HTTP: etapa=%s; status=%s; destino=%s; cookies=%s; Set-Cookie=%s' % (urllib.parse.urlsplit(path).path, e.code, location, ','.join(c.name for c in self.cookies) or 'nenhum', bool(e.headers.get_all('Set-Cookie'))), flush=True)
            if e.code in (301, 302, 303) and e.headers.get('Location', '').startswith('/') and not e.headers.get('Location', '').startswith('//'):
                if max_redirects<=0: raise GatewayError('O gateway excedeu o limite de redirecionamentos.')
                return self.request(e.headers['Location'],timeout=timeout,max_redirects=max_redirects-1)
            stage = {'/': 'página inicial', '/asp/GetRandCount.asp': 'token de login', '/login.cgi': 'autenticação', '/index.asp': 'verificação da sessão', PATH: 'leitura das reservas', '/html/ssmp/common/GetRandToken.asp': 'token de configuração'}.get(urllib.parse.urlsplit(path).path, 'operação de reserva')
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
            result = self.request('/login.cgi', {'UserName': user, 'PassWord': base64.b64encode(password.encode()).decode(), 'Language': 'english', 'x.X_HW_Token': token})
            # Emit structural markers only: never print response text, tokens or credentials.
            markers = ('document.cookie', 'location', 'window.name', 'Set-Cookie', 'login', 'error', 'fail', 'script', 'iframe', 'refresh', 'redirect', 'waiting', 'pagename', 'index.asp', 'login.asp')
            destinations = re.findall(r"(?:pageName|location(?:\.href)?)\s*=\s*['\"](/(?:index\.asp|login\.asp)?)['\"]", result, re.I)
            print('Diagnóstico da resposta: tamanho=%d; marcadores=%s; destino=%s' % (len(result), ','.join(m for m in markers if m.lower() in result.lower()) or 'nenhum', ','.join(destinations) or 'nenhum'), flush=True)
            fail = re.search(r"(?:var\s+)?FailStat\s*=\s*['\"](\d+)['\"]", result)
            print('Diagnóstico de login: página de login=%s; FailStat=%s; cookies=%s' % ('txt_Password' in result, fail.group(1) if fail else 'ausente', ','.join(c.name for c in self.cookies) or 'nenhum'), flush=True)
            page = self.request('/index.asp')
            if not re.search(r'logout', page, re.I):
                raise GatewayError('Login não confirmado. Verifique usuário, senha e permissões.')
            self.credentials = (user, password)

    def devices(self):
        page = self.request('/html/bbsp/common/GetLanUserDevInfo.asp')
        if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
            if not self.credentials:
                raise GatewayError('Não foi possível ler os dispositivos; a sessão pode ter expirado.')
            self.login(*self.credentials)
            page = self.request('/html/bbsp/common/GetLanUserDevInfo.asp')
            if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
                raise GatewayError('Não foi possível ler os dispositivos após reconectar ao gateway.')
        found = {}
        for match in re.finditer(r'new\s+USERDevice\s*\(([^)]*)\)', page):
            raw = match.group(1)
            # The firmware emits JavaScript \xHH escapes, which JSON does not accept.
            raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), raw)
            try:
                fields = json.loads('[' + raw + ']')
            except (ValueError, TypeError):
                raise GatewayError('O formato de dispositivos do gateway não foi reconhecido.')
            if len(fields) < 14:
                raise GatewayError('O gateway retornou uma lista de dispositivos incompleta.')
            domain, ip, mac, port, ip_type, _, status, kind, duration, hostname = fields[:10]
            mac = mac.lower()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                continue
            if kind.upper() not in ('ETH', 'WIFI', 'ONU'):
                continue
            device = {'id': domain, 'ip': ip, 'mac': mac, 'port': port,
                             'status': status.lower(), 'type': 'wifi' if kind.upper() == 'WIFI' else 'lan',
                             'hostname': hostname, 'gateway_name': fields[13],
                             'duration': duration, 'ip_type': ip_type,
                             'ipv4_enabled': fields[10], 'ipv6_enabled': fields[11],
                             'network': SSID_MAP.get(port.upper(), 'Wi-Fi · rede não identificada') if kind.upper() == 'WIFI' else 'LAN'}
            previous = found.get(mac)
            if not previous or (device['status'] == 'online' and previous['status'] != 'online'):
                found[mac] = device
        return list(found.values())

    def reservations_page(self):
        page = self.request(PATH)
        if 'DHCPStaticAddress' not in page or 'onttoken' not in page:
            raise GatewayError('Sessão expirada ou tela de reservas indisponível para esta conta.')
        return page

    def dhcp_config(self):
        page = self.request(DHCP_PATH)
        pools, interfaces = parse_constructors(page, 'dhcpmainst'), parse_constructors(page, 'stipaddr')
        if not pools or len(pools[0]) < 20 or not interfaces or len(interfaces[0]) < 4 or 'onttoken' not in page:
            raise GatewayError('Configuração DHCP indisponível ou sessão expirada.')
        p, lan = pools[0], interfaces[0]
        dns = (p[16] or p[18]).split(',')
        return {'enabled': p[1] == '1', 'start': p[2], 'end': p[3], 'lease': p[4], 'dns_primary': dns[0], 'dns_secondary': dns[1] if len(dns)>1 else '', 'lan_ip': lan[2], 'mask': lan[3]}

    def config_token(self):
        token = self.request('/html/ssmp/common/GetRandToken.asp', {}, xhr=True).strip()
        if not re.fullmatch(r'[a-zA-Z0-9]{16,256}', token): raise GatewayError('Token de operação indisponível; nenhuma alteração foi feita.')
        return token

    def save_dhcp(self, body, dns_only=False):
        with self.lock:
            current = self.dhcp_config()
            params = {}
            if dns_only:
                values = []
                for key in ('dns_primary', 'dns_secondary'):
                    value = str(body.get(key, '')).strip()
                    if value:
                        try: value = str(ipaddress.IPv4Address(value))
                        except ValueError: raise GatewayError('Informe endereços IPv4 válidos para DNS.')
                    values.append(value)
                if not values[0] and values[1]: raise GatewayError('Informe o DNS primário antes do secundário.')
                params['z.X_HW_DNSList'] = ','.join(v for v in values if v)
            else:
                if not isinstance(body.get('enabled'), bool): raise GatewayError('Estado DHCP inválido.')
                try:
                    start, end = (ipaddress.IPv4Address(body.get(k, '')) for k in ('start', 'end'))
                    net = ipaddress.IPv4Network((current['lan_ip'], current['mask']), strict=False)
                    lease = int(body.get('lease', ''))
                except (ValueError, TypeError): raise GatewayError('Informe intervalo e tempo de concessão válidos.')
                if start not in net or end not in net or start > end or start in (net.network_address, net.broadcast_address) or end in (net.network_address, net.broadcast_address) or start <= ipaddress.IPv4Address(current['lan_ip']) <= end or not 60 <= lease <= 31536000:
                    raise GatewayError('Intervalo DHCP inválido para a rede ou concessão fora de 60 a 31536000 segundos.')
                params.update({'z.DHCPServerEnable': int(body['enabled']), 'z.MinAddress': str(start), 'z.MaxAddress': str(end), 'z.DHCPLeaseTime': lease})
            params['x.X_HW_Token'] = self.config_token()
            url = '/set.cgi?' + urllib.parse.urlencode({'z': LAN_DOMAIN, 'RequestFile': DHCP_PATH.lstrip('/')})
            self.request(url, params, referer=DHCP_PATH)
            updated = self.dhcp_config()
            expected = {'dns_primary': values[0], 'dns_secondary': values[1]} if dns_only else {'enabled': body['enabled'], 'start': str(start), 'end': str(end), 'lease': str(lease)}
            if any(str(updated[k]) != str(v) for k,v in expected.items()):
                raise GatewayError('O gateway não confirmou os valores. Confira no painel Huawei antes de tentar novamente.')
            return updated

    def wifi_config(self):
        page = self.request(WIFI_PATH + '?2G')
        match = re.search(r'var\s+WlanArr\s*=\s*new\s+Array\((.*?)\s*,\s*null\s*\)', page, re.S)
        if not match: raise GatewayError('Configuração Wi-Fi indisponível ou sessão expirada.')
        rows = []
        for raw in re.findall(r'new\s+stWlan\s*\(([^)]*)\)', match.group(1)):
            fields = re.findall(r'"(?:\\.|[^"\\])*"', raw)[:6]
            if len(fields) != 6: raise GatewayError('Formato Wi-Fi não reconhecido.')
            fields = [re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), x) for x in fields]
            rows.append(json.loads('[' + ','.join(fields) + ']'))
        networks = []
        for fields in rows:
            if len(fields) < 6: continue
            domain, _, enabled, ssid, broadcast, maximum = fields[:6]
            match = re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.WLANConfiguration\.(\d+)', domain)
            if not match: continue
            n = int(match.group(1))
            networks.append({'id': domain, 'ssid': ssid, 'enabled': enabled == '1', 'broadcast': broadcast == '1', 'max_clients': maximum, 'network': SSID_MAP.get('SSID'+str(n), 'Rede não identificada')})
        if not networks or 'onttoken' not in page: raise GatewayError('Configuração Wi-Fi indisponível ou sessão expirada.')
        return networks

    def save_wifi(self, body):
        with self.lock:
            existing = self.wifi_config()
            target = next((n for n in existing if n['id'] == body.get('id')), None)
            if not target: raise GatewayError('Rede Wi-Fi não encontrada; atualize a lista.')
            ssid = str(body.get('ssid', '')).strip()
            if not ssid or len(ssid.encode('utf-8')) > 32 or any(ord(c) < 32 for c in ssid): raise GatewayError('Informe um nome Wi-Fi de até 32 bytes.')
            if any(n['ssid'] == ssid and n['id'] != target['id'] for n in existing): raise GatewayError('Já existe uma rede com esse nome.')
            if not isinstance(body.get('enabled'), bool) or not isinstance(body.get('broadcast'), bool): raise GatewayError('Estado da rede inválido.')
            params = {'y.SSID': ssid, 'y.Enable': int(body['enabled']), 'y.SSIDAdvertisementEnabled': int(body['broadcast']), 'x.X_HW_Token': self.config_token()}
            url = '/set.cgi?' + urllib.parse.urlencode({'y': target['id'], 'RequestFile': WIFI_PATH.lstrip('/')})
            self.request(url, params, referer=WIFI_PATH + '?2G')
            updated = next((n for n in self.wifi_config() if n['id'] == target['id']), None)
            if not updated or any(updated[k] != body[k] for k in ('ssid','enabled','broadcast')): raise GatewayError('O gateway não confirmou a rede. Confira no painel Huawei antes de tentar novamente.')
            return updated

    def reboot(self):
        with self.lock:
            token = self.config_token()
            url = '/set.cgi?' + urllib.parse.urlencode({'x': 'InternetGatewayDevice.X_HW_DEBUG.SMP.DM.ResetBoard', 'RequestFile': '../CustomApp/mainpage.asp'})
            self.request(url, {'x.X_HW_Token': token}, referer='/CustomApp/mainpage.asp')

    def block_policy(self):
        page = self.request('/html/bbsp/wlanmacfilter/wlanmacfilter.asp')
        def flag(name):
            match = re.search(r'var\s+' + name + r"\s*=\s*['\"]([01])['\"]", page)
            if not match: raise GatewayError('Política de bloqueio não reconhecida.')
            return match.group(1)
        if 'onttoken' not in page or flag('FilterBySsidFlag') != '0': raise GatewayError('Modo de filtragem não suportado por esta integração.')
        return {'enabled': flag('enableFilter') == '1', 'blacklist': flag('Mode') == '0', 'rules': parse_constructors(page, 'stMacFilter')}

    def block_client(self, body):
        with self.lock:
            mac = str(body.get('mac', '')).lower()
            if body.get('confirm') != 'BLOQUEAR': raise GatewayError('Confirmação de bloqueio inválida.')
            device = next((d for d in self.devices() if d['mac'] == mac), None)
            if not device or device['type'] != 'wifi' or not re.fullmatch(r'SSID[1-8]', device['port']): raise GatewayError('Bloqueio disponível apenas para clientes Wi-Fi com SSID identificado.')
            policy = self.block_policy()
            if not policy['blacklist']: raise GatewayError('O gateway usa lista de permissão; nenhuma alteração foi feita.')
            if not policy['enabled'] and policy['rules']: raise GatewayError('Há regras desativadas no gateway. Revise-as no Huawei antes de ativar o filtro.')
            if not policy['enabled'] and body.get('activate') is not True: raise GatewayError('Confirme a ativação do filtro Wi-Fi.')
            path = '/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            ssid = 'SSID-' + device['port'][4:]
            with labels() as db:
                saved = db.execute('SELECT name FROM labels WHERE gateway=? AND mac=?', (self.base, mac)).fetchone()
            device_name = (saved[0] if saved and saved[0].strip() else device.get('gateway_name') or device.get('hostname') or '')[:80]
            exists = any(len(r)>=4 and r[1]==ssid and r[3].lower()==mac for r in policy['rules'])
            if not exists:
                url = '/add.cgi?' + urllib.parse.urlencode({'x':'InternetGatewayDevice.X_HW_Security.WLANMacFilter','RequestFile':path.lstrip('/')})
                self.request(url, {'x.SourceMACAddress':mac,'x.SSIDName':ssid,'x.DeviceName':device_name,'x.Enable':'1','x.X_HW_Token':self.config_token()}, referer=path)
            if not policy['enabled']:
                url = '/set.cgi?' + urllib.parse.urlencode({'x':'InternetGatewayDevice.X_HW_Security','RequestFile':path.lstrip('/')})
                self.request(url, {'x.WlanMacFilterRight':'1','x.X_HW_Token':self.config_token()}, referer=path)
            updated = self.block_policy()
            if not updated['enabled'] or not updated['blacklist'] or not any(len(r)>=4 and r[1]==ssid and r[3].lower()==mac for r in updated['rules']): raise GatewayError('Bloqueio não confirmado. Confira o filtro no Huawei antes de tentar novamente.')

    def blocked_clients(self, devices):
        policy = self.block_policy()
        if not policy['blacklist']: return []
        by_mac = {d['mac']: d for d in devices}
        result = []
        for rule in policy['rules']:
            if len(rule)<4: raise GatewayError('Formato de regra de bloqueio não reconhecido.')
            domain, ssid, name, mac = rule[:4]
            mac = mac.lower()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac): continue
            port = ssid.replace('SSID-', 'SSID')
            device = dict(by_mac.get(mac, {'mac':mac,'ip':'','hostname':name,'gateway_name':'','duration':'','ip_type':'','ipv6_enabled':''}))
            device.update({'block_rule':domain,'block_active':policy['enabled'],'status':'blocked','type':'wifi','port':port,'network':SSID_MAP.get(port,'Wi-Fi · rede não identificada')})
            result.append(device)
        return result

    def sync_block_device_name(self, mac, name):
        with self.lock:
            rules = self.block_policy()['rules']
            targets = [r for r in rules if len(r)>=4 and r[3].lower()==mac and r[2]!=name]
            path = '/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            for rule in targets:
                if not re.fullmatch(r'InternetGatewayDevice\.X_HW_Security\.WLANMacFilter\.\d+', rule[0]):
                    raise GatewayError('Regra de bloqueio não reconhecida; nome não enviado.')
                url = '/set.cgi?' + urllib.parse.urlencode({'x':rule[0], 'RequestFile':path.lstrip('/')})
                self.request(url, {'x.DeviceName':name, 'x.X_HW_Token':self.config_token()}, referer=path)
            if targets:
                updated = {r[0]:r for r in self.block_policy()['rules'] if len(r)>=4}
                if any(r[0] not in updated or updated[r[0]][2]!=name for r in targets):
                    raise GatewayError('O Huawei não confirmou o Device Name da regra. Atualize antes de tentar novamente.')

    def unblock_client(self, body):
        with self.lock:
            domain = str(body.get('rule',''))
            mac = str(body.get('mac','')).lower()
            if body.get('confirm') != 'DESBLOQUEAR' or not re.fullmatch(r'InternetGatewayDevice\.X_HW_Security\.WLANMacFilter\.\d+', domain): raise GatewayError('Regra ou confirmação inválida.')
            rules = self.block_policy()['rules']
            if not any(len(r)>=4 and r[0]==domain and r[3].lower()==mac for r in rules): raise GatewayError('Regra não encontrada; atualize a lista.')
            path='/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            self.request('/del.cgi?'+urllib.parse.urlencode({'RequestFile':path.lstrip('/')}), {domain:'','x.X_HW_Token':self.config_token()}, referer=path)
            if any(r[0]==domain for r in self.block_policy()['rules']): raise GatewayError('A remoção não foi confirmada pelo Huawei; confira no painel antes de tentar novamente.')

    def logs(self, source='user'):
        paths={'user':'/html/ssmp/userlog/logview.asp','ap':'/html/ssmp/aplog/aplogview.asp'}
        if source not in paths: raise GatewayError('Origem de logs não suportada.')
        # Read the same page as Maintenance > User Log; never change logging settings.
        page = self.request(paths[source])
        match = re.search(r"document\.getElementById\([\"']logarea[\"']\)\.value\s*=\s*'((?:\\.|[^'\\])*)'", page)
        if source=='ap': match=re.search(r"var\s+ApLogInfoText\s*=\s*'((?:\\.|[^'\\])*)'",page)
        if not match:
            raise GatewayError('Logs indisponíveis. Verifique a sessão e a permissão de leitura no Huawei.')
        raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), match[1])
        raw = raw.replace(r'\r', '\r').replace(r'\n', '\n').replace(r"\'", "'").replace(r'\\', '\\')
        events = []
        levels = {'info':'INFO', 'informational':'INFO', 'notice':'INFO', 'debug':'INFO',
                  'warning':'WAR', 'warn':'WAR', 'error':'ERROR', 'critical':'ERROR',
                  'alert':'ERROR', 'emergency':'ERROR'}
        for line in raw.splitlines():
            event = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^]]+)\]\[([^]]+)\]\s*(.*)$', line)
            if event:
                stamp, level, category, message = event.groups()
                events.append({'time':stamp, 'level':levels.get(level.lower(), 'OTHER'),
                               'source_level':level, 'category':category, 'message':message})
            elif source=='ap' and line.strip():
                ap_event=re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^]]+)\]\s*(.*)$',line)
                if ap_event:
                    stamp,level,message=ap_event.groups()
                    events.append({'time':stamp,'level':levels.get(level.lower(),'OTHER'),'source_level':level,'category':'AP','message':message})
                elif events: events[-1]['message'] += '\n' + line
            elif events and line.strip():
                events[-1]['message'] += '\n' + line
        return {'events':list(reversed(events[-1000:])), 'total':len(events),
                'limited':len(events)>1000, 'source':source, 'raw':raw, 'categories':['Config-Log','Shell-Log','Alarm-Log'] if source=='user' else []}

    def reservations(self):
        page = self.reservations_page()
        # Firmware serializes reservations as constructors in JavaScript.
        rows = []
        pattern = r'new\s+stDhcp\s*\(\s*"(InternetGatewayDevice\.LANDevice\.1\.LANHostConfigManagement\.DHCPStaticAddress\.\d+)"\s*,\s*"([01])"\s*,\s*"([^"\n]*)"\s*,\s*"([^"\n]*)"'
        def decode(value):
            return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), value)
        for domain, enabled, raw_ip, raw_mac in re.findall(pattern, page, re.I):
            mac, ip = decode(raw_mac).lower(), decode(raw_ip)
            if re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                try:
                    ipaddress.IPv4Address(ip)
                except ValueError:
                    raise GatewayError('O gateway retornou um IP inválido.')
                rows.append({'id': domain, 'mac': mac, 'ip': ip, 'enabled': enabled == '1'})
        if not rows and re.search(r'DHCPStaticAddress\.\d+', page):
            raise GatewayError('Formato de reservas não reconhecido; nenhuma alteração foi feita.')
        return rows, page

    def save(self, body):
        with self.lock:
            try:
                ip = str(ipaddress.IPv4Address(body.get('ip', '')))
            except ValueError:
                raise GatewayError('Informe um IPv4 válido.')
            mac = str(body.get('mac', '')).lower().strip()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                raise GatewayError('Informe um MAC válido, por exemplo aa:bb:cc:dd:ee:ff.')
            rows, page = self.reservations()
            domain = body.get('id', '')
            if domain and domain not in [r['id'] for r in rows]:
                raise GatewayError('Reserva não encontrada; atualize a lista.')
            if any(r['id'] != domain and (r['ip'] == ip or r['mac'] == mac) for r in rows):
                raise GatewayError('Este IP ou MAC já está reservado.')
            token = self.request('/html/ssmp/common/GetRandToken.asp', {}, xhr=True).strip()
            if not re.fullmatch(r'[a-zA-Z0-9]{16,256}', token):
                raise GatewayError('Token de operação indisponível; nenhuma alteração foi feita.')
            action = 'set.cgi' if domain else 'add.cgi'
            target = domain or DOMAIN
            url = '/' + action + '?' + urllib.parse.urlencode({'x': target, 'RequestFile': PATH.lstrip('/')})
            self.request(url, {'x.Yiaddr': ip, 'x.Chaddr': mac, **({'x.Enable': '1'} if not domain else {}), 'x.X_HW_Token': token})
            updated, _ = self.reservations()
            if not any(r['ip'] == ip and r['mac'] == mac for r in updated):
                raise GatewayError('O gateway não confirmou a reserva. Verifique a interface original antes de tentar novamente.')

EVENTS = {
    'connected': ('Novo dispositivo', 'Um novo dispositivo foi conectado ao roteador,\nNome: {name}\nIP: {ip}\nMAC: {mac}\n{link}', True),
    'disconnected': ('Dispositivo desconectado', 'Dispositivo desconectado.\nNome: {name}\nIP: {ip}\nMAC: {mac}\n{link}', False),
    'ip_changed': ('IP alterado', 'O IP do dispositivo mudou.\nNome: {name}\nIP anterior: {previous_ip}\nIP atual: {ip}\nMAC: {mac}\n{link}', False),
    'blocked_ip_changed': ('Cliente com regra de bloqueio mudou de IP', 'Cliente com regra de bloqueio mudou de IP.\nNome: {name}\nIP anterior: {previous_ip}\nIP atual: {ip}\nMAC: {mac}\nBloqueio ativo: {block_active}\n{link}', False),
    'blocked_disconnected': ('Cliente com regra de bloqueio desconectou', 'Cliente com regra de bloqueio desconectado.\nNome: {name}\nIP: {ip}\nMAC: {mac}\nBloqueio ativo: {block_active}\n{link}', False),
}

def webhook_options(db, gateway):
    row = db.execute('SELECT options FROM webhook_options WHERE gateway=?', (gateway,)).fetchone()
    options = json.loads(row[0]) if row else {}
    return {'provider':options.get('provider','discord'), 'events':{k:options.get('events',{}).get(k,{'enabled':v[2],'template':v[1]}) for k,v in EVENTS.items()}}

def validate_generic_webhook(url):
    try:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443): raise ValueError()
    except ValueError: raise GatewayError('Informe uma URL HTTPS válida, sem credenciais no endereço e na porta 443.')
    return url

def send_event(url, provider, event, template, device, name, origin, previous_ip='', block_active=False):
    values={'name':name or device.get('gateway_name') or device.get('hostname') or 'Dispositivo sem nome', 'ip':device.get('ip') or 'Não informado', 'mac':device['mac'].upper(), 'previous_ip':previous_ip, 'link':origin.rstrip('/')+'/?device='+urllib.parse.quote(device['mac'],safe='') if origin else '', 'block_active':'Sim' if block_active else 'Não', 'event':event}
    text=template
    for key,value in values.items(): text=text.replace('{'+key+'}',str(value))
    if provider=='discord': return send_discord(url, content_override=text)
    import socket, ssl
    parsed=urllib.parse.urlsplit(validate_generic_webhook(url))
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): raise GatewayError('Webhook genérico deve apontar para um endereço público.')
        payload=json.dumps({'event':event,'text':text,'device':values},ensure_ascii=False).encode('utf-8')
        conn=http.client.HTTPSConnection(parsed.hostname,timeout=10)
        conn.sock=ssl.create_default_context().wrap_socket(socket.create_connection((addresses[0][4][0],443),timeout=10),server_hostname=parsed.hostname)
        try:
            conn.request('POST',urllib.parse.urlunsplit(('', '', parsed.path or '/', parsed.query, '')),body=payload,headers={'Content-Type':'application/json'})
            response=conn.getresponse();response.read(65536)
            if not 200<=response.status<300: raise GatewayError('Webhook recusou a notificação (HTTP %s).'%response.status)
        finally: conn.close()
    except (OSError,http.client.HTTPException): raise GatewayError('Não foi possível enviar a notificação ao webhook.')

def validate_webhook(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname in ('discord.com', 'discordapp.com')
                 and not parsed.username and not parsed.password and parsed.port in (None, 443)
                 and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'/api/webhooks/[0-9]{15,22}/[A-Za-z0-9_-]{20,200}', parsed.path))
    except ValueError:
        valid = False
    if not valid:
        raise GatewayError('Informe uma URL HTTPS de webhook do Discord válida.')
    return url


def send_discord(url, device=None, name='', app_origin='', content_override=None):
    import http.client
    parsed = urllib.parse.urlsplit(validate_webhook(url))
    if device is None:
        content = 'Teste de notificação do Gateway Manager. O webhook está funcionando.'
    else:
        title = (name or device.get('gateway_name') or device.get('hostname') or 'Dispositivo sem nome')[:80]
        address = (device.get('ip') or 'Não informado')[:45]
        title = title.replace('\n', ' ').replace('\r', ' ')
        content = 'Um novo dispositivo foi conectado ao roteador,\nNome: %s\nIP: %s\nMAC: %s' % (title, address, device['mac'])
        if app_origin:
            content += '\nAbrir dispositivo: %s/?device=%s' % (app_origin.rstrip('/'), urllib.parse.quote(device['mac'], safe=''))
    if content_override is not None: content = content_override
    payload = json.dumps({'content': content, 'allowed_mentions': {'parse': []}}, ensure_ascii=False).encode('utf-8')
    conn = http.client.HTTPSConnection(parsed.hostname, timeout=10)
    try:
        conn.request('POST', parsed.path + '?wait=true', body=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'GatewayManager/1.0'})
        response = conn.getresponse()
        response.read(65536)
        if not 200 <= response.status < 300:
            raise GatewayError('O Discord recusou a notificação (HTTP %d).' % response.status)
    except (OSError, http.client.HTTPException):
        raise GatewayError('Não foi possível enviar a notificação ao Discord.')
    finally:
        conn.close()


def validate_hook_url(provider,url):
    if provider=='discord': return validate_webhook(url)
    validate_generic_webhook(url)
    if provider=='slack':
        parsed=urllib.parse.urlsplit(url)
        if parsed.hostname!='hooks.slack.com' or parsed.query or not re.fullmatch(r'/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+',parsed.path): raise GatewayError('URL de incoming webhook Slack inválida.')
    return url

def post_hook_json(host,path,payload,headers=None):
    conn=http.client.HTTPSConnection(host,timeout=10)
    try:
        conn.request('POST',path,body=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json',**(headers or {})})
        response=conn.getresponse();raw=response.read(65536)
        if not 200<=response.status<300: raise GatewayError('Serviço recusou a notificação (HTTP %s).'%response.status)
        try: return json.loads(raw)
        except ValueError: return raw.decode('utf-8',errors='replace')
    except (OSError,http.client.HTTPException): raise GatewayError('Não foi possível conectar ao serviço de notificações.')
    finally: conn.close()

def deliver_hook(hook,event,template,device,name,origin,previous_ip='',block_active=False):
    provider=hook['provider'];config=hook['config']
    if provider in ('discord','generic'): return send_event(config['url'],provider,event,template,device,name,origin,previous_ip,block_active)
    values={'name':name or device.get('gateway_name') or device.get('hostname') or 'Dispositivo sem nome','ip':device.get('ip') or 'Não informado','mac':device['mac'].upper(),'previous_ip':previous_ip,'link':origin.rstrip('/')+'/?device='+urllib.parse.quote(device['mac'],safe='') if origin else '', 'block_active':'Sim' if block_active else 'Não','event':event}
    text=re.sub(r'\{(name|ip|mac|previous_ip|link|block_active|event)\}',lambda m:str(values[m[1]]),template)
    if provider=='telegram':
        response=post_hook_json('api.telegram.org','/bot'+config['token']+'/sendMessage',{'chat_id':config['chat_id'],'text':text})
        if not isinstance(response,dict) or response.get('ok') is not True: raise GatewayError('Telegram não confirmou o envio. Confira token, chat e permissões do bot.')
    elif provider=='slack':
        response=post_hook_json('hooks.slack.com',urllib.parse.urlsplit(config['url']).path,{'text':text,'mrkdwn':False})
        if response!='ok': raise GatewayError('Slack não confirmou o envio.')
    elif provider=='whatsapp':
        payload={'messaging_product':'whatsapp','to':config['recipient'],'type':'template','template':{'name':config['template'],'language':{'code':config['language']},'components':[{'type':'body','parameters':[{'type':'text','text':' '.join(text.split())[:900]}]}]}}
        response=post_hook_json('graph.facebook.com','/'+config['version']+'/'+config['phone_id']+'/messages',payload,{'Authorization':'Bearer '+config['token']})
        if not isinstance(response,dict) or not response.get('messages'): raise GatewayError('WhatsApp não confirmou o envio. Confira o template aprovado e o destinatário.')

def hook_service():
    return notifications.Service(labels,EVENTS,validate_hook_url,deliver_hook)

def monitor_once(gw):
    service=hook_service(); rows=service.rows(gw.base)
    active=[json.loads(row[1]) for row in rows if json.loads(row[1])['enabled']]
    if not active: return 'Notificações desativadas.'
    with gw.lock:
        devices=gw.devices()
        needs_block=any(h['events'][key]['enabled'] for h in active for key in ('blocked_ip_changed','blocked_disconnected'))
        blocked={d['mac']:d for d in gw.blocked_clients(devices)} if needs_block else {}
    with labels() as db:
        names=dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?',(gw.base,)))
        origin=db.execute('SELECT origin FROM app_origins WHERE gateway=?',(gw.base,)).fetchone()
    return service.observe(gw.base,devices,blocked,names,origin[0] if origin else '')


def start_monitor(gw):
    with LOCK:
        old = MONITORS.get(gw.base)
        if old: old['stop'].set()
        serial = MONITOR_LOCKS.setdefault(gw.base, threading.Lock())
        entry = {'stop': threading.Event(), 'wake': threading.Event(), 'status': 'Aguardando primeira verificação.', 'gateway': gw}
        MONITORS[gw.base] = entry
    def worker():
        while not entry['stop'].is_set():
            try:
                with serial:
                    if entry['stop'].is_set(): break
                    entry['status'] = monitor_once(gw)
            except GatewayError as e:
                entry['status'] = str(e)
            except Exception:
                entry['status'] = 'Falha ao monitorar. Verifique a sessão e tente novamente.'
            entry['wake'].wait(30)
            entry['wake'].clear()
    threading.Thread(target=worker, daemon=True, name='gateway-monitor').start()


def stop_monitor(gw):
    with LOCK:
        entry = MONITORS.get(gw.base)
        if entry and entry['gateway'] is gw:
            entry['stop'].set(); entry['wake'].set(); MONITORS.pop(gw.base, None)

def enrich_reservations(rows, devices, names):
    by_mac = {}
    for device in devices:
        mac = device.get('mac', '').lower()
        previous = by_mac.get(mac)
        if not previous or (device.get('status') == 'online' and previous.get('status') != 'online'):
            by_mac[mac] = device
    for row in rows:
        mac = row['mac'].lower()
        device = by_mac.get(mac, {})
        row['name'] = names.get(mac, '')
        row['hostname'] = device.get('hostname', '')
        row['gateway_name'] = device.get('gateway_name', '')
    return rows

def mark_fixed_addresses(devices, reservations):
    reserved = {(row['mac'].lower(), row['ip']) for row in reservations if row.get('enabled', True)}
    for device in devices:
        device['ip_fixed'] = (device['mac'].lower(), device['ip']) in reserved
        device['ip_static'] = device.get('ip_type', '').strip().lower() == 'static'
    return devices

# Register only adapters that have been implemented and validated.
def parse_gateway_identity(page):
    # Only use explicit identity fields or the page title, never a remembered IP/model mapping.
    page=html.unescape(re.sub(r'\\x([0-9a-fA-F]{2})',lambda m:chr(int(m[1],16)),page))
    def field(keys):
        match=re.search(r"(?:var\s+)?(?:"+keys+r")\s*[:=]\s*['\"]([^'\"\r\n]{1,100})['\"]",page,re.I)
        return match[1].strip() if match else None
    title=re.search(r'<title[^>]*>([^<]{1,120})</title>',page,re.I)
    model=field(r'ProductClass|ProductName|ModelName|ModelNumber|product_name|model_name')
    if model:
        found=re.search(r'\b((?:EG|HG|HS)\d{4}[A-Z0-9]*(?:-[A-Z0-9]+)?)\b',model,re.I)
        model=found[1].upper() if found else model
    elif title:
        found=re.search(r'\b((?:EG|HG|HS)\d{4}[A-Z0-9]*(?:-[A-Z0-9]+)?)\b',title[1],re.I)
        model=found[1].upper() if found else None
    firmware=field(r'SWVersion|SoftwareVersion|FirmwareVersion|SWVer|firmware_version|software_version')
    hardware=field(r'HWVersion|HardwareVersion|HWVer|hardware_version')
    text=re.sub(r'<[^>]+>',' ',page)
    if not firmware:
        found=re.search(r'\b(?:SWVer|Software Version|Firmware Version)\s*[:：]?\s*(V?\d[\w.-]{2,80})',text,re.I)
        if found: firmware=found[1]
    if not hardware:
        found=re.search(r'\b(?:HWVer|Hardware Version)\s*[:：]?\s*([A-Za-z0-9][\w.-]{1,80})',text,re.I)
        if found: hardware=found[1]
    adapter=next((key for key,cls in GATEWAY_ADAPTERS.items() if model and model.casefold() in [m.casefold() for m in getattr(cls,'detection_models',[])]),None)
    return {'detected':bool(model),'adapter_id':adapter,'supported':adapter is not None,'model':model,'firmware':firmware,'hardware':hardware}

def detect_gateway(address):
    # A fresh cookie jar and GET only: detection never signs in or reuses an admin session.
    probe=Gateway(address)
    result=parse_gateway_identity(probe.request('/',timeout=5,max_redirects=1))
    result['message']=('Modelo detectado e compatível.' if result['supported'] else 'Modelo detectado sem integração disponível.' if result['detected'] else 'Modelo não divulgado na página pública. Selecione manualmente.')
    return result

def session_identity(gateway):
    # This firmware exposes its software version in the User Log header after authentication.
    identity={'firmware':None,'hardware':None}
    try:
        header='\n'.join(gateway.logs()['raw'].splitlines()[:8])
        for key,label in [('firmware','SWVer'),('hardware','HWVer')]:
            match=re.search(r'^'+label+r':([^;\r\n]{1,100})',header,re.M)
            if match: identity[key]=match[1].strip()
    except GatewayError: pass
    gateway.identity=identity
    return identity

GATEWAY_ADAPTERS = {Gateway.model_id: Gateway}

def create_gateway(model_id, address):
    adapter = GATEWAY_ADAPTERS.get(model_id)
    if not adapter: raise GatewayError('Modelo de gateway não suportado. Selecione um modelo disponível.')
    return adapter(address)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log form data, gateway addresses, or credentials.
        print('HTTP request handled', flush=True)
    def send_json(self, status, obj, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store')
        if cookie is not None: self.send_header('Set-Cookie', 'session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=' + ('604800' if cookie else '0'))
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def session(self):
        from http.cookies import SimpleCookie
        c = SimpleCookie(); c.load(self.headers.get('Cookie', ''))
        with LOCK: s = SESSIONS.get(c['session'].value if 'session' in c else '')
        if not s: raise GatewayError('Conecte-se ao gateway novamente.')
        return s
    def do_GET(self):
        if self.path == '/api/gateway-types':
            self.send_json(200, {'models': [{'id': key, 'label': adapter.model_label} for key, adapter in GATEWAY_ADAPTERS.items()]})
            return
        if self.path == '/api/session':
            try:
                gw = self.session()
                with gw.lock: gw.devices()
                self.send_json(200, {'connected': True, 'model': gw.model_id, 'model_label': gw.model_label, **getattr(gw,'identity',{})})
            except GatewayError as e: self.send_json(401, {'error': str(e)})
            return
        if self.path == '/api/hooks':
            try:
                gw=self.session()
                with MONITOR_LOCKS.setdefault(gw.base,threading.Lock()): rows=hook_service().list(gw.base)
                with LOCK: entry=MONITORS.get(gw.base)
                self.send_json(200,{'hooks':rows,'providers':notifications.PROVIDERS,'event_labels':{k:v[0] for k,v in EVENTS.items()},'defaults':hook_service().defaults(),'status':entry['status'] if entry else 'Sessão sem monitoramento.'})
            except (GatewayError,ValueError) as e: self.send_json(400,{'error':str(e)})
            return
        if urllib.parse.urlsplit(self.path).path == '/api/logs':
            try:
                gw = self.session()
                source = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('source',['user'])[0]
                with gw.lock: result = gw.logs(source)
                self.send_json(200, result)
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        if self.path in ('/api/dhcp', '/api/wifi'):
            try:
                gw = self.session()
                with gw.lock: result = gw.dhcp_config() if self.path == '/api/dhcp' else gw.wifi_config()
                self.send_json(200, {'config': result})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/devices':
            try:
                gateway = self.session()
                with gateway.lock:
                    rows = gateway.devices()
                    try:
                        reservations, _ = gateway.reservations()
                        mark_fixed_addresses(rows, reservations)
                        reservations_available = True
                    except GatewayError:
                        for row in rows:
                            row['ip_fixed'] = False
                            row['ip_static'] = row.get('ip_type', '').strip().lower() == 'static'
                        reservations_available = False
                    try:
                        blocked = gateway.blocked_clients(rows)
                        blocked_available = True
                    except GatewayError:
                        blocked = []
                        blocked_available = False
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                    tags = dict(db.execute('SELECT mac,tag FROM device_tags WHERE gateway=?', (gateway.base,)))
                for row in rows + blocked:
                    row['name'] = saved.get(row['mac'], '')
                    row['tag'] = tags.get(row['mac'], '')
                self.send_json(200, {'devices': rows, 'blocked': blocked, 'blocked_available': blocked_available, 'reservations_available': reservations_available})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/reservations':
            try:
                gateway = self.session()
                with gateway.lock:
                    rows, _ = gateway.reservations()
                    try:
                        devices = gateway.devices()
                        names_unavailable = False
                    except GatewayError:
                        devices = []
                        names_unavailable = True
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                self.send_json(200, {'reservations': enrich_reservations(rows, devices, saved), 'device_names_unavailable': names_unavailable})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'application/javascript'), '/style.css': ('style.css', 'text/css'), '/icon.png': ('icon.png', 'image/png')}
        path = urllib.parse.urlsplit(self.path).path
        if path not in files: self.send_error(404); return
        name, mime = files[path]; data = (STATIC / name).read_bytes()
        self.send_response(200); self.send_header('Content-Type', mime if mime == 'image/png' else mime + '; charset=utf-8'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        try:
            origin = self.headers.get('Origin', '')
            if not origin or urllib.parse.urlsplit(origin).netloc != self.headers.get('Host') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise GatewayError('Origem inválida.')
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > (32768 if self.path=='/api/hooks' else 8192): raise GatewayError('Requisição inválida.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/detect':
                self.send_json(200,detect_gateway(str(body.get('address',''))))
            elif self.path == '/api/login':
                gw = create_gateway(body.get('model', Gateway.model_id), body.get('address', '')); gw.login(body.get('username', ''), body.get('password', ''))
                with gw.lock: identity=session_identity(gw)
                parsed_origin = urllib.parse.urlsplit(origin)
                if parsed_origin.scheme not in ('http', 'https') or not parsed_origin.hostname or parsed_origin.username or parsed_origin.password or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
                    raise GatewayError('Endereço do aplicativo inválido.')
                with labels() as db:
                    db.execute('INSERT INTO app_origins (gateway,origin) VALUES (?,?) ON CONFLICT(gateway) DO UPDATE SET origin=excluded.origin', (gw.base, origin))
                key = secrets.token_urlsafe(32)
                with LOCK: SESSIONS[key] = gw
                start_monitor(gw)
                self.send_json(200, {'ok': True, 'model': gw.model_id, 'model_label': gw.model_label, **identity}, key)
            elif self.path == '/api/block':
                self.session().block_client(body); self.send_json(200, {'ok': True})
            elif self.path == '/api/unblock':
                self.session().unblock_client(body); self.send_json(200, {'ok': True})
            elif self.path == '/api/reservation':
                self.session().save(body); self.send_json(200, {'ok': True})
            elif self.path in ('/api/dhcp', '/api/dns'):
                config = self.session().save_dhcp(body, dns_only=self.path == '/api/dns')
                self.send_json(200, {'config': config})
            elif self.path == '/api/wifi':
                config = self.session().save_wifi(body)
                self.send_json(200, {'config': config})
            elif self.path == '/api/reboot':
                if body.get('confirm') != 'REINICIAR': raise GatewayError('Confirmação de reinício inválida.')
                self.session().reboot(); self.send_json(200, {'ok': True})
            elif self.path == '/api/hooks':
                gw=self.session()
                with MONITOR_LOCKS.setdefault(gw.base,threading.Lock()): key=hook_service().save(gw.base,body)
                with LOCK: entry=MONITORS.get(gw.base)
                if entry: entry['wake'].set()
                self.send_json(200,{'ok':True,'id':key})
            elif self.path == '/api/hooks/test':
                gw=self.session()
                with MONITOR_LOCKS.setdefault(gw.base,threading.Lock()): hook_service().test(gw.base,str(body.get('id','')))
                self.send_json(200,{'ok':True})
            elif self.path == '/api/tag':
                gw = self.session()
                mac = str(body.get('mac', '')).lower().strip()
                tag = str(body.get('tag', '')).strip()
                if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or tag not in ('', 'IoT', 'Celulares', 'Computadores', 'Rede'):
                    raise GatewayError('Categoria ou MAC inválido.')
                with labels() as db:
                    if tag:
                        db.execute('INSERT INTO device_tags (gateway,mac,tag) VALUES (?,?,?) ON CONFLICT(gateway,mac) DO UPDATE SET tag=excluded.tag', (gw.base, mac, tag))
                    else:
                        db.execute('DELETE FROM device_tags WHERE gateway=? AND mac=?', (gw.base, mac))
                self.send_json(200, {'ok': True})
            elif self.path == '/api/name':
                gw = self.session()
                mac = str(body.get('mac', '')).lower().strip()
                name = str(body.get('name', '')).strip()
                if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or len(name) > 80 or any(ord(c)<32 for c in name):
                    raise GatewayError('Nome ou MAC inválido.')
                gw.sync_block_device_name(mac, name)
                with labels() as db:
                    db.execute('INSERT INTO labels (gateway,mac,name) VALUES (?,?,?) ON CONFLICT(gateway,mac) DO UPDATE SET name=excluded.name', (gw.base, mac, name))
                self.send_json(200, {'ok': True})
            elif self.path == '/api/logout':
                from http.cookies import SimpleCookie
                c = SimpleCookie(); c.load(self.headers.get('Cookie', ''))
                with LOCK: old = SESSIONS.pop(c['session'].value if 'session' in c else '', None)
                if old: stop_monitor(old)
                self.send_json(200, {'ok': True}, '')
            else: self.send_error(404)
        except (GatewayError, ValueError, TypeError, KeyError) as e: self.send_json(400, {'error': str(e)})

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
