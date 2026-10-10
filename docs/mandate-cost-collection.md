# Quanto custa um mandato — coleta (Fase 2)

A Fase 1 foi aprovada com coleta de folha e moradia da Câmara e piloto de até
10 senadores. Esta etapa não altera a ficha, a home, comparações, lista, API ou
esquema SQLite. Os resultados são snapshots locais auditáveis, fora do Git.

## Reprodução e escopo

```sh
make collect-mandate-cost YEAR=2026
make audit-mandate-cost YEAR=2026
```

O primeiro comando usa a rede somente nos coletores com `--collect`; o segundo
reconstrói os snapshots sem rede. A coleta é manual. A folha usa no máximo duas consultas simultâneas, com intervalo global mínimo de 0,25 segundo entre inícios; cada resposta é gravada imediatamente. Caches existentes permitem retomada. Uma atualização de moradia com `--collect --refresh` prepara uma geração separada e só a publica depois de validar todas as páginas; falhas preservam a observação anterior, sinalizada como desatualizada. Cota e gabinete existentes
são apenas lidos: não houve reimportação nem mudança de esquema, portanto não
foi necessário backup para migração.

- `ingest/chamber_payroll.py`: páginas individuais por deputado/competência e
  inventário mensal de tipos de folha do grupo parlamentar nos CSVs oficiais.
- `ingest/chamber_housing.py`: páginas da consulta de moradia com início e fim
  no mesmo mês, ligadas pelo ID público do deputado.
- `ingest/senate_payroll_pilot.py`: piloto encerrado na verificação do esquema
  do CSV de setembro de 2026; não há ligação nominal comprovada.
- `ingest/mandate_cost_audit.py`: leitura offline dos novos snapshots, do gabinete
  existente e do SQLite em modo somente leitura, com cobertura por Casa e mês.

Os caches ficam em `data/raw/mandate-cost/`; os snapshots são
`chamber-payroll.json`, `chamber-housing.json`, `senate-payroll-pilot.json` e
`mandate-cost-audit.json` em `data/snapshots/`. São projeções minimizadas com
fontes, competências e datas; não cópias integrais de arquivos com dados de
servidores. A folha mantém rubricas em centavos, identidade/tipo das tabelas
observadas e o hash da resposta. Moradia mantém apenas ID, valores, dias de
ocupação e proveniência. Equipe de gabinete não ganhou dados pessoais ou nomes.
A contagem mensal da equipe não existe no snapshot reaproveitado e fica ausente.

## Limites que afetam qualquer total futuro

A folha normal individual não comprova que todas as folhas de uma competência
estejam cobertas. O CSV mensal da Câmara publica o grupo `Parlamentar` e folhas
complementares, mas usa códigos internos sem ligação comprovada com o ID público.
O inventário registra essas folhas sem atribuí-las por aproximação. As páginas
individuais, porém, também podem trazer tabelas complementares e adiantamento de
13º: todas as tabelas presentes são guardadas e ligadas ao ID e à competência
da URL oficial. Não se usa o inventário anônimo para completar ou repartir
valores individuais. Não confundir valor normal conhecido com remuneração completa
do mês, nem ignorar as tabelas adicionais quando existem.

A verba de gabinete disponível é um recorte de salários, não todos os encargos
trabalhistas. A fonte não transforma o limite autorizado em gasto realizado.
O imóvel funcional é registrado por dias de ocupação, sem aluguel estimado.
Subsídio de referência continua separado de pagamento individual e não é somado
à folha. Nenhum componente ausente é substituído por zero.

As fontes e regras da Fase 1 permanecem em
[Levantamento de fontes](mandate-cost-sources.md). O inventário das suplementares
não inclui servidores, aposentadoria parlamentar nem pensionistas; seus totais
não são repartidos entre deputados atuais.

## Piloto do Senado

O CSV de setembro/2026 tem 23 colunas, incluindo vínculo, categoria, cargo,
lotação, tipo de folha e valores. Não tem nome nem identificador público individual
que permita ligar com segurança uma linha ao senador e à consulta individual.
Foram selecionados no máximo 10 IDs do roster local; houve **0 ligações validadas,
0 competências individuais comprovadas e 0 consultas individuais**. O piloto foi
interrompido nesse ponto, conforme a condição aprovada. Não houve busca alternativa
em massa. Senado permanece com referência do cargo e pagamento individual ausente.

