# Gateway Manager

Protótipo da tela inicial para gateway router. 

## Instalar no ZimaOS remoto

Crie um aplicativo Docker Compose no ZimaOS e cole:

```yaml
services:
  gateway-manager:
    build:
      context: https://github.com/rafaels-santos/gateway-manager.git#master
    ports:
      - "8080:8080"
    restart: unless-stopped
```

O Docker constrói a imagem a partir do repositório; o servidor precisa acessar o GitHub e ter acesso de leitura ao repositório. Se ele for privado, configure a autenticação Git no ambiente de construção. Caso o instalador do ZimaOS não aceite `build`, use Docker Compose pelo terminal com este arquivo e execute `docker compose up -d --build`.

Acesse `http://IP_DO_ZIMAOS:8080`. Para atualizar, reconstrua o serviço com `docker compose up -d --build`. A porta 8080 pode ser alterada no lado esquerdo do mapeamento.

A página permite abrir a interface original do gateway. Para implementar a integração é necessário inspecionar as telas autenticadas e as requisições do firmware, sem compartilhar senhas ou cookies.
