# Plano de gerenciamento da rede interna

Inspeção em 28/10/2026 · Huawei EG8145X6-10 · HW 343D.D · SW V5R024C10S106.

## Estado consolidado — 29/10/2026

As seções de continuação abaixo registram a evolução; suas pendências históricas não substituem este estado atual.

| Área | Implementação atual | Aceite e limitações |
| --- | --- | --- |
| Clientes e inventário | Online/offline/bloqueados, identidade por MAC, categorias, filtros, portas, topologia, concessões IPv6 e exportação sem segredos | As leituras dependem do perfil e dos formatos reconhecidos; DUID não é convertido em MAC |
| LAN e nomes | DHCP/DNS IPv4, reservas IPv4/IPv6, DNS local e DNSv6; migração conjunta LAN/DHCP com prévia e recuperação persistente | Reservas IPv6 exigem DHCPv6 gerenciado; SLAAC não é alterado automaticamente. Migração real ainda requer janela de teste |
| Wi-Fi | SSIDs, autenticação e senha agrupada, potência, canal/largura, criação desativada com recuperação e remoção em duas etapas | Protege redes principais/backhaul e dependências. Canal/largura exige contrato e perfil reconhecidos; não muda país nem Band Steering |
| Segurança | Política MAC com confirmação do conjunto afetado, desbloqueio, leitura de isolamento e modos das portas | Não promete isolamento completo. Portas observadas em Layer 3 impedem usar Port Isolation; não há conversão automática |
| Monitoramento | User/AP Logs, filtros, download, histórico local, diagnóstico TCP LAN limitado e notificações | Diagnóstico parte do servidor do app. Ping/traceroute nativos, ajustes de roaming, proteção PSK e ACL administrativa continuam expansões a investigar, sem comandos presumidos |
| Operação | Arquivo portátil de identificadores/reservas, firmware somente consulta/download, reinício explícito, Docker multiarch | Não exporta backup bruto da ONT, credenciais ou configurações WAN |

Na revisão autenticada com **Epadmin**, o app leu **599 User Logs e 500 AP Logs**, além das fontes de segurança Wi-Fi, ciclo de vida de SSIDs, DNS local, reservas IPv6, DNSv6 e isolamento. O endereço nativo confirmado de User Log é `/html/ssmp/userlog/logview.asp`; HTTP 404 pode representar indisponibilidade para o perfil. Não se tenta mais um diretório alternativo por adivinhação: apenas links observados no menu podem fornecer outro caminho.

O parser de rádio distingue o registro ativo de `StXHWGlobalConfig` no array nativo do objeto padrão construído no ramo de fallback. Valores realmente conflitantes continuam bloqueando a gravação. A correção não escolhe um valor desejado nem modifica a política do equipamento.

**Validação desta revisão: 135 testes Python e 5 de navegação passaram**, além da sintaxe dos três JavaScripts. Escritas foram exercitadas exclusivamente com gateways simulados. Nenhuma configuração do Huawei foi aplicada durante o desenvolvimento. Aceites reais de associação/bloqueio, tráfego IPv4/IPv6 entre clientes, resolução DNS e migração LAN permanecem separados da conclusão do código, pois dependem de cliente e janela autorizados.

## Objetivo e limites

Usar o Gateway Manager como painel da rede interna: clientes, Wi-Fi, endereçamento, nomes locais, controle de acesso e diagnóstico. A navegação foi reorganizada; a implementação inicial da Fase 1 está registrada abaixo.

A inspeção do roteador foi somente de leitura. Não foram acionados Apply, Save, Start, exclusões, alterações de campos, ativação de filtros, reinícios ou diagnósticos. Não se executou varredura de portas, descoberta ativa de clientes nem teste de bloqueio.

Ficam fora do produto planejado: PPPoE, WAN, credenciais da operadora, VLAN de serviço da operadora, GPON/ONT Authentication, TR-069/ACS, DDNS, NAT, DMZ, encaminhamento de portas, UPnP/ALG de acesso externo, rotas externas, VPN externa, VoIP e atualização de firmware. Notificações externas já existentes continuam como integrações do app; não são configurações de conectividade do roteador.

O objetivo de gerenciamento completo depende das funções que o firmware e o perfil autenticado realmente disponibilizam. A existência de uma página não comprova que uma escrita é permitida ou que uma política isola todo o tráfego.

## Método e grau de evidência

- **Campos lidos:** página aberta, descrição e controles consultados, sem modificações.
- **Menu observado:** a função aparece no menu, mas não foi inspecionada em profundidade.
- **Implementado:** existe código no app; isso não equivale a teste real de todas as operações no roteador.
- A conta usada nesta inspeção expôs mais menus que o perfil de uma sessão anterior. A integração deve detectar capacidades por sessão, não presumir permissões a partir do modelo.
- A sessão terminou ao final da inspeção. Informação de portas/clientes em System Information, concessões DHCPv6 e algumas páginas secundárias permanece para a próxima rodada de leitura.

