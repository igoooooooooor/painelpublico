# Período do mandato — até onde vai cada fonte

Consulta em 8 de outubro de 2026. Somente levantamento: nenhuma coleta em massa,
nenhuma alteração de banco, snapshot ou ficha. Amostras pontuais (poucas pessoas,
poucos meses) em diretório temporário, descartadas depois da leitura. Fonte que
responde não significa cobertura importada; amostra não certifica todas as pessoas.

Recorte pedido: mandato atual, desde fevereiro de 2023 (legislatura 57, de
1/2/2023 a 31/1/2027). Contexto e decisões em [Próximas etapas](roadmap.md).

## Resumo

| Parte | Câmara desde fev/2023 | Senado desde fev/2023 | Custo estimado de coleta |
| --- | --- | --- | --- |
| Cota | Sim: arquivos anuais 2023, 2024 e 2025 publicados | Sim: API CEAPS 2023 com os 12 meses | Baixo: 3 arquivos/ano por Casa |
| Folha individual | Sim: consulta por ID e `mesAno` responde em 02/2023 | Não comprovado: CSV mensal sem ID (ver abaixo) | Alto na Câmara: ~513 × 44 meses |
| Gabinete | Sim, com lacuna: perfil anual tem meses de 2023–2025, mas **dez/2024 ausente** em 3 de 3 amostras | Possível via lotação no CSV mensal, requer decisão | Baixo na Câmara: ~513 × 3 páginas |
| Auxílios / moradia | Sim: consulta mensal de 02/2023 lida pelo coletor atual sem ajuste | Indisponível para série: API só traz a situação atual | Médio: ~37 páginas × 44 meses |
| Presença | Sim: dias por ano no perfil anual (2023, 2024, 2025) | Parcial: votações 2023 na API; presença hoje vem de PDF dos diários | Baixo na Câmara; alto no Senado |
| Votações | Sim: API lista 1.296 votações só em fev–abr/2023 | Sim: API traz 141 votações de 2023, todas com votos | Médio |

Conclusão: **na Câmara as quatro partes do custo cobrem o mandato inteiro**, exceto
o gabinete de dezembro/2024. Pela regra combinada, a média do mandato usaria os
meses em que as quatro partes existem, com dez/2024 fora e escrito ao lado — ou
apenas aquele mês sem gabinete, se for aprovado exibir lacunas parciais. No Senado,
só cota e votações têm série confiável; folha e gabinete dependem da decisão abaixo.

## Câmara

**Cota (CEAP).** `https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip` publicado para
2023 (6,1 MB), 2024 (6,2 MB) e 2025 (6,0 MB), todos com `last-modified` de 8/10/2026:
os arquivos antigos continuam sendo regravados, então a coleta deve registrar a data.
É o mesmo coletor de hoje (`ingest/legislative.py`), só com outros anos.

**Folha individual.** [Amostra de 02/2023](https://www.camara.leg.br/deputados/73604/remuneracao-deputado-detalhado?mesAno=022023)
responde no mesmo formato de 2026, com remuneração fixa de R$ 39.293,32 (subsídio
da época, menor que os R$ 46.366,19 de 2026). Isso confirma a decisão de mostrar
valores da época sem correção. Volume: ~22,5 mil páginas para o mandato, mais as
folhas suplementares. É a parte mais cara de coletar; precisa de retomada e baixa
concorrência, como o coletor atual.

**Gabinete.** O perfil anual (`/deputados/{id}?ano={ano}`) é lido pelo
`parse_office` atual sem mudança. Amostra de 73604: 2023 com jan–dez (janeiro é
da legislatura anterior e fica fora do recorte), 2024 com jan–nov, 2025 com jan–dez.
Outras duas pessoas também têm 2024 só até novembro; uma terceira tem apenas janeiro
(saída do exercício). Dezembro/2024 parece faltar na fonte, não no parser —
confirmado na coleta de 8/10: nenhum dos 513 deputados tem dezembro/2024.

**Moradia.** `chamber_housing.query_url(2023, 2, 1)` lê a página 1 de 37
(723 linhas) sem ajuste. A legislatura 57 aparece no filtro com início em
1/2/2023. As mesmas regras valem: complemento da cota fica à parte, sem endereço.

**Presença.** O mesmo perfil anual traz dias de presença, ausências justificadas
e não justificadas por ano (ex.: 115, 62 e 119 dias em 2023–2025 para 73604).
É agregado anual, não mensal; serve para a ficha, mas não por mês.

**Votações.** API `dadosabertos.camara.leg.br/api/v2/votacoes` responde com
`X-Total-Count` de 1.296 (fev–abr/2023), 2.213 (2024) e 1.524 (2025) no mesmo
trimestre. A maioria é de comissões; o critério neutro do Placar (item 4 do
roadmap) precisa vir antes de qualquer coleta.

**Exercício.** Suplentes e quem saiu ou voltou têm períodos próprios. A média
por pessoa precisa contar só os meses em exercício, como já ocorre em 2026.

## Senado

**Cota (CEAPS).** API de 2023 retorna 18.822 lançamentos com os 12 meses.
Mesmo coletor atual.

**Folha e gabinete.** O [CSV de 02/2023](https://www.senado.leg.br/transparencia/LAI/secrh/SF_ConsultaRemuneracaoServidoresParlamentares_202302.csv)
existe (índice lista arquivos desde 2022). Não tem nome nem ID de pessoa, mas a
coluna de lotação traz o texto "Gabinete do Senador {nome}" em 79 lotações
distintas, inclusive nas 112 linhas da categoria PARLAMENTAR (Normal e
Suplementar). Isso abre dois caminhos que o piloto de 2026 não testou:

- folha do senador: linha PARLAMENTAR da lotação do próprio gabinete;
- gabinete: soma em memória das linhas da mesma lotação, sem guardar nenhuma linha.

A ligação é pelo nome escrito na lotação, não por ID. Exige tabela de
correspondência conferida à mão com o roster, recusa de nomes ambíguos e a
regra atual de nunca gravar linhas de servidores. **Não usado até haver
decisão**; até lá, o Senado continua sem total novo.

**Moradia.** A API de auxílio-moradia e imóveis só traz a situação atual
(`S`/`N`), sem valor nem mês. Sem série para o mandato.

**Votações.** API de votações traz 141 votações de 2023, todas com votos.

**Presença.** Hoje vem das tabelas dos diários em PDF (`ingest/senate_attendance.py`),
com a agenda mensal como índice; a agenda de mar/2023 responde. Estender para o
mandato multiplica por ~9 o volume de PDFs de 2026. Custo alto para uma
porcentagem; o roadmap já põe "faltas do Senado" em "Depois".

## Decisões pendentes

1. Câmara: coletar folha individual do mandato inteiro (~22,5 mil páginas) ou
   começar por cota, gabinete, moradia e presença, que são baratos.
2. Câmara: tratar dez/2024 do gabinete como mês fora da média ou como mês com
   lacuna explícita.
3. Senado: autorizar um piloto da ligação por lotação ("Gabinete do Senador
   {nome}") com até 10 senadores, sem gravar linhas individuais.
4. Senado: presença do mandato fica em "Depois" ou entra agora.