O coletor final lê somente duas linhas (metadados e cabeçalho), valida o esquema
exato e guarda apenas esses metadados. Na exploração anterior, um comando exibiu
por engano linhas de servidores na saída da ferramenta; nenhum arquivo com essas
linhas foi gravado. A inspeção foi interrompida e o caminho final tem teste que
rejeita uma linha de dados no lugar do cabeçalho, sem gravar cache.

Fonte: [CSV mensal do Senado](https://www.senado.leg.br/transparencia/LAI/secrh/SF_ConsultaRemuneracaoServidoresParlamentares_202609.csv)
e [orientação de consulta individual](https://www12.senado.leg.br/perguntas-frequentes/canais-de-atendimento/senadores/posso-consultar-o-contracheque-de-um-senador).

### Piloto pela lotação (9/10/2026)

Decisão 3 de [até onde vai cada fonte](mandate-period-sources.md) autorizada pelo mantenedor em 9/10/2026:
ligar senador(a) e gabinete pela lotação "Gabinete do(a) Senador(a) {nome}" do mesmo CSV mensal, para os
10 primeiros IDs da lista em ordem numérica, de janeiro a setembro de 2026.
Coletor: `ingest/senate_office_pilot.py`; correspondência conferida à mão em `ingest/senate_office_map.json`;
saída só local em `data/snapshots/senate-office-pilot.json` (fora do `make deploy-data`).

- **Ligação:** 80 das 81 lotações de gabinete têm o nome parlamentar do roster, só com acentos diferentes em
  alguns ("Jáder", "Márcio"). Os 10 do piloto têm uma linha PARLAMENTAR de folha normal no próprio gabinete
  em todos os 9 meses, inclusive o líder do governo.
- **Subsídio:** R$ 46.366,19 brutos nos 90 meses (10 × 9), igual à referência do cargo. É a conferência de
  que a ligação está certa. Auxílios e indenizações ficam fora do bruto, em campo próprio.
- **Gabinete:** soma bruta das linhas COMISSIONADO da lotação, folha normal: de R$ 170 mil a R$ 569 mil por
  mês, com 9 a 42 pessoas. A folha suplementar (13º, férias, acertos) repete as mesmas pessoas e fica em
  total à parte. Na Câmara, a verba de gabinete de 2026 tem mediana de R$ 150 mil por mês (máximo de
  R$ 166 mil, no `mandate-cost.json`): o gabinete do Senado custa de 1,1 a 3,8 vezes essa mediana. Não são
  partes iguais e a ficha precisa dizer isso.
- **Servidores efetivos lotados no gabinete:** à parte (o salário não depende do gabinete), de 0 a 6 por
  gabinete. Com menos de 3 pessoas, só a contagem é guardada.
- **Privacidade:** cada arquivo é lido em memória; nenhuma linha de servidor é gravada nem impressa (teste
  com sentinela). Ficam só agregados por gabinete e mês.

### Ampliação para os 81 gabinetes e o mandato (9/10/2026)

Autorizada pelo mantenedor em 9/10/2026. O coletor lê os 44 arquivos de fev/2023 a set/2026 (todos com o
cabeçalho conferido; leitura incompleta é repetida, nunca aceita pela metade) e a tabela passou a ter 102
senadores(as): 101 com o nome da lotação igual ao do cadastro (sem acentos) e 1 conferido à mão
("Weverton" no cadastro, "Weverton Rocha" na lotação). `--suggest` lista lotações fora da tabela para
conferência; nenhuma entra por aproximação.

- **Subsídio:** 3.336 de 4.488 senador-mês. Os valores achados são os degraus oficiais do subsídio:
  R$ 39.293,32 (fev–mar/2023), R$ 41.650,92 (abr/2023 a jan/2024), R$ 44.008,52 (fev/2024 a jan/2025) e
  R$ 46.366,19 (desde fev/2025); os demais são meses proporcionais.
- **Sem subsídio, com o motivo:** 900 meses sem a lotação (fora do exercício: suplentes, licenças e quem
  saiu), 162 com a linha do(a) senador(a) em outra lotação (Mesa, liderança) e 90 com duas linhas na mesma
  lotação. Estas são de gabinetes de suplentes cujos titulares estavam licenciados como ministros e
  optaram pelo subsídio do mandato: sem identificador, não há como separar as duas linhas.
- **Gabinete:** 3.561 senador-mês com total; 9 com menos de 3 comissionados, só com a contagem.
- **Lista atual (81):** 79 na tabela; Leany Lemos e Renzo Braz, suplentes, não têm lotação própria. Em
  set/2026, 72 com subsídio e 77 com gabinete. Sem subsídio: 4 com a linha em outra lotação, 1 com
  lotação compartilhada com o titular licenciado e 2 sem a lotação nos últimos meses (conferido com
  `--suggest`: não houve troca de nome).

### Na ficha: despesas identificadas do mandato (9/10/2026)

Decisão do mantenedor: o Senado aparece à parte, sem somar partes de definição diferente sob "custo do
mandato" e sem comparação com deputados(as). A comparação de custo total Câmara × Senado fica indisponível
até reconciliar o que cada fonte inclui.

**Revisão de 10/10/2026 (decisão do mantenedor):** na comparação lado a lado de um(a) deputado(a) com um(a)
senador(a), os dois custos mensais aparecem na mesma linha ("Quanto custa por mês"), cada um com a própria
composição escrita (Câmara: salário, auxílios, cota e verba de gabinete; Senado: remuneração, equipe do
gabinete e cota). Para o cidadão, saber quanto custa cada cargo é informação legítima; esconder os números
não protegia ninguém. Continua valendo o motivo original: as partes não são iguais, então nenhum dos dois
valores é destacado como menor, e a cota de Casas diferentes também fica sem destaque (os tetos diferem).
Listas e ordenações ("Quem mais custa", "acima da média do cargo") seguem separadas por Casa, e não há
soma nem total novo que misture as composições.

- `make collect-senate-cost` roda o coletor dos gabinetes (saída local) e `ingest/senate_cost.py --collect`,
  que junta o histórico de exercício de cada senador(a) na API do Senado (cache em
  `data/raw/senado-exercicios/`) e grava `data/snapshots/senate-cost.json`, publicado com `make deploy-data`.
- **Cartão "Quanto custa?":** "Senado · despesas identificadas do mandato", com remuneração do(a)
  senador(a), equipe do gabinete e cota parlamentar. A média só usa os meses com as três partes e diz
  quantos foram; as três partes são calculadas sobre os mesmos meses. Sem mês completo, cada parte aparece
  com os próprios meses e não há total.
- **Mês a mês (Ver mais):** cada parte com valor ou motivo; "Total parcial — remuneração não identificada"
  quando falta uma parte, sem trocar pelo subsídio tabelado.
- **Motivos:** "Fora do exercício" só quando o histórico de exercício do Senado confirma; ausência no arquivo
  sem essa confirmação diz "Não identificado nesta fonte". Outros: linha do(a) senador(a) fora do próprio
  gabinete (Mesa, liderança), gabinete compartilhado com titular licenciado(a), sem gabinete com o próprio
  nome, equipe com menos de 3 pessoas. Remuneração paga num mês fora do exercício (licença, ministério
  com opção pelo subsídio) é mantida e marcada; são 11 senador-mês.
- **Cobertura em set/2026, lista atual (81):** 72 com remuneração identificada e 9 sem: 4 com a linha fora
  do próprio gabinete, 1 com gabinete compartilhado, 2 fora do exercício segundo o histórico, 1 não
  identificado nesta fonte e 1 sem gabinete com o próprio nome. Das 2 pessoas sem gabinete próprio na
  tabela (Leany Lemos e Renzo Braz), uma está fora do exercício em set/2026 segundo o histórico.
- Folha suplementar (13º, férias), auxílios e servidores efetivos lotados no gabinete ficam fora das
  partes mostradas.

## Inventário de folhas do grupo parlamentar

Contagens de linhas nos CSVs oficiais, **não** contagens de pessoas do roster
atual. Os códigos internos não são associados por semelhança aos IDs públicos.
Os agregados excluem os outros grupos funcionais antes de qualquer gravação.

| Competência | Normal | Complementar 1 | Complementar 2 | Adiantamento de 13º |
| --- | ---: | ---: | ---: | ---: |
| Janeiro | 543 | 104 | 4 | — |
| Fevereiro | 544 | 94 | 1 | — |
| Março | 542 | 102 | — | — |
| Abril | 546 | 99 | 14 | — |
| Maio | 529 | 3 | — | — |
| Junho | 533 | — | — | 528 |
| Julho | 531 | 13 | — | — |
| Agosto | 527 | 2 | — | — |
| Setembro | 525 | — | — | — |

“—” significa tipo não encontrado no inventário publicado, não salário zero por
pessoa. Fonte: [índice de arquivos mensais de 2026 da Câmara](https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/relatorios-consolidados-por-ano-e-mes/2026/).
URLs exatas, hashes, data de consulta, contagens e totais por rubrica estão nos
caches de inventário. Nenhuma linha individual de servidor é persistida.

## Cobertura por parte e competência

Coleta concluída em 7/10/2026 (Brasília; snapshots em UTC de 8/10).
Denominador: roster local atual de **513 deputados**, não o conjunto histórico
inteiro de titulares e suplentes. Foram tentadas **4.617 consultas individuais**:
4.526 com tabelas válidas, das quais 1.014 com cobertura mensal completa e 3.512
parciais; 91 indisponíveis. Moradia tem **4.597/4.617** observações e 20 ausências.
Os números abaixo contam pessoas, não pagamentos. Cota conta meses com linhas
observadas; gabinete conta valores publicados no snapshot reaproveitado.

| Mês de 2026 | Cota | Gabinete | Folha com tabelas | Folha completa | Folha parcial | Folha ausente | Moradia |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-01 | 470 | 503 | 497 | 0 | 497 | 16 | 507 |
| 2026-02 | 474 | 503 | 497 | 0 | 497 | 16 | 507 |
| 2026-03 | 477 | 503 | 495 | 0 | 495 | 18 | 507 |
| 2026-04 | 494 | 505 | 500 | 0 | 500 | 13 | 511 |
| 2026-05 | 496 | 508 | 498 | 0 | 498 | 15 | 513 |
| 2026-06 | 498 | 511 | 508 | 501 | 7 | 5 | 513 |
| 2026-07 | 492 | 512 | 508 | 0 | 508 | 5 | 513 |
| 2026-08 | 467 | 0 | 510 | 0 | 510 | 3 | 513 |
| 2026-09 | 366 | 0 | 513 | 513 | 0 | 0 | 513 |

“Completa” descreve a cobertura da folha segundo as tabelas e o inventário,
não todas as despesas do mandato. As tabelas válidas preservam inclusive zeros;
as 91 ausências não viram salário zero. Em setembro, todos os valores de auxílio
e complemento na consulta de moradia são zero, embora existam auxílios na folha:
por isso, a contagem de observações de moradia não certifica conciliação financeira.

No Senado, o roster local tem **82 pessoas**. A cota reaproveitada tem, de janeiro
a setembro, **72, 72, 72, 77, 77, 75, 74, 73 e 45** pessoas com linhas observadas.
Gabinete, folha individual validada e moradia coletada têm **0/82 em cada mês**.
O piloto selecionou 10 pessoas e validou 0; não houve coleta adicional de moradia
do Senado. A referência salarial do cargo permanece disponível para as duas
Casas (513 e 82), separada de pagamento efetivo.

## Proposta de período comum de 2026

Usar **janeiro–julho de 2026, na Câmara**, com os meses escritos ao lado do
valor. É a interseção possível com o gabinete reaproveitado, não uma projeção
para doze meses nem uma afirmação de que todos os 513 tenham todas as partes.
Para cada pessoa, a lista efetiva de competências deve ser a interseção das
observações válidas, sem preencher buracos. Quem não tiver interseção confiável
recebe as partes separadas e o aviso da ausência.

Ainda não se certifica custo completo nem se libera média ou ordenação por
novo total. Além das ausências, a cobertura integral das folhas com suplementares
não vinculadas precisa permanecer explícita. Moradia já observada na folha não
pode ser somada de novo; complemento CEAP com sinal diferente requer regra de
conciliação documentada antes da composição final. Nenhum valor foi corrigido no
banco para forçar coincidência entre fontes.

Qualquer comparação futura será **somente dentro da mesma Casa**, com mesmas
partes, natureza e competências. (Revisto em 10/10/2026 para a comparação lado a lado de duas pessoas:
ver “Na ficha: despesas identificadas do mandato”. Rankings e médias continuam por Casa.) Mesmo que ambas tenham cota, referência salarial
não torna Senado e Câmara comparáveis em custo total. O piloto do Senado não
estabeleceu remuneração paga; não há total novo para essa Casa nesta fase.

## Três exemplos de conferência

Todos os valores abaixo são reais (R$), com competência de 2026. “Remuneração” soma somente os grupos remuneratórios das tabelas observadas, antes dos descontos obrigatórios; auxílios, diárias e indenizações ficam separados. Não é certificação de folha integral. As colunas não devem ser somadas entre si: moradia pode repetir a folha e complemento aparece também na cota. “Não informado” não é zero.

### Rui Falcão — Com moradia

Fontes: [folha por competência](https://www.camara.leg.br/deputados/73604/remuneracao-deputado-detalhado?mesAno=012026), [moradia por competência](https://www.camara.leg.br/moradia/57/2026/2026/01/01/73604), [gabinete 2026](https://www.camara.leg.br/deputados/73604?ano=2026) e [arquivo CEAP 2026](https://www.camara.leg.br/cotas/Ano-2026.csv.zip). A URL da folha usa `mesAno=MMAAAA`; moradia usa `/57/2026/2026/MM/MM/ID`. Cota é a fotografia de 6/10; gabinete é a de 7/10, com meses apenas até julho. Datas exatas de cada nova consulta estão no snapshot.

| Mês | Cota observada | Gabinete | Remuneração nas tabelas | Auxílios na folha | Auxílio na moradia | Complemento na moradia | Complemento no CEAP | Dias no imóvel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01/2026 | 30.726,13 | 128.941,72 | 46.366,19 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 02/2026 | 29.904,65 | 132.374,78 | 46.366,19 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 03/2026 | 30.534,21 | 130.566,54 | 46.366,19 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 04/2026 | 44.980,84 | 140.046,07 | 46.366,19 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 05/2026 | 53.223,33 | 146.725,50 | 46.366,19 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 06/2026 | 14.887,45 | 158.073,02 | 67.371,52 | 4.253,00 | 4.253,00 | 1.747,00 | −1.747,00 | 0 |
| 07/2026 | 11.991,80 | 165.482,20 | 46.366,19 | 4.253,00 | 4.253,00 | 2.747,00 | −2.747,00 | 0 |
| 08/2026 | 14.381,88 | não informado | 46.366,19 | 4.253,00 | 4.253,00 | 2.747,00 | −2.747,00 | 0 |
| 09/2026 | 8.190,89 | não informado | 46.366,19 | 4.253,00 | 0,00 | 0,00 | não informado | 0 |

Em janeiro, a folha normal informa auxílio zero e a **folha complementar informa R$ 4.253,00**. A consulta de moradia repete R$ 4.253,00 e informa complemento de R$ 1.747,00. No CSV CEAP, o mesmo complemento tem `vlrDocumento=1747`, `vlrLiquido=-1747`, `vlrRestituicao=0.0` e `vlrGlosa` vazio. O valor líquido negativo foi preservado no SQLite. Isso confirma a sobreposição do auxílio com a folha e a presença do complemento na cota com sinal diferente; não autoriza somar todas as colunas nem alterar o sinal automaticamente.

Em junho há tabela de adiantamento de gratificação natalina. Em setembro, a folha informa R$ 4.253,00 de auxílios, mas a [consulta de moradia de setembro](https://www.camara.leg.br/moradia/57/2026/2026/09/09/73604) informa nenhum benefício. A divergência permanece explícita, sem concluir sua causa. Há testemunhos minimizados locais da conciliação de janeiro e da consulta de setembro.

### Adriana Ventura — Sem moradia publicada

Fontes: [folha por competência](https://www.camara.leg.br/deputados/204528/remuneracao-deputado-detalhado?mesAno=012026), [moradia por competência](https://www.camara.leg.br/moradia/57/2026/2026/01/01/204528), [gabinete 2026](https://www.camara.leg.br/deputados/204528?ano=2026) e [arquivo CEAP 2026](https://www.camara.leg.br/cotas/Ano-2026.csv.zip). A URL da folha usa `mesAno=MMAAAA`; moradia usa `/57/2026/2026/MM/MM/ID`. Cota é a fotografia de 6/10; gabinete é a de 7/10, com meses apenas até julho. Datas exatas de cada nova consulta estão no snapshot.

| Mês | Cota observada | Gabinete | Remuneração nas tabelas | Auxílios na folha | Auxílio na moradia | Complemento na moradia | Complemento no CEAP | Dias no imóvel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01/2026 | 4.052,65 | 116.350,56 | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 02/2026 | 4.474,81 | 119.166,66 | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 03/2026 | 6.798,16 | 122.039,12 | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 04/2026 | 1.623,85 | 121.926,10 | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 05/2026 | 13.126,50 | 124.063,18 | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 06/2026 | 4.108,98 | 128.125,46 | 69.549,28 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 07/2026 | 4.078,67 | 115.433,95 | 42.226,35 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 08/2026 | não informado | não informado | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |
| 09/2026 | não informado | não informado | 46.366,19 | 0,00 | 0,00 | 0,00 | não informado | 0 |

Os zeros de auxílio e de dias de imóvel são publicados pela consulta, inclusive em janeiro; não foram inferidos da falta de linhas. Junho tem adiantamento de gratificação natalina. A ausência de notas da cota em agosto/setembro permanece sem valor.

### Gilmar Machado — Com meses sem folha validada

Fontes: [folha por competência](https://www.camara.leg.br/deputados/74581/remuneracao-deputado-detalhado?mesAno=012026), [moradia por competência](https://www.camara.leg.br/moradia/57/2026/2026/01/01/74581), [gabinete 2026](https://www.camara.leg.br/deputados/74581?ano=2026) e [arquivo CEAP 2026](https://www.camara.leg.br/cotas/Ano-2026.csv.zip). A URL da folha usa `mesAno=MMAAAA`; moradia usa `/57/2026/2026/MM/MM/ID`. Cota é a fotografia de 6/10; gabinete é a de 7/10, com meses apenas até julho. Datas exatas de cada nova consulta estão no snapshot.

| Mês | Cota observada | Gabinete | Remuneração nas tabelas | Auxílios na folha | Auxílio na moradia | Complemento na moradia | Complemento no CEAP | Dias no imóvel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 02/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 03/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 04/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 05/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 06/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 07/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 08/2026 | não informado | não informado | não informado | não informado | 0,00 | 0,00 | não informado | 0 |
| 09/2026 | não informado | não informado | 24.728,63 | 0,00 | 0,00 | 0,00 | não informado | 0 |

Janeiro–agosto não têm tabela de folha validada nas respostas consultadas; setembro tem remuneração publicada de R$ 24.728,63. Isso não autoriza completar os meses anteriores com o subsídio do cargo. Gabinete e cota permanecem sem valor no recorte desta base. Os zeros de moradia são observações da fonte, não prova de exercício no cargo durante todo o intervalo.

Nos meses com folha válida desses três exemplos, diárias e indenizações são zero nas tabelas observadas. Descontos e demais componentes continuam discriminados nos snapshots.

## Verificação final

`make audit-mandate-cost YEAR=2026` reconstruiu os quatro snapshots sem rede.
`make check` passou: 241 testes Python e 74 testes Node, além do build e da
verificação de sintaxe. `git diff --check` passou. Os testes novos cobrem
retomada, preservação do cache em falhas, folhas adicionais, ausência versus
zero, competências incompatíveis, proveniência, sinal do complemento e
restrição de comparação à mesma Casa. Nenhum arquivo de dados é versionado.

Snapshots foram escolhidos por permitirem auditoria local independente da ficha,
sem migração ou alteração dos contratos atuais. Não se adotaram rateio do CSV
anônimo, preenchimento por referência salarial, anualização ou correção automática
do sinal do CEAP, pois a evidência coletada não sustenta essas operações.
A Fase 3 aguarda aprovação do período e do tratamento das partes incompletas.
