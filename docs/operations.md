# Operação: como o dado chega ao site

Guia para quem vai manter o Painel Público sem ter participado do início. Ele conta a história de
um dado, da fonte oficial à tela, diz o que roda sozinho, o que ainda depende de uma pessoa e o que
fazer quando chega um e-mail. Os detalhes de cada fonte estão em [Dados e SQLite](data.md); os
comandos de servidor, em [Publicação](deploy.md). Este guia é o mapa; aqueles são o território.

## Em uma página

```text
fontes oficiais (Câmara, Senado, TSE, IBGE, Tesouro, Portal da Transparência)
        │  coletores em ingest/ (só biblioteca padrão do Python)
        ▼
data/raw/        caches das respostas, nunca no Git
data/imports/    documento normalizado da cota do ano corrente
data/snapshots/  complementos em JSON (perfis, projetos, custo do mandato, Senado, cidades…)
        │  backend/public_store.py importa a cota no SQLite; os snapshots são lidos direto
        ▼
data/na-lupa.sqlite3  banco com listas oficiais, notas da cota e sinais de alerta
        │  backend/server.py serve /api/* e dist/index.html
        ▼
site
```

Três princípios atravessam tudo:

- **Dado ausente não é zero.** Uma fonte que falha preserva a última fotografia boa, marcada como
  desatualizada, e nunca grava zero no lugar.
- **O banco em uso nunca recebe escrita direta.** Importações acontecem em uma cópia, passam por
  verificação e trocam o arquivo de uma vez só.
- **Publicar é decisão de pessoa onde há interpretação.** O Placar e o recorte do mandato não
  mudam sozinhos; o sistema aponta o trabalho e espera.

## Os três jobs

No servidor, três timers do systemd rodam `ingest/pipeline.py`. Cada execução grava
`data/status/<job>.json` (última execução) e `data/status/<job>-history.jsonl` (histórico), e
avisa por e-mail quando precisa.

| Job | Quando (Brasília) | O que faz | E-mail |
|---|---|---|---|
| `daily` | todo dia, 5h40 | Cota da Câmara e do Senado do ano corrente no banco; perfis (projetos pelos arquivos anuais), situação dos projetos, autoria e votações do Senado | Só em falha ou resultado parcial |
| `weekly` | segunda, 3h | Inventário das votações do Plenário, fila editorial do Placar, avisos sobre arquivos mantidos à mão, eventos com data (eleições) | Quando há trabalho novo para uma pessoa, ou falha |
| `monthly` | dia 10, 1h30 | Custo do mandato (folha, moradia, exercício, gabinete, presença), histórico da cota no banco, Senado (folha, exercício, presença, participação, tempo de mandato), impostos estaduais e remontagem da página | Só em falha ou resultado parcial |

Os jobs compartilham um lock: o segundo a chegar espera até 30 minutos. Cada coletor é retomável
e usa cache, então repetir uma execução custa pouco. Localmente, `make update-daily DRY_RUN=1`,
`make update-weekly` e `make update-monthly DRY_RUN=1` rodam a mesma cadeia sem trocar o banco.

Como o job diário atualiza o banco, passo a passo:

1. `collect`: baixa a lista oficial e o arquivo anual da cota das duas Casas.
2. `validate`: confere que o documento é do ano esperado; nunca importa outro ano no caminho padrão.
3. `backup`: cópia datada em `data/backups/`, mantendo as sete mais recentes.
4. `stage`: copia o banco publicado para `data/pipeline/`.
5. `import`: importação transacional na cópia.
6. `verify`: integridade do SQLite e guarda de regressão: lista oficial caindo mais de 5% ou
   notas caindo mais de 10% não são publicadas. Nos 45 dias após uma posse, o limite da lista sobe
   para 50%, porque ela cresce a cada dia.
7. `publish`: troca atômica do arquivo; o site percebe pela data do arquivo e invalida o cache.
8. Snapshots das fichas, que não dependem do banco e preservam a versão anterior se falharem.

