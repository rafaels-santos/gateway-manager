import base64
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
    try:
        if os.name != 'nt': os.chmod(DATA_DIR / 'labels.db', 0o600)
        with db:
            yield db
    finally:
        db.close()

class GatewayError(Exception):
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

    def request(self, path, data=None, *, referer='/', xhr=False):
        payload = None if data is None else urllib.parse.urlencode(data).encode('utf-8')
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.base + referer, 'Accept': 'text/html,*/*'}
        if xhr:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        if data is not None:
            headers['Origin'] = self.base
        req = urllib.request.Request(self.base + path, data=payload, headers=headers)
        try:
            with self.opener.open(req, timeout=12) as response:
                if urllib.parse.urlsplit(path).path == '/login.cgi':
                    print('Diagnóstico HTTP: etapa=/login.cgi; status=%s; cookies=%s; Set-Cookie=%s' % (response.status, ','.join(c.name for c in self.cookies) or 'nenhum', bool(response.headers.get_all('Set-Cookie'))), flush=True)
                return response.read(2_000_000).decode('utf-8-sig', errors='replace')
        except urllib.error.HTTPError as e:
            if urllib.parse.urlsplit(path).path in ('/login.cgi', '/index.asp'):
                location = urllib.parse.urlsplit(e.headers.get('Location', '')).path or 'nenhum'
                print('Diagnóstico HTTP: etapa=%s; status=%s; destino=%s; cookies=%s; Set-Cookie=%s' % (urllib.parse.urlsplit(path).path, e.code, location, ','.join(c.name for c in self.cookies) or 'nenhum', bool(e.headers.get_all('Set-Cookie'))), flush=True)
            if e.code in (301, 302, 303) and e.headers.get('Location', '').startswith('/'):
                return self.request(e.headers['Location'])
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


def send_discord(url, device=None, name='', app_origin=''):
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


def monitor_once(gw):
    with labels() as db:
        config = db.execute('SELECT url, enabled, baseline FROM webhook_config WHERE gateway=?', (gw.base,)).fetchone()
    if not config or not config[1]: return 'Notificações desativadas.'
    with gw.lock: all_devices = gw.devices()
    devices = [d for d in all_devices if d['status'] == 'online']
    with labels() as db:
        seen = {row[0] for row in db.execute('SELECT mac FROM seen_devices WHERE gateway=?', (gw.base,))}
        if not config[2]:
            db.executemany('INSERT OR IGNORE INTO seen_devices (gateway, mac) VALUES (?,?)', ((gw.base, d['mac']) for d in all_devices))
            db.execute('UPDATE webhook_config SET baseline=1 WHERE gateway=?', (gw.base,))
            return 'Monitorando; dispositivos atuais registrados como referência.'
        names = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gw.base,)))
        origin_row = db.execute('SELECT origin FROM app_origins WHERE gateway=?', (gw.base,)).fetchone()
    pending = {d['mac']: d for d in devices if d['mac'] not in seen}
    for mac, device in pending.items():
        send_discord(config[0], device, names.get(mac, ''), origin_row[0] if origin_row else '')
        with labels() as db:
            db.execute('INSERT OR IGNORE INTO seen_devices (gateway,mac) VALUES (?,?)', (gw.base, mac))
    return 'Monitorando dispositivos a cada 30 segundos.'


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
    return devices

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
        if self.path == '/api/session':
            try:
                gw = self.session()
                with gw.lock: gw.devices()
                self.send_json(200, {'connected': True})
            except GatewayError as e: self.send_json(401, {'error': str(e)})
            return
        if self.path == '/api/webhook':
            try:
                gw = self.session()
                with labels() as db:
                    row = db.execute('SELECT enabled FROM webhook_config WHERE gateway=?', (gw.base,)).fetchone()
                with LOCK: entry = MONITORS.get(gw.base)
                self.send_json(200, {'configured': bool(row), 'enabled': bool(row and row[0]), 'status': entry['status'] if entry else 'Sessão sem monitoramento.'})
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
                        for row in rows: row['ip_fixed'] = False
                        reservations_available = False
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                for row in rows: row['name'] = saved.get(row['mac'], '')
                self.send_json(200, {'devices': rows, 'reservations_available': reservations_available})
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
            if length <= 0 or length > 8192: raise GatewayError('Requisição inválida.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/login':
                gw = Gateway(body.get('address', '')); gw.login(body.get('username', ''), body.get('password', ''))
                parsed_origin = urllib.parse.urlsplit(origin)
                if parsed_origin.scheme not in ('http', 'https') or not parsed_origin.hostname or parsed_origin.username or parsed_origin.password or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
                    raise GatewayError('Endereço do aplicativo inválido.')
                with labels() as db:
                    db.execute('INSERT INTO app_origins (gateway,origin) VALUES (?,?) ON CONFLICT(gateway) DO UPDATE SET origin=excluded.origin', (gw.base, origin))
                key = secrets.token_urlsafe(32)
                with LOCK: SESSIONS[key] = gw
                start_monitor(gw)
                self.send_json(200, {'ok': True}, key)
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
            elif self.path == '/api/webhook':
                gw = self.session()
                url = str(body.get('url', '')).strip()
                enabled = body.get('enabled') is True
                with labels() as db:
                    old = db.execute('SELECT url FROM webhook_config WHERE gateway=?', (gw.base,)).fetchone()
                    if url: validate_webhook(url)
                    elif old: url = old[0]
                    elif enabled: raise GatewayError('Informe a URL do webhook do Discord.')
                    else: raise GatewayError('Nenhum webhook configurado.')
                    db.execute('INSERT INTO webhook_config (gateway,url,enabled) VALUES (?,?,?) ON CONFLICT(gateway) DO UPDATE SET url=excluded.url,enabled=excluded.enabled', (gw.base, url, int(enabled)))
                with LOCK: entry = MONITORS.get(gw.base)
                if entry: entry['wake'].set()
                self.send_json(200, {'ok': True})
            elif self.path == '/api/webhook/test':
                gw = self.session()
                with labels() as db:
                    row = db.execute('SELECT url FROM webhook_config WHERE gateway=?', (gw.base,)).fetchone()
                if not row: raise GatewayError('Salve a URL do webhook antes de testar.')
                send_discord(row[0])
                self.send_json(200, {'ok': True})
            elif self.path == '/api/name':
                gw = self.session()
                mac = str(body.get('mac', '')).lower().strip()
                name = str(body.get('name', '')).strip()
                if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or len(name) > 80:
                    raise GatewayError('Nome ou MAC inválido.')
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
