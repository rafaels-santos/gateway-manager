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
DOMAIN = 'InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress'
DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))

@contextmanager
def labels():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / 'labels.db')
    db.execute('CREATE TABLE IF NOT EXISTS labels (gateway TEXT, mac TEXT, name TEXT, PRIMARY KEY (gateway, mac))')
    db.execute('CREATE TABLE IF NOT EXISTS webhook_config (gateway TEXT PRIMARY KEY, url TEXT NOT NULL, enabled INTEGER NOT NULL, baseline INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS seen_devices (gateway TEXT NOT NULL, mac TEXT NOT NULL, PRIMARY KEY (gateway, mac))')
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

    def devices(self):
        page = self.request('/html/bbsp/common/GetLanUserDevInfo.asp')
        if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
            raise GatewayError('Não foi possível ler os dispositivos; a sessão pode ter expirado.')
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
            domain, ip, mac, port, _, _, status, kind, _, hostname = fields[:10]
            mac = mac.lower()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                continue
            if kind.upper() not in ('ETH', 'WIFI', 'ONU'):
                continue
            found[domain] = {'id': domain, 'ip': ip, 'mac': mac, 'port': port,
                             'status': status.lower(), 'type': 'wifi' if kind.upper() == 'WIFI' else 'lan',
                             'hostname': hostname, 'gateway_name': fields[13]}
        return list(found.values())

    def reservations_page(self):
        page = self.request(PATH)
        if 'DHCPStaticAddress' not in page or 'onttoken' not in page:
            raise GatewayError('Sessão expirada ou tela de reservas indisponível para esta conta.')
        return page

    def reservations(self):
        page = self.reservations_page()
        # Firmware serializes reservations as constructors in JavaScript.
        rows = []
        pattern = r'new\s+stDhcp\s*\(\s*"(InternetGatewayDevice\.LANDevice\.1\.LANHostConfigManagement\.DHCPStaticAddress\.\d+)"\s*,\s*"[01]"\s*,\s*"([^"\n]*)"\s*,\s*"([^"\n]*)"'
        def decode(value):
            return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), value)
        for domain, raw_ip, raw_mac in re.findall(pattern, page, re.I):
            mac, ip = decode(raw_mac).lower(), decode(raw_ip)
            if re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                try:
                    ipaddress.IPv4Address(ip)
                except ValueError:
                    raise GatewayError('O gateway retornou um IP inválido.')
                rows.append({'id': domain, 'mac': mac, 'ip': ip})
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


def send_discord(url, device, name):
    import http.client
    parsed = urllib.parse.urlsplit(validate_webhook(url))
    title = (name or device.get('gateway_name') or device.get('hostname') or 'Dispositivo sem nome')[:80]
    address = (device.get('ip') or 'Não informado')[:45]
    port = (device.get('port') or 'Não informada')[:40]
    content = 'Novo dispositivo conectado\nNome: %s\nIP: %s\nMAC: %s\nConexão: %s' % (title, address, device['mac'], port)
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
    with gw.lock: devices = [d for d in gw.devices() if d['status'] == 'online']
    with labels() as db:
        seen = {row[0] for row in db.execute('SELECT mac FROM seen_devices WHERE gateway=?', (gw.base,))}
        if not config[2]:
            db.executemany('INSERT OR IGNORE INTO seen_devices (gateway, mac) VALUES (?,?)', ((gw.base, d['mac']) for d in devices))
            db.execute('UPDATE webhook_config SET baseline=1 WHERE gateway=?', (gw.base,))
            return 'Monitorando; dispositivos atuais registrados como referência.'
        names = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gw.base,)))
    pending = {d['mac']: d for d in devices if d['mac'] not in seen}
    for mac, device in pending.items():
        send_discord(config[0], device, names.get(mac, ''))
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

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log form data, gateway addresses, or credentials.
        print('HTTP request handled', flush=True)
    def send_json(self, status, obj, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store')
        if cookie is not None: self.send_header('Set-Cookie', 'session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def session(self):
        from http.cookies import SimpleCookie
        c = SimpleCookie(); c.load(self.headers.get('Cookie', ''))
        with LOCK: s = SESSIONS.get(c['session'].value if 'session' in c else '')
        if not s: raise GatewayError('Conecte-se ao gateway novamente.')
        return s
    def do_GET(self):
        if self.path == '/api/webhook':
            try:
                gw = self.session()
                with labels() as db:
                    row = db.execute('SELECT enabled FROM webhook_config WHERE gateway=?', (gw.base,)).fetchone()
                with LOCK: entry = MONITORS.get(gw.base)
                self.send_json(200, {'configured': bool(row), 'enabled': bool(row and row[0]), 'status': entry['status'] if entry else 'Sessão sem monitoramento.'})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/devices':
            try:
                gateway = self.session()
                with gateway.lock: rows = gateway.devices()
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                for row in rows: row['name'] = saved.get(row['mac'], '')
                self.send_json(200, {'devices': rows})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/reservations':
            try:
                gateway = self.session()
                with gateway.lock: rows, _ = gateway.reservations()
                
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                for row in rows: row['name'] = saved.get(row['mac'], '')
                self.send_json(200, {'reservations': rows})
            except GatewayError as e: self.send_json(400, {'error': str(e)})
            return
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'application/javascript'), '/style.css': ('style.css', 'text/css')}
        if self.path not in files: self.send_error(404); return
        name, mime = files[self.path]; data = (STATIC / name).read_bytes()
        self.send_response(200); self.send_header('Content-Type', mime + '; charset=utf-8'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
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
                key = secrets.token_urlsafe(32)
                with LOCK: SESSIONS[key] = gw
                start_monitor(gw)
                self.send_json(200, {'ok': True}, key)
            elif self.path == '/api/reservation':
                self.session().save(body); self.send_json(200, {'ok': True})
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
