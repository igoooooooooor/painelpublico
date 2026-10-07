# Publicação

O site é o mesmo `backend.server` do desenvolvimento, rodando com `--prod` atrás de um **Cloudflare Tunnel**. O servidor não abre porta para a internet: o túnel sai dele até a Cloudflare, que entrega o domínio com HTTPS.

```text
visitante → Cloudflare (HTTPS, cache, proteção) → túnel → 127.0.0.1:8000 (backend.server --prod) → SQLite
```

## O que o modo `--prod` muda

- Respostas da API ficam em cache na memória e saem com `Cache-Control: public, max-age=300`. A chave inclui a data de modificação do banco: trocar o arquivo SQLite invalida o cache sozinho.
- Compressão gzip, `HEAD`, `/healthz` (verifica banco e build) e cabeçalhos de segurança (`X-Frame-Options`, `Referrer-Policy`, `nosniff`).
- Consultas que passam de 8 segundos são abortadas, para uma busca pesada não travar o site.
- Teste local igual à produção: `make prod`.

## Primeira vez

1. **Servidor.** Um VPS Ubuntu pequeno resolve (1 vCPU, 2 GB de RAM, 20 GB de disco: o banco tem ~1,3 GB). Prepare com:
   `ssh painel 'sudo bash -s' < deploy/setup-server.sh` (com `root`: `ssh root@IP 'bash -s' < ...`)
2. **Configuração local.** `cp .env.example .env` e preencha `SERVER` (o atalho do `~/.ssh/config`, ex.: `painel`). Com usuário comum (`ubuntu`) os comandos usam `sudo`; entrando como root, defina `SUDO=` vazio.
3. **Banco e código.** `make deploy-db` e depois `make deploy`. O `deploy` roda `make check` antes e para se algum teste falhar.
4. **Túnel.** No servidor:
   ```sh
   cloudflared tunnel login                          # abre um link; autorize o domínio
   cloudflared tunnel create painel                  # mostra o TUNNEL_ID
   cloudflared tunnel route dns painel seudominio.com.br
   cloudflared tunnel route dns painel www.seudominio.com.br
   mkdir -p /etc/cloudflared && cp ~/.cloudflared/*.json /etc/cloudflared/
   cp /opt/painel/app/deploy/cloudflared.example.yml /etc/cloudflared/config.yml   # edite TUNNEL_ID e domínio
   cloudflared service install && systemctl enable --now cloudflared
   ```
5. **Cloudflare (painel do site).** SSL/TLS em *Full*; *Always Use HTTPS* ligado.

## Atualizações

| O que mudou | Comando |
|---|---|
| Código, telas ou snapshots | `make deploy` |
| Banco ou snapshots (nova coleta/importação) | `make db-check` e depois `make deploy-data` (alias `deploy-db`) |
| Ver se está no ar | `make deploy-status` |

Logs: `ssh SERVIDOR journalctl -u painel -f`.

## Rodar do próprio Mac (temporário)

Para mostrar o site sem servidor: rode `make prod` e, em outro terminal, `cloudflared tunnel run painel` com `~/.cloudflared/config.yml` igual ao exemplo (trocando `/etc/cloudflared/` por `~/.cloudflared/`). O site só fica no ar com o Mac ligado.

## Cuidados

- `.env`, o banco e os backups não vão para o git nem para a pasta do código no servidor.
- A ferramenta de busca avançada expõe CSV de despesas; o limite de tempo protege o servidor, mas, se houver abuso, ative *Rate limiting* na Cloudflare para `/api/`.

## Publicação automática pelo GitHub

O workflow `.github/workflows/deploy.yml` roda `make ci` (sintaxe e testes, sem dados privados) em todo push e pull request. Em push na `main`, se passar, ele envia o código e o servidor monta a página com os snapshots que já estão lá (`/opt/painel/data/snapshots`). Banco e snapshots nunca passam pelo GitHub: vão pelo `make deploy-data`, do seu computador. **Antes do primeiro deploy automático, rode `make deploy-data` uma vez.**

Configuração (uma vez):

1. Crie uma chave só para o deploy: `ssh-keygen -t ed25519 -f ~/.ssh/painel-deploy -N "" -C github-deploy`.
2. Autorize-a no servidor: `ssh painel 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/painel-deploy.pub`.
3. No repositório do GitHub, em *Settings > Secrets and variables > Actions*, crie `DEPLOY_HOST` (IP), `DEPLOY_USER` (`ubuntu`) e `DEPLOY_SSH_KEY` (conteúdo de `~/.ssh/painel-deploy`, a chave **privada**).
4. Opcional: em *Settings > Environments*, crie `production` e exija aprovação manual antes de publicar.

## Peso da página

A página leva só os dados pequenos (amostra editorial, presença, votos, arrecadação): ~1,3 MB, ~600 KB comprimida. Os perfis complementares (`perfis.json`, ~15 MB com projetos) ficam no servidor e cada ficha busca o seu em `/api/c/perfil/<id>`. Não volte a embutir arquivos grandes em `scripts/build.py`.
