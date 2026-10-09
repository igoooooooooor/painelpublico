# Alertas da cota

Os alertas detectam **variação de gasto** e **concentração em fornecedor** nas notas da cota. Não medem
probabilidade de irregularidade: não há validação que permita ler os limites dessa forma. Um contrato
recorrente legítimo pode gerar concentração, e um gasto problemático pode não gerar alerta nenhum.
O cálculo, a cobertura e a apresentação seguem essa neutralidade.

## Regra em uso (`cota-alertas-v3`, desde 8/10/2026)

Um só cálculo, em [`backend/alert_rules.py`](../backend/alert_rules.py), usado na geração dos alertas, na
explicação de cada cartão e na simulação. Avalia as notas do **mandato inteiro** (fev/2023 em diante), na
Câmara e no Senado: as detalhadas do ano corrente (`expenses`) e as dos anos anteriores (visão
`quota_history`), lidas por `public_store.alert_inputs`, a mesma entrada da simulação. O histórico usa
identificadores estáveis (`hist:<pessoa>:<ano>:<mês>:<seq>`).

- **Mês acima da referência:** o gasto do mês é pelo menos 1,75 vez a referência, com diferença de pelo
  menos R$ 10 mil, e fica acima do piso dos colegas. Referência = mediana dos **12 meses anteriores
  completos**, atravessando o ano (`PUBLISHED_BASELINE = 'rolling12'`): os 12 precisam ter notas. Com o
  mandato começando em fev/2023, o primeiro mês avaliável é fev/2024; antes disso o mês fica como
  "histórico insuficiente". Um mês sem notas (ou com saldo negativo) entre os 12 anteriores impede a
  avaliação ("sem base"). Piso = mediana dos meses fechados e positivos dos parlamentares da mesma fonte e
  ano. Meses seguidos marcados formam um alerta só, com todos os meses marcados; o alerta fica dentro de
  um ano, como a cota, cujo saldo expira em 31/12 (dez e jan seguidos marcados são dois alertas).
- **Concentração em fornecedor:** pelo menos 50% e R$ 30 mil das notas do ano para um mesmo fornecedor,
  **ano a ano** desde 2023. Anos fechados não são parciais.
