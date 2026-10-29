"""LAN/DHCP change planning and explicit, verifiable address recovery."""
import ipaddress
import re
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_constructors
from .constants import LAN_ADDRESS_PATH, LAN_DOMAIN
from .local_records import fingerprint

ETH_INFO = '/html/amp/ethinfo/ethinfo.asp'
PRIMARY = LAN_DOMAIN + '.IPInterface.1'
RESERVATION = LAN_DOMAIN + '.DHCPStaticAddress'


def private_network(ip, mask):
    try:
        address = ipaddress.IPv4Address(str(ip))
        mask_ip = ipaddress.IPv4Address(str(mask))
        if '01' in f'{int(mask_ip):032b}': raise ValueError()
        network = ipaddress.IPv4Network((str(address), str(mask_ip)), strict=False)
        if not 8 <= network.prefixlen <= 30 or not any(network.subnet_of(ipaddress.IPv4Network(block)) for block in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')) or address in (network.network_address, network.broadcast_address): raise ValueError()
        return address, network
    except (ValueError, TypeError):
        raise GatewayError('Informe um IP privado utilizável e uma máscara contígua entre /8 e /30.')


def gateway_lan_mac(gateway):
    values = parse_constructors(gateway.request(ETH_INFO, max_redirects=0), 'DeviceLanMAC')
    row = next((row for row in values if len(row) == 3 and row[0] == 'InternetGatewayDevice.DeviceInfo'), None)
    if not row or not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}', str(row[1])):
        raise GatewayError('Não foi possível identificar o mesmo gateway pelo MAC LAN; a mudança de endereço está indisponível.')
    return str(row[1]).lower()


