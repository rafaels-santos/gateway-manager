# Gateway Manager

Aplicativo de gerenciamento de gateway com seleção de modelo na conexão. Atualmente o único adaptador disponível é o Huawei EG8145X6-10 (firmware V5R024C10S106); outros modelos exigem integração própria. A integração de escrita é experimental: os formatos foram inspecionados no firmware e exercitados com gateway simulado, sem modificar o equipamento real. Confirme o resultado no painel do Huawei ao utilizar. A criação e edição de reservas são confirmadas por releitura; exclusão de reservas ainda não está implementada.

A aba Dispositivos lista clientes online de LAN e Wi-Fi e oferece uma aba Offline com os dispositivos que o gateway informa como desconectados, com nome informado pelo Huawei, IP e MAC. A lista é atualizada a cada 15 segundos enquanto a página está visível e também pelo botão Atualizar. Os identificadores são etiquetas persistidas **somente neste aplicativo**, associadas ao MAC; não renomeiam o cliente no gateway nem no dispositivo. A interface do Huawei tem mecanismo próprio de nome por MAC, mas a escrita pelo aplicativo ainda não foi validada. IPs que coincidem com reservas DHCP ativas aparecem em verde como “Fixo”; endereços informados pelo gateway como estáticos sem reserva correspondente aparecem em verde como “Estático”. Essa classificação depende dos dados do Huawei.

Cada seção da rede tem filtros combináveis por faixa Wi-Fi e categoria. As categorias IoT, Celulares, Computadores e Rede podem ser atribuídas nos detalhes de um dispositivo; são salvas apenas no aplicativo e associadas ao MAC. As opções de rede refletem o mapeamento de SSIDs observado neste gateway.

Cada card abre detalhes da conexão e permite salvar um identificador ou criar/editar uma reserva DHCP, com o IP atual preenchido quando ainda não houver reserva. A identificação das redes reflete a configuração observada neste gateway: SSID1 é 2,4 GHz, SSID2 é convidados em 2,4 GHz e SSID5 é 5 GHz; outras redes são exibidas como não identificadas. Se essa configuração mudar, o mapeamento precisará ser atualizado. O botão de bloqueio permanece indisponível: o filtro Wi-Fi do gateway está desativado e a integração ainda não foi validada.

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

## Notificações no Discord

Na aba **Notificações**, informe a URL de webhook criada no canal do Discord e ative o monitoramento. A primeira leitura registra os dispositivos conhecidos pelo gateway como referência, sem enviar avisos, inclusive os que estiverem offline. O aplicativo verifica a rede a cada 30 segundos e notifica uma vez por MAC novo. Em caso de falha no envio, o dispositivo permanece pendente para uma próxima verificação enquanto estiver online. A URL e os MACs já vistos são guardados no volume `/data`; a URL não volta a ser exibida pela interface.

O botão **Testar webhook salvo** envia uma mensagem de teste ao canal, inclusive quando as notificações automáticas estão desativadas. Salve a URL antes de testar.

As notificações de novos dispositivos incluem um link direto para os detalhes no aplicativo. O endereço é aquele usado para o último login no Gateway Manager; os destinatários precisam conseguir acessá-lo e ter uma sessão no aplicativo. Se necessário, o link abre o card após o login. O endereço MAC é incluído no link.

O monitor roda no servidor enquanto existir uma sessão válida com o gateway, inclusive com a página fechada. O aplicativo recupera a sessão ao reabrir a página e tenta reconectar ao gateway se a sessão expirar. As credenciais ficam somente na memória do processo; após reiniciar o contêiner é necessário conectar novamente. Outra sessão administrativa pode encerrar a sessão do aplicativo. A detecção depende da lista online fornecida pelo gateway e não identifica conexões ocorridas entre verificações. Uma alteração de MAC pode ser tratada como um novo dispositivo.

O ícone para ZimaOS está disponível em `https://raw.githubusercontent.com/rafaels-santos/gateway-manager/master/static/icon.png`. Para uma instalação existente, use esse endereço no campo de ícone personalizado do aplicativo.

## Adicionar um modelo de gateway

O catálogo `/api/gateway-types` é gerado pelo registro `GATEWAY_ADAPTERS` em `app.py`. Para um novo modelo, implemente um adaptador próprio com `model_id`, `model_label`, `base`, `lock`, `login`, `devices`, `reservations`, `save`, `dhcp_config`, `save_dhcp`, `wifi_config`, `save_wifi` e `reboot`, seguindo os formatos de dados usados pela API e implementando verificação de sessão, validação e erros adequados. Registre-o somente após validar suas operações e permissões. O adaptador Huawei contém lógica específica do firmware e não é compatível automaticamente com outros modelos.
