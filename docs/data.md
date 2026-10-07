# Dados e SQLite

O banco local fica em `data/na-lupa.sqlite3` (nome preservado para não duplicar a base existente). Não é enviado ao navegador e não entra no Git. Toda a pasta `data/`, inclusive os snapshots complementares, permanece local; o repositório público contém apenas código, testes e documentação. Configure outro caminho por `PAINEL_DB` ou por `--db` nos comandos Python. Caminhos relativos de `PAINEL_DB` partem da raiz do projeto.

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

Complementos manuais da Câmara:

```sh
python3 ingest/editorial/coleta.py deps
python3 ingest/editorial/coleta.py pres 150
python3 ingest/editorial/coleta.py build
python3 ingest/editorial/coleta.py votos
make build
```

`deps` segue todos os links de paginação da API oficial e grava um cache completo separado do cache antigo. `pres SEGUNDOS` consulta os perfis dentro do tempo informado; pode ser repetido para preencher o cache local. `build` processa somente páginas de presença disponíveis e informa quantos registros foram montados. Perfil sem resposta continua ausente, sem virar zero. `votos` lê os IDs selecionados e versionados em `frontend/data/votacoes.json` e coleta todas as linhas de participação de cada votação. As respostas oficiais ficam em `data/raw/editorial-extra/`; os snapshots resultantes são opcionais. Esses comandos só rodam quando chamados: `make dev`, `make build` e o uso do app não iniciam coleta nem atualização automática.

As fichas federais têm um coletor complementar manual, sem dependências externas:

```sh
make collect-profiles                 # completa caches ausentes das fichas
python3 ingest/profiles.py --collect --refresh  # atualiza os caches oficiais
python3 ingest/profiles.py            # reconstrói o snapshot sem rede
make build
```

`ingest/profiles.py` usa os IDs das listas oficiais em `data/imports/legislative.json` — 595 registros nesta fotografia — e escreve
`data/snapshots/perfis.json`. O cache em `data/raw/profiles/` contém somente campos selecionados de contato
institucional, mandato, projetos e gabinete; respostas de detalhe com CPF e outros dados pessoais não são
salvas integralmente. A coleta usa no máximo quatro consultas concorrentes. Falhas preservam a última
observação disponível e sua data, com indicação de falha; não produzem valor zero. `--limit N` permite
uma coleta curta de diagnóstico. Nenhum desses comandos agenda atualizações.

Os coletores de perfis continuam sendo a fonte manual dos complementos para a lista completa; contatos, projetos, gabinete e presença têm a cobertura registrada em seus snapshots. A arrecadação é outro complemento atualizado manualmente, com fonte e data. Os geradores da página e dos PDFs da amostra editorial foram removidos. `ingest/editorial/requirements.txt` só é necessário para as ferramentas opcionais de passagens e agregação eleitoral; não é requisito do app nem do build.

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

A home, o resumo e a lista parlamentar consultam o roster atual da Câmara e do Senado no SQLite, junto com todos os reembolsos importados desses registros. As contagens cobrem a lista inteira; médias incluem somente parlamentares com reembolso observado e ausências continuam sem valor, nunca zero. A classificação mostra cinco nomes por espaço visual, mas considera todos os deputados com dados. Não há resultados eleitorais para a lista completa; o bloco eleitoral da home foi removido até haver cobertura ampla.

A interface de busca avançada consulta autoridades e fornecedores e aceita papéis como deputado, senador, presidente, ministro, magistrado e servidor,
mas os dados disponíveis dependem da cobertura abaixo. Filtra despesas/remunerações por natureza, categoria, fonte, período e
valor, ordena e exporta resultados em CSV. Comparações usam mesmo mês, fonte, instituição, cargo, UF e natureza e exigem cinco
outras pessoas com registros observados. Na remuneração também exigem cargo funcional e situação equivalentes; participação
no mandato e datas de exercício não dividem os pares de reembolso. Ausência de linha não é zero; o mês pode estar incompleto. Diferenças
da mediana/quartis são descritivas. Na folha mensal, competência conhecida não é tratada como data de emissão.

