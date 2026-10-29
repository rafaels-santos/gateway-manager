import datetime
import html
import http.cookiejar
import http.client
import ipaddress
import json
import re
import secrets
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
from services import notifications, storage, connection
from services import network_management

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
SESSIONS = {}
LOCK = threading.Lock()
MONITORS = {}
MONITOR_LOCKS = {}
PORTABLE_CONFIG_FORMAT = 'gateway-manager-network-config'
PORTABLE_CONFIG_VERSION = 1
DEVICE_TAGS = ('', 'IoT', 'Celulares', 'Computadores', 'Rede')
HUAWEI_ONT_PRODUCT_URL = 'https://e.huawei.com/en/products/optical-terminal/eg8145x6-10'
HUAWEI_SOFTWARE_URL = 'https://support.huawei.com/enterprise/en/software'
DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))

def labels():
    return storage.open_database(DATA_DIR)

from gateway_adapters.errors import GatewayError
from gateway_adapters.parsers import parse_constructors
from gateway_adapters.huawei import Gateway
from gateway_adapters.huawei.constants import DOMAIN
from gateway_adapters.capabilities import capability_snapshot, record_capability
from gateway_adapters.client_model import normalize_clients


def normalize_portable_config(value):
    """Validate and normalize the portable, LAN-only configuration format."""
    if not isinstance(value, dict) or value.get('format') != PORTABLE_CONFIG_FORMAT or value.get('version') != PORTABLE_CONFIG_VERSION:
        raise GatewayError('Arquivo incompatível. Selecione uma exportação do Gateway Manager versão 1.')
    devices, reservations = value.get('devices'), value.get('reservations')
    if not isinstance(devices, list) or not isinstance(reservations, list) or len(devices) > 2000 or len(reservations) > 1024:
        raise GatewayError('O arquivo precisa conter listas válidas de dispositivos e reservas.')
    clean_devices, clean_reservations = [], []
    seen_devices, seen_macs, seen_ips = set(), set(), set()
    for row in devices:
        if not isinstance(row, dict):
            raise GatewayError('Há um identificador de dispositivo inválido no arquivo.')
        mac = str(row.get('mac', '')).strip().lower()
        name = row.get('name', '')
        tag = row.get('tag', '')
        if (not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac)
                or int(mac[:2], 16) & 1 or mac == '00:00:00:00:00:00'
                or not isinstance(name, str) or len(name) > 80
                or any(ord(char) < 32 for char in name)
                or not isinstance(tag, str) or tag not in DEVICE_TAGS
                or (not name.strip() and not tag)):
            raise GatewayError('Há um MAC, nome ou categoria inválidos no arquivo.')
        if mac in seen_devices:
            raise GatewayError('O arquivo contém MACs repetidos nos identificadores.')
        seen_devices.add(mac)
        clean_devices.append({'mac': mac, 'name': name.strip(), 'tag': tag})
    for row in reservations:
        if not isinstance(row, dict):
            raise GatewayError('Há uma reserva inválida no arquivo.')
        mac = str(row.get('mac', '')).strip().lower()
        if (not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac)
                or int(mac[:2], 16) & 1 or mac == '00:00:00:00:00:00'
                or not isinstance(row.get('enabled', True), bool)):
            raise GatewayError('Há um MAC ou estado de reserva inválido no arquivo.')
        try:
            address = ipaddress.IPv4Address(row.get('ip', ''))
        except (ValueError, TypeError):
            raise GatewayError('Há um endereço IPv4 inválido no arquivo.')
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            raise GatewayError('O arquivo contém um IPv4 que não pode ser reservado.')
        ip = str(address)
        if mac in seen_macs or ip in seen_ips:
            raise GatewayError('O arquivo contém MAC ou IP repetido nas reservas.')
        seen_macs.add(mac); seen_ips.add(ip)
        clean_reservations.append({'mac': mac, 'ip': ip, 'enabled': row.get('enabled', True)})
    source = value.get('source') if isinstance(value.get('source'), dict) else {}
    source = {key: source[key][:120] for key in ('model', 'label') if isinstance(source.get(key), str)}
    exported_at = value.get('exported_at') if isinstance(value.get('exported_at'), str) else ''
    return {'format': PORTABLE_CONFIG_FORMAT, 'version': PORTABLE_CONFIG_VERSION,
            'exported_at': exported_at[:80], 'source': source,
            'devices': clean_devices, 'reservations': clean_reservations}


def export_portable_config(gateway):
    with labels() as db:
        saved = db.execute('SELECT mac,name FROM labels WHERE gateway=? ORDER BY mac', (gateway.base,)).fetchall()
        tags = dict(db.execute('SELECT mac,tag FROM device_tags WHERE gateway=?', (gateway.base,)))
    devices = [{'mac': mac, 'name': name or '', 'tag': tags.get(mac, '')}
               for mac, name in saved if (name or '').strip() or tags.get(mac, '')]
    reservations, _ = gateway.reservations()
    return normalize_portable_config({'format': PORTABLE_CONFIG_FORMAT, 'version': PORTABLE_CONFIG_VERSION,
            'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source': {'model': gateway.model_id, 'label': gateway.model_label},
            'devices': devices,
            'reservations': [{'mac': row['mac'], 'ip': row['ip'], 'enabled': row['enabled']} for row in reservations]})


