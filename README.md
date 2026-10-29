# Gateway Manager

Aplicativo de gerenciamento de gateway com seleção de modelo na conexão. Atualmente o único adaptador disponível é o Huawei EG8145X6-10 (firmware V5R024C10S106); outros modelos exigem integração própria. A integração de escrita é experimental: os formatos foram inspecionados no firmware e exercitados com gateway simulado, sem modificar o equipamento real. Confirme o resultado no painel do Huawei ao utilizar. Criação, edição e remoção de reservas são confirmadas por releitura antes de a interface reportar sucesso.

A aba Dispositivos lista clientes online de LAN e Wi-Fi e oferece uma aba Offline com os dispositivos que o gateway informa como desconectados, com nome informado pelo Huawei, IP e MAC. A lista é atualizada a cada 15 segundos enquanto a página está visível e também pelo botão Atualizar. Os identificadores são etiquetas persistidas **somente neste aplicativo**, associadas ao MAC; não renomeiam o cliente no gateway nem no dispositivo. A interface do Huawei tem mecanismo próprio de nome por MAC, mas a escrita pelo aplicativo ainda não foi validada. IPs que coincidem com reservas DHCP ativas aparecem em verde como “Fixo”; endereços informados pelo gateway como estáticos sem reserva correspondente aparecem em verde como “Estático”. Essa classificação depende dos dados do Huawei.

Cada seção da rede tem filtros combináveis por faixa Wi-Fi e categoria. As categorias IoT, Celulares, Computadores e Rede podem ser atribuídas nos detalhes de um dispositivo; são salvas apenas no aplicativo e associadas ao MAC. As opções de rede refletem o mapeamento de SSIDs observado neste gateway.

Cada card abre detalhes da conexão e permite salvar um identificador ou criar/editar uma reserva DHCP, com o IP atual preenchido quando ainda não houver reserva. A identificação das redes reflete a configuração observada neste gateway: SSID1 é 2,4 GHz, SSID2 é convidados em 2,4 GHz e SSID5 é 5 GHz; outras redes são exibidas como não identificadas. Se essa configuração mudar, o mapeamento precisará ser atualizado. O bloqueio Wi-Fi exige confirmação, cria uma regra no SSID atual e confirma a política por releitura. A integração aceita o modo de lista de bloqueio global observado neste firmware; recusa lista de permissão e a ativação de filtros que já tenham regras antigas desativadas. A aba Bloqueados lista regras ativas em modo Blacklist, inclusive clientes ausentes da lista de dispositivos. Os cards mostram o estado em vermelho e permitem remover uma regra por MAC e SSID, mediante confirmação e verificação por releitura. A escrita ainda não foi testada em um cliente real.

As abas DHCP e DNS permitem consultar e alterar o intervalo principal, concessão e servidores DNS distribuídos aos clientes. A aba Redes Wi-Fi permite alterar o nome, ativação e transmissão de SSIDs existentes; senhas e configurações de segurança não são editadas. A aba Reinício envia um comando de reinício após confirmação textual, sem restaurar padrões de fábrica. Os comandos foram implementados com base no firmware observado e testados em simulação; ainda não foram executados neste gateway. Alterações podem interromper a rede ou exigir renovação DHCP; confira o painel Huawei caso o aplicativo não confirme uma alteração.

Em **Reservas de IP**, cada reserva pode ser removida com confirmação; o app relê a tabela do Huawei e só informa sucesso quando a entrada desaparece. **LAN e IPs → Nomes DNS locais** permite criar, editar e remover associações da LAN quando o objeto `X_HW_DNS.HOSTS` e a fonte `dnshostslist.asp` são reconhecidos. Cada operação confere se a tabela mudou desde a leitura e verifica o resultado completo; DNS template e Search List são preservados.

