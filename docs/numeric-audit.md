# Varredura numérica — 11/10/2026

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
