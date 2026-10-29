const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const model=require('../static/navigation-model.js');

test('all existing pages remain reachable exactly once in the simplified navigation',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  const extension=fs.readFileSync(path.join(__dirname,'../static/network.js'),'utf8')+fs.readFileSync(path.join(__dirname,'../static/network-actions.js'),'utf8');
  const existing=[...Array.from(html.matchAll(/<section id="page-([\w-]+)"/g),m=>m[1]),...Array.from(extension.matchAll(/addNetworkPage\('([^']+)'/g),m=>m[1])];
  const destinations=model.groups.flatMap(group=>group.tabs.flatMap(tab=>tab.pages||[tab.page]));
  assert.deepEqual([...destinations].sort(),[...existing].sort());
  assert.equal(new Set(destinations).size,destinations.length);
  assert.equal(model.groups.length,6);
  assert.equal(model.locate('wan'),null);
});

test('DHCP and reservations share one workspace, while radios remain separate from SSIDs',()=>{
  assert.equal(model.locate('dhcp').tab,model.locate('reservations').tab);
  assert.equal(model.locate('dns').tab,model.locate('static-dns').tab);
  assert.equal(model.locate('wifi').tab,model.locate('wifi-security').tab);
  assert.equal(model.locate('wifi').tab,model.locate('wifi-lifecycle').tab);
  assert.notEqual(model.locate('wifi').tab,model.locate('wifi-radios').tab);
  assert.equal(model.locate('notifications').group.id,'notifications');
  assert.equal(model.groups.at(-1).tabs.at(-1).page,'reboot');
});

test('Wi-Fi selection uses object identity, supports shared security and recovers after deletion',()=>{
  const rows=[{id:'ssid.1',ssid:'Casa'},{id:'ssid.5',ssid:'Casa'},{id:'ssid.2',ssid:'Convidados'}];
  assert.equal(model.wifiSelection(rows,'ssid.5'),'ssid.5');
  assert.equal(model.wifiSelection(rows.filter(row=>row.id!=='ssid.5'),'ssid.5'),'ssid.1');
  assert.equal(model.wifiSelection([],'ssid.5'),'');
  assert.equal(model.matchesNetwork({id:'ssid.1',members:['ssid.1','ssid.5']},'ssid.5'),true);
  assert.equal(model.matchesNetwork({id:'ssid.1'},'ssid.5'),false);
  assert.equal(model.matchesNetwork({id:'ssid.1'},''),false);
});

test('networks are ordered by primary bands, additional networks and guests, without mutating input',()=>{
  const rows=[
    {id:'guest',ssid:'A',guest:true,band:'2G'},
    {id:'extra-1',ssid:'Z',band:'2G'},
    {id:'main-5',ssid:'Same name',primary:true,band:'5G'},
    {id:'main-2',ssid:'Same name',primary:true,band:'2G'},
    {id:'extra-2',ssid:'B',band:'5G'}
  ];
  assert.deepEqual(model.sortWifiNetworks(rows).map(row=>row.id),['main-2','main-5','extra-1','extra-2','guest']);
  assert.equal(rows[0].id,'guest');
});

function element(dataset={}){
  const values=new Set(),attrs={};
  return {dataset,hidden:false,textContent:'',classList:{toggle(key,on){on?values.add(key):values.delete(key);},contains(key){return values.has(key);}},setAttribute(k,v){attrs[k]=v;},removeAttribute(k){delete attrs[k];},attrs};
}
function fixture(){
  const pages=Object.fromEntries(['devices','wifi','dhcp','reservations','dns','logs','notifications','maintenance','reboot','inventory','history','planning','diagnostic'].map(key=>['#page-'+key,element()]));
  for(const [key,page] of Object.entries(pages))page.id=key.slice(1);
  const buttons=[element({page:'devices'}),element({page:'devices',networkView:'blocked'}),element({page:'wifi'})];
  const panels=['online','offline','blocked'].map(view=>element({deviceView:view}));
  const controls={...pages,'#breadcrumb':element(),...Object.fromEntries(['online','offline','blocked'].map(key=>['#show-'+key,element()]))};
  const context=vm.createContext({window:{},deviceView:'online',$:selector=>controls[selector],document:{querySelectorAll(selector){if(selector==='.page')return Object.values(pages);if(selector==='.nav-item')return buttons;if(selector==='[data-device-view]')return panels;throw Error(selector);}},refreshDevices(){},refreshReservations(){return Promise.resolve();},refreshWebhook(){return Promise.resolve();},loadNetworkConfig(){},loadWifi(){},loadLogs(){},loadMaintenance(){}});
  const navigation=source.slice(source.indexOf('const pageLabels='),source.indexOf("document.addEventListener('click'"));
  const select=source.slice(source.indexOf('function selectDeviceView(view)')).split('\n')[0];
  vm.runInContext(navigation+'\n'+select,context);
  return {context,buttons,panels,controls};
}
test('security shortcut opens existing blocked clients with one active menu item',()=>{
  const {context,buttons,panels,controls}=fixture();
  vm.runInContext("setPage('devices','blocked')",context);
  assert.equal(buttons[0].attrs['aria-current'],undefined);
  assert.equal(buttons[1].attrs['aria-current'],'page');
  assert.equal(controls['#breadcrumb'].textContent,'Bloqueios Wi-Fi');
  assert.deepEqual(panels.map(p=>p.hidden),[true,true,false]);
});
test('offline tab belongs to devices and returning to devices restores online view',()=>{
  const {context,buttons,panels}=fixture();
  vm.runInContext("setPage('devices','blocked');selectDeviceView('offline')",context);
  assert.equal(buttons[0].attrs['aria-current'],'page');
  assert.equal(buttons[1].attrs['aria-current'],undefined);
  vm.runInContext("setPage('devices')",context);
  assert.deepEqual(panels.map(p=>p.hidden),[false,true,true]);
});
test('unsupported external page does not replace the active internal page',()=>{
  const {context,buttons,controls}=fixture();
  vm.runInContext("setPage('wifi');setPage('wan')",context);
  assert.equal(buttons[2].attrs['aria-current'],'page');
  assert.equal(controls['#page-wifi'].hidden,false);
  assert.equal(controls['#breadcrumb'].textContent,'Redes e SSIDs');
});
test('maintenance import/export page is reachable and has its own breadcrumb',()=>{
  const {context,controls}=fixture();
  vm.runInContext("setPage('maintenance')",context);
  assert.equal(controls['#page-maintenance'].hidden,false);
  assert.equal(controls['#breadcrumb'].textContent,'Importar / exportar');
});

test('internal network extension pages use their loader and preserve page selection',()=>{
  const {context,controls}=fixture();const loaded=[];
  context.window={networkPageLoaders:Object.fromEntries(['inventory','history','planning','diagnostic'].map(page=>[page,()=>loaded.push(page)]))};
  vm.runInContext("Object.assign(pageLabels,{inventory:'Inventário e topologia',history:'Histórico da rede',planning:'Endereço LAN',diagnostic:'Diagnóstico interno'})",context);
  for(const page of ['inventory','history','planning','diagnostic']){
    vm.runInContext(`setPage('${page}')`,context);
    assert.equal(controls['#page-'+page].hidden,false);
    assert.equal(Object.values(controls).filter(control=>control.id?.startsWith('page-')&&!control.hidden).length,1);
  }
  assert.deepEqual(loaded,['inventory','history','planning','diagnostic']);
});


test('top gateway link opens the authenticated address, including restored sessions',async()=>{
  const top={removeAttribute(name){delete this[name];}},controls={'#device-model':top,'#address':{value:'192.168.50.99'},'#login-screen':{},'#dashboard':{}};
  const context=vm.createContext({URL,$:selector=>controls[selector],window:{},document:{hidden:false},refreshDevices:async()=>{},clearInterval(){},setInterval(){return 1;},deviceTimer:null});
  const urls=source.slice(source.indexOf('function validProbeAddress'),source.indexOf('function setGatewayVendor'));
  const dashboard=source.slice(source.indexOf('async function showDashboard'),source.indexOf("$('#connect').addEventListener"));
  vm.runInContext(urls+'\n'+dashboard,context);
  await vm.runInContext("showDashboard({address:'https://192.168.50.1:8443',model_label:'Huawei',firmware:'test'})",context);
  assert.equal(top.href,'https://192.168.50.1:8443/');
  assert.equal(top.textContent,'Huawei · test');
  await vm.runInContext("showDashboard({address:'javascript:alert(1)'})",context);
  assert.equal(top.href,undefined);
  const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(html,/<a class="device-model" id="device-model" target="_blank" rel="noopener noreferrer"/);
});
