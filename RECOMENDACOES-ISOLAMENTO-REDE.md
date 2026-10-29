# Recomendações de isolamento de dispositivos e Wi-Fi de convidados

Registrado em 28/10/2026 para retomada futura.

Equipamento: Huawei EG8145X6-10 · HW 343D.D · firmware V5R024C10S106.

## Objetivo

Impedir dispositivos indesejados de acessar a rede ou permitir apenas internet, sem acesso aos outros clientes, ao ZimaOS ou à administração dos equipamentos.

## Evidências da inspeção

A inspeção foi somente de leitura; nenhuma configuração do roteador foi alterada.

- Existe filtro MAC Wi-Fi com lista de bloqueio e regras por SSID.
- Na última leitura, havia uma regra cadastrada e o filtro global estava desativado. Uma regra cadastrada nessa condição não representa bloqueio efetivo.
- A página descreve filtragem de tráfego/acesso à internet. Não foi comprovado se impede a associação ao Wi-Fi ou encerra imediatamente uma conexão existente.
- A página básica WLAN contém suporte de isolamento por SSID no código, mas o controle está oculto/desabilitado na versão/conta observada (`staIsolationFlag=0`). As entradas de isolamento consultadas estavam em 0.
- O SSID `Rafael_Convidados` existe, mas seu nome não comprova segregação da LAN.
- A documentação genérica de Guest Wi-Fi da Huawei encontrada aplica-se a outros modelos e não confirma essas funções no EG8145X6-10.

## Alternativas

| Alternativa | Aplicação | Limitações |
| --- | --- | --- |
| Trocar a senha Wi-Fi, desativar WPS e encerrar conexões antigas | Quando o dispositivo não deve ter acesso algum; reconectar somente aparelhos autorizados | Exige reconectar os aparelhos legítimos; não foi executado |
| Bloqueio por MAC | Controle complementar por dispositivo e SSID | Depende de filtro ativo; comportamento de associação ainda precisa de teste; MACs privados podem mudar |
| Rede de convidados em segmento separado, com firewall | Manter internet e impedir acesso à rede principal | Depende de suporte real no roteador/firmware |
| Roteador/AP adicional com segmentação | Contornar limitações do Huawei | Deve oferecer rede isolada ou VLANs, firewall e isolamento entre clientes; NAT sozinho não comprova isolamento da rede a montante |

## Configuração parcial disponível no SSID de convidados

Confirmado na interface do Huawei:

- Nome e senha próprios para o SSID.
- Ativação/desativação do SSID.
- Limite de clientes associados.
- Divulgação do nome da rede.
- Autenticação, criptografia e WPS.
- Filtro MAC associado ao SSID.

Não confirmado ou não exposto na interface atual:

- Bloqueio de convidados para a LAN.
- Isolamento entre os próprios convidados.
- DHCP/sub-rede e DNS exclusivos para convidados.
- Limitação de velocidade exclusiva da rede de convidados.

Senha própria e limite de clientes controlam o acesso, mas não demonstram isolamento.

## Política desejada: internet apenas

Em equipamento que ofereça os recursos necessários:

1. Criar rede de convidados/IoT em sub-rede ou VLAN separada.
2. Permitir saída para internet.
3. Bloquear acesso à LAN principal, ao ZimaOS e à administração dos equipamentos.
4. Permitir os serviços necessários, como DHCP e DNS.
5. Aplicar política equivalente ao IPv6.
6. Ativar isolamento entre clientes, considerando também clientes em bandas e APs diferentes.

Isolamento entre clientes do mesmo AP e firewall entre redes são controles complementares. Apenas mudar a faixa de IP, ocultar o SSID ou usar NAT não é prova de isolamento completo.

## Recomendação para este ambiente

Manter aparelhos confiáveis na rede principal e colocar convidados/IoT em rede separada por firewall. Primeiro, verificar com a operadora se o firmware/perfil administrativo permite essa configuração. Se não permitir, avaliar um roteador/AP adicional que ofereça os controles necessários.

O Gateway Manager em Docker pode administrar políticas suportadas pelo equipamento. Ele não consegue impor isolamento ao tráfego que circula diretamente entre os outros clientes da rede.

## Roteiro para retomada

- Confirmar com a operadora suporte a isolamento, rede de convidados segregada e recursos liberados para esta versão.
- Escolher explicitamente um cliente de teste antes de qualquer mudança real.
- Revisar todas as regras existentes antes de ativar o filtro MAC: a ativação aplica também as regras previamente cadastradas.
- Testar reconexão Wi-Fi do cliente bloqueado em cada SSID/banda relevante.
- Verificar acesso à internet, ao gateway, ao ZimaOS e a outro cliente, em IPv4 e IPv6 quando disponíveis. Ping sozinho não basta: testar também serviços conhecidos.
- Testar comunicação entre convidados no mesmo AP e em bandas/APs diferentes.
- Definir plano de reversão e preservar acesso administrativo antes de aplicar alterações.
- Somente após os testes, representar no app a capacidade efetivamente confirmada: filtragem de tráfego, impedimento de associação ou isolamento.

## Fontes consultadas

- [Huawei — Guest Wi-Fi (outros modelos; não comprova suporte no EG8145X6-10)](https://consumer.huawei.com/en/support/content/en-us15806364/)
- [OpenWrt — Rede de convidados com interface e firewall próprios](https://openwrt.org/docs/guide-user/network/wifi/guestwifi/configuration_webinterface)
- [OpenWrt — Opções adicionais e isolamento entre interfaces](https://openwrt.org/docs/guide-user/network/wifi/guestwifi/extras)
- [Apple — Endereços Wi-Fi privados e mudanças de MAC](https://support.apple.com/en-nz/102509)

As referências OpenWrt descrevem alternativas de arquitetura; não são instruções para instalar OpenWrt nesta ONT Huawei.
