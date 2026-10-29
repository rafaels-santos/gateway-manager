"""Typed readers for constructor layouts inspected on the target firmware."""
import ipaddress
import json
import re

from ..parsers import parse_constructors


def observed_fields(feature, page):
    result = []
    def add(label, value, field, **extra):
        result.append({'label': label, 'value': str(value), 'field': field, **extra})
    if feature == 'lan_address':
        for row in parse_constructors(page, 'stLanHostInfo'):
            if len(row) != 5 or not re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.LANHostConfigManagement\.IPInterface\.[12]', str(row[0])): continue
            try: address, mask = str(ipaddress.IPv4Address(row[2])), str(ipaddress.IPv4Network(('0.0.0.0', row[3])).netmask)
            except ValueError: continue
            prefix = 'Principal' if row[0].endswith('.1') else 'Secundário'
            add(prefix + ' · IP', address, row[0]); add(prefix + ' · máscara', mask, row[0]); add(prefix + ' · estado', 'Ativado' if row[1] == '1' else 'Desativado', row[0])
    elif feature in ('port_mode', 'port_isolation'):
        for row in parse_constructors(page, 'stLayer3Enable'):
            if len(row) != 2: continue
            match = re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.LANEthernetInterfaceConfig\.([1-4])', str(row[0]))
            if match and row[1] in ('0', '1'):
                add('LAN' + match[1] + ' · modo', 'Layer 3' if row[1] == '1' else 'Layer 2', row[0])
        # An empty ethIsolateCfg array does not establish the isolation flag.
    elif feature == 'dhcpv6_ra':
        for row in parse_constructors(page, 'RaConfigInfoClass'):
            if len(row) != 6 or row[0] != 'InternetGatewayDevice.LANDevice.1.X_HW_RouterAdvertisement': continue
            add('Atribuição de endereços', 'DHCPv6' if row[1] == '1' else 'SLAAC', 'ManagedFlag')
            add('Outras informações', 'DHCPv6' if row[2] == '1' else 'SLAAC', 'OtherConfigFlag')
            add('Router Advertisement', 'Ativado' if row[4] == '1' else 'Desativado', 'RA.Enable')
            if str(row[5]).isdigit(): add('MTU IPv6', row[5], 'RA.MTU')
        for row in parse_constructors(page, 'DhcpV6Server'):
            if len(row) == 3 and row[0] == 'InternetGatewayDevice.LANDevice.1.X_HW_DHCPv6.Server':
                add('Servidor DHCPv6', 'Ativado' if row[1] == '1' else 'Desativado', 'DHCPv6.Enable')
        for row in parse_constructors(page, 'IPv6DNSConfigClass'):
            if len(row) == 5 and row[0] == 'InternetGatewayDevice.LANDevice.1.X_HW_IPv6Config':
                add('Origem do DNS IPv6', row[2], 'IPv6DNSConfigType')
                for index, raw in enumerate(str(row[4]).split(','), 1):
                    try: address = str(ipaddress.IPv6Address(raw))
                    except ValueError: continue
                    add('DNS IPv6 ' + str(index), address, 'IPv6DNSServers')
    elif feature == 'mesh_topology':
        for row in parse_constructors(page, 'StEasymeshInfo'):
            if len(row) == 2 and row[0] == 'InternetGatewayDevice.EasyMesh': add('EasyMesh', 'Ativado' if row[1] == '1' else 'Desativado', 'EasyMesh.Enable')
        for row in parse_constructors(page, 'EasymeshInfo'):
            if len(row) != 3 or row[0] != 'InternetGatewayDevice.EasyMesh': continue
            for band, raw in zip(('2,4 GHz', '5 GHz'), row[1:]):
                if re.fullmatch(r'-\d{1,3}', str(raw)) and -100 <= int(raw) <= -55: add('Limiar RSSI ' + band, str(raw) + ' dBm', 'EasyMesh.RSSI')
    elif feature == 'wifi_radio':
        seen = set()
        for row in parse_constructors(page, 'stWlanWifi'):
            if len(row) < 11 or row[0] in seen: continue
            if row[0] not in ('InternetGatewayDevice.LANDevice.1.WLANConfiguration.1', 'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5'): continue
            seen.add(row[0]); band = '2,4 GHz' if row[0].endswith('.1') else '5 GHz'
            add(band + ' · modo', row[5], 'Standard')
            add(band + ' · canal', 'Automático' if row[9] == '1' else row[6], 'Channel')
            if str(row[7]).isdigit(): add(band + ' · potência', str(row[7]) + '%', 'TransmitPower')
            add(band + ' · largura (código do firmware)', row[10], 'X_HW_HT20')
            add(band + ' · domínio regulatório', row[8], 'RegulatoryDomain')
    elif feature == 'system_information':
        speeds = {'0':'10 Mbit/s','1':'100 Mbit/s','2':'1000 Mbit/s','3':'2500 Mbit/s','4':'10000 Mbit/s','6':'5000 Mbit/s','7':'25000 Mbit/s'}
        for row in parse_constructors(page, 'GEInfo'):
            if len(row) != 5: continue
            match = re.fullmatch(r'InternetGatewayDevice\.X_HW_DEBUG\.AMP\.LANPort\.([1-4])\.CommonConfig', str(row[0]))
            if not match or row[3] not in ('0','1'): continue
            port = 'LAN' + match[1]
            status = 'Up' if row[3] == '1' else 'Down'
            add(port + ' · enlace', status, row[0], port=port, status=status)
            if row[3] == '1':
                if row[2] in speeds: add(port + ' · velocidade', speeds[row[2]], row[0])
                if row[1] in ('0','1'): add(port + ' · modo', 'Full-duplex' if row[1] == '1' else 'Half-duplex', row[0])
        for row in parse_constructors(page, 'LANStats'):
            if len(row) != 13: continue
            match = re.fullmatch(r'InternetGatewayDevice\.X_HW_DEBUG\.AMP\.LANPort\.([1-4])\.Statistics', str(row[0]))
            if not match or not all(str(value).isdigit() for value in row[1:]): continue
            values = [int(value) for value in row[1:]]
            if any(value > 2**32-1 for value in values): continue
            tx_packets = values[0] + values[1] * 2**32
            tx_bytes = values[2] + values[3] * 2**32 + values[4] + values[5] * 2**32
            rx_packets = values[6] + values[7] * 2**32
            rx_bytes = values[8] + values[9] * 2**32 + values[10] + values[11] * 2**32
            port = 'LAN' + match[1]
            add(port + ' · RX', f'{rx_bytes} bytes · {rx_packets} pacotes', row[0])
            add(port + ' · TX', f'{tx_bytes} bytes · {tx_packets} pacotes', row[0])
        from ..network_readers import _Tables
        parser = _Tables(); parser.feed(page)
        for table in parser.tables:
            for row in table:
                if len(row) != 2 or row[0].strip().casefold().rstrip(':') not in ('uptime', 'system uptime', 'device uptime'):
                    continue
                value = row[1].strip()
                match = re.fullmatch(r'(?:(\d+)\s*(?:days?|d)\s*)?(\d{1,2}):(\d{2}):(\d{2})', value, re.I)
                if not match or int(match[2]) > 23 or int(match[3]) > 59 or int(match[4]) > 59: continue
                seconds = int(match[1] or 0) * 86400 + int(match[2]) * 3600 + int(match[3]) * 60 + int(match[4])
                add('Tempo de atividade', value, 'System Information.Uptime', metric='uptime', seconds=seconds)
    return result


