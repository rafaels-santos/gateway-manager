"""Read-only export of selected native function bodies, never page state arrays."""
import hashlib
import re

from ..errors import GatewayError

SOURCES = {
    '/html/amp/wlanadv/wlanadvance_api.asp': ('AddSubmitParamChannel', 'AddSubmitParam', 'CheckConfigChannel', 'stWlanWifi', 'StXHWGlobalConfig'),
    '/html/amp/wlanadv/wlanadvance_com_api.asp': ('CheckConfigChannel', 'X_HW_HT20Change', 'ChannelChange'),
    '/html/amp/common/wlan_list.asp': ('stWlanWifi', 'StXHWGlobalConfig'),
}


def selected_functions(source, names):
    result = {}
    for name in names:
        match = re.search(r'(?m)^\s*function\s+'+re.escape(name)+r'\s*\([^)]*\)\s*\{', source)
        if not match: continue
        start = match.start(); cursor = match.end(); depth = 1; quote = None; comment = None
        while cursor < len(source) and cursor-start < 80000:
            char, pair = source[cursor], source[cursor:cursor+2]
            if comment == '//':
                if char == '\n': comment = None
            elif comment == '/*':
                if pair == '*/': comment = None; cursor += 1
            elif quote:
                if char == '\\': cursor += 1
                elif char == quote: quote = None
            elif pair in ('//', '/*'): comment = pair; cursor += 1
            elif char == '/':
                # A regular expression can contain braces. Without a full JS
                # lexer, omit the function rather than risk crossing its end.
                break
            elif char in ('\"', "'", '`'): quote = char
            elif char == '{': depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    body = source[start:cursor+1].strip()
                    # Runtime arrays and credential literals are not necessary to
                    # inspect radio commands. Omit a function if either appears.
                    if not re.search(r'new\s+(?:st|St)\w+\s*\(|(?:password|psk|secret|token)\w*\s*=\s*[\"\'][^\"\']+[\"\']', body, re.I):
                        result[name] = body
                    break
            cursor += 1
    return result


def integration_report(gateway):
    sources = []
    for path, names in SOURCES.items():
        try:
            source = gateway.request(path, max_redirects=0)
            functions = selected_functions(source, names)
            from .radio_control import FLAGS, literal_flag
            sources.append({'path': path, 'status': 'available' if functions else 'unrecognized',
                            'sha256': hashlib.sha256('\n'.join(functions.values()).encode()).hexdigest(), 'functions': functions,
                            'flags': {name: literal_flag(source,name) for name in FLAGS},
                            'flags_note': 'Inicializadores do código, não valores calculados pelo JavaScript em execução.'})
        except GatewayError:
            sources.append({'path': path, 'status': 'unavailable', 'functions': {}})
    identity = getattr(gateway, 'identity', {}) or {}
    return {'schema': 1, 'model': gateway.model_id, 'hardware': identity.get('hardware'),
            'firmware': identity.get('firmware'), 'read_only': True, 'sources': sources}