## Nova organização do menu

| Grupo | Disponível nesta etapa | Expansões planejadas |
| --- | --- | --- |
| Rede interna | Dispositivos, com abas online/offline/bloqueados existentes | Visão geral, portas LAN e topologia |
| Wi-Fi | Redes e SSIDs | Segurança por SSID, rádios, convidados, cobertura/EasyMesh |
| LAN e IPs | DHCP IPv4, Reservas de IP, DNS da LAN | Endereço LAN, IPv6, concessões e nomes DNS locais |
| Segurança | Bloqueios Wi-Fi, atalho para a listagem existente | Isolamento de portas, capacidades de isolamento Wi-Fi, proteção PSK, acesso administrativo pela LAN |
| Monitoramento | Logs, Notificações | Histórico de eventos e diagnósticos internos |
| Manutenção | Importar/exportar identificadores por MAC e reservas DHCP IPv4; reinício | Informações do equipamento e expansão do arquivo portátil para outras funções da LAN |

Apenas destinos funcionais aparecem como itens clicáveis. Não foram criados formulários vazios de funcionalidades futuras. Notificações permanece acima de Reinício. Em telas menores, a navegação permite rolagem horizontal; no desktop, os grupos ficam na lateral com rolagem própria.

O arquivo portátil versão 1 leva identificadores/categorias locais por MAC e reservas DHCP IPv4, sem credenciais, hooks, chaves Wi-Fi, logs ou cópia completa da configuração. A importação exige prévia no gateway de destino, verifica conflitos de endereço e só grava reservas após confirmação; nomes/categorias permanecem locais ao app. Atualizações das funções exportadas devem manter a versão do schema e acrescentar testes de compatibilidade.

## Inventário e lacunas do app