**LAN e IPs → IPv6 e DHCPv6** consulta DHCPv6/Router Advertisement e permite gerenciar reservas por MAC/identificador de interface de 64 bits quando o firmware confirma atribuição DHCPv6. Em SLAAC, a edição fica indisponível. A tela também permite configurar somente os servidores DNSv6 estáticos servidos na LAN, com confirmação e releitura. Não modifica prefixos ou delegação.

Em **Segurança → Isolamento de portas**, a consulta é somente leitura e mostra apenas controles LAN identificados no firmware. A página do Huawei condiciona esse recurso ao modo Layer 2/3; a tela não infere isolamento Wi-Fi nem isolamento completo entre clientes.

**Rede interna → Inventário e topologia** reúne leituras de endereços LAN, modo das portas, isolamento, EasyMesh, rádios e concessões DHCPv6. Cada painel mostra quando foi consultado; consultas são manuais, por painel ou por inventário completo. Os leitores reconhecem os construtores JavaScript observados no firmware, sem executar JavaScript do gateway. As concessões DHCPv6 observadas usam DUID e aparecem separadas de MACs; estações da topologia não são classificadas como APs.

**LAN e IPs → Endereço LAN** faz uma prévia de impacto usando DHCP, reservas e clientes atuais. Identifica endereços ocupados, reservas incompatíveis e intervalo DHCP inválido para a nova rede, com roteiro de reconexão. A mudança efetiva de IP/máscara continua indisponível até validar as dependências do firmware.

**Monitoramento → Histórico da rede** mantém até 2.000 eventos por gateway em SQLite, com INFO neutro, WAR amarelo, ERROR vermelho, filtros, busca, paginação e download dos eventos exibidos. Clientes são observados a cada 30 segundos durante a sessão; mudanças de configuração/enlace e tempo de atividade dependem de novas leituras do inventário. A primeira leitura cria referência e uma falha de coleta não representa desconexão em massa. Possível reinício é marcado como inferência, sem atribuir causa.

**Monitoramento → Diagnóstico interno** executa uma única tentativa TCP HTTP/HTTPS, sob demanda, a partir do servidor do aplicativo, com limite de dois segundos. O destino precisa ser o gateway ou um cliente conectado na LAN atual. Não é o ping/traceroute do Huawei nem prova de isolamento entre clientes.

Os SSIDs permitem ajustar limite de 1 a 64 clientes quando a propriedade observada está presente. O app apresenta as alterações antes de salvar e rejeita edição sobre configuração desatualizada. SSIDs de backhaul identificados como EasyMesh ficam protegidos. **Wi-Fi → Autenticação** permite selecionar perfis pessoais WPA2, WPA3 ou de transição reconhecidos, com AES e preservação da chave atual, sem exibir senhas. WPA3 exige WPS reconhecido como desativado. **Wi-Fi → Rádios e potência** permite ajustar potência no perfil BREBG2 inspecionado, preservando país, modo, largura e seleção de canal. Alteração de senha, canal/largura e políticas de Band Steering ainda não são oferecidas.

## Executar no ZimaOS

Para a instalação existente em `192.168.100.236:8081`, use [docker-compose.zimaos.yml](docker-compose.zimaos.yml). Ele preserva o volume verificado `custom__kyq3dva5_gateway-manager-data`, limita os logs e verifica a saúde do aplicativo. O `pull_policy: always` consulta o registro quando o Compose é executado. Ele não consulta nem instala imagens automaticamente em segundo plano; um simples reinício Docker também não força o download.

Atualize a instalação existente usando o Compose completo em vez de criar uma segunda cópia com a mesma porta e nome. O volume é externo e precisa existir. Em outro ZimaOS, identifique o volume atual com `docker inspect gateway-manager --format '{{range .Mounts}}{{.Name}} {{.Destination}}{{end}}'` e substitua o nome correspondente a `/data` no arquivo; para uma instalação nova, crie antes o volume ou adapte a seção de volumes. Não remova o volume existente durante a migração. Algumas telas do ZimaOS podem regravar campos do Compose: confira se o volume e a política de download foram mantidos depois de salvar pela interface.