class HuaweiLanChange:
    def plan_lan_change(self, body):
        with self.lock:
            current = self.dhcp_config()
            reservations, _ = self.reservations()
            devices = self.devices()
            page = self.request(LAN_ADDRESS_PATH, max_redirects=0)
            interfaces = [row for row in parse_constructors(page, 'stLanHostInfo') if len(row) == 5 and re.fullmatch(re.escape(LAN_DOMAIN) + r'\.IPInterface\.[12]', str(row[0]))]
            primary = next((row for row in interfaces if row[0] == PRIMARY), None)
            if not primary or primary[2] != current['lan_ip'] or primary[3] != current['mask'] or 'x.IPInterfaceIPAddress' not in page or 'x.IPInterfaceSubnetMask' not in page:
                raise GatewayError('Os dados de endereço LAN não correspondem ao DHCP ou o formulário não foi reconhecido.')
            address, network = private_network(body.get('ip'), body.get('mask'))
            old_network = ipaddress.IPv4Network((current['lan_ip'],current['mask']), strict=False)
            blockers, warnings = [], []
            start = str(body.get('start') or current['start']); end = str(body.get('end') or current['end'])
            try: first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
            except ValueError: raise GatewayError('Informe início e fim válidos para o intervalo DHCP proposto.')
            usable = lambda ip: ip in network and ip not in (network.network_address,network.broadcast_address,address)
            if not usable(first) or not usable(last) or first > last or first <= address <= last:
                blockers.append('O intervalo DHCP proposto precisa caber na nova rede e excluir o endereço do gateway.')
            for row in interfaces:
                if row[0] != PRIMARY and row[1] == '1':
                    try: secondary = ipaddress.IPv4Network((row[2],row[3]), strict=False)
                    except ValueError: raise GatewayError('Formato do endereço secundário não reconhecido.')
                    if network.overlaps(secondary): blockers.append('A rede proposta sobrepõe um endereço secundário ativo.')
            # Conditional and per-port pools have service dependencies outside this
            # narrow transaction. Recognize them and refuse to silently modify them.
            for constructor in ('condhcpst','PortVlanIpInterfaceInfo','PortVlanDhcpPollInfo'):
                if parse_constructors(page, constructor):
                    blockers.append('Há configuração condicional ou por porta. Revise essas dependências no Huawei antes de alterar a LAN pelo app.'); break
            migrate = body.get('migrate_reservations',False)
            if not isinstance(migrate,bool): raise GatewayError('Opção de migração de reservas inválida.')
            planned, used = [], set()
            for row in reservations:
                if not re.fullmatch(re.escape(RESERVATION)+r'\.\d+',str(row.get('id',''))): raise GatewayError('Objeto de reserva não reconhecido.')
                old = ipaddress.IPv4Address(row['ip'])
                offset = int(old)-int(old_network.network_address)
                try: proposed = ipaddress.IPv4Address(int(network.network_address)+offset) if migrate else old
                except ipaddress.AddressValueError: raise GatewayError('Uma reserva não cabe na rede proposta.')
                valid = usable(proposed) and str(proposed) not in used
                if not valid and row.get('enabled',True): blockers.append(f'A reserva {row["mac"].upper()} não cabe na nova rede ou conflita com outro endereço.')
                if not valid and not row.get('enabled',True):
                    proposed = old
                    warnings.append('Uma reserva inativa incompatível será preservada sem reendereçamento; revise-a antes de ativar.')
                used.add(str(proposed))
                planned.append({'id':row['id'],'mac':row['mac'],'old_ip':row['ip'],'ip':str(proposed),'enabled':row.get('enabled',True),'changed':proposed != old})
            for row in devices:
                if row.get('status') == 'online' and row.get('ip') == str(address) and str(address) != current['lan_ip']:
                    blockers.append('Outro cliente conectado já usa o novo endereço do gateway.')
            changed = str(address) != current['lan_ip'] or str(network.netmask) != current['mask'] or start != current['start'] or end != current['end'] or any(row['changed'] for row in planned)
            if changed:
                warnings.append('Clientes com IP manual precisam ser ajustados no próprio dispositivo. Reservas não equivalem a endereços configurados manualmente.')
                warnings.append('A conexão pode cair e a gravação pode ser parcial se o firmware interromper a operação. Não há rollback automático.')
            identity = gateway_lan_mac(self)
            snapshot = fingerprint({'dhcp':current,'reservations':reservations,'interfaces':interfaces,'identity':identity})
            parsed = urllib.parse.urlsplit(self.base)
            new_base = urllib.parse.urlunsplit((parsed.scheme, str(address)+(':'+str(parsed.port) if parsed.port else ''),'','',''))
            return {'current':current,'proposed':{'ip':str(address),'mask':str(network.netmask),'start':start,'end':end,'network':str(network),'base':new_base},
                    'reservations':planned,'blockers':list(dict.fromkeys(blockers)),'warnings':warnings,'changed':changed,
                    'expected':snapshot,'apply_available':not blockers and bool(self.credentials),'migrate_reservations':migrate,
                    'identity':identity,'recovery':['Mantenha um computador conectado por cabo e acesso físico ao roteador.',
                       'Após a mudança, renove o DHCP ou ajuste o IP manual para a nova rede.',
                       'Use Verificar novo endereço para confirmar o mesmo equipamento sem reenviar o comando.',
                       'Se o servidor do aplicativo estiver fora da nova rede, ajuste sua conectividade antes de tentar a verificação.']}

    def apply_lan_change(self, body, journal=None):
        if body.get('confirm') != 'ALTERAR LAN' or body.get('confirm_ip') != str(body.get('ip','')):
            raise GatewayError('Confirme ALTERAR LAN e o novo endereço IP.')
        with self.lock:
            if getattr(self,'pending_lan_change',None): raise GatewayError('Há uma alteração aguardando verificação. Verifique o novo endereço antes de qualquer reenvio.')
            plan = self.plan_lan_change(body)
            if body.get('expected') != plan['expected']: raise GatewayError('A configuração mudou desde a prévia. Analise novamente.')
            if not plan['apply_available']: raise GatewayError('A alteração tem conflitos ou não há credenciais de sessão para recuperar o acesso.')
            if not plan['changed']: return {'state':'unchanged','verified':True,'proposed':plan['proposed']}
            params = {'x.IPInterfaceIPAddress':plan['proposed']['ip'],'x.IPInterfaceSubnetMask':plan['proposed']['mask'],
                      'z.MinAddress':plan['proposed']['start'],'z.MaxAddress':plan['proposed']['end']}
            targets = {'x':PRIMARY,'z':LAN_DOMAIN,'RequestFile':LAN_ADDRESS_PATH.lstrip('/')}
            for index, row in enumerate(plan['reservations']):
                if row['changed']:
                    alias = 'r'+str(index); targets[alias] = row['id']; params[alias+'.Yiaddr'] = row['ip']
            params['x.X_HW_Token'] = self.config_token()
            if journal is not None: journal(plan)
            self.pending_lan_change = {'plan':plan,'attempted':True}
            try: self.request('/set.cgi?'+urllib.parse.urlencode(targets),params,referer=LAN_ADDRESS_PATH)
            except GatewayError:
                # A dropped connection does not tell us whether the command ran.
                self.pending_lan_change['transport_uncertain'] = True
            return self.verify_lan_change()

    def verify_lan_change(self):
        with self.lock:
            pending = getattr(self,'pending_lan_change',None)
            if not pending: raise GatewayError('Não há mudança de LAN aguardando verificação nesta sessão.')
            plan = pending['plan']; proposed = plan['proposed']
            try:
                candidate = type(self)(proposed['base'])
                candidate.login(*self.credentials)
                if gateway_lan_mac(candidate) != plan['identity']: raise GatewayError('O novo endereço não corresponde ao MAC LAN do equipamento original.')
                actual = candidate.dhcp_config()
                wanted = {'lan_ip':proposed['ip'],'mask':proposed['mask'],'start':proposed['start'],'end':proposed['end']}
                if any(str(actual[key]) != str(value) for key,value in wanted.items()): raise GatewayError('O endereço ou o intervalo DHCP ainda não corresponde ao planejado.')
                if any(str(actual[key]) != str(plan['current'][key]) for key in ('enabled','lease','dns_primary','dns_secondary') if key in plan['current']):
                    raise GatewayError('O Huawei alterou outros parâmetros DHCP. Revise o equipamento antes de continuar.')
                reservations = candidate.reservations()[0]
                actual_rows = sorted((row['mac'],row['ip'],row.get('enabled',True)) for row in reservations)
                expected_rows = sorted((row['mac'],row['ip'],row['enabled']) for row in plan['reservations'])
                if actual_rows != expected_rows: raise GatewayError('As reservas não correspondem ao planejamento.')
            except GatewayError as error:
                return {'state':'pending_verification','verified':False,'proposed':proposed,'message':str(error),'recovery':plan['recovery']}
            return {'state':'verified','verified':True,'proposed':proposed,'replacement':candidate,'recovery':plan['recovery']}
