# Notas de integração: Huawei EG8145X6-10

Observações em modo somente leitura no firmware V5R024C10S106. Nenhuma configuração foi alterada.

- O login usa POST em `/asp/GetRandCount.asp` para obter um token e POST em `/login.cgi` com `UserName`, `PassWord` codificada em Base64, `Language` e `x.X_HW_Token`. Base64 não protege a senha; HTTP deve ser usado apenas em rede confiável.
- A interface DHCP está em `/html/bbsp/dhcpservercfg/dhcp2.asp`. O formulário expõe ativação do DHCP, início e fim do intervalo, duração e DNS primário e secundário. Há opções adicionais que precisam ser preservadas.
- Reservas estão em `/html/bbsp/dhcpstatic/dhcpstatic.asp`. O firmware usa `add.cgi` para adicionar, `set.cgi` para editar e `del.cgi` para excluir entradas `InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress`, com campos `x.Yiaddr` e `x.Chaddr` e token da página.
- Os detalhes de leitura, tratamento de sessão e token, validação das respostas e renomeação de clientes ainda precisam ser implementados e testados. Não se deve supor que a reserva DHCP altere o nome do dispositivo.
- O equipamento pode encerrar uma sessão existente quando outro usuário entra. Testes de autenticação e escrita devem ser isolados e as alterações reais não devem ser feitas sem autorização explícita.


## Logs e isolamento (inspeção de leitura)

- User Logs: `/html/ssmp/userlog/logview.asp`, texto codificado em atribuição a `logarea`. Categorias do filtro nativo: todos, Config-Log, Shell-Log, Alarm-Log. Outros tipos (ex.: Run-Log) continuam em Todos.
- AP Logs: `/html/ssmp/aplog/aplogview.asp`, variável `ApLogInfoText`. O painel observado não oferece filtro de categorias; as linhas têm um nível (`[Notice]`) seguido da mensagem, incluindo eventos ACCESS/BBSP e portas. O app acrescenta filtros locais de severidade e busca nos dois tipos. Download `.log` preserva o texto completo devolvido pela última consulta, incluindo cabeçalho, sem as simplificações ou filtros da tela; não é um arquivo de diagnóstico expandido do firmware.
- A página Wi-Fi MAC Filtering descreve filtragem de tráfego. Existência de regra não demonstra bloqueio de associação, desassociação imediata ou isolamento completo da LAN. Seria necessário testar reconexão e tráfego entre clientes, nas bandas relevantes, com um cliente explicitamente escolhido.
- Na página básica WLAN observada, `staIsolationFlag=0` e `isShowGuestWifiPage=0`; o código prevê isolamento por SSID, mas o controle não está exposto nessa versão/conta. As entradas de isolamento retornadas estavam em 0. Nomear uma rede Convidados não demonstra segregação.
- Para garantir separação de um grupo de clientes, é necessária rede/SSID em segmento separado com política de firewall (incluindo IPv6) ou equipamento que exponha isolamento. Isolamento apenas entre clientes do mesmo AP/SSID não deve ser tratado como garantia de bloqueio para toda a LAN. Não foi aplicada nenhuma dessas configurações.
