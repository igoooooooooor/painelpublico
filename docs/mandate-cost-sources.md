# Quanto custa um mandato — levantamento de fontes (Fase 1)

Consulta em 7 de outubro de 2026. Levantamento para aprovação, sem novo coletor,
sem mudança de produto ou esquema e sem coleta em massa. Disponibilidade da fonte
não significa cobertura importada. Uma consulta inacessível não comprova que o
órgão não publica o dado.

## Parte × Casa e recomendação

**Disponível**: amostra individual pertinente confirmada. **Parcial**: fonte
publicada, mas falta história, valor, ligação temporal ou acesso reproduzível.
**Indisponível**: nenhum valor adequado validado para o total nesta fase; não
significa declaração de que o órgão jamais publica a informação.

| Parte | Câmara | Senado | Recomendação para a v1 |
| --- | --- | --- | --- |
| Subsídio do cargo | Disponível: referência já integrada | Disponível: referência já integrada | Manter fora do total pago quando não houver folha individual validada |
| Cota | Disponível: CEAP no SQLite | Disponível: CEAPS no SQLite | Usar competências compatíveis; não somar de novo benefícios contidos na cota |
| Equipe de gabinete | Disponível: agregado por deputado e mês no perfil | Parcial: equipe e remuneração publicadas em canais separados; agregado histórico por gabinete não validado | Câmara entra nos meses confirmados; Senado fica sem valor até provar a ligação mensal |
| Auxílio-moradia | Parcial: valores individuais e filtros de intervalo; extração mensal ainda não validada | Parcial: opção atual em API; pagamentos históricos em consulta individual | Priorizar piloto da Câmara; Senado somente com pagamento individual confirmado |
| Imóvel funcional | Parcial: ocupação/dias por pessoa, sem custo individual | Parcial: ocupação atual por pessoa, sem custo individual | Informação contextual, fora da barra monetária |
| Folha parlamentar individual | Disponível: amostra por ID/mês em HTML | Parcial: consulta oficial e CSV mensal publicados; atribuição automatizada precisa validação | Priorizar Câmara; Senado mantém referência até validação de pessoa e competência |
| Outros auxílios/indenizações | Parcial: rubricas da folha, sem garantir decomposição de todos os benefícios | Parcial: rubricas de remuneração e outras consultas administrativas | Só valores individualizados, com natureza definida e sem sobreposição |

Não recomendar custo anual completo de 2026 nesta fotografia: o exercício está
em andamento e as fontes têm atrasos diferentes. O rótulo adequado é custo
conhecido no período explicitado. Um total de doze meses só será possível com
cobertura confirmada dos doze meses, inclusive exercício e substituições.

## Câmara — fontes e viabilidade

### Gabinete