def preview_portable_config(gateway, raw_config):
    config = normalize_portable_config(raw_config)
    rows, _ = gateway.reservations()
    current_by_mac = {row['mac']: row for row in rows}
    current_by_ip = {row['ip']: row for row in rows}
    current_devices = gateway.devices()
    dhcp = gateway.dhcp_config()
    network = ipaddress.IPv4Network((dhcp['lan_ip'], dhcp['mask']), strict=False)
    with labels() as db:
        existing_names = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
        existing_tags = dict(db.execute('SELECT mac,tag FROM device_tags WHERE gateway=?', (gateway.base,)))
    planned_devices = []
    for row in config['devices']:
        existing = row['mac'] in existing_names or row['mac'] in existing_tags
        planned_devices.append({**row, 'action': 'existente' if existing else 'importar',
                                'current_name': existing_names.get(row['mac'], ''),
                                'current_tag': existing_tags.get(row['mac'], '')})
    planned_reservations = []
    for row in config['reservations']:
        address = ipaddress.IPv4Address(row['ip'])
        current = current_by_mac.get(row['mac'])
        occupying = current_by_ip.get(row['ip'])
        live = next((device for device in current_devices if device.get('ip') == row['ip'] and device.get('mac') != row['mac'] and device.get('status') == 'online'), None)
        reason = ''
        action = 'importar'
        if address not in network or address in (network.network_address, network.broadcast_address) or address == ipaddress.IPv4Address(dhcp['lan_ip']):
            action, reason = 'conflito', 'O IP não pertence à rede LAN utilizável deste gateway.'
        elif occupying and occupying['mac'] != row['mac']:
            action, reason = 'conflito', 'Este IP já está reservado para outro MAC no gateway atual.'
        elif live:
            action, reason = 'conflito', 'Outro dispositivo está online usando este IP.'
        elif current and current['ip'] == row['ip'] and current['enabled'] == row['enabled']:
            action, reason = 'igual', 'A reserva já existe com os mesmos dados.'
        elif current:
            action, reason = 'substituir', 'Este MAC já tem outra reserva; a troca exige confirmação adicional.'
        planned_reservations.append({**row, 'action': action, 'reason': reason,
                                     'current_ip': current['ip'] if current else '',
                                     'current_enabled': current['enabled'] if current else None})
    return {'config': config, 'target': {'model': gateway.model_label, 'lan_ip': dhcp['lan_ip'], 'mask': dhcp['mask']},
            'devices': planned_devices, 'reservations': planned_reservations}


def apply_portable_config(gateway, raw_config, *, import_devices, import_reservations,
                          replace_names=False, replace_reservations=False):
    if not all(isinstance(value, bool) for value in (import_devices, import_reservations, replace_names, replace_reservations)):
        raise GatewayError('Opções de importação inválidas.')
    if not import_devices and not import_reservations:
        raise GatewayError('Selecione identificadores, reservas ou ambos para importar.')
    preview = preview_portable_config(gateway, raw_config)
    result = {'devices': {'imported': 0, 'preserved': 0}, 'reservations': {'added': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0}, 'errors': []}
    if import_devices:
        with labels() as db:
            for row in preview['devices']:
                existing_name = db.execute('SELECT name FROM labels WHERE gateway=? AND mac=?', (gateway.base, row['mac'])).fetchone()
                existing_tag = db.execute('SELECT tag FROM device_tags WHERE gateway=? AND mac=?', (gateway.base, row['mac'])).fetchone()
                if (existing_name and existing_name[0] and not replace_names) or (existing_tag and existing_tag[0] and not replace_names):
                    result['devices']['preserved'] += 1
                    continue
                if row['name']:
                    db.execute('INSERT INTO labels (gateway,mac,name) VALUES (?,?,?) ON CONFLICT(gateway,mac) DO UPDATE SET name=excluded.name', (gateway.base, row['mac'], row['name']))
                elif replace_names:
                    db.execute('DELETE FROM labels WHERE gateway=? AND mac=?', (gateway.base, row['mac']))
                if row['tag']:
                    db.execute('INSERT INTO device_tags (gateway,mac,tag) VALUES (?,?,?) ON CONFLICT(gateway,mac) DO UPDATE SET tag=excluded.tag', (gateway.base, row['mac'], row['tag']))
                elif replace_names:
                    db.execute('DELETE FROM device_tags WHERE gateway=? AND mac=?', (gateway.base, row['mac']))
                result['devices']['imported'] += 1
    if import_reservations:
        for row in preview['reservations']:
            if row['action'] == 'conflito':
                result['reservations']['skipped'] += 1
                result['errors'].append({'mac': row['mac'], 'ip': row['ip'], 'message': row['reason']})
                continue
            if row['action'] == 'igual':
                result['reservations']['unchanged'] += 1
                continue
            if row['action'] == 'substituir' and not replace_reservations:
                result['reservations']['skipped'] += 1
                result['errors'].append({'mac': row['mac'], 'ip': row['ip'], 'message': 'Reserva existente preservada; marque a opção para substituir.'})
                continue
            try:
                current = next((item for item in gateway.reservations()[0] if item['mac'] == row['mac']), None)
                gateway.save({'id': current['id'] if current else '', 'mac': row['mac'], 'ip': row['ip'], 'enabled': row['enabled']})
                result['reservations']['updated' if current else 'added'] += 1
            except (GatewayError, ValueError, TypeError) as error:
                result['reservations']['skipped'] += 1
                result['errors'].append({'mac': row['mac'], 'ip': row['ip'], 'message': str(error)})
    return result


