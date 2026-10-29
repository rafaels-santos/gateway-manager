// Explicit confirmations and recovery for connectivity-affecting operations.
const lanForm=$('#lan-preview-form');
for(const [id,label] of [['lan-new-start','DHCP inicial proposto'],['lan-new-end','DHCP final proposto']]){
  const wrapper=node('label','',label),input=node('input');input.id=id;input.required=true;wrapper.append(input);lanForm.querySelector('.form-grid').append(wrapper);
}
const migrateLabel=node('label','switch-label'),migrateInput=node('input');migrateInput.type='checkbox';migrateInput.id='lan-migrate-reservations';migrateLabel.append(migrateInput,document.createTextNode(' Migrar reservas preservando o número do host na nova rede'));lanForm.insertBefore(migrateLabel,lanForm.querySelector('button'));
const lanDialog=node('dialog','device-dialog');lanDialog.id='lan-change-dialog';lanDialog.innerHTML='<h2>Aplicar mudança de LAN?</h2><p id="lan-confirm-summary" class="muted"></p><p>A rede e a administração podem ficar indisponíveis. Não há rollback automático. Mantenha acesso por cabo e ajuste o IP do servidor do aplicativo se ele estiver fora da nova rede.</p><form id="lan-confirm-form"><label>Digite o novo IP<input id="lan-confirm-ip" required autocomplete="off"></label><label>Digite ALTERAR LAN<input id="lan-confirm-phrase" required autocomplete="off"></label><div class="actions"><button type="submit" class="danger">Aplicar uma vez e verificar</button><button id="lan-confirm-cancel" type="button" class="secondary">Cancelar</button></div></form>';document.body.append(lanDialog);
let lanReviewed=null,lanBusy=false;
const lanBody=()=>({ip:$('#lan-new-ip').value.trim(),mask:$('#lan-new-mask').value.trim(),start:$('#lan-new-start').value.trim(),end:$('#lan-new-end').value.trim(),migrate_reservations:migrateInput.checked});
lanForm.addEventListener('input',()=>{lanReviewed=null;$('#lan-apply-button')?.remove();});
$('#lan-confirm-cancel').addEventListener('click',()=>lanDialog.close());

function renderLanRecovery(result){
  const area=$('#planning-result');area.hidden=false;area.replaceChildren();
  area.append(node('h2','',result.verified?'Mudança confirmada no mesmo equipamento':'Mudança aguardando verificação'));
  area.append(node('p','muted',result.message||'Endereço LAN, DHCP e reservas serão conferidos sem reenviar o comando.'));
  if(result.proposed)displayValues(area,[{label:'Novo gateway',value:result.proposed.base},{label:'Máscara',value:result.proposed.mask},{label:'DHCP',value:`${result.proposed.start} a ${result.proposed.end}`}]);
  if(result.recovery?.length){const list=node('ol');for(const text of result.recovery)list.append(node('li','',text));area.append(list);}
  if(!result.verified){const verify=node('button','primary','Verificar novo endereço');verify.type='button';verify.addEventListener('click',async()=>{verify.disabled=true;try{const response=await api('/api/network/lan-verify',{});renderLanRecovery(response);if(response.verified){window.pendingLanRecovery=false;await showDashboard(await api('/api/session'));setPage('planning');}}catch(error){message(error.message,true);}finally{verify.disabled=false;}});area.append(verify);}
}

