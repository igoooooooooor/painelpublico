# Auditoria de sinal da complementação do auxílio-moradia na CEAP

Este levantamento isola a categoria oficial `COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA`
no arquivo anual da CEAP. O auditor não altera o banco.

**Correção aplicada em 8/10/2026 (esquema v3).** Essas linhas passaram a ter
natureza própria (`kind = complemento_moradia`) em vez de `reembolso`, na
migração do banco e no importador. Assim, total, média, lista, categorias,
fornecedores e alertas da cota não são mais reduzidos por elas. O sinal
publicado é preservado; a ficha mostra o complemento à parte e a exportação de
notas continua com essas linhas. As tabelas abaixo descrevem a situação antes
da correção: o “total atual” passou a ser o “total após removê-las”. A
recomputação dos sinais retirou 8 alertas (5 de fornecedor e 3 de pico), que só
existiam porque as linhas negativas reduziam o total.
Os valores são centavos inteiros, com o sinal publicado preservado.

Reprodução sem rede:

```sh
python3 ingest/chamber_quota_audit.py
```

O comando lê `data/raw/legislative/camara-2026.csv.zip` e
`data/na-lupa.sqlite3` em modo somente leitura. O resumo fica em
`data/snapshots/chamber-quota-audit.json`; o manifesto local de entrada fica em
`data/raw/mandate-cost/quota-audit/manifest.json`. O snapshot não guarda linhas
originais, CPF, fornecedor ou dados de folha. Ele contém agregados e os IDs e
nomes públicos dos deputados afetados. A verificação de completude remonta a
expectativa com o leitor e a regra de deduplicação do importador, compara os
campos persistidos com o SQLite e registra contagem e hash por mês e por perfil.

## Resultado no arquivo da Câmara

O arquivo consultado tem SHA-256
`329c7f729fa2f131894e3aaab5ca58b13006f205724d2b7d042d9409225cc4d4` e foi
importado no SQLite em `2026-10-06T22:22:49+00:00`. O arquivo já contém registros
de competência até outubro, mas a categoria auditada aparece de janeiro a
agosto; 2026 ainda está em andamento.

| Recorte e população | Linhas da categoria | Deputados distintos | `vlrLiquido` negativo | Soma assinada de `vlrLiquido` |
| --- | ---: | ---: | ---: | ---: |
| Arquivo CEAP 2026 inteiro, conforme baixado | 491 | 77 | 491 | −R$ 1.175.477,34 |
| Janeiro–julho, arquivo inteiro | 438 | 77 | 438 | −R$ 1.046.995,11 |
| Deputados da lista atual, arquivo inteiro | 457 | 65 | 457 | −R$ 1.084.447,24 |
| Deputados da lista atual, janeiro–julho | 405 | 65 | 405 | −R$ 960.112,01 |

No arquivo inteiro, as contagens de `vlrLiquido` positivo, zero ou vazio são
todas **0**. Em todas as 491 linhas, `vlrDocumento` é positivo, `vlrGlosa` está
em branco, `vlrRestituicao` é zero e `vlrLiquido` é igual ao negativo de
`vlrDocumento`. Os 34 lançamentos restantes estão vinculados a 12 IDs que não
fazem parte da lista atual; por isso a contagem atual é menor que a do arquivo.
“Arquivo inteiro” significa todo o conteúdo publicado nesse ZIP, não doze
competências já encerradas.

## Efeito nos totais atuais

O banco tem 513 deputados na lista atual, dos quais 509 têm algum reembolso
observado. O total da lista soma os valores `amountCents` assinados desses
registros. Excluir as linhas negativas da categoria aumenta o total porque
retira valores negativos da soma:

| Recorte | Total atual, com as linhas | Total após removê-las | Aumento ao remover |
| --- | ---: | ---: | ---: |
| Todo o arquivo importado em 2026 | R$ 129.383.446,64 | R$ 130.467.893,88 | R$ 1.084.447,24 |
| Janeiro–julho de 2026 | R$ 117.442.717,40 | R$ 118.402.829,41 | R$ 960.112,01 |

O total atual é o valor exato usado pela API e pela média/lista; o cartão de
resumo arredonda a chamada principal para milhares. Remover apenas as linhas da
categoria equivale a subtrair a soma assinada delas, sem mudar o sinal em disco.

