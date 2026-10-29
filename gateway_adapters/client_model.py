import ipaddress
import re


def _valid_ipv4(value):
    try:
        return str(ipaddress.IPv4Address(value))
    except (ValueError, TypeError):
        return None


def normalize_client(device, *, app_alias='', tag='', reservation=None, block_rule=None, ipv6_addresses=None, lan_port_status=None):
    """Return one source-aware client record without treating unknown data as absent."""
    mac = str(device.get('mac', '')).strip().lower()
    if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
        return None
    ipv4 = _valid_ipv4(device.get('ip'))
    port = str(device.get('port', '')).upper()
    connection_type = device.get('type')
    band = '2.4 GHz' if port in ('SSID1', 'SSID2') else '5 GHz' if port == 'SSID5' else None
    names = {
        'app_alias': app_alias or None,
        'client_reported': device.get('hostname') or None,
        'router_rule': device.get('gateway_name') or (block_rule or {}).get('name') or None,
        'local_dns': None,
    }
    fixed = bool(reservation and reservation.get('enabled', True) and ipv4 == reservation.get('ip'))
    blocked_rule = block_rule or {}
    ipv6_addresses = sorted(set(ipv6_addresses or []))
    return {
        'mac': mac,
        'addresses': {
            'ipv4': ipv4,
            'ipv6': ipv6_addresses,
            'ipv6_enabled_flag': device.get('ipv6_enabled'),
            'ipv6_address_status': 'read_from_dhcpv6_information' if ipv6_addresses else 'not_read_or_not_reported',
        },
        'connection': {
            'status': device.get('status', 'unknown'),
            'type': connection_type,
            'network': device.get('network') or None,
            'ssid_id': port if connection_type == 'wifi' else None,
            'band': band,
            'lan_port': port if connection_type == 'lan' else None,
            'lan_port_status': lan_port_status.get('status') if lan_port_status else None,
            'lan_port_client_count': lan_port_status.get('client_count') if lan_port_status else None,
            'lan_port_observed_at': lan_port_status.get('observed_at') if lan_port_status else None,
            'duration': device.get('duration') or None,
            'ipv6_lease': bool(ipv6_addresses),
        },
        'names': names,
        'category': tag or None,
        'reservation': {
            'fixed': fixed,
            'ip': reservation.get('ip') if reservation else None,
            'enabled': reservation.get('enabled') if reservation else None,
        },
        'access_control': {
            'listed': bool(blocked_rule),
            'active': blocked_rule.get('block_active') if blocked_rule else None,
            'rule_id': blocked_rule.get('block_rule') if blocked_rule else None,
        },
        'sources': {
            'mac': 'Huawei · lista de dispositivos LAN/Wi-Fi ou regra de filtro MAC',
            'ipv4': 'Huawei · lista de dispositivos LAN/Wi-Fi' if ipv4 else 'Não informado pelo gateway',
            'ipv6': 'Huawei · tabela DHCPv6 Information' if ipv6_addresses else 'DHCPv6 Information não leu um endereço para este MAC nesta sessão',
            'status': 'Huawei · lista de dispositivos LAN/Wi-Fi' if device.get('status') in ('online', 'offline') else 'Huawei · regra de filtro MAC' if device.get('status') == 'blocked' else 'Estado de conexão não informado',
            'client_reported': 'Huawei · nome informado pelo cliente' if names['client_reported'] else 'Não informado pelo cliente',
            'router_rule': 'Huawei · regra de bloqueio' if names['router_rule'] and blocked_rule else 'Huawei · Device Name' if names['router_rule'] else 'Não informado pelo gateway',
            'app_alias': 'Gateway Manager · cadastro local por MAC' if app_alias else 'Sem identificador local',
            'category': 'Gateway Manager · cadastro local por MAC' if tag else 'Sem categoria local',
            'reservation': 'Huawei · reserva DHCP IPv4' if reservation else 'Sem reserva lida nesta sessão',
            'network': 'Huawei · porta/SSID da conexão' if device.get('network') else 'Não informado pelo gateway',
            'lan_port_status': 'Huawei · System Information' if lan_port_status else 'Estado da porta LAN não lido nesta sessão',
            'duration': 'Huawei · duração informada pelo gateway' if device.get('duration') else 'Não informado pelo gateway',
        },
    }


def normalize_clients(devices, blocked, aliases, tags, reservations, ipv6_clients=(), lan_port_statuses=None):
    reservations_by_mac = {}
    for row in reservations:
        mac = str(row.get('mac', '')).lower()
        if row.get('enabled', True):
            reservations_by_mac[mac] = row
    blocked_by_mac = {str(row.get('mac', '')).lower(): row for row in blocked}
    ipv6_by_mac = {str(row.get('mac', '')).lower(): row.get('ipv6', []) for row in ipv6_clients}
    lan_port_statuses = lan_port_statuses or {}
    merged = {}
    source_devices = list(devices) + list(blocked)
    seen_macs = {str(device.get('mac', '')).lower() for device in source_devices}
    for row in ipv6_clients:
        mac = str(row.get('mac', '')).lower()
        if mac and mac not in seen_macs:
            source_devices.append({'mac': mac, 'ip': '', 'port': '', 'status': 'unknown', 'type': 'unknown', 'network': '', 'duration': '', 'hostname': '', 'gateway_name': ''})
            seen_macs.add(mac)
    for device in source_devices:
        mac = str(device.get('mac', '')).lower()
        block_rule = blocked_by_mac.get(mac)
        record = normalize_client(
            device,
            app_alias=aliases.get(mac, ''),
            tag=tags.get(mac, ''),
            reservation=reservations_by_mac.get(mac),
            block_rule=block_rule,
            ipv6_addresses=ipv6_by_mac.get(mac, []),
            lan_port_status=lan_port_statuses.get(str(device.get('port', '')).upper()),
        )
        if record is None:
            continue
        previous = merged.get(mac)
        if previous and previous['connection']['status'] in ('online', 'offline'):
            continue
        merged[mac] = record
    return sorted(merged.values(), key=lambda row: row['mac'])
