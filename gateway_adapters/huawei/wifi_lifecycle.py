"""Staged SSID provisioning. No network is enabled before security readback."""
import re
import sqlite3
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_constructors
from .constants import WIFI_PATH
from .local_records import fingerprint
from .radio_security import key_material, password_matches

ROOT = 'InternetGatewayDevice.LANDevice.1.WLANConfiguration'
PARALLEL = 'InternetGatewayDevice.X_HW_DEBUG.AMP.ParallelDelSsid'


def journal_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS wifi_provisioning (gateway TEXT, ssid TEXT, band TEXT, object_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(gateway,ssid,band))')


def password_input(body):
    value = body.get('password')
    if (not isinstance(value, str) or not 8 <= len(value) <= 63
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
            or not all(re.search(pattern, value) for pattern in (r'[A-Z]', r'[a-z]', r'[0-9]', r'[^A-Za-z0-9]'))):
        raise GatewayError('Use 8–63 caracteres ASCII sem espaços, com maiúsculas, minúsculas, números e símbolos.')
    if value != body.get('password_confirmation'):
        raise GatewayError('As senhas não coincidem.')
    return value


class HuaweiWifiLifecycle:
    def provisioning_rows(self):
        if self.label_store_factory is None: return []
        with self.label_store_context() as db:
            journal_schema(db)
            return [dict(zip(('ssid', 'band', 'id', 'state'), row)) for row in db.execute(
                "SELECT ssid,band,object_id,state FROM wifi_provisioning WHERE gateway=? AND state!='ready'", (self.base,))]

    def _provision_mark(self, ssid, band, ident, state):
        try:
            with self.label_store_context() as db:
                journal_schema(db)
                db.execute('INSERT INTO wifi_provisioning VALUES (?,?,?,?,?) ON CONFLICT(gateway,ssid,band) DO UPDATE SET object_id=excluded.object_id,state=excluded.state',
                           (self.base, ssid, band, ident, state))
        except sqlite3.Error:
            raise GatewayError('O registro local da operação falhou. Confira a rede no Huawei antes de continuar.')

    def wifi_lifecycle(self):
        page = self.request(WIFI_PATH+'?2G', max_redirects=0)
        signature = re.search(r'function\s+stWlan\s*\((.*?)\)\s*\{', page, re.S)
        if not signature: raise GatewayError('Formato de redes Wi-Fi não reconhecido.')
        names = [name.strip() for name in signature[1].split(',')]
        if not all(name in names for name in ('domain', 'ssid', 'enable', 'wlHide', 'DeviceNum', 'LowerLayers')):
            raise GatewayError('Campos de criação de redes não reconhecidos.')
        records = []
        for fields in parse_constructors(page, 'stWlan'):
            if len(fields) < len(names): continue
            row = dict(zip(names, fields)); ident = str(row['domain'])
            if not re.fullmatch(re.escape(ROOT)+r'\.[1-8]', ident): continue
            index = int(ident.split('.')[-1])
            records.append({'id': ident, 'ssid': str(row['ssid']), 'enabled': row['enable'] == '1',
                            'broadcast': row['wlHide'] == '1', 'max_clients': str(row['DeviceNum']),
                            'band': '2G' if index <= 4 else '5G', 'lower_layer': str(row['LowerLayers']),
                            'protected': index in (1, 4, 5, 8) or str(row['ssid']).casefold().startswith('easymesh_backhaul')})
        if not records: raise GatewayError('Nenhuma rede Wi-Fi reconhecida.')
        identity = getattr(self, 'identity', {}) or {}
        profile = (identity.get('hardware') == '343D.D' and identity.get('firmware') == 'V5R024C10S106'
                   and bool(re.search(r"var\s+CfgMode\s*=\s*['\"]BREBG2['\"]", page)))
        capacity = re.search(r"var\s+ssidMaxNum\s*=\s*['\"]4['\"]", page)
        counts = re.search(r"var\s+SsidNum\s*=\s*['\"]([0-4]),([0-4]),[0-4],?['\"]", page)
        required = ('addcfg.cgi?', 'y.LowerLayers', 'y.SSID', 'y.Enable', 'y.SSIDAdvertisementEnabled',
                    'y.WMMEnable', 'y.X_HW_AssociateNum', 'y.IEEE11iAuthenticationMode',
                    'y.IEEE11iEncryptionModes', 'k.KeyPassphrase', 'z.Enable')
        creation = profile and bool(capacity and counts) and all(field in page for field in required)
        bands = []
        for index, band in enumerate(('2G', '5G')):
            layer = next((row['lower_layer'] for row in records if row['id'] == ROOT+('.1' if band == '2G' else '.5')), '')
            valid_layer = layer == 'InternetGatewayDevice.LANDevice.1.WiFi.Radio.'+str(index+1)
            used = int(counts[index+1]) if counts else None
            bands.append({'id': band, 'occupied': used, 'capacity': 4 if capacity else None,
                          'lower_layer': layer if valid_layer else '',
                          'create_available': bool(creation and valid_layer and used < 4)})
        guests = []
        for row in parse_constructors(page, 'stGuestSsid'):
            if (len(row) != 3 or not re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.X_HW_WLANForGuest\.[12]', str(row[0]))
                    or str(row[1]) not in [str(n) for n in range(9)] or str(row[2]) not in ('0', '1')):
                raise GatewayError('Referências de convidados não reconhecidas; operação de redes indisponível.')
            if str(row[1]) != '0':
                guests.append({'id': str(row[0]), 'ssid_id': ROOT+'.'+str(row[1])})
        # AP dependencies must not be detached automatically.
        aps = bool(parse_constructors(page, 'StApDevice'))
        deletion = profile and bool(re.search(r'function\s+StApDevice\s*\(', page)) and all(marker in page for marker in ('y.DeleteInstArray', PARALLEL, 'del.cgi?RequestFile', 'SubmitForm.addParameter(wlandomain'))
        for row in records:
            duplicate = sum(other['ssid'] == row['ssid'] for other in records) > 1
            guest = next((item for item in guests if item['ssid_id'] == row['id']), None)
            row['guest_reference'] = guest
            row['delete_available'] = bool(deletion and not aps and not row['protected'] and not duplicate)
            row['delete_reason'] = ('Rede principal ou reservada para cobertura.' if row['protected'] else
                                    'Há dependências de pontos de acesso; revise no Huawei.' if aps else
                                    'O nome é compartilhado entre redes; revise o grupo no Huawei.' if duplicate else
                                    'Contrato de exclusão indisponível neste perfil.' if not deletion else '')
        return {'records': records, 'bands': bands, 'pending': self.provisioning_rows(), 'guest_references': guests,
                'expected': fingerprint({'records': records, 'bands': bands, 'guests': guests}), 'profile_supported': profile}

    def create_wifi_network(self, body):
        if body.get('confirm') != 'CRIAR REDE': raise GatewayError('Confirme a criação da rede desativada.')
        password = password_input(body)
        ssid = str(body.get('ssid', '')).strip(); band = body.get('band')
        if not ssid or len(ssid.encode('utf-8')) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
            raise GatewayError('Informe um nome de rede de até 32 bytes, sem controles.')
        if ssid.casefold().startswith('easymesh_backhaul'): raise GatewayError('Nome reservado para cobertura.')
        maximum = body.get('max_clients', 32)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 64:
            raise GatewayError('Informe um limite de 1 a 64 clientes.')
        with self.lock:
            state = self.wifi_lifecycle()
            if body.get('expected') != state['expected']: raise GatewayError('As redes mudaram. Atualize antes de criar.')
            target_band = next((row for row in state['bands'] if row['id'] == band), None)
            if not target_band or not target_band['create_available']: raise GatewayError('Criação indisponível ou banda sem capacidade reconhecida.')
            if any(row['ssid'] == ssid for row in state['records']) or any(row['ssid'] == ssid for row in state['pending']):
                raise GatewayError('Já existe uma rede ou criação pendente com esse nome. Use a recuperação, sem repetir a criação.')
            token = self.config_token()
            self._provision_mark(ssid, band, '', 'allocating')
            params = {'y.SSID': ssid, 'y.Enable': '0', 'y.SSIDAdvertisementEnabled': '0', 'y.WMMEnable': '1',
                      'y.X_HW_AssociateNum': maximum, 'y.LowerLayers': target_band['lower_layer'], 'x.X_HW_Token': token}
            try:
                self.request('/addcfg.cgi?'+urllib.parse.urlencode({'y': ROOT, 'RequestFile': WIFI_PATH.lstrip('/')}), params, referer=WIFI_PATH+'?'+band)
            except GatewayError: pass
            try: after = self.wifi_lifecycle()
            except GatewayError:
                return {'verified': False, 'state': 'pending', 'message': 'Não foi possível reler a criação. Confira o Huawei; o comando não será repetido.'}
            original = {row['id']: row for row in state['records']}
            added = [row for row in after['records'] if row['id'] not in original and row['ssid'] == ssid and row['band'] == band]
            if len(added) != 1 or any(next((new for new in after['records'] if new['id'] == ident), None) != row for ident, row in original.items()):
                return {'verified': False, 'state': 'pending', 'message': 'A criação não corresponde à prévia. Revise o Huawei antes de qualquer repetição.'}
            row = added[0]
            self._provision_mark(ssid, band, row['id'], 'security_pending')
            if row['protected'] or row['enabled'] or row['broadcast']:
                return {'verified': False, 'state': 'pending', 'id': row['id'], 'message': 'A rede criada não está no estado desativado esperado ou usou um índice reservado. Confira o Huawei.'}
            return self._initialize_wifi_network(row, password)

    def _initialize_wifi_network(self, row, password):
        ident = row['id']; band = row['band']
        targets = {'y': ident, 'z': ident+'.WPS', 'k': ident+'.PreSharedKey.1', 'RequestFile': WIFI_PATH.lstrip('/')}
        params = {'y.Enable': '0', 'y.SSIDAdvertisementEnabled': '0', 'y.BeaconType': '11i',
                  'y.IEEE11iAuthenticationMode': 'PSKAuthentication', 'y.IEEE11iEncryptionModes': 'AESEncryption',
                  'z.Enable': '0', 'k.KeyPassphrase': password, 'x.X_HW_Token': self.config_token()}
        try:
            self.request('/set.cgi?'+urllib.parse.urlencode(targets), params, referer=WIFI_PATH+'?'+band)
            security = next((item for item in self.wifi_security() if item['id'] == ident), None)
            page = self.request(WIFI_PATH+'?2G', max_redirects=0)
            current = next((item for item in self.wifi_lifecycle()['records'] if item['id'] == ident), None)
            if (not security or not current or current['enabled'] or current['broadcast']
                    or current['ssid'] != row['ssid'] or security['mode'] != 'wpa2'
                    or security['encryption'] != 'AESEncryption' or security['wps_enabled'] is not False
                    or not password_matches(key_material(page).get(ident+'.PreSharedKey.1', ()), password, row['ssid'])):
                raise GatewayError('Segurança não confirmada.')
            self._provision_mark(row['ssid'], band, ident, 'ready')
        except GatewayError:
            return {'verified': False, 'state': 'pending', 'id': ident, 'message': 'A segurança não foi confirmada. A rede permanece em recuperação; não a ative. Reenvie a senha pela recuperação após conferir o Huawei.'}
        return {'verified': True, 'state': 'ready', 'id': ident, 'message': 'Rede criada com WPA2/AES e WPS desativado, confirmados por releitura. Ative e divulgue a rede na tela Redes Wi-Fi quando desejar.'}

    def resume_wifi_network(self, body):
        if body.get('confirm') != 'RECUPERAR REDE': raise GatewayError('Confirme a recuperação da rede desativada.')
        password = password_input(body)
        with self.lock:
            state = self.wifi_lifecycle()
            if body.get('expected') != state['expected']: raise GatewayError('As redes mudaram. Atualize antes de recuperar.')
            row = next((item for item in state['records'] if item['id'] == body.get('id')), None)
            if (not state['profile_supported'] or not row or row['protected'] or row['enabled']
                    or not any(item['id'] in ('', row['id']) and item['ssid'] == row['ssid'] and item['band'] == row['band'] for item in state['pending'])):
                raise GatewayError('Rede pendente desativada não reconhecida. Confira o Huawei.')
            self._provision_mark(row['ssid'], row['band'], row['id'], 'security_pending')
            return self._initialize_wifi_network(row, password)

    def delete_wifi_network(self, body):
        if body.get('confirm') != 'EXCLUIR REDE' or body.get('disconnect_clients') is not True:
            raise GatewayError('Confirme a exclusão e a desconexão dos clientes desta rede.')
        with self.lock:
            state = self.wifi_lifecycle()
            if body.get('expected') != state['expected']: raise GatewayError('As redes mudaram. Atualize antes de excluir.')
            row = next((item for item in state['records'] if item['id'] == body.get('id')), None)
            if not row or not row['delete_available'] or body.get('confirm_ssid') != row['ssid']:
                raise GatewayError('Rede protegida, dependência não validada ou nome de confirmação incorreto.')
            if row['guest_reference'] and body.get('clear_guest') is not True:
                raise GatewayError('Confirme também a remoção da referência de convidados.')
            ident = row['id']; targets = {'y': PARALLEL, 'RequestFile': WIFI_PATH.lstrip('/')}
            params = {'y.DeleteInstArray': ident.split('.')[-1], 'x.X_HW_Token': self.config_token()}
            if row['guest_reference']:
                targets['z'] = row['guest_reference']['id']; params['z.SSID_IDX'] = '0'
            try:
                self.request('/set.cgi?'+urllib.parse.urlencode(targets), params, referer=WIFI_PATH+'?'+row['band'])
                self.request('/del.cgi?'+urllib.parse.urlencode({'RequestFile': WIFI_PATH.lstrip('/')}),
                             {ident: '', 'x.X_HW_Token': self.config_token()}, referer=WIFI_PATH+'?'+row['band'])
            except GatewayError:
                raise GatewayError('Exclusão interrompida. Confira o Huawei antes de repetir; nenhuma etapa será reenviada automaticamente.')
            after = self.wifi_lifecycle()
            expected = [{**item, 'delete_available': None, 'delete_reason': None} for item in state['records'] if item['id'] != ident]
            actual = [{**item, 'delete_available': None, 'delete_reason': None} for item in after['records']]
            if sorted(expected, key=lambda item:item['id']) != sorted(actual, key=lambda item:item['id']):
                raise GatewayError('A exclusão não foi confirmada com as outras redes preservadas. Confira o Huawei.')
            if any(guest['ssid_id'] == ident for guest in after['guest_references']):
                raise GatewayError('A referência de convidados ainda aponta para a rede excluída.')
            self._provision_mark(row['ssid'], row['band'], ident, 'ready')
            return {'verified': True, 'id': ident}
