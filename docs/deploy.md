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

1. **Servidor.** Um VPS Ubuntu pequeno resolve (1 vCPU, 2 GB de RAM, 20 GB de disco: o banco tem cerca de 85 MB). Prepare com:
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
| Código ou telas | `make deploy` |
| Banco ou snapshots (nova coleta/importação) | `make db-check` e depois `make deploy-data` (alias `deploy-db`). Os snapshots listados em `deploy/snapshots-local-only.txt` (insumos do custo do mandato) não são enviados; o servidor produz os seus no job mensal e eles ficam lá. Também envia as revisões do Placar (`data/reviews/chamber-vote-reviews-*.json` e `chamber-vote-segment-reviews-*.json`), que a fila editorial do servidor precisa para saber o que já foi revisado |
| Revisões novas do Placar | `make deploy-reviews`: envia só `data/reviews/`, sem tocar o banco; depois `sudo systemctl start painel-ingest-weekly.service` no servidor. Sem isso, a fila semanal conta essas votações como sem revisão |
| Cota do ano corrente | Nada: `painel-ingest.timer` atualiza no servidor todo dia (abaixo). `make deploy-data` continua válido para publicar uma base local, e substitui a do servidor |
| Ver se está no ar | `make deploy-status` |

Logs: `ssh SERVIDOR journalctl -u painel -f`.

## Atualização automática dos dados

A cota da Câmara e do Senado do ano corrente, os projetos e a situação dos projetos são atualizados
todo dia no próprio servidor por `painel-ingest.timer` (5h40 de Brasília, com até 15 min de atraso
aleatório). O timer chama
`python3 -m ingest.pipeline daily`, que executa, nesta ordem, e grava cada etapa em
`/opt/painel/data/status/daily.json` (histórico em `daily-history.jsonl`):

| Etapa | O que faz | Se falhar |
|---|---|---|
| `collect` | `ingest/legislative.py --year <ano corrente>` grava `data/imports/legislative.json` | Fonte indisponível vira execução **parcial** e preserva a fotografia anterior daquela fonte; coletor que morre interrompe |
| `validate` | Confere fontes, ano das notas (nunca importa outro ano no caminho padrão) e o que será substituído | Interrompe antes de tocar o banco |
| `backup` | Cópia consistente em `data/backups/na-lupa-daily-<data>.sqlite3`; mantém as 7 mais recentes | Interrompe |
| `stage` | Copia o banco publicado para `data/pipeline/`; o banco em uso nunca recebe escrita | Interrompe |
| `import` | Importação transacional na cópia (`backend.public_store`) | Transação desfeita; interrompe |
| `verify` | `quick_check`, chaves estrangeiras, versão do esquema e **guarda de regressão**: lista oficial caindo mais de 5% ou notas caindo mais de 10% não são publicadas | Interrompe; a cópia é descartada |
| `publish` | Troca atômica do arquivo do banco (`os.replace`); o cache do site invalida sozinho pela data do arquivo | Recusa se houver `-journal`/`-wal` pendente ao lado do banco |
| `profiles` | `ingest/profiles.py --collect`: contatos e gabinete que faltam no cache e projetos pelos arquivos anuais da Câmara (só o ano corrente é baixado de novo) | Execução **parcial**; o coletor preserva as observações anteriores das fichas |
| `project-status` | `ingest/project_status.py --collect` com validade dos arquivos anuais (20 h o ano corrente, uma semana os fechados) e detalhes só para andamentos novos | Execução **parcial**; o snapshot anterior fica |
| `notify` | E-mail em falha e parcial (sucesso só com `PAINEL_MAIL_ON_SUCCESS=1`) e ping opcional no monitor | Falha de envio fica registrada no status |

| `senate-projects`, `senate-activity` | Autoria e votações nominais do Senado desde fev/2023 (`--mandate`); só o ano corrente é consultado de novo | Execução **parcial**; snapshot anterior fica |

As etapas de snapshot rodam depois do banco publicado e não o desfazem. `--db-only` (ou
`make update-daily DB_ONLY=1`) pula todas. Na primeira execução no servidor, que não tem os caches de
`data/raw/`, a etapa `profiles` consulta o detalhe e a página de gabinete dos 513 deputados e baixa os
arquivos anuais de 2023 até o ano corrente (dezenas de MB cada, lidos um por vez); as seguintes usam os
caches. Confira na primeira execução a linha `conciliacao:` do log dessa etapa (ou `projectsArchive` em
`perfis.json`), que compara a lista de projetos dos arquivos com a da consulta antiga por deputado.