| Função | Evidência no Huawei | Situação no app e proposta |
| --- | --- | --- |
| Clientes e identidade | Listagem já integrada por MAC; informações de LAN, Wi-Fi e estado | Manter identidade global por gateway/MAC. Separar apelido do app, nome informado pelo cliente, nome de regra e nome DNS; não prometer que são o mesmo campo |
| DHCP IPv4 | Página conhecida `/html/bbsp/dhcpservercfg/dhcp2.asp` | Já edita ativação, intervalo e concessão. Inventariar os campos adicionais antes de expandir, preservando opções não editadas |
| Reservas IPv4 | `/html/bbsp/dhcpstatic/dhcpstatic.asp` | Cria/edita reservas, detecta conflitos e agora permite remoção verificada por releitura; verde/Fixo apenas quando reserva efetiva corresponder ao MAC/IP |
| LAN Host | Campos lidos em `/html/bbsp/dhcp/dhcp.asp`: endereço primário, máscara e endereço secundário | Novo formulário futuro. Mudança de IP exige coerência com DHCP e recuperação da conexão; não confundir IP secundário com isolamento de rede |
| DHCPv6 e RA | Campos lidos em `/html/bbsp/lanaddress/lanaddress.asp`: servidor, RA, DHCPv6/SLAAC, DNS da LAN, MTU e ULA | Começar com leitura. Escrita apenas de propriedades da LAN; excluir seleção de WAN, delegação e mudanças no prefixo da operadora |
| Reservas IPv6 | Campos lidos em `/html/bbsp/dhcpstaticaddr/dhcpstaticaddress.asp`: MAC e identificador de interface | Novo recurso condicionado ao modo DHCPv6. O próprio Huawei informa que não tem efeito com atribuição SLAAC |
| Concessões/informação DHCPv6 | Menu DHCPv6 Information observado | Inspecionar página e representação dos clientes antes de implementar; não inferir IPv6 ativo apenas por um indicador de capacidade |
| DNS da LAN | DNS entregue por DHCP já integrado | Manter distinto de DNS usado pelo próprio gateway e das políticas globais de resolução |
| DNS estático | Campos lidos em `/html/bbsp/dnsconfiguration/dnsconfigcommon.asp`: associação Domain Name/IP Address | Aba somente leitura criada para exibir a tabela quando o parser reconhecer cabeçalhos Domain Name/IP Address. Escrita segue pendente até confirmar o objeto TR-069 e excluir os campos DNS template/Search List associados à WAN |
| SSIDs | Campos lidos em `WlanBasic.asp?2G`: nome, ativação, máximo de clientes, divulgação, WMM, autenticação, criptografia, PSK, WPS; menu equivalente de 5 GHz observado | Hoje nome/ativação/divulgação. Expandir limite de clientes e segurança por SSID; confirmar equivalência e restrições de cada banda. Nunca devolver PSK salvo ao navegador |
| Rádios 2,4/5 GHz | Campos avançados consultados em `WlanAdvance.asp`: potência, canal, largura, padrão, Airtime Fairness, DTIM, Beacon, RTS, fragmentação; Band Steering observado em 5 GHz | Começar por leitura e edição de canal/largura/potência com opções retornadas pelo firmware. Preservar domínio regulatório atual, sem expor mudança de país como ajuste comum |
| Convidados e isolamento Wi-Fi | SSID secundário existente; controle de isolamento não exposto na página básica consultada | Expor capacidades reais e aviso de isolamento não confirmado. Nome Convidados, senha diferente ou faixa diferente não comprovam segregação |
| Isolamento de portas | Campos lidos em `/html/bbsp/portinfo/portisolate.asp`: LAN1–LAN4; descrição condiciona a portas Layer 2 | Prioridade de investigação. Começar com leitura do modo da porta. Não converter Layer 2/3 automaticamente; não afirmar que isola Wi-Fi, bandas ou toda a LAN |
| Modo Layer 2/3 | Menu LAN > Layer 2/3 Port observado | Consultar para interpretar Port Isolation. Escrita fica fora do primeiro ciclo por possível impacto nas vinculações de serviços |
| Bloqueio MAC Wi-Fi | Página já integrada; lista, SSID, Device Name, ativação e modo | Melhorar diagnóstico da regra efetiva. Mudanças de ativação devem listar todas as regras afetadas. Ainda exige teste escolhido pelo usuário para confirmar associação/reconexão, não só cadastro |
| Defesa contra quebra de PSK | Campos lidos em `/html/amp/wlanadv/wlanpskprotect.asp`: ativação de WLAN PSK Crack Defense | Recurso futuro condicionado à permissão e ao comportamento documentado do firmware. Não ativado na inspeção |
| Controle de acesso ao equipamento | Precise Device Access Control observado nesta sessão e consultado em sessão anterior (`/html/bbsp/portacl/newacl.asp`) | Considerar somente acesso administrativo pela LAN/SSID. Não alterar regras WAN nem confundir proteção do painel com isolamento entre clientes |
| EasyMesh/Multi-AP | Campos lidos em `/html/amp/wlaninfo/easymeshTopo.asp`: topologia, papel, clientes por banda/porta, limiares RSSI; ativação exige reinício | Primeiro topologia somente de leitura. Depois avaliar roaming. Exigir identificação de AP real; a topologia também lista estações comuns |
| Cobertura Wi-Fi | Campos lidos em `/html/amp/wificovercfg/wifiCover.asp`: APs locais, sincronização por SSID e política de cobertura | Apenas APs pertencentes à rede interna. Começar com leitura; sincronização e Linkturbo ficam para validação posterior. Algumas alterações só vigoram após reinício |
| Diagnóstico interno | Campos lidos em `/html/bbsp/maintenance/diagnosecommon.asp`: ping/traceroute e interface br0 | Futuro teste com alvo privado interno e interface LAN, limites curtos. Não executar diagnóstico de hardware: a página alerta interrupção de serviços. Não testar destinos de internet |
| Logs | User/AP já integrados, com filtros e download | Acrescentar contexto, horário não sincronizado, busca e histórico local. Firewall/Debug/Intrusion aparecem no menu, mas seu conteúdo e pertinência à LAN precisam ser inspecionados |
| Notificações | Implementação do app, independente da interface Huawei | Múltiplos hooks por gateway; adicionar eventos somente quando houver fonte confiável. Sem interpretar falha de coleta como desconexão de todos os clientes |
| Reinício | Código existente no app | Manter separado e explícito; não é restauração de fábrica e não foi executado |

## Plano por fases

### Fase 0 — Navegação e planejamento (esta entrega)

- Agrupar funções existentes pelos seis domínios acima.
- Adicionar atalho Segurança > Bloqueios Wi-Fi sem duplicar estado ou dados.
- Manter indicação da página ativa coerente ao alternar entre o atalho e as abas de clientes.
- Registrar inventário, limites e dependências neste documento.
- Nenhuma nova escrita no gateway e nenhuma alteração de suas configurações.

### Fase 1 — Base de leitura e capacidades

1. Criar uma matriz de capacidades do adaptador por firmware/perfil: ler, editar, indisponível e ainda não validado, com motivo.
2. Separar transporte/autenticação, parsers e operações LAN/Wi-Fi/diagnóstico em módulos do adaptador Huawei.
3. Inspecionar System Information para portas/clientes/estatísticas e DHCPv6 Information, coletando somente campos necessários.
4. Ler endereços LAN, DNS estático, modo das portas, isolamento e topologia. Não exibir valores fictícios quando a leitura falhar.
5. Unificar o modelo de cliente com MAC normalizado, IPs IPv4/IPv6, SSID/banda/porta, estado, nomes e origem de cada informação.

Aceite: a conta de menor privilégio não recebe botões de escrita presumidos; leituras que falham mostram indisponibilidade; os clientes não são duplicados entre telas; a inspeção não altera o roteador.

