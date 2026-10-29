# Gateway Manager

Painel web para gerenciar a rede interna de gateways compatíveis. Reúne dispositivos, Wi-Fi, endereçamento, diagnósticos e notificações em uma interface única, com instalação por Docker.

## Compatibilidade

O adaptador disponível é o **Huawei EG8145X6-10**. A disponibilidade de cada recurso depende do firmware, do perfil autenticado e dos campos reconhecidos na sessão. Outros modelos precisam de um adaptador próprio; a seleção manual não os torna automaticamente compatíveis.

## Recursos

- **Dispositivos:** clientes online, offline e bloqueados, IP/MAC, identificadores e categorias locais, filtros e atualização periódica.
- **Wi-Fi:** seleção de redes por SSID e banda, nome, ativação, divulgação, limite de clientes, autenticação, senha e gerenciamento de redes adicionais. Ordem: principal 2,4 GHz, principal 5 GHz, adicionais e convidados.
- **Rádios:** potência, canal e largura por banda, conforme o perfil reconhecido. Ajustes de rádio afetam todos os SSIDs daquela banda.
- **LAN e IPs:** DHCP e reservas IPv4, DNS distribuído aos clientes, nomes DNS locais, IPv6/DNSv6 e prévia de alteração do endereço LAN.
- **Monitoramento:** User/AP Logs com filtros e download, histórico local, inventário, topologia e diagnóstico TCP limitado à rede interna.
- **Notificações:** múltiplas integrações com Discord, Telegram, WhatsApp Cloud API, Slack e webhooks HTTPS, com eventos e mensagens configuráveis.
- **Manutenção:** importação/exportação de identificadores e reservas, consulta de firmware e reinício explícito do equipamento.

Os identificadores do aplicativo são associados ao MAC e não renomeiam automaticamente o cliente no sistema operacional ou no gateway. Reservas IPv6 dependem do modo DHCPv6; não têm efeito em SLAAC. Uma regra MAC ou um SSID de convidados não comprova isolamento completo entre clientes.

O aplicativo não administra PPPoE, WAN, credenciais da operadora, GPON ou serviços externos do roteador. Não instala firmware; exibe informações e referências oficiais quando disponíveis.

## Instalação com Docker

Requisitos: Docker Engine com Compose e acesso do contêiner à rede do gateway. A imagem é publicada para `linux/amd64` e `linux/arm64`.

```sh
docker compose up -d
```

Abra `http://localhost:8080` no próprio servidor, ou use o endereço do servidor na rede local. Informe o IP do gateway e suas credenciais. Nenhum endereço de gateway ou credencial vem pré-configurado.

O arquivo `docker-compose.yml` inclui persistência, verificação de saúde, limite de logs, reinício automático e metadados para importação no ZimaOS. Ele é um exemplo genérico para **novas instalações**. Em uma instalação existente, mantenha o volume e as configurações de implantação originais para preservar seus dados.

| Variável | Padrão | Uso |
| --- | --- | --- |
| `GATEWAY_MANAGER_PORT` | `8080` | Porta publicada pelo Compose |
| `COOKIE_SECURE` | `0` | Use `1` quando o acesso ao app ocorrer exclusivamente por HTTPS |
| `DATA_DIR` | `/data` no contêiner | Diretório persistente do aplicativo |
| `PORT` | `8080` | Porta interna do servidor HTTP |

O volume `gateway-manager-data` guarda o estado do aplicativo. Não remova esse volume durante uma atualização. O exportador portátil leva identificadores/categorias e reservas IPv4; ele não substitui um backup completo do volume.

Para atualizar:

```sh
docker compose pull
docker compose up -d
```

`pull_policy: always` verifica a imagem ao executar o Compose; isso **não** cria um atualizador em segundo plano. O Compose não monta o socket Docker nem instala serviços com controle sobre o host.

## Segurança e operação

- Use em uma rede administrativa confiável. Para acesso remoto, proteja o serviço com VPN ou um proxy HTTPS com controle de acesso; não publique a porta diretamente na internet.
- O contêiner executa sem usuário root, sem capabilities Linux e sem elevação de privilégios. O estado gravável fica no volume persistente.
- As credenciais do gateway ficam na memória da sessão do servidor. Reiniciar o aplicativo exige nova conexão; alguns firmwares também limitam sessões simultâneas.
- URLs de hooks e tokens das integrações são armazenados no banco local para permitir notificações. Proteja o volume e seus backups: esses dados não são criptografados em repouso pelo aplicativo e não devem ser adicionados ao Git.
- As respostas autenticadas usam `Cache-Control: no-store`; cookies de sessão usam `HttpOnly` e `SameSite=Strict`. Ative `COOKIE_SECURE=1` somente quando houver HTTPS.
- Alterações de configuração exigem confirmação e releitura quando suportadas. Mudanças de Wi-Fi, DHCP e LAN podem interromper o acesso; mantenha uma alternativa de conexão. Não há promessa de rollback automático.
- As integrações de escrita dependem de contratos específicos do firmware. Testes automatizados com gateways simulados não substituem o aceite operacional com clientes reais.

## Organização do código

```text
app.py                 Servidor HTTP e coordenação dos fluxos
services/              Persistência, notificações e operações da rede
gateway_adapters/      Protocolos, parsers e adaptadores dos gateways
static/                Interface web e navegação
tests/                 Testes de regressão e segurança
tools/                 Verificações do repositório
```

O adaptador concentra os objetos e comandos permitidos do fabricante. Os serviços cuidam do estado local; a interface usa as rotas explícitas da aplicação, sem um proxy genérico para comandos do roteador.

## Desenvolvimento

Requisitos: Python 3.12 ou superior e Node.js para os testes da interface. O backend usa a biblioteca padrão do Python, sem instalação de pacotes adicionais.

```sh
python app.py
```

Validação:

```sh
python tools/check_repository.py
python -m unittest discover -s tests -v
node --test tests/navigation.test.cjs
```

O CI verifica os testes, os arquivos JavaScript, padrões comuns de credenciais e a inicialização do contêiner nas duas arquiteturas. A verificação de credenciais é preventiva e não substitui revisão de código nem auditoria de segurança.
