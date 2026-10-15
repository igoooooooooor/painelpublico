# Painel Público

Site para entender, em linguagem simples, gastos, presença e votações de deputados(as) e senadores(as), sempre com link para a fonte oficial.

- **Políticos**: ficha de cada parlamentar com o custo do mês mais recente e a média do mandato (salário, auxílios, cota e verba de gabinete), notas da cota, presença e votos.
- **Placar**: votações nominais do texto principal no Plenário da Câmara e, dentro de cada uma, as decisões sobre trechos (destaques e emendas), com o que significava Sim e Não.
- **Alertas**: registros da cota que merecem conferência, não conclusões de irregularidade.
- **Comparar**: políticos ou partidos lado a lado, com imagem para compartilhar.
- **Metodologia** e **Sobre**: as regras de cada número, as fontes, a licença dos dados e o canal de correção, nas páginas `/metodologia` e `/sobre`.

Cada página (fichas, votações do Placar, seções) chega com o conteúdo essencial no HTML, com título, canonical e dados estruturados: funciona sem JavaScript e pode ser lida por buscadores e assistentes ([Arquitetura](docs/architecture.md#endereços-e-buscadores)).

A área **Minha cidade** reúne a base nacional do IBGE, os resultados eleitorais do TSE, as emendas municipais do Portal da Transparência e as contas anuais do SICONFI, com busca por nome, fontes, períodos e indicação de dados ausentes.

É um projeto pessoal, independente e apartidário, sem vínculo com partidos, políticos ou órgãos públicos. Ele apenas reúne e organiza informações que os próprios órgãos já publicam. Veja o [Aviso legal](LEGAL-NOTICE.md).

## Rodar localmente

Requer **Python 3.10+**. Para os testes de frontend, **Node.js 18+**. A aplicação, o build e os testes não precisam de pacotes Python externos. A coleta opcional de presença do Senado em PDFs requer `pdfplumber`; veja a instalação em [Dados e SQLite](docs/data.md).

```sh
make dev
```

Abra [localhost:8000](http://127.0.0.1:8000/). `make dev` gera `dist/index.html` e `dist/assets/` e inicia a API local. Não faz downloads nem reimporta o banco. Depois de editar o frontend, rode `make build` e recarregue a página; alterações Python exigem reiniciar o servidor.

A base já existente em `data/na-lupa.sqlite3` é preservada. Este repositório publica somente código, testes e documentação: banco, snapshots complementares, downloads e credenciais são locais.

**Em um clone novo**, `make fetch-data` baixa o [release de dados](https://github.com/igoooooooooor/painelpublico/releases) mais recente (banco, snapshots e revisões do Placar, com conferência de SHA-256), instala em `data/` e monta a página; depois, `make dev`. Sem rede, `make check`, `make build` e `make dev` funcionam com `make db-init` (banco vazio) e sem snapshots. O build não baixa dados. No servidor, a cota do ano corrente é atualizada todo dia e o release de dados sai todo mês por timers do systemd. Para assumir o projeto do zero, siga [Continuidade](docs/continuity.md).

Sem Make:

```sh
python3 scripts/build.py
python3 -m backend.server --port 8000
```

## Comandos

| Comando | Uso |
|---|---|
| `make dev PORT=8001` | Rodar em outra porta |
| `make build` | Gerar HTML em `dist/` |
| `make check` | Build, sintaxe e testes locais |
| `make fetch-data` | Baixar o release de dados mais recente, instalar em `data/` e montar a página; `TAG=data-AAAA-MM-DD` escolhe outro, `FORCE=1` substitui o banco |
| `make db-init` | Criar/atualizar esquema sem apagar dados |
| `make db-check` | Conferir integridade e cobertura numérica |
| `make audit-numbers` | Conferir consistência de proporções, cobertura, custos, presença e placares na base local, sem alterar dados |
| `make db-backup` | Backup SQLite consistente e datado |
| `make import` | Importar arquivos locais de `data/imports/` |
| `make collect-legislative YEAR=2026` | Baixar dados da Câmara e do Senado |
| `make collect-profiles` | Coletar os complementos das fichas (projetos pelos arquivos anuais da Câmara); depois rode `make build` |
| `make collect-senate YEAR=2026` | Coletar presença registrada de 2026 e votos/autoria do mandato; depois rode `make build` |
| `make collect-senate-mandate` | Coletar votos nominais e autoria desde fev/2023, sem baixar PDFs de presença |
| `make collect-project-status` | Consultar a situação dos projetos já listados, com fontes e datas; atualização e modo offline em [Dados e SQLite](docs/data.md) |
| `make collect-vote-inventory YEAR=2026` | Levantar votações do Plenário para o Placar; relatório local e metodologia em [Piloto do Placar](docs/voting-scoreboard.md) |
| `make collect-votes THROUGH=2026-10-09` | Gerar o catálogo paginado a partir das revisões locais, com votos individuais separados; [coleta e cobertura](docs/voting-scoreboard.md) |
| `make collect-accounts YEAR=2025` | Coletar contas anuais municipais do SICONFI, com cache e reconstrução offline |
| `make collect-amendments YEAR=2026` | Coletar emendas por município e ano da proposta; valores empenhados e pagos separados |
| `make collect-cities` | Coletar a base nacional de Minha cidade (IBGE e TSE); reconstrução offline em [Dados e SQLite](docs/data.md) |
| `make collect-elections` | Ligar a lista atual às candidaturas de 2026 no TSE; depois rode `make build` |
| `make collect-mandate-cost` | Coletar folha e moradia da Câmara nos meses já encerrados do ano, para o custo do mandato |
| `make collect-mandate-history` | Coletar os anos fechados do mandato na Câmara e recompor a média (faça `make db-backup` antes) |
| `make update-daily` | Atualização diária da cota: coleta, importa em cópia, verifica e publica; no servidor roda por timer ([Publicação](docs/deploy.md)) |
| `make update-weekly` | Inventário do Plenário e fila editorial do Placar; no servidor roda por timer |
| `make update-monthly` | Custo do mandato, histórico da cota, Senado e página; no servidor roda por timer |
| `make pipeline-status` | Último resultado das atualizações automáticas |
| `make prod` | Rodar como em produção (cache, só localhost) |
| `make deploy` / `make deploy-data` | Publicar código / banco e snapshots no servidor; push na `main` já publica o código ([Publicação](docs/deploy.md)) |
| `make publish-data` | Publicar banco, snapshots e revisões do Placar como release de dados no GitHub; `DRY_RUN=1` só monta o pacote; no servidor sai todo mês ([Dados e SQLite](docs/data.md#publicar-a-base)) |
| `make deploy-status` | Ver se o site está no ar |

## Estrutura

```text
backend/        API Python, consultas e esquema SQLite
frontend/       template HTML, scripts e design system
scripts/        montagem do app
ingest/         coletores oficiais; editorial/ contém complementos manuais da Câmara
data/           snapshots, banco e downloads locais, fora do Git
reviews/        revisões editoriais do Placar, versionadas
tests/          testes Python e Node
docs/           arquitetura, dados, visual e próximas etapas
dist/           app gerado, ignorado no Git
```

## Convenções

- [Operação](docs/operations.md): como o dado chega ao site, os jobs automáticos, o que cada e-mail significa e o que ainda depende de uma pessoa. Comece por aqui para manter o projeto.
- [Arquitetura](docs/architecture.md): divisão de responsabilidades e fluxo dos dados.
- [Design system](docs/design-system.md): componentes, temas e bordas neutras.
- [Buscadores e assistentes](docs/seo.md): como cada página é lida sem JavaScript, o que ficou fora e como medir.
- [Dados e SQLite](docs/data.md): fontes, limitações, importação e backups.
- [Continuidade](docs/continuity.md): como assumir o projeto do zero, o que é automático e o que depende de uma pessoa.
- [Alertas da cota](docs/alerts.md): regras, prazos, cobertura, simulação e decisões registradas.
- [Contribuição](CONTRIBUTING.md): branches curtas, commits por finalidade e verificações.
- [Próximas etapas](docs/roadmap.md): expansão planejada, separada da cobertura entregue.

O servidor usa `127.0.0.1` por padrão e serve somente o app e a API. O código está em [igoooooooooor/painelpublico](https://github.com/igoooooooooor/painelpublico); publicar código no GitHub não publica o site nem a base. A instalação do servidor e do túnel está descrita em [Publicação](docs/deploy.md). `.env.example` e os arquivos `*.example.*` contêm apenas modelos de configuração.

## Licença

Código sob a [licença MIT](LICENSE). Os [releases de dados](https://github.com/igoooooooooor/painelpublico/releases) estão sob [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt-br); as informações pertencem às fontes públicas indicadas em [Dados e SQLite](docs/data.md). Veja também o [Aviso legal](LEGAL-NOTICE.md).
