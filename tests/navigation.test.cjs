const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');

function element(dataset={}){
  const values=new Set(),attrs={};
  return {dataset,hidden:false,textContent:'',classList:{toggle(key,on){on?values.add(key):values.delete(key);},contains(key){return values.has(key);}},setAttribute(k,v){attrs[k]=v;},removeAttribute(k){delete attrs[k];},attrs};
}
function fixture(){
  const pages=Object.fromEntries(['devices','wifi','dhcp','reservations','dns','logs','notifications','reboot'].map(key=>['#page-'+key,element()]));
  for(const [key,page] of Object.entries(pages))page.id=key.slice(1);
  const buttons=[element({page:'devices'}),element({page:'devices',networkView:'blocked'}),element({page:'wifi'})];
  const panels=['online','offline','blocked'].map(view=>element({deviceView:view}));
  const controls={...pages,'#breadcrumb':element(),...Object.fromEntries(['online','offline','blocked'].map(key=>['#show-'+key,element()]))};
  const context=vm.createContext({deviceView:'online',$:selector=>controls[selector],document:{querySelectorAll(selector){if(selector==='.page')return Object.values(pages);if(selector==='.nav-item')return buttons;if(selector==='[data-device-view]')return panels;throw Error(selector);}},refreshDevices(){},refreshReservations(){return Promise.resolve();},refreshWebhook(){return Promise.resolve();},loadNetworkConfig(){},loadWifi(){},loadLogs(){}});
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
