import copy
import threading
import unittest
import urllib.parse
from types import SimpleNamespace

from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei.radio_options import options_for
from gateway_adapters.huawei.radio_control import apply_radio_change, enrich_radios, steering_records, ACTION, COMMON_SOURCE, SHARED_SOURCE

IDENTITY = {'hardware':'343D.D','firmware':'V5R024C10S106'}
ROOT = 'InternetGatewayDevice.LANDevice.1.WLANConfiguration.'


class RadioGateway:
    def __init__(self):
        self.lock=threading.RLock(); self.writes=[]; self.partial=self.timeout=self.other_changed=False
        self.rows=[]
        for number in ('1','5'):
            row={'id':ROOT+number,'band':'2,4 GHz' if number=='1' else '5 GHz','country':'BR','standard':'11ax','power':'100',
                 'channel':'6' if number=='1' else '36','auto_channel':number=='5','auto_scope':'0','band_steering':'1',
                 'width_code':'0' if number=='1' else '4','expected':'snapshot','channel_selection':'6' if number=='1' else '-1',
                 'channel_write_available':True}
            row['channel_options']=options_for(IDENTITY,True,row);self.rows.append(row)
    def radio_config(self): return copy.deepcopy(self.rows)
    def wifi_config(self): return [{'id':ROOT+'1','ssid':'Office','enabled':True}]
    def config_token(self): return 'fixture-token'
    def request(self,path,data,**kwargs):
        self.writes.append((path,data.copy()))
        if not self.partial:
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            row=next(row for row in self.rows if row['id']==query['y'][0])
            row.update(channel=data['y.Channel'],auto_channel=data['y.AutoChannelEnable']=='1',width_code=data['y.X_HW_HT20'])
            if 'y.X_HW_AutoChannelScope' in data: row['auto_scope']=data['y.X_HW_AutoChannelScope']
            if self.other_changed:self.rows[1]['power']='80'
        if self.timeout:raise GatewayError('Response dropped')
        return 'OK'
    def body(self,number='1',channel='11',width='1'):
        return {'id':ROOT+number,'channel':channel,'width_code':width,'expected':'snapshot','confirm':'WIFI'}


