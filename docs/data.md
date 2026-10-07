# Dados e SQLite

O banco local fica em `data/na-lupa.sqlite3` (nome preservado para não duplicar a base existente). Não é enviado ao navegador e não entra no Git. Toda a pasta `data/`, inclusive os snapshots editoriais, permanece local; o repositório público contém apenas código, testes e documentação. Configure outro caminho por `PAINEL_DB` ou por `--db` nos comandos Python. Caminhos relativos de `PAINEL_DB` partem da raiz do projeto.

```sh
make db-backup   # cópia consistente em data/backups/, sem sobrescrever
make db-init     # cria/atualiza esquema, sem baixar ou importar registros
make db-check    # integridade, chaves estrangeiras, versão e contagens
make import     # data/imports/ → SQLite, preservando rollback em caso de falha
```

O esquema está em `backend/schema.sql`; `backend/database.py` controla a versão com `PRAGMA user_version`. A primeira migração adota o banco existente sem apagar registros. Mudanças futuras devem incluir migração e teste antes de subir a versão. A conexão habilita chaves estrangeiras; não há troca automática de journal mode nesta organização.

Backup usa a API do SQLite, podendo operar com o app aberto. Para restaurar: pare o servidor, guarde uma cópia do banco atual e aponte `PAINEL_DB` para o backup validado. Não substitua arquivos de banco enquanto o servidor estiver usando-os. Backups locais ainda precisam de uma política externa antes de produção.

## Coletas manuais

```sh
python3 ingest/legislative.py --year 2026
python3 ingest/executive_judicial.py --month 202608
python3 ingest/judiciary.py --year 2026 --month 8
make db-backup
make import
make db-check
```

Os importadores atuais usam apenas a biblioteca padrão do Python. Downloads podem ser grandes. Os snapshots normalizados ficam em `data/imports/`, e os originais/cache em `data/raw/`. Nem todos os brutos são retidos; preserve os normalizados se precisar reconstruir exatamente a mesma fotografia. Recoletar uma fonte pode produzir outro retrato.

Coletores complementares:

```sh
python3 ingest/editorial/coleta.py votos
python3 ingest/editorial/coleta.py deps
python3 ingest/editorial/coleta.py pres 150
python3 ingest/editorial/coleta.py build
make build
```

Esses comandos escrevem os snapshots complementares em `data/snapshots/` e cache em `data/raw/editorial-extra/`. `arrecadacao.json` é um snapshot editorial atualizado manualmente com a fonte e a data. Os demais coletores em `ingest/editorial/` reconstruíam a amostra original de dez perfis: dependem de insumos históricos que não estão todos neste repositório. Não fazem parte de `make dev`; alguns exigem `pip install -r ingest/editorial/requirements.txt` em ambiente virtual.

## Base e recursos

O esquema normalizado contém `sources(id,label,url,scope,period,status,detail,fetchedAt)`,
`authorities(id,name,role,branch,sphere,institution,uf,party,sourceId,sourceUrl,position,employmentStatus,positionCount,positions,searchText)`,
`suppliers(key,name,cnpj)` e
`expenses(id,authorityId,sourceId,date,year,month,category,amountCents,documentId,documentUrl,supplierKey,kind,firstSeen,lastChanged)`;
`authority_totals`, `supplier_totals`, `signals` e `meta` guardam agregados, sinais e controle do retrato. Valores em
`amountCents` são centavos. A natureza separa reembolso de remuneração; os dois não são somados como um custo único.

Na fotografia de 6 de outubro de 2026 havia 652.693 cadastros, 667.241 lançamentos, 22.216 chaves de fornecedor e 3.593 sinais.
Cadastros não são pessoas únicas nacionais. Fornecedores são associados por CNPJ quando a fonte o publica; chaves alternativas
são limitadas à fonte e não garantem conciliação de empresas com nomes iguais.

A interface busca autoridades e fornecedores e aceita papéis como deputado, senador, presidente, ministro, magistrado e servidor,
mas os dados disponíveis dependem da cobertura abaixo. Filtra despesas/remunerações por natureza, categoria, fonte, período e
valor, ordena e exporta resultados em CSV. Comparações usam mesmo mês, fonte, instituição, cargo, situação funcional, UF e
natureza e exigem cinco outras pessoas com registros observados. Ausência de linha não é zero; o mês pode estar incompleto. Diferenças
da mediana/quartis são descritivas. Na folha mensal, competência conhecida não é tratada como data de emissão.

O radar aplica três cortes a reembolsos: lançamento de pelo menos R$ 10.000; concentração de pelo menos 50% do total anual com
um fornecedor na mesma fonte, com soma mínima de R$ 30.000; e mês pelo menos 1,75 vez a mediana anterior, com diferença mínima
de R$ 10.000 e três meses anteriores observados sem lacuna. O último mês observado pela fonte é excluído. São critérios de
triagem, não conclusões sobre conduta. Valores negativos são preservados e podem ser créditos ou estornos; documentos repetidos
exigem conferência na fonte. Referências idênticas não são deduplicadas como se fossem pagamentos repetidos.

