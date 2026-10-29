// Shared by the browser and navigation regression tests.
(function(root){
  const groups=[
    {id:'devices',label:'Dispositivos',icon:'◉',tabs:[
      {label:'Clientes',page:'devices'}, {label:'Inventário e topologia',page:'inventory'}]},
    {id:'wifi',label:'Wi-Fi',icon:'⌁',tabs:[
      {label:'Redes',page:'wifi',pages:['wifi','wifi-security','wifi-lifecycle']},
      {label:'Rádios e cobertura',page:'wifi-radios'}]},
    {id:'lan',label:'LAN e IPs',icon:'◫',tabs:[
      {label:'DHCP e reservas',page:'dhcp',pages:['dhcp','reservations']},
      {label:'DNS',page:'dns',pages:['dns','static-dns']},
      {label:'IPv6',page:'ipv6'}, {label:'Endereço LAN',page:'planning'},
      {label:'Isolamento de portas',page:'port-isolation'}]},
    {id:'monitoring',label:'Monitoramento',icon:'≡',tabs:[
      {label:'Logs',page:'logs'}, {label:'Histórico',page:'history'}, {label:'Diagnóstico',page:'diagnostic'}]},
    {id:'notifications',label:'Notificações',icon:'♧',tabs:[{label:'Integrações',page:'notifications'}]},
    {id:'maintenance',label:'Manutenção',icon:'⚙',tabs:[
      {label:'Backup',page:'maintenance'}, {label:'Firmware',page:'firmware'},
      {label:'Compatibilidade',page:'capabilities'}, {label:'Reiniciar',page:'reboot'}]}
  ];
  function locate(page){
    for(const group of groups)for(const tab of group.tabs){
      const pages=tab.pages||[tab.page];
      if(pages.includes(page))return {group,tab,pages};
    }
    return null;
  }
  function wifiSelection(rows,id){return rows.some(row=>row.id===id)?id:rows[0]?.id||'';}
  function sortWifiNetworks(rows){
    const rank=row=>row.guest?3:row.primary&&row.band==='2G'?0:row.primary&&row.band==='5G'?1:2;
    return rows.map((row,index)=>({row,index})).sort((a,b)=>rank(a.row)-rank(b.row)||a.index-b.index).map(item=>item.row);
  }
  function matchesNetwork(card,selected){return !!selected&&(card.id===selected||(card.members||[]).includes(selected));}
  const model={groups,locate,wifiSelection,matchesNetwork,sortWifiNetworks};
  if(typeof module!=='undefined'&&module.exports)module.exports=model;
  else root.navigationModel=model;
})(typeof window==='undefined'?{}:window);