Gateway.set_label_store_factory(labels)

class HuaweiOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        host = (target.hostname or '').lower()
        if target.scheme != 'https' or not (host == 'huawei.com' or host.endswith('.huawei.com')):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def firmware_status(gateway, check_online=False):
    identity = getattr(gateway, 'identity', {}) or {}
    checked_at = None
    source_reachable = None
    if check_online:
        request = urllib.request.Request(HUAWEI_ONT_PRODUCT_URL, headers={'User-Agent': 'GatewayManager/1.0', 'Accept': 'text/html'})
        opener = urllib.request.build_opener(HuaweiOnlyRedirect())
        try:
            with opener.open(request, timeout=8) as response:
                final_host = (urllib.parse.urlsplit(response.geturl()).hostname or '').lower()
                if response.status != 200 or not (final_host == 'huawei.com' or final_host.endswith('.huawei.com')):
                    raise OSError('A página oficial não confirmou uma resposta Huawei segura.')
                response.read(1024)
            source_reachable = True
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            source_reachable = False
            source_error = 'Não foi possível consultar a página oficial agora.'
        else:
            source_error = ''
        checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    else:
        source_error = ''
    return {
        'model': gateway.model_id,
        'model_label': gateway.model_label,
        'hardware': identity.get('hardware'),
        'current': identity.get('firmware'),
        'checked_at': checked_at,
        'source_reachable': source_reachable,
        'latest': None,
        'available': [],
        'download_url': None,
        'source_url': HUAWEI_ONT_PRODUCT_URL,
        'support_url': HUAWEI_SOFTWARE_URL,
        'source_error': source_error,
        'message': ('A página oficial do produto respondeu, mas não publica um catálogo de firmware para download deste ONT. A Huawei orienta obter a versão compatível com o provedor, pois o firmware precisa corresponder ao OLT/NMS.' if source_reachable else
                    source_error if source_reachable is False else
                    'A Huawei não publica nesta página uma lista de versões de firmware do ONT. A versão compatível deve ser confirmada com o provedor, considerando o OLT/NMS.')
    }


EVENTS = {
    'connected': ('Novo dispositivo', 'Um novo dispositivo foi conectado ao roteador,\nNome: {name}\nIP: {ip}\nMAC: {mac}\n{link}', True),
    'disconnected': ('Dispositivo desconectado', 'Dispositivo desconectado.\nNome: {name}\nIP: {ip}\nMAC: {mac}\n{link}', False),
    'ip_changed': ('IP alterado', 'O IP do dispositivo mudou.\nNome: {name}\nIP anterior: {previous_ip}\nIP atual: {ip}\nMAC: {mac}\n{link}', False),
    'blocked_ip_changed': ('Cliente com regra de bloqueio mudou de IP', 'Cliente com regra de bloqueio mudou de IP.\nNome: {name}\nIP anterior: {previous_ip}\nIP atual: {ip}\nMAC: {mac}\nBloqueio ativo: {block_active}\n{link}', False),
    'blocked_disconnected': ('Cliente com regra de bloqueio desconectou', 'Cliente com regra de bloqueio desconectado.\nNome: {name}\nIP: {ip}\nMAC: {mac}\nBloqueio ativo: {block_active}\n{link}', False),
}

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
    with gw.lock:
        devices=gw.devices()
        with labels() as db:
            network_management.observe_devices(db, gw.base, devices)
        if not active: return 'Histórico ativo; notificações desativadas.'
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


