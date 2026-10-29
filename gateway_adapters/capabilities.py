from copy import deepcopy


FEATURES = {
    'clients': ('Dispositivos', 'Lista autenticada de dispositivos LAN/Wi-Fi', True, False),
    'reservations_ipv4': ('Reservas IPv4', '/html/bbsp/dhcpstatic/dhcpstatic.asp', True, True),
    'dhcp_ipv4': ('DHCP IPv4', '/html/bbsp/dhcpservercfg/dhcp2.asp', True, True),
    'dns_lan': ('DNS entregue na LAN', '/html/bbsp/dhcpservercfg/dhcp2.asp · lista DNS do DHCP', True, True),
    'wifi_ssids': ('Redes Wi-Fi', '/html/amp/wlanbasic/WlanBasic.asp?2G', True, True),
    'wifi_security': ('Autenticação Wi-Fi', 'Propriedades de autenticação por SSID; chave preservada', True, True),
    'wifi_access_policy': ('Bloqueio MAC Wi-Fi', '/html/bbsp/wlanmacfilter/wlanmacfilter.asp', True, True),
    'user_logs': ('User Logs', '/html/ssmp/userlog/logview.asp', True, False),
    'ap_logs': ('AP Logs', '/html/ssmp/aplog/aplogview.asp', True, False),
    'system_information': ('Portas Ethernet', '/html/amp/ethinfo/ethinfo.asp', True, False),
    'dhcpv6_information': ('DHCPv6 Information', None, True, False),
    'lan_address': ('Endereço LAN', '/html/bbsp/dhcp/dhcp.asp · mudança conjunta com DHCP e recuperação', True, True),
    'wifi_password': ('Senha Wi-Fi', 'PreSharedKey.1.KeyPassphrase · confirmação sem devolver a chave', True, True),
    'dhcpv6_ra': ('DHCPv6 e RA', '/html/bbsp/lanaddress/lanaddress.asp', True, False),
    'ipv6_reservations': ('Reservas IPv6', '/html/bbsp/dhcpstaticaddr/dhcpstaticaddress.asp', True, True),
    'static_dns': ('DNS estático local', '/html/bbsp/dnsconfiguration/dnsconfigcommon.asp', True, True),
    'dns_ipv6': ('DNS IPv6 da LAN', 'InternetGatewayDevice.LANDevice.1.X_HW_IPv6Config', True, True),
    'port_isolation': ('Isolamento de portas', '/html/bbsp/portinfo/portisolate.asp', True, False),
    'mesh_topology': ('Topologia EasyMesh', '/html/amp/wlaninfo/easymeshTopo.asp', True, False),
    'port_mode': ('Modo Layer 2/3', 'Link interno descoberto no menu da sessão', True, False),
    'wifi_radio': ('Parâmetros de rádio', '/html/amp/wlanadv/wlanadvance_api.asp · potência para personalização validada', True, True),
    'wifi_coverage': ('Cobertura Wi-Fi', 'Link interno descoberto no menu da sessão', True, False),
}


def new_session_capabilities():
    result = {}
    for key, (label, evidence, read_implemented, write_implemented) in FEATURES.items():
        result[key] = {
            'label': label,
            'evidence': evidence,
            'read': {
                'implementation': 'implemented' if read_implemented else 'not_implemented',
                'session': 'not_checked',
                'reason': 'Nenhuma leitura foi feita nesta sessão.' if read_implemented else 'Leitura ainda não implementada ou inspecionada; não inferir disponibilidade pelo modelo.',
            },
            'write': {
                'implementation': 'implemented' if write_implemented else 'not_offered',
                'session': 'not_checked' if write_implemented else 'not_applicable',
                'reason': 'A permissão só é confirmada após operação e releitura bem-sucedidas.' if write_implemented else 'O aplicativo não oferece escrita para este recurso.',
            },
        }
    return result


def record_capability(gateway, feature, operation, result, reason=''):
    if result not in ('available', 'verified', 'denied', 'unavailable', 'unrecognized', 'not_checked', 'not_applicable'):
        return
    matrix = getattr(gateway, 'capability_matrix', None)
    if matrix is None or feature not in matrix or operation not in ('read', 'write'):
        return
    cell = matrix[feature][operation]
    if cell['implementation'] == 'not_offered' or (cell['implementation'] == 'not_implemented' and operation == 'write'):
        return
    cell['session'] = result
    if reason:
        cell['reason'] = reason


def capability_snapshot(gateway):
    return {
        'model': gateway.model_id,
        'model_label': gateway.model_label,
        'firmware': (getattr(gateway, 'identity', {}) or {}).get('firmware'),
        'hardware': (getattr(gateway, 'identity', {}) or {}).get('hardware'),
        'access_profile': 'Sessão autenticada; perfil e permissões da conta não são identificados pelo modelo.',
        'features': deepcopy(getattr(gateway, 'capability_matrix', new_session_capabilities())),
    }
