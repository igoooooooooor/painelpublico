# Quanto custa um mandato — verificações antes da ficha

Recorte aprovado: janeiro–julho de 2026, Câmara. A fotografia das fontes é local;
não é uma afirmação sobre valores finais após futuras revisões dos órgãos.
A composição nova não altera os lançamentos importados. A correção da cota
exibida para o complemento de moradia foi aplicada depois, em 8/10/2026.

## A. Complemento na cota

No arquivo CEAP 2026, a categoria exata `COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA`
tem **491 linhas, todas negativas em `vlrLiquido`, para 77 deputados**, com soma
**−R$ 1.175.477,34**. Janeiro–julho contém 438 dessas linhas, também para 77
deputados, somando **−R$ 1.046.995,11**. O universo anual inclui pessoas que
não estão no roster atual; não se confunde esse universo com as 513 fichas.

| Recorte das fichas atuais | Cota com as linhas | Sem as linhas | Aumento ao excluir |
| --- | ---: | ---: | ---: |
| CEAP 2026 observado | R$ 129.383.446,64 | R$ 130.467.893,88 | R$ 1.084.447,24 |
| Janeiro–julho de 2026 | R$ 117.442.717,40 | R$ 118.402.829,41 | R$ 960.112,01 |
| Rui Falcão, 2026 observado | R$ 238.821,18 | R$ 254.797,18 | R$ 15.976,00 |
| Rui Falcão, janeiro–julho | R$ 216.248,41 | R$ 229.477,41 | R$ 13.229,00 |

O roster atual tem 457 linhas dessa categoria, para 65 deputados; janeiro–julho tem 405 linhas para os mesmos 65. A comparação integral validou 108.757 lançamentos normalizados do arquivo oficial contra 108.757 linhas do SQLite, sem ausências, extras ou divergências de campos. Adriana Ventura não tem essas
linhas: sua cota anual observada continua R$ 38.263,62. Gilmar Machado não tem
cota observada nesta base; ausência continua nula.