window.networkActions={
  async loadLanPlanning(reset=false){
    const status=$('#planning-current');
    try{
      const state=await api('/api/network/lan-state');
      if(state.pending){window.pendingLanRecovery=true;status.textContent='Confirme a mudança anterior antes de editar outros parâmetros.';renderLanRecovery({...state,verified:false});for(const input of lanForm.querySelectorAll('input,button'))input.disabled=true;return;}
      window.pendingLanRecovery=false;for(const input of lanForm.querySelectorAll('input,button'))input.disabled=false;
      const {config}=await api('/api/dhcp');status.textContent=`Atual: ${config.lan_ip} · ${config.mask} · DHCP ${config.start} a ${config.end}`;
      if(reset||!$('#lan-new-ip').value){$('#lan-new-ip').value=config.lan_ip;$('#lan-new-mask').value=config.mask;$('#lan-new-start').value=config.start;$('#lan-new-end').value=config.end;lanReviewed=null;}
    }catch(error){status.textContent=error.message;}
  },
  async previewLan(event){
    event.preventDefault();if(lanBusy)return;const button=event.submitter,area=$('#planning-result');button.disabled=true;area.hidden=false;area.replaceChildren(node('p','muted','Conferindo endereço, pools, reservas e identidade do equipamento…'));
    try{
      const submitted=lanBody(),data=await api('/api/network/lan-preview',submitted);lanReviewed={data,submitted};
      area.replaceChildren(node('h2','',data.changed?'Prévia da alteração':'Nenhuma mudança proposta'));
      displayValues(area,[{label:'Rede',value:data.proposed.network},{label:'Gateway',value:data.proposed.ip},{label:'DHCP',value:`${data.proposed.start} a ${data.proposed.end}`}]);
      for(const text of data.blockers)area.append(node('p','network-warning',text));for(const text of data.warnings)area.append(node('p','muted',text));
      for(const row of data.reservations.filter(row=>row.changed))area.append(node('p','muted',`${row.mac.toUpperCase()}: ${row.old_ip} → ${row.ip}`));
      const recovery=node('ol');for(const text of data.recovery)recovery.append(node('li','',text));area.append(node('h3','','Recuperação de acesso'),recovery);
      const backup=node('button','secondary','Baixar backup de nomes e reservas');backup.type='button';backup.addEventListener('click',async()=>{try{downloadNetwork(await api('/api/maintenance/export'),'backup-antes-mudanca-lan.json');}catch(error){message(error.message,true);}});area.append(backup);
      if(data.apply_available&&data.changed){const apply=node('button','danger','Revisar mudança de LAN');apply.id='lan-apply-button';apply.type='button';apply.addEventListener('click',()=>{if(!lanReviewed)return;$('#lan-confirm-summary').textContent=`Gateway ${data.current.lan_ip} → ${data.proposed.ip}, máscara ${data.proposed.mask}. DHCP ${data.proposed.start} a ${data.proposed.end}. ${data.reservations.filter(row=>row.changed).length} reserva(s) serão migradas.`;$('#lan-confirm-ip').value='';$('#lan-confirm-phrase').value='';lanDialog.showModal();});area.append(apply);}
    }catch(error){lanReviewed=null;area.replaceChildren(node('p','network-warning',error.message));}finally{button.disabled=false;}
  }
};
$('#lan-confirm-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!lanReviewed||lanBusy)return;
  if($('#lan-confirm-ip').value.trim()!==lanReviewed.data.proposed.ip||$('#lan-confirm-phrase').value!=='ALTERAR LAN'){message('Confirme o novo IP e digite ALTERAR LAN.',true);return;}
  lanBusy=true;const button=event.submitter;button.disabled=true;
  try{
    const result=await api('/api/network/lan-apply',{...lanReviewed.submitted,expected:lanReviewed.data.expected,confirm:'ALTERAR LAN',confirm_ip:$('#lan-confirm-ip').value.trim()});
    lanDialog.close();clearInterval(deviceTimer);window.pendingLanRecovery=!result.verified;renderLanRecovery(result);
    if(result.verified){await showDashboard(await api('/api/session'));setPage('planning');}
  }catch(error){message(error.message,true);await window.networkActions.loadLanPlanning();}finally{lanBusy=false;button.disabled=false;}
});

