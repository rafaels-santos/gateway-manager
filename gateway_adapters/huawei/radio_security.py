"""Narrow Wi-Fi operations using property names inspected in the firmware UI."""
import re
import urllib.parse

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
            networks.append({**public, 'expected':fingerprint(public), 'profiles':profiles,
                             'writable': bool(personal and profiles and not public['ssid'].casefold().startswith('easymesh_backhaul'))})
        if not networks: raise GatewayError('Nenhum SSID com dados de segurança reconhecidos.')
        return networks

    def save_wifi_security(self, body):
        if body.get('confirm') != 'WIFI': raise GatewayError('Confirme a alteração de autenticação Wi-Fi.')
        with self.lock:
            target = next((row for row in self.wifi_security() if row['id'] == body.get('id')), None)
            if not target or not target['writable']: raise GatewayError('Edição de autenticação indisponível para este SSID.')
            if body.get('expected') != target['expected']: raise GatewayError('A segurança da rede mudou. Atualize antes de salvar.')
            mode = body.get('mode')
            if mode not in SECURITY_MODES or mode not in [row['id'] for row in target['profiles']]: raise GatewayError('Selecione um modo de autenticação disponível.')
            if mode != 'wpa2' and target.get('wps_enabled') is not False:
                raise GatewayError('WPA3 exige WPS desativado e reconhecido. Confira o WPS no Huawei antes de alterar o modo.')
            _, beacon, prefix, authentication = SECURITY_MODES[mode]
            params = {'y.BeaconType':beacon, 'y.'+prefix+'AuthenticationMode':authentication,
                      'y.'+prefix+'EncryptionModes':'AESEncryption', 'x.X_HW_Token':self.config_token()}
            # No PSK, WPS, radio, enterprise/RADIUS or WAN properties are sent.
            path = WIFI_PATH + ('?5G' if int(target['id'].split('.')[-1]) >= 5 else '?2G')
            self.request('/set.cgi?' + urllib.parse.urlencode({'y':target['id'],'RequestFile':WIFI_PATH.lstrip('/')}), params, referer=path)
            updated = next((row for row in self.wifi_security() if row['id'] == target['id']), None)
            if not updated or updated['mode'] != mode or updated['encryption'] != 'AESEncryption':
                raise GatewayError('O Huawei não confirmou a autenticação esperada. Confira o painel antes de repetir.')
            return updated
