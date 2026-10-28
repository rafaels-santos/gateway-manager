const $ = s => document.querySelector(s);
let reservations = [], deviceTimer = null, loadingDevices = false, currentDevice = null, deviceView = 'online', pendingDevice = new URLSearchParams(location.search).get('device')?.toLowerCase() || '';
const zoneFilters = {wifi:{network:'',tag:'',name:''},lan:{network:'',tag:'',name:''},offline:{network:'',tag:'',name:''},blocked:{network:'',tag:'',name:''}};
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
  document.addEventListener('click',event=>{document.querySelectorAll('.filter-menu[open]').forEach(menu=>{if(!menu.contains(event.target)) menu.open=false;});});
document.addEventListener('keydown',event=>{if(event.key==='Escape') document.querySelectorAll('.filter-menu[open]').forEach(menu=>{menu.open=false;menu.querySelector('summary').focus();});});
document.querySelectorAll('.nav-item').forEach(el=>{ const active=el.dataset.page===page; el.classList.toggle('active',active); if(active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  $('#breadcrumb').textContent=({devices:'Dispositivos',reservations:'Reservas de IP',dhcp:'DHCP',dns:'DNS',wifi:'Redes Wi-Fi',reboot:'Reinício',logs:'Logs',notifications:'Notificações'})[page];
  if(page==='devices') refreshDevices(); else if(page==='reservations') refreshReservations().catch(e=>message(e.message,true)); else if(page==='notifications') refreshWebhook().catch(e=>message(e.message,true)); else if(page==='dhcp'||page==='dns') loadNetworkConfig(page); else if(page==='wifi') loadWifi(); else if(page==='logs') loadLogs();
}
document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>setPage(el.dataset.page)));
function selectDeviceView(view){ deviceView=view; for(const state of ['online','offline','blocked']){ const active=state===view; $(`#show-${state}`).classList.toggle('active',active); $(`#show-${state}`).setAttribute('aria-pressed',String(active)); } document.querySelectorAll('[data-device-view]').forEach(panel=>panel.hidden=panel.dataset.deviceView!==view); }
$('#show-online').addEventListener('click',()=>selectDeviceView('online'));
$('#show-offline').addEventListener('click',()=>selectDeviceView('offline'));
$('#show-blocked').addEventListener('click',()=>selectDeviceView('blocked'));
async function refreshDevices() {
  if (loadingDevices || $('#dashboard').hidden || document.querySelector('.filter-menu[open]')) return;
  loadingDevices=true;
  try {
    const data=await api('/api/devices');
    if(document.querySelector('.filter-menu[open]')) return;
    const online=data.devices.filter(d=>d.status==='online');
    const lan=online.filter(d=>d.type==='lan'), wifi=online.filter(d=>d.type==='wifi'), offline=data.devices.filter(d=>d.status==='offline');
    $('#total-count').textContent=online.length; $('#wifi-count').textContent=wifi.length; $('#lan-count').textContent=lan.length;
    const target=$('#device-sections'); target.replaceChildren();
    for(const [title, subtitle, devices, state, zone] of [['Wi-Fi','Conexões sem fio',wifi,'online','wifi'],['LAN','Conexões com fio',lan,'online','lan'],['Dispositivos offline','Dispositivos informados pelo gateway como desconectados',offline,'offline','offline'],['Dispositivos bloqueados','Regras de bloqueio Wi-Fi · regras inativas não impedem o acesso',data.blocked || [],'blocked','blocked']]) {
      const panel=node('div','panel device-panel'); const head=node('div','panel-header');
      panel.dataset.deviceView=state; panel.hidden=state!==deviceView;
      const heading=node('div'); heading.append(node('h2','',title),node('p','muted',subtitle));
      const tools=node('div','zone-tools'), count=node('span','count'); const menu=node('details','filter-menu'), summary=node('summary','secondary','⚙ Filtrar'); menu.append(summary);
      const choices=node('div','filter-options'), filterHeader=node('div','filter-header'); filterHeader.append(node('strong','','Filtros')); choices.append(filterHeader);
      function makeFilter(label, type, options){const wrap=node('label','',label), select=node('select'); select.setAttribute('aria-label',`${label} — ${title}`); for(const [value,text] of options){const opt=node('option','',text); opt.value=value; select.append(opt)} select.value=zoneFilters[zone][type]; select.addEventListener('change',()=>{zoneFilters[zone][type]=select.value;applyFilters()}); wrap.append(select); choices.append(wrap)}
      makeFilter('Rede','network',[['','Todas as redes'],['2.4','2,4 GHz'],['5','5 GHz'],['guest','Convidados']]);
      makeFilter('Categoria','tag',[['','Todas as categorias'],['IoT','IoT'],['Celulares','Celulares'],['Computadores','Computadores'],['Rede','Rede'],['none','Sem categoria']]);
      makeFilter('Identificador','name',[['','Todos os dispositivos'],['named','Com identificador'],['unnamed','Sem identificador']]);
      const reset=node('button','secondary','Todos'); reset.type='button'; reset.setAttribute('aria-label',`Limpar filtros de ${title}`); reset.addEventListener('click',()=>{zoneFilters[zone]={network:'',tag:'',name:''}; choices.querySelectorAll('select').forEach(s=>s.value=''); applyFilters()}); filterHeader.append(reset); menu.append(choices); tools.append(count,menu); head.append(heading,tools); panel.append(head);
      const empty=node('p','empty'); panel.append(empty);
      const grid=node('div','device-grid');
      const entries=[];
      devices.forEach(d=>{
        const card=node('button','device-card'); card.type='button';
        const top=node('div','device-card-top'), icon=node('span','device-icon'); icon.append(deviceIcon(d.type));
        top.append(icon,node('span',state==='blocked'?(d.block_active===false?'offline-pill':'blocked-pill'):state==='offline'?'offline-pill':'online-pill',state==='blocked'?(d.block_active===false?'● Regra inativa':'● Bloqueado'):state==='offline'?'● Offline':'● Online')); const title=node('strong',`device-card-name${d.name ? ' ip-fixed' : ''}`,d.name || d.gateway_name || d.hostname || 'Dispositivo sem nome');
        card.append(top,title,node('span','device-card-network',d.network || d.port || 'Rede não identificada'),node('span',`device-card-ip${d.ip_fixed || d.ip_static ? ' ip-fixed' : ''}`,`${d.ip || 'Sem IP'}${d.ip_fixed ? ' · Fixo' : d.ip_static ? ' · Estático' : ''}`),node('span','device-card-mac',d.mac.toUpperCase()),node('span','device-card-open','Ver detalhes →'));
        if(d.tag) card.insertBefore(node('span','device-tag',d.tag),card.lastChild);
        card.addEventListener('click',()=>openDevice(d)); grid.append(card); entries.push({card,device:d});
      });
      function applyFilters(){const f=zoneFilters[zone], active=Object.values(f).filter(Boolean).length; summary.classList.toggle('filter-active',active>0); summary.textContent=active ? `⚙ Filtrar · ${active}` : '⚙ Filtrar'; summary.setAttribute('aria-label',`Filtrar ${title}${active ? `: ${active} filtros ativos` : ': sem filtros ativos'}`); reset.disabled=active===0; let shown=0; for(const {card,device:d} of entries){const network=d.network || ''; const matchNetwork=!f.network || (f.network==='guest' ? network.includes('Convidados') : f.network==='2.4' ? network.includes('2,4 GHz') : network.includes('5 GHz')); const matchTag=!f.tag || (f.tag==='none' ? !d.tag : d.tag===f.tag); const named=Boolean((d.name || '').trim()); const matchName=!f.name || (f.name==='named' ? named : !named); card.hidden=!(matchNetwork && matchTag && matchName); if(!card.hidden)shown++} count.textContent=`${shown} de ${devices.length} ${state}`; empty.hidden=shown>0; empty.textContent=devices.length?'Nenhum dispositivo corresponde aos filtros.':state==='blocked'?'Nenhum bloqueio ativo informado pelo gateway.':state==='offline'?'Nenhum dispositivo offline informado pelo gateway.':'Nenhum dispositivo conectado nesta rede.'; }
      applyFilters(); panel.append(grid); target.append(panel);
    }
    $('#blocked-error').hidden=data.blocked_available!==false; $('#blocked-error').textContent=data.blocked_available===false?'Não foi possível consultar os bloqueios do gateway. A lista de bloqueados está indisponível.':'';
    if(pendingDevice){ const linked=data.devices.find(d=>d.mac===pendingDevice); pendingDevice=''; if(linked) openDevice(linked); else message('Dispositivo não encontrado na lista atual do gateway.',true); }
    $('#devices-error').hidden=data.reservations_available!==false; if(data.reservations_available===false) $('#devices-error').textContent='Não foi possível verificar as reservas; alguns IPs fixos podem não estar destacados.'; $('#last-update').textContent=`Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
  } catch(err) { $('#devices-error').textContent=err.message; $('#devices-error').hidden=false; }
  finally { loadingDevices=false; }
}
function detailItem(label,value){ const item=node('div','detail-item'); item.append(node('span','muted',label),node('strong','',value || 'Não informado')); return item; }
function formatDuration(value){ const match=/^(\d+):(\d+)$/.exec(value || ''); return match ? `${match[1]} h ${match[2]} min` : value || 'Não informado'; }
async function openDevice(device){
  currentDevice=device; $('#block-client').disabled=device.type!=='wifi'; $('#block-client').textContent=device.block_rule?(device.block_active===false?'Remover regra inativa':'Desbloquear cliente'):'Bloquear cliente Wi-Fi'; $('#detail-title').textContent=device.name || device.gateway_name || device.hostname || 'Dispositivo sem nome'; $('#detail-title').classList.toggle('ip-fixed',Boolean(device.name));
  $('#detail-subtitle').textContent=`${device.network || device.port || 'Rede não identificada'} · ${device.block_rule ? 'Bloqueado' : device.status === 'online' ? 'Online' : 'Offline'}`;
  $('#detail-subtitle').classList.toggle('blocked-pill',Boolean(device.block_rule));
  const info=$('#detail-info'); info.replaceChildren();
  for(const [label,value] of [['Nome no gateway',device.gateway_name || device.hostname],['IP atual',device.ip ? `${device.ip}${device.ip_fixed ? ' · Fixo' : device.ip_static ? ' · Estático' : ''}` : ''],['Endereço MAC',device.mac.toUpperCase()],['Rede',device.network],['Porta',device.port],['Tempo conectado',formatDuration(device.duration)],['Tipo de IP',device.ip_type],['IPv6',device.ipv6_enabled === '1' ? 'Ativo' : device.ipv6_enabled === '0' ? 'Não informado pelo cliente' : 'Não informado']]) { const item=detailItem(label,value); if(label==='IP atual' && (device.ip_fixed || device.ip_static)) item.querySelector('strong').classList.add('ip-fixed'); info.append(item); }
  $('#detail-name').value=device.name || ''; $('#detail-tag').value=device.tag || ''; $('#detail-ip').value=device.ip || ''; $('#detail-ip-submit').disabled=true; $('#detail-ip-status').textContent='Consultando reservas...';
  if(!$('#device-dialog').open) $('#device-dialog').showModal();
  try { const data=await api('/api/reservations'); if(currentDevice !== device) return; const existing=data.reservations.find(r=>r.mac.toLowerCase()===device.mac); device.reservationId=existing?.id || ''; if(existing) $('#detail-ip').value=existing.ip; $('#detail-ip-submit').textContent=existing?'Atualizar reserva':'Fixar IP'; $('#detail-ip-status').textContent=existing?'Este dispositivo já possui uma reserva de IP.':'A reserva pode entrar em vigor após a renovação DHCP.'; $('#detail-ip-submit').disabled=false; }
  catch(e){if(currentDevice===device) $('#detail-ip-status').textContent='Não foi possível consultar reservas: '+e.message;}
}
$('#detail-close').addEventListener('click',()=>$('#device-dialog').close());
$('#device-dialog').addEventListener('close',()=>{currentDevice=null; const url=new URL(location.href); url.searchParams.delete('device'); history.replaceState(null,'',url);});
$('#detail-name-form').addEventListener('submit',async e=>{e.preventDefault(); const d=currentDevice, button=e.submitter; button.disabled=true; try{await api('/api/name',{mac:d.mac,name:$('#detail-name').value}); d.name=$('#detail-name').value.trim(); $('#detail-title').textContent=d.name || d.gateway_name || d.hostname || 'Dispositivo sem nome'; $('#detail-title').classList.toggle('ip-fixed',Boolean(d.name)); message('Identificador salvo.'); await refreshDevices();}catch(err){message(err.message,true)}finally{button.disabled=false}});
$('#detail-tag-form').addEventListener('submit',async e=>{e.preventDefault(); const d=currentDevice, button=e.submitter; button.disabled=true; try{await api('/api/tag',{mac:d.mac,tag:$('#detail-tag').value}); d.tag=$('#detail-tag').value; message('Categoria salva.'); await refreshDevices();}catch(err){message(err.message,true)}finally{button.disabled=false}});
$('#detail-ip-form').addEventListener('submit',async e=>{e.preventDefault(); const d=currentDevice, button=e.submitter; button.disabled=true; try{await api('/api/reservation',{id:d.reservationId || '',mac:d.mac,ip:$('#detail-ip').value.trim()}); message('Reserva de IP confirmada pelo gateway.'); $('#detail-ip-status').textContent='Reserva confirmada pelo gateway.'; const data=await api('/api/reservations'); d.reservationId=data.reservations.find(r=>r.mac.toLowerCase()===d.mac)?.id || ''; button.textContent='Atualizar reserva';}catch(err){message(err.message,true)}finally{button.disabled=false}});
function resetForm(){ $('#reservation').reset();$('#reservation-id').value='';$('#form-title').textContent='Nova reserva'; }
async function refreshReservations(){
  const data=await api('/api/reservations');reservations=data.reservations;const list=$('#list');list.replaceChildren();
  if(data.device_names_unavailable) list.append(node('p','notice','Não foi possível carregar os nomes do gateway; os identificadores locais continuam disponíveis.'));
  if(!reservations.length){list.append(node('p','empty','Nenhuma reserva encontrada.'));return;}
  reservations.forEach(row=>{const card=node('div','reservation-row');const info=node('div');const network=node('small','muted');network.append(document.createTextNode(`${row.mac.toUpperCase()} · `),node('span',row.enabled===false?'':'ip-fixed',`${row.ip} · ${row.enabled===false?'Reserva desativada':'Reservado'}`));info.append(node('strong',row.name?'ip-fixed':'',row.name||'Identificador não definido'),network,node('small','muted',`Nome do dispositivo: ${row.gateway_name||row.hostname||'Não informado'}`));const edit=node('button','secondary','Editar');edit.type='button';edit.addEventListener('click',()=>{$('#reservation-id').value=row.id;$('#mac').value=row.mac.toUpperCase();$('#ip').value=row.ip;$('#name').value=row.name;$('#form-title').textContent='Editar reserva';$('#mac').focus()});card.append(info,edit);list.append(card)});
}
async function loadGatewayModels(){const select=$('#gateway-model'); try{const {models}=await api('/api/gateway-types'); select.replaceChildren();const manual=node('option','','Selecione o modelo');manual.value='';select.append(manual); for(const model of models){const option=node('option','',model.label);option.value=model.id;select.append(option)} select.disabled=models.length===0; if(!models.length)message('Nenhum modelo de gateway disponível.',true);}catch(err){message('Não foi possível carregar os modelos: '+err.message,true)}}
async function showDashboard(session){ $('#device-model').textContent=(session.model_label || 'Gateway')+(session.firmware?` · ${session.firmware}`:''); $('#login-screen').hidden=true; $('#dashboard').hidden=false; await refreshDevices(); clearInterval(deviceTimer); deviceTimer=setInterval(()=>{if(!document.hidden)refreshDevices()},15000); }
$('#connect').addEventListener('submit',async e=>{e.preventDefault();if(!$('#gateway-model').value){setManualGateway(true);$('#gateway-model').focus();message('Selecione um modelo compatível para conectar.',true);return}message('Conectando...');try{const session=await api('/api/login',{model:$('#gateway-model').value,address:$('#address').value,username:$('#username').value,password:$('#password').value});if(window.isSecureContext && window.PasswordCredential && navigator.credentials){try{await navigator.credentials.store(new PasswordCredential({id:$('#username').value,password:$('#password').value}))}catch{}}$('#password').value='';message('Conectado.');await showDashboard(session)}catch(err){$('#password').value='';message(err.message,true)}});
let detectTimer=null,detectSequence=0,manualGatewayModel=false;
const modelsReady=loadGatewayModels();
function validProbeAddress(value){try{const url=new URL(value.includes('://')?value:'http://'+value),host=url.hostname.replace(/^\[|\]$/g,'');return /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)?host.split('.').every(part=>Number(part)<=255):host.includes(':')&&/^[a-f0-9:]+$/i.test(host);}catch{return false;}}
async function detectGateway(){
  clearTimeout(detectTimer);const address=$('#address').value.trim(),sequence=++detectSequence,status=$('#gateway-detection'),button=$('#detect-gateway');
  if(!validProbeAddress(address)){status.textContent='Confira o endereço IP.';button.disabled=false;return;}
  button.disabled=true;status.title='';status.textContent='Identificando gateway…';
  try{await modelsReady;const result=await api('/api/detect',{address});if(sequence!==detectSequence||address!==$('#address').value.trim())return;
    if(manualGatewayModel)return;status.replaceChildren();status.append(node('strong','',result.model||'Modelo não identificado'));if(result.firmware)status.append(node('span','muted',`Firmware ${result.firmware}`));if(!result.supported)status.append(node('span','muted','Selecione um modelo compatível manualmente.'));
    if(!manualGatewayModel){$('#gateway-model').value=result.supported?result.adapter_id:'';}
  }catch(error){if(sequence===detectSequence){status.textContent='Detecção indisponível. Selecione o modelo manualmente.';status.title=error.message;}}
  finally{if(sequence===detectSequence)button.disabled=false;}
}
$('#address').addEventListener('input',()=>{clearTimeout(detectTimer);detectSequence++;manualGatewayModel=false;$('#gateway-model').value='';setManualGateway(false);$('#gateway-detection').title='';$('#detect-gateway').disabled=false;$('#gateway-detection').textContent='Aguardando um IP completo…';if(validProbeAddress($('#address').value.trim()))detectTimer=setTimeout(detectGateway,900);});
$('#address').addEventListener('blur',()=>{if(!manualGatewayModel&&validProbeAddress($('#address').value.trim())){clearTimeout(detectTimer);detectTimer=setTimeout(detectGateway,100);}});
function setManualGateway(open){$('#manual-model').hidden=!open;$('#manual-gateway').setAttribute('aria-expanded',String(open));$('#manual-gateway').textContent=open?'Fechar seleção':'Selecionar manualmente';}
$('#manual-gateway').addEventListener('click',()=>{const open=$('#manual-model').hidden;setManualGateway(open);if(open)$('#gateway-model').focus();});
$('#gateway-model').addEventListener('change',()=>{manualGatewayModel=Boolean($('#gateway-model').value);if(manualGatewayModel){detectSequence++;$('#detect-gateway').disabled=false;$('#gateway-detection').title='';$('#gateway-detection').replaceChildren(node('strong','',$('#gateway-model').selectedOptions[0].textContent),node('span','muted','Selecionado manualmente'));setManualGateway(false);}});
$('#detect-gateway').addEventListener('click',()=>{manualGatewayModel=false;setManualGateway(false);detectGateway();});
api('/api/session').then(session=>showDashboard(session)).catch(()=>{if(!$('#login-screen').hidden)detectGateway();});
$('#reservation').addEventListener('submit',async e=>{e.preventDefault();message('Salvando reserva...');try{const mac=$('#mac').value.trim().toLowerCase(),id=$('#reservation-id').value,ip=$('#ip').value.trim();const old=reservations.find(row=>row.id===id);if(!old||old.mac!==mac||old.ip!==ip)await api('/api/reservation',{id,mac,ip});try{await api('/api/name',{mac,name:$('#name').value})}catch(err){message('Reserva salva, mas o identificador não foi salvo: '+err.message,true);await refreshReservations();return}resetForm();await refreshReservations();message('Dados salvos.')}catch(err){message(err.message,true)}});
let hookData={hooks:[],defaults:{},event_labels:{}},editingHook=null,hookBusy=false;
const hookFields={discord:[['url','URL do webhook','password']],generic:[['url','URL HTTPS pública','password']],slack:[['url','URL incoming webhook','password']],telegram:[['token','Token do bot','password'],['chat_id','Chat ID ou @canal','text']],whatsapp:[['token','Token de acesso Meta','password'],['phone_id','Phone Number ID','text'],['recipient','Destinatário com DDI (somente números)','text'],['version','Versão Graph API da sua conta (vXX.0)','text'],['template','Nome do template aprovado','text'],['language','Idioma do template (ex.: pt_BR)','text']]};
const hookHelp={discord:'Crie um webhook no canal Discord e copie sua URL.',generic:'Endpoint HTTPS público na porta 443. Recebe JSON com event, text e device. Não segue redirecionamentos.',slack:'Crie um Incoming Webhook no app Slack e selecione o canal de destino.',telegram:'Crie um bot com @BotFather. Inicie a conversa com o bot ou adicione-o ao grupo/canal com permissão para enviar. Informe o chat_id do destino.',whatsapp:'Requer WhatsApp Business Cloud API, token válido e template aprovado com exatamente um parâmetro posicional no corpo ({{1}}), sem parâmetros em cabeçalho ou botões. A mensagem do evento preenche esse parâmetro, em uma linha e até 900 caracteres. Use destinatário autorizado a receber mensagens. Não conecta WhatsApp pessoal por QR Code.'};
function hookDate(value){return value?new Date(value).toLocaleString('pt-BR'):'Ainda não realizado';}
async function refreshWebhook(){
  if($('#hook-dialog').open)return;
  const data=await api('/api/hooks');if($('#hook-dialog').open)return;hookData=data;$('#create-hook').disabled=false;$('#hooks-status').textContent=data.status;const list=$('#hooks-list');list.replaceChildren();
  if(!data.hooks.length)list.append(node('p','empty','Nenhum hook criado. Adicione seu primeiro destino de notificações.'));
  for(const hook of data.hooks){
    const card=node('article','panel hook-card'),head=node('div','panel-header'),title=node('div');title.append(node('h2','',hook.name),node('p','muted',`${data.providers[hook.provider]} · ${hook.enabled?'Ativado':'Desativado'}`));head.append(title);card.append(head);
    card.append(node('p',hook.valid?'hook-valid':'hook-invalid',hook.validation),node('p','muted',`Último teste aceito: ${hookDate(hook.last_test)} · Último evento aceito: ${hookDate(hook.last_sent)}`));
    if(hook.error)card.append(node('p','hook-invalid',hook.error));
    const details=node('details','hook-details');details.append(node('summary','','Ver configurações e mensagens'));
    for(const [key,label,type] of hookFields[hook.provider])details.append(node('p','muted',`${label}: ${type==='password'?(hook.credentials_saved?'Salvo · oculto':'Não configurado'):(hook.config[key]||'Não informado')}`));
    for(const [key,setting] of Object.entries(hook.events)){const section=node('div','hook-event-summary');section.append(node('strong','',`${data.event_labels[key]} · ${setting.enabled?'Ativado':'Desativado'}`),node('pre','',setting.template));details.append(section);}
    card.append(details);const actions=node('div','actions'),edit=node('button','secondary','Editar'),test=node('button','secondary','Testar hook');edit.type=test.type='button';edit.addEventListener('click',()=>openHook(hook));test.addEventListener('click',async()=>{test.disabled=true;try{await api('/api/hooks/test',{id:hook.id});message('Teste aceito pelo serviço. Confira o destino.');}catch(e){message(e.message,true);}finally{test.disabled=false;await refreshWebhook();}});actions.append(edit,test);card.append(actions);list.append(card);
  }
}
function renderHookFields(){
  const provider=$('#hook-provider').value,fields=$('#hook-fields');fields.replaceChildren();$('#hook-help').textContent=hookHelp[provider];
  for(const [key,label,type] of hookFields[provider]){const wrap=node('label','',label),input=node('input');input.type=type;input.dataset.hookField=key;input.autocomplete='off';input.maxLength=2048;const saved=editingHook&&editingHook.provider===provider;input.value=saved&&type!=='password'?(editingHook.config[key]||''):'';input.required=!(saved&&type==='password'&&editingHook.credentials_saved);if(!input.required)input.placeholder='Salvo — deixe vazio para manter';wrap.append(input);fields.append(wrap);}
}
function openHook(hook=null){
  editingHook=hook;$('#hook-form').reset();$('#hook-title').textContent=hook?'Editar hook':'Criar hook';$('#hook-name').value=hook?.name||'';$('#hook-provider').value=hook?.provider||'discord';$('#hook-enabled').checked=hook?.enabled??true;$('#hook-feedback').textContent='';renderHookFields();
  const events=$('#hook-events');events.replaceChildren();for(const [key,setting] of Object.entries(hook?.events||hookData.defaults)){const box=node('fieldset','webhook-event'),label=node('label','switch-label'),enabled=node('input');enabled.type='checkbox';enabled.checked=setting.enabled;enabled.dataset.hookEvent=key;label.append(enabled,document.createTextNode(hookData.event_labels[key]));const textarea=node('textarea');textarea.value=setting.template;textarea.dataset.hookTemplate=key;textarea.maxLength=1500;textarea.required=true;textarea.rows=4;textarea.setAttribute('aria-label',`Mensagem: ${hookData.event_labels[key]}`);box.append(label,textarea);events.append(box);}
  $('#hook-dialog').showModal();
}
$('#create-hook').addEventListener('click',()=>openHook());
$('#close-hook').addEventListener('click',()=>{if(!hookBusy)$('#hook-dialog').close();});
$('#hook-dialog').addEventListener('cancel',e=>{if(hookBusy)e.preventDefault();});
$('#hook-provider').addEventListener('change',renderHookFields);
$('#hook-form').addEventListener('submit',async e=>{
  e.preventDefault();if(hookBusy)return;hookBusy=true;const test=e.submitter.id==='save-test-hook';$('#save-hook').disabled=$('#save-test-hook').disabled=true;$('#hook-feedback').textContent='Salvando…';
  const body={id:editingHook?.id,name:$('#hook-name').value,provider:$('#hook-provider').value,enabled:$('#hook-enabled').checked,config:Object.fromEntries([...document.querySelectorAll('[data-hook-field]')].map(el=>[el.dataset.hookField,el.value])),events:Object.fromEntries([...document.querySelectorAll('[data-hook-event]')].map(el=>[el.dataset.hookEvent,{enabled:el.checked,template:document.querySelector(`[data-hook-template="${el.dataset.hookEvent}"]`).value}]))};
  try{const saved=await api('/api/hooks',body);editingHook={...body,config:Object.fromEntries(Object.entries(body.config).filter(([key])=>!['url','token'].includes(key))),id:saved.id,credentials_saved:true};document.querySelectorAll('[data-hook-field]').forEach(el=>{if(el.type==='password'){el.value='';el.required=false;el.placeholder='Salvo — deixe vazio para manter';}});if(test){$('#hook-feedback').textContent='Hook salvo. Enviando teste…';try{await api('/api/hooks/test',{id:saved.id});}catch(error){$('#hook-feedback').textContent=`Hook salvo, mas o teste falhou: ${error.message}`;return;}}$('#hook-dialog').close();await refreshWebhook();message(test?'Hook salvo e teste aceito pelo serviço.':'Hook salvo. Use Testar hook para validar o envio.');}
  catch(error){$('#hook-feedback').textContent=error.message;}finally{hookBusy=false;$('#save-hook').disabled=$('#save-test-hook').disabled=false;}
});
$('#cancel').addEventListener('click',resetForm);$('#refresh-devices').addEventListener('click',refreshDevices);$('#refresh-reservations').addEventListener('click',()=>refreshReservations().catch(e=>message(e.message,true)));
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{})}finally{clearInterval(deviceTimer);editingHook=null;$('#hook-dialog').close();$('#hook-form').reset();$('#dashboard').hidden=true;$('#login-screen').hidden=false;resetForm();message('Sessão encerrada.')}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('#dashboard').hidden)refreshDevices()});

setInterval(()=>{if(!document.hidden && !$('#dashboard').hidden && !$('#page-notifications').hidden && !$('#hook-dialog').open) refreshWebhook().catch(()=>{});},10000);

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

$('#block-client').addEventListener('click',async e=>{const d=currentDevice;if(!d||d.type!=='wifi')return;if(d.block_rule){if(!confirm(`${d.block_active===false?'Remover regra inativa de':'Desbloquear'} ${d.name||d.hostname||d.mac.toUpperCase()} na rede ${d.port}?`))return;const button=e.currentTarget;button.disabled=true;try{await api('/api/unblock',{mac:d.mac,rule:d.block_rule,confirm:'DESBLOQUEAR'});$('#device-dialog').close();message('Regra de bloqueio removida e confirmada pelo Huawei.');await refreshDevices();}catch(err){message(err.message,true)}finally{button.disabled=false}return}if(!confirm(`Bloquear ${d.name||d.hostname||d.mac.toUpperCase()} na rede ${d.port}? O dispositivo perderá acesso. Se o filtro estiver desativado e sem regras, ele será ativado. Para desfazer, use a aba Bloqueados.`))return;const button=e.currentTarget;button.disabled=true;try{await api('/api/block',{mac:d.mac,confirm:'BLOQUEAR',activate:true});message('Regra de bloqueio confirmada pelo Huawei.');$('#device-dialog').close();await refreshDevices();}catch(err){message(err.message,true)}finally{button.disabled=false}});

let logEvents=[], logSource='user', logRaw='', logRequest=0;
const logDescriptions={user:'User Logs: ações de administração e configuração, comandos, alarmes e eventos do sistema. Úteis para investigar reinícios e alterações no roteador.',ap:'AP Logs: registros dos pontos de acesso disponibilizados pelo Huawei, incluindo eventos técnicos de portas e conectividade. Nesta versão, o painel AP não possui filtro por Config/Shell/Alarm. Complementam os User Logs na investigação de problemas da rede sem fio.'};
function readableLog(event){
  const text=event.message.replace(/\s+/g,' ').trim();
  const port=/PortIndex:(\d+)/.exec(text);
  if(port && /LinkMode/.test(text)) return `Porta ${port[1]}: registro de negociação do enlace — ${text}`;
  if(port && /Enable:1/.test(text)) return `Porta ${port[1]} habilitada — ${text}`;
  if(/Device reset\./i.test(text)) return `Reinício do equipamento registrado — ${text}`;
  if(/Time synchronized successfully/i.test(text)) return `Relógio sincronizado — ${text}`;
  if(/System power-on time/i.test(text)) return `Inicialização do sistema — ${text}`;
  if(/Result:Success/.test(text)) return `Operação concluída — ${text}`;
  if(/Result:(Fail|Failure)/i.test(text)) return `Falha na operação — ${text}`;
  return text;
}
function renderLogs(){
  const query=$('#log-search').value.trim().toLocaleLowerCase('pt-BR'),level=$('#log-level').value,category=$('#log-category').value,list=$('#log-events');list.replaceChildren();
  const events=logEvents.filter(e=>(!level||e.level===level)&&(!category||e.category===category)&&(!query||`${e.time} ${e.source_level} ${e.category} ${e.message}`.toLocaleLowerCase('pt-BR').includes(query)));
  if(!events.length) list.append(node('p','muted','Nenhum evento para este filtro.'));
  for(const event of events){
    const row=node('div','log-line');row.title=`${event.time} [${event.source_level}] [${event.category}] ${event.message}`;
    row.append(node('span',`log-badge log-${event.level.toLowerCase()}`,event.level),node('span','log-line-text',`${event.time || 'Sem horário'} · ${event.category || 'Registro'} · ${readableLog(event)}`));
    list.append(row);
  }
}
async function loadLogs(){
  const request=++logRequest,source=logSource,button=$('#refresh-logs'),status=$('#log-status');button.disabled=true;$('#download-logs').disabled=true;status.textContent='Consultando Huawei…';logRaw='';logEvents=[];$('#log-events').replaceChildren();
  $('#log-description').textContent=logDescriptions[source];
  try{const result=await api(`/api/logs?source=${source}`);if(request!==logRequest)return;logEvents=result.events;logRaw=result.raw;
    const select=$('#log-category');select.hidden=source==='ap';$('#log-category-label').hidden=source==='ap';select.replaceChildren();const all=node('option','','Todos');all.value='';select.append(all);
    for(const category of result.categories){const option=node('option','',category+'s');option.value=category;select.append(option);}
    renderLogs();$('#download-logs').disabled=!logRaw;status.textContent=`${result.total} registros${result.limited?' · exibindo os últimos 1.000':''} · Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
  }catch(e){if(request===logRequest)status.textContent=e.message;}
  finally{if(request===logRequest)button.disabled=false;}
}
function selectLogs(source){logSource=source;for(const key of ['user','ap']){const button=$(`#logs-${key}`);button.classList.toggle('active',source===key);button.setAttribute('aria-pressed',String(source===key));}$('#log-level').value='';loadLogs();}
$('#logs-user').addEventListener('click',()=>selectLogs('user'));
$('#logs-ap').addEventListener('click',()=>selectLogs('ap'));
$('#refresh-logs').addEventListener('click',loadLogs);
$('#log-level').addEventListener('change',renderLogs);
$('#log-category').addEventListener('change',renderLogs);
$('#log-search').addEventListener('input',renderLogs);
$('#download-logs').addEventListener('click',()=>{if(!logRaw)return;const url=URL.createObjectURL(new Blob([logRaw],{type:'text/plain;charset=utf-8'})),link=node('a');link.href=url;link.download=`huawei-${logSource}-${new Date().toISOString().replace(/[:.]/g,'-')}.log`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