Investigações, anotações e autoridades acompanhadas ficam no `localStorage` deste navegador. Seleções não salvas ficam só em memória e
podem ser exportadas em CSV. Ao abrir perfil acompanhado, consulta-se o que foi incluído ou alterado desde a visita anterior;
não há alerta, consulta em segundo plano ou atualização automática. O acompanhamento usa a versão importada como marco; o horário da visita é apenas informativo.

## Cobertura em 6 de outubro de 2026

- **Câmara:** lista oficial de 513 deputados; CEAP 2026 parcial, 113.065 linhas no arquivo consultado, com emissões de 1/12/2025
  a 5/10/2026. Inclui contas institucionais de lideranças; valores negativos mantêm o sinal da fonte.
- **Senado:** lista oficial de 82 senadores; CEAPS 2026 parcial, 14.713 linhas consultadas. A data do documento pode divergir da
  competência.
- **Executivo federal:** SIAPE 2026-08 lista 629.305 IDs públicos e 516.754 registros. Só importa `REMUNERAÇÃO BÁSICA BRUTA
  (R$)`, não total líquido, remuneração completa ou custo do vínculo. 112.551 IDs não têm linha associada; ausência não
  significa zero.
- **Judiciário:** DadosJusBr 2026-08 é uma coleta de terceiro baseada em publicações de tribunais. Importa categoria `base` de
  74 dos 94 órgãos catalogados (22.709 registros); outras verbas e descontos ficam de fora. Identificadores derivados de campos
  publicados podem mudar e confundir homônimos no mesmo órgão.
- **STF:** a página oficial lista a composição, mas não remuneração. Não foi inferido pagamento dela; o painel CNJ não forneceu
  arquivo integrado neste recorte.

Faltam folhas do Executivo e Legislativo estaduais/municipais, servidores do Legislativo, arquivos separados do Banco Central e
de militares. SIAPE não cobre toda a força de trabalho pública. Vínculos e homônimos podem ser difíceis de conciliar; cadastros
não devem ser somados como pessoas nacionais únicas.

Fontes: [CEAP da Câmara](https://www.camara.leg.br/cotas/Ano-2026.csv.zip), [CEAPS do
Senado](https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/2026),
[SIAPE](https://portaldatransparencia.gov.br/download-de-dados/servidores/202608_Servidores_SIAPE), [dicionário
SIAPE](https://portaldatransparencia.gov.br/dicionario-de-dados/servidores-remuneracao),
[DadosJusBr](https://api.dadosjusbr.org/uiapi/v2/download?anos=2026&meses=8&categorias=base),
[CNJ](https://www.cnj.jus.br/transparencia-cnj/remuneracao-dos-magistrados/).

CPFs e matrículas brutos não são exportados pelo importador SIAPE. Referências documentais numéricas ambíguas com 11 dígitos são
ocultadas; isso também pode ocultar um número de documento legítimo nesse formato.

## Cobertura das telas de parlamentares

A consulta principal usa as listas oficiais importadas: 513 deputados e 82 registros de senadores nesta fotografia. Os 513 IDs da Câmara coincidem com as seis páginas coletadas da API. O total do Senado não é uma contagem de cadeiras: o XML inclui Lourdinha Pereira como segunda suplente, com exercício encerrando em 6/10/2026 por retorno do titular. A UF dessa linha está no bloco de mandato e ainda não é capturada pelo adaptador; isso fica pendente de reconciliação na próxima coleta.

Há reembolsos associados a 509 dos deputados e 79 dos registros do Senado. Os demais devem aparecer como dados ausentes, não como zero. As fichas básicas consultam esses dados para todos os cadastros listados; dez deputados têm informação editorial adicional.

A presença complementar cobre 512 dos 513 deputados; Gilmar Machado não tem dias extraídos no snapshot. As votações complementares cobrem quatro votações escolhidas para o Placar. Cadastro completo não significa histórico de presença, votações e remunerações completo.

### Comparar partidos

`/api/c/partidos` agrupa os cadastros atuais de deputados e senadores pela sigla da lista oficial. Para cada cargo informa bancada, quantos têm notas importadas, gasto somado, média por parlamentar com notas e alertas (`pico` e `fornecedor`), além dos três maiores gastos do partido. Quem não tem nota importada não entra na média; partido sem nenhuma nota fica com gasto e média nulos. A tela soma a isso a presença média e os votos por partido calculados dos snapshots da Câmara (sem votações secretas e sem quem não votou); o Senado não tem presença nem votos nesta versão. A sigla é a atual de cada parlamentar, não a da época de cada voto.
