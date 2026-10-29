"""Radio changes matching the inspected BREBG2 native command sequence."""
import hashlib
import re
import urllib.parse

from ..errors import GatewayError
from ..parsers import parse_constructors
from .integration_report import selected_functions
from .radio_options import preview_radio

SHARED_SOURCE = '/html/amp/common/wlan_list.asp'
COMMON_SOURCE = '/html/amp/wlanadv/wlanadvance_com_api.asp'
ACTION = 'InternetGatewayDevice.X_HW_DEBUG.WLANConfigAction'
CHECK_CONTRACT = 'functionCheckConfigChannel(selChannel,curChannel){if((selChannel==0)||(selChannel==-1)){returnfalse;}return(selChannel!=curChannel);}'
FLAGS = ('WdsFlag', 'fobidChannel', 'DoubleFreqFlag', 'dfsChSwitch')


def literal_flag(source, name):
    values = re.findall(r'\bvar\s+'+re.escape(name)+r'''\s*=\s*["']?([01])["']?\s*;''', source)
    return int(values[0]) if values and len(set(values)) == 1 else None


def scope_index(source):
    functions = selected_functions(source, ('stWlanWifi',))
    body = functions.get('stWlanWifi', '')
    signature = re.search(r'function\s+stWlanWifi\s*\(([^)]*)\)', body)
    assignment = re.search(r'this\.X_HW_AutoChannelScope\s*=\s*([A-Za-z_$][\w$]*)\s*;', body)
    if not signature or not assignment: return None
    names = [name.strip() for name in signature[1].split(',')]
    return names.index(assignment[1]) if assignment[1] in names else None


def canonical_scope(value):
    if value == '0': return '0'
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}(?:,\d{1,3})*', value): return None
    return ','.join(str(n) for n in sorted(set(map(int, value.split(',')))))


def automatic_scope(options, width):
    option = next(row for row in options if row['value'] == width)
    return ','.join(row['value'] for row in option['channels']
                    if int(row['value']) > 0 and not 52 <= int(row['value']) <= 144)


def enrich_radios(gateway, page, radios):
    try:
        shared = gateway.request(SHARED_SOURCE, max_redirects=0)
        common = gateway.request(COMMON_SOURCE, max_redirects=0)
    except GatewayError: shared = common = ''
    all_source = page+'\n'+shared+'\n'+common
    flags = {name: literal_flag(all_source, name) for name in FLAGS}
    check = selected_functions(common, ('CheckConfigChannel',)).get('CheckConfigChannel', '')
    contract = re.sub(r'\s+', '', check) == CHECK_CONTRACT
    contract = contract and all(marker in page for marker in ('y.Channel', 'y.AutoChannelEnable', 'y.X_HW_HT20',
                            'y.X_HW_AutoChannelScope', ACTION, 'c1.ActionType', 'c2.ActionType', 'c2.SSIDList'))
    # dfsChSwitch starts at 0 in the common script and is computed by the UI.
    # It is not a persisted capability bit. DFS options come from the exact
    # BR/11ax/firmware matrix observed in the native UI, not this initializer.
    contract = contract and flags['WdsFlag'] == 0 and flags['fobidChannel'] == 0 and flags['DoubleFreqFlag'] == 1 and flags['dfsChSwitch'] in (0, 1)
    index = scope_index(all_source)
    scopes = {str(row[0]): str(row[index]) for row in parse_constructors(all_source, 'stWlanWifi')
              if index is not None and len(row) > index}
    steering = [row[1] for row in parse_constructors(all_source, 'StXHWGlobalConfig') if len(row) == 2
                and row[0] == 'InternetGatewayDevice.LANDevice.1.WiFi.X_HW_GlobalConfig' and row[1] in ('0', '1')]
    steering = steering[0] if steering and len(set(steering)) == 1 else None
    for radio in radios:
        scope = canonical_scope(scopes.get(radio['id']))
        five = radio['id'].endswith('.5')
        radio['auto_scope'] = scope
        radio['band_steering'] = steering
        selection = str(radio['channel']) if not radio['auto_channel'] else '0' if not five else '-1' if scope == '0' else None
        if five and radio['auto_channel'] and radio['channel_options']:
            if scope == canonical_scope(automatic_scope(radio['channel_options'], radio['width_code'])): selection = '0'
        radio['channel_selection'] = selection
        radio['channel_write_available'] = bool(contract and radio['channel_options'] and steering is not None
                                                 and (not five or scope is not None) and selection is not None)
        radio['expected'] = hashlib.sha256((radio['expected']+str(scope)+str(steering)+str(flags)+check).encode()).hexdigest()
    return radios