class RadioControlTests(unittest.TestCase):
    def test_different_fixed_channel_has_only_scoped_radio_properties(self):
        gateway=RadioGateway();updated=apply_radio_change(gateway,gateway.body())
        self.assertEqual(updated['channel'],'11')
        self.assertEqual(set(gateway.writes[0][1]),{'y.Channel','y.AutoChannelEnable','y.X_HW_HT20','x.X_HW_Token'})
        self.assertNotIn(ACTION,gateway.writes[0][0])

    def test_same_channel_width_change_uses_native_ordered_bracket(self):
        gateway=RadioGateway();apply_radio_change(gateway,gateway.body(channel='6'))
        query=urllib.parse.parse_qsl(urllib.parse.urlsplit(gateway.writes[0][0]).query)
        self.assertEqual([name for name,_ in query],['c1','y','c2','RequestFile'])
        self.assertEqual(gateway.writes[0][1]['c1.ActionType'],'0')
        self.assertEqual(gateway.writes[0][1]['c2.ActionType'],'1')
        self.assertEqual(gateway.writes[0][1]['c2.SSIDList'],'1')

    def test_non_dfs_twenty_mhz_scope_includes_165_but_excludes_dfs(self):
        gateway=RadioGateway();apply_radio_change(gateway,gateway.body('5','0','1'))
        self.assertEqual(gateway.writes[0][1]['y.X_HW_AutoChannelScope'],'36,40,44,48,149,153,157,161,165')
        self.assertEqual(gateway.writes[0][1]['c2.SSIDList'],'5')

    def test_timeout_after_success_is_confirmed_without_resending(self):
        gateway=RadioGateway();gateway.timeout=True
        self.assertEqual(apply_radio_change(gateway,gateway.body())['channel'],'11')
        self.assertEqual(len(gateway.writes),1)

    def test_partial_write_or_other_band_change_is_not_success(self):
        for attribute in ('partial','other_changed'):
            gateway=RadioGateway();setattr(gateway,attribute,True)
            with self.assertRaises(GatewayError):apply_radio_change(gateway,gateway.body())
            self.assertEqual(len(gateway.writes),1)

    def test_snapshot_invalid_combination_and_unknown_contract_prevent_write(self):
        for changes in ({'expected':'stale'},{'channel':'165','width_code':'4'},{'confirm':''}):
            gateway=RadioGateway()
            with self.assertRaises(GatewayError):apply_radio_change(gateway,{**gateway.body(),**changes})
            self.assertEqual(gateway.writes,[])
        gateway=RadioGateway();gateway.rows[0]['channel_write_available']=False
        with self.assertRaises(GatewayError):apply_radio_change(gateway,gateway.body())
        self.assertEqual(gateway.writes,[])

    def test_exact_native_contract_and_typed_scope_enable_supported_profile(self):
        common='function CheckConfigChannel(selChannel, curChannel) { if ((selChannel == 0) || (selChannel == -1)) { return false; } return (selChannel != curChannel); }'
        shared='function stWlanWifi(domain,scope){this.X_HW_AutoChannelScope=scope;} new stWlanWifi("'+ROOT+'5","0"); new StXHWGlobalConfig("InternetGatewayDevice.LANDevice.1.WiFi.X_HW_GlobalConfig","1");'
        page="var WdsFlag='0';var fobidChannel=0;var DoubleFreqFlag=1;var dfsChSwitch=1; y.Channel y.AutoChannelEnable y.X_HW_HT20 y.X_HW_AutoChannelScope "+ACTION+' c1.ActionType c2.ActionType c2.SSIDList'
        gateway=SimpleNamespace(request=lambda path,**kwargs: shared if path==SHARED_SOURCE else common)
        radios=RadioGateway().radio_config()
        result=enrich_radios(gateway,page,radios)
        self.assertTrue(all(row['channel_write_available'] for row in result))
        self.assertEqual(result[1]['channel_selection'],'-1')
        result=enrich_radios(gateway,page.replace('var WdsFlag=\'0\'','var WdsFlag=\'1\''),RadioGateway().radio_config())
        self.assertFalse(any(row['channel_write_available'] for row in result))

    def test_constructor_and_global_instances_can_live_in_api_with_dfs_initializer_zero(self):
        common='function CheckConfigChannel(selChannel, curChannel) { if ((selChannel == 0) || (selChannel == -1)) { return false; } return (selChannel != curChannel); } var dfsChSwitch=0;var fobidChannel=0;'
        shared='var DoubleFreqFlag=1;function StXHWGlobalConfig(domain,BandSteeringPolicy){this.domain=domain;this.BandSteeringPolicy=BandSteeringPolicy;}'
        page='''var WdsFlag=0;
function stWlanWifi(domain,scope){this.X_HW_AutoChannelScope=scope;}
new stWlanWifi("'''+ROOT+'''5","0");new StXHWGlobalConfig("InternetGatewayDevice.LANDevice.1.WiFi.X_HW_GlobalConfig","1");
y.Channel y.AutoChannelEnable y.X_HW_HT20 y.X_HW_AutoChannelScope c1.ActionType c2.ActionType c2.SSIDList '''+ACTION
        gateway=SimpleNamespace(request=lambda path,**kwargs:shared if path==SHARED_SOURCE else common)
        result=enrich_radios(gateway,page,RadioGateway().radio_config())
        self.assertTrue(all(row['channel_write_available'] for row in result))
        self.assertEqual(result[1]['auto_scope'],'0')
        self.assertEqual(result[1]['band_steering'],'1')

    def test_global_policy_is_an_opaque_local_value_not_a_guessed_boolean(self):
        source='new StXHWGlobalConfig("InternetGatewayDevice.X_HW_WIFIInfo.X_HW_GlobalConfig",2);'
        self.assertEqual(steering_records(source),[{'domain':'InternetGatewayDevice.X_HW_WIFIInfo.X_HW_GlobalConfig','value':'2'}])
        self.assertEqual(steering_records('new StXHWGlobalConfig("InternetGatewayDevice.X_HW_WIFIInfo","1");'),[{'domain':'InternetGatewayDevice.X_HW_WIFIInfo','value':'1'}])
        for domain, value in [('InternetGatewayDevice.WANDevice.1.Config','1'),('InternetGatewayDevice.X_HW_WIFIInfo.Config','"secret"'),('InternetGatewayDevice.X_HW_WIFIInfo.Config','-1')]:
            self.assertEqual(steering_records('new StXHWGlobalConfig("'+domain+'",'+value+');'),[])