#### Implementação inicial da Fase 1 — 28/10/2026

- O transporte, a sessão/autenticação e os módulos de operações Huawei foram separados em `gateway_adapters/transport.py` e `gateway_adapters/huawei/`. Parsers de clientes, DHCP, Wi-Fi, reservas, bloqueios e logs ficam em `gateway_adapters/parsers.py`.
- Foi criado um registro de capacidades por sessão autenticada. Ele não presume privilégios pelo modelo: cada leitura começa como não consultada, alterações não oferecidas aparecem como tal e uma escrita só é marcada como confirmada após o fluxo existente de releitura concluir com sucesso.
- A página **Monitoramento → Capacidades** exibe modelo, firmware/hardware disponíveis e estado de leitura/alteração por recurso. **Inspecionar páginas** faz somente GET às páginas internas documentadas e descobre System Information e DHCPv6 Information apenas por links internos do menu da sessão. Não envia formulários nem altera o roteador. Parsers conservadores extraem campos LAN em allowlist: IPv4 LAN/máscara, campos DHCPv6/RA/ULA/MTU, tabela DNS local com cabeçalhos explícitos, estado das portas LAN1–LAN4 quando a tabela identifica porta/status, e endereços IPv6 por MAC quando a tabela DHCPv6 identifica os dois cabeçalhos. Valor não reconhecido ou formato diferente não é inferido; senhas, tokens, campos ocultos, identificadores de série e dados de páginas fora do escopo são excluídos.
- O modelo canônico reúne online, offline e bloqueados por MAC normalizado, com endereço IPv4 observado, interface/rede, estado, tempo quando disponível, reserva e status de bloqueio. Distingue identificador local, nome reportado pelo cliente, nome de regra do roteador e nome DNS. Registra a fonte de cada campo. Endereços IPv6 só são associados ao MAC quando a tabela DHCPv6 Information contém cabeçalhos inequívocos de MAC e endereço e cada valor passa pela validação IPv6; o indicador IPv6 legado não é apresentado como endereço.
- Nesta execução, não havia sessão autenticada do app conectada ao Huawei para confirmar os parsers no firmware. System Information, DHCPv6 Information e páginas LAN secundárias não foram consultadas nesta sessão. A ação de inspeção fica disponível após o login e atualiza os estados daquela sessão.
- A inspeção registra nomes de controles não sensíveis e valores somente quando um parser allowlist reconhece o campo. Respostas que indicam a tela de login são tratadas como sessão expirada/indisponível. A página alcançável sem campo reconhecido aparece como formato não reconhecido, sem substituir isso por valores estimados.

**Validação atualizada da Fase 1:** uma nova inspeção de leitura reconferiu as fontes Ethernet, Layer 2/3, DNS local, DHCPv6 e EasyMesh, conforme o registro de continuação abaixo. A execução dos leitores integrados no app com a sessão real e o aceite operacional permanecem pendentes; DUID não é associado a MAC sem evidência. A aplicação não deve interpretar “página acessível” como permissão de escrita.

#### Continuação da Fase 2 — 28/10/2026

- Reservas IPv4 agora permitem remoção individual com confirmação na interface. O adaptador valida o identificador fixo da reserva, lê a linha atual, envia a exclusão somente para aquele domínio/IP/MAC e relê a tabela; o app só informa sucesso se a linha deixar de existir.
- Foi criada a tela **LAN e IPs → Nomes DNS locais**, separada do DNS entregue por DHCP. A leitura faz GET à página de DNS estático e exibe somente tabelas que tenham cabeçalhos explícitos `Domain Name` e `IP Address`; não lê DNS Template/DNS Search List e não oferece gravação.
- O inventário agora reconhece reservas IPv6 somente em tabelas com cabeçalhos explícitos MAC e Interface ID/IPv6 Address. Elas aparecem na inspeção de capacidades, separadas dos endereços IPv6 observados em concessões; ainda não são enviadas como endereços ativos do cliente.
- Foi adicionada a tela **LAN e IPs → IPv6 e DHCPv6**, somente leitura, para consultar os campos DHCPv6/RA reconhecidos e as reservas IPv6 reconhecidas. A página também diferencia tabela vazia de formato não reconhecido.
- Foi adicionada a consulta **Segurança → Isolamento de portas**, somente leitura, para mostrar apenas controles que o parser allowlist reconhece na página LAN do Huawei. A tela informa que a eficácia depende do modo Layer 2/3 e não representa isolamento Wi-Fi nem segregação completa da rede.
- Nenhuma alteração foi enviada ao Huawei nesta continuação. O formato real de exclusão e de tabela DNS continua condicionado a conferência pela sessão do usuário antes de usar as operações no roteador.

### Fase 2 — Endereçamento e nomes locais

