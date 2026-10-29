"""Narrow Wi-Fi operations using property names inspected in the firmware UI."""
import re
import urllib.parse
import hashlib
import hmac
import json
import secrets

from ..errors import GatewayError
from ..parsers import parse_constructors
from .constants import WIFI_PATH
from .local_records import fingerprint

RADIO_SOURCE = '/html/amp/wlanadv/wlanadvance_api.asp'
RADIO_PAGE = '/html/amp/wlanadv/WlanAdvance.asp'
SECURITY_MODES = {
    'wpa2': ('WPA2 Personal', '11i', 'IEEE11i', 'PSKAuthentication'),
    'wpa3': ('WPA3 SAE', 'WPA3', 'X_HW_WPAand11i', 'SAEAuthentication'),
    'transition': ('WPA2/WPA3', 'WPA2/WPA3', 'X_HW_WPAand11i', 'PSKandSAEAuthentication'),
}
_KEY_SNAPSHOT_NONCE = secrets.token_bytes(32)


def key_material(page):
    return {str(row[0]): tuple(str(value) for value in row[1:3]) for row in parse_constructors(page, 'stPreSharedKey')
            if len(row) == 3 and re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.WLANConfiguration\.[1-8]\.PreSharedKey\.1', str(row[0]))}


def key_can_be_verified(values):
    return any(8 <= len(value) <= 63 and value.isascii() and not re.fullmatch(r'[*•]+|<redacted>|REDACTED', value, re.I)
               or bool(re.fullmatch(r'[a-fA-F0-9]{64}', value)) for value in values)


def key_version(base, record, values):
    # An HMAC with a server-only nonce prevents exposing a guessable password hash.
    payload = json.dumps([base, record['id'], record['expected'], values], separators=(',', ':')).encode()
    return hmac.new(_KEY_SNAPSHOT_NONCE, payload, hashlib.sha256).hexdigest()


def password_matches(values, password, ssid):
    derived = hashlib.pbkdf2_hmac('sha1', password.encode('ascii'), ssid.encode('utf-8'), 4096, 32).hex()
    return any(hmac.compare_digest(value.encode('utf-8'), password.encode('ascii')) or re.fullmatch(r'[a-fA-F0-9]{64}', value) and hmac.compare_digest(value.lower(), derived) for value in values)


def group_key_version(base, group, material):
    versions = [(row['id'],key_version(base,row,material.get(row['id']+'.PreSharedKey.1',()))) for row in sorted(group,key=lambda row:row['id'])]
    return hmac.new(_KEY_SNAPSHOT_NONCE,json.dumps(versions).encode(),hashlib.sha256).hexdigest()


class HuaweiRadioSecurity:
    def radio_config(self):
        page = self.request(RADIO_SOURCE, max_redirects=0)
        # These power options were inspected for this customization. Do not apply
        # guessed regulatory/channel option lists to a different customization.
        supported = bool(re.search(r"var\s+CfgMode\s*=\s*['\"]BREBG2['\"]", page))
        result = []
        for row in parse_constructors(page, 'stWlanWifi'):
            if len(row) < 11 or row[0] not in ('InternetGatewayDevice.LANDevice.1.WLANConfiguration.1','InternetGatewayDevice.LANDevice.1.WLANConfiguration.5'): continue
            public = {'id': row[0], 'band': '2,4 GHz' if row[0].endswith('.1') else '5 GHz', 'standard': row[5],
                      'channel': row[6], 'power': str(row[7]), 'country': row[8], 'auto_channel': row[9] == '1', 'width_code': row[10]}
            if not re.fullmatch(r'\d{1,3}', public['power']): continue
            result.append({**public, 'expected': fingerprint(public), 'power_options': ['100','80','60','40','20'] if supported else [], 'writable': supported and 'y.TransmitPower' in page})
        if not result: raise GatewayError('Dados de rádio indisponíveis ou formato não reconhecido.')
        return result

    def save_radio(self, body):
        if body.get('confirm') != 'WIFI': raise GatewayError('Confirme a alteração de rádio.')
        with self.lock:
            target = next((row for row in self.radio_config() if row['id'] == body.get('id')), None)
            if not target or not target['writable']: raise GatewayError('Edição de potência indisponível neste perfil de firmware.')
            if body.get('expected') != target['expected']: raise GatewayError('Os parâmetros do rádio mudaram. Atualize antes de salvar.')
            power = str(body.get('power', ''))
            if power not in target['power_options']: raise GatewayError('Selecione uma potência oferecida pelo firmware.')
            if power == target['power']: return target
            path = RADIO_PAGE + ('?2G' if target['id'].endswith('.1') else '?5G')
            url = '/set.cgi?' + urllib.parse.urlencode({'y': target['id'], 'RequestFile': RADIO_PAGE.lstrip('/')})
            self.request(url, {'y.TransmitPower': power, 'x.X_HW_Token': self.config_token()}, referer=path)
            updated = next((row for row in self.radio_config() if row['id'] == target['id']), None)
            if not updated or updated['power'] != power or any(updated[key] != target[key] for key in ('country','standard','auto_channel','width_code')):
                raise GatewayError('A alteração de potência não foi confirmada com os demais parâmetros preservados. Confira o Huawei antes de repetir.')
            if not target['auto_channel'] and updated['channel'] != target['channel']:
                raise GatewayError('O canal fixo mudou durante a operação. Confira o Huawei antes de repetir.')
            return updated

    def wifi_security(self):
        page = self.request(WIFI_PATH + '?2G', max_redirects=0)
        signature = re.search(r'function\s+stWlan\s*\((.*?)\)\s*\{', page, re.S)
        if not signature: raise GatewayError('Formato de segurança Wi-Fi não reconhecido.')
        names = [name.strip() for name in signature[1].split(',')]
        required = ('domain','ssid','BeaconType','WPAAuthenticationMode','IEEE11iAuthenticationMode','X_HW_WPAand11iAuthenticationMode')
        if not all(name in names for name in required): raise GatewayError('Campos de segurança Wi-Fi não reconhecidos.')
        wps = {str(row[0]): row[4] == '1' for row in parse_constructors(page, 'stWpsPin') if len(row) == 5 and row[4] in ('0','1')}
        keys = key_material(page)
        networks = []
        for fields in parse_constructors(page, 'stWlan'):
            if len(fields) < len(names): continue
            record = dict(zip(names, fields)); domain = str(record['domain'])
            if not re.fullmatch(r'InternetGatewayDevice\.LANDevice\.1\.WLANConfiguration\.[1-8]', domain): continue
            beacon = str(record['BeaconType'])
            prefix = 'IEEE11i' if beacon == '11i' else 'WPA' if beacon == 'WPA' else 'X_HW_WPAand11i'
            public = {'id':domain, 'ssid':str(record['ssid']), 'beacon':beacon,
                      'authentication':str(record.get(prefix+'AuthenticationMode', '')),
                      'encryption':str(record.get(prefix+'EncryptionModes', '')), 'wps_enabled':wps.get(domain+'.WPS')}
            public['mode'] = next((key for key, value in SECURITY_MODES.items() if value[1] == beacon and value[3] == public['authentication']), '')
            personal = public['authentication'] in ('PSKAuthentication','SAEAuthentication','PSKandSAEAuthentication')
            profiles = [{'id':key, 'label':value[0]} for key, value in SECURITY_MODES.items() if value[1] in page and 'y.'+value[2]+'AuthenticationMode' in page and (key == 'wpa2' or public['wps_enabled'] is False)]
            result = {**public, 'expected':fingerprint(public), 'profiles':profiles,
                      'writable': bool(personal and profiles and not public['ssid'].casefold().startswith('easymesh_backhaul'))}
            values = keys.get(domain+'.PreSharedKey.1', ())
            result['password_writable'] = bool(result['writable'] and key_can_be_verified(values) and 'k.KeyPassphrase' in page)
            result['password_expected'] = key_version(self.base, result, values) if result['password_writable'] else None
            networks.append(result)
        if not networks: raise GatewayError('Nenhum SSID com dados de segurança reconhecidos.')
        password_flags = {row['id']:row['password_writable'] for row in networks}
        profile_ids = {row['id']:{profile['id'] for profile in row['profiles']} for row in networks}
        for row in networks:
            group = [other for other in networks if other['ssid'] == row['ssid']]
            row['affected_ssids'] = [{'id':other['id'],'ssid':other['ssid'],'band':'5 GHz' if int(other['id'].split('.')[-1]) >= 5 else '2,4 GHz'} for other in group]
            row['group_expected'] = fingerprint(sorted((other['id'],other['expected']) for other in group))
            available = set.intersection(*(profile_ids[other['id']] for other in group))
            row['profiles'] = [profile for profile in row['profiles'] if profile['id'] in available]
            row['writable'] = all(other['writable'] for other in group) and bool(row['profiles'])
            row['password_writable'] = all(password_flags[other['id']] for other in group)
            row['password_expected'] = group_key_version(self.base,group,keys) if row['password_writable'] else None
        return networks

    def save_wifi_password(self, body):
        if body.get('confirm') != 'WIFI': raise GatewayError('Confirme a alteração da senha Wi-Fi.')
        password = body.get('password')
        if not isinstance(password, str) or not 8 <= len(password) <= 63 or not password.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in password):
            raise GatewayError('Use uma senha de 8 a 63 caracteres ASCII, sem espaços, com maiúsculas, minúsculas, números e símbolos.')
        if not all(re.search(pattern, password) for pattern in (r'[A-Z]',r'[a-z]',r'[0-9]',r'[^A-Za-z0-9]')):
            raise GatewayError('A senha precisa conter maiúsculas, minúsculas, números e símbolos.')
        if password != body.get('password_confirmation'): raise GatewayError('As senhas não coincidem.')
        with self.lock:
            networks = self.wifi_security()
            target = next((row for row in networks if row['id'] == body.get('id')), None)
            if not target or not target.get('password_writable'): raise GatewayError('Alteração de senha indisponível: SSID protegido ou firmware sem releitura verificável da chave.')
            if not isinstance(body.get('expected'), str) or not hmac.compare_digest(body['expected'], target['password_expected']):
                raise GatewayError('A rede ou a senha mudou desde a leitura. Atualize antes de salvar.')
            group = [row for row in networks if row['ssid'] == target['ssid']]
            material = key_material(self.request(WIFI_PATH+'?2G', max_redirects=0))
            if not hmac.compare_digest(group_key_version(self.base,group,material), target['password_expected']):
                raise GatewayError('A chave mudou durante a revisão. Atualize antes de salvar.')
            path = WIFI_PATH + ('?5G' if int(target['id'].split('.')[-1]) >= 5 else '?2G')
            targets = {'RequestFile':WIFI_PATH.lstrip('/')}; params = {'x.X_HW_Token':self.config_token()}
            for index,row in enumerate(group):
                alias = 'k' if len(group) == 1 else 'k'+str(index)
                targets[alias] = row['id']+'.PreSharedKey.1'; params[alias+'.KeyPassphrase'] = password
            self.request('/set.cgi?'+urllib.parse.urlencode(targets),params,referer=path)
            updated = {row['id']:row for row in self.wifi_security()}
            material = key_material(self.request(WIFI_PATH+'?2G', max_redirects=0))
            for row in group:
                current = updated.get(row['id'])
                if not current or any(current[key] != row[key] for key in ('ssid','beacon','authentication','encryption','wps_enabled')) or not password_matches(material.get(row['id']+'.PreSharedKey.1',()),password,row['ssid']):
                    raise GatewayError('Não foi possível confirmar a nova senha em todo o grupo, com os demais parâmetros preservados. Confira o Huawei antes de repetir; o comando não será reenviado automaticamente.')
            return {'verified':True,'id':target['id'],'affected_ssids':target['affected_ssids']}

    def save_wifi_security(self, body):
        if body.get('confirm') != 'WIFI': raise GatewayError('Confirme a alteração de autenticação Wi-Fi.')
        with self.lock:
            networks = self.wifi_security()
            target = next((row for row in networks if row['id'] == body.get('id')), None)
            if not target or not target['writable']: raise GatewayError('Edição de autenticação indisponível para este SSID.')
            if body.get('expected') != target.get('group_expected',target['expected']): raise GatewayError('A segurança da rede mudou. Atualize antes de salvar.')
            mode = body.get('mode')
            if mode not in SECURITY_MODES or mode not in [row['id'] for row in target['profiles']]: raise GatewayError('Selecione um modo de autenticação disponível.')
            if mode != 'wpa2' and target.get('wps_enabled') is not False:
                raise GatewayError('WPA3 exige WPS desativado e reconhecido. Confira o WPS no Huawei antes de alterar o modo.')
            _, beacon, prefix, authentication = SECURITY_MODES[mode]
            group = [row for row in networks if row['ssid'] == target['ssid']]
            params = {'x.X_HW_Token':self.config_token()}; targets = {'RequestFile':WIFI_PATH.lstrip('/')}
            for index,row in enumerate(group):
                if not row['writable'] or mode not in [profile['id'] for profile in row['profiles']]: raise GatewayError('O perfil não está disponível em todos os SSIDs do grupo.')
                if mode != 'wpa2' and row.get('wps_enabled') is not False: raise GatewayError('Desative o WPS de todo o grupo antes de usar WPA3.')
                alias = 'y' if len(group) == 1 else 'y'+str(index); targets[alias] = row['id']
                params.update({alias+'.BeaconType':beacon,alias+'.'+prefix+'AuthenticationMode':authentication,alias+'.'+prefix+'EncryptionModes':'AESEncryption'})
            # No PSK, WPS, radio, enterprise/RADIUS or WAN properties are sent.
            path = WIFI_PATH + ('?5G' if int(target['id'].split('.')[-1]) >= 5 else '?2G')
            self.request('/set.cgi?' + urllib.parse.urlencode(targets), params, referer=path)
            updated = {row['id']:row for row in self.wifi_security()}
            if any(row['id'] not in updated or updated[row['id']]['mode'] != mode or updated[row['id']]['encryption'] != 'AESEncryption' for row in group):
                raise GatewayError('O Huawei não confirmou a autenticação esperada. Confira o painel antes de repetir.')
            return updated[target['id']]
