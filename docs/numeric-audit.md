# Varredura numérica

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
