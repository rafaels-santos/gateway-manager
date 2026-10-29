"""Local network planning, bounded diagnostics and observed event history.

This module never sends configuration commands to a gateway.
"""
import datetime
import ipaddress
import json
import socket

from gateway_adapters.errors import GatewayError


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS network_observations (gateway TEXT, category TEXT, payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(gateway,category))')
    db.execute('CREATE TABLE IF NOT EXISTS network_events (id INTEGER PRIMARY KEY AUTOINCREMENT, gateway TEXT NOT NULL, occurred_at TEXT NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL, evidence TEXT NOT NULL, mac TEXT NOT NULL DEFAULT \'\')')
    db.execute('CREATE INDEX IF NOT EXISTS network_events_gateway ON network_events(gateway,id)')


def event(db, gateway, kind, message, *, level='INFO', evidence='observed', mac=''):
    db.execute('INSERT INTO network_events (gateway,occurred_at,level,kind,message,evidence,mac) VALUES (?,?,?,?,?,?,?)',
               (gateway, utc_now(), level, kind, message[:1000], evidence, mac))
    db.execute('DELETE FROM network_events WHERE gateway=? AND id NOT IN (SELECT id FROM network_events WHERE gateway=? ORDER BY id DESC LIMIT 2000)', (gateway, gateway))


def observe(db, gateway, category, payload):
    previous = db.execute('SELECT payload FROM network_observations WHERE gateway=? AND category=?', (gateway, category)).fetchone()
    db.execute('INSERT INTO network_observations VALUES (?,?,?,?) ON CONFLICT(gateway,category) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
               (gateway, category, json.dumps(payload, sort_keys=True), utc_now()))
    return json.loads(previous[0]) if previous else None


def observe_devices(db, gateway, devices):
    current = {row['mac'].lower(): {'ip': row.get('ip', ''), 'port': row.get('port', '')}
               for row in devices if row.get('mac') and row.get('status') == 'online'}
    previous = observe(db, gateway, 'clients', current)
    if previous is None:
        return
    for mac in sorted(current.keys() - previous.keys()):
        event(db, gateway, 'connected', f'{mac.upper()} apareceu conectado · IP {current[mac]["ip"] or "não informado"}.', mac=mac)
    for mac in sorted(previous.keys() - current.keys()):
        event(db, gateway, 'disconnected', f'{mac.upper()} deixou de aparecer na lista de clientes conectados.', mac=mac)
    for mac in sorted(current.keys() & previous.keys()):
        old, new = previous[mac], current[mac]
        if old['ip'] != new['ip']:
            event(db, gateway, 'ip_changed', f'{mac.upper()} · IP observado mudou de {old["ip"] or "não informado"} para {new["ip"] or "não informado"}.', mac=mac)
        if old['port'] and new['port'] and old['port'] != new['port']:
            event(db, gateway, 'interface_changed', f'{mac.upper()} · conexão mudou de {old["port"]} para {new["port"]}.', mac=mac)


def observe_pages(db, gateway, pages):
    for page in pages:
        if page.get('status') != 'available' or not page.get('recognized'):
            continue
        feature = page['id']
        observations = page.get('observations', [])
        # Store only normalized allowlisted observations, never raw HTML or credentials.
        values = sorted(({'field': str(row.get('field', '')), 'label': str(row['label']), 'value': str(row['value'])}
                         for row in observations), key=lambda row: (row['field'], row['label'], row['value']))
        previous = observe(db, gateway, 'feature:' + feature, values)
        if previous is not None and previous != values and feature not in ('system_information', 'mesh_topology'):
            event(db, gateway, 'configuration_changed', f'Mudança observada em {page["label"]}. A leitura não identifica quem realizou a alteração.')
        if feature == 'system_information':
            ports = {row['port']: row['status'] for row in observations if row.get('port')}
            old_ports = observe(db, gateway, 'ports', ports)
            for port, status in ports.items():
                if old_ports and port in old_ports and old_ports[port] != status:
                    event(db, gateway, 'link_changed', f'{port} · estado mudou de {old_ports[port]} para {status}.', level='WAR' if status.casefold() in ('down', 'disconnected', 'linkdown', 'inactive') else 'INFO')
            uptime = next((row.get('seconds') for row in observations if row.get('metric') == 'uptime'), None)
            if uptime is not None:
                old = observe(db, gateway, 'uptime', uptime)
                if old is not None and uptime < old:
                    event(db, gateway, 'possible_restart', 'Possível reinício: o tempo de atividade informado pelo Huawei diminuiu. Confirme a causa nos logs do equipamento.', level='WAR', evidence='inferred')


def history(db, gateway, *, level='', kind='', query='', before=None, limit=200):
    clauses, params = ['gateway=?'], [gateway]
    if level:
        if level not in ('INFO', 'WAR', 'ERROR'):
            raise GatewayError('Nível de evento inválido.')
        clauses.append('level=?'); params.append(level)
    if kind:
        clauses.append('kind=?'); params.append(kind[:60])
    if query:
        clauses.append('(instr(lower(message),lower(?))>0 OR instr(lower(mac),lower(?))>0)'); params.extend((query[:160], query[:160]))
    if before is not None:
        try: before = int(before)
        except (ValueError, TypeError): raise GatewayError('Página de histórico inválida.')
        clauses.append('id<?'); params.append(before)
    rows = db.execute('SELECT id,occurred_at,level,kind,message,evidence,mac FROM network_events WHERE ' + ' AND '.join(clauses) + ' ORDER BY id DESC LIMIT ?', [*params, min(max(int(limit), 1), 200) + 1]).fetchall()
    keys = ('id', 'occurred_at', 'level', 'kind', 'message', 'evidence', 'mac')
    return {'events': [dict(zip(keys, row)) for row in rows[:limit]], 'next_before': rows[limit-1][0] if len(rows) > limit else None}


