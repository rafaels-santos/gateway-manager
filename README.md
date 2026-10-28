# Gateway Manager

Aplicativo de gerenciamento de gateway com seleção de modelo na conexão. Atualmente o único adaptador disponível é o Huawei EG8145X6-10 (firmware V5R024C10S106); outros modelos exigem integração própria. A integração de escrita é experimental: os formatos foram inspecionados no firmware e exercitados com gateway simulado, sem modificar o equipamento real. Confirme o resultado no painel do Huawei ao utilizar. A criação e edição de reservas são confirmadas por releitura; exclusão de reservas ainda não está implementada.

A aba Dispositivos lista clientes online de LAN e Wi-Fi e oferece uma aba Offline com os dispositivos que o gateway informa como desconectados, com nome informado pelo Huawei, IP e MAC. A lista é atualizada a cada 15 segundos enquanto a página está visível e também pelo botão Atualizar. Os identificadores são etiquetas persistidas **somente neste aplicativo**, associadas ao MAC; não renomeiam o cliente no gateway nem no dispositivo. A interface do Huawei tem mecanismo próprio de nome por MAC, mas a escrita pelo aplicativo ainda não foi validada. IPs que coincidem com reservas DHCP ativas aparecem em verde como “Fixo”; endereços informados pelo gateway como estáticos sem reserva correspondente aparecem em verde como “Estático”. Essa classificação depende dos dados do Huawei.

Cada seção da rede tem filtros combináveis por faixa Wi-Fi e categoria. As categorias IoT, Celulares, Computadores e Rede podem ser atribuídas nos detalhes de um dispositivo; são salvas apenas no aplicativo e associadas ao MAC. As opções de rede refletem o mapeamento de SSIDs observado neste gateway.

Cada card abre detalhes da conexão e permite salvar um identificador ou criar/editar uma reserva DHCP, com o IP atual preenchido quando ainda não houver reserva. A identificação das redes reflete a configuração observada neste gateway: SSID1 é 2,4 GHz, SSID2 é convidados em 2,4 GHz e SSID5 é 5 GHz; outras redes são exibidas como não identificadas. Se essa configuração mudar, o mapeamento precisará ser atualizado. O bloqueio Wi-Fi exige confirmação, cria uma regra no SSID atual e confirma a política por releitura. A integração aceita o modo de lista de bloqueio global observado neste firmware; recusa lista de permissão e a ativação de filtros que já tenham regras antigas desativadas. A aba Bloqueados lista regras ativas em modo Blacklist, inclusive clientes ausentes da lista de dispositivos. Os cards mostram o estado em vermelho e permitem remover uma regra por MAC e SSID, mediante confirmação e verificação por releitura. A escrita ainda não foi testada em um cliente real.

As abas DHCP e DNS permitem consultar e alterar o intervalo principal, concessão e servidores DNS distribuídos aos clientes. A aba Redes Wi-Fi permite alterar o nome, ativação e transmissão de SSIDs existentes; senhas e configurações de segurança não são editadas. A aba Reinício envia um comando de reinício após confirmação textual, sem restaurar padrões de fábrica. Os comandos foram implementados com base no firmware observado e testados em simulação; ainda não foram executados neste gateway. Alterações podem interromper a rede ou exigir renovação DHCP; confira o painel Huawei caso o aplicativo não confirme uma alteração.

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