1. Completar concessões e reservas IPv4, incluindo remoção verificada e detecção de conflitos. Criação, edição, conflitos e remoção têm implementação; exclusão confere a lista relida antes de informar sucesso.
2. Implementar registros DNS estáticos de nomes locais, com operações limitadas à tabela local, sem alterar as demais políticas da página. CRUD foi implementado após conferir o objeto HOSTS e a fonte da tabela, com estado esperado e releitura completa.
3. Adicionar reservas e DNS IPv6 conforme capacidades; explicar a dependência de DHCPv6 versus SLAAC. CRUD de reservas e configuração de DNSv6 LAN foram implementados; a reserva permanece indisponível na condição SLAAC observada.
4. Só depois implementar alteração de endereço/máscara LAN, com prévia de impacto, validação conjunta com DHCP e instruções de reconexão ao novo IP.

Aceite: mudanças preservam campos não editados e estado externo; leitura posterior confirma o resultado; falhas nunca são apresentadas como sucesso. Validar resolução usando um cliente que realmente utilize o DNS da LAN.

### Fase 3 — Wi-Fi completo e segurança interna

1. Completar configuração por SSID: quantidade de clientes e segurança/autenticação; criação/remoção de SSID somente após conhecer limites, SSIDs reservados e efeitos na cobertura.
2. Adicionar parâmetros de rádio por banda, com valores suportados pelo firmware e dependências de Band Steering.
3. Implementar a leitura e o diagnóstico de políticas MAC. Usar um cliente de teste autorizado para confirmar bloqueio efetivo em cada SSID/banda relevante.
4. Validar Port Isolation em cenário controlado e distinguir isolamento entre portas, entre clientes Wi-Fi e entre segmentos. Não ativar regras existentes sem mostrar o conjunto afetado.
5. Se o firmware não permitir segregação adequada de convidados, manter a função indisponível e apresentar a alternativa documentada em RECOMENDACOES-ISOLAMENTO-REDE.md.

Aceite: testar serviços reais entre clientes e acesso à administração, em IPv4 e IPv6, incluindo bandas/APs distintos. Receber IP ou deixar de responder a ping isoladamente não comprova permissão/bloqueio. Testes reais exigem escolha prévia de cliente e janela pelo usuário.

### Fase 4 — Topologia, observabilidade e operação

1. Expandir topologia e informações de portas/APs locais; avaliar limites de roaming após validar a leitura.
2. Adicionar diagnóstico interno limitado e histórico de eventos, sem varredura automática nem diagnóstico disruptivo.
3. Incluir eventos sustentados por dados: alteração de configuração local observada, mudança de enlace, mudança de IP e possível reinício. Distinguir evento confirmado de inferência.
4. Disponibilizar exportação das configurações e identificadores do app e, se viável, uma projeção de configurações LAN sem segredos. Backup bruto da ONT inclui áreas externas e não faz parte deste escopo.

## Contrato das futuras alterações

- Nesta entrega, todas as configurações do Huawei continuam intactas. As fases futuras descrevem implementação e critérios; não autorizam execução de alterações reais agora.
- Cada operação deve usar uma lista explícita de objetos/propriedades internos permitidos. Não disponibilizar um proxy genérico para set.cgi/add.cgi/del.cgi.
- Antes de salvar: obter estado recente, comparar com o estado editado, apresentar alterações e efeitos, preservar os campos restantes. Recusar gravação quando houver conflito ou perda de sessão.
- Após salvar: reler a configuração e verificar o resultado; não repetir comandos cegamente após timeout.
- Mudanças que interrompem Wi-Fi, administração, DHCP ou conectividade precisam de confirmação clara no produto e roteiro de recuperação. Não prometer rollback automático se o novo IP ou a política impedir acesso ao gateway.
- Segredos nunca são devolvidos nem incluídos em logs, URLs de notificações ou documentos. Permissões e recursos devem ser verificados novamente após reconexão.
- Identificadores locais, DNS e nomes do gateway têm semânticas diferentes e não serão sincronizados silenciosamente.

## Continuação implementada em 28/10/2026

Esta atualização amplia as fases, mas não marca o plano inteiro como concluído. Foi feita nova inspeção de leitura no painel autenticado; hardware `343D.D`, software `V5R024C10S106` e personalização `BREBG2` foram conferidos. Nenhuma gravação, reinício, ativação de filtro ou teste de isolamento foi executado no equipamento.