def dhcpv6_leases(page):
    recognized = 'function DhcpInfoClass' in page and bool(re.search(r'var\s+RecordList\s*=\s*new\s+Array\s*\(', page))
    records = []
    for row in parse_constructors(page, 'DhcpInfoClass') if recognized else []:
        if len(row) != 5: continue
        try: address = str(ipaddress.IPv6Address(row[2])); prefix = int(row[3]); duration = int(row[4])
        except (ValueError, TypeError): continue
        if not 0 <= prefix <= 128 or duration < 0 or not re.fullmatch(r'[0-9a-fA-F:-]{2,256}', str(row[1])): continue
        records.append({'duid': str(row[1]).upper(), 'ipv6': address, 'prefix': prefix, 'remaining_seconds': duration})
    return records, recognized


def mesh_nodes(page):
    # The firmware embeds JSON text, not executable objects. Never evaluate JavaScript.
    match = re.search(r"var\s+staInfo\s*=\s*'((?:\\.|[^'\\])*)'", page)
    if not match: return [], False
    try:
        text = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), match[1]).replace('\\\'', "'").replace('\\"', '"')
        tree = json.loads(text)
    except (ValueError, TypeError): return [], False
    if not isinstance(tree, list): return [], False
    nodes, seen = [], set()
    def mac(raw):
        raw = str(raw or '').replace(':', '').lower()
        return ':'.join(raw[i:i+2] for i in range(0, 12, 2)) if re.fullmatch('[0-9a-f]{12}', raw) else None
    def walk(items, parent=None, depth=0):
        if depth > 8: return
        for item in items[:256]:
            if not isinstance(item, dict): continue
            identity = mac(item.get('mac_address'))
            if not identity or identity in seen: continue
            seen.add(identity)
            nodes.append({'mac': identity, 'parent': parent, 'role': 'Controller' if parent is None else 'Agent', 'link': str(item.get('link', ''))[:30]})
            stations = item.get('station_info', [])
            for station in stations[:256] if isinstance(stations, list) else []:
                if not isinstance(station, dict): continue
                station_mac = mac(station.get('station_mac'))
                if station_mac and station_mac not in seen:
                    seen.add(station_mac); nodes.append({'mac': station_mac, 'parent': identity, 'role': 'Station', 'link': str(station.get('link', ''))[:30]})
            children = item.get('child_devices', [])
            if isinstance(children, list): walk(children, identity, depth + 1)
    walk(tree)
    return nodes, True
