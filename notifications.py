"""Persistent notification destinations, migration and independent delivery queues."""
import json
import re
import secrets
from datetime import datetime, timezone


PROVIDERS = {'discord':'Discord', 'telegram':'Telegram', 'whatsapp':'WhatsApp Cloud API',
             'slack':'Slack', 'generic':'Webhook genérico'}
FIELDS = {'discord':['url'], 'generic':['url'], 'slack':['url'],
          'telegram':['token','chat_id'],
          'whatsapp':['token','phone_id','recipient','version','template','language']}
SECRETS = {'url','token'}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS notification_hooks (id TEXT PRIMARY KEY, gateway TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL, seen TEXT NOT NULL, baseline INTEGER NOT NULL, last_test TEXT NOT NULL DEFAULT "", last_sent TEXT NOT NULL DEFAULT "", error TEXT NOT NULL DEFAULT "")')
    db.execute('CREATE TABLE IF NOT EXISTS notification_migrations (gateway TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS notification_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, hook TEXT NOT NULL, payload TEXT NOT NULL)')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Service:
    def __init__(self, store, events, validate_url, send):
        self.store, self.events, self.validate_url, self.send = store, events, validate_url, send

    def defaults(self):
        return {key:{'enabled':value[2], 'template':value[1]} for key,value in self.events.items()}

    def migrate(self, gateway):
        with self.store() as db:
            if db.execute('SELECT 1 FROM notification_migrations WHERE gateway=?',(gateway,)).fetchone(): return
            old=db.execute('SELECT url,enabled,baseline FROM webhook_config WHERE gateway=?',(gateway,)).fetchone()
            if old:
                options=db.execute('SELECT options FROM webhook_options WHERE gateway=?',(gateway,)).fetchone()
                options=json.loads(options[0]) if options else {}
                data={'name':'Hook existente', 'provider':options.get('provider','discord'), 'enabled':bool(old[1]),
                      'config':{'url':old[0]}, 'events':dict(self.defaults(),**options.get('events',{}))}
                seen=[r[0] for r in db.execute('SELECT mac FROM seen_devices WHERE gateway=?',(gateway,))]
                state={mac:json.loads(value) for mac,value in db.execute('SELECT mac,state FROM webhook_state WHERE gateway=?',(gateway,))}
                db.execute('INSERT INTO notification_hooks (id,gateway,data,state,seen,baseline) VALUES (?,?,?,?,?,?)',
                           (secrets.token_hex(12),gateway,json.dumps(data),json.dumps(state),json.dumps(seen),old[2]))
            db.execute('INSERT INTO notification_migrations VALUES (?)',(gateway,))

    def validate(self, data):
        if not isinstance(data,dict): raise ValueError('Configuração inválida.')
        provider=data.get('provider'); config=data.get('config')
        if provider not in PROVIDERS or not isinstance(config,dict): raise ValueError('Serviço inválido.')
        if not isinstance(data.get('enabled'),bool): raise ValueError('Ativação inválida.')
        if not isinstance(data.get('name'),str) or not 1<=len(data['name'].strip())<=80: raise ValueError('Informe um nome de até 80 caracteres.')
        for key in FIELDS[provider]:
            value=config.get(key)
            if not isinstance(value,str) or not value.strip() or len(value)>2048 or any(ord(c)<32 for c in value): raise ValueError('Preencha os campos de conexão do serviço.')
        if provider in ('discord','generic','slack'): self.validate_url(provider,config['url'])
        if provider=='telegram':
            if not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,150}',config['token']): raise ValueError('Token de bot Telegram inválido.')
            if not re.fullmatch(r'-?\d{1,22}|@[A-Za-z0-9_]{5,64}',config['chat_id']): raise ValueError('Chat ID do Telegram inválido.')
        if provider=='whatsapp':
            for key in ('phone_id','recipient'):
                if not re.fullmatch(r'\d{5,25}',config[key]): raise ValueError('IDs e destinatário WhatsApp devem conter apenas números, com DDI no destinatário.')
            if not re.fullmatch(r'v\d{1,3}\.\d',config['version']): raise ValueError('Informe a versão Graph API usada na sua conta, como vXX.0.')
            if not re.fullmatch(r'[a-z0-9_]{1,512}',config['template']) or not re.fullmatch(r'[a-z]{2,3}(?:_[A-Z]{2})?',config['language']): raise ValueError('Template ou idioma do WhatsApp inválido.')
        events=data.get('events')
        if not isinstance(events,dict) or set(events)!=set(self.events): raise ValueError('Eventos inválidos.')
        for value in events.values():
            if not isinstance(value,dict) or not isinstance(value.get('enabled'),bool) or not isinstance(value.get('template'),str) or not 1<=len(value['template'])<=1500: raise ValueError('Cada mensagem deve ter entre 1 e 1.500 caracteres.')

    def rows(self, gateway):
        self.migrate(gateway)
        with self.store() as db:
            return db.execute('SELECT id,data,state,seen,baseline,last_test,last_sent,error FROM notification_hooks WHERE gateway=? ORDER BY rowid',(gateway,)).fetchall()

    def list(self, gateway):
        result=[]
        for key,raw,_,__,___,test,sent,error in self.rows(gateway):
            data=json.loads(raw)
            try: self.validate(data); valid=True; validation='Configuração válida'
            except ValueError as e: valid=False;validation=str(e)
            result.append(dict(data,id=key,config={k:v for k,v in data['config'].items() if k not in SECRETS},
                               credentials_saved=any(data['config'].get(k) for k in SECRETS),valid=valid,validation=validation,last_test=test,last_sent=sent,error=error))
        return result

    def save(self, gateway, body):
        self.migrate(gateway)
        key=body.get('id') or secrets.token_hex(12)
        with self.store() as db:
            old=db.execute('SELECT data FROM notification_hooks WHERE gateway=? AND id=?',(gateway,key)).fetchone()
            if body.get('id') and not old: raise ValueError('Hook não encontrado neste gateway.')
            if not old and db.execute('SELECT count(*) FROM notification_hooks WHERE gateway=?',(gateway,)).fetchone()[0]>=20: raise ValueError('Limite de 20 hooks por gateway.')
            previous=json.loads(old[0]) if old else {}
            provider=body.get('provider')
            incoming=body.get('config',{})
            if provider not in FIELDS or not isinstance(incoming,dict): raise ValueError('Serviço inválido.')
            saved=previous.get('config',{}) if previous.get('provider')==provider else {}
            config={k:str(incoming.get(k,'')).strip() or (saved.get(k,'') if k in SECRETS else '') for k in FIELDS[provider]}
            data={'name':str(body.get('name','')).strip(),'provider':provider,'enabled':body.get('enabled'),'config':config,'events':body.get('events')}
            self.validate(data)
            reset=not old or previous.get('enabled')!=data['enabled']
            if old:
                # Pending events belong to the previous configuration; never redirect them to a new destination.
                db.execute('DELETE FROM notification_queue WHERE hook=?',(key,))
                db.execute('UPDATE notification_hooks SET data=?,last_test="",error="" WHERE id=?',(json.dumps(data),key))
                if reset: db.execute('UPDATE notification_hooks SET state="{}",seen="[]",baseline=0 WHERE id=?',(key,))
            else:
                db.execute('INSERT INTO notification_hooks (id,gateway,data,state,seen,baseline) VALUES (?,?,?,"{}","[]",0)',(key,gateway,json.dumps(data)))
        return key

    def test(self, gateway, key):
        rows=[r for r in self.rows(gateway) if r[0]==key]
        if not rows: raise ValueError('Hook não encontrado neste gateway.')
        data=json.loads(rows[0][1]);self.validate(data)
        try: self.send(data,'test','Teste de notificação do Gateway Manager.',{'mac':'','ip':''},'', '')
        except ValueError as e:
            with self.store() as db: db.execute('UPDATE notification_hooks SET last_test="",error=? WHERE id=?',(str(e),key))
            raise
        with self.store() as db: db.execute('UPDATE notification_hooks SET last_test=?,error="" WHERE id=?',(now(),key))

    def observe(self, gateway, devices, blocked, names, origin):
        failures=[]
        for key,raw,state,seen,baseline,*_ in self.rows(gateway):
            data=json.loads(raw)
            if not data['enabled']: continue
            try: self.validate(data)
            except ValueError:
                failures.append(key);continue
            previous=json.loads(state); known=set(json.loads(seen)); current={d['mac']:dict(d) for d in devices}
            for mac,old in previous.items():
                if mac not in current: current[mac]=dict(old,status='offline')
            pending=[]
            for mac,device in current.items():
                old=previous.get(mac); events=[]
                if baseline:
                    if device['status']=='online' and mac not in known: events.append('connected')
                    if old and old.get('status')=='online' and device['status']!='online':
                        events.append('disconnected')
                        if mac in blocked: events.append('blocked_disconnected')
                    if old and device['status']=='online' and old.get('ip') and device.get('ip') and old['ip']!=device['ip']:
                        events.append('ip_changed')
                        if mac in blocked: events.append('blocked_ip_changed')
                for event in events:
                    setting=data['events'][event]
                    if setting['enabled']: pending.append([event,setting['template'],device,names.get(mac,''),origin,(old or {}).get('ip',''),blocked.get(mac,{}).get('block_active',False)])
                known.add(mac)
            with self.store() as db:
                # Snapshot and queue are committed together so retries cannot lose the transition.
                db.executemany('INSERT INTO notification_queue (hook,payload) VALUES (?,?)',((key,json.dumps(event)) for event in pending))
                db.execute('UPDATE notification_hooks SET state=?,seen=?,baseline=1 WHERE id=?',(json.dumps(current),json.dumps(sorted(known)),key))
                queue=db.execute('SELECT id,payload FROM notification_queue WHERE hook=? ORDER BY id LIMIT 3',(key,)).fetchall()
            for queue_id,payload in queue:
                try: self.send(data,*json.loads(payload))
                except ValueError as e:
                    failures.append(key)
                    with self.store() as db: db.execute('UPDATE notification_hooks SET error=? WHERE id=?',(str(e),key))
                    break
                with self.store() as db:
                    db.execute('DELETE FROM notification_queue WHERE id=?',(queue_id,))
                    db.execute('UPDATE notification_hooks SET last_sent=?,error="" WHERE id=?',(now(),key))
        return '%s hook(s) com falha; demais destinos continuam ativos.'%len(set(failures)) if failures else 'Monitorando hooks a cada 30 segundos.'
