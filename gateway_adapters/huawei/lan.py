import ipaddress
import re
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_dhcp_page, parse_reservations_page
from ..network_readers import parse_network_page, parse_ipv6_reservations, parse_static_dns_records
from .constants import DHCP_PATH, DOMAIN, LAN_DOMAIN, PATH, STATIC_DNS_PATH, LAN_IPV6_PATH, IPV6_RESERVATIONS_PATH, PORT_ISOLATION_PATH


class HuaweiLANOperations:
    def reservations_page(self):
        page = self.request(PATH)
        if 'DHCPStaticAddress' not in page or 'onttoken' not in page:
            raise GatewayError('Sessão expirada ou tela de reservas indisponível para esta conta.')
        return page
    def dhcp_config(self):
        return parse_dhcp_page(self.request(DHCP_PATH))
    def static_dns(self):
        return self.local_records('dns')
    def ipv6_network(self):
        ipv6_page = self.request(LAN_IPV6_PATH, max_redirects=0)
        login_pattern = r'<title[^>]*>[^<]*(?:login|sign in)[^<]*</title>'
        if 'txt_Password' in ipv6_page or re.search(login_pattern, ipv6_page, re.I):
            raise GatewayError('Sessão expirada; conecte-se novamente para consultar IPv6.')
        observations = parse_network_page('dhcpv6_ra', ipv6_page)
        local = self.local_records('ipv6')
        return {'observations': observations, 'settings_recognized': bool(observations),
                'reservations': local['records'], 'reservations_recognized': local['recognized'], 'local_records': local}
    def port_isolation(self):
        page = self.request(PORT_ISOLATION_PATH, max_redirects=0)
        if 'txt_Password' in page or re.search(r'<title[^>]*>[^<]*(?:login|sign in)[^<]*</title>', page, re.I):
            raise GatewayError('Sessão expirada; conecte-se novamente para consultar o isolamento de portas.')
        observations = parse_network_page('port_isolation', page)
        return {'observations': observations, 'recognized': bool(observations)}
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
    def reservations(self):
        page = self.reservations_page()
        return parse_reservations_page(page), page
    def save(self, body):
        with self.lock:
            try:
                ip = str(ipaddress.IPv4Address(body.get('ip', '')))
            except ValueError:
                raise GatewayError('Informe um IPv4 válido.')
            mac = str(body.get('mac', '')).lower().strip()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac):
                raise GatewayError('Informe um MAC válido, por exemplo aa:bb:cc:dd:ee:ff.')
            requested_enabled = body.get('enabled')
            if 'enabled' in body and not isinstance(requested_enabled, bool):
                raise GatewayError('Estado da reserva inválido.')
            rows, page = self.reservations()
            domain = body.get('id', '')
            if domain and domain not in [r['id'] for r in rows]:
                raise GatewayError('Reserva não encontrada; atualize a lista.')
            existing = next((row for row in rows if row['id'] == domain), None)
            enabled = requested_enabled if requested_enabled is not None else (existing['enabled'] if existing else True)
            if any(r['id'] != domain and (r['ip'] == ip or r['mac'] == mac) for r in rows):
                raise GatewayError('Este IP ou MAC já está reservado.')
            token = self.request('/html/ssmp/common/GetRandToken.asp', {}, xhr=True).strip()
            if not re.fullmatch(r'[a-zA-Z0-9]{16,256}', token):
                raise GatewayError('Token de operação indisponível; nenhuma alteração foi feita.')
            action = 'set.cgi' if domain else 'add.cgi'
            target = domain or DOMAIN
            url = '/' + action + '?' + urllib.parse.urlencode({'x': target, 'RequestFile': PATH.lstrip('/')})
            self.request(url, {'x.Yiaddr': ip, 'x.Chaddr': mac, 'x.Enable': str(int(enabled)), 'x.X_HW_Token': token})
            updated, _ = self.reservations()
            if not any(r['ip'] == ip and r['mac'] == mac and r['enabled'] == enabled for r in updated):
                raise GatewayError('O gateway não confirmou a reserva. Verifique a interface original antes de tentar novamente.')

    def delete_reservation(self, body):
        with self.lock:
            domain = str(body.get('id', '')).strip()
            if body.get('confirm') != 'REMOVER' or not re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.LANHostConfigManagement\.DHCPStaticAddress\.\d+', domain):
                raise GatewayError('Reserva ou confirmação inválida.')
            rows, _ = self.reservations()
            target = next((row for row in rows if row['id'] == domain), None)
            if not target:
                raise GatewayError('Reserva não encontrada; atualize a lista.')
            token = self.config_token()
            url = '/del.cgi?' + urllib.parse.urlencode({'RequestFile': PATH.lstrip('/')})
            self.request(url, {domain: '', 'x.Yiaddr': target['ip'], 'x.Chaddr': target['mac'], 'x.X_HW_Token': token}, referer=PATH)
            updated, _ = self.reservations()
            if any(row['id'] == domain for row in updated):
                raise GatewayError('O Huawei ainda lista esta reserva. Confira no painel antes de repetir a remoção.')
            return target