- **Lançamento de valor alto** (tipo `nota`, interno): continua só nas notas detalhadas do ano corrente.
- **Prazos (meses elegíveis):**
  - Câmara: o deputado tem até 90 dias para apresentar a nota, lançada no mês da despesa
    ([guia da Câmara](https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/cota-parlamentar)).
    Um mês só é avaliado se a coleta da fonte ocorreu 90 dias ou mais depois do último dia do mês.
  - Senado: comprovantes do exercício anterior podem ser apresentados até o último dia útil de abril do
    ano seguinte ([APS 5/2014, art. 5º, § 3º](https://adm.senado.gov.br/normas/ui/pub/normaConsultada?idNorma=203003)).
    Um mês só é avaliado com coleta posterior a 30 de abril do ano seguinte. Por isso, em 2026 nenhum mês
    do Senado é avaliado para pico.
  - É um critério conservador de elegibilidade, não garantia de base completa: uma base antiga não fica
    completa só porque o calendário avançou.
  - A data usada é a da **última coleta que forneceu as notas** (`sources.dataFetchedAt`), não a da última
    tentativa. Uma coleta indisponível atualiza o status da fonte, mas não torna meses elegíveis.
- **Período parcial:** a concentração do ano corrente sai como "período parcial", com os meses observados
  e a data da coleta, no cartão e em qualquer ranking que use o valor.
- **Intermediação de passagens:** quando a maioria das notas de uma concentração cita, no registro
  oficial, uma companhia aérea (LATAM/TAM, GOL ou Azul) que não é o fornecedor pago, o alerta sai como
  "Pagamentos de passagens intermediados por uma agência". O total continua visível e não é apresentado
  como receita da agência nem como gasto com uma só companhia. Só o Senado publica a companhia
  (detalhamento do CEAPS); a Câmara não, então lá não há evidência. Quando o registro traz o nome da
  própria agência no lugar da companhia, não há como saber a companhia e a regra não infere nada.
- **Valores absolutos:** a porcentagem da concentração aparece sempre com o valor pago ao fornecedor, o
  total observado e os meses com notas. Sem cobertura suficiente, não se conclui que o gasto do ano foi baixo.
- **Senado, fonte:** o cartão aponta o detalhamento oficial por tipo de despesa e mês
  (`/transparencia/sen/<senador>/ceaps/<tipo>/detalhe/?mesAno=MM/AAAA`) e diz: "Análise dos registros
  publicados; imagem do documento não disponível nesta base."
- **Fim do ano:** novembro e dezembro são avaliados como os outros meses. O alerta continua e o cartão
  informa que o saldo não usado da cota se acumula no ano e expira em 31 de dezembro (campo
  `yearEndMonths` no resultado gravado).

O que fica gravado (`signals.detail`): versão da regra, base (`baseline`), meses marcados com valor,
referência e múltiplo, piso, série do cartão com ano, mês e situação de cada mês (`flagged`, `evaluated`
ou o motivo de não avaliação), data da coleta e se é parcial. A série é a janela usada como referência
(os 12 meses antes do primeiro mês marcado, atravessando o ano), os meses marcados e até 3 meses
seguintes com notas, para a linha de referência bater com a regra. O cartão só lê esses campos; nada é
recalculado. A janela de referência aparece recolhida numa linha (período, miniatura e mediana), que abre
mês a mês na mesma escala; assim os cartões de pico não ficam muito mais altos que os de concentração. O
gráfico mostra uma linha por mês com o valor escrito (e o ano quando é outro, como "dez/23"): os meses
deste alerta em destaque, com a própria referência na barra e o múltiplo ao lado;
meses avaliados sem alerta em cinza (um mês marcado por outro alerta também); meses não avaliados
esmaecidos, com o motivo na legenda.

## Cobertura

`alert_coverage` registra, por pessoa, regra, fonte e ano do mandato, o que foi avaliado e o que não foi,
com o motivo: prazo de apresentação aberto, histórico insuficiente (menos de 12 meses com notas antes do
mês), sem base (mês sem notas entre os 12 anteriores), sem notas no mês, sem piso dos colegas. Meses antes
de fev/2023 não são do mandato e não aparecem como "sem notas". A ficha lista a cobertura do ano mais
recente ao mais antigo, diz "Nenhum alerta nos meses avaliados" só quando alguma regra avaliou algo, e
lista os meses e regras não avaliados. Sem nada avaliável, diz "Dados insuficientes para avaliar".

## Valor das despesas nos alertas

`alert_totals` soma, por pessoa, as notas que estão em algum alerta do mandato, **cada lançamento uma vez
só** pelo identificador do lançamento, com estornos preservados. Num pico agrupado entram todos os meses
marcados. A marca "parcial" vale quando há concentração do ano corrente. É a soma de despesas observadas, não estimativa de prejuízo. Antes, uma nota podia entrar no
pico e na concentração: para a lista atual, eram R$ 972.810,24 contados em dobro.

## Apresentação

Títulos factuais ("Mês acima da referência: maio de 2024", "Concentração em fornecedor"), sem selo de
intensidade nem ordenação por gravidade. A cor identifica o tipo de informação. Comparações não destacam
como "melhor" quem tem menos alertas. A home, a página de Alertas e a ficha mostram os alertas dos mais
recentes aos mais antigos; a página de Alertas filtra por ano (`/api/c/radar?ano=AAAA`) e o resumo diz o
período do mandato ou o ano escolhido.

## Simulação reproduzível

```sh
python3 scripts/alert_simulation.py --sample 2
```

Somente leitura do banco. Grava `data/reviews/alert-simulation.json` com a fotografia (hash do banco,
datas de coleta, número de notas), os parâmetros, a população (lista atual e todos os parlamentares) e,
por Casa e ano, os alertas, os meses-pessoa marcados, avaliados e não avaliados por motivo. Com
`--sample`, sorteia com semente fixa uma amostra por Casa × tipo × ano, casos perto dos limites, casos sem
alerta e casos que só aparecem nas bases móveis.

Três bases, comparadas na mesma fotografia e com a mesma entrada dos alertas gravados:

- **12 meses completos** (publicada desde a v3): os 12 meses anteriores, todos com notas, atravessando o
  ano. Com o histórico começando em fev/2023, só existe a partir de fev/2024; antes disso, o mês fica
  como histórico insuficiente.
- **anual** (regra até a v2, só para comparação): meses anteriores do mesmo ano, ao menos 3.
- **base curta** (só para comparação): de 3 a 12 meses, conforme o histórico disponível.

A amostra (`--sample`) sorteia pela base publicada e acrescenta casos que só apareceriam nas outras duas.
Os números da base de 12 meses na simulação batem com os sinais e a cobertura gravados (conferido em
8/10/2026 por Casa, tipo e ano, nas duas populações).

Resultado em 8/10/2026, lista atual. Taxa = meses marcados ÷ meses avaliados (alertas agrupam meses
seguidos, então não servem de numerador):

| Casa e ano | 12 meses completos (publicada) | Anual | Base curta |
|---|---|---|---|
| Câmara 2023 | 0 de 0 (histórico insuficiente) | 442 de 3.590 (12,31%) | 445 de 3.609 (12,33%) |
| Câmara 2024 | 322 de 4.650 (6,92%) | 312 de 3.851 (8,10%) | 332 de 5.120 (6,48%) |
| Câmara 2025 | 251 de 5.110 (4,91%) | 250 de 4.111 (6,08%) | 263 de 5.194 (5,06%) |
| Câmara 2026 | 168 de 2.658 (6,32%) | 96 de 1.382 (6,95%) | 170 de 2.688 (6,32%) |
| Senado 2023 | 0 de 0 (histórico insuficiente) | 52 de 562 (9,25%) | 52 de 566 (9,19%) |
| Senado 2024 | 41 de 733 (5,59%) | 33 de 599 (5,51%) | 42 de 807 (5,20%) |
| Senado 2025 | 48 de 769 (6,24%) | 50 de 623 (8,03%) | 48 de 777 (6,18%) |
| Senado 2026 | 0 de 0 (prazo aberto) | 0 de 0 (prazo aberto) | 0 de 0 (prazo aberto) |

Gravados na base publicada, para todos os parlamentares: 996 alertas (696 de mês acima da referência e
300 de concentração), de fev/2024 a jun/2026 nos picos e de 2023 a 2026 nas concentrações.

As bases móveis avaliam mais meses (janeiro a março) e marcam uma fração menor ou parecida. A base curta
e a anual marcam muito mais em 2023, quando a referência sai de poucos meses. Nenhuma base está validada.
Na v3, janeiro de 2023 deixou de contar como mês "sem notas" (não é do mandato); por isso a base anual,
que antes não avaliava 2023 por essa falsa lacuna, agora avalia o ano a partir de maio.
(Uma versão anterior deste documento dividia alertas por meses avaliados e trazia 5,7% e 5,0% para 2024;
a métrica correta é a da tabela.)

## Primeira triagem documental (8/10/2026)

56 casos, triados por Claude para revisão humana: 26 alertas da base anual, 4 perto dos limites, 2 sem
alerta e 24 que só aparecem nas bases móveis (10 na de 12 meses, 14 na base curta). A triagem por caso,
com evidências e pendências, fica fora do Git em `data/reviews/` porque traz nomes e hipóteses sobre
pessoas. A amostra inicia a revisão; não demonstra a precisão do sistema.

- **Concentração:** os 16 casos são pagamentos recorrentes de valor mensal fixo ou quase fixo
  (divulgação, consultoria, aluguel, locação), compatíveis com contratos, ou uma agência que intermedeia
  passagens. Os registros, sozinhos, não comprovam a existência nem o conteúdo de contratos.
- **Pico:** em geral 1 ou 2 notas grandes (gráfica, mídia, fretamento). As três notas abertas estavam
  formalmente completas. 6 dos 10 picos são em novembro ou dezembro.
- **Sem alerta:** gasto alto e constante, ou concentração abaixo de 50%, não gera alerta. "Sem alerta"
  não indica gasto baixo nem regular.
- **Só nas bases móveis:** o ganho principal é avaliar janeiro a março, com picos da mesma natureza
  (divulgação, gráfica, fretamento). A base curta gera múltiplos extremos no início do mandato: num caso
  do Senado, 15,5× sobre uma referência de R$ 4,2 mil formada pelos primeiros meses de gasto baixo.

Pendências antes de ampliar para o mandato:

1. **Fim de ano: confirmado (8/10/2026).** Nas duas Casas, o saldo mensal não usado se acumula ao longo
   do ano e se perde em 31 de dezembro:
   - Câmara: "O saldo mensal não utilizado em um mês acumula-se ao longo do exercício financeiro, vedada
     a acumulação de um exercício financeiro para o seguinte"
     ([guia da Câmara](https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/cota-parlamentar)).
   - Senado: o valor mensal "poderá ser remanejado para os meses subsequentes, dentro do mesmo exercício",
     e "em nenhuma hipótese haverá acumulação da CEAPS de um exercício financeiro para o seguinte"
     ([APS 5/2014, art. 5º, §§ 5º e 6º](https://adm.senado.gov.br/normas/ui/pub/normaConsultada?idNorma=203003)).

   Nos dados, dezembro somou 1,38× e 1,34× a média de março a novembro na Câmara (2023 e 2024) e 1,41× e
   1,16× no Senado; em 2025, perto de 1,0× nas duas Casas. Na simulação (base anual, lista atual),
   dezembro tem 26% dos meses marcados como pico e novembro e dezembro juntos, 39%; se os meses
   avaliados fossem iguais, dezembro teria cerca de 11%. Parte dos picos de fim de ano reflete o uso do
   saldo acumulado antes que ele expire.

   **Decisão (8/10/2026): manter os alertas de novembro e dezembro, com contexto.** Gasto é gasto: usar o
   saldo antes que expire também interessa ao cidadão, e omitir esses meses esconderia dinheiro público.
   O cartão informa a regra do saldo anual, sem tratá-la como justificativa.
2. **Mês no Senado: é o mês da despesa (verificado em 8/10/2026).** A documentação da API
   (`/adm-dadosabertos/v3/api-docs`, `DespesaCeapsDto`) não define o campo `mes`, mas três evidências
   apontam para o mês em que a despesa acontece, não para o do reembolso:
   - o mês coincide com o mês da data do documento em 86–89% das notas (2024–2026), como na Câmara (85%);
   - em cerca de 8% das notas a data do documento é **posterior** ao mês (27% em divulgação, faturada
     depois do serviço). Isso seria impossível se o mês fosse o do reembolso, que só acontece depois do
     documento;
   - no portal de transparência, o detalhe do mês mostra que as passagens com data de agosto lançadas
     em dezembro (caso da triagem) são de voos feitos em dezembro: a data é a da compra, o mês é o do
     voo ([exemplo](https://www6g.senado.leg.br/transparencia/sen/5525/ceaps/8/detalhe/?mesAno=12/2024)).

   A regra de pico vale para o Senado como está. O portal traz, por senador, tipo e mês, a lista das
   notas com fornecedor, descrição, data e número do documento, mas não a imagem da nota; a pendência 3
   continua. Essas páginas mostram nomes de servidores nas passagens e não devem ser copiadas.
3. **Documentos do Senado:** a base não traz a imagem do documento do CEAPS. Decidido: o cartão aponta o
   detalhamento oficial e diz que a análise é dos registros publicados. Pedido de acesso à informação
   fica para investigação posterior.
4. **Intermediários de passagem:** tratados à parte, com critério verificável (ver "Regra em uso").
5. **Totais baixos:** mantido o mínimo de R$ 30 mil; o cartão mostra valores absolutos e cobertura.

## Decisões registradas

| Data | Decisão | Motivo |
|---|---|---|
| 8/10/2026 | Regra única gravada (`cota-alertas-v2`); o cartão lê o resultado, sem recalcular | A explicação incluía meses que não passaram pela regra |
| 8/10/2026 | Valor das despesas nos alertas conta cada lançamento uma vez, com estornos; mantém a ordenação por valor | Uma nota entrava no pico e na concentração (R$ 972.810,24 em dobro na lista atual) |
| 8/10/2026 | Câmara: mês avaliado só 90 dias depois do fim do mês, contados até a coleta | Prazo de apresentação das notas |
| 8/10/2026 | Senado: mês avaliado só depois de 30 de abril do ano seguinte; regra por Casa | APS 5/2014, art. 5º, § 3º |
| 8/10/2026 | Concentração do ano corrente marcada como "período parcial" no cartão e nos rankings | O ano ainda pode receber notas |
| 8/10/2026 | Cobertura por regra e período; "Nenhum alerta nos meses avaliados" ou "Dados insuficientes para avaliar" | Não anunciar checagem que não aconteceu |
| 8/10/2026 | Títulos factuais, sem selo de intensidade e sem destaque de "melhor" para menos alertas | A regra mede variação, não conduta |
| 8/10/2026 | Novembro e dezembro avaliados normalmente, com aviso do saldo anual que expira em 31/12 | Gasto é gasto; omitir os meses esconderia dinheiro público |
| 8/10/2026 | Mês do CEAPS tratado como mês da despesa; regra de pico sem mudança para o Senado | Datas posteriores ao mês e detalhe do portal (pendência 2) |
| 8/10/2026 | Prazos usam a data da última coleta que forneceu as notas (`dataFetchedAt`) | Uma coleta indisponível tornava meses elegíveis sem notas novas |
| 8/10/2026 | Senado: cartão aponta o detalhamento oficial e avisa que não há imagem do documento | A base não traz o documento |
| 8/10/2026 | Passagens intermediadas por agência com critério verificável (companhia citada ≠ fornecedor), sem excluir passagens | Não apresentar como receita da agência nem como uma só companhia |
| 8/10/2026 | Mínimo de R$ 30 mil mantido; porcentagem sempre com valores absolutos e meses com notas | Não ajustar o corte pelos casos da amostra |
| 8/10/2026 | Cards de custo dizem a composição: deputado soma quatro partes; cota sozinha não é comparável | Evitar comparação direta entre composições diferentes |
| 8/10/2026 | Base para ampliar ao mandato: 12 meses anteriores completos; antes de fev/2024, histórico insuficiente. A base curta fica só na simulação | Decisão do mantenedor após simulação e triagem |
| 8/10/2026 | `cota-alertas-v3`: picos e concentração no mandato inteiro, Câmara e Senado, com a base de 12 meses; concentração segue por ano; lançamento de valor alto segue só no ano corrente | Implementa a decisão anterior; números iguais aos da simulação |
| 8/10/2026 | Cartão de pico mostra a janela de 12 meses usada, os meses marcados e até 3 seguintes; alerta não atravessa o ano | A linha de referência precisa bater com a regra; a cota é anual |
| 8/10/2026 | Alertas dos mais recentes aos mais antigos, com filtro por ano | Mais de mil alertas no mandato |
| 8/10/2026 | Janela de referência recolhida no cartão; sequência de 3 meses ou mais com uma frase só | Cartões da mesma linha têm a mesma altura e o pico ocupava o dobro |
| Em aberto | Pedido de acesso aos documentos do Senado | Investigação posterior |
