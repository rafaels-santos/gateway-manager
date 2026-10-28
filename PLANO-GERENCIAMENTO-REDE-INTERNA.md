# Plano de gerenciamento da rede interna

Inspeção em 28/10/2026 · Huawei EG8145X6-10 · HW 343D.D · SW V5R024C10S106.

## Objetivo e limites

Usar o Gateway Manager como painel da rede interna: clientes, Wi-Fi, endereçamento, nomes locais, controle de acesso e diagnóstico. Nesta etapa foram alterados somente a navegação do app e documentos do projeto.

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
| Manutenção | Reinício | Informações do equipamento e exportação das configurações do app/rede interna |

Apenas destinos funcionais aparecem como itens clicáveis. Não foram criados formulários vazios de funcionalidades futuras. Notificações permanece acima de Reinício. Em telas menores, a navegação permite rolagem horizontal; no desktop, os grupos ficam na lateral com rolagem própria.

## Inventário e lacunas do app

| Função | Evidência no Huawei | Situação no app e proposta |
| --- | --- | --- |
| Clientes e identidade | Listagem já integrada por MAC; informações de LAN, Wi-Fi e estado | Manter identidade global por gateway/MAC. Separar apelido do app, nome informado pelo cliente, nome de regra e nome DNS; não prometer que são o mesmo campo |
| DHCP IPv4 | Página conhecida `/html/bbsp/dhcpservercfg/dhcp2.asp` | Já edita ativação, intervalo e concessão. Inventariar os campos adicionais antes de expandir, preservando opções não editadas |
| Reservas IPv4 | `/html/bbsp/dhcpstatic/dhcpstatic.asp` | Já cria/edita reservas e verifica a resposta. Avaliar remoção de reserva e conflitos em fase posterior; verde/Fixo apenas quando reserva efetiva corresponder ao MAC/IP |
| LAN Host | Campos lidos em `/html/bbsp/dhcp/dhcp.asp`: endereço primário, máscara e endereço secundário | Novo formulário futuro. Mudança de IP exige coerência com DHCP e recuperação da conexão; não confundir IP secundário com isolamento de rede |
| DHCPv6 e RA | Campos lidos em `/html/bbsp/lanaddress/lanaddress.asp`: servidor, RA, DHCPv6/SLAAC, DNS da LAN, MTU e ULA | Começar com leitura. Escrita apenas de propriedades da LAN; excluir seleção de WAN, delegação e mudanças no prefixo da operadora |
| Reservas IPv6 | Campos lidos em `/html/bbsp/dhcpstaticaddr/dhcpstaticaddress.asp`: MAC e identificador de interface | Novo recurso condicionado ao modo DHCPv6. O próprio Huawei informa que não tem efeito com atribuição SLAAC |
| Concessões/informação DHCPv6 | Menu DHCPv6 Information observado | Inspecionar página e representação dos clientes antes de implementar; não inferir IPv6 ativo apenas por um indicador de capacidade |
| DNS da LAN | DNS entregue por DHCP já integrado | Manter distinto de DNS usado pelo próprio gateway e das políticas globais de resolução |
| DNS estático | Campos lidos em `/html/bbsp/dnsconfiguration/dnsconfigcommon.asp`: associação Domain Name/IP Address | Prioridade para nomes locais. Não alterar DNS template ou DNS Search List com vínculo WAN presentes na mesma página |
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

### Fase 2 — Endereçamento e nomes locais

1. Completar concessões e reservas IPv4, incluindo remoção verificada e detecção de conflitos.
2. Implementar registros DNS estáticos de nomes locais, com operações limitadas à tabela local, sem alterar as demais políticas da página.
3. Adicionar reservas e DNS IPv6 conforme capacidades; explicar a dependência de DHCPv6 versus SLAAC.
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

## Próxima entrega recomendada

**Fase 1: capacidades por sessão e inventário LAN somente de leitura**, dando prioridade a portas/isolamento e DNS estático. Essa base permite escolher com evidência as próximas operações, sem expor controles externos ou prometer funções não suportadas.
