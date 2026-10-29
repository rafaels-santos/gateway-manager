"""Generate a private Compose; inspect only deployment metadata, never passwords."""
import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def inspect_container(name):
    template = '{{json .Mounts}}\n{{json .NetworkSettings.Ports}}\n{{index .Config.Labels "com.docker.compose.project"}}\n{{.Name}}'
    try:
        output = subprocess.check_output(['docker', 'inspect', '--format', template, name], stderr=subprocess.DEVNULL, text=True)
        mounts, ports, project, container_name = output.strip().splitlines()
        data = [item for item in json.loads(mounts) if item['Destination'] == '/data']
        bindings = json.loads(ports).get('8080/tcp') or []
        published = {item['HostPort'] for item in bindings}
        host_ips = sorted({str(ipaddress.ip_address(item['HostIp'])) for item in bindings})
        if len(data) != 1 or len(published) != 1 or project == '<no value>': raise ValueError()
        mount = data[0]
        if mount['Type'] not in ('volume', 'bind') or not mount.get('RW', True): raise ValueError()
        return {'project': project, 'port': int(published.pop()),
                'volume': mount.get('Name') if mount['Type'] == 'volume' else None,
                'bind': mount['Source'] if mount['Type'] == 'bind' else None,
                'container_name': container_name.lstrip('/'), 'host_ips': host_ips}
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError):
        raise ValueError('Não foi possível identificar projeto, porta e armazenamento do contêiner. Verifique o acesso ao Docker; nenhum arquivo foi gerado.')


def connection_defaults(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/connection-defaults', timeout=3) as response:
            data = json.loads(response.read(8192))
        return {key: data.get(key, '') for key in ('address', 'username')}
    except (OSError, ValueError):
        return {}


def quoted(value):
    # Compose expands dollars even inside YAML strings. Escape literal values.
    return json.dumps(str(value).replace('$', '$$'), ensure_ascii=False)


def render(template, *, project, port, address='', username='', volume='gateway-manager-data', bind=None, external=False, password=None, container_name=None, host_ips=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project): raise ValueError('Nome de projeto inválido.')
    if not 1 <= int(port) <= 65535: raise ValueError('Porta inválida.')
    if address:
        parsed = urllib.parse.urlsplit(address if '://' in address else 'http://' + address)
        ip = ipaddress.ip_address(parsed.hostname or '')
        if (parsed.scheme not in ('http','https') or not ip.is_private or ip.is_loopback or ip.is_link_local
                or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
            raise ValueError('Use um IP privado de gateway, sem credenciais na URL.')
        parsed.port  # Validate the optional port.
    if not bind and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', volume): raise ValueError('Nome de volume inválido.')
    if host_ips and set(host_ips) != {'0.0.0.0','::'}:
        mappings = []
        for address_ip in host_ips:
            host_ip = ipaddress.ip_address(address_ip)
            host = f'[{host_ip}]' if host_ip.version == 6 else str(host_ip)
            mappings.append('      - ' + quoted(f'{host}:{int(port)}:8080'))
        template = template.replace('      - "${GATEWAY_MANAGER_PORT:-8080}:8080"', '\n'.join(mappings))
    replacements = {'"${GATEWAY_MANAGER_PROJECT:-gateway-manager}"': quoted(project),
                    '${GATEWAY_MANAGER_PORT:-8080}': str(int(port)),
                    '"${GATEWAY_ADDRESS:-}"': quoted(address),
                    '"${GATEWAY_USERNAME:-}"': quoted(username),
                    '"${GATEWAY_MANAGER_DATA_VOLUME:-gateway-manager-data}"': quoted(volume)}
    if password is not None: replacements['"${GATEWAY_PASSWORD:-}"'] = quoted(password)
    for old, new in replacements.items(): template = template.replace(old, new)
    if container_name:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', container_name): raise ValueError('Nome do contêiner inválido.')
        template = template.replace('  gateway-manager:\n', '  gateway-manager:\n    container_name: ' + quoted(container_name) + '\n', 1)
    if bind:
        if not bind.startswith('/') or '\n' in bind or '\r' in bind: raise ValueError('Bind mount existente não suportado; informe um caminho Linux absoluto.')
        template = template.replace('- gateway-manager-data:/data', '- ' + quoted(bind + ':/data'))
        template = re.sub(r'\nvolumes:\n  gateway-manager-data:\n    name: [^\n]+\n', '\n', template)
    elif external:
        template = template.replace('  gateway-manager-data:\n    name:', '  gateway-manager-data:\n    external: true\n    name:')
    return template


def write_private(path, text, force=False):
    path = Path(path)
    if not path.name.endswith(('.local.yml', '.local.yaml')):
        raise ValueError('Use a extensão .local.yml ou .local.yaml para manter a configuração fora do Git.')
    if path.is_symlink(): raise ValueError('O arquivo de saída não pode ser um link simbólico.')
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        if os.name != 'nt': os.fchmod(output.fileno(), 0o600)
        output.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', help='Detectar projeto, porta e volume de uma instalação existente')
    parser.add_argument('--project')
    parser.add_argument('--port', type=int)
    parser.add_argument('--gateway')
    parser.add_argument('--username')
    parser.add_argument('--volume')
    parser.add_argument('--external-volume', action='store_true')
    parser.add_argument('--ask-password', action='store_true', help='Ler a senha sem exibi-la e incluí-la somente no arquivo privado')
    parser.add_argument('--output', default='compose.local.yml')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        metadata = inspect_container(args.container) if args.container else {}
        if args.volume and metadata and args.volume != metadata.get('volume'):
            raise ValueError('O volume informado não corresponde ao contêiner existente.')
        if args.project and metadata and args.project != metadata.get('project'):
            raise ValueError('O projeto informado não corresponde ao contêiner existente.')
        port = args.port or metadata.get('port') or int(os.environ.get('GATEWAY_MANAGER_PORT', '8080'))
        defaults = connection_defaults(port) if args.container else {}
        secret = getpass.getpass('Senha padrão do gateway (não será exibida): ') if args.ask_password else None
        result = render((ROOT/'docker-compose.yml').read_text(encoding='utf-8'),
                        project=args.project or metadata.get('project') or 'gateway-manager', port=port,
                        address=args.gateway if args.gateway is not None else defaults.get('address') or os.environ.get('GATEWAY_ADDRESS',''),
                        username=args.username if args.username is not None else defaults.get('username') or os.environ.get('GATEWAY_USERNAME',''),
                        volume=args.volume or metadata.get('volume') or 'gateway-manager-data', bind=metadata.get('bind'),
                        external=bool(metadata.get('volume')) or args.external_volume, password=secret,
                        container_name=metadata.get('container_name'))
        write_private(args.output, result, args.force)
        print(f'Compose privado gerado: {args.output}')
        print('Preserve este arquivo e seus valores. Atualize por redeploy com pull da imagem; não use down -v.')
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