O radar aplica três cortes a reembolsos: lançamento de pelo menos R$ 10.000; concentração de pelo menos 50% do total anual com
um fornecedor na mesma fonte, com soma mínima de R$ 30.000; e mês pelo menos 1,75 vez a mediana anterior, com diferença mínima
de R$ 10.000, três meses anteriores observados sem lacuna e valor acima da mediana dos meses positivos de todos os parlamentares
da mesma fonte e ano (piso pelos colegas, exigido a partir de cinco meses observados). O piso evita que quem gasta pouco o ano todo
vire alerta por um mês ainda abaixo do que os colegas gastam normalmente. Meses seguidos acima do critério contam como um único alerta,
registrado no primeiro mês da sequência. O último mês observado pela fonte é excluído. São critérios de
triagem, não conclusões sobre conduta. Valores negativos são preservados e podem ser créditos ou estornos; documentos repetidos
exigem conferência na fonte. Referências idênticas não são deduplicadas como se fossem pagamentos repetidos.

Cada alerta da visão cidadã traz uma linha de contexto com o total do ano na cota e a diferença para a média do cargo
(deputados ou senadores com notas importadas); diferenças menores que 10% aparecem como “parecido com a média”. A ordem
“Maior valor em alerta” soma os valores dos alertas `pico` e `fornecedor` de cada pessoa, em vez de contar alertas. O radar
da visão cidadã lista só deputados e senadores; contas institucionais (lideranças) seguem na busca avançada.

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

Há reembolsos associados a 509 dos deputados e 79 dos registros do Senado. Os demais devem aparecer como dados ausentes, não como zero. A lista, o Placar e as comparações abrem a mesma ficha parlamentar; a busca avançada usa as mesmas seções complementares. Os antigos detalhes e PDF de dez deputados e a análise editorial de despesas foram removidos.

`frontend/scripts/profile-data.js` concentra a leitura do snapshot complementar, presença e votos. Contatos e situação da Câmara vêm do detalhe oficial de cada deputado; verba e equipe de gabinete vêm da página oficial, com ano, meses publicados e data de atualização. Projetos da Câmara abrangem PL, PLP e PEC apresentados desde 1/2/2023: total só é confirmado quando todas as páginas da consulta são lidas. O resumo dessa API não fornece a situação atual; a coleta separada da Etapa 3, descrita abaixo, consulta os IDs já listados e preserva lacunas. Contatos e participação/exercício do Senado vêm do XML reconciliado. Autoria do Senado usa a API substituta `/dadosabertos/processo`, com o filtro `codigoParlamentarAutor` validado; a cobertura está detalhada abaixo. Gabinete do Senado ainda não tem fonte integrada.

Na coleta de 7/10/2026, o complemento contém os 595 IDs da lista: 513 deputados e 82 registros do Senado. Na Câmara, há e-mail para 513, telefone/endereço para 512, gasto de gabinete para 512 e equipe ativa para 512; dois perfis têm a seção de gabinete parcial. A consulta de projetos concluiu a paginação dos 513 perfis (quatro com zero resultados no recorte): são 35.746 associações entre autor e projeto, correspondentes a 19.878 IDs de proposição distintos, pois há coautorias. No Senado, o XML da fotografia de 6/10 informa e-mail para 78 e telefone para 80; 81 registros têm ao menos um desses contatos. Campos não publicados continuam sem valor. Essas contagens não ampliam o recorte de despesas no SQLite.

O salário nas fichas e comparações é o subsídio bruto de referência do cargo, com fonte oficial e vigência; não comprova pagamento individual. Folha, descontos e outras verbas parlamentares ainda não foram importados. Cota, verba de gabinete e subsídio não são somados. O build pode ser feito sem snapshots; complementos disponíveis identificam seu recorte e sua fonte.

A presença complementar cobre 512 dos 513 deputados; Gilmar Machado não tem dias extraídos no snapshot. Somente denominadores positivos e contagens consistentes entram nas porcentagens. As votações complementares cobrem quatro votações escolhidas para o Placar. Linha ausente significa registro não importado, nunca a inferência de que a pessoa não votou; votação secreta informa somente participação. As comparações de concordância usam apenas votações com registro para ambos. Cadastro completo não significa histórico de presença, votações e remunerações completo.

### Atividade e autoria do Senado — consulta de 7/10/2026

```sh
# Só a coleta de PDFs de presença requer esta dependência opcional:
python3 -m pip install -r ingest/senado-requirements.txt
make collect-senate YEAR=2026
python3 ingest/senado_attendance.py --collect --refresh --year 2026
python3 ingest/senado_projects.py --collect --refresh --year 2026
python3 ingest/senado_activity.py --collect --refresh --year 2026
# Reconstrução dos snapshots sem acessar a rede:
python3 ingest/senado_attendance.py --year 2026
python3 ingest/senado_projects.py --year 2026
python3 ingest/senado_activity.py --year 2026
make build
```