[Perfil por ID e ano](https://www.camara.leg.br/deputados/220661?ano=2026):
HTML com agregado de verba de gabinete, meses e contagens de equipe. É a fonte
já usada por `ingest/profile_office.py`. A amostra local confirma 2026 até julho;
não foi auditada uma série histórica completa. Atualização vem da própria página,
sem prazo de publicação garantido validado. Download da página é reproduzível,
mas o cache atual preserva a extração, não o HTML integral. A nova coleta deverá
guardar evidência minimizada/datada e distinguir total publicado de teto.
Contagem de pessoas ativas no momento não é contagem mensal da equipe.
A [explicação de gastos parlamentares](https://www.camara.leg.br/transparencia/gastos-parlamentares)
informa que encargos como 13º, férias e auxílio-alimentação ficam fora da verba.
Portanto esse agregado não deve ser rotulado como custo trabalhista completo;
nem se deve somá-lo de novo aos salários que ele já financia.

### Moradia

[Apresentação](https://www.camara.leg.br/moradia) e
[detalhamento](https://www.camara.leg.br/moradia/detalhamento): HTML, filtros de
legislatura, pessoa, início/fim mês/ano, paginação e botão de download. A amostra
confirma colunas de dias em imóvel, auxílio recebido e complemento com a cota.
O resultado padrão tem 717 registros, **não** uma cobertura de 717 deputados em
2026. A janela depende dos filtros; o início histórico, o formato do download e
o contrato de consulta mensal não foram confirmados. Não há API documentada
validada neste levantamento. A interface oferece filtro mensal, mas isso ainda
não prova extração mensal reproduzível. Frequência/prazo de atualização não
confirmados; registrar data consultada e período solicitado.

O [guia oficial](https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/auxilio-moradia-e-apartamento-funcional)
distingue auxílio e uso de imóvel. A consulta mantém complemento CEAP separado;
essa parcela não deve ser somada novamente à cota. Para cache, preferir valores,
ID público e dias; excluir recibos e endereços residenciais. Preservar HTML bruto
somente após verificar ausência de campos desnecessários.

### Folha e outros benefícios

[Amostra individual de fevereiro de 2026](https://www.camara.leg.br/deputados/220661/remuneracao-deputado-detalhado?mesAno=022026):
HTML por ID, competência e tipo de folha. O cabeçalho interno identifica salário
do deputado, embora o título HTML mencione pessoal de gabinete. Confirmados
remuneração fixa, eventuais, abono, descontos obrigatórios e grupo Outros
(diárias, auxílios e indenizações). A amostra tem remuneração fixa de R$ 46.366,19
e auxílios iguais a zero: zero efetivamente publicado, não inferido.
O valor após descontos obrigatórios não é necessariamente o líquido recebido,
pois descontos pessoais não são divulgados. Não tentar reconstruí-los.

O [índice mensal de remuneração](https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/relatorios-consolidados-por-ano-e-mes)
lista 2012–2026. Em 2026 há links de janeiro a setembro; rótulos de outubro a
dezembro não comprovam arquivo publicado. Histórico de 2012 é parcial; o índice
oferece PDF e CSV para anos posteriores. Essa janela de arquivos não certifica
que cada parlamentar tenha todos os meses na consulta por ID. Periodicidade
mensal, sem SLA de dia específico confirmado. Preferir HTML individual para
reduzir dados de terceiros; validar todas as folhas da competência, incluindo
suplementares, antes de declarar mês completo.

[Esclarecimentos das rubricas](https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/relatorios-consolidados-por-ano-e-mes/esclarecimentos-consulta-remuneracao):
auxílios de parlamentar podem incluir moradia. Portanto a mesma verba não pode
entrar como folha e novamente como moradia. O bruto/cache individual pode ser
preservado com fonte e data após inspeção; arquivos gerais exigem projeção para
excluir servidores fora do recorte, nomes de assessores e identificadores pessoais.

## Senado — fontes e viabilidade

### Gabinete e folha

[Equipe de um gabinete, exemplo de 2025](https://www6g.senado.leg.br/transparencia/sen/4642/pessoal/?ano=2025&local=gabinete&vinculo=TODOS):
HTML por senador/ano/local/vínculo, com equipe nominal. A lista anual não fornece
por si o total salarial por gabinete/mês nem confirma a lotação em cada mês.
Não guardar os nomes da equipe. Período inicial e atualização histórica por
lotação não confirmados. O custo do gabinete fica indisponível para soma enquanto
não existir agregado oficial ou ligação temporal comprovada; teto e tabela de
cargos não substituem gasto.

[Índice de remuneração mensal](https://www.senado.leg.br/transparencia/rh/servidores/consulta_remuneracao.asp):
CSV com arquivos de agosto de 2012 a setembro de 2026 listados. Exemplo publicado:
[setembro/2026](https://www.senado.leg.br/transparencia/LAI/secrh/SF_ConsultaRemuneracaoServidoresParlamentares_202609.csv).
Publicação mensal, sem certificação nesta fase da completude de todos os arquivos.
Não se deduz identidade individual ou possibilidade de ligação só pelo nome do
arquivo. O cabeçalho do CSV não pôde ser lido nesta pesquisa: o leitor web não
processou o tipo de conteúdo e a consulta HTTP limitada encontrou restrição de
rede. Isso é limite de verificação, não prova de indisponibilidade pública.
O catálogo de gestão de pessoas informa atualização antiga (junho/2023), enquanto
o índice tem links até setembro/2026; preferir evidência do arquivo e sua
competência, sem usar a data do catálogo como data da folha.
A documentação de rubricas está no
[Ato 10/2012](https://www.senado.leg.br/transparencia/rh/servidores/pdf/BAP_APS_10_20120730.pdf).

A [orientação oficial para contracheque de senador](https://www12.senado.leg.br/perguntas-frequentes/canais-de-atendimento/senadores/posso-consultar-o-contracheque-de-um-senador)
indica página pessoal, subsídio e aposentadoria, e seleção de competência.
A [consulta de remuneração](https://www.senado.leg.br/transparencia/rh/servidores/nova_consulta.asp)
é um sistema HTML interativo; acesso automatizado e histórico por pessoa ainda
precisam validação. Não contornar CAPTCHA nem associar linhas sem identidade
comprovada. Recomenda-se amostra controlada na Fase 2 antes de coleta ampla;
se o caminho não se confirmar, preservar referência do cargo e ausência do pago.

### Moradia e imóvel

[Portal de moradia](https://www12.senado.leg.br/transparencia/sen/coapat/auxilio-moradia-e-imoveis-funcionais)
publica PDF, CSV, JSON, XML e HTML. O
[endpoint JSON oficial](https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/auxilio-moradia-imoveis-funcionais?formato=json)
retorna nome público, UF, partido e indicadores `auxilioMoradia` e
`imovelFuncional`. Não retorna valor pago, competência explícita por linha nem
histórico mensal. A própria página limita o relatório ao mês de emissão e
remete às páginas individuais para meses anteriores. O
[catálogo administrativo](https://www12.senado.leg.br/dados-abertos/conjuntos?grupo=senadores&portal=administrativo)
indica atualização diária; isso não torna o relatório uma série diária arquivada.

Download atual é reproduzível e pode ser guardado datado em `data/raw/`, mas não
reconstrói retroativamente o ano. `S` não é pagamento do teto, `N` não comprova
zero de pagamentos antigos. Guardar somente ID associado sem ambiguidade, estado,
fonte e consulta; não guardar endereço do imóvel. Série individual de pagamentos
precisa de validação antes de integrar o total. Não somar benefícios à CEAPS ou
folha sem conferir rubricas, pessoa e competência.

## Licença, termos e minimização

A [FAQ de Dados Abertos da Câmara](https://dadosabertos.camara.leg.br/faq/faq-home.html)
permite acesso gratuito, sem cadastro e uso inclusive comercial. Isso se refere
ao serviço Dados Abertos: não atribuir automaticamente uma licença específica
CC/MIT às páginas HTML de moradia e remuneração. Não foi localizada licença
específica desses conjuntos nas páginas consultadas; manter atribuição, link,
data e fidelidade às rubricas, e registrar essa limitação nos metadados.

A [política de uso do Senado](https://www12.senado.leg.br/institucional/documentos/politica-de-uso-do-portal-do-senado-federal)
permite reutilização com fonte e finalidade lícita, sem prejudicar o acesso de
outros usuários. Aplica-se aos canais do portal aqui citados; não foi identificada
licença nominal separada por arquivo. Usar baixa concorrência e respeitar
restrições técnicas do serviço.

Em ambas as Casas, publicidade da fonte não justifica guardar CPF, matrícula,
conta bancária, dependentes, pensão, descontos pessoais, endereço residencial ou
nomes de assessores para calcular um total. Cache de equipe será agregado e
minimizado, com a transformação documentada. Documentos brutos contendo esses
campos não serão persistidos integralmente. Dados locais permanecem fora do Git.

## Cobertura local conferida

Leitura somente local do SQLite e de `data/snapshots/perfis.json`
(`generatedAt=2026-10-07T13:32:39+00:00`). Denominadores são os registros do roster,
não a quantidade constitucional de cadeiras.

| Parte | Câmara (513 registros) | Senado (82 registros) |
| --- | ---: | ---: |
| Subsídio de referência aplicável ao cargo; não pagamento individual | 513 | 82 |
| Cota com lançamento importado | 509 | 79 |
| Gabinete com valor e meses publicados | 512 | 0 |
| Auxílios individualizados em componente próprio | 0 | 0 |
| Ocupação de imóvel funcional integrada | 0 | 0 |
| Folha individual integrada | 0 | 0 |

Zeros nesta tabela significam **nenhuma pessoa com a parte integrada**, nunca
pagamento zero. Não certificam a ausência de rubricas de benefício dentro de
outras fontes. Gabinete da Câmara: 503 perfis têm janeiro–julho, 3 junho–julho,
3 maio–julho, 2 abril–julho, 1 somente julho e 1 sem meses. Há 511 seções com
estado `imported` e 2 `partial`; valor disponível não implica seção completa.
A data de atualização da página (7/10) não estende a competência até outubro.

## Regras propostas para a coleta e a apresentação

- Preferir snapshot complementar por pessoa, parte e competência em vez de
  migração SQLite nesta primeira versão. A cota permanece no banco; a composição
  deve acontecer no backend, com uma regra compartilhada por ficha, comparação
  e lista. Nenhuma implementação foi feita nesta fase.
- Guardar valor em centavos inteiros, fonte, URL exata, competência, consulta,
  atualização publicada e estado por parte. O legado de gabinete usa reais;
  converter com precisão decimal na fronteira, sem renomear seus campos.
- Guardar cada resposta aproveitável atomicamente e retomar apenas consultas
  faltantes/falhas; separar `--collect` de reconstrução offline. Falha de uma
  pessoa não derruba as demais nem apaga observação válida anterior.
- Guardar bruto datado e manifesto com URL, parâmetros e hash quando não contiver
  dados pessoais desnecessários. Quando contiver, processar em memória e guardar
  projeção minimizada explicitamente identificada como tal, nunca chamá-la de
  cópia integral. Equipes: somente totais e contagens por gabinete/mês, sem nomes,
  CPF, matrícula, dados bancários, dependentes ou endereço residencial.
- Não obter custo de gabinete multiplicando teto por mês nem cruzando lotação
  atual com folha histórica. Não valorar imóvel funcional por aluguel estimado.
- Subsídio de referência permanece em linha separada do total pago conhecido.
  Se futuramente houver estimativa que o inclua, nomeá-la como estimativa e
  explicar o cálculo; não rotular como pagamento individual comprovado.
- Para 2026, apresentar acumulado em período explícito, sem anualizar meses
  faltantes. Somar apenas competências comuns e confirmadas. Se não houver
  interseção confiável, mostrar partes separadas. Ausência de nota da cota em
  um mês não basta para certificar gasto zero naquele mês.
- Folha individual, quando validada, substitui a referência salarial; não somar
  as duas. Rubricas de auxílio já incluídas na folha/cota não entram duas vezes.
  Descontos não são uma despesa adicional; bruto e líquido não são somados.
- Comparação depende das mesmas partes, competências e natureza para todos os
  pares. Sem isso, ocultar a média, sem preencher lacunas nem comparar Casas.

## Verificação e critérios para as próximas fases

`make check` verifica o produto atual. Os testes existentes de cota e gabinete
cobrem ausência versus zero publicado; os de períodos do resumo verificam os
recortes observados. Como não há ainda um compositor de custo, não se afirma que
exista teste automatizado de soma entre partes com períodos diferentes.

Casos de aceitação obrigatórios para a implementação:

| Entrada | Resultado esperado |
| --- | --- |
| Gabinete ausente; cota disponível | Gabinete sem valor, aviso e exclusão do total; não zero |
| Gabinete publicado como 0 | Preservar 0 e sua competência/fonte |
| Cota jan–set; gabinete jan–jul | No máximo jan–jul confirmado em ambos; restante separado, sem soma anual fictícia |
| Meses sem linha ou interrupção de exercício | Não completar com zero ou salário mensal presumido |
| Referência salarial e folha da mesma pessoa | Folha validada substitui referência no total, sem duplicação |
| Benefício já contido na folha/cota | Exibir desdobramento sem nova soma |
| Pares com partes/períodos diferentes | Sem média comparativa |

Verificação executada: `make check` passou com 202 testes Python e 74 testes Node.
A primeira execução teve bloqueio de bind em localhost no sandbox; a repetição
com permissão para o servidor local passou. `git diff --check` passou. Nenhum
teste de produto novo foi criado numa fase exclusivamente documental.

## Decisão solicitada

Aprovar a Fase 2 com prioridade em folha individual e moradia da Câmara,
reaproveitamento do gabinete e cota existentes e piloto limitado das fontes do
Senado. Se ligação mensal e pagamento individual não forem demonstrados, essas
partes do Senado continuam sem valor; a opção atual de moradia pode ser mostrada
apenas como contexto. A proposta usa 2026 acumulado, com período comum explícito,
referência salarial separada e sem estimar o preço de imóveis ou tetos.

A aprovação desta fase autoriza definir o recorte de coleta; não aprova merge,
push ou publicação. A próxima fase deve medir cobertura efetivamente coletada,
validar as amostras e executar estes testes antes de alterar a ficha.
