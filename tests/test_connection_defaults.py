import io
import json
import os
from pathlib import Path
import tempfile
import threading
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from email.message import Message

import app
from services import connection, storage
from gateway_adapters.errors import GatewayError
from tools import generate_compose as compose


class ConnectionDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=app.ROOT)
        self.directory = Path(self.temp.name)
        self.store = lambda: storage.open_database(self.directory)
        self.environment = patch.dict(os.environ, {'GATEWAY_ADDRESS':'', 'GATEWAY_USERNAME':'', 'GATEWAY_PASSWORD':'', 'GATEWAY_PASSWORD_FILE':'', 'GATEWAY_MODEL':connection.DEFAULT_MODEL})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def remember(self, address):
        connection.remember(self.store, SimpleNamespace(base=address, model_id=connection.DEFAULT_MODEL), 'administrator')

    def test_last_successful_address_survives_reopening_storage_without_password(self):
        self.remember('http://192.168.50.1')
        reopened = lambda: storage.open_database(self.directory)
        self.assertEqual(connection.defaults(reopened)['address'], 'http://192.168.50.1')
        self.assertEqual(connection.defaults(reopened)['username'], 'administrator')
        self.assertEqual(set(connection.saved(reopened)), {'address', 'username', 'model', 'seed'})

    def test_same_environment_seed_preserves_manual_target_but_changed_seed_overrides(self):
        os.environ['GATEWAY_ADDRESS'] = '192.168.50.1'
        self.remember('http://192.168.50.2')
        self.assertEqual(connection.defaults(self.store)['address'], 'http://192.168.50.2')
        os.environ['GATEWAY_ADDRESS'] = '192.168.50.3'
        self.assertEqual(connection.defaults(self.store)['address'], 'http://192.168.50.3')

    def configure(self):
        os.environ.update(GATEWAY_ADDRESS='192.168.50.1', GATEWAY_USERNAME='administrator', GATEWAY_PASSWORD='test-only-server-password')

    def test_default_password_never_appears_in_public_settings_or_storage(self):
        self.configure()
        result = connection.defaults(self.store)
        self.assertTrue(result['default_credentials_available'])
        self.assertNotIn(os.environ['GATEWAY_PASSWORD'], json.dumps(result))
        self.remember('http://192.168.50.1')
        self.assertNotIn(os.environ['GATEWAY_PASSWORD'], json.dumps(connection.saved(self.store)))

    def test_default_password_is_bound_to_exact_target_username_and_model(self):
        self.configure()
        body = {'use_default_credentials': True}
        self.assertEqual(connection.resolve(self.store, body)[-1], os.environ['GATEWAY_PASSWORD'])
        for change in ({'address':'192.168.50.2'}, {'username':'another'}, {'model':'another'}, {'address':'https://192.168.50.1'}, {'address':'192.168.50.1:8080'}):
            with self.subTest(change=change), self.assertRaises(GatewayError):
                connection.resolve(self.store, {**body, **change})
        self.assertEqual(connection.resolve(self.store, {**body, 'address':'http://192.168.50.1:80/'})[-1], os.environ['GATEWAY_PASSWORD'])

    def test_explicit_password_overrides_server_password_and_requires_no_default_flag(self):
        self.configure()
        self.assertEqual(connection.resolve(self.store, {'address':'192.168.50.2','password':'typed-password','use_default_credentials':True})[-1], 'typed-password')
        self.assertEqual(connection.resolve(self.store, {})[-1], '')

    def test_password_file_is_supported_and_read_errors_are_safe(self):
        self.configure()
        secret = self.directory/'password'
        secret.write_text('file-test-password\n', encoding='utf-8')
        os.environ['GATEWAY_PASSWORD_FILE'] = str(secret)
        self.assertEqual(connection.resolve(self.store, {'use_default_credentials':True})[-1], 'file-test-password')
        secret.unlink()
        with self.assertRaisesRegex(GatewayError, 'Não foi possível ler'):
            connection.resolve(self.store, {'use_default_credentials':True})

    def request(self, path, body=None, cookie=None):
        handler = app.Handler.__new__(app.Handler)
        handler.headers = Message()
        for key,value in {'Origin':'http://127.0.0.1:8765','Host':'127.0.0.1:8765','Content-Type':'application/json'}.items(): handler.headers[key]=value
        if cookie: handler.headers['Cookie']=cookie
        payload = json.dumps(body).encode() if body is not None else b''
        handler.headers['Content-Length']=str(len(payload))
        handler.path=path; handler.request_version='HTTP/1.1'; handler.requestline='TEST'
        handler.rfile=io.BytesIO(payload); handler.wfile=io.BytesIO()
        with patch.object(app, 'DATA_DIR', self.directory):
            handler.do_GET() if body is None else handler.do_POST()
        head,data=handler.wfile.getvalue().split(b'\r\n\r\n',1)
        return int(head.split(b' ')[1]),json.loads(data)

    def test_public_bootstrap_excludes_password_and_failed_login_does_not_change_default(self):
        self.configure(); self.remember('http://192.168.50.1')
        status,data=self.request('/api/connection-defaults')
        self.assertEqual(status,200)
        self.assertNotIn(os.environ['GATEWAY_PASSWORD'],json.dumps(data))
        fake=SimpleNamespace(login=lambda *args: (_ for _ in ()).throw(GatewayError('Credenciais rejeitadas')))
        with patch.object(app,'create_gateway',return_value=fake):
            status,data=self.request('/api/login',{'address':'192.168.50.2','username':'administrator','password':'wrong'})
        self.assertEqual(status,400)
        self.assertEqual(connection.defaults(self.store)['address'],'http://192.168.50.1')

    def test_successful_login_saves_target_and_restored_session_exposes_its_actual_address(self):
        fake=SimpleNamespace(base='http://192.168.50.2',model_id=connection.DEFAULT_MODEL,model_label='Huawei Test',lock=threading.RLock(),devices=lambda:[],identity={'firmware':'test'})
        with patch.object(app,'create_gateway',return_value=fake), patch.object(app,'session_identity',return_value=fake.identity), patch.object(app,'start_monitor'), patch.dict(app.SESSIONS,{},clear=True), patch.object(fake,'login',create=True) as login:
            status,data=self.request('/api/login',{'address':'192.168.50.2','username':'administrator','password':'test-typed-password'})
            self.assertEqual(status,200)
            login.assert_called_once_with('administrator','test-typed-password')
            cookie='session='+next(iter(app.SESSIONS))
            status,restored=self.request('/api/session',cookie=cookie)
            self.assertEqual(status,200)
            self.assertEqual(restored['address'],fake.base)
        self.assertNotIn('test-typed-password',json.dumps(data)+json.dumps(connection.saved(self.store)))
        self.assertEqual(connection.defaults(self.store)['address'],fake.base)


