const $ = s => document.querySelector(s);
let reservations = [], deviceTimer = null, loadingDevices = false, webhookEditing = false, currentDevice = null, deviceView = 'online', pendingDevice = new URLSearchParams(location.search).get('device')?.toLowerCase() || '';
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Erro de comunicação.');
  return result;
}
function message(text, error=false) { const box=$('#message'); box.replaceChildren(); box.className=error?'toast error':'toast'; if(!text)return; const label=document.createElement('span'); label.textContent=text; const close=document.createElement('button'); close.type='button'; close.className='toast-close'; close.setAttribute('aria-label','Fechar notificação'); close.textContent='×'; close.addEventListener('click',()=>box.replaceChildren()); box.append(label,close); }
function node(tag, cls, text) { const el=document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el; }
function deviceIcon(kind) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('viewBox','0 0 24 24'); svg.setAttribute('aria-hidden','true');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d',kind==='wifi' ? 'M3 8.5a14 14 0 0 1 18 0M6 12a9.5 9.5 0 0 1 12 0M9 15.5a5 5 0 0 1 6 0M12 19h.01' : 'M4 4h16v10H4zM9 18h6M12 14v4'); svg.append(path); return svg;
}
function setPage(page) {
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==`page-${page}`);
  document.querySelectorAll('.nav-item').forEach(el=>{ const active=el.dataset.page===page; el.classList.toggle('active',active); if(active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  $('#breadcrumb').textContent=({devices:'Dispositivos',reservations:'Reservas de IP',dhcp:'DHCP',dns:'DNS',wifi:'Redes Wi-Fi',reboot:'Reinício',notifications:'Notificações'})[page];
  if(page==='devices') refreshDevices(); else if(page==='reservations') refreshReservations().catch(e=>message(e.message,true)); else if(page==='notifications') refreshWebhook().catch(e=>message(e.message,true)); else if(page==='dhcp'||page==='dns') loadNetworkConfig(page); else if(page==='wifi') loadWifi();
}
document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>setPage(el.dataset.page)));
function selectDeviceView(view){ deviceView=view; for(const state of ['online','offline']){ const active=state===view; $(`#show-${state}`).classList.toggle('active',active); $(`#show-${state}`).setAttribute('aria-pressed',String(active)); } document.querySelectorAll('[data-device-view]').forEach(panel=>panel.hidden=panel.dataset.deviceView!==view); }
$('#show-online').addEventListener('click',()=>selectDeviceView('online'));
$('#show-offline').addEventListener('click',()=>selectDeviceView('offline'));
async function refreshDevices() {
  if (loadingDevices || $('#dashboard').hidden || document.querySelector('.name-form.is-editing')) return;
  loadingDevices=true;
  try {
    const data=await api('/api/devices');
    if(document.querySelector('.name-form.is-editing')) return;
    const online=data.devices.filter(d=>d.status==='online');
    const lan=online.filter(d=>d.type==='lan'), wifi=online.filter(d=>d.type==='wifi'), offline=data.devices.filter(d=>d.status==='offline');
    $('#total-count').textContent=online.length; $('#wifi-count').textContent=wifi.length; $('#lan-count').textContent=lan.length;
    const target=$('#device-sections'); target.replaceChildren();
    for(const [title, subtitle, devices, state] of [['Wi-Fi','Conexões sem fio',wifi,'online'],['LAN','Conexões com fio',lan,'online'],['Dispositivos offline','Dispositivos informados pelo gateway como desconectados',offline,'offline']]) {
      const panel=node('div','panel device-panel'); const head=node('div','panel-header');
      panel.dataset.deviceView=state; panel.hidden=state!==deviceView;
      const heading=node('div'); heading.append(node('h2','',title),node('p','muted',subtitle)); head.append(heading,node('span','count',`${devices.length} ${state}`)); panel.append(head);
      if(!devices.length) panel.append(node('p','empty',state==='offline'?'Nenhum dispositivo offline informado pelo gateway.':'Nenhum dispositivo conectado nesta rede.'));
      const grid=node('div','device-grid');
      devices.forEach(d=>{
        const card=node('button','device-card'); card.type='button';
        const top=node('div','device-card-top'), icon=node('span','device-icon'); icon.append(deviceIcon(d.type));
        top.append(icon,node('span',state==='offline'?'offline-pill':'online-pill',state==='offline'?'● Offline':'● Online')); const title=node('strong',`device-card-name${d.name ? ' ip-fixed' : ''}`,d.name || d.gateway_name || d.hostname || 'Dispositivo sem nome');
        card.append(top,title,node('span','device-card-network',d.network || d.port || 'Rede não identificada'),node('span',`device-card-ip${d.ip_fixed || d.ip_static ? ' ip-fixed' : ''}`,`${d.ip || 'Sem IP'}${d.ip_fixed ? ' · Fixo' : d.ip_static ? ' · Estático' : ''}`),node('span','device-card-mac',d.mac),node('span','device-card-open','Ver detalhes →'));
        card.addEventListener('click',()=>openDevice(d)); grid.append(card);
      }); panel.append(grid); target.append(panel);
    }
    if(pendingDevice){ const linked=data.devices.find(d=>d.mac===pendingDevice); pendingDevice=''; if(linked) openDevice(linked); else message('Dispositivo não encontrado na lista atual do gateway.',true); }
    $('#devices-error').hidden=data.reservations_available!==false; if(data.reservations_available===false) $('#devices-error').textContent='Não foi possível verificar as reservas; alguns IPs fixos podem não estar destacados.'; $('#last-update').textContent=`Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
  } catch(err) { $('#devices-error').textContent=err.message; $('#devices-error').hidden=false; }
  finally { loadingDevices=false; }
}
function detailItem(label,value){ const item=node('div','detail-item'); item.append(node('span','muted',label),node('strong','',value || 'Não informado')); return item; }
function formatDuration(value){ const match=/^(\d+):(\d+)$/.exec(value || ''); return match ? `${match[1]} h ${match[2]} min` : value || 'Não informado'; }
async function openDevice(device){
  currentDevice=device; $('#detail-title').textContent=device.name || device.gateway_name || device.hostname || 'Dispositivo sem nome'; $('#detail-title').classList.toggle('ip-fixed',Boolean(device.name));
  $('#detail-subtitle').textContent=`${device.network || device.port || 'Rede não identificada'} · ${device.status === 'online' ? 'Online' : 'Offline'}`;
  const info=$('#detail-info'); info.replaceChildren();
  for(const [label,value] of [['Nome no gateway',device.gateway_name || device.hostname],['IP atual',device.ip ? `${device.ip}${device.ip_fixed ? ' · Fixo' : device.ip_static ? ' · Estático' : ''}` : ''],['Endereço MAC',device.mac],['Rede',device.network],['Porta',device.port],['Tempo conectado',formatDuration(device.duration)],['Tipo de IP',device.ip_type],['IPv6',device.ipv6_enabled === '1' ? 'Ativo' : device.ipv6_enabled === '0' ? 'Não informado pelo cliente' : 'Não informado']]) { const item=detailItem(label,value); if(label==='IP atual' && (device.ip_fixed || device.ip_static)) item.querySelector('strong').classList.add('ip-fixed'); info.append(item); }
  $('#detail-name').value=device.name || ''; $('#detail-ip').value=device.ip || ''; $('#detail-ip-submit').disabled=true; $('#detail-ip-status').textContent='Consultando reservas...';
  if(!$('#device-dialog').open) $('#device-dialog').showModal();
  try { const data=await api('/api/reservations'); if(currentDevice !== device) return; const existing=data.reservations.find(r=>r.mac.toLowerCase()===device.mac); device.reservationId=existing?.id || ''; if(existing) $('#detail-ip').value=existing.ip; $('#detail-ip-submit').textContent=existing?'Atualizar reserva':'Fixar IP'; $('#detail-ip-status').textContent=existing?'Este dispositivo já possui uma reserva de IP.':'A reserva pode entrar em vigor após a renovação DHCP.'; $('#detail-ip-submit').disabled=false; }
  catch(e){if(currentDevice===device) $('#detail-ip-status').textContent='Não foi possível consultar reservas: '+e.message;}
}
$('#detail-close').addEventListener('click',()=>$('#device-dialog').close());
$('#device-dialog').addEventListener('close',()=>{currentDevice=null; const url=new URL(location.href); url.searchParams.delete('device'); history.replaceState(null,'',url);});
$('#detail-name-form').addEventListener('submit',async e=>{e.preventDefault(); const d=currentDevice, button=e.submitter; button.disabled=true; try{await api('/api/name',{mac:d.mac,name:$('#detail-name').value}); d.name=$('#detail-name').value.trim(); $('#detail-title').textContent=d.name || d.gateway_name || d.hostname || 'Dispositivo sem nome'; $('#detail-title').classList.toggle('ip-fixed',Boolean(d.name)); message('Identificador salvo.'); await refreshDevices();}catch(err){message(err.message,true)}finally{button.disabled=false}});
$('#detail-ip-form').addEventListener('submit',async e=>{e.preventDefault(); const d=currentDevice, button=e.submitter; button.disabled=true; try{await api('/api/reservation',{id:d.reservationId || '',mac:d.mac,ip:$('#detail-ip').value.trim()}); message('Reserva de IP confirmada pelo gateway.'); $('#detail-ip-status').textContent='Reserva confirmada pelo gateway.'; const data=await api('/api/reservations'); d.reservationId=data.reservations.find(r=>r.mac.toLowerCase()===d.mac)?.id || ''; button.textContent='Atualizar reserva';}catch(err){message(err.message,true)}finally{button.disabled=false}});
function resetForm(){ $('#reservation').reset();$('#reservation-id').value='';$('#form-title').textContent='Nova reserva'; }
async function refreshReservations(){
  const data=await api('/api/reservations');reservations=data.reservations;const list=$('#list');list.replaceChildren();
  if(data.device_names_unavailable) list.append(node('p','notice','Não foi possível carregar os nomes do gateway; os identificadores locais continuam disponíveis.'));
  if(!reservations.length){list.append(node('p','empty','Nenhuma reserva encontrada.'));return;}
  reservations.forEach(row=>{const card=node('div','reservation-row');const info=node('div');const network=node('small','muted');network.append(document.createTextNode(`${row.mac} · `),node('span',row.enabled===false?'':'ip-fixed',`${row.ip} · ${row.enabled===false?'Reserva desativada':'Reservado'}`));info.append(node('strong',row.name?'ip-fixed':'',row.name||'Identificador não definido'),network,node('small','muted',`Nome do dispositivo: ${row.gateway_name||row.hostname||'Não informado'}`));const edit=node('button','secondary','Editar');edit.type='button';edit.addEventListener('click',()=>{$('#reservation-id').value=row.id;$('#mac').value=row.mac;$('#ip').value=row.ip;$('#name').value=row.name;$('#form-title').textContent='Editar reserva';$('#mac').focus()});card.append(info,edit);list.append(card)});
}
async function showDashboard(){ $('#login-screen').hidden=true; $('#dashboard').hidden=false; await refreshDevices(); clearInterval(deviceTimer); deviceTimer=setInterval(()=>{if(!document.hidden)refreshDevices()},15000); }
$('#connect').addEventListener('submit',async e=>{e.preventDefault();message('Conectando...');try{await api('/api/login',{address:$('#address').value,username:$('#username').value,password:$('#password').value});$('#password').value='';message('Conectado.');await showDashboard()}catch(err){$('#password').value='';message(err.message,true)}});
api('/api/session').then(()=>showDashboard()).catch(()=>{});
$('#reservation').addEventListener('submit',async e=>{e.preventDefault();message('Salvando reserva...');try{const mac=$('#mac').value.trim().toLowerCase(),id=$('#reservation-id').value,ip=$('#ip').value.trim();const old=reservations.find(row=>row.id===id);if(!old||old.mac!==mac||old.ip!==ip)await api('/api/reservation',{id,mac,ip});try{await api('/api/name',{mac,name:$('#name').value})}catch(err){message('Reserva salva, mas o identificador não foi salvo: '+err.message,true);await refreshReservations();return}resetForm();await refreshReservations();message('Dados salvos.')}catch(err){message(err.message,true)}});
async function refreshWebhook(){
  const data=await api('/api/webhook');
  if(webhookEditing) return;
  $('#webhook-enabled').checked=data.enabled;
  $('#webhook-badge').textContent=data.enabled?'Ativado':data.configured?'Desativado':'Não configurado';
  $('#webhook-url').placeholder=data.configured?'URL salva — preencha apenas para alterar':'https://discord.com/api/webhooks/...';
  $('#webhook-status').textContent=data.status;
}
$('#webhook-form').addEventListener('input',()=>{webhookEditing=true});
$('#webhook-form').addEventListener('change',()=>{webhookEditing=true});
$('#webhook-form').addEventListener('submit',async e=>{
  e.preventDefault(); const button=e.submitter; button.disabled=true;
  try { await api('/api/webhook',{url:$('#webhook-url').value,enabled:$('#webhook-enabled').checked}); $('#webhook-url').value=''; webhookEditing=false; await refreshWebhook(); message('Configurações de notificação salvas.'); }
  catch(err) { message(err.message,true); } finally { button.disabled=false; }
});
$('#cancel').addEventListener('click',resetForm);$('#refresh-devices').addEventListener('click',refreshDevices);$('#refresh-reservations').addEventListener('click',()=>refreshReservations().catch(e=>message(e.message,true)));
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{})}finally{clearInterval(deviceTimer);webhookEditing=false;$('#webhook-url').value='';$('#dashboard').hidden=true;$('#login-screen').hidden=false;resetForm();message('Sessão encerrada.')}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('#dashboard').hidden)refreshDevices()});

setInterval(()=>{if(!document.hidden && !$('#dashboard').hidden && !$('#page-notifications').hidden && document.activeElement!==$('#webhook-url')) refreshWebhook().catch(()=>{});},10000);
$('#test-webhook').addEventListener('click',async e=>{const button=e.currentTarget; button.disabled=true; try { await api('/api/webhook/test',{}); message('Mensagem de teste enviada ao Discord.'); } catch(err) { message(err.message,true); } finally { button.disabled=false; }});
async function loadNetworkConfig(page){
  const status=$(`#${page}-status`); status.textContent='Consultando gateway...';
  try{const {config:c}=await api('/api/dhcp'); if(page==='dhcp'){ $('#dhcp-enabled').checked=c.enabled; $('#dhcp-start').value=c.start; $('#dhcp-end').value=c.end; $('#dhcp-lease').value=c.lease; $('#dhcp-network').textContent=`Gateway ${c.lan_ip} · Máscara ${c.mask}`; } else {$('#dns-primary').value=c.dns_primary; $('#dns-secondary').value=c.dns_secondary;} status.textContent='Dados carregados do gateway.';}catch(e){status.textContent=e.message;}
}
for(const page of ['dhcp','dns']){
  $(`#refresh-${page}`).addEventListener('click',()=>loadNetworkConfig(page));
  $(`#${page}-form`).addEventListener('submit',async e=>{e.preventDefault(); const button=e.submitter; button.disabled=true;
    const body=page==='dhcp'?{enabled:$('#dhcp-enabled').checked,start:$('#dhcp-start').value.trim(),end:$('#dhcp-end').value.trim(),lease:$('#dhcp-lease').value}:{dns_primary:$('#dns-primary').value.trim(),dns_secondary:$('#dns-secondary').value.trim()};
    try{await api(`/api/${page}`,body); message(`${page.toUpperCase()} confirmado pelo gateway.`); await loadNetworkConfig(page);}catch(err){message(err.message,true)}finally{button.disabled=false;}
  });
}
async function loadWifi(){
  const area=$('#wifi-configs'), status=$('#wifi-status'); area.replaceChildren(); status.hidden=false; status.textContent='Consultando gateway...';
  try{const {config}=await api('/api/wifi'); status.hidden=true; config.forEach(n=>{
    const panel=node('div','panel wifi-panel'), heading=node('h2','',n.network); const form=node('form','wifi-config-form');
    const label=node('label','','Nome da rede'); const input=node('input'); input.value=n.ssid; input.required=true; input.maxLength=32; label.append(input);
    const enabledLabel=node('label','switch-label'), enabled=node('input'); enabled.type='checkbox'; enabled.checked=n.enabled; enabledLabel.append(enabled,document.createTextNode(' Rede ativada'));
    const broadcastLabel=node('label','switch-label'), broadcast=node('input'); broadcast.type='checkbox'; broadcast.checked=n.broadcast; broadcastLabel.append(broadcast,document.createTextNode(' Transmitir nome da rede'));
    const details=node('p','footnote',`${n.id.split('.').pop()} · Limite de ${n.max_clients} clientes`); const button=node('button','primary','Salvar rede'); button.type='submit';
    form.append(label,enabledLabel,broadcastLabel,details,button); panel.append(heading,form); area.append(panel);
    form.addEventListener('submit',async e=>{e.preventDefault(); button.disabled=true; try{await api('/api/wifi',{id:n.id,ssid:input.value,enabled:enabled.checked,broadcast:broadcast.checked});message('Rede Wi-Fi confirmada pelo gateway.'); await loadWifi();}catch(err){message(err.message,true)}finally{button.disabled=false}});
  });}catch(e){status.textContent=e.message;}
}
$('#refresh-wifi').addEventListener('click',loadWifi);
$('#reboot-button').addEventListener('click',()=>{$('#reboot-confirm').value='';$('#reboot-dialog').showModal()});
$('#reboot-cancel').addEventListener('click',()=>$('#reboot-dialog').close());
$('#reboot-form').addEventListener('submit',async e=>{e.preventDefault(); if($('#reboot-confirm').value!=='REINICIAR'){message('Digite REINICIAR para confirmar.',true);return} const button=e.submitter; button.disabled=true; try{await api('/api/reboot',{confirm:'REINICIAR'}); $('#reboot-dialog').close(); $('#reboot-status').textContent='Comando enviado. Aguarde a retomada da rede e conecte-se novamente.'; message('Comando de reinício enviado.');}catch(err){message(err.message,true)}finally{button.disabled=false}});