## O que cada e-mail significa

O assunto diz o job e o resultado: `concluída`, `parcial` ou `FALHOU`. O corpo lista as etapas.

| Situação | O que aconteceu | O que fazer |
|---|---|---|
| `parcial`, etapa `collect` com fonte indisponível | A Câmara ou o Senado não respondeu | Nada. A fotografia anterior dessa fonte fica no ar e amanhã tenta de novo. Se repetir por dias, veja se a URL mudou em `ingest/legislative.py` |
| `FALHOU` em `verify` com "Regressão detectada" | A lista oficial ou as notas caíram além do limite | Confira a fonte. Se a queda for real (por exemplo, correção em massa pela Câmara), rode uma vez com limite maior: `python3 -m ingest.pipeline daily --max-expense-drop 0.3` |
| `FALHOU` em `validate` com "cobre o período" | Um documento de outro ano apareceu em `data/imports/` | Alguém rodou `legislative.py --year` antigo no caminho padrão. Rode o diário de novo; ele regrava o ano corrente |
| `parcial` em `profiles` com "Arquivos anuais incompletos" | A Câmara não entregou um dos arquivos anuais de proposições | Nada. As fichas mantêm a lista anterior como desatualizada e a próxima execução tenta de novo |
| `parcial` em `senate-attendance` | Em geral falta `pdfplumber` no venv ou um Diário mudou de formato | `sudo /opt/painel/venv/bin/pip install -r ingest/senate-requirements.txt`; se persistir, abra o log |
| `FALHOU` em `import-history` (mensal) | A importação dos anos anteriores da cota não passou | O banco publicado não foi tocado. Veja o log; em geral é um arquivo anual sem status `imported` |
| Assunto "painel-ingest… falhou" | O processo morreu sem gravar status (timeout, memória) | `journalctl -u <unidade> -n 100` no servidor |
| Semanal com "Fila editorial" | Há votações novas para revisar ou um arquivo mantido à mão venceu | Veja a seção seguinte |
| Nenhum e-mail por mais de um dia | O timer pode ter parado | `systemctl list-timers 'painel-ingest*'` no servidor; um monitor externo (`PAINEL_HEALTHCHECK_URL`) avisa disso sozinho |

Para ver o estado sem e-mail: `make deploy-status` do seu computador, ou
`cat /opt/painel/data/status/daily.json` no servidor.

## O que ainda depende de uma pessoa

O job semanal escreve `data/reviews/editorial-queue.md` e manda por e-mail quando há novidade.

- **Revisar votações do Placar.** Para cada candidato sem revisão, o semanal gera um rascunho em
  `data/reviews/chamber-vote-reviews-draft-<data>.json` com os campos objetivos já preenchidos
  (ID, data, proposição, placar, links da API e da ficha). Falta conferir o relatório nominal,
  colar o link dele em `sources.rollCall`, escrever `title`, `summary`, `decisionLabel`,
  `yesMeaning` e `noMeaning` em linguagem simples, registrar `evidence` e mudar `status` para
  `confirmed` (ou `excluded`/`pending` com motivo). Copie as entradas prontas para
  `chamber-vote-reviews-<data>.json` e rode `make collect-votes THROUGH=<data>`. Regras e exemplos
  em [Metodologia do Placar](voting-scoreboard.md).
- **Arrecadação federal** (`data/snapshots/arrecadacao.json`): atualizar `acumulado`, `inicio` e
  `ate` com o relatório mais recente da Receita Federal. O aviso chega quando passa de 60 dias.
- **Gabinetes do Senado.** Senador novo com nome de lotação igual ao do cadastro entra sozinho no
  job mensal, em `data/snapshots/senate-office-map-auto.json`. Nome diferente ou ambíguo aparece
  no aviso: confira à mão e acrescente em `ingest/senate_office_map.json` com a evidência.