| Parte | Implementação nesta continuação | Limite atual |
| --- | --- | --- |
| Inventário | Tela própria com horários, atualização completa/por recurso e exportação de projeção LAN sem segredos | Projeção não é um backup restaurável da ONT |
| Ethernet | Fonte conferida `/html/amp/ethinfo/ethinfo.asp`: `GEInfo` e `LANStats` para estado, modo, velocidade e contadores LAN de 64 bits | Não coleta estatísticas GPON/WAN; não zera contadores |
| Layer 2/3 | Leitura de `stLayer3Enable` em `/html/bbsp/layer3/layer3.asp` | As quatro portas observadas estão em Layer 3; o próprio painel desabilita Port Isolation. Não converte portas automaticamente |
| IPv6 | Concessões em `/html/bbsp/dhcpv6info/dhcpv6info.asp`, construtor `DhcpInfoClass` | DUID, endereço/prefixo e concessão são exibidos separadamente; DUID não é convertido em MAC |
| DNS local | Criar, editar e remover exclusivamente `InternetGatewayDevice.X_HW_DNS.HOSTS`, com dados de `/html/bbsp/common/dnshostslist.asp` | Detecta estado desatualizado e relê toda a tabela; DNS template e Search List ficam fora da operação |
| Reservas IPv6 | CRUD de `X_HW_DHCPv6.Server.StaticAllocation`, MAC e InterfaceID de 64 bits | A rede observada usa SLAAC. A gravação fica indisponível quando ManagedFlag não confirma atribuição DHCPv6 |
| DNSv6 | Servidores estáticos da LAN no objeto `LANDevice.1.X_HW_IPv6Config` | Preserva seleção externa, prefixos, RA, ULA e delegação; não muda o método de atribuição |
| IP/máscara LAN | Prévia com DHCP atual, conflitos de clientes, reservas afetadas e roteiro de reconexão | A gravação efetiva ainda depende de validar atualização conjunta e recuperação de acesso |
| SSID | Limite de 1–64 clientes quando o campo estiver presente; confirmação de efeito, controle de concorrência e releitura | Backhaul EasyMesh protegido; criação/remoção e senha não são oferecidas |
| Autenticação | Perfis pessoais WPA2/WPA3/transição reconhecidos, com AES e chave existente preservada | Não expõe senhas, não configura Enterprise/RADIUS nem comprova compatibilidade de todos os clientes |
| Rádio | Leitura por banda e alteração de potência para personalização BREBG2 validada | Canal, largura, país e Band Steering preservados; seleção dinâmica de canal/largura ainda pendente |
| Histórico | SQLite, até 2.000 eventos/gateway, níveis, busca, filtros, paginação e download; comparação de clientes sem notificações ativas | Configuração/enlace dependem de atualizar inventário. Falha de coleta não gera desconexão em massa |
| Reinício observado | Suporte a inferência quando uma leitura reconhecida de uptime diminui | Não usa relógio do sistema como uptime nem atribui causa; se a fonte não fornecer uptime reconhecido, não gera o evento |
| Diagnóstico | Uma tentativa TCP HTTP/HTTPS, até dois segundos, apenas no gateway ou cliente online da LAN | Parte do servidor do app; não é ping/traceroute do Huawei e não comprova isolamento entre clientes |
| Docker | Copia adaptadores e novos módulos, serve o novo JS e verifica os arquivos no fluxo de publicação | Imagem local não construída neste ambiente sem Docker; o fluxo de CI mantém smoke test em amd64/arm64 |

As operações novas usam objetos e propriedades fixos, confirmação, nova leitura de estado, comparação com a versão editada e releitura de resultado. Não há proxy genérico. Uma operação sem confirmação por releitura retorna erro e não é repetida automaticamente.

Validação local final desta continuação: **83 testes Python e 5 testes de navegação passaram**, além de verificação de sintaxe dos dois arquivos JavaScript e revisão de diferenças sem erros de whitespace. Inclui roteamento HTTP em memória, autenticação/CSRF, rejeição de estado desatualizado, escopo de propriedades, SLAAC, WPS, preservação de segredos, histórico e diagnóstico limitado. A rede do ambiente impediu abrir a prévia local no navegador; não foi feita validação visual das novas telas nem build local de imagem Docker. Não foi feito push ou deploy nesta execução.

## Pendências específicas para conclusão integral

1. Conferir o resultado operacional das escritas com cliente/janela escolhidos pelo usuário. As implementações de escrita foram verificadas com gateways simulados, sem aplicar mudanças no Huawei.
2. Validar operacionalmente, em janela autorizada, a mudança conjunta de LAN/DHCP e recuperação implementadas na etapa abaixo.
3. Implementar as opções dinâmicas de canal/largura e restrições de Band Steering conforme a próxima etapa reservada. A alteração de senha foi implementada na etapa abaixo.
4. Confirmar limites e SSIDs reservados/cobertura antes de criar ou remover SSIDs. Estudar administração LAN e proteção PSK em operações separadas, sem ampliar acesso externo.
5. Testar bloqueio efetivo, associação/reconexão e tráfego IPv4/IPv6 entre SSIDs/APs com um cliente autorizado. A condição atual Layer 3 impede usar Port Isolation como solução automática; as alternativas permanecem em `RECOMENDACOES-ISOLAMENTO-REDE.md`.
6. Mapear e validar ping/traceroute estritamente LAN no Huawei caso seja necessário originar testes do equipamento. O diagnóstico TCP do servidor não é substituto para esse aceite.

