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

As fichas federais têm um coletor complementar manual, sem dependências externas:

```sh
make collect-profiles                 # completa caches ausentes das fichas
python3 ingest/profiles.py --collect --refresh  # atualiza os caches oficiais
python3 ingest/profiles.py            # reconstrói o snapshot sem rede
make build
```

`ingest/profiles.py` usa os IDs das listas oficiais em `data/imports/legislative.json` e escreve
`data/snapshots/perfis.json`. O cache em `data/raw/profiles/` contém somente campos selecionados de contato
institucional, mandato, projetos e gabinete; respostas de detalhe com CPF e outros dados pessoais não são
salvas integralmente. A coleta usa no máximo quatro consultas concorrentes. Falhas preservam a última
observação disponível e sua data, com indicação de falha; não produzem valor zero. `--limit N` permite
uma coleta curta de diagnóstico. Nenhum desses comandos agenda atualizações.

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
valor, ordena e exporta resultados em CSV. Comparações usam mesmo mês, fonte, instituição, cargo, UF e natureza e exigem cinco
outras pessoas com registros observados. Na remuneração também exigem cargo funcional e situação equivalentes; participação
no mandato e datas de exercício não dividem os pares de reembolso. Ausência de linha não é zero; o mês pode estar incompleto. Diferenças
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

A consulta principal usa as listas oficiais importadas: 513 deputados e 82 registros de senadores nesta fotografia. Os 513 IDs da Câmara coincidem com as seis páginas coletadas da API. O total do Senado não é uma contagem de cadeiras: o XML inclui Lourdinha Pereira como segunda suplente, com exercício de 5/8/2026 a 6/10/2026 e motivo publicado de retorno do titular.

A reconciliação de 7/10/2026 reprocessa essa mesma fotografia do XML (`Metadados/Versao`: `06/10/2026 19:19:34`), sem nova coleta nem mudança de cobertura. O adaptador usa `Mandato/UfParlamentar` quando a identificação não informa UF; assim recupera MA para esse registro. Importa `Mandato/DescricaoParticipacao` em `position` e descreve em `employmentStatus` o exercício com a data de início mais recente, independentemente da ordem do XML. A ficha do Senado mostra participação, intervalo e motivo de término quando informados, com link da fonte. Datas ausentes, inválidas ou conflitantes não geram uma situação inferida; intervalo sem término informado não confirma exercício na data de hoje. Os 82 IDs da lista e as despesas históricas são preservados. Não se deduplicam suplentes e titulares como se fossem a mesma pessoa.

Há reembolsos associados a 509 dos deputados e 79 dos registros do Senado. Os demais devem aparecer como dados ausentes, não como zero. A home, a lista, o Placar e as comparações abrem a mesma ficha parlamentar; a busca avançada usa as mesmas seções complementares. Dez deputados mantêm detalhes e PDF da amostra editorial em uma entrada identificada separadamente.

`frontend/scripts/profile-data.js` concentra a leitura do snapshot complementar, presença e votos. Contatos e situação da Câmara vêm do detalhe oficial de cada deputado; verba e equipe de gabinete vêm da página oficial, com ano, meses publicados e data de atualização. Projetos da Câmara abrangem PL, PLP e PEC apresentados desde 1/2/2023: total só é confirmado quando todas as páginas da consulta são lidas. O resumo dessa API não fornece a situação atual de cada projeto, que permanece ausente. Contatos e participação/exercício do Senado vêm do XML reconciliado; gabinete e projetos do Senado ainda não têm fonte integrada validada. O antigo serviço de autoria anuncia descontinuação e o filtro por autor da API substituta não foi confirmado.

Na coleta de 7/10/2026, o complemento contém os 595 IDs da lista: 513 deputados e 82 registros do Senado. Na Câmara, há e-mail para 513, telefone/endereço para 512, gasto de gabinete para 512 e equipe ativa para 512; dois perfis têm a seção de gabinete parcial. A consulta de projetos concluiu a paginação dos 513 perfis (quatro com zero resultados no recorte): são 35.746 associações entre autor e projeto, correspondentes a 19.878 IDs de proposição distintos, pois há coautorias. No Senado, o XML da fotografia de 6/10 informa e-mail para 78 e telefone para 80; 81 registros têm ao menos um desses contatos. Campos não publicados continuam sem valor. Essas contagens não ampliam o recorte de despesas no SQLite.

O salário nas fichas e comparações é o subsídio bruto de referência do cargo, com fonte oficial e vigência; não comprova pagamento individual. Folha, descontos e outras verbas parlamentares ainda não foram importados. Cota, verba de gabinete e subsídio não são somados. Quando um campo mantém complemento editorial, a ficha informa esse recorte.

A presença complementar cobre 512 dos 513 deputados; Gilmar Machado não tem dias extraídos no snapshot. Somente denominadores positivos e contagens consistentes entram nas porcentagens. As votações complementares cobrem quatro votações escolhidas para o Placar. Linha ausente significa registro não importado, nunca a inferência de que a pessoa não votou; votação secreta informa somente participação. As comparações de concordância usam apenas votações com registro para ambos. Cadastro completo não significa histórico de presença, votações e remunerações completo.

### Comparar partidos

`/api/c/partidos` agrupa os cadastros atuais de deputados e senadores pela sigla da lista oficial. Para cada cargo informa quantos registros integram a lista, quantos têm notas importadas, gasto somado, média por parlamentar com notas e alertas (`pico` e `fornecedor`), além dos três maiores gastos do partido. Quem não tem nota importada não entra na média; partido sem nenhuma nota fica com gasto e média nulos. A tela soma a isso a presença média e os votos por partido calculados dos snapshots da Câmara (sem votações secretas); o Senado não tem presença nem votos nesta versão. Cota usa a sigla da lista atual; presença usa a sigla do respectivo snapshot e votos usam a sigla publicada na votação. Esses recortes podem divergir após mudanças de partido.
