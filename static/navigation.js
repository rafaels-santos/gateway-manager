// Compose existing, independently confirmed forms into task-oriented workspaces.
// Navigation never submits a router configuration.
(()=>{
  const {groups,locate,wifiSelection,matchesNetwork}=window.navigationModel;
  const nav=$('.sidebar nav'),remembered={},main=$('.content');
  let wifiRows=[],selectedWifi='',wifiGeneration=0;
  const header=node('div','workspace-header'),tabs=node('div','workspace-tabs');
  tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Seções da área');header.append(tabs);
  const wifiBar=node('div','wifi-workspace');wifiBar.hidden=true;
  const wifiTitle=node('div','workspace-heading');wifiTitle.append(node('h1','','Wi-Fi'),node('p','muted','Selecione uma rede para configurar nome, acesso, segurança e senha.'));
  const wifiTools=node('div','actions wifi-workspace-tools'),refreshWifi=node('button','secondary','Atualizar redes');refreshWifi.type='button';
  refreshWifi.addEventListener('click',async()=>{refreshWifi.disabled=true;try{await window.appNavigation.refreshWifi();}finally{refreshWifi.disabled=false;}});
  wifiTools.append(refreshWifi,$('#ssid-create'));wifiTitle.append(wifiTools);
  for(const id of ['refresh-wifi','security-refresh','ssid-refresh'])$('#'+id).hidden=true;
  const capacity=node('details','wifi-capacity'),capacityTitle=node('summary','','Capacidade das bandas');capacity.append(capacityTitle);
  $('#ssid-capacity').before(capacity);capacity.append($('#ssid-capacity'));
  const networks=node('div','wifi-network-tabs');networks.setAttribute('role','tablist');networks.setAttribute('aria-label','Redes Wi-Fi');
  const networkStatus=node('p','muted');networkStatus.setAttribute('role','status');
  wifiBar.append(wifiTitle,networks,networkStatus);header.append(wifiBar);main.insertBefore(header,$('.page'));
  nav.replaceChildren();nav.classList.add('compact-navigation');
  for(const group of groups){
    const button=node('button','nav-item');button.type='button';button.dataset.group=group.id;
    const icon=node('span','',group.icon);icon.setAttribute('aria-hidden','true');button.append(icon,document.createTextNode(group.label));
    button.addEventListener('click',()=>setPage(remembered[group.id]||group.tabs[0].page));nav.append(button);
  }
  function keyboardTabs(container){
    container.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      const buttons=Array.from(container.querySelectorAll('[role="tab"]'));
      const index=buttons.indexOf(event.target);if(index<0||!buttons.length)return;
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      buttons[next].focus();buttons[next].click();
    });
  }
  keyboardTabs(tabs);keyboardTabs(networks);
  function filterWifi(){
    for(const selector of ['#wifi-configs','#security-networks','#ssid-networks']){
      const area=$(selector);
      for(const card of area.children){
        if(!card.dataset.wifiId)continue;
        card.hidden=!matchesNetwork({id:card.dataset.wifiId,members:(card.dataset.wifiMembers||'').split('|')},selectedWifi);
      }
    }
    networkStatus.textContent=wifiRows.length?'Os ajustes abaixo pertencem à rede selecionada. Segurança compartilhada entre bandas é indicada no próprio formulário.':'Nenhuma rede disponível nesta leitura. Use Atualizar para tentar novamente.';
  }
  function renderWifiTabs(){
    networks.replaceChildren();selectedWifi=wifiSelection(wifiRows,selectedWifi);
    for(const row of wifiRows){
      const button=node('button','wifi-network-tab');button.type='button';button.setAttribute('role','tab');
      button.id='wifi-network-'+row.id.split('.').pop();button.setAttribute('aria-controls','page-wifi page-wifi-security page-wifi-lifecycle');
      button.append(node('strong','',row.ssid),node('small','',`${row.network}${row.enabled?'':' · Desativada'}`));
      const active=row.id===selectedWifi;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;button.classList.toggle('active',active);
      button.addEventListener('click',()=>{selectedWifi=row.id;renderWifiTabs();document.getElementById(button.id)?.focus();});networks.append(button);
    }
    filterWifi();
  }
  const observer=new MutationObserver(filterWifi);
  for(const selector of ['#wifi-configs','#security-networks','#ssid-networks'])observer.observe($(selector),{childList:true});
  // Pending creations remain visible across networks: hiding recovery would be unsafe.
  function update(page){
    const target=locate(page);if(!target)return;
    remembered[target.group.id]=target.tab.page;
    document.querySelectorAll('.page').forEach(el=>el.hidden=!target.pages.includes(el.id.slice(5)));
    document.querySelectorAll('.nav-item').forEach(button=>{
      const active=button.dataset.group===target.group.id;button.classList.toggle('active',active);
      if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
    $('#breadcrumb').textContent=target.group.label+(target.group.tabs.length>1?' / '+target.tab.label:'');
    if(page==='devices'&&deviceView==='blocked')$('#breadcrumb').textContent+=' / Bloqueados';
    tabs.replaceChildren();tabs.hidden=target.group.tabs.length===1;
    for(const tab of target.group.tabs){
      const button=node('button','workspace-tab',tab.label);button.type='button';button.id='workspace-tab-'+tab.page;button.setAttribute('role','tab');
      const active=tab===target.tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
      button.setAttribute('aria-controls',(tab.pages||[tab.page]).map(id=>'page-'+id).join(' '));
      button.addEventListener('click',()=>{setPage(tab.page);document.getElementById(button.id)?.focus();});tabs.append(button);
    }
    for(const id of target.pages){const panel=$('#page-'+id);panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','workspace-tab-'+target.tab.page);}
    wifiBar.hidden=target.tab.page!=='wifi';filterWifi();
  }
  function loadRelated(page){
    const target=locate(page);if(!target)return;
    const loaders={wifi:loadWifi,'wifi-security':loadWifiSecurity,'wifi-lifecycle':loadWifiLifecycle,dhcp:()=>loadNetworkConfig('dhcp'),reservations:refreshReservations,dns:()=>loadNetworkConfig('dns'),'static-dns':loadStaticDns};
    for(const related of target.pages)if(related!==page&&loaders[related])Promise.resolve(loaders[related]()).catch(error=>message(error.message,true));
  }
  window.appNavigation={update,loadRelated,
    wifiNetworks(rows){wifiRows=rows;renderWifiTabs();},
    async refreshWifiRelated(){await Promise.all([loadWifiSecurity(),loadWifiLifecycle()]);},
    async refreshWifi(){const generation=++wifiGeneration;await loadWifi();if(generation===wifiGeneration)await Promise.all([loadWifiSecurity(),loadWifiLifecycle()]);}
  };
  // Keep individual refresh controls and confirmations, while reducing repeated headings.
  for(const [id,title] of [['wifi','Configurações da rede'],['wifi-security','Segurança e senha'],['wifi-lifecycle','Gerenciamento da rede']]){
    const heading=$('#page-'+id+' .heading h1');heading.replaceWith(node('h2','',title));$('#page-'+id).classList.add('wifi-composed-page');
  }
  $('#page-dhcp').classList.add('composed-first');$('#page-reservations').classList.add('composed-next');
  $('#page-dns').classList.add('composed-first');$('#page-static-dns').classList.add('composed-next');
  const badge=node('span','release-preview','Preparação 1.0');$('.sidebar .brand small').append(document.createElement('br'),badge);
  $('#logout').addEventListener('click',()=>{wifiRows=[];selectedWifi='';wifiGeneration++;renderWifiTabs();for(const key of Object.keys(remembered))delete remembered[key];});
  update(document.querySelector('.page:not([hidden])')?.id.slice(5)||'devices');
})();