Os coletores derivam ano, meses encerrados e legislatura da data (`ingest/periods.py`), então as
viradas de mês e de ano não exigem edição de código; `PAINEL_TODAY=AAAA-MM-DD` no ambiente fixa a
data de referência quando for preciso reproduzir uma fotografia antiga. Só uma execução por vez
(lock em `data/status/pipeline.lock`). Os limites da guarda de regressão
são argumentos do comando (`--max-roster-drop`, `--max-expense-drop`); quando uma queda for legítima,
rode uma vez à mão com limites maiores, confira e deixe o timer seguir. O banco, os backups e os
caches ficam em `/opt/painel/data`; `/opt/painel/app/data` é um link para essa pasta, criado pelo
deploy, porque os coletores gravam em `<app>/data`.

Ativar (uma vez), depois do `make deploy`, que instala as unidades:

```sh
sudo install -m 0600 /opt/painel/app/deploy/pipeline.env.example /etc/painel/pipeline.env
sudo nano /etc/painel/pipeline.env                      # destinatário e SMTP (Gmail: senha de app)
sudo systemctl start painel-ingest.service && sudo journalctl -u painel-ingest -n 50   # primeira execução, assistida; "parcial" sai com código 0
sudo systemctl enable --now painel-ingest.timer painel-ingest-weekly.timer painel-ingest-monthly.timer
```

Acompanhar: `systemctl list-timers 'painel-ingest*'`, `journalctl -u painel-ingest -n 100`
e `make deploy-status`, que mostra o último resultado. Teste do e-mail no servidor:
`cd /opt/painel/app && sudo -u painel env $(sudo cat /etc/painel/pipeline.env | xargs) python3 -m ingest.pipeline test-mail`.
Localmente, `make update-daily DRY_RUN=1` faz tudo, menos trocar o banco (os snapshots das fichas são atualizados normalmente; use `DB_ONLY=1` para evitar).

### Job mensal

`painel-ingest-monthly.timer` (dia 10, 1h30 de Brasília) roda `python3 -m ingest.pipeline monthly`
(`make update-monthly`), a cadeia do custo do mandato e do Senado, com status em
`/opt/painel/data/status/monthly.json`. O mês de referência é o anterior (`--period AAAA-MM` para
outro); cada coletor é retomável, usa os caches e só busca o que falta, então um mês já coletado
custa pouco. A ordem:

1. `legislative-<ano>` para cada ano fechado do mandato (cota dos anos anteriores, com correções da fonte) e
   `quota-history`; se ambos derem certo, o histórico entra no banco pelo mesmo caminho do diário
   (`backup`, `stage`, `import-history`, `verify`, `publish`), com a guarda de regressão nas notas do histórico.
2. `payroll-<ano>`, `housing-<ano>` e `service-<ano>` para cada ano do mandato (folha individual, moradia e
   exercício da Câmara; meses já encerrados), `chamber-mandate-history` (gabinete dos anos anteriores e
   presença do ano corrente) e `mandate-cost` (composição da média).
3. `senate-office-pilot` (com `--auto-accept`: senador novo cujo nome de lotação é igual ao nome
   único do cadastro entra sozinho em `data/snapshots/senate-office-map-auto.json`; a tabela
   versionada `ingest/senate_office_map.json` prevalece), `senate-cost`, `senate-attendance` (PDFs do
   Diário; precisa de `pdfplumber`, instalado no venv pelo deploy), `senate-activity`,
   `senate-participation` e `tenure`.
