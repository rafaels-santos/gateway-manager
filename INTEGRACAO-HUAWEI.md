# Notas de integração: Huawei EG8145X6-10

Observações em modo somente leitura no firmware V5R024C10S106. Nenhuma configuração foi alterada.

- O login usa POST em `/asp/GetRandCount.asp` para obter um token e POST em `/login.cgi` com `UserName`, `PassWord` codificada em Base64, `Language` e `x.X_HW_Token`. Base64 não protege a senha; HTTP deve ser usado apenas em rede confiável.
- A interface DHCP está em `/html/bbsp/dhcpservercfg/dhcp2.asp`. O formulário expõe ativação do DHCP, início e fim do intervalo, duração e DNS primário e secundário. Há opções adicionais que precisam ser preservadas.
- Reservas estão em `/html/bbsp/dhcpstatic/dhcpstatic.asp`. O firmware usa `add.cgi` para adicionar, `set.cgi` para editar e `del.cgi` para excluir entradas `InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress`, com campos `x.Yiaddr` e `x.Chaddr` e token da página.
- A criação, edição e remoção de reservas são implementadas com token e releitura antes de reportar sucesso. A remoção é acionada individualmente e exige confirmação na tela. Não se deve supor que a reserva DHCP altere o nome do dispositivo; a exclusão ainda precisa ser conferida com o firmware real antes de uso operacional.
- O equipamento pode encerrar uma sessão existente quando outro usuário entra. Testes de autenticação e escrita devem ser isolados e as alterações reais não devem ser feitas sem autorização explícita.


## Logs e isolamento (inspeção de leitura)

- User Logs: `/html/ssmp/userlog/logview.asp`, texto codificado em atribuição a `logarea`. Categorias do filtro nativo: todos, Config-Log, Shell-Log, Alarm-Log. Outros tipos (ex.: Run-Log) continuam em Todos.
- AP Logs: `/html/ssmp/aplog/aplogview.asp`, variável `ApLogInfoText`. O painel observado não oferece filtro de categorias; as linhas têm um nível (`[Notice]`) seguido da mensagem, incluindo eventos ACCESS/BBSP e portas. O app acrescenta filtros locais de severidade e busca nos dois tipos. Download `.log` preserva o texto completo devolvido pela última consulta, incluindo cabeçalho, sem as simplificações ou filtros da tela; não é um arquivo de diagnóstico expandido do firmware.
- A página Wi-Fi MAC Filtering descreve filtragem de tráfego. Existência de regra não demonstra bloqueio de associação, desassociação imediata ou isolamento completo da LAN. Seria necessário testar reconexão e tráfego entre clientes, nas bandas relevantes, com um cliente explicitamente escolhido.
- Na página básica WLAN observada, `staIsolationFlag=0` e `isShowGuestWifiPage=0`; o código prevê isolamento por SSID, mas o controle não está exposto nessa versão/conta. As entradas de isolamento retornadas estavam em 0. Nomear uma rede Convidados não demonstra segregação.
- Para garantir separação de um grupo de clientes, é necessária rede/SSID em segmento separado com política de firewall (incluindo IPv6) ou equipamento que exponha isolamento. Isolamento apenas entre clientes do mesmo AP/SSID não deve ser tratado como garantia de bloqueio para toda a LAN. Não foi aplicada nenhuma dessas configurações.

## Estruturas reconferidas em 28/10/2026

- Eth Port: `/html/amp/ethinfo/ethinfo.asp`; `GEInfo(domain,Mode,Speed,Status,OptEthMode)` e `LANStats` trazem somente propriedades LAN selecionadas pelo leitor. Contadores altos/baixos são combinados em 64 bits.
- Layer 2/3: `/html/bbsp/layer3/layer3.asp`, `stLayer3Enable`. As quatro portas lidas estavam em Layer 3; Port Isolation apresentava controles desabilitados.
- DHCPv6 Information: `/html/bbsp/dhcpv6info/dhcpv6info.asp`, `DhcpInfoClass(domain,DUID,IPAddress,PrefixLen,Duration)`. A tabela observada estava vazia e não tinha coluna MAC. Não converter DUID em MAC.
- DNS local: a página referencia `/html/bbsp/common/dnshostslist.asp`, que usa `DnsHostsItemClass(domain,IPAddress,DomainName)`. CRUD usa exclusivamente `InternetGatewayDevice.X_HW_DNS.HOSTS`, propriedades `IPAddress` e `DomainName`; não utiliza SearList ou o objeto global de políticas DNS.
- IPv6 estático: `stConfig(domain,InterfaceID,Chaddr)`, base `InternetGatewayDevice.LANDevice.1.X_HW_DHCPv6.Server.StaticAllocation`; `RaConfigInfoClass` na própria página permite verificar ManagedFlag. A rede lida usa SLAAC; o app mantém a edição indisponível nesse estado.
- DNSv6: `IPv6DNSConfigClass(domain,DomainName,IPv6DNSConfigType,IPv6DNSWANConnection,IPv6DNSServers)`; alterações limitadas a `IPv6DNSConfigType=Static` e `IPv6DNSServers` em `LANDevice.1.X_HW_IPv6Config`. A propriedade de seleção externa é preservada.
- SSID: campo `y.X_HW_AssociateNum` e faixa 1–64 conferidos. Perfis pessoais usam BeaconType e propriedades de autenticação/criptografia correspondentes; a operação implementada preserva PSK e usa AES. Nenhuma chave atual é retornada ao navegador.
- Rádio: `/html/amp/wlanadv/wlanadvance_api.asp`, construtor `stWlanWifi`; para BREBG2 foram observadas potências 100/80/60/40/20. O app grava somente `TransmitPower` no SSID primário da banda. As opções de canal/largura dependem de JavaScript, país, modo e banda, portanto continuam somente leitura.
- EasyMesh: `var staInfo` contém texto JSON com `mac_address`, `station_info`, `station_mac`, `child_devices` e `link`. O parser usa JSON, sem executar JavaScript; mantém Station separado de Controller/Agent.

Estas notas registram inspeção de código/controles e testes simulados. Nenhuma operação de configuração descrita foi aplicada no roteador nesta execução.
