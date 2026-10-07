# Próximas etapas

Atualizado em 7 de outubro de 2026. Itens pendentes são planejamento; não descrevem cobertura já disponível. A cobertura e suas datas estão em [Dados e SQLite](data.md).

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
   - Importar do TSE quem foi eleito e reeleito em 2026, para mostrar na ficha e preparar a troca de legislatura.
   - O bloco eleitoral só volta à home com cobertura ampla.
2. **Minha cidade, versão 1.** A pessoa digita a cidade e vê quem a representa e quanto custa. A base é nacional e igual para as 5.570 cidades:
   - **TSE:** prefeito(a), vice e vereadores eleitos em 2024; governador(a) e deputados(as) estaduais eleitos em 2026; bens declarados e financiamento de campanha; deputados(as) federais mais votados(as) na cidade.
   - **Emendas parlamentares (Portal da Transparência):** quanto cada deputado(a) e senador(a) destinou para a cidade.
   - **SICONFI (Tesouro Nacional):** quanto a prefeitura e o estado arrecadam e gastam com saúde, educação e pessoal, comparados com cidades do mesmo porte.

   Onde houver dado aberto, entram extras (portais estaduais e Tribunais de Contas que publicam as contas de todos os municípios do estado), começando pelos lugares mais populosos e pelas fontes com arquivo para baixar ou API; raspar site vem por último. Onde não houver, a página diz que o órgão não publica aquilo em formato aberto. Comparações entre cidades e estados usam só a base nacional, para que publicar mais não faça um lugar parecer pior.
3. **Quanto custa um mandato.** Um total por parlamentar com divisão simples: subsídio, cota, gabinete e auxílios, cada parte com fonte e período. Inclui a verba de gabinete do Senado e a folha parlamentar. Retroativos e descontos ficam no link da fonte.
4. **Placar mais amplo.** Hoje a Câmara tem só quatro votações selecionadas. Ampliar com um critério neutro e público (por exemplo, todas as votações finais de PEC e PL), com resumo em linguagem simples a partir da ementa oficial e agrupamento por tema com metodologia publicada.
5. **Antes de divulgar o site:**
   - Atualização automática das cotas da Câmara e do Senado, com data da coleta, validação e registro das falhas. Hoje as coletas são manuais e o app não agenda downloads.
   - Backup externo com teste de restauração. O backup local consistente já existe.
   - Confirmar o deploy pelo GitHub Actions no servidor, cuja configuração ainda não foi verificada.

## Depois

- Faltas e justificativas do Senado, sem gastar semanas em PDF para chegar a uma porcentagem.
- Botão de destaque "Fale com ele(a)" na ficha, com o e-mail e o telefone do gabinete que já são coletados.
- Aviso por e-mail quando algo muda na ficha de quem a pessoa acompanha; depende da atualização automática.
- Busca por CEP em "Minha cidade".
- Histórico de anos anteriores das cotas e lacunas da Câmara, somente com fonte validada.

## Fora do escopo

Decidido em 7/10/2026, para manter o app simples:

- Remuneração de servidores, inclusive Ministério Público, tribunais de contas, militares, Banco Central e servidores do Legislativo.
- Aposentados e pensionistas.
- Busca avançada e ferramentas de pesquisa (filtros, anotações, acompanhamento no navegador). Quem precisa do dado bruto baixa o CSV da ficha.
- Contratos e licitações do PNCP como recurso próprio. Se voltarem, entram como um bloco de "Minha cidade" (maiores compras da prefeitura), nunca ligados a uma pessoa.

## Princípios

Toda ampliação mostra dados ausentes como ausência, nunca como zero. Sinais de atenção não são conclusões de irregularidade. Cada número indica fonte, período e onde conferir.
