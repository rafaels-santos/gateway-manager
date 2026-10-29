"""Local DNS and DHCPv6 tables observed on EG8145X6-10 V5R024C10S106."""
import hashlib
import ipaddress
import json
import re
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_constructors
from .constants import STATIC_DNS_PATH, IPV6_RESERVATIONS_PATH

DNS_SOURCE = '/html/bbsp/common/dnshostslist.asp'
DNS_DOMAIN = 'InternetGatewayDevice.X_HW_DNS.HOSTS'
IPV6_DOMAIN = 'InternetGatewayDevice.LANDevice.1.X_HW_DHCPv6.Server.StaticAllocation'


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def interface_id(value):
    value = str(value).strip()
    if not re.fullmatch(r'[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){3}', value):
        raise GatewayError('Use um identificador de interface de 64 bits, como 0000:0000:0000:0001.')
    number = int(value.replace(':', '').zfill(16), 16) if all(len(p) == 4 for p in value.split(':')) else int(''.join(p.zfill(4) for p in value.split(':')), 16)
    if number in (0, 2**64 - 1):
        raise GatewayError('O identificador de interface não pode ser todo zero nem todo FFFF.')
    return ':'.join(part.zfill(4).lower() for part in value.split(':'))


def parse_allocations(page):
    recognized = bool(re.search(r'function\s+stConfig\s*\(\s*domain\s*,\s*InterfaceID\s*,\s*Chaddr\s*\)', page) and re.search(r'var\s+Configs\s*=\s*new\s+Array\s*\(', page))
    rows = []
    if not recognized:
        return rows, False
    array = re.search(r'var\s+Configs\s*=\s*new\s+Array\s*\((.*?)\)\s*(?:;|\r?\n)', page, re.S)
    if not array: return [], False
    for fields in parse_constructors(array[1], 'stConfig'):
        if len(fields) != 3 or not re.fullmatch(re.escape(IPV6_DOMAIN) + r'\.\d+', str(fields[0])):
            raise GatewayError('Objeto de reserva IPv6 não reconhecido.')
        mac = str(fields[2]).lower()
        if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
            raise GatewayError('MAC inválido na tabela IPv6.')
        iid = interface_id(fields[1])
        rows.append({'id': fields[0], 'mac': mac, 'identifier': iid, 'label': 'Reserva IPv6', 'value': f'{mac.upper()} → {iid}', 'field': 'StaticAllocation'})
    return rows, True


def parse_dns_source(source):
    recognized = bool(re.search(r'function\s+DnsHostsItemClass\s*\(\s*domain\s*,\s*IPAddress\s*,\s*DomainName\s*\)', source) and re.search(r'var\s+DnsHostsListTemp\s*=\s*new\s+Array\s*\(', source))
    rows = []
    if not recognized:
        return rows, False
    for fields in parse_constructors(source, 'DnsHostsItemClass'):
        if len(fields) != 3 or not re.fullmatch(re.escape(DNS_DOMAIN) + r'\.\d+', str(fields[0])):
            raise GatewayError('Objeto de DNS local não reconhecido.')
        try: address = str(ipaddress.ip_address(fields[1]))
        except ValueError: raise GatewayError('Endereço inválido na tabela DNS local.')
        name = str(fields[2]).strip().lower().rstrip('.')
        if not valid_hostname(name): raise GatewayError('Nome inválido na tabela DNS local.')
        rows.append({'id': fields[0], 'name': name, 'ip': address, 'label': 'DNS local', 'value': f'{name} → {address}', 'field': 'HOSTS'})
    return rows, True


def valid_hostname(name):
    return len(name) <= 253 and bool(name) and all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part) for part in name.split('.'))