A [documentação oficial dos campos CEAP](https://dadosabertos.camara.leg.br/howtouse/2023-12-26-dados-ceap.html)
define `vlrLiquido` como despesa debitada da cota, calculada por documento menos
glosa. Explica valores negativos em documentos de compensação de passagens,
mas não explica especificamente o sinal negativo deste complemento. Nas 491
linhas de moradia, o documento é positivo, a glosa está vazia e o líquido é o
oposto do documento. Não se presumiu que glosa vazia seja zero nem se inventou
uma justificativa contábil para essa combinação.

**Correção aplicada em 8/10/2026** (ver [auditoria da cota](mandate-quota-audit.md)):
a categoria tem natureza própria e não reduz mais a cota exibida; a ficha passa a
mostrar um único total de cota, coerente com o custo do mandato. Texto original da
proposta: retirar somente
essa categoria da soma apresentada e exibir seus lançamentos uma vez à parte,
com o sinal original e indicação de que o tratamento é provisório. Isso exige
revisar também a coerência de médias, alertas, totais de categorias e exportação.
O efeito aritmético está comprovado; chamar os totais atuais de erro contábil
exige esclarecer o significado na fonte. A composição nova segue a exclusão
provisória autorizada e não transforma o negativo em pagamento positivo.

## B. Exercício efetivo

A fonte é o serviço oficial `ObterDetalhesDeputado`, com `numLegislatura=57`,
que publica `periodosExercicio` com início e fim. Os caches guardam somente a
identidade pública, intervalos e proveniência. O histórico JSON é uma conferência
independente para o exemplo, não um substituto da data efetiva por data eleitoral.

Para Gilmar Machado, o início de exercício é **15/09/2026**, com fim aberto.
O [histórico oficial](https://dadosabertos.camara.leg.br/api/v2/deputados/74581/historico?formato=json)
registra entrada em exercício e posse como titular nessa data. Janeiro–julho
fica **fora do mandato**, não “não informado” e não salário zero. Setembro tem
16 dias de exercício, contando o dia da posse.

A coleta validou **513/513 históricos**, com zero meses desconhecidos. Dois históricos continham intervalos duplicados/sobrepostos; a união dos intervalos evita contar dias duas vezes. As [definições oficiais](https://www2.camara.leg.br/transparencia/dados-abertos/dados-abertos-legislativo/webservices/deputados/periodoExercicio) distinguem posse e fim do exercício.

| Mês de 2026 | Em exercício em algum dia | Fora do mandato no mês | Desconhecido |
| --- | ---: | ---: | ---: |
| Janeiro | 472 | 41 | 0 |
| Fevereiro | 478 | 35 | 0 |
| Março | 486 | 27 | 0 |
| Abril | 498 | 15 | 0 |
| Maio | 498 | 15 | 0 |
| Junho | 504 | 9 | 0 |
| Julho | 507 | 6 | 0 |

Um mês entra no recorte de exercício quando existe interseção com um intervalo
oficial. Meses de exercício parcial mantêm o número de dias; não se extrapola
um mês parcial para trinta dias. História inválida ou ausente fica desconhecida,
sem inferir que a pessoa estava fora do mandato.

## C. Moradia como conferência

Somente o componente `Auxílios` da folha individual entra na soma. A consulta
de moradia fornece dias de imóvel funcional e conferência; seu valor monetário
nunca entra na soma. Divergências são registradas sem bloquear a ficha nem o mês.
A divergência de Rui Falcão em setembro permanece no relatório da Fase 2,
fora do período de janeiro–julho aprovado para o novo valor principal.

Os testes alteram o valor de moradia para um número muito maior e também removem
a observação: nenhuma das duas ações muda a soma nem impede um mês válido.

## Regra do número principal (revisada em 8/10/2026)

**Mudança de regra, por decisão do dono do projeto.** A primeira versão só aceitava
meses cuja folha estivesse “certificada” contra o inventário anônimo de folhas
suplementares. Em janeiro–julho isso deixou apenas junho, mês do adiantamento de
13º, e o número principal ficava distorcido (Rui Falcão aparecia com “pelo menos
R$ 246.331,99/mês”). A regra passou a ser:

- A página individual oficial da Câmara (`remuneracao-deputado-detalhado`) é o
  registro individual da pessoa, com todas as tabelas que ela publica (normal,
  complementares e 13º). Um mês de folha vale quando essa página foi lida por
  completo (`detailStatus = complete`).
- Número principal = média mensal dos meses de janeiro–julho em que a pessoa
  estava em exercício **e** havia as quatro partes no mesmo mês: remuneração bruta
  das tabelas, auxílios da folha, cota sem o complemento e gabinete.
- O 13º salário (`christmas_bonus`) fica fora da média e aparece à parte, por
  exemplo “13º adiantado em junho: R$ X”.
- O inventário anônimo de folhas suplementares vira nota de rodapé: ele não liga
  folhas a deputados e não bloqueia o número principal.
- Rótulo: “custa em média R$ X por mês”, com os meses usados ao lado
  (“jan–jul/2026, 7 meses”). Não é mais apresentado como valor mínimo.
- Sem nenhum mês com as quatro partes: sem número principal; a ficha mostra as
  partes, cada uma com seus meses, e o motivo.

Continuam valendo: a cota precisa corresponder ao arquivo oficial completo da
fotografia (estornos de outras categorias preservados com sinal) e o gabinete
precisa de seção importada completa. Parte ausente não vira zero: um mês sem
nenhuma nota de cota fica fora da média. Mês de exercício parcial entra com os
valores publicados, sem extrapolar para o mês inteiro. Ajustes negativos
publicados (por exemplo, em “outras remunerações eventuais”) entram com o sinal.
Diárias e vantagens indenizatórias seguem fora das quatro partes e não bloqueiam
mais o mês, pois o número deixou de ser um mínimo. Médias e partes são
arredondadas para baixo ao centavo; por isso a soma das partes exibidas pode
diferir do principal em centavos.

Imóvel funcional permanece em dias, sem aluguel estimado. Encargos do gabinete
não publicados ficam expressamente fora da soma. A referência salarial do cargo
não se soma à remuneração individual paga. Não há média geral, ranking,
ordenação por esse valor ou comparação com o Senado.

## Auditoria de dados de servidores

A [auditoria de privacidade](mandate-privacy-audit.md) registra o comando exato e o alcance da busca. Não foram encontrados registros compatíveis com o CSV de servidores nos caches, snapshots, caches compilados, logs temporários da coleta ou histórico do shell examinados. Entretanto, uma linha do incidente anterior permaneceu no log da sessão do Codex, em quatro cópias serializadas. Não é possível afirmar ausência em todos os logs. Nenhum conteúdo desse registro é reproduzido nos relatórios, e nenhum histórico de sessão foi apagado.

## Resultado aplicado à nova composição

Com a regra revisada, a fotografia tem número principal em **508 de 513 fichas**:
452 usam os sete meses, 56 usam de um a seis meses. Os 3.395 meses usados
incluem 30 meses de exercício parcial (28 pessoas), somados sem extrapolação.
Em 2.901 desses meses o inventário anônimo lista folhas suplementares sem
identificação; isso aparece só como nota. 500 fichas têm 13º adiantado em junho,
mostrado à parte.

| Ficha | Média mensal | Meses usados | 13º à parte |
| --- | ---: | --- | ---: |
| Rui Falcão | R$ 226.330,99 | jan–jul/2026, 7 meses | R$ 22.709,97 (junho) |
| Adriana Ventura | R$ 172.256,02 | jan–jul/2026, 7 meses | R$ 23.183,09 (junho) |
| Gilmar Machado | — | nenhum | Fora do mandato em janeiro–julho |
| Esperidião Amin (Senado) | — | nenhum | Somente cota e referência salarial, sem nova composição |

Partes de Rui Falcão (média dos 7 meses): salário bruto R$ 46.122,67, auxílios
R$ 4.253,00, cota sem complemento R$ 32.782,48 e gabinete R$ 143.172,83. Adriana
Ventura tem auxílios publicados em zero; o zero da fonte é preservado.

Sem número principal (5): Gilmar Machado e Priscila Costa (fora do mandato em
todo o período); Nivaldo Albuquerque (só julho em exercício, sem nota de cota no
mês); Santin Roveda (junho e julho em exercício, gabinete incompleto); Amom Mandel
(em exercício nos sete meses, sem nenhuma nota de cota no período — ausência não
é tratada como zero). Nos meses em exercício das 513 fichas, as exclusões são:
46 meses com parte ausente (42 por cota sem nota, 3 por folha, 1 por gabinete),
3 com página de remuneração não lida e 2 com gabinete incompleto.
