# Alertas da cota

Os alertas detectam **variação de gasto** e **concentração em fornecedor** nas notas da cota. Não medem
probabilidade de irregularidade: não há validação que permita ler os limites dessa forma. Um contrato
recorrente legítimo pode gerar concentração, e um gasto problemático pode não gerar alerta nenhum.
O cálculo, a cobertura e a apresentação seguem essa neutralidade.

## Regra em uso (`cota-alertas-v2`, desde 8/10/2026)

Um só cálculo, em [`backend/alert_rules.py`](../backend/alert_rules.py), usado na geração dos alertas, na
explicação de cada cartão e na simulação. Hoje só as notas detalhadas do ano corrente (2026) são avaliadas.

- **Mês acima da referência:** o gasto do mês é pelo menos 1,75 vez a referência, com diferença de pelo
  menos R$ 10 mil, e fica acima do piso dos colegas. Referência = mediana dos meses anteriores do mesmo
  ano, com ao menos 3 meses e sem lacuna. Piso = mediana dos meses fechados e positivos dos parlamentares
  da mesma fonte e ano. Meses seguidos marcados formam um alerta só, com todos os meses marcados.
- **Concentração em fornecedor:** pelo menos 50% e R$ 30 mil das notas do ano para um mesmo fornecedor.
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
- **Período parcial:** a concentração do ano corrente sai como "período parcial", com os meses observados
  e a data da coleta, no cartão e em qualquer ranking que use o valor.
- **Fim do ano:** novembro e dezembro são avaliados como os outros meses. O alerta continua e o cartão
  informa que o saldo não usado da cota se acumula no ano e expira em 31 de dezembro (campo
  `yearEndMonths` no resultado gravado).

O que fica gravado (`signals.detail`): versão da regra, meses marcados com valor, referência e múltiplo,
piso, série usada, data da coleta e se é parcial. O cartão só lê esses campos; nada é recalculado.

## Cobertura

`alert_coverage` registra, por pessoa, regra, fonte e ano, o que foi avaliado e o que não foi, com o
motivo: prazo de apresentação aberto, menos de 3 meses anteriores, sem notas no mês, sem piso dos
colegas. A ficha diz "Nenhum alerta nos meses avaliados" só quando alguma regra avaliou algo, e lista os
meses e regras não avaliados. Sem nada avaliável, diz "Dados insuficientes para avaliar".

## Valor das despesas nos alertas

`alert_totals` soma, por pessoa, as notas que estão em algum alerta, **cada lançamento uma vez só** pelo
identificador do lançamento, com estornos preservados. Num pico agrupado entram todos os meses
marcados. É a soma de despesas observadas, não estimativa de prejuízo. Antes, uma nota podia entrar no
pico e na concentração: para a lista atual, eram R$ 972.810,24 contados em dobro.

## Apresentação

Títulos factuais ("Mês acima da referência", "Concentração em fornecedor"), sem selo de intensidade nem
ordenação por gravidade. A cor identifica o tipo de informação. Comparações não destacam como "melhor"
quem tem menos alertas.

## Simulação reproduzível

```sh
python3 scripts/alert_simulation.py --sample 2
```

Somente leitura do banco. Grava `data/reviews/alert-simulation.json` com a fotografia (hash do banco,
datas de coleta, número de notas), os parâmetros, a população (lista atual e todos os parlamentares) e,
por Casa e ano, os alertas e os meses-pessoa avaliados e não avaliados por motivo. Compara a base anual
(regra em uso) com a de 12 meses (hipótese em estudo). Com `--sample`, sorteia com semente fixa uma
amostra por Casa × tipo × ano, mais casos perto dos limites e sem alerta.

Resultado em 8/10/2026, lista atual (pico / concentração; meses-pessoa avaliados):

| Casa e ano | Base anual | Base de 12 meses |
|---|---|---|
| Câmara 2023 | 0 / 45; 0 avaliados (a base exige janeiro) | 301 / 45; 3.609 |
| Câmara 2024 | 220 / 44; 3.851 | 255 / 44; 5.120 |
| Câmara 2025 | 179 / 40; 4.111 | 197 / 40; 5.194 |
| Câmara 2026 | 85 / 67; 1.382 | 144 / 67; 2.688 |
| Senado 2023 | 0 / 11; 0 | 41 / 11; 566 |
| Senado 2024 | 27 / 10; 599 | 31 / 10; 807 |
| Senado 2025 | 37 / 10; 623 | 36 / 10; 777 |
| Senado 2026 | 0 / 12; 0 (prazo aberto) | 0 / 12; 0 |

A base de 12 meses gera mais alertas sobretudo porque avalia mais meses (janeiro a março e 2023), não
por marcar uma fração maior: em 2024, 5,7% dos meses avaliados na base anual e 5,0% na de 12 meses.
Continua uma hipótese, não uma escolha validada.

## Primeira triagem documental (8/10/2026)

32 casos (26 alertas, 4 perto dos limites, 2 sem alerta), triados por Claude para revisão humana. A
triagem por caso, com evidências e pendências, fica fora do Git em `data/reviews/` porque traz nomes e
hipóteses sobre pessoas. Trinta casos iniciam a revisão; não demonstram a precisão do sistema.

- **Concentração:** os 16 casos são contratos recorrentes de valor mensal fixo (divulgação, consultoria,
  aluguel, locação) ou uma agência que intermedeia passagens. A regra identifica a estrutura de
  contratação, não um gasto atípico.
- **Pico:** em geral 1 ou 2 notas grandes (gráfica, mídia, fretamento). As três notas abertas estavam
  formalmente completas. 6 dos 10 picos são em novembro ou dezembro.
- **Sem alerta:** gasto alto e constante, ou concentração abaixo de 50%, não gera alerta. "Sem alerta"
  não indica gasto baixo nem regular.

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
3. **Documentos do Senado:** a base não traz link de documento do CEAPS.
4. **Intermediários de passagem:** agências concentram passagens de várias companhias.
5. **Totais baixos:** a concentração alcança quem gasta pouco no ano.

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
| Em aberto | Base anual ou de 12 meses para ampliar ao mandato | Simulação feita; falta decidir |
| 8/10/2026 | Mês do CEAPS tratado como mês da despesa; regra de pico sem mudança para o Senado | Datas posteriores ao mês e detalhe do portal (pendência 2) |
| Em aberto | Documentos do Senado, intermediários de passagem, totais baixos | Pendências da triagem |
