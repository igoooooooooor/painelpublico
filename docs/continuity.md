# Continuidade

Este guia existe para que qualquer pessoa consiga pegar o projeto e manter o site no ar sem depender de quem o criou: se o repositório mudar de dono, se o servidor sair do ar ou se o site precisar ser republicado em outro endereço. Tudo o que o site precisa está em dois lugares públicos: o código, neste repositório (licença MIT), e a base, nos [releases de dados](https://github.com/igoooooooooor/painelpublico/releases) (licença CC BY 4.0; ver [Aviso legal](../LEGAL-NOTICE.md)).

## Rodar o site em dez minutos

Requer Python 3.10+ e, para os testes de frontend, Node.js 18+. Nenhum pacote externo.

```sh
git clone https://github.com/igoooooooooor/painelpublico.git
cd painelpublico
make fetch-data   # baixa o último release de dados, confere SHA-256, instala em data/ e monta a página
make dev          # http://127.0.0.1:8000/
```

Pronto: é o mesmo banco, os mesmos snapshots e as mesmas revisões do Placar que o site público usa na data da tag. `make check` roda build, sintaxe e testes. Detalhes em [Dados e SQLite](data.md#baixar-a-base).

## Publicar em um servidor próprio

1. Faça um fork (ou um clone com outro remoto) e ajuste `GITHUB_REPO` em `scripts/publish_data.py` se o repositório mudar de endereço; o `make fetch-data` e o `make publish-data` apontam para lá.
2. Prepare um servidor Linux com `deploy/setup-server.sh` e siga [Publicação](deploy.md): `make deploy` envia o código, `make deploy-data` envia banco e snapshots a partir do seu computador. Com `make fetch-data` feito, você já tem tudo o que `make deploy-data` precisa.
3. Copie `deploy/pipeline.env.example` para `/etc/painel/pipeline.env` e ligue os timers. Eles fazem o trabalho de rotina sozinhos:
   - diário: cota do ano corrente, perfis, situação dos projetos e Senado;
   - semanal: inventário das votações do Plenário e fila editorial do Placar;
   - mensal: custo do mandato, histórico da cota, Senado, página e, com `PAINEL_DATA_RELEASE=1` e um token, o **release de dados no GitHub**.
4. O endereço público passa por um túnel do Cloudflare (`deploy/cloudflared.example.yml`); qualquer domínio serve.

Em um servidor novo, a primeira execução mensal recolhe o histórico desde 2023 e pode levar horas; como o `fetch-data` já traz os snapshots, ela só completa o que faltar.

## O que é automático e o que depende de uma pessoa

Automático, com fontes e cobertura registradas nos próprios snapshots:

- cota parlamentar, perfis, projetos, custo do mandato, presença, votos e licenças do Senado;
- inventário das votações do Plenário (a lista bruta de candidatos ao Placar);
- backups, verificação de regressão, e-mail de falha e o release mensal de dados.

Depende de decisão humana, e por isso vai no release de dados para ninguém precisar refazer:

- **Placar**: quais votações entram, o que Sim e Não significavam e os trechos destacados. As decisões ficam em `reviews/chamber-vote-reviews-*.json` e `chamber-vote-segment-reviews-*.json`, versionadas no Git; o catálogo sai com `make collect-votes`. A metodologia está em [Placar](voting-scoreboard.md). O `make update-weekly` monta a fila do que está pendente.
- **Curadoria pontual**: `editorial.json`, a tabela de gabinetes do Senado (`ingest/senate_office_map.json`), Minha cidade e eleições. O job semanal avisa quando algum deles precisa de atenção.

Sem ninguém revisando o Placar, o site continua funcionando com o catálogo publicado no último release; ele só deixa de ganhar votações novas.

## Se o site tiver de sair do ar

O código e os dados continuam públicos e licenciados para reuso. Quem quiser republicar segue "Publicar em um servidor próprio" acima; o nome, o domínio e a aparência podem ser outros, bastando citar "Painel Público" e o release usado, como pede a CC BY 4.0. O [Aviso legal](../LEGAL-NOTICE.md) descreve o que o site é e o que não é: um projeto independente que reúne informações que os órgãos públicos já publicam, com link para a fonte oficial em cada número.

## Onde está cada coisa

| O quê | Onde |
|---|---|
| Visão geral e comandos | [README](../README.md) |
| Arquitetura e fluxo dos dados | [Arquitetura](architecture.md) |
| Fontes, limitações, importação, releases | [Dados e SQLite](data.md) |
| Regras dos alertas | [Alertas](alerts.md) |
| Metodologia do Placar | [Placar](voting-scoreboard.md) |
| Servidor, timers, túnel, e-mail | [Publicação](deploy.md) e [Operação](operations.md) |
| Próximas etapas | [Roteiro](roadmap.md) |
| Design | [Design system](design-system.md) |