O arquivo não fornece o socket do Docker ao aplicativo. Verificações periódicas e recriação automática exigem um mecanismo separado no host, com acesso apropriado ao Docker. Quando o aplicativo é recriado, as credenciais e sessões mantidas em memória são perdidas: conecte-se novamente para retomar os alertas.

Para uma instalação genérica sem atualizador automático, está disponível o Compose abaixo. Para atualizar manualmente, execute `docker compose pull` e `docker compose up -d`.

```yaml
services:
  gateway-manager:
    image: ghcr.io/rafaels-santos/gateway-manager:latest
    ports:
      - "8080:8080"
    volumes:
      - gateway-manager-data:/data
    restart: unless-stopped
volumes:
  gateway-manager-data:
```

Acesse `http://IP_DO_ZIMAOS:8080`. O volume conserva os nomes; a sessão e as credenciais não são salvas nele. Uma nova conexão pode encerrar a sessão de administração existente no gateway.

O firmware pode usar HTTP para o login: Base64 não é criptografia. Use o aplicativo e o gateway apenas em rede confiável, e não exponha a porta do aplicativo diretamente à Internet. O ZimaOS precisa alcançar o IP privado do gateway.

Testes locais: `python -m unittest discover -s tests -v`.

Caso o contêiner não inicie, consulte `docker compose logs gateway-manager` e verifique se a porta 8080 está disponível. Para mudar a porta externa, substitua `8080:8080` por `8081:8080`.

## Notificações por hooks

A aba **Notificações**, acima de Reinício, lista os destinos cadastrados. Use **Criar hook** para abrir o popup e escolher Discord, Telegram, WhatsApp Cloud API, Slack ou webhook genérico. É possível cadastrar vários hooks do mesmo serviço (até 20 por gateway), cada um com nome, ativação e mensagens por evento independentes. **Editar** permite mudar as configurações ou desativar um destino.

**Salvar hook** valida os campos e persiste a configuração. **Salvar e testar** também envia uma mensagem simples; cada card possui **Testar hook** para repetir o teste inclusive com o hook desativado. Sucesso indica aceitação pelo serviço, não entrega/leitura pelo destinatário. Alterar a configuração exige novo teste. URL e tokens não são devolvidos ao navegador; campos secretos vazios em edição preservam o valor salvo para o mesmo serviço.

O webhook único anterior é migrado automaticamente para **Hook existente**, preservando formato, eventos, ativação e referência de dispositivos conhecidos. Ele é apresentado como não testado até que um teste seja executado. Os dados antigos são mantidos para recuperação, mas deixam de ser utilizados pelo monitor. Não há envio automático de teste durante a migração.

Cada hook possui referência de dispositivos e fila persistente próprias em `/data/labels.db`. Falhas de um destino não bloqueiam os outros. Até três mensagens pendentes por destino são tentadas por ciclo. Alterar um hook descarta mensagens pendentes da configuração anterior; mudar sua ativação estabelece uma nova referência sem alertas retroativos. Há possibilidade de duplicação se o serviço aceitar uma mensagem e a conexão/processo falhar antes de registrar a confirmação local.

A primeira leitura registra os dispositivos conhecidos sem enviar alertas. O monitor consulta a cada 30 segundos e roda enquanto existir uma sessão válida com o gateway, inclusive com a página fechada. Após reiniciar o contêiner, conecte-se novamente. Conexões ocorridas entre leituras podem não ser detectadas. Links usam o endereço do último login e exigem acesso à rede e sessão no aplicativo.

### Configuração dos serviços

