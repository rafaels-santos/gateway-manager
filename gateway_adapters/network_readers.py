"""Read-only, allowlisted field extraction for Huawei internal-network pages."""
from html.parser import HTMLParser
import ipaddress
import re


SENSITIVE = re.compile(r'password|passwd|psk|secret|token|private.?key|serial|pon.?sn|loid', re.I)


class _Controls(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.labels = {}
        self._label_for = None
        self._label_text = []
        self._select = None
        self._selected_option = False
        self._textarea = None
        self._option = None
        self._script_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self._script_depth += 1
            return
        if self._script_depth:
            return
        if tag == 'label':
            self._label_for = attrs.get('for')
            self._label_text = []
        if tag == 'input':
            kind = attrs.get('type', 'text').lower()
            name, field_id = attrs.get('name', ''), attrs.get('id', '')
            if kind not in ('hidden', 'password', 'submit', 'button', 'reset', 'image') and not SENSITIVE.search(name + ' ' + field_id):
                self.rows.append({'name': name, 'id': field_id, 'kind': kind,
                                  'value': attrs.get('value', ''), 'checked': 'checked' in attrs})
        elif tag == 'select':
            self._select = {'name': attrs.get('name', ''), 'id': attrs.get('id', ''), 'kind': 'select', 'value': ''}
            self._selected_option = False
        elif tag == 'option' and self._select is not None:
            self._option = {'value': attrs.get('value', ''), 'selected': 'selected' in attrs, 'text': []}
        elif tag == 'textarea':
            self._textarea = {'name': attrs.get('name', ''), 'id': attrs.get('id', ''), 'kind': 'textarea', 'value': []}

    def handle_endtag(self, tag):
        if tag == 'script' and self._script_depth:
            self._script_depth -= 1
            return
        if self._script_depth:
            return
        if tag == 'option' and self._option is not None and self._select is not None:
            if self._option['selected'] or not self._selected_option:
                self._select['value'] = self._option['value'] or ' '.join(self._option['text']).strip()
                self._selected_option = self._option['selected'] or self._selected_option
            self._option = None
        elif tag == 'select' and self._select is not None:
            self.rows.append(self._select)
            self._select = None
            self._selected_option = False
        elif tag == 'textarea' and self._textarea is not None:
            self._textarea['value'] = ''.join(self._textarea['value']).strip()
            self.rows.append(self._textarea)
            self._textarea = None
        elif tag == 'label' and self._label_for:
            self.labels[self._label_for] = ' '.join(' '.join(self._label_text).split())[:120]
            self._label_for = None
            self._label_text = []

    def handle_data(self, data):
        if self._script_depth:
            return
        if self._label_for is not None:
            self._label_text.append(data)
        if self._option is not None:
            self._option['text'].append(data)
        if self._textarea is not None:
            self._textarea['value'].append(data)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._script_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._script_depth += 1
        elif not self._script_depth:
            if tag == 'table':
                self._table = []
            elif tag == 'tr' and self._table is not None:
                self._row = []
            elif tag in ('th', 'td') and self._row is not None:
                self._cell = []

    def handle_endtag(self, tag):
        if tag == 'script' and self._script_depth:
            self._script_depth -= 1
        elif not self._script_depth:
            if tag in ('th', 'td') and self._cell is not None and self._row is not None:
                self._row.append(' '.join(' '.join(self._cell).split()))
                self._cell = None
            elif tag == 'tr' and self._row is not None:
                if self._row:
                    self._table.append(self._row)
                self._row = None
            elif tag == 'table' and self._table is not None:
                if self._table:
                    self.tables.append(self._table)
                self._table = None

    def handle_data(self, data):
        if not self._script_depth and self._cell is not None:
            self._cell.append(data)


def parse_dhcpv6_clients(html):
    """Extract IPv6 client addresses only from tables with explicit MAC/IPv6 headers."""
    parser = _Tables()
    parser.feed(html)
    clients = {}
    for table_rows in parser.tables:
        header_index = None
        mac_col = ipv6_col = None
        for row_index, row in enumerate(table_rows):
            normalized = [re.sub(r'[^a-z0-9]+', ' ', cell.casefold()).strip() for cell in row]
            mac = next((i for i, cell in enumerate(normalized) if re.search(r'\bmac(?: address)?\b|\b(?:hardware|physical) address\b', cell)), None)
            ipv6 = next((i for i, cell in enumerate(normalized) if re.search(r'\bipv6(?: ?address)?\b|\baddress ipv6\b|^ip address$', cell)), None)
            if mac is not None and ipv6 is not None:
                header_index, mac_col, ipv6_col = row_index, mac, ipv6
                break
        if header_index is None:
            continue
        for row in table_rows[header_index + 1:]:
            if max(mac_col, ipv6_col) >= len(row):
                continue
            mac = row[mac_col].strip().lower().replace('-', ':')
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                continue
            raw_ipv6 = row[ipv6_col].strip()
            try:
                address = str(ipaddress.ip_interface(raw_ipv6).ip if '/' in raw_ipv6 else ipaddress.IPv6Address(raw_ipv6))
            except ValueError:
                continue
            clients.setdefault(mac, set()).add(address)
    return [{'mac': mac, 'ipv6': sorted(addresses)} for mac, addresses in sorted(clients.items())]


def parse_ipv6_reservations(html):
    """Read IPv6 reservation rows only when MAC and interface/address headers are explicit."""
    from .huawei.local_records import parse_allocations
    typed, recognized = parse_allocations(html)
    if recognized:
        return typed, True
    parser = _Tables()
    parser.feed(html)
    reservations, seen, recognized = [], set(), False
    for table_number, rows in enumerate(parser.tables, 1):
        mac_col = identifier_col = None
        data_start = None
        for row_index, row in enumerate(rows):
            headers = [re.sub(r'[^a-z0-9]+', ' ', cell.casefold()).strip() for cell in row]
            mac_col = next((i for i, h in enumerate(headers) if h in ('mac', 'mac address', 'hardware address')), None)
            identifier_col = next((i for i, h in enumerate(headers) if h in ('interface id', 'interface identifier', 'ipv6 address', 'address ipv6')), None)
            if mac_col is not None and identifier_col is not None:
                data_start = row_index + 1
                recognized = True
                break
        if data_start is None:
            continue
        for row in rows[data_start:]:
            if max(mac_col, identifier_col) >= len(row):
                continue
            mac = row[mac_col].strip().lower().replace('-', ':')
            identifier = row[identifier_col].strip()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or not identifier or len(identifier) > 80:
                continue
            if ':' in identifier:
                try:
                    identifier = str(ipaddress.IPv6Address(identifier))
                except ValueError:
                    continue
            elif not re.fullmatch(r'[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,7}', identifier):
                continue
            key = (mac, identifier.lower())
            if key in seen:
                continue
            seen.add(key)
            reservations.append({'mac': mac, 'identifier': identifier, 'label': 'Reserva IPv6',
                                'value': f'{mac.upper()} → {identifier}', 'field': f'tabela {table_number}'})
    return reservations, recognized


def parse_static_dns_records(html):
    """Read local DNS rows only when the table explicitly identifies both columns."""
    parser = _Tables()
    parser.feed(html)
    records, seen, recognized = [], set(), False
    for table_number, rows in enumerate(parser.tables, 1):
        domain_col = ip_col = None
        data_start = None
        for row_index, row in enumerate(rows):
            headers = [re.sub(r'[^a-z0-9]+', ' ', cell.casefold()).strip() for cell in row]
            if any('template' in header or 'search list' in header or 'wan' in header for header in headers):
                continue
            domain_col = next((index for index, header in enumerate(headers) if header in ('domain name', 'host name', 'hostname')), None)
            ip_col = next((index for index, header in enumerate(headers) if header in ('ip address', 'ipv4 address')), None)
            if domain_col is not None and ip_col is not None:
                data_start = row_index + 1
                recognized = True
                break
        if data_start is None:
            continue
        for row in rows[data_start:]:
            if max(domain_col, ip_col) >= len(row):
                continue
            domain = _clean_value(row[domain_col], 'hostname')
            address = _clean_value(row[ip_col], 'ipv4')
            if not domain or not address or (domain, address) in seen:
                continue
            seen.add((domain, address))
            records.append({'name': domain, 'ip': address, 'label': 'DNS local',
                            'value': f'{domain} → {address}', 'field': f'tabela {table_number}'})
    return records, recognized


def parse_system_lan_ports(html):
    """Read only explicitly named LAN1–LAN4 rows from a table with port/status headers."""
    parser = _Tables()
    parser.feed(html)
    ports, seen = [], set()
    port_names = {'lan 1': 'LAN1', 'lan1': 'LAN1', 'lan 2': 'LAN2', 'lan2': 'LAN2',
                  'lan 3': 'LAN3', 'lan3': 'LAN3', 'lan 4': 'LAN4', 'lan4': 'LAN4'}
    for rows in parser.tables:
        port_col = status_col = count_col = None
        data_start = None
        for row_index, row in enumerate(rows):
            headers = [re.sub(r'[^a-z0-9]+', ' ', cell.casefold()).strip() for cell in row]
            port_col = next((i for i, h in enumerate(headers) if h in ('port', 'port name', 'interface')), None)
            status_col = next((i for i, h in enumerate(headers) if h in ('status', 'link status', 'connection status')), None)
            count_col = next((i for i, h in enumerate(headers) if h in ('client count', 'connected clients', 'number of clients')), None)
            if port_col is not None and status_col is not None:
                data_start = row_index + 1
                break
        if data_start is None:
            continue
        for row in rows[data_start:]:
            if max(port_col, status_col) >= len(row):
                continue
            normalized_port = re.sub(r'\s+', ' ', row[port_col].casefold().strip())
            port = port_names.get(normalized_port)
            status = row[status_col].strip()
            status_key = re.sub(r'[^a-z]+', '', status.casefold())
            if not port or not status or len(status) > 40:
                continue
            if status_key not in ('up', 'down', 'connected', 'disconnected', 'enabled', 'disabled', 'active', 'inactive', 'linkup', 'linkdown'):
                continue
            item = {'port': port, 'status': status, 'label': f'{port} · status', 'value': status, 'field': 'System Information'}
            if count_col is not None and count_col < len(row) and re.fullmatch(r'\d{1,3}', row[count_col].strip()):
                item['client_count'] = int(row[count_col].strip())
                item['value'] += f" · {item['client_count']} cliente(s)"
            if (port, status_key, item['value']) not in seen:
                seen.add((port, status_key, item['value']))
                ports.append(item)
    return ports


RULES = {
    'lan_address': [
        ('Endereço IPv4 LAN', re.compile(r'(?:lan.*(?:ip|address)|(?:ip|address).*lan|primary.*ip|(?:^|[^a-z])ip.?address(?:$|[^a-z]))', re.I), 'ipv4'),
        ('Máscara LAN', re.compile(r'(?:subnet.?mask|net.?mask|lan.*mask)', re.I), 'ipv4'),
        ('Endereço IPv4 secundário', re.compile(r'(?:secondary.*(?:ip|address)|(?:ip|address).*secondary)', re.I), 'ipv4'),
    ],
    'dhcpv6_ra': [
        ('Servidor DHCPv6', re.compile(r'dhcpv6.*(?:enable|server)|(?:enable|server).*dhcpv6', re.I), 'flag'),
        ('Router Advertisement', re.compile(r'\bra(?:enable|mode|$|[^a-z])|router.?advertisement', re.I), 'text'),
        ('Modo de atribuição IPv6', re.compile(r'(?:slaac|address.?assign|assign.?mode|dhcpv6.*mode)', re.I), 'text'),
        ('DNS IPv6 da LAN', re.compile(r'(?:lan.*dns|dns.*(?:ipv6|lan))', re.I), 'ipv6_or_text'),
        ('MTU LAN IPv6', re.compile(r'(?:ipv6.*mtu|mtu.*ipv6)', re.I), 'integer'),
        ('ULA', re.compile(r'(?:ula|unique.?local)', re.I), 'ipv6_or_text'),
    ],
    'ipv6_reservations': [
        ('Identificador de interface IPv6', re.compile(r'(?:interface.?id|i.?id|ipv6.*(?:address|host))', re.I), 'ipv6_or_text'),
    ],
    'static_dns': [
        ('Nome DNS local', re.compile(r'(?:local.*(?:domain|host)|host.?name|static.*domain)', re.I), 'hostname'),
        ('Endereço DNS local', re.compile(r'(?:local.*(?:ip|address)|static.*(?:ip|address)|record.*ip)', re.I), 'ipv4'),
    ],
    'port_isolation': [
        ('Modo Layer 2/3', re.compile(r'(?:layer.?[23]|port.?mode|mode.?port)', re.I), 'text'),
        ('Isolamento de porta LAN', re.compile(r'(?:port.?isolation|isolation.?port|lan[1-4]|port[1-4].*(?:isolate|enable)|(?:isolate|enable).*port[1-4])', re.I), 'flag'),
    ],
    'mesh_topology': [
        ('Papel EasyMesh', re.compile(r'(?:mesh.*role|role.*mesh|device.?role)', re.I), 'text'),
        ('Contagem de clientes por banda/porta', re.compile(r'(?:client|sta).*(?:count|number)|(?:count|number).*(?:client|sta)', re.I), 'integer'),
        ('Limiar RSSI', re.compile(r'(?:rssi|signal).*(?:threshold|limit)|(?:threshold|limit).*(?:rssi|signal)', re.I), 'integer'),
    ],
}


def _clean_value(raw, kind):
    value = str(raw or '').strip()
    if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
        return None
    if kind == 'ipv4':
        try:
            return str(ipaddress.IPv4Address(value))
        except ValueError:
            return None
    if kind == 'integer':
        return value if re.fullmatch(r'\d{1,5}', value) else None
    if kind == 'flag':
        normalized = value.casefold()
        if normalized in ('1', 'on', 'yes', 'true', 'enabled', 'enable'):
            return 'Ativado'
        if normalized in ('0', 'off', 'no', 'false', 'disabled', 'disable'):
            return 'Desativado'
        return None
    if kind == 'hostname':
        return value if re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', value) else None
    if kind == 'ipv6_or_text':
        if ':' in value:
            try:
                return str(ipaddress.IPv6Address(value))
            except ValueError:
                return None
        return value if re.fullmatch(r'[A-Za-z0-9_. -]{1,80}', value) else None
    return value if re.fullmatch(r'[A-Za-z0-9_.:/ -]{1,100}', value) else None


def parse_network_page(feature, html, labels=None):
    """Extract only explicitly allowlisted LAN fields; unknown layouts yield no values."""
    from .huawei.observed_readers import observed_fields
    typed = observed_fields(feature, html)
    if feature == 'system_information':
        return typed + parse_system_lan_ports(html)
    if typed:
        return typed
    if feature == 'dhcpv6_information':
        return []
    if feature == 'ipv6_reservations':
        reservations, _ = parse_ipv6_reservations(html)
        return reservations
    if feature == 'system_information':
        return parse_system_lan_ports(html)
    if feature == 'static_dns':
        records, _ = parse_static_dns_records(html)
        if records:
            return records
    rules = RULES.get(feature, [])
    if not rules:
        return []
    parser = _Controls()
    parser.feed(html)
    merged_labels = dict(parser.labels)
    merged_labels.update(labels or {})
    observations, seen = [], set()
    for control in parser.rows:
        if control['kind'] == 'radio' and not control.get('checked'):
            continue
        key = f"{control['name']} {control['id']} {merged_labels.get(control['id'], '')}".strip()
        if SENSITIVE.search(key):
            continue
        # Values assigned by page JavaScript are not the default HTML values.
        if control['id'] and re.search(r'(?:setCheck|setSelect|setText)\s*\(\s*[\'\"]' + re.escape(control['id']) + r'[\'\"]', html):
            continue
        for label, pattern, value_kind in rules:
            if not pattern.search(key):
                continue
            raw = 'true' if control.get('checked') and control['kind'] in ('checkbox', 'radio') else 'false' if control['kind'] in ('checkbox', 'radio') else control.get('value', '')
            value = _clean_value(raw, value_kind)
            if value is None or (label, value) in seen:
                break
            seen.add((label, value))
            observations.append({'label': label, 'value': value, 'field': (control['name'] or control['id'])[:100]})
            break
    return observations
