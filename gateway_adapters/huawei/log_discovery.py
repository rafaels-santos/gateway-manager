"""Discover read-only log pages from the authenticated firmware menu."""
import html
import re
import urllib.parse
from html.parser import HTMLParser

from ..errors import GatewayError


def log_links(source, base='/index.asp'):
    source=html.unescape(re.sub(r'\\(?:x|u00)([0-9a-fA-F]{2})',lambda match:chr(int(match[1],16)),source))
    source=source.replace(r'\"','"').replace(r"\'","'").replace(r'\/','/')
    result={}
    for match in re.finditer(r'''["']([^"'\s<>]*(?:html/ssmp/|\.\./)[^"'\s<>]*log[^"'\s<>]*\.asp)["']''',source,re.I):
        href=match[1]; original=urllib.parse.urlsplit(href)
        if original.scheme or original.netloc or '\\' in href or original.query: continue
        path=urllib.parse.urljoin(base,href)
        if not path.startswith('/html/ssmp/') or re.search(r'delete|reset|reboot|apply|upgrade|debug|firewall|intrusion',path,re.I): continue
        if re.search(r'aplog',path,re.I): result.setdefault('ap',path)
        elif re.search(r'userlog|/logview/',path,re.I): result.setdefault('user',path)
    return result


class MenuScripts(HTMLParser):
    def __init__(self): super().__init__();self.paths=[]
    def handle_starttag(self,tag,attrs):
        if tag.casefold()!='script':return
        value=dict(attrs).get('src','');parsed=urllib.parse.urlsplit(value)
        if parsed.scheme or parsed.netloc or '\\' in value:return
        path=urllib.parse.urljoin('/index.asp',parsed.path)
        if re.search(r'delete|reset|reboot|apply|upgrade',path,re.I):return
        if 'menu' in path.rsplit('/',1)[-1].casefold() and re.search(r'\.(?:js|asp)$',path,re.I):
            self.paths.append(path+('?'+parsed.query if parsed.query else ''))


def discover_log_paths(gateway):
    source=gateway.request('/index.asp',max_redirects=0)
    paths=log_links(source)
    if 'user' not in paths:
        parser=MenuScripts();parser.feed(source)
        # Only scripts explicitly declared by this authenticated page. Their
        # navigation strings resolve against the document, not the script URL.
        for path in list(dict.fromkeys(parser.paths))[:3]:
            try: menu=gateway.request(path,max_redirects=0)
            except GatewayError as error:
                if '(HTTP 404)' in str(error): continue
                raise
            paths.update(log_links(menu))
            if 'user' in paths: break
    return paths
