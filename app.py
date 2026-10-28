from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os

os.chdir(os.path.join(os.path.dirname(__file__), 'static'))
ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), SimpleHTTPRequestHandler).serve_forever()
