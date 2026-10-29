from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request
import datetime

from .errors import GatewayError
from .capabilities import record_capability
from .network_readers import parse_dhcpv6_clients, parse_ipv6_reservations, parse_network_page, parse_static_dns_records


KNOWN_READ_PAGES = {
    'lan_address': ('Endereço LAN', '/html/bbsp/dhcp/dhcp.asp'),
    'dhcpv6_ra': ('DHCPv6 e RA', '/html/bbsp/lanaddress/lanaddress.asp'),
    'ipv6_reservations': ('Reservas IPv6', '/html/bbsp/dhcpstaticaddr/dhcpstaticaddress.asp'),
    'static_dns': ('DNS estático local', '/html/bbsp/dnsconfiguration/dnsconfigcommon.asp'),
    'port_isolation': ('Isolamento de portas', '/html/bbsp/portinfo/portisolate.asp'),
    'mesh_topology': ('Topologia EasyMesh', '/html/amp/wlaninfo/easymeshTopo.asp'),
    'port_mode': ('Modo Layer 2/3', '/html/bbsp/layer3/layer3.asp'),
    'dhcpv6_information': ('Concessões DHCPv6', '/html/bbsp/dhcpv6info/dhcpv6info.asp'),
    'wifi_radio': ('Rádios 2,4 e 5 GHz', '/html/amp/wlanadv/wlanadvance_api.asp'),
    'system_information': ('Portas Ethernet', '/html/amp/ethinfo/ethinfo.asp'),
}
MENU_DISCOVERED_PAGES = {
    'wifi_coverage': ('Wi-Fi Coverage', 'wi fi coverage'),
}


class _MenuLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self._href = dict(attrs).get('href')
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self._href is not None:
            self.links.append((self._href, ' '.join(' '.join(self._text).split())))
            self._href = None
            self._text = []


class _FormShape(HTMLParser):
    SENSITIVE = re.compile(r'password|passwd|psk|secret|token|private.?key', re.I)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag.lower() == 'title':
            self.in_title = True
        if tag.lower() not in ('input', 'select', 'textarea', 'button'):
            return
        name = attributes.get('name', '')
        field_id = attributes.get('id', '')
        kind = attributes.get('type', tag.lower()).lower()
        if self.SENSITIVE.search(name) or self.SENSITIVE.search(field_id) or kind == 'password' or kind == 'hidden':
            return
        label = name or field_id
        if label and label not in self.controls:
            self.controls.append(label[:100])

    def handle_endtag(self, tag):
        if tag.lower() == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def _safe_internal_path(href):
    parsed = urllib.parse.urlsplit(href or '')
    if parsed.scheme or parsed.netloc or not parsed.path or '\\' in parsed.path:
        return None
    resolved = urllib.parse.urlsplit(urllib.parse.urljoin('/index.asp', href))
    if not resolved.path.startswith('/html/') or not resolved.path.casefold().endswith('.asp') or resolved.query not in ('', '2G', '5G'):
        return None
    return resolved.path + (('?' + resolved.query) if resolved.query else '')


def _discover_menu_pages(page):
    parser = _MenuLinks()
    parser.feed(page)
    discovered = {}
    for href, label in parser.links:
        normalized = re.sub(r'[^a-z0-9]+', ' ', label.casefold()).strip()
        for feature, (_, phrase) in MENU_DISCOVERED_PAGES.items():
            if phrase in normalized and feature not in discovered:
                path = _safe_internal_path(href)
                if path:
                    discovered[feature] = (label, path)
    return discovered