function attachPasswordForm(card,network){
  const members=network.affected_ssids||[{id:network.id,ssid:network.ssid,band:''}];
  card.append(node('p','footnote','Grupo afetado: '+members.map(row=>`${row.ssid} · ${row.band}`).join('; ')));
  const details=node('details','password-settings'),summary=node('summary','','Alterar senha Wi-Fi');details.append(summary);
  if(!network.password_writable){details.append(node('p','muted','Este perfil não fornece confirmação de senha por releitura ou o SSID é protegido. Nenhuma chave atual é exibida.'));card.append(details);return;}
  const form=node('form','local-record-form'),password=node('input'),confirmation=node('input');
  for(const [input,label] of [[password,'Nova senha'],[confirmation,'Repita a nova senha']]){const wrapper=node('label','',label);input.type='password';input.autocomplete='new-password';input.minLength=8;input.maxLength=63;input.required=true;wrapper.append(input);form.append(wrapper);}
  form.append(node('p','footnote','Use 8–63 caracteres ASCII, sem espaços, com maiúsculas, minúsculas, números e símbolos. Clientes precisarão se reconectar.'));
  const button=node('button','danger','Revisar nova senha');button.type='submit';form.append(button);details.append(form);card.append(details);
  form.addEventListener('submit',async event=>{event.preventDefault();if(password.value!==confirmation.value){message('As senhas não coincidem.',true);return;}if(!confirm(`Alterar a senha de ${members.map(row=>`${row.ssid} (${row.band})`).join(', ')}? Clientes precisarão usar a nova chave. Mantenha acesso por cabo ou por outro SSID.`))return;button.disabled=true;try{await api('/api/wifi/password',{id:network.id,password:password.value,password_confirmation:confirmation.value,expected:network.password_expected,confirm:'WIFI'});message('Nova senha confirmada por releitura, sem registrar a chave.');await loadWifiSecurity();}catch(error){message(error.message,true);}finally{password.value=confirmation.value='';button.disabled=false;}});
}
function openLanRecovery(){if(window.pendingLanRecovery)setPage('planning');}
document.addEventListener('lan-recovery',openLanRecovery);openLanRecovery();

function attachRadioPreview(card,radio){
  const details=node('details'),summary=node('summary','','Planejar canal e largura');details.append(summary);card.append(details);
  if(!radio.channel_preview_available){details.append(node('p','muted','Opções de canal e largura indisponíveis para este hardware, firmware, país ou modo.'));return;}
  details.append(node('p','footnote','Prévia sem alterar o roteador. A gravação depende da conferência das ações auxiliares do firmware.'));
  const form=node('form'),width=node('select'),channel=node('select'),result=node('div');
  width.required=channel.required=true;
  for(const [input,label] of [[width,'Largura proposta'],[channel,'Canal proposto']]){const wrapper=node('label','',label);wrapper.append(input);form.append(wrapper);}
  for(const row of radio.channel_options){const option=node('option','',row.label);option.value=row.value;width.append(option);}width.value=radio.width_code;
  function updateChannels(){const previous=channel.value;channel.replaceChildren();const placeholder=node('option','','Selecione o canal ou modo automático');placeholder.value='';channel.append(placeholder);for(const row of radio.channel_options.find(row=>row.value===width.value)?.channels||[]){const option=node('option','',row.label);option.value=row.value;channel.append(option);}channel.value=Array.from(channel.options).some(row=>row.value===previous)?previous:'';result.replaceChildren();}
  updateChannels();if(!radio.auto_channel)channel.value=String(radio.channel);
  width.addEventListener('change',updateChannels);channel.addEventListener('change',()=>result.replaceChildren());
  const button=node('button','secondary','Conferir prévia');button.type='submit';form.append(button);details.append(form,result);
  form.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;result.replaceChildren();try{const data=await api('/api/wifi/radios/preview',{id:radio.id,expected:radio.expected,width_code:width.value,channel:channel.value});result.append(node('p','',`${data.band} · ${data.width_label} · ${data.channel_label}`));for(const warning of data.warnings)result.append(node('p','footnote',warning));}catch(error){result.append(node('p','network-warning',error.message));}finally{button.disabled=false;}});
}