def capability_failure(error):
    message = str(error)
    if re.search(r'HTTP (?:401|403)', message): return 'denied'
    if re.search(r'Informe|Confirmação|Confirme|inválid|já existe|não encontrada|fora de|limite de', message, re.I): return None
    return 'unavailable'

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
        header='\n'.join(gateway.logs()['raw'].lstrip('\ufeff').splitlines()[:8])
        header=re.split(r'(?m)^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}',header,maxsplit=1)[0]
        for key,label in [('firmware','SWVer'),('hardware','HWVer')]:
            match=re.search(r'(?:^|[;\r\n])\s*'+label+r'\s*:\s*([^;\r\n]{1,100})',header,re.M)
            if match: identity[key]=match[1].strip()
    except GatewayError: pass
    if any(value is None for value in identity.values()):
        try:
            page=gateway.request('/html/ssmp/deviceinfo/deviceinfo.asp',max_redirects=0)
            detected=parse_gateway_identity(page)
            for key in identity:
                if identity[key] is None and detected.get(key): identity[key]=detected[key]
            for constructor in ('stDevInfo','stDeviceInfo','DeviceInfo'):
                signature=re.search(r'function\s+'+constructor+r'\s*\(([^)]*)\)',page)
                if not signature: continue
                names=[name.strip().casefold() for name in signature[1].split(',')]
                for values in parse_constructors(page,constructor):
                    if len(values)!=len(names) or not values or values[0]!='InternetGatewayDevice.DeviceInfo': continue
                    fields=dict(zip(names,values))
                    for key,aliases in (('firmware',('swver','softwareversion','swversion')),('hardware',('hwver','hardwareversion','hwversion'))):
                        value=next((str(fields[name]) for name in aliases if name in fields),None)
                        if identity[key] is None and value and re.fullmatch(r'[A-Za-z0-9._-]{1,100}',value): identity[key]=value
        except GatewayError: pass
    gateway.identity=identity
    return identity

GATEWAY_ADAPTERS = {Gateway.model_id: Gateway}

def create_gateway(model_id, address):
    adapter = GATEWAY_ADAPTERS.get(model_id)
    if not adapter: raise GatewayError('Modelo de gateway não suportado. Selecione um modelo disponível.')
    return adapter(address)