| Perfil da lista atual | Todo o arquivo: atual → sem linhas | Janeiro–julho: atual → sem linhas | Linhas auditadas no arquivo inteiro |
| --- | ---: | ---: | ---: |
| Rui Falcão (`camara:73604`) | R$ 238.821,18 → R$ 254.797,18 | R$ 216.248,41 → R$ 229.477,41 | 8 |
| Adriana Ventura (`camara:204528`) | R$ 38.263,62 → R$ 38.263,62 | R$ 38.263,62 → R$ 38.263,62 | 0 |
| Gilmar Machado (`camara:74581`) | Sem total observado → sem total observado | Sem total observado → sem total observado | 0 |

“Sem total observado” não é R$ 0. O snapshot detalha a diferença para todos os
65 perfis atuais com linhas da categoria.

## Conferência do snapshot no SQLite

Antes de comparar a composição com o SQLite, o auditor reconstrói os IDs de
lançamento pelo importador, inclusive os identificadores derivados usados para
duplicatas. Filtrado para os deputados da lista atual, o arquivo tem **108.757**
lançamentos e o banco tem os mesmos **108.757**: **0 ausentes, 0 inesperados e
0 com campos persistidos divergentes**. As contagens e somas assinadas também
coincidem mês a mês:

| Competência | Linhas no arquivo e no banco |
| --- | ---: |
| Jan/2026 | 9.203 |
| Fev/2026 | 12.049 |
| Mar/2026 | 15.494 |
| Abr/2026 | 14.908 |
| Mai/2026 | 16.058 |
| Jun/2026 | 14.292 |
| Jul/2026 | 13.678 |
| Ago/2026 | 9.040 |
| Set/2026 | 3.966 |
| Out/2026 | 69 |
| Nov e dez/2026 | 0 no arquivo consultado |

Essa igualdade certifica somente que o SQLite reflete o ZIP e a lista atual na
data indicada. Não prevê atualizações posteriores da Câmara nem prova que o ano
esteja fechado. Os oito lançamentos negativos fora da categoria permanecem
intactos; o auditor não os classifica nem remove.

## O que a Câmara documenta sobre o sinal

A [documentação oficial dos campos da CEAP](https://dadosabertos.camara.leg.br/howtouse/2023-12-26-dados-ceap.html)
define `vlrDocumento` como valor de face, `vlrGlosa` como valor não coberto pela
CEAP e `vlrLiquido` como o valor efetivamente debitado da cota, correspondente
a `vlrDocumento` menos `vlrGlosa`. Ela menciona que alguns tipos de despesa
podem ter documento negativo, dando bilhete de compensação de passagem aérea
não usada como exemplo. Não especifica o que significa um `vlrLiquido` negativo
para a categoria de auxílio-moradia.

A [página oficial das regras da CEAP](https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/arquivo/acervo-por-tipo/sites-tematicos/57a-legislatura/no-exercicio-do-mandato/cota-para-o-exercicio-da-atividade-parlamentar-ceap)
lista a complementação do auxílio-moradia entre as despesas admitidas e diz que
a cota é usada por reembolso. O testemunho local de janeiro
(`data/raw/mandate-cost/reconciliation/camara-73604-2026-01.json`) registra
`vlrDocumento=1747`, `vlrGlosa=""`, `vlrLiquido=-1747` e
`vlrRestituicao=0.0`. Logo, os valores publicados nessa categoria não seguem a
fórmula documentada se o campo de glosa em branco corresponder a zero. As
fontes consultadas não resolvem essa divergência nem autorizam inverter o sinal
automaticamente.

## Onde o sinal entra hoje

`ingest/legislative.py::load_chamber_expenses` importa `vlrLiquido` em `amount`
preservando o sinal. `backend/public_store.py::import_snapshot` grava centavos
e monta `authority_totals` com `SUM(amountCents)`. `backend/citizen.py::summary`
usa essas somas para a home, média e lista; `backend/citizen.py::politician`
soma `amountCents` por mês e categoria na ficha. Na interface,
`frontend/scripts/citizen-view.js::profileExpenseAnswer` mostra o total e
`profileExpenseDetails` mostra meses e categorias. `frontend/scripts/home-view.js`
usa `quota.total` nos cartões e informa que os estornos são preservados. A
exportação de notas também lê o valor assinado do banco. Esses caminhos não
foram alterados nesta auditoria.

## Composição provisória para revisão

Uma composição que retire a categoria da cota-base deve calcular o valor
contrafactual como `total atual − soma assinada das linhas removidas`. Com estes
dados isso eleva os totais. O “complemento de moradia pago pela cota” pode ser
exibido uma vez como componente separado, com a fonte própria de moradia e sem
alterar o registro CEAP assinado. A semântica contábil da linha negativa ainda
precisa de confirmação oficial antes de somar esse componente ao total geral ou
de apresentar a composição como custo efetivo corrigido.
