# Placar mais amplo — metodologia e piloto

Implementação local em 9/10/2026, na branch `codex/broader-voting-scoreboard`.
Este documento registra a metodologia, a conferência de fontes e o catálogo
paginado de 2026. Integração à `main` e publicação no servidor são etapas separadas.

## Pergunta do cidadão e recorte

“O que meu deputado votou, o que estava sendo decidido e o que significa o voto?”

A proposta de v1 é cobrir **votações nominais abertas do Plenário da Câmara sobre
o texto principal de PL, PLP e PEC**, desde 1º/2/2023. A primeira conferência usa
2026. Entram aprovações e não aprovações, com a mesma regra, sem seleção por
partido, autor, tema, placar apertado ou repercussão.

Substitutivos e subemendas substitutivas podem ser a versão integral decidida.
Os dois turnos de uma PEC são decisões distintas, com IDs e textos próprios.
Urgência, retirada de pauta, admissibilidade e outros procedimentos ficam
separados; emendas e destaques também. Redação final é outra etapa, não um
sinônimo de aprovação do mérito. MPV, PLV, PDL e PRC ficam fora deste primeiro
recorte; essa limitação deve aparecer na página de cobertura.

## O que a fonte permite afirmar

A [documentação da Câmara](https://dadosabertos.camara.leg.br/howtouse/2020-02-07-dados-votacoes.html)
adverte que a proposição afetada pode ser diferente do objeto efetivamente
votado. `objetosPossiveis` não é uma lista de objetos todos votados; nem a última
apresentação de proposição comprova qual versão foi decidida.

Cada candidato precisa de conferência do registro do resultado, do texto
efetivamente submetido e do relatório nominal. Uma ementa do projeto original
não comprova o conteúdo do substitutivo. Casos sem identificação segura ficam
pendentes, com motivo, sem um resumo que atribua efeitos ao voto.

A [lista oficial](https://dadosabertos.camara.leg.br/api/v2/orgaos/180/votacoes)
é consultada por **data de ocorrência**. A data de registro permanece separada.
O campo `aprovacao=0` significa não aprovação; para dizer “rejeitado” é preciso
conferir o resultado, pois também pode haver quórum insuficiente. Campo ausente
não significa rejeição, voto “não”, abstenção ou zero.

O método só fica identificado automaticamente quando o texto o declara de forma
explícita. Placar e linhas individuais, isoladamente, não comprovam o método
nominal: a fonte também tem manifestações individuais em decisões simbólicas.
Um relatório nominal oficial pode resolver essa pendência na revisão humana.

## Levantamento reproduzível

```sh
make collect-vote-inventory YEAR=2026 THROUGH=2026-10-09
# Reconstrução sem rede, com os mesmos limites e caches:
python3 -m ingest.chamber_vote_inventory --year 2026 --through 2026-10-09
```

`ingest/chamber_vote_inventory.py` segue todas as páginas do órgão Plenário
(180), valida datas e IDs e recusa saltos, ciclos e links fora do endpoint
oficial. Duplicatas idênticas são contadas uma vez; conflitos interrompem a lista.
Falha na lista preserva o relatório anterior, sem declarar uma lista parcial
como completa.

Respostas originais, URL, data de consulta e checksum ficam em
`data/raw/chamber-vote-inventory/<início>_<fim>/`. O relatório JSON e a tabela
Markdown ficam em `data/reviews/chamber-vote-inventory-<fim>.*`, fora do Git.
Nada é importado para o SQLite ou para os snapshots que o site usa.

A regra `chamber-vote-inventory-v1` faz uma triagem conservadora da descrição:
texto principal, emenda/destaque, procedimento, redação final ou desconhecido.
**Candidato é provisório, não elegível para publicação.** Proposições afetadas
servem para conferir o recorte; um resultado vago continua desconhecido.

A amostra tem até 40 detalhes e 10 consultas de votos individuais. Prioriza
candidatos com placar explícito, dos mais recentes aos mais antigos; depois,
os demais candidatos. Esses limites escolhem a conferência, não o catálogo
final. `--detail-limit` e `--participant-limit` permitem ampliar a amostra.
Contagens não publicadas continuam ausentes, inclusive abstenções.

Nos votos individuais, todas as páginas são lidas. IDs duplicados com escolhas
conflitantes são recusados; Sim, Não e Abstenção são comparados separadamente
com o placar observado. Presidência (“Artigo 17”) e obstrução permanecem
distintas; quantidade de linhas não é automaticamente o total de votos.

## Resultado do piloto de 9/10/2026

Consulta de 1º/1 a 9/10/2026: **1.339 registros, em 14 páginas**, com datas de
ocorrência observadas entre 2/2 e 3/9. “Lista completa” significa que toda a
paginação retornada pela API foi lida; não garante que a fonte tenha registrado
todas as decisões que efetivamente ocorreram.

| Triagem provisória | Registros |
| --- | ---: |
| Texto principal, incluindo tipos fora da v1 | 207 |
| Emenda ou destaque | 78 |
| Procedimento | 705 |
| Redação final | 192 |
| Descrição ainda sem classificação segura | 157 |
| Total | 1.339 |

Há **162 candidatos provisórios ao recorte PL/PLP/PEC**, 19 com placar explícito
na descrição. Isso não equivale a 162 votações nominais elegíveis. Foram
conferidos 40 detalhes e 10 conjuntos de votos individuais, sem falhas de fonte;
os valores publicados de Sim, Não e, quando informado, Abstenção bateram nos
10 casos. Naquela triagem, os candidatos ainda precisavam de confirmação de
método antes de publicação, pois o texto da API não a resolveu automaticamente.

Um caso ilustra por que a conferência precisa preservar cada estado: no PLP 74,
o resultado tem 395 votos, mas a lista individual tem 396 pessoas, incluindo
uma presidência (“Artigo 17”). Essa linha adicional não é um voto extra.

Casos reais incorporados às regras e testes: “Rejeitadas as Emendas ao
Substitutivo” é decisão sobre emendas; mudança do regime por um requerimento
apensado é procedimento; “ressalvado o destaque” é uma ressalva do texto
principal, não um placar do destaque. Texto mantido sem identificação do trecho
fica desconhecido. As palavras do registro precisam identificar a decisão,
não apenas mencionar o projeto a que ela se relaciona.

## Exemplos da conferência

Estes três exemplos partem de itens já presentes no Placar, para conferir a
continuidade das fontes. Não definem o critério de escolha do catálogo novo.
Os relatórios oficiais identificam votação nominal eletrônica nos três casos.
O resultado abaixo é o daquela decisão na Câmara; não afirma a situação legal
atual da proposição.

### PLP 74/2026 · 3/9/2026

**Título:** Regras para benefícios tributários e despesas de 2026.

**O que foi decidido:** a Câmara aprovou uma subemenda substitutiva adotada pelo
relator da Comissão de Finanças e Tributação. A versão decidida substituiu os
textos anteriores; este placar não é uma votação do projeto original.

**Sim:** aprovar essa subemenda substitutiva. **Não:** rejeitar essa versão.
**Resultado:** 346 Sim, 46 Não e 3 abstenções; aprovado.

[Relatório nominal](https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13931&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=160&numSessaoLegislativa=4&tipo=uf),
[registro da sessão](https://www.camara.leg.br/internet/ordemdodia/integras/3177907.htm)
e [detalhe da API](https://dadosabertos.camara.leg.br/api/v2/votacoes/2611313-31).
Explicações de efeitos específicos exigem conferir o texto desta versão.

### PLP 114/2026 · 12/8/2026

**Título:** Substitutivo ao projeto sobre tributos de combustíveis.

**O que foi decidido:** a Câmara aprovou o substitutivo reformulado da relatora,
ressalvado um destaque. Esse placar diz respeito ao substitutivo; emendas e o
destaque têm decisões próprias.

**Sim:** aprovar esse substitutivo. **Não:** rejeitar essa versão.
**Resultado:** 318 Sim, 113 Não e 1 abstenção; aprovado.

[Relatório nominal](https://www.camara.leg.br/Internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13872&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=151&numSessaoLegislativa=4&tipo=partido),
[registro da sessão](https://www.camara.leg.br/internet/ordemdodia/integras/3171603.htm)
e [ficha e tramitação](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2618177).

### PLP 41/2026 · 7/7/2026

**Título:** Substitutivo ao projeto de enfrentamento da violência contra mulheres.

**O que foi decidido:** a Câmara aprovou o substitutivo da relatora da Comissão
de Defesa dos Direitos da Mulher. A ementa descreve um sistema nacional de
enfrentamento da violência contra meninas e mulheres e destinação de recursos.

**Sim:** aprovar esse substitutivo. **Não:** rejeitar essa versão.
**Resultado:** 470 Sim e 1 Não; aprovado. Abstenções não são completadas a partir
da ausência de informação no resumo.

[Relatório nominal](https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13830&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=136&numSessaoLegislativa=4&tipo=uf)
e [ficha e tramitação](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2606313).
O rascunho não repete a regra de 10% ligada ao Propag do cartão antigo: esse
efeito precisa ser conferido no substitutivo antes de reaproveitar o resumo.

## Catálogo local de 2026

Os 19 candidatos com placar explícito passaram por conferência do relatório
nominal, da data, do resultado e da versão identificada na decisão oficial.
Os votos individuais são conciliados com Sim, Não, Abstenção quando publicada
e Total. Presidência e obstrução ficam separadas; pessoas sem linha na fonte
não recebem um voto inventado.

A revisão fica em `data/reviews/chamber-vote-reviews-2026-10-09.json`, fora do
Git, com ID, status, data da revisão, título, resumo, significados de Sim/Não,
links oficiais e evidências do método e da versão. Status `pending` exige um
motivo e não publica o item. Confirmar o objeto pelo relatório e pela sessão
não autoriza atribuir efeitos específicos de uma ementa anterior. Quando não
há link seguro para o texto daquela versão, `sources.text` fica ausente como
valor (`null`); a página mantém o relatório e o registro da decisão.

```sh
make collect-votes THROUGH=2026-10-09
# Reconstrução offline com as revisões e caches locais:
python3 -m ingest.chamber_votes --through 2026-10-09
```

`--reviews <arquivo>` aceita outro arquivo local de revisão. O coletor valida
links oficiais, confirma o marcador nominal no relatório, segue todas as
páginas dos votos individuais e preserva os múltiplos
[temas oficiais da proposição de referência](https://dadosabertos.camara.leg.br/swagger/api.html#proposicoes).
Uma proposição sem temas continua sem temas. Falhas na coleta ou conciliação
interrompem a geração e preservam o catálogo anterior. Os originais ficam no
cache do inventário com URL, data de consulta e checksum.

O índice `data/snapshots/chamber-votes.json` contém somente resumos e cobertura;
cada lista nominal fica em `data/snapshots/chamber-vote-details/<geração>/<id>.json`.
Uma geração é identificada pelo checksum do conjunto de detalhes. Ela é preparada
integralmente antes de trocar o índice de forma atômica; falhas não misturam
resumos antigos com detalhes novos. Gerações anteriores são preservadas.
`GET /api/c/votes` oferece busca, tipo, tema e paginação (12 itens por página,
limite de 24). `GET /api/c/votes/<id>` carrega a decisão e seus votos individuais.
Nenhuma dessas rotas depende do SQLite. Falha ou ausência do detalhe não elimina
o resumo: a API indica que a lista individual está indisponível.

O Placar usa esse catálogo ao entrar na tela, com filtros, cobertura, fontes,
significados de Sim/Não e endereço `/placar/<id>`. A home, as fichas, os partidos
e as comparações mantêm as quatro seleções originais e seus contratos em `DATA`.
Num clone sem snapshots, o Placar informa a indisponibilidade e mostra essas
seleções. Uma busca sem resultados num catálogo disponível mostra lista vazia.

Esta entrega cobre **19 decisões conferidas**, não todo o ano nem todo o mandato.
São **7.859 registros individuais**, incluindo presidência e obstrução quando
presentes; não é um total de votos de mérito. Quatro decisões não têm link seguro
para o texto exato, nove não publicam a contagem de abstenções na descrição da
API e uma não tem tema oficial. Essas lacunas permanecem explícitas, sem zeros
ou links inferidos.
Os outros **143 candidatos provisórios** aguardam revisão; podem incluir decisões
simbólicas e itens que serão excluídos após conferir o método e o objeto.
O fato de as 19 decisões deste lote terem sido aprovadas é uma observação das
fontes, não um critério de inclusão. A regra também admite não aprovações.

## Próxima etapa

Conferir os candidatos sem placar explícito em 2026, resolver pendências de texto
e aplicar a mesma metodologia desde fevereiro de 2023. Só depois dessa coleta
e conciliação será possível declarar cobertura do mandato inteiro.