Os novos coletores são manuais. Caches ficam em `data/raw/senado-projetos/` e
`data/raw/senado-atividade/` e `data/raw/senado-presenca/`; os snapshots correspondentes, em `data/snapshots/`.
Autoria é mesclada na resposta individual `/api/c/perfil/<id>`, preservando contato e
mandato. Votos e presença chegam por `/api/c/senado/atividade`, somente quando uma
ficha ou comparação precisa deles. O HTML leva apenas o marcador de disponibilidade.
Nenhum dado novo é embutido na home ou importado no SQLite.

**Autoria:** [API oficial de processos](https://legis.senado.leg.br/dadosabertos/v3/api-docs),
endpoint `/processo`, filtros `codigoParlamentarAutor`, `sigla=PL,PLP,PEC`,
`dataInicioApresentacao=2026-01-01` e `dataFimApresentacao=2026-10-07`.
As 82 consultas do cadastro local responderam com arrays válidos: 788 associações
senador–projeto, 462 IDs distintos e três respostas vazias confirmadas. Inclui coautorias,
portanto a soma por senador não é uma contagem de projetos distintos. Mantém somente
processos `objetivo=Iniciadora`: substitutivos posteriores podem herdar o autor do projeto
original e não são novos projetos de sua autoria. O serviço não documenta paginação
nem publica total independente; a cobertura se refere aos arrays retornados pelos
filtros oficiais, não a uma auditoria da completude interna da fonte. O serviço legado
anunciava descontinuação em 1/2/2026 e não é usado. Situação atual vem da coleta separada da Etapa 3, descrita abaixo, sem inferência a partir da autoria. O recorte do Senado começa em 2026; o da Câmara, em fevereiro de 2023.

**Votos:** [API oficial de votações](https://legis.senado.leg.br/dadosabertos/votacao?dataInicio=2026-01-01&dataFim=2026-10-07),
consulta de 1/1 a 7/10/2026. A resposta contém 59 votações do Plenário do Senado:
19 abertas nominais com 1.539 linhas individuais e 40 secretas. As secretas ficam
fora dos itens e de todos os denominadores de escolha nominal. Registros sem escolha
(presença sem voto, atividade parlamentar, licenças, missão, não comparecimento e
presidência) são mantidos como registros, sem virar votos nem faltas. A comparação de
pessoas usa somente Sim, Não, Abstenção ou Obstrução presentes para os dois senadores;
casas diferentes não têm concordância calculada. O resumo da ficha informa em quantas
votações com linha individual foi identificado um voto; chamadas sem linha dessa pessoa
não entram no denominador, e registros sem voto não são classificados como faltas.
A lista completa deste recorte é distinta das quatro votações editoriais do Placar da Câmara.
Cada item aponta para a consulta oficial da sessão; os títulos vêm da descrição e da
identificação da matéria, sem resumo editorial novo. Falha de atualização preserva a
fotografia anterior e sua data, com status parcial.

**Presença registrada:** a [agenda mensal oficial](https://legis.senado.leg.br/dadosabertos/plenario/agenda/mes/20260401)
é consultada desde o primeiro dia de cada mês; a API lista eventos da data informada
até o fim do mês. O coletor considera sessões deliberativas ordinárias/extraordinárias
realizadas e cruza o [calendário por data de sessão do DSF](https://legis.senado.leg.br/diarios/ver)
com os cadernos. Baixa somente o sumário e as páginas necessárias da tabela
“Registro de Comparecimento” (com ou sem “e Voto”), validando data, tipo de sessão e
total “Compareceram N senadores”. A evidência positiva é a marca na coluna Presença ou,
no formato que publica a coluna Horário, o registro nominal explícito de data e hora
do comparecimento. Marcas na coluna Voto não são usadas como presença. Cada tabela
guarda o método aplicado. Cadernos repetidos da mesma sessão são conciliados por data,
tipo e número da sessão. Texto selecionado e observações validadas
ficam no cache local, com URL e data; falhas de atualização preservam evidência anterior.
A extração de PDF é a única parte que requer a dependência opcional descrita acima;
modo offline, build, testes e servidor não precisam dela.

Na consulta de 7/10/2026 foram validadas **42 tabelas**, em um universo de 45 eventos
deliberativos realizados enumerados na agenda: 41 com marcas na coluna Presença e
uma, de 29/4, com 79 horários nominais e total oficial de 79 comparecimentos.
Há observações positivas associadas a 80 IDs do cadastro. Faltam tabelas validadas
para 1º e 2/9 (atas da sessão deliberativa contínua sem seção de comparecimento
identificada nos sumários) e 6/10 (sem caderno no calendário consultado).
Outras 215 linhas, de 21 nomes ou grafias extraídas, não coincidiram com um nome
normalizado único do cadastro atual. Há nomes históricos e erros de reconhecimento
de texto nos PDFs; essas linhas foram preservadas no cache, mas não atribuídas por
aproximação. Isso pode subcontar comparecimentos de pessoas com outros registros
válidos. As contagens exibidas são somente as observações positivas associadas,
não o total certificado de presença de cada senador em 2026.

O nome publicado é associado somente a um nome normalizado único no cadastro local.
Nomes sem correspondência ou ambíguos não recebem ID por aproximação. O snapshot
`senado-presenca.json` guarda as sessões, links dos Diários, IDs associados e contagens
positivas por pessoa; `senado-atividade.json` incorpora essa seção na reconstrução.
A legenda usada para agrupar essas presenças é a do cadastro atual, enquanto votos
usam a legenda publicada em cada votação. O denominador de dias, faltas e faltas
justificadas permanecem nulos. Perfis sem marca positiva permanecem sem dado, nunca
com zero inferido. As comparações mostram sessões com presença registrada e, nos
partidos, a média apenas entre pessoas com registros positivos, sem ranking de
assiduidade e sem comparar essa métrica com o percentual da Câmara.

O [tutorial oficial de assiduidade](https://www12.senado.leg.br/assessoria-de-imprensa/guia-para-jornalistas/tutorial-de-verificacao-da-assiduidade-dos-senadores)
explica que registrar presença isoladamente não confirma a assiduidade: é preciso
verificar votações e justificativas, publicadas separadamente. Por isso a integração
é **parcial para presença**: não exibe percentual, selo comparativo nem barra de
faltas do Senado. Apurar faltas e justificativas permanece pendente; não se deduz
nenhum desses estados a partir de uma omissão na tabela ou no arquivo de votos.

### Situação atual dos projetos — Etapa 3

`ingest/project_status.py` consulta somente os IDs de projetos que já existem nas
fichas locais: Câmara em `perfis.json`, Senado em `senado-projetos.json`. Coautorias
são deduplicadas para a coleta; cada ficha conserva sua própria lista e contagem.
Não há ampliação do período de autoria nem substituição do snapshot original.

```sh
make collect-project-status
# Atualização explícita de todas as consultas:
python3 ingest/project_status.py --collect --refresh
# Reconstrução sem rede, mantendo a data real das consultas em cache:
python3 ingest/project_status.py
make build
```

Os arquivos brutos e seus metadados (URL, data da consulta e SHA-256) ficam em
`data/raw/projetos-situacao/`. O snapshot `data/snapshots/projetos-situacao.json`
usa chaves `camara:<idProposicao>` e `senado:<idProcesso>`; IDs numéricos de casas
diferentes nunca são fundidos. A API `/api/c/perfil/<id>` anexa `situacaoAtual`
somente aos projetos daquela pessoa, sem embutir o conjunto no HTML e sem gravar
no SQLite. Para testar alterações da API, reinicie o servidor Python e recarregue
a página. Novas coletas podem ser relidas sem reiniciar: o cache acompanha o mtime.

**Câmara:** os [arquivos anuais oficiais de proposições](https://dadosabertos.camara.leg.br/swagger/api.html)
de 2023, 2024, 2025 e 2026 fornecem `ultimoStatus`, com descrição da situação, código
e data. Por exemplo: [arquivo de 2026](https://dadosabertos.camara.leg.br/arquivos/proposicoes/json/proposicoes-2026.json).
O coletor lê esses quatro arquivos, filtra os IDs já listados e só consulta
`/api/v2/proposicoes/<id>` para IDs não encontrados ou referências normativas.
O detalhe chama esse campo de `statusProposicao`. A consulta resumida em lote não
fornece situação. Situações vazias aparecem também no detalhe oficial; não são
completadas a partir da ementa, da proposição principal ou de uma apensada.
Para PEC cuja situação própria já confirma transformação em norma, o despacho
pode identificar a emenda somente quando começa com a declaração explícita
“Transformado na Emenda Constitucional N/AAAA.”; menções no restante do texto
não contam. O último andamento disponível pode ser anterior à data da coleta.

**Senado:** a [API oficial de processos](https://legis.senado.leg.br/dadosabertos/v3/api-docs)
aceita até 100 valores de `idProcesso` por consulta. O coletor usa cinco lotes para
os 462 IDs e consulta `/processo/<id>` quando precisa confirmar estados finais,
norma gerada ou informação incompleta. Usa `situacaoAtual`, `tramitando`, datas
publicadas e `normaGerada` do próprio processo. No detalhe, considera somente a
autuação principal para situações históricas; processos relacionados e outros
números não transferem seu resultado para o projeto consultado.

As classificações são conservadoras e preservam a descrição original:

- **Virou lei:** transformação explícita do próprio PL/PLP em norma legal ou
  referência normativa final direta. Aprovação e remessa à sanção não bastam.
- **Tramitando:** situação ativa reconhecida da Câmara ou indicação explícita de
  tramitação do Senado, sem estado terminal conflitante.
- **Arquivado/rejeitado:** situação final explicitamente informada pela fonte.
- **Emenda promulgada:** resultado normativo próprio de PEC, separado da contagem
  de leis, conforme a distinção da [Constituição, artigos 59 e 60](https://legis.senado.leg.br/norma/579494/publicacao/16434817).
- **Outras / sem classificação:** situação vazia, desconhecida, retirada,
  prejudicada ou transformada em outra proposição, quando não há prova de um dos
  resultados acima. A descrição oficial e a data continuam visíveis.

Cada item conserva `consultadoEm` (consulta), `atualizadoEm` (andamento informado),
fonte, descrição original e eventual norma gerada. `generatedAt` marca apenas a
montagem do snapshot. Falha de atualização mantém a consulta anterior e sua data,
com status parcial; a interface não inclui esse estado antigo nas contagens
confirmadas. Sem classificação de todos os itens, o cabeçalho informa cobertura
parcial e não transforma zero leis confirmadas em prova de que nenhuma virou lei.
Snapshots sem a nova coleta continuam válidos e mostram situação não consultada.

**Fotografia local consultada em 7/10/2026:**

| Casa | IDs consultados | Viraram lei | Emendas | Tramitando | Arquivados/rejeitados | Sem classificação confirmada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Câmara | 19.878 | 149 | 1 | 16.876 | 675 | 2.177 |
| Senado | 462 | 2 | 0 | 441 | 0 | 19 |

Esses números contam projetos distintos dentro de cada casa; uma coautoria pode
aparecer em várias fichas. A coleta conseguiu ler todos os IDs, mas isso não torna
todas as situações classificáveis. Na Câmara, os casos sem classificação incluem
1.581 situações vazias, 389 retiradas, 197 devolvidas e dez transformações em nova
proposição. No Senado, são oito prejudicadas, seis retiradas, quatro remessas à
Câmara com tramitação encerrada no Senado e um processo sem situação confirmada.
Remessa à outra casa não comprova a situação atual no destino. O detalhe individual
prevalece sobre o arquivo anual quando consultado; ambos preservam suas datas reais
nos metadados. Esta fotografia e os caches são locais e não estão no Git.

### Comparar partidos

`/api/c/partidos` agrupa os cadastros atuais de deputados e senadores pela sigla da lista oficial. Para cada cargo informa quantos registros integram a lista, quantos têm notas importadas, gasto somado, média por parlamentar com notas e alertas (`pico` e `fornecedor`), além dos três maiores gastos do partido. Quem não tem nota importada não entra na média; partido sem nenhuma nota fica com gasto e média nulos. A tela soma a isso a presença média e os votos por partido calculados dos snapshots da Câmara e os dados coletados do Senado, sempre em linhas separadas por casa. Votações secretas ficam fora da comparação nominal. A unidade usa somente votos Sim/Não; a concordância entre pessoas usa escolhas nominais registradas para ambas. Presença do Senado é contagem de registros positivos, sem percentual de assiduidade nem classificação de faltas. Cota usa a sigla da lista atual; presença usa a sigla do respectivo snapshot e votos usam a sigla publicada na votação. Esses recortes podem divergir após mudanças de partido.
