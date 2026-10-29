"""Connection defaults: persistent address, environment-bound credentials."""
import json
import os
import urllib.parse
from pathlib import Path

from gateway_adapters.errors import GatewayError
from gateway_adapters.transport import GatewayTransport

DEFAULT_MODEL = 'huawei-eg8145x6-10'


def canonical(address):
    if not address: return ''
    base = GatewayTransport(address).base
    parsed = urllib.parse.urlsplit(base)
    if parsed.port == (443 if parsed.scheme == 'https' else 80):
        return parsed.scheme + '://' + parsed.netloc.rsplit(':', 1)[0]
    return base


def saved(store):
    with store() as db:
        row = db.execute("SELECT value FROM app_settings WHERE name='last_connection'").fetchone()
    return json.loads(row[0]) if row else {}


def password():
    filename = os.environ.get('GATEWAY_PASSWORD_FILE', '')
    if filename:
        try:
            with Path(filename).open(encoding='utf-8') as source: value = source.read(4097)
            if len(value) > 4096: raise ValueError()
            return value.rstrip('\r\n')
        except (OSError, ValueError, UnicodeError):
            raise GatewayError('Não foi possível ler a senha padrão configurada no servidor.')
    return os.environ.get('GATEWAY_PASSWORD', '')


def defaults(store):
    previous = saved(store)
    seed = canonical(os.environ.get('GATEWAY_ADDRESS', '').strip())
    # An explicitly changed deployment address overrides the last successful
    # address. Otherwise a manual successful connection becomes the new default.
    address = seed if seed and seed != previous.get('seed') else previous.get('address') or seed
    user = os.environ.get('GATEWAY_USERNAME') or previous.get('username', '')
    model = os.environ.get('GATEWAY_MODEL') or previous.get('model') or DEFAULT_MODEL
    try: configured = bool(password())
    except GatewayError: configured = False
    credential_address = seed
    available = bool(configured and seed and user and address == seed and user == os.environ.get('GATEWAY_USERNAME', '')
                     and model == (os.environ.get('GATEWAY_MODEL') or DEFAULT_MODEL))
    return {'address': address or '', 'username': user, 'model': model,
            'default_credentials_available': available,
            'credential_address': credential_address if configured else '',
            'credential_username': os.environ.get('GATEWAY_USERNAME', '') if configured else '',
            'credential_model': os.environ.get('GATEWAY_MODEL') or DEFAULT_MODEL}


def resolve(store, body):
    preferred = defaults(store)
    address = canonical(body.get('address') or preferred['address'])
    model = body.get('model') or preferred['model']
    user = body.get('username') or preferred['username']
    secret = body.get('password') or ''
    if not secret and body.get('use_default_credentials') is True:
        seed = canonical(os.environ.get('GATEWAY_ADDRESS', '').strip())
        if (not seed or not user or address != seed or user != os.environ.get('GATEWAY_USERNAME', '')
                or model != (os.environ.get('GATEWAY_MODEL') or DEFAULT_MODEL)):
            raise GatewayError('As credenciais padrão só podem ser usadas no gateway, modelo e usuário configurados no servidor.')
        secret = password()
        if not secret: raise GatewayError('Nenhuma senha padrão está configurada no servidor.')
    return model, address, user, secret


def remember(store, gateway, username):
    value = {'address': gateway.base, 'model': gateway.model_id, 'username': username,
             'seed': canonical(os.environ.get('GATEWAY_ADDRESS', '').strip())}
    with store() as db:
        db.execute("INSERT INTO app_settings(name,value) VALUES ('last_connection',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (json.dumps(value),))
