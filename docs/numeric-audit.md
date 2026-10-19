# Varredura numérica

## Segunda revisão de 19/10/2026 — números contra as páginas oficiais

Percorremos home, fichas, lista, comparar, partidos, presença, Placar e Minha cidade como um leitor, abrindo
cada fonte. Bateram com a fonte: salário e auxílios (remuneração de jul/2026), verba de gabinete, presença somada
ano a ano, Placar (ex.: PLP 74/2026, 346–46–3; PL 45–23; PT 52–0 na API da Câmara) e cota do Senado por mês
(Randolfe Rodrigues, jul/2026: R$ 85.722,91 nos detalhamentos por tipo).

- **Cota da Câmara sem as passagens da agência (SIGEPA) desde ago/2025:** o arquivo anual trazia a subcota 998
  ("PASSAGEM AÉREA - SIGEPA") até jul/2025 e deixou de trazer depois; a página do(a) deputado(a), linkada no próprio
  cartão de custo, soma esses bilhetes. Felipe Francischini (`camara:204398`), jul/2026: R$ 33.700,83 de cota no
  cartão, R$ 38.672,59 na Câmara; jun/2026, a diferença é exatamente a linha "PASSAGEM AÉREA - SIGEPA R$ 5.770,12"
  do detalhamento. Numa amostra de 35 deputados(as), jan–jul/2026: diferença mediana de R$ 9,4 mil por mês (21%),
  máxima de 52%. Afetava custo, cota média, rankings, total da home, categorias, imposto equivalente e a referência
  dos alertas (que passava a comparar meses sem os bilhetes com meses que os tinham). Correção: coletor
  `ingest/chamber_sigepa.py` e mescla em `load_chamber_expenses` (ver [Dados](data.md#coletas-manuais)); os textos que
  diziam que as passagens ficavam de fora agora dizem de onde elas vêm. Na base local refeita: 27.237 linhas em
  ago–dez/2025 (R$ 3,6–5,1 mi por mês, o mesmo nível de jan–jul/2025 no arquivo) e 39.676 em 2026; Felipe Francischini
  bate centavo a centavo com o gráfico da Câmara nos 12 meses de 2025, e o total de 2026 (R$ 413.824) e jun/2026
  (R$ 135.979) também. Jul/2026 fica R$ 0,03 acima do gráfico porque a própria lista de bilhetes da Câmara soma
  R$ 4.971,79 e o gráfico arredonda para menos; seguimos a lista item a item. Efeitos: custo médio do(a) deputado(a)
  de R$ 204 mil para R$ 207 mil por mês (mediana +R$ 2,1 mil por pessoa, máximo +R$ 27 mil), cota do mandato de
  R$ 782,8 mi para R$ 836,0 mi, passagens aéreas de R$ 103,8 mi para R$ 157,0 mi, outro 1º lugar em "Quem mais usa a
  cota" e 804 alertas em vez de 803, com as mesmas regras. `make audit-numbers`: 19.691 meses de cota conferidos,
  nenhuma divergência. A página analítica dá erro 500 para alguns IDs em qualquer tipo de despesa; nesses casos, o
  resumo por tipo do mesmo período comprova quando não há bilhete (33 casos em 2026). Ficaram sem consulta 1 conta de
  liderança em 2026 e 27 cadastros em 2025, dos quais 8 na lista atual, todos sem nenhuma nota em ago–dez/2025 no
  arquivo (ministros licenciados, entre outros), então nada do que o site mostra muda.
- **Contexto dos alertas com total e média de períodos diferentes:** "Em 2026, gastou R$ 352.433 na cota, R$ 47.589
  por mês em média nos 7 meses com notas assentadas": 352.433 ÷ 7 dá 50.347, porque o total soma jan–out e a média só
  jan–jul. A frase agora nomeia os dois períodos quando eles diferem.
- **Link da cota no custo do Senado:** "Página do Senado ↗" não mostrava valor nenhum. Corrigido na mesma data pela
  segunda varredura das fichas de senadores (abaixo): o link abre a cota do ano no portal de transparência.
- **Minha cidade, "47% acima do típico" sob a barra de Educação:** o veredito era do gasto total (Campinas: R$ 8.979
  contra típico de R$ 6.115, que não aparecia), mas lia-se como Educação (R$ 1.762 contra R$ 1.241, 42%). Agora diz
  "Gasto total" e mostra o típico total.
- **Emendas da cidade sem a cobertura:** só 3% do valor reservado em emendas de 2026 (R$ 1,35 bi de R$ 40,1 bi)
  informa a cidade de destino; "R$ 443 mil em 1 emenda" para Campinas parecia tudo o que chegou. O cartão agora diz
  essa fatia e que pode ter chegado mais.
- **Fatias da cota na ficha acima de 100% com estornos:** o resumo "Onde gastou a cota" ainda dividia pelo total
  líquido (Aline Gurgel: 60% + 44% e "−5% do total"); a imagem e o detalhe já usavam os saldos positivos. Agora o
  resumo também usa os saldos positivos quando há categoria negativa e tira a fatia dos fornecedores quando algum
  fornecedor tem saldo negativo. Com as passagens SIGEPA, a categoria de passagens da Aline Gurgel deixou de ser
  negativa (os estornos eram de bilhetes que faltavam), mas a GOL segue com −R$ 4.045,94 em estornos sem bilhete no
  período; sem a regra nova, os três maiores fornecedores somariam 103%.
- **Período do "Quem mais usa a cota":** dizia "fev/2023 a out/2026", mas a média vai só até o último mês assentado.
  O período agora termina nele (`mediaPeriodo` no resumo).
- **Verba de gabinete publicada como R$ 0,00:** 15 perfis da lista atual têm meses usados no custo com R$ 0,00 de gabinete
  na própria Câmara, mesmo com equipe listada (Hildo Rocha, `camara:178884`: 5 pessoas ativas, R$ 0,00 em todos os
  meses de 2026). É o valor publicado e fica; o cartão avisa que o total pode estar sem o custo da equipe. É o que
  produz o "menor" da home (Paulo Soares, 2 meses: R$ 52 mil antes das passagens SIGEPA, R$ 56 mil depois).

- **Trava diária do custo barrando nota removida pela Câmara:** desde a atualização das 8h49 de 19/10/2026, a
  recomposição do custo era recusada ("camara:220643 2026-03 lost numeric quota"): a Câmara tirou do arquivo o único
  lançamento de mar/2026 de Sônia Guajajara, um complemento de auxílio-moradia (cota 0), num mês fora da média. O
  custo publicado ficava parado. A trava agora aceita uma cota que some só quando a recomposição conferiu a fonte
  inteira contra o banco (sem `quota_snapshot_unverified`); meses usados, outras partes e arquivo local faltando
  continuam barrados.

Ficam como estão, documentados: presença soma até set/2026 e a página de 2026 da Câmara já inclui outubro; notas de
um mês podem ter data de emissão no mês seguinte (competência da Câmara).

## Revisão de 19/10/2026

- **Média da cota com meses ainda em aberto:** `authority_totals.monthCount` contava todo mês com
  qualquer nota, inclusive os que ainda recebem notas. Na base de 8/10/2026, out/2026 já tinha notas
  de 96 deputados (R$ 107 mil no total, vários com R$ 100) e contava como mês inteiro; set/2026 somava
  R$ 4,3 mi contra cerca de R$ 20 mi de um mês cheio. Resultado: 457 de 511 deputados com média menor
  que a dos meses assentados (mediana −2,7%; Marcelo Nilo, `camara:204558`, **R$ 33 mil** em vez de
  **R$ 43 mil**), e o 1º lugar do "Quem mais usa a cota" trocava de pessoa. Enquanto isso, o cartão de
  custo ao lado já deixava esses meses fora da média (regra dos 3 meses de `a08028d5`). A média da cota
  (ficha, home, lista, partidos, comparar, imagem, buscadores, média do cargo por ano e contexto dos
  alertas) passa a usar a mesma regra, em `backend/settlement.py` e nas colunas `settled*` de
  `authority_totals` (esquema v8); total, mês a mês e alertas seguem com todas as notas, e a ficha
  marca os meses em aberto. Sem nenhum mês assentado, valem todos, como no custo.

- **Link da presença só de 2026:** o cartão "Presença no Plenário" soma fev/2023–set/2026 (ex.: 334 de
  391 dias), mas "Fonte da presença na Câmara" abria só a página de 2026, com cerca de 90 dias. A Câmara
  publica um ano por página; a ficha, as fontes e o comparativo passam a trazer um link por ano do período
  observado e dizem que o número soma os anos.
- **"Conferir na fonte" dos alertas abria a página do deputado:** o gráfico de gastos dessa página inclui
  passagens aéreas que ficam fora do arquivo aberto das notas (`docs/data.md`, "Notas do mês"), então o
  valor do mês lá não bate com o do alerta. Na Câmara, cada mês marcado abre aqui a lista de notas (a mesma
  do cartão de custo), a concentração em fornecedor oferece o CSV com todas as notas, e o link passa a se
  chamar "Página na Câmara", com a ressalva. O texto "sem as passagens aéreas da Câmara" era impreciso: o
  arquivo aberto traz 343 notas de "PASSAGEM AÉREA - REEMBOLSO/RPA" em 2026 (R$ 791 mil); o que fica fora
  são as passagens que só aparecem no gráfico da página do deputado. Textos ajustados na ficha, nos
  alertas, em comparar, partidos, metodologia e páginas para buscadores.

- **Minha cidade, população de outro ano:** o cabeçalho mostra a estimativa do IBGE para 2026 e o "por
  morador" dividia pela população de 2025 (o ano das contas) sem dizer o ano; quem dividisse o total pelo
  número do cabeçalho chegava a outro valor (ex.: Manaus, 2.327.101 × 2.303.732). O cartão e o detalhe das
  contas agora nomeiam o ano da população usada.
- **"Placar em 2026":** o vazio das votações no comparativo e a nota de fontes da ficha diziam que o Placar
  cobre 2026; a seleção vai desde fev/2023, como o próprio título da seção diz. Textos corrigidos.

- **Ajustes menores da mesma varredura:** (1) Placar: em 83 de 187 votações o resumo da Câmara não publica
  abstenções, mas Sim + Não fecham o total (conferido com o relatório nominal na coleta); o cartão dizia
  "Abstenção — não publicada" ao lado de "O total soma Sim, Não e Abstenção". Passa a mostrar 0, "nenhuma no
  relatório nominal"; "não publicada" fica só quando nem isso se sabe. (2) Imagem de compartilhar: partes
  abaixo de R$ 100 mil com uma casa decimal, para somarem o destaque e R$ 400 não virar "R$ 0 mil". (3) Notas
  do mês: a instrução de somar `vlrLiquido` no arquivo anual avisa para deixar de fora as linhas de
  complemento de moradia quando o mês as tem. (4) Minha cidade: "Receita" vira "Receita bruta", com a nota de
  que o Siconfi destaca a líquida, menor; o percentual pago nunca arredonda para 100% com parte em aberto
  ("mais de 99%"), e "Nada foi pago" passa a citar restos a pagar pagos depois, quando houver. (5) Páginas
  sem JavaScript: "R$ N mil" arredonda meio para cima como no app (Python `round()` ia para o par). (6)
  Comparar: as linhas de remuneração e gabinete dizem "média de N meses com a parte publicada", já que não
  usam o corte de meses assentados do total. (7) Texto para buscadores: quando nenhum mês tem a folga de 3
  meses, a linha do custo avisa que a cota do mês ainda recebe notas.

- **Metodologia e home sem a regra dos 3 meses do custo:** diziam só "nos meses com todas as partes
  publicadas", enquanto a ficha deixa fora os meses com notas chegando. Textos alinhados.
- **"Salário bruto" diferente do subsídio da página oficial:** a linha soma todas as tabelas da página de
  remuneração do mês (normal e complementares, inclusive férias e retroativos), então em alguns meses mostra
  mais do que os R$ 46.366,19 que a página destaca. A linha agora diz "acima do subsídio de R$ 46.366,19:
  inclui férias, retroativos ou outras parcelas pagas no mês" (ou "abaixo…: redução ao teto constitucional, exercício por parte do mês ou outro
  desconto publicado"), só a partir de fev/2025, quando esse subsídio vale.

- **Fichas de senadores (segunda varredura):** (1) a linha da cota linkava "Página do Senado" para um JSON de
  dados abertos; agora abre a cota do ano no portal de transparência (CEAPS). (2) Bruto da folha zero ou
  negativo (acerto ou abate-teto; 4 meses na base, um deles o mês principal de Pedro Chaves) era somado como
  remuneração; passa a "não identificado", com motivo, no cartão e em `backend/costs.py`. (3) "Equipe e verba
  de gabinete" fazia a média de todos os meses, inclusive os em aberto, enquanto o cartão usava só os
  assentados (97 de 104 senadores com contagens diferentes); agora usa o mesmo corte e diz o que fica fora.
  (4) "de N no recorte" misturava os meses da pessoa com o período do snapshot. (5) "24 sessões com presença
  / de 23 em exercício" (Hermes Klann): o total nunca fica abaixo das presenças. (6) O período das votações
  nominais ia até a data em que o coletor rodou (19/10), depois da "Fotografia" (11/10): passa a terminar na
  data da consulta. (7) O resumo de votos dos senadores ganha a linha dos registros de licença, missão ou
  atividade parlamentar e a nota das votações sem linha individual, como na Câmara; "votou em" vira "votou ou
  presidiu em". (8) "O mandato começou em…" usava o trecho de exercício mais recente (errado para 15
  senadores, como Chico Rodrigues e Renan Calheiros); agora usa a sequência no cargo (`tenure.json`). (9)
  "Fontes e datas" mostrava a fonte de gabinete da Câmara para senadores; passa a listar a folha do Senado e
  o histórico de exercício. (10) O "Qual mês aparece" do Senado diz que as notas podem entrar até abril do
  ano seguinte. (11) Resumo e imagem avisam "a cota do mês ainda recebe notas" quando nenhum mês tem a folga.
- **Páginas para buscadores:** a ficha de senador(a) só tinha a cota (R$ 34 mil para Esperidião Amin,
  contra R$ 332 mil do app); ganha a linha "Quanto custa" das despesas do Senado e a presença registrada.
  "da Senado Federal" corrigido. Trechos do Placar: o tipo (emenda, destaque, bloco) e a frase "faz parte da
  votação do texto" com o resultado, como no app. Percentuais e "% acima da média" arredondam meio para cima
  como o app. Rodapé da home diz o denominador dos percentuais. `llms.txt` descreve o mês de referência.
- **Presença dos deputados:** "391 sessões de votação" vira "391 dias com sessão deliberativa"; "não faltaram
  nenhum dia" conta só quem tem o mandato inteiro (antes, 12 dos 22 tinham de 14 a 125 dias); quem chegou
  depois aparece com "desde jun/2026" na lista; "falta justificada" descrita como qualquer motivo publicado
  (inclusive "decisão da Mesa", 726 dias na base). O status "Presença (~)" (172 dias, 117 deputados) era
  classificado como falta justificada pelo coletor; conferido na página da Câmara em 19/10 (Altineu Côrtes,
  20/03 e 17/06/2025): é o dia com mais de uma sessão em que a pessoa esteve em uma e teve justificativa na
  outra, e a Câmara o conta como presença no quadro anual. O coletor passa a contar como presença; os
  números mudam quando `presenca.json` for recomposto (`python3 ingest/chamber_mandate_history.py`, sem
  rede, a partir do cache, ou na coleta mensal).
- **Metodologia:** lacuna confirmada (dez/2024, gabinete) explicada; "3 meses de folga" com exemplo e aviso de
  que é mais curta que os 90 dias dos alertas; regra do Senado com a mesma folga; "sem base" inclui saldo
  negativo; "custo refeito todo mês" vira "recomposto todo dia".

## Varredura de 18/10/2026

Revisão adicional motivada pela troca da média pelo mês de referência no cartão de custo
(commits `6fa52f65` e `a08028d5`). A revisão começou com código e dados locais; as correções
foram autorizadas para publicação, com nova auditoria sobre os dados do servidor.

## Inconsistências confirmadas nesta revisão

- **Cota desatualizada no custo do mandato:** o banco e as notas históricas haviam sido atualizados
  em 13/10, mas `mandate-cost.json` ainda usava notas anteriores. A atualização diária não recompunha
  esse arquivo. Exemplo: Sargento Fahur (`camara:204387`), jul/2026, aparecia com **R$ 9.514,36** de
  cota no custo, enquanto as notas do mesmo mês somavam **R$ 18.730,16**. Recompusemos o snapshot
  offline a partir dos arquivos oficiais já coletados e do banco. **482 médias** mudaram; salário,
  auxílios e gabinete não mudaram nos perfis presentes nas duas versões. A lista de perfis também
  acompanha a lista atual do banco. O arquivo anterior foi preservado em
  `data/backups/numeric-audit-2026-10-18/mandate-cost.json`; o banco não foi alterado.
  A atualização diária passa a recompor o custo existente, inclusive com `--db-only`, e a auditoria
  confere a cota mensal do custo contra as notas. A recomposição diária recusa perda de cobertura
  quando faltam arquivos locais; falhas ficam registradas no status e preservam o custo anterior.
- **Percentuais superiores a 100% com estornos:** Aline Gurgel (`camara:204353`) tem **R$ 90.101,14**
  nas categorias com saldo positivo, **−R$ 4.045,94** em passagens e total líquido de **R$ 86.055,20**.
  A imagem de compartilhamento dividia as categorias positivas pelo total líquido, produzindo
  aproximadamente **105%**. A distribuição passa a usar a soma dos saldos positivos e explica os
  estornos; os totais líquidos e valores negativos são preservados. Percentuais de fornecedores,
  calculados sobre o mesmo denominador inadequado, deixam de aparecer.
- **Meses que a tela dizia incluir na média:** o detalhamento mensal usava `usedMonths` diretamente,
  sem o filtro dos três meses de folga aplicado ao número principal. A marcação agora acompanha os
  meses efetivamente usados na média. Reproduzido com dados de teste: em uma fotografia de setembro,
  julho ficava fora da média mas recebia a etiqueta “entra na média”. Na base local de outubro, com
  custos até julho, esse filtro ainda não exclui meses; a falha reapareceria ao importar agosto.
- **Ausência na base atribuída à fonte:** “Por que este mês?” afirmava que Câmara/Senado ainda não
  haviam publicado o mês seguinte apenas porque ele não estava no snapshot. O texto agora descreve
  a disponibilidade na base do painel, sem afirmar algo que a coleta não comprovou. As explicações
  da lista e a imagem de comparação também identificam a média explicitamente, evitando confundi-la
  com o número principal do mês na ficha.
- **Soma parcial apresentada como custo completo:** um mês com lacuna confirmada na verba de gabinete
  podia ser escolhido como número principal, somando apenas as outras três partes. O cartão e o
  resumo para buscadores agora exigem as quatro partes para um total mensal. A regra da média de
  cada parte permanece. Dez/2024 contém essa lacuna real; ela não afetava o mês principal de julho
  na fotografia atual, mas foi reproduzida e coberta por regressão.

- **Valor pequeno arredondado para zero:** a telefonia de Aline Gurgel, **R$ 1,14**, aparecia como
  “R$ 0 mil” no detalhamento. A formatação compacta agora conserva centavos abaixo de R$ 1.000,
  inclusive para estornos, e mantém a mesma regra no conteúdo entregue pelo servidor.

Na preparação do deploy, a proteção de cobertura detectou outro caso no servidor: a seção de gabinete
de Gustavo Gayer tinha todos os valores mensais publicados, mas status `partial` por não trazer a
contagem de funcionários. Isso excluía meses válidos da recomposição. A elegibilidade agora aceita
o valor mensal publicado nesse status; valor ausente ou desatualizado continua impedindo o uso.
A ausência da contagem de funcionários não transforma a verba observada em dado ausente.

## Valores oficiais que ainda exigem conferência

Além de Epitaciolândia, descrita na revisão abaixo, **Confins (MG), IBGE 3117876**, tem receita total
realizada de **R$ 776.110,40** e despesa total empenhada de **R$ 87.680.742,29** em 2025. O arquivo
`data/raw/finbra.csv` (linha 674632, `DCA-Anexo I-C`, “Receitas Brutas Realizadas”,
`siconfi-cor_TotalReceitas`) contém `776110,4`; snapshot e API local reproduzem o valor corretamente.
Essa diferença exige conferir a declaração; não prova erro de conversão nem permite substituir o
valor por uma estimativa. A consulta à API oficial de Confins não pôde ser concluída nesta revisão.
Os dois indicadores continuam pendentes de reconciliação com os balanços municipais; não foram
alterados nem sinalizados automaticamente na interface.

## Verificação desta revisão

Foram revisados custo, fontes por mês, médias, comparações, compartilhamento, categorias, fornecedores,
presença, partidos e contas municipais. A verificação usa a fotografia local e não certifica que
produção tenha os mesmos arquivos. As receitas municipais pendentes mostram por que uma auditoria
aritmética não garante a exatidão de toda declaração oficial.

A auditoria ampliada comparou **19.661 valores mensais de cota**, sem divergências na base recomposta
(**401.887 verificações**, nenhuma ocorrência). Aplicada ao backup anterior, identifica **12.217
divergências**, demonstrando que agora detecta o problema. Casos sem notas observadas permanecem
sem verificação, nunca convertidos automaticamente em zero. `make check` cobre as regressões de
cálculo, exibição e atualização diária; a revisão de espaço dos cartões usa o desenho em canvas
instrumentado nos testes, sem automação de navegador.

## Revisão anterior — 11/10/2026

Auditoria do código e da base local. Não certifica a base que está no servidor nem a exatidão das
declarações oficiais. Nenhum banco ou snapshot foi alterado.

## Correções

- **Contexto dos alertas:** a média mensal de uma pessoa em um ano era comparada à média do mandato
  inteiro. A comparação agora usa membros da lista atual com notas no mesmo ano do alerta e informa
  esse ano. Na fotografia auditada, um contexto de 2025 passava de cerca de 24% para 8% acima da
  referência ao corrigir o período. As regras que geram os alertas não mudaram.
- **Contas municipais:** o texto da comparação usava a quantidade de cidades com qualquer dado,
  mesmo quando faltavam valores para um indicador. Agora cada mediana informa sua própria amostra.
  Em Acrelândia, três indicadores usam 1.330 cidades; outros usam 1.331.
- **Concordância de votos:** “Presidiu” continua no registro individual, mas deixa de contar como
  voto no cálculo de concordância entre duas pessoas e na referência geral, inclusive na imagem
  compartilhada. A referência da fotografia local muda de 74,09% para 74,39%.
- **Presença ausente:** uma base vazia não exibe mais 0% de presença média. O resumo das fichas
  enviado aos buscadores também rejeita contagens inconsistentes, como 20 presenças em 10 dias.
- **Impostos:** fontes de anos diferentes não são somadas; a fonte federal do ano anterior não é
  extrapolada após a virada do ano em Brasília. População ausente ou inválida não produz infinito.

## Pendência antes de publicar os dados municipais

**Epitaciolândia (AC), código IBGE 1200252, exercício 2025:** a receita total aparece como **R$ 132,01**,
contra **R$ 18.623.700,06** de despesa empenhada. Esse valor exige conferência; não foi considerado
confiável apenas porque a aritmética passou nos testes.

O arquivo local `data/raw/finbra.csv`, linha 687550, contém o valor `132,01` na coluna
“Receitas Brutas Realizadas”, conta `siconfi-cor_TotalReceitas`. A projeção local da DCA e o snapshot
também contêm 13.201 centavos. A seleção da conta e a conversão para centavos foram conferidas.
As [instruções oficiais da DCA 2025](https://siconfi.tesouro.gov.br/siconfi/pages/public/arquivo/conteudo/2026_Regras_Gerais_e_Instrucoes_de_preenchimento_DCA_2025.pdf)
indicam valores em unidades de reais, sem escala de milhares.

A consulta direta à [DCA individual no SICONFI](https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=1200252)
foi concluída antes da publicação das correções: a resposta completa, com 331 linhas e sem paginação
pendente, confirma `valor: 132.01` em `DCA-Anexo I-C`, coluna “Receitas Brutas Realizadas”, conta
`TotalReceitas`. Portanto, o valor também está na API oficial atual, não apenas no arquivo local.
Falta reconciliá-lo com o [Balanço Anual 2025 da prefeitura](https://www.epitaciolandia.ac.gov.br/publicacoes-transparencia/balan%C3%A7o-anual-2025),
cujo anexo não pôde ser consultado. Não há evidência para substituir o valor por outro, nem para
atribuir a origem da divergência à prefeitura ou ao Tesouro. A recomendação é sinalizar esse indicador
como “em conferência”; essa sinalização ainda não foi implementada.

Em uma linha de emenda de Campos dos Goytacazes (`202641580011`), o arquivo-fonte local informa
R$ 81.803,20 pagos e R$ 64.441,00 empenhados. Os totais municipais fecham com os registros, e a tela
não apresenta essa linha como percentual de execução. Pagamento e empenho não foram tratados como
conjuntos necessariamente equivalentes; esse registro não foi classificado como erro aritmético.

## Cobertura da revisão

- 594 membros da lista atual (513 deputados e 81 senadores) e 23 partidos.
- 512 registros de presença da Câmara, todos consistentes, com taxas entre 43,83% e 100%.
- 187 votações do Placar e 212 decisões sobre trechos; detalhes nominais conferidos.
- Agregados de notas, meses, categorias, fornecedores e custos: sem divergência nas recomposições
  auditadas. Estornos foram preservados; valores altos não foram descartados por serem altos.
- 5.571 registros municipais nos snapshots de cidades, contas e emendas, revisados quanto a cobertura,
  somas, população e relações entre indicadores.
- A correção anterior de `comAlerta` foi preservada: em todos os partidos, pessoas com alerta não
  superam pessoas com notas. A quantidade de eventos de alerta pode superar a de pessoas.

## Checagem repetível

`make audit-numbers` verifica relações de cobertura, pessoas com alerta, custos mínimos/médios/máximos,
contagens de presença e placares, além de números não finitos. O banco é aberto somente para leitura;
snapshots opcionais ausentes são informados como não verificados. Uma violação produz saída com erro.

Essa checagem passou na fotografia local. Ela **não detecta todo valor implausível vindo da fonte**:
a receita de Epitaciolândia continua sendo uma pendência mesmo com o resultado automático sem violações.
Antes de publicar, execute a auditoria sobre os dados que serão efetivamente usados e resolva essa pendência.