Object.assign(pageLabels,{'wifi-lifecycle':'Gerenciar redes Wi-Fi'});
addNetworkPage('wifi-lifecycle','＋ Gerenciar redes','#nav-wifi',`<div class="heading"><div><div class="eyebrow">REDES ADICIONAIS</div><h1>Gerenciar redes Wi-Fi</h1><p>Crie redes protegidas e gerencie a remoção de SSIDs adicionais.</p></div><div class="actions"><button id="ssid-refresh" type="button" class="secondary">Atualizar</button><button id="ssid-create" type="button" class="primary" disabled>Nova rede</button></div></div><p id="ssid-status" role="status" class="muted"></p><div id="ssid-capacity" class="panel"></div><div id="ssid-pending" class="capability-grid"></div><div id="ssid-networks" class="capability-grid"></div><p class="footnote">Uma rede nova fica desativada e oculta até você ativá-la em Redes Wi-Fi. A criação usa WPA2/AES e WPS desativado, com confirmação por releitura. Nome Convidados não comprova isolamento. Redes principais, reservadas e dependências de cobertura são protegidas.</p>`);
const ssidDialog=node('dialog','device-dialog');ssidDialog.innerHTML=`<h2 id="ssid-dialog-title">Nova rede Wi-Fi</h2><p class="muted">A operação mantém a rede desativada. Se houver falha, use a recuperação; não repita a criação.</p><form id="ssid-form"><label>Nome da rede<input id="ssid-name" required maxlength="32" autocomplete="off"></label><label>Banda<select id="ssid-band"><option value="2G">2,4 GHz</option><option value="5G">5 GHz</option></select></label><label>Máximo de clientes<input id="ssid-maximum" type="number" min="1" max="64" value="32" required></label><label>Nova senha<input id="ssid-password" type="password" required minlength="8" maxlength="63" autocomplete="new-password"></label><label>Repita a senha<input id="ssid-confirm-password" type="password" required minlength="8" maxlength="63" autocomplete="new-password"></label><p class="footnote">8–63 caracteres ASCII sem espaços, com maiúsculas, minúsculas, números e símbolos.</p><div class="actions"><button id="ssid-submit" type="submit" class="primary">Criar rede desativada</button><button id="ssid-cancel" type="button" class="secondary">Cancelar</button></div></form>`;document.body.append(ssidDialog);
let lifecycleState=null,ssidOperation=null;
function clearSsidSecrets(){$('#ssid-password').value=$('#ssid-confirm-password').value='';}
ssidDialog.addEventListener('close',clearSsidSecrets);$('#ssid-cancel').addEventListener('click',()=>ssidDialog.close());
function openSsidForm(action,row=null){
  if(!lifecycleState)return;ssidOperation={action,id:row?.id,expected:lifecycleState.expected};
  const recovery=action==='resume';$('#ssid-dialog-title').textContent=recovery?'Recuperar rede desativada':'Nova rede Wi-Fi';$('#ssid-submit').textContent=recovery?'Configurar e conferir segurança':'Criar rede desativada';
  $('#ssid-name').value=row?.ssid||'';$('#ssid-name').disabled=recovery;$('#ssid-band').disabled=recovery;$('#ssid-maximum').disabled=recovery;$('#ssid-maximum').value=row?.max_clients||32;
  for(const option of $('#ssid-band').options)option.disabled=!recovery&&!lifecycleState.bands.find(band=>band.id===option.value)?.create_available;
  $('#ssid-band').value=row?.band||lifecycleState.bands.find(band=>band.create_available)?.id||'2G';clearSsidSecrets();ssidDialog.showModal();
}
$('#ssid-create').addEventListener('click',()=>openSsidForm('create'));$('#ssid-refresh').addEventListener('click',loadWifiLifecycle);
async function loadWifiLifecycle(){
  const status=$('#ssid-status'),area=$('#ssid-networks'),pending=$('#ssid-pending'),create=$('#ssid-create');create.disabled=true;status.textContent='Conferindo redes e capacidade do firmware…';area.replaceChildren();pending.replaceChildren();
  try{lifecycleState=await api('/api/wifi/lifecycle');status.textContent=lifecycleState.profile_supported?'Criação e exclusão condicionadas aos campos reconhecidos e à capacidade atual.':'Perfil não validado para criar ou excluir redes.';$('#ssid-capacity').replaceChildren();displayValues($('#ssid-capacity'),lifecycleState.bands.map(band=>({label:band.id==='2G'?'2,4 GHz':'5 GHz',value:band.occupied===null?'Capacidade não reconhecida':`${band.occupied} de ${band.capacity??'?'} posições ocupadas, incluindo redes reservadas`})));create.disabled=!lifecycleState.bands.some(band=>band.create_available);
    for(const item of lifecycleState.pending){const card=node('article','panel config-panel');card.append(node('h2','',item.ssid),node('p','network-warning','Criação pendente. Mantenha esta rede desativada até confirmar sua segurança.'));const row=lifecycleState.records.find(row=>row.id===item.id||(!item.id&&row.ssid===item.ssid&&row.band===item.band));const button=node('button','secondary','Recuperar segurança');button.type='button';button.disabled=!row||row.enabled||row.protected;button.addEventListener('click',()=>openSsidForm('resume',row));card.append(button);if(!row)card.append(node('p','muted','O objeto não foi localizado; confira a criação no Huawei sem repetir o envio.'));pending.append(card);}
    for(const row of lifecycleState.records){const card=node('article','panel config-panel');card.append(node('h2','',row.ssid));displayValues(card,[{label:'Banda',value:row.band==='2G'?'2,4 GHz':'5 GHz'},{label:'Estado',value:row.enabled?'Ativada':'Desativada'},{label:'Divulgação',value:row.broadcast?'Visível':'Oculta'},{label:'Limite de clientes',value:row.max_clients}]);const button=node('button','danger','Excluir rede');button.type='button';button.disabled=!row.delete_available;card.append(button);if(row.delete_reason)card.append(node('p','footnote',row.delete_reason));button.addEventListener('click',async()=>{const name=prompt(`Digite o nome da rede para excluir: ${row.ssid}`);if(name!==row.ssid)return;if(!confirm(`Excluir ${row.ssid}? Os clientes desta rede perderão a conexão.${row.guest_reference?' A referência de convidados também será removida.':''} Mantenha acesso por cabo ou outra rede. Não há restauração automática.`))return;button.disabled=true;try{await api('/api/wifi/lifecycle',{action:'delete',id:row.id,expected:lifecycleState.expected,confirm:'EXCLUIR REDE',confirm_ssid:name,disconnect_clients:true,clear_guest:!!row.guest_reference});message('Exclusão confirmada pelo Huawei.');await loadWifiLifecycle();}catch(error){message(error.message,true);await loadWifiLifecycle();}finally{button.disabled=!row.delete_available;}});area.append(card);}
  }catch(error){lifecycleState=null;status.textContent=error.message;}
}
$('#ssid-form').addEventListener('submit',async event=>{event.preventDefault();if(!ssidOperation)return;const button=$('#ssid-submit');button.disabled=true;try{const result=await api('/api/wifi/lifecycle',{...ssidOperation,ssid:$('#ssid-name').value.trim(),band:$('#ssid-band').value,max_clients:Number($('#ssid-maximum').value),password:$('#ssid-password').value,password_confirmation:$('#ssid-confirm-password').value,confirm:ssidOperation.action==='create'?'CRIAR REDE':'RECUPERAR REDE'});message(result.message,!result.verified);ssidDialog.close();await loadWifiLifecycle();}catch(error){message(error.message,true);}finally{clearSsidSecrets();button.disabled=false;}});
window.networkPageLoaders['wifi-lifecycle']=loadWifiLifecycle;
const integrationReportButton=node('button','secondary','Exportar diagnóstico de integração');integrationReportButton.type='button';$('#inventory-export').parentElement.append(integrationReportButton);integrationReportButton.addEventListener('click',async()=>{integrationReportButton.disabled=true;try{downloadNetwork(await api('/api/maintenance/integration-report'),'gateway-integration-report.json');}catch(error){message(error.message,true);}finally{integrationReportButton.disabled=false;}});
