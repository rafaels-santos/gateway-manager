import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from services import notifications


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=app.ROOT)
        self.patch=patch.object(app,'DATA_DIR',Path(self.tmp.name));self.patch.start()
        self.service=app.hook_service();self.gateway='http://192.168.1.1'

    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()

    def body(self, name='Casa',provider='generic'):
        return {'name':name,'provider':provider,'enabled':True,'config':{'url':'https://example.com/secret'},'events':self.service.defaults()}

    def test_legacy_migration_is_once_preserves_options_and_hides_url(self):
        with app.labels() as db:
            db.execute('INSERT INTO webhook_config VALUES (?,?,?,?)',(self.gateway,'https://example.com/secret',1,1))
            events=self.service.defaults();events['disconnected']['enabled']=True
            db.execute('INSERT INTO webhook_options VALUES (?,?)',(self.gateway,json.dumps({'provider':'generic','events':events})))
            db.execute('INSERT INTO seen_devices VALUES (?,?)',(self.gateway,'aa:bb:cc:dd:ee:ff'))
        hooks=self.service.list(self.gateway)
        self.assertEqual(len(hooks),1);self.assertTrue(hooks[0]['events']['disconnected']['enabled'])
        self.assertTrue(hooks[0]['valid']);self.assertFalse(hooks[0]['last_test'])
        self.assertNotIn('secret',json.dumps(hooks));self.assertTrue(hooks[0]['credentials_saved'])
        self.assertEqual(self.service.list(self.gateway)[0]['id'],hooks[0]['id'])
        self.assertIn('aa:bb:cc:dd:ee:ff',json.loads(self.service.rows(self.gateway)[0][3]))

    def test_multiple_same_service_edit_preserves_secret_and_gateway_scope(self):
        first=self.service.save(self.gateway,self.body('Primeiro'));second=self.service.save(self.gateway,self.body('Segundo'))
        self.assertNotEqual(first,second)
        edit=self.body('Renomeado');edit.update(id=first,config={'url':''})
        self.service.save(self.gateway,edit)
        self.assertEqual(len(self.service.list(self.gateway)),2)
        self.assertEqual(json.loads(self.service.rows(self.gateway)[0][1])['config']['url'],'https://example.com/secret')
        with self.assertRaises(ValueError):self.service.save('http://192.168.2.1',edit)
        with self.assertRaises(ValueError):self.service.test('http://192.168.2.1',first)

    def test_failure_does_not_block_other_hook_and_queue_retries_once(self):
        first=self.service.save(self.gateway,self.body('Falha'));second=self.service.save(self.gateway,self.body('Funciona'))
        sent=[]
        def send(hook,*args):
            if hook['name']=='Falha':raise ValueError('Serviço indisponível')
            sent.append(hook['name'])
        self.service.send=send
        devices=[{'mac':'aa','status':'online','ip':'1'}]
        self.service.observe(self.gateway,devices,{}, {},'')
        devices.append({'mac':'bb','status':'online','ip':'2'})
        self.assertIn('falha',self.service.observe(self.gateway,devices,{}, {},''))
        self.assertEqual(sent,['Funciona'])
        self.service.send=lambda hook,*args:sent.append(hook['name'])
        self.service.observe(self.gateway,devices,{}, {},'')
        self.service.observe(self.gateway,devices,{}, {},'')
        self.assertEqual(sent,['Funciona','Falha'])

    def test_test_status_resets_on_edit_and_reports_failure_without_secret(self):
        key=self.service.save(self.gateway,self.body())
        self.service.send=lambda *args:None;self.service.test(self.gateway,key)
        self.assertTrue(self.service.list(self.gateway)[0]['last_test'])
        edit=self.body();edit['id']=key;self.service.save(self.gateway,edit)
        self.assertFalse(self.service.list(self.gateway)[0]['last_test'])
        self.service.send=lambda *args:(_ for _ in ()).throw(ValueError('Falha HTTP 401'))
        with self.assertRaises(ValueError):self.service.test(self.gateway,key)
        self.assertEqual(self.service.list(self.gateway)[0]['error'],'Falha HTTP 401')

    def test_service_specific_validation_and_telegram_api_failure(self):
        body=self.body(provider='telegram');body['config']={'token':'123456:'+('a'*30),'chat_id':'-12345678'}
        self.service.validate(body)
        with patch.object(app,'post_hook_json',return_value={'ok':False}):
            with self.assertRaises(ValueError):app.deliver_hook(body,'test','hello',{'mac':''},'','')
        body['config']['chat_id']='wrong chat'
        with self.assertRaises(ValueError):self.service.validate(body)
        with self.assertRaises(ValueError):app.validate_hook_url('slack','https://hooks.slack.com.evil.example/services/A/B/C')

    def test_whatsapp_template_and_slack_payloads(self):
        hook={'provider':'whatsapp','config':{'token':'secret','phone_id':'12345678','recipient':'5511999999999','version':'v99.0','template':'alerta_rede','language':'pt_BR'}}
        with patch.object(app,'post_hook_json',return_value={'messages':[{'id':'accepted'}]}) as send:
            app.deliver_hook(hook,'test','Alerta\n{name}',{'mac':''},'Casa','')
            args=send.call_args.args
            self.assertEqual(args[0],'graph.facebook.com')
            self.assertEqual(args[2]['template']['components'][0]['parameters'][0]['text'],'Alerta Casa')
            self.assertEqual(args[3],{'Authorization':'Bearer secret'})
        with patch.object(app,'post_hook_json',return_value='ok') as send:
            app.deliver_hook({'provider':'slack','config':{'url':'https://hooks.slack.com/services/A/B/C'}},'test','hello',{'mac':''},'','')
            self.assertEqual(send.call_args.args[2],{'text':'hello','mrkdwn':False})


if __name__=='__main__':unittest.main()
