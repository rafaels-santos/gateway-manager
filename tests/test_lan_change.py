import copy
import json
import sqlite3
import unittest
import urllib.parse

import network_management as nm
from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei import Gateway
from gateway_adapters.huawei.lan_change import PRIMARY, RESERVATION


class SimulatedLanGateway(Gateway):
    router = None
    def __init__(self,address='192.168.100.254'):
        super().__init__(address)
        self.credentials=('demo','not-a-real-password')
    def login(self,user,password):
        if self.base != self.router['base'] or self.router.get('unreachable'): raise GatewayError('Novo endereço indisponível.')
        self.credentials=(user,password)
    def dhcp_config(self): return copy.deepcopy(self.router['dhcp'])
    def reservations(self): return copy.deepcopy(self.router['reservations']),''
    def devices(self): return copy.deepcopy(self.router.get('devices',[]))
    def request(self,path,data=None,**kwargs):
        state=self.router
        if data is not None and path.startswith('/set.cgi?'):
            state['commands'].append((path,copy.deepcopy(data)))
            state['base']='http://'+data['x.IPInterfaceIPAddress']
            state['dhcp'].update(lan_ip=data['x.IPInterfaceIPAddress'],mask=data['x.IPInterfaceSubnetMask'])
            if not state.get('partial'):
                state['dhcp'].update(start=data['z.MinAddress'],end=data['z.MaxAddress'])
                targets=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
                for key,value in data.items():
                    if key.startswith('r') and key.endswith('.Yiaddr'):
                        domain=targets[key.split('.')[0]][0]
                        for row in state['reservations']:
                            if row['id']==domain: row['ip']=value
            if state.get('drop_after_write'): raise GatewayError('Conexão caiu durante a resposta.')
            return 'OK'
        if path.endswith('GetRandToken.asp'): return 'x'*32
        if path.endswith('/ethinfo.asp'):
            mac='02:00:00:00:00:09' if state.get('wrong_identity') and self.base==state['base'] and self.base!='http://192.168.100.254' else '02:00:00:00:00:01'
            return 'new DeviceLanMAC("InternetGatewayDevice.DeviceInfo",'+json.dumps(mac)+',"")'
        if path.endswith('/dhcp.asp'):
            row=[PRIMARY,'1',state['dhcp']['lan_ip'],state['dhcp']['mask'],'1']
            return 'new stLanHostInfo('+','.join(json.dumps(value) for value in row)+'); x.IPInterfaceIPAddress x.IPInterfaceSubnetMask'+state.get('extra_lan','')
        raise GatewayError('Leitura não prevista no simulador.')


