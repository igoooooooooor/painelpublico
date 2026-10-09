# Próximas etapas

Atualizado em 9 de outubro de 2026. Itens pendentes são planejamento; não descrevem cobertura já disponível. A cobertura e suas datas estão em [Dados e SQLite](data.md).

## Rumo

O Painel Público é para o cidadão comum: abrir, entender em poucos segundos e saber quem o representa, quanto custa e como trabalha. A referência é o [TheyWorkForYou](https://www.theyworkforyou.com/), do Reino Unido: uma porta de entrada simples, votos explicados em linguagem clara e um jeito fácil de falar com o representante.

Antes de entrar no roadmap, cada item passa por duas perguntas:

1. Responde a uma pergunta que um cidadão comum faria sobre alguém que ele elegeu ou pode deixar de eleger?
2. Vale o custo de manter? As coletas são manuais, então cada fonte nova é trabalho permanente.

## Entregue

- Projeto organizado com Git, SQLite e design system, preservando a home e as telas.
- Consulta dos 513 deputados e dos 82 registros do Senado, com cobertura explícita e distinção entre ausência e zero.
- Fichas em "3 respostas" (cota, presença/Placar e maior alerta), com detalhes recolhidos, atividade e autoria do Senado e situação atual dos projetos (Etapas 1 a 3, integradas à `main`).
- Foco no cidadão (7/10/2026): saíram a busca avançada e os dados de servidores (SIAPE) e do Judiciário (DadosJusBr). O banco caiu de 1,27 GB para 84 MB sem mudar nenhuma resposta das telas, e cada ficha passou a oferecer o download de todas as notas da cota em CSV.

## Agora, nesta ordem

1. **Eleições de 2026 e troca de mandatos, antes de fevereiro de 2027.** O primeiro turno foi em 4/10 e o segundo é em 25/10. A nova legislatura começa em 1º/2/2027, com toda a Câmara e dois terços do Senado eleitos agora.
   - **Feito (7/10):** a lista oficial agora fica separada do cadastro (tabela `roster`). Quem sai deixa de aparecer como em exercício e fica marcado como fora da lista atual, sem perder notas nem alertas; uma coleta indisponível mantém a lista anterior.
   - **Feito (7/10):** cada ficha mostra o resultado de 2026 no TSE (eleito, reeleito, suplente, não eleito, 2º turno) quando há uma única candidatura correspondente; 551 dos 595 registros foram ligados. **Falta:** nova coleta depois do 2º turno (25/10) e, com a lista da nova legislatura, a troca em 1º/2/2027.
   - O bloco eleitoral só volta à home com cobertura ampla.
2. **Minha cidade, versão 1.** A pessoa digita a cidade e vê quem a representa e quanto custa. A base é nacional e usa as mesmas regras para as 5.571 localidades atuais do IBGE:
   - **Fase 1 aprovada (7/10), implementada localmente:** busca por cidade, população de 2026, tabela oficial TSE–IBGE, eleitos ordinários de 2024 e 2026, votos municipais de deputados federais eleitos e links conservadores às fichas. São 5.571 localidades com população e votos, 69.213 eleitos municipais, 1.666 estaduais/federais e 288 ligações de eleitos federais ao roster. Lacunas (inclusive Iporá/GO) e recortes estão em [Dados e SQLite](data.md). Sem merge ou publicação nesta etapa.
   - **Fase 2 aprovada (7/10), implementada localmente:** emendas do Portal da Transparência por município, autoria e ano da proposta, com empenhado, pago e restos a pagar separados; transferências especiais identificadas como subconjunto. Cobertura e limites em [Dados e SQLite](data.md). Sem merge ou publicação.
   - **Fase 3 implementada localmente, aguardando aprovação (7/10):** contas anuais de 2025 com cobertura dos 5.569 municípios aplicáveis: 5.494 completos, 6 parciais e 69 com não entrega confirmada. Medianas nacionais por faixa populacional liberadas; importação FINBRA auditável e divergências explícitas. Sem merge ou publicação. Bens e financiamento de campanha continuam fora deste recorte.
   - **TSE:** prefeito(a), vice e vereadores eleitos em 2024; governador(a) e deputados(as) estaduais eleitos em 2026; bens declarados e financiamento de campanha; deputados(as) federais mais votados(as) na cidade.
   - **Emendas parlamentares (Portal da Transparência):** quanto cada deputado(a) e senador(a) destinou para a cidade.
   - **SICONFI (Tesouro Nacional):** quanto a prefeitura e o estado arrecadam e gastam com saúde, educação e pessoal, comparados com cidades do mesmo porte.

   Onde houver dado aberto, entram extras (portais estaduais e Tribunais de Contas que publicam as contas de todos os municípios do estado), começando pelos lugares mais populosos e pelas fontes com arquivo para baixar ou API; raspar site vem por último. Onde não houver, a página diz que o órgão não publica aquilo em formato aberto. Comparações entre cidades e estados usam só a base nacional, para que publicar mais não faça um lugar parecer pior.
3. **Quanto custa um mandato.** Um total por parlamentar com divisão simples: subsídio, cota, gabinete e auxílios, cada parte com fonte e período. Gabinete do Senado e folha individual dependem de fonte validada por pessoa e competência; referência salarial não comprova pagamento.
   - **Fase 1 aprovada (7/10):** [levantamento oficial](mandate-cost-sources.md), com disponibilidade, limitações, cobertura local e proposta de v1. Sem coleta em massa ou alteração do produto. Gabinete da Câmara tem meses até julho; moradia e folha exigem cuidado com períodos e dupla contagem. A Fase 2 foi autorizada com foco na Câmara e piloto de até 10 senadores.
   - **Fase 2 aprovada:** [coleta e conferência](mandate-cost-collection.md), com folha e moradia por competência, retomada, inventário das suplementares e piloto do Senado interrompido por falta de identidade individual segura. Cota e gabinete reaproveitados; sem alteração da ficha ou do banco. Janeiro–julho é a proposta de período comum, com lacunas e sobreposição explícitas. Fase 3 autorizada para janeiro–julho/2026, somente Câmara.
   - **Fase 3 local:** custo médio mensal na ficha da Câmara, com meses explícitos, partes e fontes, exercício confirmado, auxílio vindo só da folha e 13º à parte. [Verificações A–C e resultado](mandate-cost-preflight.md). Regra revisada em 8/10: a página individual de remuneração é o registro da pessoa; o inventário anônimo é só nota. Média disponível em 508/513 fichas; Senado sem total novo. Sem ranking ou nova ordenação. Complemento de moradia da cota corrigido em 8/10 (esquema v3): fica à parte e não reduz mais a cota.
   - **Próximo: período do mandato, não do calendário (decidido em 8/10).** Hoje a média usa só jan–jul/2026, que é ano eleitoral e pode distorcer cota e presença. A régua passa a ser o mandato atual: Câmara desde fev/2023 (legislatura 57); Senado no mesmo recorte, para manter as mesmas regras, com aviso quando o mandato começou antes. Em 1º/2/2027 a média recomeça e o mandato 2023–2027 fica como histórico na ficha. Carreira inteira (2008 em diante) fica fora: custo alto, pouco ganho para o leigo.
     - **Levantamento feito (8/10):** [até onde vai cada fonte](mandate-period-sources.md). Câmara cobre o mandato nas quatro partes, salvo gabinete de dez/2024; Senado só tem série de cota e votações. Quatro decisões pendentes no fim do documento.
     - **Coleta das partes baratas da Câmara (8/10):** cota, moradia, gabinete e presença de 2023–2025 em arquivos próprios (`make collect-mandate-history`), sem alterar a ficha. Dez/2024 sem gabinete confirmado na fonte para todos. Cobertura em [Dados e SQLite](data.md).
     - **Média do mandato na ficha (8/10, local):** folha individual 2023–2025 coletada; a ficha da Câmara mostra fev/2023–jul/2026, 510/513 com média, dez/2024 com gabinete vazio. Sem publicação. **Falta:** decisões do Senado (piloto por lotação e presença).
     - **Prioridade (9/10): salário e gabinete do Senado.** Caminho levantado em [até onde vai cada fonte](mandate-period-sources.md): o CSV mensal de remuneração não tem ID de pessoa, mas a lotação "Gabinete do Senador {nome}" permite um piloto (folha do senador pela linha PARLAMENTAR do próprio gabinete; gabinete pela soma em memória da lotação, sem gravar linhas de servidores), com tabela de correspondência conferida à mão e recusa de nomes ambíguos. **Piloto feito (9/10, local):** 10 senadores, jan–set/2026, subsídio igual à referência em 90 de 90 meses e gabinete de R$ 170–569 mil/mês; [resultado](mandate-cost-collection.md). **Ampliado (9/10, local):** 102 senadores(as), fev/2023–set/2026, subsídio nos degraus oficiais em 3.336 senador-mês e gabinete em 3.561; lacunas com motivo. **Na ficha (9/10, local):** "Senado · despesas identificadas do mandato", à parte da Câmara, com remuneração, equipe do gabinete e cota, média só dos meses com as três partes, mês a mês com lacunas e motivos; comparação de custo total Câmara × Senado indisponível. [Regras](mandate-cost-collection.md). Até lá, as fichas do Senado seguem só com a cota.
     - **Cota e presença da Câmara no mandato em todo o app (8/10, local):** lista, ficha, comparação, home e partidos usam média mensal da cota (comparável com o Senado, que segue em 2026); presença soma o mandato. No banco, 2023–2025 entram só como agregados por pessoa. Alertas e CSV seguem em 2026. Detalhes em [Dados e SQLite](data.md).
     - **Cota do Senado desde fev/2023 (8/10, local):** mesmo recorte e mesma média mensal da Câmara; ficha avisa quando o mandato começou antes. **Falta:** alertas do mandato e o restante do Senado (presença, salário e gabinete).
     - **Alertas no mandato (feito e publicado, 8–9/10):** regra `cota-alertas-v3`, Câmara e Senado desde fev/2023, base de 12 meses completos (avaliação a partir de fev/2024), concentração por ano, alertas dos mais recentes aos mais antigos com filtro por ano. Simulação e sinais gravados batem; nova triagem pela base publicada em 9/10. Detalhes em [Alertas](alerts.md).
     - **Votações nominais e projetos do Senado no mandato (9/10):** coleta anual desde 1/2/2023, fontes e cobertura por ano nas fichas e comparações, projetos PL/PLP/PEC de autoria ou coautoria da lista atual. Ausências não viram zero; votos secretos ficam fora. Presença do Senado continua em 2026 e sua expansão permanece em Depois. Código integrado à `main`; snapshots coletados localmente, com envio ao servidor pendente. Resultados em [Dados e SQLite](data.md#atividade-e-autoria-do-senado--mandato-desde-fevereiro-de-2023).
     - **Notas e CSV desde fev/2023 (8/10, local):** decidido aceitar o peso no servidor: as notas de 2023–2025 das duas Casas ficam no banco em formato enxuto (+59 MB; banco de 142 MB), no lugar dos totais da v4. A lista de notas do mês e o CSV da ficha cobrem o mandato.
     - **Antes de coletar:** levantar fonte por fonte até onde cada uma vai de verdade (cota, folha individual, gabinete, auxílios, votações, presença). Só levantamento, sem coleta. Se uma das quatro partes do custo não cobrir o mandato inteiro, a média só usa os meses em que todas existem, com os meses escritos ao lado.
     - **Peso na VPS:** o servidor guarda as notas detalhadas do ano corrente e, desde 8/10, as notas antigas em formato enxuto (revisão desta regra, que antes previa só agregados). Os arquivos brutos completos continuam só na base local.
     - **Valores da época, sem correção pela inflação**, com essa frase na ficha. Correção pelo IPCA fica para depois, se fizer falta.
     - Minha cidade mantém "último ano fechado" como régua: contas municipais são anuais e chegam com atraso.
4. **Placar mais amplo.** Hoje a Câmara tem só quatro votações selecionadas. Ampliar com um critério neutro e público (por exemplo, todas as votações finais de PEC e PL), com resumo em linguagem simples a partir da ementa oficial e agrupamento por tema com metodologia publicada.
5. **Antes de divulgar o site:**
   - Atualização automática das cotas da Câmara e do Senado, com data da coleta, validação e registro das falhas. Hoje as coletas são manuais e o app não agenda downloads.
   - Backup externo com teste de restauração. O backup local consistente já existe.
   - Confirmar o deploy pelo GitHub Actions no servidor, cuja configuração ainda não foi verificada.

## Depois

- Faltas e justificativas do Senado: o Diário só registra presença. Feito em 9/10: presença pelo Diário no mandato (296 de 301 sessões), participação nas votações nominais com os motivos do Senado e licenças desde fev/2023.
- Botão de destaque "Fale com ele(a)" na ficha, com o e-mail e o telefone do gabinete que já são coletados.
- Aviso por e-mail quando algo muda na ficha de quem a pessoa acompanha; depende da atualização automática.
- Busca por CEP em "Minha cidade".
- Histórico anterior ao mandato atual (antes de 2023), somente com fonte validada e se houver demanda.

## Fora do escopo

Decidido em 7/10/2026, para manter o app simples:

- Remuneração de servidores, inclusive Ministério Público, tribunais de contas, militares, Banco Central e servidores do Legislativo.
- Aposentados e pensionistas.
- Busca avançada e ferramentas de pesquisa (filtros, anotações, acompanhamento no navegador). Quem precisa do dado bruto baixa o CSV da ficha.
- Contratos e licitações do PNCP como recurso próprio. Se voltarem, entram como um bloco de "Minha cidade" (maiores compras da prefeitura), nunca ligados a uma pessoa.

## Princípios

Toda ampliação mostra dados ausentes como ausência, nunca como zero. Sinais de atenção não são conclusões de irregularidade. Cada número indica fonte, período e onde conferir.