def preview_lan(current, reservations, devices, proposed):
    try:
        address = ipaddress.IPv4Address(str(proposed.get('ip', '')).strip())
        mask = str(proposed.get('mask', '')).strip()
        # A dotted netmask is required; wildcard/host masks are not accepted.
        mask_ip = ipaddress.IPv4Address(mask)
        bits = f'{int(mask_ip):032b}'
        if '01' in bits:
            raise ValueError()
        network = ipaddress.IPv4Network((str(address), mask), strict=False)
        if not 8 <= network.prefixlen <= 30 or not any(network.subnet_of(ipaddress.IPv4Network(block)) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            raise ValueError()
        if address in (network.network_address, network.broadcast_address):
            raise ValueError()
    except (ValueError, TypeError):
        raise GatewayError('Informe um IPv4 privado utilizável e uma máscara contígua entre /8 e /30.')
    blockers, warnings = [], []
    pool_start, pool_end = ipaddress.IPv4Address(current['start']), ipaddress.IPv4Address(current['end'])
    pool_valid = pool_start in network and pool_end in network and pool_start <= pool_end and pool_start not in (network.network_address, network.broadcast_address) and pool_end not in (network.network_address, network.broadcast_address)
    if not pool_valid:
        (blockers if current['enabled'] else warnings).append('O intervalo DHCP atual não cabe na nova rede; será necessário ajustar início e fim em conjunto.')
    if current['enabled'] and pool_start <= address <= pool_end:
        blockers.append('O novo IP do gateway está dentro do intervalo DHCP atual.')
    affected = []
    for row in reservations:
        ip = ipaddress.IPv4Address(row['ip'])
        if ip not in network or ip in (network.network_address, network.broadcast_address) or ip == address:
            affected.append({'mac': row['mac'].upper(), 'ip': row['ip'], 'enabled': row.get('enabled', True)})
    if any(row['enabled'] for row in affected):
        blockers.append('Há reservas ativas incompatíveis com a nova rede ou com o novo IP do gateway.')
    occupied = [row['mac'].upper() for row in devices if row.get('status') == 'online' and row.get('ip') == str(address) and str(address) != current['lan_ip']]
    if occupied:
        blockers.append('Outro cliente conectado já usa o IP proposto: ' + ', '.join(occupied) + '.')
    changed = str(address) != current['lan_ip'] or str(network.netmask) != current['mask']
    if changed:
        warnings.append('Clientes com IP configurado manualmente podem perder acesso e precisar de ajuste no próprio dispositivo.')
    return {'current': {key: current[key] for key in ('lan_ip', 'mask', 'start', 'end', 'enabled')},
            'proposed': {'ip': str(address), 'mask': str(network.netmask), 'network': str(network)},
            'changed': changed, 'blockers': blockers, 'warnings': warnings, 'affected_reservations': affected,
            'apply_available': False,
            'recovery': ['Conecte um computador por cabo e mantenha acesso físico ao equipamento.',
                         'Após uma alteração pelo painel Huawei, renove o DHCP do computador ou configure um IP da nova rede.',
                         f'Abra o painel em http://{address}/ e atualize o endereço do gateway no login do aplicativo.',
                         'Se o acesso falhar, confira endereço e máscara pelo painel local; não há rollback automático.'] if changed else []}


def tcp_diagnostic(current, devices, target, port):
    try:
        address = ipaddress.IPv4Address(str(target))
        port = int(port)
        network = ipaddress.IPv4Network((current['lan_ip'], current['mask']), strict=False)
    except (ValueError, TypeError):
        raise GatewayError('Informe um IPv4 da LAN e uma porta válida.')
    if not address.is_private or address not in network or address in (network.network_address, network.broadcast_address) or address.is_loopback or address.is_link_local or address.is_multicast:
        raise GatewayError('O diagnóstico aceita somente endereços utilizáveis da LAN atual.')
    known = {row.get('ip') for row in devices if row.get('status') == 'online'} | {current['lan_ip']}
    if str(address) not in known or port not in (80, 443):
        raise GatewayError('Escolha um cliente conectado ou o gateway e a porta HTTP (80) ou HTTPS (443).')
    import time
    started = time.monotonic()
    try:
        with socket.create_connection((str(address), port), timeout=2):
            outcome, description = 'reachable', 'O serviço aceitou uma conexão TCP.'
    except ConnectionRefusedError:
        outcome, description = 'refused', 'O destino recusou esta porta. Isso não comprova isolamento de rede.'
    except (OSError, TimeoutError):
        outcome, description = 'unreachable', 'Não houve conexão nesta tentativa. Firewall, ausência de serviço ou caminho indisponível podem causar esse resultado.'
    return {'target': str(address), 'port': port, 'outcome': outcome, 'description': description,
            'duration_ms': round((time.monotonic() - started) * 1000), 'origin': 'Servidor do Gateway Manager; este diagnóstico não parte do Huawei.'}