class ComposeGeneratorTests(unittest.TestCase):
    def setUp(self): self.template=(compose.ROOT/'docker-compose.yml').read_text(encoding='utf-8')

    def test_existing_volume_project_and_port_are_preserved_without_reading_secrets(self):
        metadata='[{"Type":"volume","Name":"existing_data","Destination":"/data","RW":true}]\n{"8080/tcp":[{"HostPort":"8089"}]}\nexisting_project\n/gateway-manager\n'
        with patch.object(compose.subprocess,'check_output',return_value=metadata) as command:
            detected=compose.inspect_container('gateway-manager')
        self.assertNotIn('.Config.Env',str(command.call_args))
        rendered=compose.render(self.template,external=True,**detected)
        self.assertIn('name: "existing_project"',rendered)
        self.assertIn('"8089:8080"',rendered)
        self.assertIn('external: true\n    name: "existing_data"',rendered)
        self.assertIn('container_name: "gateway-manager"',rendered)
        self.assertNotIn('/var/run/docker.sock',rendered)
        self.assertIn('pull_policy: always',rendered)
        self.assertIn('watchtower.enable: "false"',rendered)

    def test_missing_or_ambiguous_storage_refuses_to_generate_new_empty_volume(self):
        with patch.object(compose.subprocess,'check_output',return_value='[]\n{"8080/tcp":[{"HostPort":"8089"}]}\nexisting\n/app'):
            with self.assertRaises(ValueError): compose.inspect_container('gateway-manager')

    def test_bind_mount_is_preserved_without_creating_unrelated_named_volume(self):
        rendered=compose.render(self.template,project='existing',port=8089,bind='/srv/gateway/data')
        self.assertIn('"/srv/gateway/data:/data"',rendered)
        self.assertNotIn('gateway-manager-data',rendered)

    def test_password_interpolation_is_escaped_and_private_files_cannot_overwrite_template(self):
        rendered=compose.render(self.template,project='example',port=8080,password='test$PASSWORD:"\nvalue')
        self.assertIn('test$$PASSWORD',rendered)
        self.assertIn('\\nvalue',rendered)
        with tempfile.TemporaryDirectory(dir=compose.ROOT) as folder:
            target=Path(folder)/'compose.local.yml'
            compose.write_private(target,rendered)
            with self.assertRaises(FileExistsError): compose.write_private(target,rendered)
            with self.assertRaises(ValueError): compose.write_private(Path(folder)/'docker-compose.yml',rendered)
            if os.name!='nt': self.assertEqual(target.stat().st_mode&0o777,0o600)

    def test_private_gateway_validation_rejects_credentials_and_public_addresses(self):
        for address in ('http://user:secret@192.168.50.1','https://8.8.8.8','192.168.50.1:invalid'):
            with self.subTest(address=address),self.assertRaises(ValueError):
                compose.render(self.template,project='example',port=8080,address=address)

    @unittest.skipUnless(shutil.which('docker'),'Docker Compose is not installed')
    def test_docker_compose_preserves_escaped_password_until_container_creation(self):
        if subprocess.run(['docker','compose','version'],capture_output=True).returncode: self.skipTest('Compose unavailable')
        secret='test-only$UNDEFINED_DOLLAR:\"value'
        rendered=compose.render(self.template,project='compose-test',port=8088,password=secret)
        with tempfile.TemporaryDirectory(dir=compose.ROOT) as folder:
            target=Path(folder)/'compose.local.yml'; compose.write_private(target,rendered)
            parsed=json.loads(subprocess.check_output(['docker','compose','-f',str(target),'config','--format','json'],stderr=subprocess.DEVNULL))
        # config retains $$ for the later container-creation interpolation.
        # The workflow additionally checks the final value inside a container.
        self.assertEqual(parsed['services']['gateway-manager']['environment']['GATEWAY_PASSWORD'],secret.replace('$','$$'))