## Etapa atual finalizada — LAN e senha Wi-Fi

- LAN: prévia conjunta de endereço, máscara, intervalo DHCP e reservas; migração opcional preservando o número de host. Valida sobreposição, conflitos, reservas e pools especiais antes do envio.
- Aplicação exige confirmação explícita e o novo IP digitado. O comando é enviado uma única vez. Um diário persistente sem credenciais permite retomar a verificação após reiniciar o aplicativo.
- Recuperação: reconecta no endereço proposto, compara o MAC LAN do equipamento e relê endereço, DHCP e reservas. Migra cadastros locais somente após confirmação; uma resposta interrompida permanece pendente, sem repetição automática.
- Senha Wi-Fi: formulário sem revelar a chave atual; valida os requisitos do firmware, detecta alterações concorrentes e agrupa SSIDs de mesmo nome nas bandas. Confirma a chave por releitura em todos os membros; backhaul e chaves mascaradas ficam indisponíveis.
- A chave não é incluída nas respostas, no diário nem nos eventos. A troca exige confirmação sobre a reconexão dos clientes.
- Verificação local: **99 testes Python e 5 testes de navegação passaram**, além da sintaxe dos três JavaScripts e verificação de diferenças. As escritas foram testadas com gateways simulados; nenhuma configuração do Huawei foi aplicada.

## Próxima etapa reservada — rádios e ciclo de vida de SSIDs

Iniciada pela prévia de canal/largura descrita abaixo. As gravações e o ciclo de vida de SSIDs continuam pendentes. O levantamento abaixo foi feito no painel, restaurando os valores dos formulários sem clicar em Aplicar.

1. Expor canal/largura para `EG8145X6-10`, hardware `343D.D`, firmware `V5R024C10S106`, personalização `BREBG2`, país `BR` e modo `11ax`. Outros perfis exigem nova detecção; não reutilizar uma lista regulatória por suposição.
2. 2,4 GHz: larguras `0` (auto 20/40), `1` (20) e `2` (40); canais `0` (automático) e 1–13 nas três larguras observadas.
3. 5 GHz: larguras `0` (auto 20/40), `1` (20), `2` (40), `3` (auto 20/40/80), `4` (auto 20/40/80/160). Canais observados: 36, 40, 44, 48, 52, 56, 60, 64, 100–144 em passos de quatro e 149, 153, 157, 161; canal 165 disponível apenas em 20 MHz. Automáticos distintos: `-1` com DFS e `0` sem DFS.
4. Mapear o escopo automático e os comandos auxiliares de rádio antes de escrever. Preservar país, modo, potência não editada e dependências de Band Steering; a presença das opções na tela não comprova sozinha o contrato de gravação.
5. Criação: o fluxo nativo usa **`addcfg.cgi`**, objeto `y=InternetGatewayDevice.LANDevice.1.WLANConfiguration`, `y.LowerLayers` e campos do SSID. A criação e a configuração de chave são etapas distintas no painel. Planejar criação desativada, segurança verificável antes da ativação e recuperação de falhas parciais.
6. Conferir limites por banda, índices reservados, cobertura/EasyMesh e a rotina nativa de exclusão, ainda não capturada. Não liberar remoção nem inferir o comando de exclusão antes disso.
7. Acrescentar testes de combinações, concorrência, preservação dos campos e falhas parciais; deixar o aceite com clientes reais para janela autorizada.

### Continuação: prévia por banda e exclusão nativa

- A tela Rádios e potência passou a oferecer planejamento de canal/largura por banda. A lista depende da identificação exata do hardware, firmware, país e modo acima; não é aplicada a outros perfis.
- `POST /api/wifi/radios/preview` relê o rádio, verifica a versão e valida a combinação. Não grava nem anuncia disponibilidade de aplicação. Campos de canal/largura enviados ao endpoint de potência são recusados explicitamente.
- São diferenciados os automáticos com/sem DFS; canal 165 só é oferecido em 20 MHz. O formulário não presume o escopo automático atual quando essa informação não foi lida.
- Validação: 105 testes Python e 5 de navegação passaram. Nenhuma escrita foi executada no Huawei e não houve deploy desta continuação.
- Nova inspeção autenticada confirmou que excluir um SSID não equivale a enviar apenas `del.cgi`: há uma etapa prévia `InternetGatewayDevice.X_HW_DEBUG.AMP.ParallelDelSsid`, com `y.DeleteInstArray`. O fluxo nativo também pode atualizar a referência de convidados. Essas dependências devem ser tratadas antes de liberar remoção.

### Implementação de SSIDs — 29/10/2026