def inspect_network_pages(gateway, features=None):
    """Read documented LAN pages and menu-discovered information pages; never submit forms."""
    from .huawei.observed_readers import dhcpv6_leases, mesh_nodes
    requested = set(features) if features is not None else None
    allowed = set(KNOWN_READ_PAGES) | set(MENU_DISCOVERED_PAGES)
    if requested is not None and (not requested or not requested <= allowed):
        raise GatewayError('Recurso de inventário inválido.')
    pages = {key: value for key, value in KNOWN_READ_PAGES.items() if requested is None or key in requested}
    try:
        menu = gateway.request('/index.asp', max_redirects=0) if requested is None or requested & set(MENU_DISCOVERED_PAGES) else ''
        pages.update({key: value for key, value in _discover_menu_pages(menu).items() if requested is None or key in requested})
    except GatewayError as error:
        menu_error = str(error)
    else:
        menu_error = ''

    results = []
    for feature, (label, path) in pages.items():
        try:
            html = gateway.request(path, max_redirects=0)
            if 'txt_Password' in html or re.search(r'<title[^>]*>[^<]*(?:login|sign in)[^<]*</title>', html, re.I):
                raise GatewayError('O Huawei retornou a tela de login; reconecte o app para inspecionar esta página.')
            shape = _FormShape()
            shape.feed(html)
            observations = parse_network_page(feature, html)
            dhcpv6_clients = parse_dhcpv6_clients(html) if feature == 'dhcpv6_information' else []
            leases, leases_recognized = dhcpv6_leases(html) if feature == 'dhcpv6_information' else ([], False)
            nodes, mesh_recognized = mesh_nodes(html) if feature == 'mesh_topology' else ([], False)
            ipv6_reservations, ipv6_reservations_recognized = parse_ipv6_reservations(html) if feature == 'ipv6_reservations' else ([], False)
            parser_recognized = bool(observations or dhcpv6_clients)
            if feature == 'static_dns':
                dns = gateway.static_dns()
                observations, parser_recognized = dns['records'], dns['recognized']
            elif feature == 'ipv6_reservations':
                parser_recognized = ipv6_reservations_recognized
            elif feature == 'dhcpv6_information':
                parser_recognized = bool(dhcpv6_clients) or leases_recognized
            elif feature == 'mesh_topology':
                parser_recognized = bool(observations) or mesh_recognized
            if feature == 'dhcpv6_information':
                gateway.dhcpv6_clients = dhcpv6_clients
            if feature == 'system_information':
                gateway.lan_port_statuses = {item['port']: {'status': item['status'], 'client_count': item.get('client_count')}
                                             for item in observations if item.get('port')}
            has_readings = parser_recognized
            parser_status = 'parsed' if has_readings else 'unrecognized'
            if feature in getattr(gateway, 'capability_matrix', {}):
                gateway.capability_matrix[feature]['evidence'] = path
            reading_count = len(observations)
            if feature == 'dhcpv6_information':
                reading_count = len(leases) + len(dhcpv6_clients)
            elif feature == 'ipv6_reservations':
                reading_count = len(ipv6_reservations)
            record_capability(gateway, feature, 'read', 'available' if has_readings else 'unrecognized',
                              f'{reading_count} registro(s) lido(s).' if has_readings else 'Página acessível, mas não contém campos reconhecidos por este parser; nenhum valor foi inferido.')
            results.append({'id': feature, 'label': label, 'status': 'available', 'path': path,
                            'title': ' '.join(' '.join(shape.title_parts).split())[:160],
                            'controls': shape.controls[:80],
                            'parser_status': parser_status,
                            'observations': observations,
                            'clients': dhcpv6_clients,
                            'leases': leases,
                            'nodes': nodes,
                            'reservations': ipv6_reservations,
                            'recognized': has_readings,
                            'message': 'Página lida sem enviar formulários. Valores aparecem somente para campos allowlist reconhecidos.'})
        except GatewayError as error:
            if feature == 'system_information': gateway.lan_port_statuses = {}
            if feature == 'dhcpv6_information': gateway.dhcpv6_clients = []
            status = 'denied' if re.search(r'HTTP (?:401|403)', str(error)) else 'unavailable'
            record_capability(gateway, feature, 'read', status, str(error))
            results.append({'id': feature, 'label': label, 'status': status, 'path': path, 'controls': [], 'message': str(error)})

    for feature, (label, _) in MENU_DISCOVERED_PAGES.items():
        if requested is not None and feature not in requested:
            continue
        if feature in pages:
            continue
        message = 'Link não encontrado no menu desta conta.' if not menu_error else 'Menu não pôde ser lido: ' + menu_error
        record_capability(gateway, feature, 'read', 'unavailable', message)
        results.append({'id': feature, 'label': label, 'status': 'unavailable', 'path': None, 'controls': [], 'message': message})
    sampled_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache = getattr(gateway, 'network_pages', {})
    for result in results:
        result['sampled_at'] = sampled_at
        cache[result['id']] = result
        if result['id'] == 'system_information' and result['status'] == 'available':
            for port in gateway.lan_port_statuses.values(): port['observed_at'] = sampled_at
    gateway.network_pages = cache
    return results
