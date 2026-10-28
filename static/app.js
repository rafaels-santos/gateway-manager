const $ = s => document.querySelector(s);
let reservations = [], deviceTimer = null, loadingDevices = false, webhookEditing = false;
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Erro de comunicação.');
  return result;
}
function message(text, error=false) { $('#message').textContent=text; $('#message').className=error?'toast error':'toast'; }
function node(tag, cls, text) { const el=document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el; }
function deviceIcon(kind) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('viewBox','0 0 24 24'); svg.setAttribute('aria-hidden','true');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d',kind==='wifi' ? 'M3 8.5a14 14 0 0 1 18 0M6 12a9.5 9.5 0 0 1 12 0M9 15.5a5 5 0 0 1 6 0M12 19h.01' : 'M4 4h16v10H4zM9 18h6M12 14v4'); svg.append(path); return svg;
}
function setPage(page) {
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==`page-${page}`);
  document.querySelectorAll('.nav-item').forEach(el=>{ const active=el.dataset.page===page; el.classList.toggle('active',active); if(active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  $('#breadcrumb').textContent=page==='devices'?'Dispositivos':page==='reservations'?'Reservas de IP':'Notificações';
  if(page==='devices') refreshDevices(); else if(page==='reservations') refreshReservations().catch(e=>message(e.message,true)); else refreshWebhook().catch(e=>message(e.message,true));
}
document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>setPage(el.dataset.page)));
async function refreshDevices() {
  if (loadingDevices || $('#dashboard').hidden || document.querySelector('.name-form.is-editing')) return;
  loadingDevices=true;
  try {
    const data=await api('/api/devices');
    if(document.querySelector('.name-form.is-editing')) return;
    const online=data.devices.filter(d=>d.status==='online');
    const lan=online.filter(d=>d.type==='lan'), wifi=online.filter(d=>d.type==='wifi');
    $('#total-count').textContent=online.length; $('#wifi-count').textContent=wifi.length; $('#lan-count').textContent=lan.length;
    const target=$('#device-sections'); target.replaceChildren();
    for(const [title, subtitle, devices] of [['Wi-Fi','Conexões sem fio',wifi],['LAN','Conexões com fio',lan]]) {
      const panel=node('div','panel device-panel'); const head=node('div','panel-header');
      const heading=node('div'); heading.append(node('h2','',title),node('p','muted',subtitle)); head.append(heading,node('span','count',`${devices.length} online`)); panel.append(head);
      if(!devices.length) panel.append(node('p','empty','Nenhum dispositivo conectado nesta rede.'));
      devices.forEach(d=>{
        const row=node('div','device-row'); const identity=node('div','device-identity'); const icon=node('span','device-icon'); icon.append(deviceIcon(d.type));
        const info=node('div'); info.append(node('strong','',d.gateway_name || d.hostname || 'Dispositivo sem nome'),node('small','muted',`${d.port || '—'} · Online`)); identity.append(icon,info);
        const network=node('div','network'); network.append(node('span','',d.ip || 'Sem IP'),node('small','muted',d.mac));
        const form=node('form','name-form');
        const display=node('div','name-display');
        const caption=node('span','identifier-label','Identificador');
        const current=node('strong','identifier-value',d.name || 'Não definido');
        display.append(caption,current);
        const edit=node('button','identifier-edit',d.name ? 'Editar' : '+ Adicionar'); edit.type='button'; edit.setAttribute('aria-label',`Editar identificador de ${d.hostname || d.mac}`);
        const input=node('input','device-name-input'); input.value=d.name; input.placeholder='Nome do identificador'; input.maxLength=80; input.setAttribute('aria-label',`Identificador de ${d.hostname || d.mac}`); input.hidden=true;
        const save=node('button','secondary','Salvar'); save.type='submit'; save.hidden=true;
        const cancel=node('button','identifier-edit','Cancelar'); cancel.type='button'; cancel.hidden=true;
        function leaveEdit() { form.classList.remove('is-editing'); display.hidden=false; edit.hidden=false; input.hidden=true; save.hidden=true; cancel.hidden=true; }
        edit.addEventListener('click',()=>{ form.classList.add('is-editing'); display.hidden=true; edit.hidden=true; input.hidden=false; save.hidden=false; cancel.hidden=false; input.value=d.name; input.focus(); });
        cancel.addEventListener('click',()=>{leaveEdit();refreshDevices()});
        input.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();leaveEdit();refreshDevices()}});
        form.append(display,edit,input,save,cancel);
        form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{await api('/api/name',{mac:d.mac,name:input.value});d.name=input.value.trim();leaveEdit();message('Identificador salvo para todas as abas.');await refreshDevices();}catch(err){message(err.message,true)}finally{save.disabled=false}});
        row.append(identity,network,form); panel.append(row);
      }); target.append(panel);
    }
    $('#devices-error').hidden=true; $('#last-update').textContent=`Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
  } catch(err) { $('#devices-error').textContent=err.message; $('#devices-error').hidden=false; }
  finally { loadingDevices=false; }
}
function resetForm(){ $('#reservation').reset();$('#reservation-id').value='';$('#form-title').textContent='Nova reserva'; }
async function refreshReservations(){
  const data=await api('/api/reservations');reservations=data.reservations;const list=$('#list');list.replaceChildren();
  if(data.device_names_unavailable) list.append(node('p','notice','Não foi possível carregar os nomes do gateway; os identificadores locais continuam disponíveis.'));
  if(!reservations.length){list.append(node('p','empty','Nenhuma reserva encontrada.'));return;}
  reservations.forEach(row=>{const card=node('div','reservation-row');const info=node('div');info.append(node('strong','',row.gateway_name||row.hostname||'Dispositivo sem nome'),node('small','muted',`${row.mac} · ${row.ip}`),node('small','muted',`Identificador: ${row.name||'Não definido'}`));const edit=node('button','secondary','Editar');edit.type='button';edit.addEventListener('click',()=>{$('#reservation-id').value=row.id;$('#mac').value=row.mac;$('#ip').value=row.ip;$('#name').value=row.name;$('#form-title').textContent='Editar reserva';$('#mac').focus()});card.append(info,edit);list.append(card)});
}
$('#connect').addEventListener('submit',async e=>{e.preventDefault();message('Conectando...');try{await api('/api/login',{address:$('#address').value,username:$('#username').value,password:$('#password').value});$('#password').value='';$('#login-screen').hidden=true;$('#dashboard').hidden=false;message('Conectado.');await refreshDevices();clearInterval(deviceTimer);deviceTimer=setInterval(()=>{if(!document.hidden)refreshDevices()},15000)}catch(err){$('#password').value='';message(err.message,true)}});
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