- **Contas municipais e eleições** têm aviso quando o exercício ou o turno muda.
- **Troca de legislatura (1º/2/2027).** Iniciar o novo recorte do mandato é decisão explícita
  (`PAINEL_MANDATE_START`), porque apaga o mandato anterior das fichas enquanto não existir a tela
  de histórico. Roteiro em [Publicação](deploy.md#troca-de-legislatura-roteiro-para-1º22027).

### Por que as revisões do Placar não estão no servidor

As revisões são arquivos JSON escritos à mão em `data/reviews/`, no computador de quem revisa.
Elas não estão no Git, porque toda a pasta `data/` fica fora do repositório, e não são
coletadas de fonte nenhuma, porque são uma decisão editorial, não um dado oficial. Logo,
nenhum job as cria e nenhum deploy as copia por padrão.

O job semanal roda no servidor e pergunta "quais candidatos já têm revisão?" olhando a pasta
`data/reviews/` de lá. Em um servidor que nunca recebeu as revisões, a resposta é nenhuma, e a
fila lista todos os candidatos como sem revisão. Isso não é perda de dado: o catálogo publicado
do Placar continua igual, porque ele vem dos snapshots, não da fila.

Para o servidor saber o que já foi revisado, copie as revisões uma vez e sempre que fizer uma
nova: `make deploy-reviews` envia só esses arquivos, sem tocar o banco nem os snapshots do
servidor. Depois, `sudo systemctl start painel-ingest-weekly.service` lá refaz a fila. O
comando é separado do `make deploy-data` de propósito: este também substitui o banco do
servidor pela cópia local, e o banco do servidor é atualizado todo dia pelo job diário, ficando
mais novo que a cópia local.

## Como adicionar uma fonte nova ao pipeline

1. Escreva o coletor em `ingest/`, só com a biblioteca padrão, com `--collect` para rede e
   execução sem rede reconstruindo do cache. Falha preserva a saída anterior e marca `stale`;
   o processo termina com código diferente de zero quando algo ficou incompleto.
2. Não fixe datas: use `ingest/periods.py` (`current_year`, `closed_months`, `MANDATE_START`).
3. Acrescente a etapa em `ingest/pipeline.py`, em `SNAPSHOT_STEPS` (diário) ou `monthly_steps`
   (mensal), na posição que respeita as dependências. Uma etapa é `(nome, argumentos, marcador)`.
4. Escreva o teste do coletor sem rede e acrescente o nome da etapa ao teste de ordem em
   `tests/test_pipeline.py`.
5. Documente a fonte, o recorte e as limitações em [Dados e SQLite](data.md).

## Rodar tudo no seu computador

```sh
make db-init                       # banco vazio com o esquema
make update-daily DRY_RUN=1        # coleta e importa em cópia, sem trocar o banco
make update-daily                  # igual, trocando o banco local
make update-weekly                 # inventário e fila editorial
make update-monthly DRY_RUN=1      # cadeia mensal; a primeira vez leva horas
make pipeline-status               # último resultado de cada job
make pipeline-test-mail            # testa o SMTP com as variáveis de deploy/pipeline.env.example
```

Sem SMTP configurado, os jobs rodam normalmente e só registram em `data/status/`.
`PAINEL_TODAY=AAAA-MM-DD` fixa a data de referência para reproduzir uma fotografia antiga.

## Glossário

- **Cota (CEAP/CEAPS):** reembolsos de despesas de deputados e senadores, a base do banco.
- **Snapshot:** arquivo JSON em `data/snapshots/` com um complemento das telas; lido pelo servidor
  sem reiniciar, pela data do arquivo.
- **Fotografia:** o estado de uma fonte em uma data; a interface sempre diz de quando é.
- **Guarda de regressão:** regra que recusa publicar um banco com menos registros do que o
  anterior além de um limite.
- **Fila editorial:** lista do que uma pessoa precisa revisar ou atualizar, gerada toda semana.
- **Recorte do mandato:** o período "desde fev/2023" que todos os coletores usam, definido em um
  único lugar (`ingest/periods.py`).
