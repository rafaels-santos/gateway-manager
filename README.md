# Gateway Manager

Aplicativo para reservas DHCP no Huawei EG8145X6-10 (firmware V5R024C10S106). A integração de escrita é experimental: os formatos foram inspecionados no firmware e exercitados com gateway simulado, sem modificar o equipamento real. Confirme o resultado no painel do Huawei ao utilizar. A criação e edição de reservas são confirmadas por releitura; exclusão de reservas ainda não está implementada.

A aba Dispositivos lista clientes online de LAN e Wi-Fi, com nome informado pelo Huawei, IP e MAC. A lista é atualizada a cada 15 segundos enquanto a página está visível e também pelo botão Atualizar. Os identificadores são etiquetas persistidas **somente neste aplicativo**, associadas ao MAC; não renomeiam o cliente no gateway nem no dispositivo. A interface do Huawei tem mecanismo próprio de nome por MAC, mas a escrita pelo aplicativo ainda não foi validada. IPs que coincidem com reservas DHCP ativas, ou que o gateway identifica como estáticos, aparecem em verde; um endereço diferente da reserva não é marcado como fixo.

Cada card abre detalhes da conexão e permite salvar um identificador ou criar/editar uma reserva DHCP, com o IP atual preenchido quando ainda não houver reserva. A identificação das redes reflete a configuração observada neste gateway: SSID1 é 2,4 GHz, SSID2 é convidados em 2,4 GHz e SSID5 é 5 GHz; outras redes são exibidas como não identificadas. Se essa configuração mudar, o mapeamento precisará ser atualizado. O botão de bloqueio permanece indisponível: o filtro Wi-Fi do gateway está desativado e a integração ainda não foi validada.

As abas DHCP e DNS permitem consultar e alterar o intervalo principal, concessão e servidores DNS distribuídos aos clientes. A aba Redes Wi-Fi permite alterar o nome, ativação e transmissão de SSIDs existentes; senhas e configurações de segurança não são editadas. A aba Reinício envia um comando de reinício após confirmação textual, sem restaurar padrões de fábrica. Os comandos foram implementados com base no firmware observado e testados em simulação; ainda não foram executados neste gateway. Alterações podem interromper a rede ou exigir renovação DHCP; confira o painel Huawei caso o aplicativo não confirme uma alteração.

## Executar no ZimaOS

Use o Compose abaixo após o workflow de publicação no GitHub terminar com sucesso. Para atualizar uma instalação existente, baixe novamente a imagem e recrie o contêiner: `docker compose pull` e `docker compose up -d`.

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
