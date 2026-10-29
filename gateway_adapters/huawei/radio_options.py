"""Options observed on BREBG2/BR/11ax; never a general regulatory database."""
from ..errors import GatewayError

WIDTHS = {'0': 'Auto 20/40 MHz', '1': '20 MHz', '2': '40 MHz',
          '3': 'Auto 20/40/80 MHz', '4': 'Auto 20/40/80/160 MHz'}
FIVE_CHANNELS = [36, 40, 44, 48, 52, 56, 60, 64, *range(100, 145, 4), 149, 153, 157, 161]


def options_for(identity, supported, radio):
    if (radio.get('id') not in ('InternetGatewayDevice.LANDevice.1.WLANConfiguration.1',
                               'InternetGatewayDevice.LANDevice.1.WLANConfiguration.5')
            or not supported or identity.get('hardware') != '343D.D'
            or identity.get('firmware') != 'V5R024C10S106'
            or radio['country'] != 'BR' or radio['standard'] != '11ax'):
        return []
    five = radio['id'].endswith('.5')
    result = []
    for code in ('0', '1', '2', '3', '4') if five else ('0', '1', '2'):
        automatic = [{'value': '-1', 'label': 'Automático (com DFS)'},
                     {'value': '0', 'label': 'Automático sem DFS'}] if five else [{'value': '0', 'label': 'Automático'}]
        channels = FIVE_CHANNELS + ([165] if code == '1' else []) if five else range(1, 14)
        result.append({'value': code, 'label': WIDTHS[code], 'channels': automatic + [
            {'value': str(value), 'label': str(value)} for value in channels]})
    return result


def preview_radio(target, body):
    if body.get('expected') != target['expected']:
        raise GatewayError('Os parâmetros do rádio mudaram. Atualize antes de revisar.')
    width, channel = str(body.get('width_code', '')), str(body.get('channel', ''))
    option = next((row for row in target.get('channel_options', []) if row['value'] == width), None)
    if not option or channel not in [row['value'] for row in option['channels']]:
        raise GatewayError('Combinação de canal e largura não conferida para este perfil.')
    return {'id': target['id'], 'band': target['band'], 'width_code': width, 'channel': channel,
            'width_label': option['label'],
            'channel_label': next(row['label'] for row in option['channels'] if row['value'] == channel),
            'apply_available': False,
            'warnings': ['A alteração afeta todos os clientes e enlaces de cobertura desta banda.',
                         'Canais DFS podem exigir espera e mudar quando houver detecção de radar.',
                         'Prévia sem gravação: as ações auxiliares do firmware ainda precisam ser conferidas.']}