4. `state-tax-revenue` e `build`, que remonta `dist/index.html` com a presença e os impostos estaduais novos.
5. `publish-data`, só com `PAINEL_DATA_RELEASE=1` em `/etc/painel/pipeline.env`: publica banco, snapshots e
   revisões do Placar como release de dados no GitHub, com a tag `data-<data>` e o token de `PAINEL_GITHUB_TOKEN`
   ([Dados e SQLite](data.md#publicar-a-base)). Em `--dry-run`, só monta o pacote em `data/releases/`.

Uma etapa que falha deixa a execução parcial, com e-mail, e as seguintes continuam; só a importação
do histórico no banco pode marcar a execução como falha, sem tocar o banco publicado. `--only a,b` e
`--skip c` (ou `ONLY=`/`SKIP=` no `make`) limitam a cadeia, por nome ou prefixo (`payroll` cobre
`payroll-2026`). Os dois jobs compartilham um lock: o que chegar segundo espera até 30 minutos.

Em um servidor novo, a primeira execução mensal coleta o histórico desde fevereiro de 2023 (folha e
moradia de 513 deputados por 45 meses) e pode levar algumas horas; o timeout da unidade é 12 h. Rode-a
assistida: `sudo systemctl start --no-block painel-ingest-monthly.service` e `journalctl -u painel-ingest-monthly -f`
(sem `--no-block`, o `start` de uma unidade `oneshot` só devolve o terminal quando ela termina).
Os insumos ficam em `/opt/painel/data/snapshots` e não são apagados pelo `make deploy-data`.

### Job semanal e fila editorial

`painel-ingest-weekly.timer` (segunda-feira, 3h de Brasília) roda `python3 -m ingest.pipeline weekly`
(`make update-weekly`): refaz o inventário das votações do Plenário do ano corrente até o dia
(`ingest.chamber_vote_inventory --collect`, cerca de 70 consultas) e monta a fila editorial
(`ingest/editorial_queue.py`) em `/opt/painel/data/reviews/editorial-queue.md` e `.json`. A fila cruza
os candidatos do inventário com todas as revisões locais e lista os sem revisão, os pendentes com
motivo e os alertas de tipo do inventário, e grava para cada candidato sem revisão um rascunho em
`chamber-vote-reviews-draft-<data>.json`, com ID, data, proposição, placar e links preenchidos e
`status: draft`, que o catálogo recusa até uma pessoa julgar; também avisa sobre os arquivos mantidos à mão
(`arrecadacao.json` com mais de 60 dias, senador da lista atual sem gabinete em
`ingest/senate_office_map.json`, contas municipais com exercício atrasado a partir de julho e a
fotografia das eleições antes do segundo turno). Nada é publicado: o catálogo do Placar continua
seguindo a revisão descrita em [Metodologia do Placar](voting-scoreboard.md). O e-mail sai quando há
candidato novo sem revisão desde a fila anterior, aviso de arquivo manual ou falha; status em
`data/status/weekly.json`.

### Eventos com data

O job semanal também executa `ingest/calendar_events.py`: sem rede, ele diz o que ainda falta
depois de uma data marcada e roda as ações pendentes.

- **Segundo turno (25/10/2026).** Depois da data, enquanto a fotografia das eleições e os caches de
  candidaturas e votos de 2026 forem anteriores ao turno, o semanal roda `make collect-elections` e
  `cities.py --collect --refresh-election`. Os dois pedem os arquivos do TSE por GET condicional:
  enquanto o TSE não regenerar os arquivos, a resposta `304` não transfere nada (o ZIP de votos tem
  cerca de 450 MB). Quando os arquivos passam da data do turno, o evento fica concluído. Depois de 90
  dias sem arquivo novo, vira aviso para conferência manual.
- **Troca de legislatura (1º/2/2027).** Trinta dias antes, o e-mail semanal avisa com o roteiro
  abaixo. Nos 45 dias seguintes à posse, a lista oficial muda a cada dia (posses, suplentes), e a
  guarda de regressão da lista no job diário aceita quedas de até 50% em vez de 5%; lista vazia
  continua sem substituir a anterior. O recorte "mandato atual" não muda sozinho.

### Troca de legislatura (roteiro para 1º/2/2027)

1. **Antes da posse**, confira o roadmap: manter o mandato 2023–2027 como histórico nas fichas é uma
   mudança de produto (telas e API), não de coleta. Sem isso, trocar o recorte apaga o mandato
   anterior do site.
2. **Na posse**, nada a fazer na cota: o job diário importa a nova lista oficial e preserva notas e
   alertas de quem saiu (`roster`, esquema v2). Confira `make deploy-status` nos primeiros dias.
3. **Quando decidir iniciar o novo recorte**, defina em `/etc/painel/pipeline.env`
   `PAINEL_MANDATE_START=2027-02-01`. Todos os coletores leem esse valor de `ingest/periods.py`
   (projetos, presença, votações e autoria do Senado, folha, moradia, histórico da cota, custo do
   mandato). Rode o mensal assistido (`sudo systemctl start painel-ingest-monthly.service`) e
   revise `docs/data.md`, que descreve o recorte em texto.
4. **Tempo de mandato** (`tenure.json`) e a legislatura em vigor seguem a data sozinhos.

Os jobs usam o interpretador `/opt/painel/venv/bin/python3`, criado pelo deploy com
`ingest/senate-requirements.txt`; o site continua no Python do sistema, sem dependências.

Se o processo morrer sem gravar status (timeout, falta de memória), `painel-ingest-failure@.service`
envia o aviso de último recurso para a unidade que falhou. O e-mail não detecta o timer que deixou de disparar; para isso,
defina `PAINEL_HEALTHCHECK_URL` (e as variantes `_WEEKLY` e `_MONTHLY`) com um monitor externo
(healthchecks.io ou similar), que avisa quando o ping não chega. Continuam manuais, com aviso da fila
editorial: o catálogo do Placar (revisão), Minha cidade (cidades, emendas, contas), eleições e os
arquivos mantidos à mão; a ordem de automação está em [Próximas etapas](roadmap.md).

## Rodar do próprio Mac (temporário)

Para mostrar o site sem servidor: rode `make prod` e, em outro terminal, `cloudflared tunnel run painel` com `~/.cloudflared/config.yml` igual ao exemplo (trocando `/etc/cloudflared/` por `~/.cloudflared/`). O site só fica no ar com o Mac ligado.

## Cuidados

- `.env`, o banco e os backups não vão para o git nem para a pasta do código no servidor.
- Cada ficha oferece o CSV com as notas da pessoa (`/api/c/gastos.csv`); o limite de tempo protege o servidor, mas, se houver abuso, ative *Rate limiting* na Cloudflare para `/api/`.

## Publicação automática pelo GitHub

O workflow `.github/workflows/deploy.yml` roda `make ci` (sintaxe e testes, sem dados privados ou downloads) em todo push e pull request. Em push na `main`, se passar, ele envia o código, instala as unidades do systemd (site e atualização automática) e o servidor monta a página com os snapshots complementares que já estiverem lá (`/opt/painel/data/snapshots`). O build não exige `editorial.json` nem qualquer snapshot; a lista e os totais de parlamentares vêm do SQLite em execução. Banco e snapshots nunca passam pelo GitHub: vão pelo `make deploy-data`, do seu computador. Rode esse comando para publicar uma nova base ou atualizar complementos locais.

Configuração (uma vez):

1. Crie uma chave só para o deploy: `ssh-keygen -t ed25519 -f ~/.ssh/painel-deploy -N "" -C github-deploy`.
2. Autorize-a no servidor: `ssh painel 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/painel-deploy.pub`.
3. No repositório do GitHub, em *Settings > Secrets and variables > Actions*, crie `DEPLOY_HOST` (IP), `DEPLOY_USER` (`ubuntu`) e `DEPLOY_SSH_KEY` (conteúdo de `~/.ssh/painel-deploy`, a chave **privada**).
4. Opcional: em *Settings > Environments*, crie `production` e exija aprovação manual antes de publicar.

## Peso da página

O HTML contém os metadados curtos dos quatro cartões de votação e os complementos pequenos que existirem nos snapshots. O roster, totais e despesas ficam no SQLite e são consultados pela API; o banco completo não é embutido no HTML. Os perfis complementares (`perfis.json`) ficam no servidor e cada ficha busca o seu em `/api/c/perfil/<id>`.

## Endereço público e buscadores

Defina o domínio no servidor para que `sitemap.xml`, `robots.txt` e os endereços canônicos usem sempre o mesmo
endereço. Use um override do systemd: o deploy reinstala `deploy/dashboard.service` a cada publicação, mas não
toca no override.

```sh
sudo mkdir -p /etc/systemd/system/painel.service.d
printf '[Service]\nEnvironment=PAINEL_SITE_URL=https://seudominio.com.br\n' | sudo tee /etc/systemd/system/painel.service.d/site-url.conf
sudo systemctl daemon-reload && sudo systemctl restart painel
```

Sem a variável, o servidor usa o `Host` que o Cloudflare Tunnel repassa.
Depois do deploy, envie `https://seudominio.com.br/sitemap.xml` no Google Search Console e no Bing Webmaster Tools.
