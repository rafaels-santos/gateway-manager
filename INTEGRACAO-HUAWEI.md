# Notas de integração: Huawei EG8145X6-10

Observações em modo somente leitura no firmware V5R024C10S106. Nenhuma configuração foi alterada.

- O login usa POST em `/asp/GetRandCount.asp` para obter um token e POST em `/login.cgi` com `UserName`, `PassWord` codificada em Base64, `Language` e `x.X_HW_Token`. Base64 não protege a senha; HTTP deve ser usado apenas em rede confiável.
- A interface DHCP está em `/html/bbsp/dhcpservercfg/dhcp2.asp`. O formulário expõe ativação do DHCP, início e fim do intervalo, duração e DNS primário e secundário. Há opções adicionais que precisam ser preservadas.
- Reservas estão em `/html/bbsp/dhcpstatic/dhcpstatic.asp`. O firmware usa `add.cgi` para adicionar, `set.cgi` para editar e `del.cgi` para excluir entradas `InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress`, com campos `x.Yiaddr` e `x.Chaddr` e token da página.
- Os detalhes de leitura, tratamento de sessão e token, validação das respostas e renomeação de clientes ainda precisam ser implementados e testados. Não se deve supor que a reserva DHCP altere o nome do dispositivo.
- O equipamento pode encerrar uma sessão existente quando outro usuário entra. Testes de autenticação e escrita devem ser isolados e as alterações reais não devem ser feitas sem autorização explícita.