- **Discord:** URL de webhook do canal. [Documentação](https://discord.com/developers/docs/resources/webhook).
- **Telegram:** token de bot criado com BotFather e chat ID (ou `@canal`). Inicie a conversa ou adicione o bot ao grupo/canal com permissão de envio. [Bot API](https://core.telegram.org/bots/api#sendmessage).
- **WhatsApp:** conta Business Cloud API, token, Phone Number ID, destinatário com DDI, versão Graph API vigente na conta, nome e idioma de template aprovado. Esta integração usa exatamente um parâmetro posicional `{{1}}` no corpo, sem parâmetros em cabeçalho/botões. O texto do evento é normalizado para uma linha e limitado a 900 caracteres para esse parâmetro. Não há login por QR Code/WhatsApp pessoal. O teste usa o mesmo template e depende de permissões, aprovação, destinatário autorizado e condições da Meta. [Templates oficiais](https://whatsappbusiness.com/blog/manage-message-templates-whatsapp-business-api/).
- **Slack:** URL de Incoming Webhook para o canal. [Documentação](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).
- **Webhook genérico:** endpoint HTTPS público na porta 443. Recebe JSON com `event`, `text` e `device`; redirecionamentos não são seguidos. Endereços privados/locais não são aceitos.

O ícone para ZimaOS está disponível em `https://raw.githubusercontent.com/rafaels-santos/gateway-manager/master/static/icon.png`. Para uma instalação existente, use esse endereço no campo de ícone personalizado do aplicativo.

## Adicionar um modelo de gateway

O catálogo `/api/gateway-types` é gerado pelo registro `GATEWAY_ADAPTERS` em `app.py`. Para um novo modelo, implemente um adaptador próprio com `model_id`, `model_label`, `base`, `lock`, `login`, `devices`, `reservations`, `save`, `dhcp_config`, `save_dhcp`, `wifi_config`, `save_wifi` e `reboot`, seguindo os formatos de dados usados pela API e implementando verificação de sessão, validação e erros adequados. Registre-o somente após validar suas operações e permissões. O adaptador Huawei contém lógica específica do firmware e não é compatível automaticamente com outros modelos.

O formulário de login permite o preenchimento automático e tenta solicitar o armazenamento da senha pelo gerenciador do navegador após autenticação bem-sucedida, quando a Credential Management API estiver disponível em contexto seguro. Em HTTP de rede local, a exibição do aviso depende do navegador e não pode ser garantida.


### Webhooks de eventos

Ao criar um hook, escolha o serviço desejado. O formato genérico aceita um endpoint HTTPS público na porta 443 e envia `{"event":"ip_changed","text":"mensagem personalizada","device":{...}}`. Redirecionamentos não são seguidos. A URL salva não é devolvida ao navegador.

Cada evento tem ativação e texto independentes: novo MAC online, desconexão, mudança de IP e as duas últimas condições para clientes com regra de bloqueio. Somente novo dispositivo fica ativo por padrão. Se eventos gerais e específicos estiverem ativos, ambos serão enviados. Regras inativas são identificadas pelo campo `{block_active}`. Mudança de IP significa diferença da última leitura, não desvio de reserva DHCP. O monitor consulta a cada 30 segundos; não representa captura em tempo real. A primeira observação cria referência sem disparar eventos de transição.

Variáveis: `{name}`, `{ip}`, `{previous_ip}`, `{mac}`, `{link}`, `{block_active}`, `{event}`. Mensagens aceitam até 1.500 caracteres. O botão de teste usa as configurações já salvas do hook. Novos eventos dependem de uma sessão ativa com o gateway.


### Detecção na tela de login

Ao preencher um IP, o app consulta a página inicial do gateway com GET e uma sessão HTTP separada, sem enviar usuário ou senha. O modelo compatível é selecionado automaticamente quando identificado; os campos de modelo/firmware/hardware vêm de títulos ou metadados explícitos da resposta, nunca de uma associação fixa com o IP. Modelos não reconhecidos permanecem disponíveis para seleção manual entre as integrações cadastradas.

Firmware pode não ser divulgado antes de autenticar. No Huawei, após login, o app tenta ler SWVer/HWVer do cabeçalho de User Logs e exibe o firmware junto ao modelo no painel. Se essa leitura não estiver disponível, a conexão continua sem uma versão presumida. A detecção limita tempo e redirecionamentos e aceita somente os mesmos IPs privados permitidos no login. Um novo adaptador pode declarar seus nomes exatos de identificação pública em `detection_models`.

O login usa um cartão compacto de gateway: clique no modelo para abrir o painel do IP em nova aba; clique no IP/lápis para editar o endereço dentro do cartão. Aplicar ou Enter confirma; Cancelar ou Esc preserva o endereço anterior. A seleção manual fica recolhida. O ícone Huawei fornecido pelo usuário é servido localmente em `/huawei.png`, com crédito a [Icons8](https://icons8.com/).

## Evolução da rede interna

O [plano de gerenciamento da rede interna](PLANO-GERENCIAMENTO-REDE-INTERNA.md) registra a inspeção de leitura do EG8145X6-10, as capacidades observadas e a expansão em fases. A navegação está agrupada em Rede interna, Wi-Fi, LAN e IPs, Segurança, Monitoramento e Manutenção. Bloqueios Wi-Fi abre a listagem de bloqueados existente. PPPoE, WAN e conexões externas não fazem parte do escopo de expansão.

Em **Monitoramento → Capacidades**, o app mostra leituras e alterações implementadas, o resultado da última consulta e o motivo de indisponibilidade por sessão. **Inspecionar páginas** faz somente GET às fontes LAN documentadas, incluindo as páginas Ethernet e DHCPv6 Information conferidas no painel. Os leitores extraem propriedades permitidas dos construtores de dados, tabelas e JSON reconhecidos, sem executar scripts do gateway. Tokens, segredos, números de série e propriedades externas são omitidos. A inspeção real conferiu as estruturas do firmware; a confirmação de escritas no equipamento e testes de isolamento continuam pendentes de execução autorizada. Implementação e testes simulados não comprovam permissão de gravação na conta conectada.

### Importar e exportar

Em **Manutenção → Importar / exportar**, a exportação gera um JSON versão 1 com identificadores e categorias por MAC salvos no aplicativo e reservas DHCP IPv4 do gateway conectado. O arquivo não inclui credenciais, hooks, senhas Wi-Fi, logs ou uma cópia completa da configuração do roteador. Para migrar, conecte o app ao gateway de destino, selecione o arquivo e confira a prévia antes de escolher o que aplicar. Os identificadores ficam no banco local do app, vinculados ao MAC e ao novo gateway. Reservas são gravadas no DHCP do Huawei somente após confirmação; IP fora da LAN, ocupado por outro MAC ou em conflito com um cliente online é ignorado e informado. Itens existentes são preservados por padrão; substituí-los requer marcar as opções correspondentes. Cada reserva é revalidada e confirmada individualmente, então uma falha parcial aparece no resumo. O formato só aplica reservas nos modelos/firmwares com adaptador compatível.

## Firmware do roteador

Em **Manutenção → Firmware**, o aplicativo mostra SWVer e HWVer lidos da sessão autenticada no gateway. A consulta online acessa somente a página oficial da [Huawei para o EG8145X6-10](https://e.huawei.com/en/products/optical-terminal/eg8145x6-10) e aceita redirecionamentos HTTPS dentro de domínios Huawei. Essa página não publica um catálogo de pacotes de firmware para este ONT, então a lista de downloads permanece vazia até haver um pacote verificável para o modelo e revisão de hardware exatos. A tela também oferece o [portal de software da Huawei](https://support.huawei.com/enterprise/en/software), que pode exigir acesso autorizado. O firmware de ONT precisa ser compatível com o OLT/NMS do provedor; solicite a versão aprovada ao provedor. O aplicativo não oferece instalação, gravação ou alteração de firmware.

Teste de navegação: `node --test tests/navigation.test.cjs`.