class HuaweiLocalRecords:
    def dnsv6_config(self):
        from .constants import LAN_IPV6_PATH
        page = self.request(LAN_IPV6_PATH, max_redirects=0)
        rows = parse_constructors(page, 'IPv6DNSConfigClass')
        row = next((row for row in rows if len(row) == 5 and row[0] == 'InternetGatewayDevice.LANDevice.1.X_HW_IPv6Config'), None)
        if not row: raise GatewayError('Formato do DNSv6 da LAN não reconhecido ou sessão expirada.')
        servers = []
        for value in str(row[4]).split(','):
            if value:
                try: servers.append(str(ipaddress.IPv6Address(value)))
                except ValueError: raise GatewayError('Endereço DNSv6 inválido retornado pelo Huawei.')
        result = {'mode': row[2], 'primary': servers[0] if servers else '', 'secondary': servers[1] if len(servers) > 1 else ''}
        return {**result, 'expected': fingerprint(result), 'writable': 'p.IPv6DNSServers' in page and 'p.IPv6DNSConfigType' in page}

    def save_dnsv6(self, body):
        from .constants import LAN_IPV6_PATH
        if body.get('confirm') != 'APLICAR': raise GatewayError('Confirme a alteração de DNSv6.')
        with self.lock:
            current = self.dnsv6_config()
            if not current['writable'] or body.get('expected') != current['expected']:
                raise GatewayError('DNSv6 não disponível ou configuração mudou. Atualize antes de salvar.')
            values = []
            for key in ('primary', 'secondary'):
                raw = str(body.get(key) or '').strip()
                try: address = ipaddress.IPv6Address(raw) if raw else None
                except ValueError: raise GatewayError('Informe servidores DNS com endereços IPv6 válidos.')
                if address and (address.is_multicast or address.is_loopback or address.is_unspecified):
                    raise GatewayError('Este IPv6 não pode ser usado como servidor DNS.')
                values.append(str(address) if address else '')
            if not values[0]: raise GatewayError('Informe o servidor DNSv6 principal.')
            url = '/set.cgi?' + urllib.parse.urlencode({'p': 'InternetGatewayDevice.LANDevice.1.X_HW_IPv6Config', 'RequestFile': LAN_IPV6_PATH.lstrip('/')})
            self.request(url, {'p.IPv6DNSConfigType': 'Static', 'p.IPv6DNSServers': ','.join(value for value in values if value), 'x.X_HW_Token': self.config_token()}, referer=LAN_IPV6_PATH)
            updated = self.dnsv6_config()
            if updated['mode'].casefold() != 'static' or [updated['primary'], updated['secondary']] != values:
                raise GatewayError('O Huawei não confirmou os servidores DNSv6. Confira o painel antes de repetir.')
            return updated

    def local_records(self, kind):
        if kind == 'dns':
            page = self.request(STATIC_DNS_PATH, max_redirects=0)
            if 'GetDnsHostsList' not in page or DNS_DOMAIN not in page:
                raise GatewayError('A página de DNS local não corresponde ao formato validado; reconecte ou confira as capacidades.')
            rows, recognized = parse_dns_source(self.request(DNS_SOURCE, max_redirects=0))
            bindings = 'x.IPAddress' in page and 'x.DomainName' in page and 'OnApplyButtonClick' in page
            reason = 'Somente associações de nomes locais. Políticas e listas externas não são alteradas.'
        elif kind == 'ipv6':
            page = self.request(IPV6_RESERVATIONS_PATH, max_redirects=0)
            rows, recognized = parse_allocations(page)
            bindings = IPV6_DOMAIN in page and 'x.InterfaceID' in page and 'x.Chaddr' in page
            flags = parse_constructors(page, 'RaConfigInfoClass')
            managed = bool(flags and len(flags[0]) == 3 and flags[0][0] == 'InternetGatewayDevice.LANDevice.1.X_HW_RouterAdvertisement' and flags[0][1] == '1')
            bindings = bindings and managed
            reason = 'Reservas dependem de atribuição DHCPv6.' if managed else 'O Huawei informa SLAAC ou modo não confirmado. Reservas não terão efeito; a edição está indisponível neste modo.'
        else:
            raise GatewayError('Tabela local inválida.')
        return {'records': rows, 'recognized': recognized, 'writable': bool(recognized and bindings), 'reason': reason, 'expected': fingerprint(rows)}

    def save_local_record(self, body):
        kind, action = body.get('kind'), body.get('action')
        if kind not in ('dns', 'ipv6') or action not in ('save', 'delete') or body.get('confirm') != 'APLICAR':
            raise GatewayError('Tabela, ação ou confirmação inválida.')
        with self.lock:
            current = self.local_records(kind)
            if not current['writable']: raise GatewayError(current['reason'])
            if body.get('expected') != current['expected']:
                raise GatewayError('A tabela mudou desde a leitura. Atualize antes de aplicar.')
            domain = DNS_DOMAIN if kind == 'dns' else IPV6_DOMAIN
            path = STATIC_DNS_PATH if kind == 'dns' else IPV6_RESERVATIONS_PATH
            record_id = str(body.get('id') or '')
            target = next((row for row in current['records'] if row['id'] == record_id), None)
            if record_id and (not target or not re.fullmatch(re.escape(domain) + r'\.\d+', record_id)):
                raise GatewayError('Registro não encontrado; atualize a tabela.')
            if action == 'delete' and not target: raise GatewayError('Selecione um registro existente.')
            params = {}
            desired = None
            if action == 'save':
                if not target and len(current['records']) >= (20 if kind == 'dns' else 256):
                    raise GatewayError('Limite da tabela alcançado.')
                if kind == 'dns':
                    name = str(body.get('name') or '').strip().lower().rstrip('.')
                    if not valid_hostname(name): raise GatewayError('Informe um nome DNS válido, com até 253 caracteres.')
                    try: address = ipaddress.ip_address(str(body.get('ip') or '').strip())
                    except ValueError: raise GatewayError('Informe um IPv4 ou IPv6 válido.')
                    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
                        raise GatewayError('Este endereço não é permitido para um registro da LAN.')
                    # Scope records to addresses actually observed in the internal network.
                    dhcp = self.dhcp_config()
                    lan = ipaddress.IPv4Network((dhcp['lan_ip'], dhcp['mask']), strict=False)
                    if address.version == 4 and (address not in lan or address in (lan.network_address, lan.broadcast_address)):
                        raise GatewayError('Use um endereço utilizável da LAN atual para este registro local.')
                    leases = getattr(self, 'network_pages', {}).get('dhcpv6_information', {}).get('leases', [])
                    if address.version == 6 and not any(str(address) in item.get('ipv6', []) for item in self.dhcpv6_clients) and not any(str(address) == item.get('ipv6') for item in leases) and address not in ipaddress.IPv6Network('fc00::/7'):
                        raise GatewayError('Use um IPv6 local ULA ou um endereço já observado na LAN.')
                    desired = {'name': name, 'ip': str(address)}
                    if any(row['id'] != record_id and row['name'].casefold() == name and ipaddress.ip_address(row['ip']).version == address.version for row in current['records']):
                        raise GatewayError('Já existe um endereço desta família para esse nome DNS.')
                    params = {'x.DomainName': name, 'x.IPAddress': str(address)}
                else:
                    mac = str(body.get('mac') or '').strip().lower()
                    if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac) or int(mac[:2], 16) & 1 or mac == '00:00:00:00:00:00':
                        raise GatewayError('Informe um MAC unicast válido.')
                    desired = {'mac': mac, 'identifier': interface_id(body.get('identifier', ''))}
                    if any(row['id'] != record_id and (row['mac'] == mac or row['identifier'] == desired['identifier']) for row in current['records']):
                        raise GatewayError('Esse MAC ou identificador já está reservado.')
                    params = {'x.Chaddr': mac, 'x.InterfaceID': desired['identifier']}
            keys = ('name', 'ip') if kind == 'dns' else ('mac', 'identifier')
            signature = lambda row: tuple(row[key] for key in keys)
            expected = [signature(row) for row in current['records'] if row['id'] != record_id]
            if desired: expected.append(signature(desired))
            if action == 'delete':
                url = '/del.cgi?' + urllib.parse.urlencode({'x': domain, 'RequestFile': path.lstrip('/')})
                params = {record_id: ''}
            else:
                url = ('/set.cgi?' if target else '/add.cgi?') + urllib.parse.urlencode({'x': record_id or domain, 'RequestFile': path.lstrip('/')})
            params['x.X_HW_Token'] = self.config_token()
            self.request(url, params, referer=path)
            updated = self.local_records(kind)
            if not updated['recognized'] or sorted(signature(row) for row in updated['records']) != sorted(expected):
                raise GatewayError('O Huawei não confirmou a tabela esperada. Confira o painel antes de repetir a operação.')
            return updated