class LanChangeTests(unittest.TestCase):
    def setUp(self):
        SimulatedLanGateway.router={'base':'http://192.168.100.254','commands':[],
            'dhcp':{'lan_ip':'192.168.100.254','mask':'255.255.255.0','start':'192.168.100.1','end':'192.168.100.200','enabled':True,'lease':'3600','dns_primary':'192.168.100.10','dns_secondary':''},
            'reservations':[{'id':RESERVATION+'.1','mac':'02:01:02:03:04:05','ip':'192.168.100.50','enabled':True}]}
        self.gateway=SimulatedLanGateway()
        self.body={'ip':'192.168.101.254','mask':'255.255.255.0','start':'192.168.101.1','end':'192.168.101.200','migrate_reservations':True,'confirm':'ALTERAR LAN','confirm_ip':'192.168.101.254'}
    def submission(self): return {**self.body,'expected':self.gateway.plan_lan_change(self.body)['expected']}
    def test_joint_change_rebases_reservations_and_verifies_identity(self):
        result=self.gateway.apply_lan_change(self.submission())
        self.assertTrue(result['verified']);self.assertEqual(result['replacement'].base,'http://192.168.101.254')
        self.assertEqual(self.gateway.router['reservations'][0]['ip'],'192.168.101.50')
        self.assertEqual(len(self.gateway.router['commands']),1)
        params=self.gateway.router['commands'][0][1]
        self.assertEqual(set(params),{'x.IPInterfaceIPAddress','x.IPInterfaceSubnetMask','z.MinAddress','z.MaxAddress','r0.Yiaddr','x.X_HW_Token'})
        self.assertEqual(self.gateway.base,'http://192.168.100.254')
    def test_timeout_after_committed_write_is_verified_without_resending(self):
        self.gateway.router['drop_after_write']=True
        result=self.gateway.apply_lan_change(self.submission())
        self.assertTrue(result['verified']);self.assertEqual(len(self.gateway.router['commands']),1)
        with self.assertRaises(GatewayError):self.gateway.apply_lan_change(self.body)
        self.gateway.verify_lan_change();self.assertEqual(len(self.gateway.router['commands']),1)
    def test_unreachable_new_ip_is_pending_and_can_be_verified_later(self):
        self.gateway.router['unreachable']=True
        result=self.gateway.apply_lan_change(self.submission())
        self.assertFalse(result['verified']);self.assertEqual(result['state'],'pending_verification')
        self.gateway.router['unreachable']=False
        self.assertTrue(self.gateway.verify_lan_change()['verified'])
        self.assertEqual(len(self.gateway.router['commands']),1)
    def test_wrong_equipment_or_partial_dhcp_change_is_never_success(self):
        for flag in ('wrong_identity','partial'):
            self.setUp();self.gateway.router[flag]=True
            result=self.gateway.apply_lan_change(self.submission())
            self.assertFalse(result['verified']);self.assertNotIn('replacement',result)
            self.assertEqual(self.gateway.base,'http://192.168.100.254')
    def test_stale_preview_and_missing_typed_confirmation_prevent_commands(self):
        body=self.submission();self.gateway.router['dhcp']['lease']='7200'
        with self.assertRaisesRegex(GatewayError,'mudou'):self.gateway.apply_lan_change(body)
        body=self.submission();body['confirm_ip']='wrong'
        with self.assertRaises(GatewayError):self.gateway.apply_lan_change(body)
        self.assertEqual(self.gateway.router['commands'],[])
    def test_secondary_network_overlap_blocks_change(self):
        self.gateway.router['extra_lan']='new stLanHostInfo("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.2","1","192.168.101.1","255.255.255.0","1")'
        plan=self.gateway.plan_lan_change(self.body)
        self.assertTrue(any('secundário' in value for value in plan['blockers']))
        self.assertFalse(plan['apply_available'])
    def test_journal_failure_prevents_network_change(self):
        def unavailable(plan):raise GatewayError('Não foi possível registrar a recuperação.')
        with self.assertRaises(GatewayError):self.gateway.apply_lan_change(self.submission(),journal=unavailable)
        self.assertEqual(self.gateway.router['commands'],[]);self.assertIsNone(self.gateway.pending_lan_change)
    def test_pending_record_is_durable_and_contains_no_credentials(self):
        with sqlite3.connect(':memory:') as db:
            nm.schema(db)
            self.gateway.router['unreachable']=True
            self.gateway.apply_lan_change(self.submission(),journal=lambda plan:nm.journal_lan_change(db,self.gateway.base,plan))
            restored=nm.restore_lan_journal(db,'http://192.168.101.254')
            self.assertEqual(restored['storage_source'],'http://192.168.100.254')
            self.assertNotIn('not-a-real-password',json.dumps(restored))
    def test_local_data_migration_is_scoped_and_conflicts_do_not_overwrite(self):
        with sqlite3.connect(':memory:') as db:
            nm.schema(db);db.execute('CREATE TABLE labels(gateway TEXT,mac TEXT,name TEXT,PRIMARY KEY(gateway,mac))')
            old,new='http://192.168.100.254','http://192.168.101.254'
            db.execute('INSERT INTO labels VALUES (?,?,?)',(old,'02:01:02:03:04:05','Printer'))
            nm.journal_lan_change(db,old,self.gateway.plan_lan_change(self.body))
            nm.move_gateway_state(db,old,new)
            self.assertEqual(db.execute('SELECT gateway,name FROM labels').fetchone(),(new,'Printer'))
            self.assertIsNone(nm.restore_lan_journal(db,new))
            db.execute('INSERT INTO labels VALUES (?,?,?)',(old,'02:01:02:03:04:06','Other'))
            with self.assertRaises(GatewayError):nm.move_gateway_state(db,old,new)
            self.assertEqual(db.execute('SELECT count(*) FROM labels').fetchone()[0],2)


if __name__=='__main__':unittest.main()
