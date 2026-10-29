import json
import re
import ipaddress

from .errors import GatewayError


def parse_constructors(page, name):
    result = []
    for raw in re.findall(r'new\s+' + re.escape(name) + r'\s*\(([^)]*)\)', page):
        raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), raw)
        try:
            result.append(json.loads('[' + raw + ']'))
        except (ValueError, TypeError):
            raise GatewayError('Formato de configuração do gateway não reconhecido.')
    return result


def parse_devices_page(page, ssid_map):
    if 'var UserDevinfo' not in page or 'function USERDevice' not in page:
        raise GatewayError('O formato de dispositivos do gateway não foi reconhecido.')
    found = {}
    for match in re.finditer(r'new\s+USERDevice\s*\(([^)]*)\)', page):
        raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), match.group(1))
        try:
            fields = json.loads('[' + raw + ']')
        except (ValueError, TypeError):
            raise GatewayError('O formato de dispositivos do gateway não foi reconhecido.')
        if len(fields) < 14:
            raise GatewayError('O gateway retornou uma lista de dispositivos incompleta.')
        domain, ip, mac, port, ip_type, _, status, kind, duration, hostname = fields[:10]
        mac = str(mac).lower()
        if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or kind.upper() not in ('ETH', 'WIFI', 'ONU'):
            continue
        device = {
            'id': domain, 'ip': ip, 'mac': mac, 'port': port,
            'status': str(status).lower(), 'type': 'wifi' if kind.upper() == 'WIFI' else 'lan',
            'hostname': hostname, 'gateway_name': fields[13], 'duration': duration,
            'ip_type': ip_type, 'ipv4_enabled': fields[10], 'ipv6_enabled': fields[11],
            'network': ssid_map.get(str(port).upper(), 'Wi-Fi · rede não identificada') if kind.upper() == 'WIFI' else 'LAN',
        }
        previous = found.get(mac)
        if not previous or (device['status'] == 'online' and previous['status'] != 'online'):
            found[mac] = device
    return list(found.values())


def parse_dhcp_page(page):
    pools, interfaces = parse_constructors(page, 'dhcpmainst'), parse_constructors(page, 'stipaddr')
    if not pools or len(pools[0]) < 20 or not interfaces or len(interfaces[0]) < 4 or 'onttoken' not in page:
        raise GatewayError('Configuração DHCP indisponível ou sessão expirada.')
    pool, lan = pools[0], interfaces[0]
    dns = (pool[16] or pool[18]).split(',')
    return {'enabled': pool[1] == '1', 'start': pool[2], 'end': pool[3], 'lease': pool[4], 'dns_primary': dns[0], 'dns_secondary': dns[1] if len(dns)>1 else '', 'lan_ip': lan[2], 'mask': lan[3]}


def parse_wifi_page(page, ssid_map):
    match = re.search(r'var\s+WlanArr\s*=\s*new\s+Array\((.*?)\s*,\s*null\s*\)', page, re.S)
    if not match:
        raise GatewayError('Configuração Wi-Fi indisponível ou sessão expirada.')
    networks = []
    for raw in re.findall(r'new\s+stWlan\s*\(([^)]*)\)', match.group(1)):
        fields = re.findall(r'"(?:\\.|[^"\\])*"', raw)[:6]
        if len(fields) != 6:
            raise GatewayError('Formato Wi-Fi não reconhecido.')
        fields = [re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), value) for value in fields]
        values = json.loads('[' + ','.join(fields) + ']')
        if len(values) < 6:
            continue
        domain, _, enabled, ssid, broadcast, maximum = values[:6]
        item = re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.WLANConfiguration\.(\d+)', domain)
        if item:
            number = int(item.group(1))
            networks.append({'id': domain, 'ssid': ssid, 'enabled': enabled == '1', 'broadcast': broadcast == '1', 'max_clients': maximum, 'network': ssid_map.get('SSID'+str(number), 'Rede não identificada')})
    if not networks or 'onttoken' not in page:
        raise GatewayError('Configuração Wi-Fi indisponível ou sessão expirada.')
    return networks


def parse_block_policy_page(page):
    def flag(name):
        match = re.search(r'var\s+' + name + r"\s*=\s*['\"]([01])['\"]", page)
        if not match:
            raise GatewayError('Política de bloqueio não reconhecida.')
        return match.group(1)
    if 'onttoken' not in page or flag('FilterBySsidFlag') != '0':
        raise GatewayError('Modo de filtragem não suportado por esta integração.')
    return {'enabled': flag('enableFilter') == '1', 'blacklist': flag('Mode') == '0', 'rules': parse_constructors(page, 'stMacFilter')}


def parse_reservations_page(page):
    pattern = r'new\s+stDhcp\s*\(\s*"(InternetGatewayDevice\.LANDevice\.1\.LANHostConfigManagement\.DHCPStaticAddress\.\d+)"\s*,\s*"([01])"\s*,\s*"([^"\n]*)"\s*,\s*"([^"\n]*)"'
    def decode(value):
        return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), value)
    rows = []
    for domain, enabled, raw_ip, raw_mac in re.findall(pattern, page, re.I):
        mac, ip = decode(raw_mac).lower(), decode(raw_ip)
        if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
            continue
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            raise GatewayError('O gateway retornou um IP inválido.')
        rows.append({'id': domain, 'mac': mac, 'ip': ip, 'enabled': enabled == '1'})
    if not rows and re.search(r'DHCPStaticAddress\.\d+', page):
        raise GatewayError('Formato de reservas não reconhecido; nenhuma alteração foi feita.')
    return rows


def parse_logs_page(page, source):
    match = re.search(r"document\.getElementById\([\"']logarea[\"']\)\.value\s*=\s*'((?:\\.|[^'\\])*)'", page)
    if source == 'ap':
        match = re.search(r"var\s+ApLogInfoText\s*=\s*'((?:\\.|[^'\\])*)'", page)
    if not match:
        raise GatewayError('Logs indisponíveis. Verifique a sessão e a permissão de leitura no Huawei.')
    raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), match[1])
    raw = raw.replace(r'\r', '\r').replace(r'\n', '\n').replace(r"\'", "'").replace(r'\\', '\\')
    events = []
    levels = {'info':'INFO', 'informational':'INFO', 'notice':'INFO', 'debug':'INFO', 'warning':'WAR', 'warn':'WAR', 'error':'ERROR', 'critical':'ERROR', 'alert':'ERROR', 'emergency':'ERROR'}
    for line in raw.splitlines():
        event = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^]]+)\]\[([^]]+)\]\s*(.*)$', line)
        if event:
            stamp, level, category, message = event.groups()
            events.append({'time':stamp, 'level':levels.get(level.lower(), 'OTHER'), 'source_level':level, 'category':category, 'message':message})
        elif source == 'ap' and line.strip():
            ap_event = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([^]]+)\]\s*(.*)$', line)
            if ap_event:
                stamp, level, message = ap_event.groups()
                events.append({'time':stamp, 'level':levels.get(level.lower(), 'OTHER'), 'source_level':level, 'category':'AP', 'message':message})
            elif events:
                events[-1]['message'] += '\n' + line
        elif events and line.strip():
            events[-1]['message'] += '\n' + line
    return {'events':list(reversed(events[-1000:])), 'total':len(events), 'limited':len(events)>1000, 'source':source, 'raw':raw, 'categories':['Config-Log','Shell-Log','Alarm-Log'] if source == 'user' else []}
