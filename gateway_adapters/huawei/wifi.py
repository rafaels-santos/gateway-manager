import re
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_block_policy_page, parse_wifi_page
from .constants import SSID_MAP, WIFI_PATH


class HuaweiWifiOperations:
    def wifi_config(self):
        page = self.request(WIFI_PATH + '?2G')
        rows = parse_wifi_page(page, SSID_MAP)
        for row in rows:
            row['max_clients_writable'] = 'y.X_HW_AssociateNum' in page
            index = int(row['id'].rsplit('.', 1)[-1])
            row['primary'] = index in (1, 5)
            row['band'] = '2G' if index <= 4 else '5G'
            row['guest'] = 'Convidados' in row['network']
            row['managed_by_mesh'] = row['ssid'].casefold().startswith('easymesh_backhaul')
        return rows
    def save_wifi(self, body):
        with self.lock:
            existing = self.wifi_config()
            target = next((n for n in existing if n['id'] == body.get('id')), None)
            if not target: raise GatewayError('Rede Wi-Fi não encontrada; atualize a lista.')
            if target.get('managed_by_mesh'): raise GatewayError('Este SSID de backhaul pertence ao EasyMesh. A edição isolada está indisponível.')
            if 'expected' in body and (not isinstance(body['expected'], dict) or any(str(body['expected'].get(key)) != str(target[key]) for key in ('ssid', 'enabled', 'broadcast', 'max_clients'))):
                raise GatewayError('A rede mudou desde a leitura. Atualize antes de salvar.')
            ssid = str(body.get('ssid', '')).strip()
            if not ssid or len(ssid.encode('utf-8')) > 32 or any(ord(c) < 32 for c in ssid): raise GatewayError('Informe um nome Wi-Fi de até 32 bytes.')
            if any(n['ssid'] == ssid and n['id'] != target['id'] for n in existing): raise GatewayError('Já existe uma rede com esse nome.')
            if not isinstance(body.get('enabled'), bool) or not isinstance(body.get('broadcast'), bool): raise GatewayError('Estado da rede inválido.')
            pending = any(row['id'] == target['id'] or row['ssid'] == target['ssid'] and row['band'] == ('5G' if int(target['id'].split('.')[-1]) >= 5 else '2G') for row in self.provisioning_rows())
            if pending and (body['enabled'] or body['broadcast'] or ssid != target['ssid']):
                raise GatewayError('A segurança desta rede ainda não foi confirmada. Conclua a recuperação antes de ativar.')
            params = {'y.SSID': ssid, 'y.Enable': int(body['enabled']), 'y.SSIDAdvertisementEnabled': int(body['broadcast']), 'x.X_HW_Token': self.config_token()}
            maximum = None
            if 'max_clients' in body:
                if not target.get('max_clients_writable') or not isinstance(body.get('expected'), dict) or body.get('confirm') != 'WIFI':
                    raise GatewayError('Limite de clientes indisponível ou alteração sem confirmação.')
                if isinstance(body['max_clients'], bool) or not re.fullmatch(r'\d{1,2}', str(body['max_clients'])):
                    raise GatewayError('Informe um limite entre 1 e 64 clientes.')
                maximum = int(body['max_clients'])
                if not 1 <= maximum <= 64: raise GatewayError('Informe um limite entre 1 e 64 clientes.')
                params['y.X_HW_AssociateNum'] = maximum
            url = '/set.cgi?' + urllib.parse.urlencode({'y': target['id'], 'RequestFile': WIFI_PATH.lstrip('/')})
            band = '5G' if int(target['id'].split('.')[-1]) >= 5 else '2G'
            self.request(url, params, referer=WIFI_PATH + '?' + band)
            updated = next((n for n in self.wifi_config() if n['id'] == target['id']), None)
            if not updated or any(updated[k] != body[k] for k in ('ssid','enabled','broadcast')): raise GatewayError('O gateway não confirmou a rede. Confira no painel Huawei antes de tentar novamente.')
            if maximum is not None and str(updated['max_clients']) != str(maximum):
                raise GatewayError('O Huawei não confirmou o limite de clientes. Confira o painel antes de repetir.')
            return updated
    def block_policy(self):
        return parse_block_policy_page(self.request('/html/bbsp/wlanmacfilter/wlanmacfilter.asp'))
    def block_client(self, body):
        with self.lock:
            mac = str(body.get('mac', '')).lower()
            if body.get('confirm') != 'BLOQUEAR': raise GatewayError('Confirmação de bloqueio inválida.')
            device = next((d for d in self.devices() if d['mac'] == mac), None)
            if not device or device['type'] != 'wifi' or not re.fullmatch(r'SSID[1-8]', device['port']): raise GatewayError('Bloqueio disponível apenas para clientes Wi-Fi com SSID identificado.')
            policy = self.block_policy()
            if not policy['blacklist']: raise GatewayError('O gateway usa lista de permissão; nenhuma alteração foi feita.')
            if not policy['enabled'] and policy['rules']: raise GatewayError('Há regras desativadas no gateway. Revise-as no Huawei antes de ativar o filtro.')
            if not policy['enabled'] and body.get('activate') is not True: raise GatewayError('Confirme a ativação do filtro Wi-Fi.')
            path = '/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            ssid = 'SSID-' + device['port'][4:]
            with self.label_store_context() as db:
                saved = db.execute('SELECT name FROM labels WHERE gateway=? AND mac=?', (self.base, mac)).fetchone()
            device_name = (saved[0] if saved and saved[0].strip() else device.get('gateway_name') or device.get('hostname') or '')[:80]
            exists = any(len(r)>=4 and r[1]==ssid and r[3].lower()==mac for r in policy['rules'])
            if not exists:
                url = '/add.cgi?' + urllib.parse.urlencode({'x':'InternetGatewayDevice.X_HW_Security.WLANMacFilter','RequestFile':path.lstrip('/')})
                self.request(url, {'x.SourceMACAddress':mac,'x.SSIDName':ssid,'x.DeviceName':device_name,'x.Enable':'1','x.X_HW_Token':self.config_token()}, referer=path)
            if not policy['enabled']:
                url = '/set.cgi?' + urllib.parse.urlencode({'x':'InternetGatewayDevice.X_HW_Security','RequestFile':path.lstrip('/')})
                self.request(url, {'x.WlanMacFilterRight':'1','x.X_HW_Token':self.config_token()}, referer=path)
            updated = self.block_policy()
            if not updated['enabled'] or not updated['blacklist'] or not any(len(r)>=4 and r[1]==ssid and r[3].lower()==mac for r in updated['rules']): raise GatewayError('Bloqueio não confirmado. Confira o filtro no Huawei antes de tentar novamente.')
    def blocked_clients(self, devices):
        policy = self.block_policy()
        if not policy['blacklist']: return []
        by_mac = {d['mac']: d for d in devices}
        result = []
        for rule in policy['rules']:
            if len(rule)<4: raise GatewayError('Formato de regra de bloqueio não reconhecido.')
            domain, ssid, name, mac = rule[:4]
            mac = mac.lower()
            if not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', mac): continue
            port = ssid.replace('SSID-', 'SSID')
            device = dict(by_mac.get(mac, {'mac':mac,'ip':'','hostname':name,'gateway_name':'','duration':'','ip_type':'','ipv6_enabled':''}))
            device.update({'block_rule':domain,'block_active':policy['enabled'],'status':'blocked','type':'wifi','port':port,'network':SSID_MAP.get(port,'Wi-Fi · rede não identificada')})
            result.append(device)
        return result
    def sync_block_device_name(self, mac, name):
        with self.lock:
            rules = self.block_policy()['rules']
            targets = [r for r in rules if len(r)>=4 and r[3].lower()==mac and r[2]!=name]
            path = '/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            for rule in targets:
                if not re.fullmatch(r'InternetGatewayDevice\.X_HW_Security\.WLANMacFilter\.\d+', rule[0]):
                    raise GatewayError('Regra de bloqueio não reconhecida; nome não enviado.')
                url = '/set.cgi?' + urllib.parse.urlencode({'x':rule[0], 'RequestFile':path.lstrip('/')})
                self.request(url, {'x.DeviceName':name, 'x.X_HW_Token':self.config_token()}, referer=path)
            if targets:
                updated = {r[0]:r for r in self.block_policy()['rules'] if len(r)>=4}
                if any(r[0] not in updated or updated[r[0]][2]!=name for r in targets):
                    raise GatewayError('O Huawei não confirmou o Device Name da regra. Atualize antes de tentar novamente.')
    def unblock_client(self, body):
        with self.lock:
            domain = str(body.get('rule',''))
            mac = str(body.get('mac','')).lower()
            if body.get('confirm') != 'DESBLOQUEAR' or not re.fullmatch(r'InternetGatewayDevice\.X_HW_Security\.WLANMacFilter\.\d+', domain): raise GatewayError('Regra ou confirmação inválida.')
            rules = self.block_policy()['rules']
            if not any(len(r)>=4 and r[0]==domain and r[3].lower()==mac for r in rules): raise GatewayError('Regra não encontrada; atualize a lista.')
            path='/html/bbsp/wlanmacfilter/wlanmacfilter.asp'
            self.request('/del.cgi?'+urllib.parse.urlencode({'RequestFile':path.lstrip('/')}), {domain:'','x.X_HW_Token':self.config_token()}, referer=path)
            if any(r[0]==domain for r in self.block_policy()['rules']): raise GatewayError('A remoção não foi confirmada pelo Huawei; confira no painel antes de tentar novamente.')
