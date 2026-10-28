# Gateway Manager

Protótipo da tela inicial para gateway router. 

## Instalar no ZimaOS remoto

Após a conclusão bem-sucedida do workflow **Publish container** no GitHub, use o nome de imagem `ghcr.io/rafaels-santos/gateway-manager:latest` ou crie um aplicativo Docker Compose com:

```yaml
services:
  gateway-manager:
    image: ghcr.io/rafaels-santos/gateway-manager:latest
    ports:
      - "8080:8080"
    restart: unless-stopped
```

A imagem é publicada no GitHub Container Registry para `linux/amd64` e `linux/arm64`. O servidor precisa ter acesso ao `ghcr.io`. Se o pacote for privado, será necessário torná-lo público nas configurações do pacote no GitHub ou autenticar o Docker no GHCR com uma conta autorizada. A visibilidade do repositório não garante a visibilidade do pacote.

Acesse `http://IP_DO_ZIMAOS:8080`. Para atualizar pelo terminal, use `docker compose pull` seguido de `docker compose up -d`. A porta 8080 pode ser alterada no lado esquerdo do mapeamento.

A página permite abrir a interface original do gateway. Para implementar a integração é necessário inspecionar as telas autenticadas e as requisições do firmware, sem compartilhar senhas ou cookies.
