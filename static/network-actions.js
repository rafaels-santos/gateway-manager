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