class Handler(BaseHTTPRequestHandler):
    server_version = 'GatewayManager'
    sys_version = ''

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_message(self, fmt, *args):
        # Do not log form data, gateway addresses, or credentials.
        print('HTTP request handled', flush=True)
    def send_json(self, status, obj, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store')
        if cookie is not None:
            secure = '; Secure' if os.environ.get('COOKIE_SECURE') == '1' else ''
            self.send_header('Set-Cookie', 'session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=' + ('604800' if cookie else '0') + secure)
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def session(self, *, allow_pending=False):
        from http.cookies import SimpleCookie
        c = SimpleCookie(); c.load(self.headers.get('Cookie', ''))
        with LOCK: s = SESSIONS.get(c['session'].value if 'session' in c else '')
        if not s: raise GatewayError('Conecte-se ao gateway novamente.')
        if getattr(s,'pending_lan_change',None) and not allow_pending:
            raise GatewayError('Há uma mudança LAN aguardando verificação. Abra Endereço LAN e use Verificar novo endereço, sem reenviar o comando.')
        return s
    def do_GET(self):
        if self.path == '/api/connection-defaults':
            try: self.send_json(200, connection.defaults(labels))
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/gateway-types':
            self.send_json(200, {'models': [{'id': key, 'label': adapter.model_label} for key, adapter in GATEWAY_ADAPTERS.items()]})
            return
        if self.path == '/api/session':
            try:
                gw = self.session(allow_pending=True)
                pending = getattr(gw,'pending_lan_change',None)
                with gw.lock:
                    if not pending: gw.devices()
                self.send_json(200, {'connected': True, 'address': gw.base, 'model': gw.model_id, 'model_label': gw.model_label, 'pending_lan':bool(pending), **getattr(gw,'identity',{})})
            except GatewayError as e: self.send_json(401, {'error': str(e)})
            return
        if self.path == '/api/network/lan-state':
            try:
                gw = self.session(allow_pending=True)
                pending = getattr(gw,'pending_lan_change',None)
                self.send_json(200, {'pending':bool(pending),'proposed':pending['plan']['proposed'] if pending else None,'recovery':pending['plan']['recovery'] if pending else []})
            except GatewayError as error: self.send_json(400,{'error':str(error)})
            return
        if self.path == '/api/capabilities':
            try:
                self.send_json(200, capability_snapshot(self.session()))
            except GatewayError as e: self.send_json(401, {'error': str(e)})
            return
        if self.path == '/api/network/inventory':
            try:
                gw = self.session()
                with gw.lock:
                    self.send_json(200, {'pages': list(gw.network_pages.values()), 'capabilities': capability_snapshot(gw)})
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if urllib.parse.urlsplit(self.path).path == '/api/local-records':
            try:
                gw = self.session()
                kind = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('kind', [''])[0]
                with gw.lock: result = gw.local_records(kind)
                feature = 'static_dns' if kind == 'dns' else 'ipv6_reservations'
                record_capability(gw, feature, 'read', 'available' if result['recognized'] else 'unrecognized', result['reason'])
                if not result['writable']: record_capability(gw, feature, 'write', 'unavailable', result['reason'])
                self.send_json(200, result)
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/dnsv6':
            try:
                gw = self.session()
                with gw.lock: result = gw.dnsv6_config()
                record_capability(gw, 'dns_ipv6', 'read', 'available', 'Objeto local de DNSv6 reconhecido.')
                self.send_json(200, result)
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/wifi/lifecycle':
            try:
                gw = self.session()
                with gw.lock: result = gw.wifi_lifecycle()
                record_capability(gw, 'wifi_lifecycle', 'read', 'available')
                self.send_json(200, result)
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path in ('/api/wifi/security', '/api/wifi/radios'):
            feature = 'wifi_security' if self.path.endswith('security') else 'wifi_radio'
            try:
                gw = self.session()
                with gw.lock: result = gw.wifi_security() if feature == 'wifi_security' else gw.radio_config()
                record_capability(gw, feature, 'read', 'available', 'Propriedades de Wi-Fi reconhecidas no firmware.')
                self.send_json(200, {'config': result})
            except GatewayError as error:
                if 'gw' in locals(): record_capability(gw, feature, 'read', capability_failure(error), str(error))
                self.send_json(400, {'error': str(error)})
            return
        if urllib.parse.urlsplit(self.path).path == '/api/network/history':
            try:
                gw = self.session()
                params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                with labels() as db:
                    result = network_management.history(db, gw.base, level=params.get('level', [''])[0], kind=params.get('kind', [''])[0], query=params.get('q', [''])[0], before=params.get('before', [None])[0])
                self.send_json(200, result)
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/network/export':
            try:
                gw = self.session()
                with gw.lock:
                    pages = [{key: row[key] for key in ('id', 'label', 'status', 'sampled_at', 'recognized', 'observations', 'clients', 'reservations', 'leases', 'nodes') if key in row} for row in gw.network_pages.values()]
                self.send_json(200, {'format': 'gateway-manager-lan-projection', 'version': 1, 'exported_at': network_management.utc_now(), 'model': gw.model_label, 'pages': pages,
                                     'notice': 'Inventário de leitura. Não contém credenciais e não é um backup restaurável do Huawei.'})
            except GatewayError as error: self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/static-dns':
            try:
                gw = self.session()
                with gw.lock: result = gw.static_dns()
                record_capability(gw, 'static_dns', 'read', 'available' if result['recognized'] else 'unrecognized',
                                  'Objeto HOSTS e fonte de dados DNS locais reconhecidos.' if result['recognized'] else 'A fonte da tabela DNS local não foi reconhecida; nenhum valor foi presumido.')
                self.send_json(200, result)
            except GatewayError as error:
                if 'gw' in locals(): record_capability(gw, 'static_dns', 'read', capability_failure(error), str(error))
                self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/ipv6':
            try:
                gw = self.session()
                with gw.lock: result = gw.ipv6_network()
                record_capability(gw, 'dhcpv6_ra', 'read', 'available' if result['settings_recognized'] else 'unrecognized',
                                  'Campos LAN IPv6 reconhecidos.' if result['settings_recognized'] else 'Página acessível, mas os campos DHCPv6/RA não foram reconhecidos.')
                record_capability(gw, 'ipv6_reservations', 'read', 'available' if result['reservations_recognized'] else 'unrecognized',
                                  'Tabela de reservas IPv6 reconhecida.' if result['reservations_recognized'] else 'Tabela IPv6 acessível, mas sem cabeçalhos reconhecidos.')
                self.send_json(200, result)
            except GatewayError as error:
                if 'gw' in locals():
                    record_capability(gw, 'dhcpv6_ra', 'read', capability_failure(error), str(error))
                    record_capability(gw, 'ipv6_reservations', 'read', capability_failure(error), str(error))
                self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/port-isolation':
            try:
                gw = self.session()
                with gw.lock: result = gw.port_isolation()
                record_capability(gw, 'port_isolation', 'read', 'available' if result['recognized'] else 'unrecognized',
                                  'Campos de isolamento de portas reconhecidos.' if result['recognized'] else 'Página acessível, mas os campos de isolamento não foram reconhecidos.')
                self.send_json(200, result)
            except GatewayError as error:
                if 'gw' in locals(): record_capability(gw, 'port_isolation', 'read', capability_failure(error), str(error))
                self.send_json(400, {'error': str(error)})
            return
        if self.path == '/api/firmware':
            try:
                gw = self.session()
                with gw.lock: session_identity(gw)
                self.send_json(200, firmware_status(gw))
            except GatewayError as e: self.send_json(401, {'error': str(e)})
            return
        if self.path == '/api/maintenance/export':
            try:
                gw = self.session()
                with gw.lock: result = export_portable_config(gw)
                self.send_json(200, result)
            except GatewayError as e: self.send_json(400, {'error': str(e)})
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
                record_capability(gw, 'user_logs' if source == 'user' else 'ap_logs', 'read', 'available')
                self.send_json(200, result)
            except GatewayError as e:
                if 'gw' in locals(): record_capability(gw, 'user_logs' if locals().get('source') == 'user' else 'ap_logs', 'read', capability_failure(e), str(e))
                self.send_json(400, {'error': str(e)})
            return
        if self.path in ('/api/dhcp', '/api/wifi'):
            try:
                gw = self.session()
                with gw.lock: result = gw.dhcp_config() if self.path == '/api/dhcp' else gw.wifi_config()
                record_capability(gw, 'dhcp_ipv4' if self.path == '/api/dhcp' else 'wifi_ssids', 'read', 'available')
                self.send_json(200, {'config': result})
            except GatewayError as e:
                if 'gw' in locals(): record_capability(gw, 'dhcp_ipv4' if self.path == '/api/dhcp' else 'wifi_ssids', 'read', capability_failure(e), str(e))
                self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/devices':
            try:
                gateway = self.session()
                with gateway.lock:
                    rows = gateway.devices()
                    with labels() as db:
                        network_management.observe_devices(db, gateway.base, rows)
                    record_capability(gateway, 'clients', 'read', 'available')
                    try:
                        reservations, _ = gateway.reservations()
                        mark_fixed_addresses(rows, reservations)
                        reservations_available = True
                        record_capability(gateway, 'reservations_ipv4', 'read', 'available')
                    except GatewayError as error:
                        for row in rows:
                            row['ip_fixed'] = False
                            row['ip_static'] = row.get('ip_type', '').strip().lower() == 'static'
                        reservations_available = False
                        record_capability(gateway, 'reservations_ipv4', 'read', capability_failure(error), str(error))
                    try:
                        blocked = gateway.blocked_clients(rows)
                        blocked_available = True
                        record_capability(gateway, 'wifi_access_policy', 'read', 'available')
                    except GatewayError as error:
                        blocked = []
                        blocked_available = False
                        record_capability(gateway, 'wifi_access_policy', 'read', capability_failure(error), str(error))
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                    tags = dict(db.execute('SELECT mac,tag FROM device_tags WHERE gateway=?', (gateway.base,)))
                for row in rows + blocked:
                    row['name'] = saved.get(row['mac'], '')
                    row['tag'] = tags.get(row['mac'], '')
                self.send_json(200, {'devices': rows, 'blocked': blocked, 'clients': normalize_clients(rows, blocked, saved, tags, reservations if reservations_available else [], getattr(gateway, 'dhcpv6_clients', []), getattr(gateway, 'lan_port_statuses', {})), 'blocked_available': blocked_available, 'reservations_available': reservations_available})
            except GatewayError as e:
                if 'gateway' in locals(): record_capability(gateway, 'clients', 'read', capability_failure(e), str(e))
                self.send_json(400, {'error': str(e)})
            return
        if self.path == '/api/reservations':
            try:
                gateway = self.session()
                with gateway.lock:
                    rows, _ = gateway.reservations()
                    record_capability(gateway, 'reservations_ipv4', 'read', 'available')
                    try:
                        devices = gateway.devices()
                        names_unavailable = False
                    except GatewayError:
                        devices = []
                        names_unavailable = True
                with labels() as db:
                    saved = dict(db.execute('SELECT mac,name FROM labels WHERE gateway=?', (gateway.base,)))
                self.send_json(200, {'reservations': enrich_reservations(rows, devices, saved), 'device_names_unavailable': names_unavailable})
            except GatewayError as e:
                if 'gateway' in locals(): record_capability(gateway, 'reservations_ipv4', 'read', capability_failure(e), str(e))
                self.send_json(400, {'error': str(e)})
            return
        files = {'/navigation-model.js': ('navigation-model.js', 'application/javascript'), '/navigation.js': ('navigation.js', 'application/javascript'), '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'application/javascript'), '/network.js': ('network.js', 'application/javascript'), '/network-actions.js': ('network-actions.js', 'application/javascript'), '/style.css': ('style.css', 'text/css'), '/icon.png': ('icon.png', 'image/png'), '/huawei.png': ('huawei.png', 'image/png')}
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
            limit = 524288 if self.path in ('/api/maintenance/preview', '/api/maintenance/apply') else 32768 if self.path=='/api/hooks' else 8192
            if length <= 0 or length > limit: raise GatewayError('Requisição inválida ou arquivo de configuração maior que 512 KiB.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/detect':
                self.send_json(200,detect_gateway(str(body.get('address',''))))
            elif self.path == '/api/firmware/check':
                gw = self.session()
                with gw.lock: session_identity(gw)
                self.send_json(200, firmware_status(gw, check_online=True))
            elif self.path == '/api/capabilities/inspect':
                gw = self.session()
                with gw.lock:
                    pages = gw.inspect_network_pages()
                    with labels() as db: network_management.observe_pages(db, gw.base, pages)
                self.send_json(200, {**capability_snapshot(gw), 'pages': pages})
            elif self.path == '/api/network/inventory/refresh':
                gw = self.session()
                features = body.get('features')
                if features is not None and (not isinstance(features, list) or not all(isinstance(item, str) for item in features)):
                    raise GatewayError('Seleção de inventário inválida.')
                with gw.lock:
                    pages = gw.inspect_network_pages(features)
                    with labels() as db: network_management.observe_pages(db, gw.base, pages)
                    result = {'pages': list(gw.network_pages.values()), 'capabilities': capability_snapshot(gw)}
                self.send_json(200, result)
            elif self.path == '/api/network/lan-preview':
                gw = self.session()
                with gw.lock:
                    result = gw.plan_lan_change(body)
                    with labels() as db: network_management.assert_gateway_target_free(db,gw.base,result['proposed']['base'])
                self.send_json(200, result)
            elif self.path in ('/api/network/lan-apply','/api/network/lan-verify'):
                gw = self.session(allow_pending=self.path.endswith('verify'))
                serial = MONITOR_LOCKS.setdefault(gw.base,threading.Lock())
                with serial:
                    stop_monitor(gw)
                    with gw.lock:
                        source = (getattr(gw,'pending_lan_change',None) or {}).get('storage_source',gw.base)
                        def journal(plan):
                            try:
                                with labels() as db: network_management.journal_lan_change(db,source,plan)
                            except sqlite3.Error:
                                raise GatewayError('Não foi possível registrar a recuperação local. O comando de mudança LAN não foi enviado.')
                        try:
                            result = gw.verify_lan_change() if self.path.endswith('verify') else gw.apply_lan_change(body,journal=journal)
                            replacement = result.pop('replacement',None)
                            if replacement is not None:
                                try:
                                    with labels() as db:
                                        network_management.move_gateway_state(db,source,replacement.base)
                                        network_management.event(db,replacement.base,'configuration_changed','Novo endereço LAN, DHCP e reservas confirmados no mesmo equipamento. Cadastros locais preservados.',evidence='confirmed')
                                except (GatewayError,sqlite3.Error) as error:
                                    result = {**result,'state':'pending_verification','verified':False,'message':'O gateway respondeu no novo endereço, mas a migração dos cadastros não concluiu. Resolva o conflito e use Verificar novamente.'}
                                else:
                                    for attribute in ('base','cookies','opener','credentials','capability_matrix','dhcpv6_clients','lan_port_statuses','network_pages'):
                                        setattr(gw,attribute,getattr(replacement,attribute))
                                    gw.pending_lan_change = None
                                    connection.remember(labels, gw, gw.credentials[0] if gw.credentials else '')
                                    record_capability(gw,'lan_address','write','verified')
                            if not getattr(gw,'pending_lan_change',None): start_monitor(gw)
                        except Exception:
                            if not getattr(gw,'pending_lan_change',None): start_monitor(gw)
                            raise
                self.send_json(200,result)
            elif self.path in ('/api/local-records', '/api/dnsv6'):
                gw = self.session()
                feature = 'static_dns' if body.get('kind') == 'dns' else 'ipv6_reservations' if self.path == '/api/local-records' else 'dns_ipv6'
                try:
                    result = gw.save_local_record(body) if self.path == '/api/local-records' else gw.save_dnsv6(body)
                except GatewayError as error:
                    record_capability(gw, feature, 'write', capability_failure(error), str(error)); raise
                record_capability(gw, feature, 'write', 'verified')
                with labels() as db:
                    network_management.event(db, gw.base, 'configuration_changed', 'Alteração de DNS local ou reserva IPv6 confirmada por releitura.', evidence='confirmed')
                self.send_json(200, result)
            elif self.path == '/api/wifi/lifecycle':
                gw = self.session()
                action = body.get('action')
                if action == 'create': result = gw.create_wifi_network(body)
                elif action == 'resume': result = gw.resume_wifi_network(body)
                elif action == 'delete': result = gw.delete_wifi_network(body)
                else: raise GatewayError('Operação de rede Wi-Fi inválida.')
                if result.get('verified'):
                    record_capability(gw,'wifi_lifecycle','write','verified')
                    with labels() as db: network_management.event(db,gw.base,'configuration_changed','Operação de rede Wi-Fi confirmada por releitura: '+action+'. Nenhuma chave registrada.',evidence='confirmed')
                else:
                    with labels() as db: network_management.event(db,gw.base,'configuration_pending','Criação de rede Wi-Fi aguardando conferência. Mantenha a rede desativada.',level='WAR',evidence='observed')
                self.send_json(200, result)
            elif self.path == '/api/wifi/radios/preview':
                gw = self.session()
                self.send_json(200, gw.preview_radio_change(body))
            elif self.path in ('/api/wifi/security', '/api/wifi/radios'):
                gw = self.session()
                feature = 'wifi_security' if self.path.endswith('security') else 'wifi_radio'
                try: result = gw.save_wifi_security(body) if feature == 'wifi_security' else gw.save_radio(body)
                except GatewayError as error:
                    record_capability(gw, feature, 'write', capability_failure(error), str(error)); raise
                record_capability(gw, feature, 'write', 'verified')
                with labels() as db: network_management.event(db, gw.base, 'configuration_changed', 'Alteração de autenticação Wi-Fi ou rádio confirmada por releitura.', evidence='confirmed')
                self.send_json(200, {'config': result})
            elif self.path == '/api/wifi/password':
                gw = self.session()
                result = gw.save_wifi_password(body)
                with labels() as db: network_management.event(db,gw.base,'configuration_changed','Alteração de senha Wi-Fi confirmada por releitura. A chave não foi registrada.',evidence='confirmed')
                self.send_json(200,result)
            elif self.path == '/api/network/diagnostic':
                gw = self.session()
                with gw.lock:
                    current, devices = gw.dhcp_config(), gw.devices()
                result = network_management.tcp_diagnostic(current, devices, body.get('target'), body.get('port'))
                with labels() as db:
                    network_management.event(db, gw.base, 'diagnostic', f'Diagnóstico TCP {result["target"]}:{result["port"]} · {result["description"]}', evidence='confirmed', level='INFO' if result['outcome'] == 'reachable' else 'WAR')
                self.send_json(200, result)
            elif self.path == '/api/maintenance/preview':
                gw = self.session()
                with gw.lock: result = preview_portable_config(gw, body.get('config'))
                self.send_json(200, result)
            elif self.path == '/api/maintenance/apply':
                if body.get('confirm') != 'IMPORTAR': raise GatewayError('Confirme a importação antes de aplicar.')
                gw = self.session()
                with gw.lock:
                    result = apply_portable_config(gw, body.get('config'),
                        import_devices=body.get('import_devices', False),
                        import_reservations=body.get('import_reservations', False),
                        replace_names=body.get('replace_names', False),
                        replace_reservations=body.get('replace_reservations', False))
                self.send_json(200, result)
            elif self.path == '/api/login':
                model, address, username, password = connection.resolve(labels, body)
                gw = create_gateway(model, address); gw.login(username, password)
                with gw.lock: identity=session_identity(gw)
                parsed_origin = urllib.parse.urlsplit(origin)
                if parsed_origin.scheme not in ('http', 'https') or not parsed_origin.hostname or parsed_origin.username or parsed_origin.password or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
                    raise GatewayError('Endereço do aplicativo inválido.')
                with labels() as db:
                    db.execute('INSERT INTO app_origins (gateway,origin) VALUES (?,?) ON CONFLICT(gateway) DO UPDATE SET origin=excluded.origin', (gw.base, origin))
                connection.remember(labels, gw, username)
                key = secrets.token_urlsafe(32)
                with LOCK: SESSIONS[key] = gw
                with labels() as db: gw.pending_lan_change = network_management.restore_lan_journal(db,gw.base)
                if not gw.pending_lan_change: start_monitor(gw)
                self.send_json(200, {'ok': True, 'address': gw.base, 'model': gw.model_id, 'model_label': gw.model_label, 'pending_lan':bool(gw.pending_lan_change), **identity}, key)
            elif self.path == '/api/block':
                gw = self.session()
                try: gw.block_client(body)
                except GatewayError as error: record_capability(gw, 'wifi_access_policy', 'write', capability_failure(error), str(error)); raise
                record_capability(gw, 'wifi_access_policy', 'write', 'verified'); self.send_json(200, {'ok': True})
            elif self.path == '/api/unblock':
                gw = self.session()
                try: gw.unblock_client(body)
                except GatewayError as error: record_capability(gw, 'wifi_access_policy', 'write', capability_failure(error), str(error)); raise
                record_capability(gw, 'wifi_access_policy', 'write', 'verified'); self.send_json(200, {'ok': True})
            elif self.path == '/api/reservation':
                gw = self.session()
                try: gw.save(body)
                except GatewayError as error: record_capability(gw, 'reservations_ipv4', 'write', capability_failure(error), str(error)); raise
                record_capability(gw, 'reservations_ipv4', 'write', 'verified'); self.send_json(200, {'ok': True})
            elif self.path == '/api/reservation/delete':
                gw = self.session()
                try: deleted = gw.delete_reservation(body)
                except GatewayError as error: record_capability(gw, 'reservations_ipv4', 'write', capability_failure(error), str(error)); raise
                record_capability(gw, 'reservations_ipv4', 'write', 'verified'); self.send_json(200, {'deleted': deleted})
            elif self.path in ('/api/dhcp', '/api/dns'):
                gw = self.session(); feature = 'dns_lan' if self.path == '/api/dns' else 'dhcp_ipv4'
                try: config = gw.save_dhcp(body, dns_only=self.path == '/api/dns')
                except GatewayError as error: record_capability(gw, feature, 'write', capability_failure(error), str(error)); raise
                record_capability(gw, feature, 'write', 'verified')
                self.send_json(200, {'config': config})
            elif self.path == '/api/wifi':
                gw = self.session()
                try: config = gw.save_wifi(body)
                except GatewayError as error: record_capability(gw, 'wifi_ssids', 'write', capability_failure(error), str(error)); raise
                record_capability(gw, 'wifi_ssids', 'write', 'verified')
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