def apply_radio_change(gateway, body):
    from .radio_security import RADIO_PAGE
    if body.get('confirm') != 'WIFI': raise GatewayError('Confirme a alteração de canal e largura.')
    with gateway.lock:
        before = gateway.radio_config()
        target = next((row for row in before if row['id'] == body.get('id')), None)
        if not target or not target.get('channel_write_available'):
            raise GatewayError('Contrato de rádio, perfil ou dependências ainda não reconhecidos. Consulte o diagnóstico de integração.')
        plan = preview_radio(target, body)
        selection, width = plan['channel'], plan['width_code']
        if selection == target['channel_selection'] and width == str(target['width_code']): return target
        networks = gateway.wifi_config()
        automatic = selection in ('0', '-1')
        targets = {}; params = {}
        # This deliberately reproduces CheckConfigChannel as inspected: automatic
        # or an unchanged operating channel needs the c1/c2 bracket.
        bracket = automatic or selection == str(target['channel'])
        if bracket: targets['c1'] = ACTION; params['c1.ActionType'] = '0'
        targets['y'] = target['id']
        params.update({'y.Channel': '0' if automatic else selection,
                       'y.AutoChannelEnable': '1' if automatic else '0', 'y.X_HW_HT20': width})
        scope = target['auto_scope']
        if target['id'].endswith('.5') and automatic:
            scope = '0' if selection == '-1' else automatic_scope(target['channel_options'], width)
            params['y.X_HW_AutoChannelScope'] = scope
        if bracket:
            targets['c2'] = ACTION; params.update({'c2.ActionType': '1', 'c2.SSIDList': target['id'].split('.')[-1]})
        targets['RequestFile'] = RADIO_PAGE.lstrip('/')
        params['x.X_HW_Token'] = gateway.config_token()
        try:
            gateway.request('/set.cgi?'+urllib.parse.urlencode(targets), params,
                            referer=RADIO_PAGE+('?5G' if target['id'].endswith('.5') else '?2G'))
        except GatewayError:
            # Verify once after an ambiguous transport response; never resend.
            pass
        after = gateway.radio_config()
        updated = next((row for row in after if row['id'] == target['id']), None)
        if (not updated or updated['auto_channel'] != automatic or str(updated['width_code']) != width
                or any(updated[key] != target[key] for key in ('power','country','standard','band_steering'))
                or updated['auto_scope'] != canonical_scope(scope)
                or not automatic and str(updated['channel']) != selection):
            raise GatewayError('Canal e largura não confirmados com os demais parâmetros preservados. Confira o Huawei antes de repetir; o comando não foi reenviado.')
        preserved = ('power','country','standard','band_steering','auto_scope','auto_channel','width_code')
        for old in before:
            if old['id'] == target['id']: continue
            current = next((row for row in after if row['id'] == old['id']), None)
            if not current or any(current[key] != old[key] for key in preserved) or not old['auto_channel'] and current['channel'] != old['channel']:
                raise GatewayError('Outra banda mudou durante a operação. Confira o Huawei antes de repetir.')
        if sorted(gateway.wifi_config(),key=lambda row:row['id']) != sorted(networks,key=lambda row:row['id']):
            raise GatewayError('Os SSIDs mudaram durante a alteração de rádio. Confira o Huawei antes de repetir.')
        return updated