- Nova tela **Wi-Fi → Gerenciar redes**: capacidade por banda informada pelo firmware, criação de rede protegida desativada, recuperação de criação incompleta e exclusão de redes adicionais elegíveis.
- A criação usa `addcfg.cgi`, inicialmente com Enable e divulgação desativados; só depois configura WPA2/AES, senha e WPS desativado nos objetos novos reconhecidos. Relê o estado e a chave sem devolvê-la. A ativação posterior continua sendo uma ação separada do usuário.
- Diário local sem senhas protege a recuperação entre sessões e reinícios. Uma rede pendente não pode ser ativada, divulgada ou renomeada pela edição comum antes da confirmação de segurança.
- A exclusão implementa a preparação ParallelDelSsid e o del.cgi observados, confirmação pelo nome, aceite da desconexão e confirmação separada de referência de convidados quando existente. Redes principais, índices de backhaul, nomes compartilhados e dependências de APs ficam protegidos. A tabela remanescente é relida para verificar preservação.
- Não há repetição automática de criação/exclusão após resposta ambígua. A recuperação configura somente o objeto desativado já reconhecido; não cria outro SSID.
- Inventário ganhou exportação autenticada de diagnóstico da integração: somente funções nativas selecionadas de rádio, sem arrays de estado, credenciais ou token da sessão. Funções ambíguas são omitidas.
- **116 testes Python e 5 testes de navegação passaram**; inclui criação desativada, falha parcial, recuperação persistente, bloqueio de ativação/renomeação pendente, exclusão em duas etapas, dependências e ausência de segredos nas respostas e no diário.
- Restam os comandos auxiliares de canal/largura e os aceites reais de conectividade/isolamento. Nenhum desses aceites é substituído pelos testes simulados. Nenhuma configuração do Huawei foi aplicada durante o desenvolvimento.

### Continuação de rádio e conferência no ZimaOS — 29/10/2026

- O commit `615c8ac` foi instalado pelo Compose existente no ZimaOS. A revisão do contêiner foi conferida, com estado healthy e zero reinícios. O pull do Compose pulou a imagem; o download direto do GHCR corrigiu a imagem local antes da recriação.
- A sessão real do app confirmou as leituras das duas bandas e as capacidades nativas de SSID: quatro posições por banda, com contadores que incluem redes reservadas. Nenhuma configuração foi aplicada no Huawei.
- O diagnóstico autenticado permitiu conferir AddSubmitParamChannel, AddSubmitParam e CheckConfigChannel. Foram implementados canal fixo, largura e automático com/sem DFS, com as ações auxiliares nativas e releitura de país, padrão, potência, Band Steering, outras bandas e SSIDs.
- A aplicação exige perfil exato, esquema de leitura do escopo automático, flags reconhecidas e contrato nativo compatível. WDS ou dependências desconhecidas mantêm o controle em prévia; nenhuma opção regulatória é inferida para outro perfil.
- A identificação não deve depender exclusivamente de User Logs. O caminho antigo retornou HTTP 404 na sessão real; foi acrescentado fallback de pasta somente nesse caso e leitura de versão por campos explícitos da página Device Information. Cabeçalhos com campos separados por ponto e vírgula são suportados; eventos do log não são fonte de versão.
- **127 testes Python e 5 de navegação passaram**, incluindo ordem c1/y/c2, diferenças entre canal fixo e automático, DFS, escopo do canal 165, resposta interrompida, preservação de outra banda e rejeição de contrato desconhecido.
- Aceites que dependem de mudar a rede continuam separados: isolamento IPv4/IPv6 entre clientes, reconexão de cliente bloqueado, resolução DNS por cliente real e mudança de LAN. Eles exigem cliente/janela autorizados e não foram executados durante o desenvolvimento.

Conferência posterior: `9184253` foi instalado com healthcheck saudável e zero reinícios. A sessão real passou a reconhecer HW `343D.D` e SW `V5R024C10S106`. Foi necessário ajustar a leitura dos campos auxiliares distribuídos entre scripts e distinguir o inicializador de DFS de seu valor calculado. O conjunto atualizado tem **128 testes Python aprovados**, além dos cinco testes de navegação.

O ajuste de leitura de Band Steering preserva a política nativa como valor numérico opaco, inclusive no namespace local X_HW_WIFIInfo, sem acrescentar escrita dessa política. **129 testes Python passaram** após esse ajuste. `93153c4` foi instalado e iniciou saudável; a aplicação de rádio permanece condicionada à confirmação dos campos reais na sessão.

A leitura real confirmou AP Logs (500 registros). User Logs ainda devolveu 404 nas pastas fixas; foi implementada descoberta dos links de log no menu autenticado e em até três scripts de menu explicitamente declarados pela página, sem tentar nomes de arquivos por adivinhação. Negações de permissão não geram busca alternativa. A descoberta valida caminhos locais de leitura e o parser de logs continua obrigatório. **133 testes Python passaram** com essa continuação.
