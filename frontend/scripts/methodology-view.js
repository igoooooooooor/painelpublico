/* Metodologia e perguntas (/metodologia): as regras de cada número do painel, em perguntas.
   Complementa, sem substituir, as explicações junto de cada número nas telas. Os textos seguem
   docs/alerts.md (alertas), docs/voting-scoreboard.md (Placar) e as notas de cada tela; ao mudar uma
   regra, mude aqui também. */
const METHODOLOGY_REPOSITORY = 'https://github.com/igoooooooooor/painelpublico';
const METHODOLOGY_LINKS = {
  chamberQuotaGuide: ['Guia da Câmara sobre a cota', 'https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/cota-parlamentar'],
  senateQuotaRule: ['Ato do Senado sobre a cota (APS 5/2014)', 'https://adm.senado.gov.br/normas/ui/pub/normaConsultada?idNorma=203003'],
  alertRule: ['Regra no GitHub', `${METHODOLOGY_REPOSITORY}/blob/main/backend/alert_rules.py`],
  alertDocs: ['Documentação dos alertas', `${METHODOLOGY_REPOSITORY}/blob/main/docs/alerts.md`],
  scoreboardDocs: ['Metodologia do Placar', `${METHODOLOGY_REPOSITORY}/blob/main/docs/voting-scoreboard.md`],
  reportError: ['Informar um erro', `${METHODOLOGY_REPOSITORY}/issues`],
  legalNotice: ['Aviso legal', `${METHODOLOGY_REPOSITORY}/blob/main/LEGAL-NOTICE.md`],
  dataReleases: ['Releases de dados', `${METHODOLOGY_REPOSITORY}/releases`],
};
/* Cada resposta é uma lista de parágrafos; um item em lista vira uma lista com marcadores. */
const METHODOLOGY_SECTIONS = [
  { id: 'alerts', title: 'Alertas da cota', view: ['alerts', 'Ver os alertas'],
    lead: 'Duas regras fixas, aplicadas igualmente a deputados(as) e senadores(as), nas notas do mandato inteiro (fev/2023 em diante). Versão em uso: cota-alertas-v3, desde 8/10/2026.',
    questions: [
      { question: 'O que é um alerta de “mês acima da referência”?', answer: [
        'Aparece quando o gasto de um mês com a cota:',
        ['é pelo menos 1,75 vez a referência da própria pessoa;', 'fica pelo menos R$ 10 mil acima dela;',
          'e também fica acima do gasto mensal típico dos(as) colegas (o piso: mediana dos meses fechados dos parlamentares da mesma Casa e ano).'],
        'A referência é a mediana dos 12 meses anteriores completos, atravessando o ano. Os 12 meses precisam ter notas. Como o mandato começa em fev/2023, o primeiro mês avaliado é fev/2024. Meses seguidos marcados contam como um alerta só, dentro do mesmo ano.'] },
      { question: 'O que é uma “concentração em fornecedor”?', answer: [
        'Aparece quando pelo menos 50% e pelo menos R$ 30 mil das notas do ano foram para um mesmo fornecedor. É avaliada ano a ano desde 2023. O cartão sempre mostra a porcentagem junto com o valor pago, o total observado no ano e os meses com notas.'] },
      { question: 'E “passagens intermediadas por uma agência”?', answer: [
        'Quando a maioria das notas de uma concentração cita, no registro oficial, uma companhia aérea (LATAM/TAM, GOL ou Azul) que não é o fornecedor pago, o alerta sai com esse título. O valor é o total pago pelas passagens, não a receita da agência nem gasto com uma só companhia. Só o Senado publica a companhia; na Câmara não há essa evidência.'] },
      { question: 'Por que alguns meses não são avaliados?', answer: [
        'Só entram meses cujo prazo de apresentação das notas já terminou na data da coleta:',
        ['Câmara: 90 dias após o fim do mês.', 'Senado: até o fim de abril do ano seguinte. Por isso, em 2026, nenhum mês do Senado é avaliado para pico.'],
        'Também ficam de fora meses com histórico insuficiente (menos de 12 meses anteriores com notas), sem base (algum mês sem notas na janela) ou sem piso dos colegas. A ficha de cada pessoa lista esses meses e o motivo.'],
        links: [METHODOLOGY_LINKS.chamberQuotaGuide, METHODOLOGY_LINKS.senateQuotaRule] },
      { question: 'Por que novembro e dezembro aparecem tanto?', answer: [
        'Nas duas Casas, o saldo da cota não usado num mês se acumula ao longo do ano e expira em 31 de dezembro. Parte dos picos de fim de ano reflete o uso desse saldo. Os meses são avaliados como os outros, e o cartão informa a regra do saldo anual, sem tratá-la como justificativa.'] },
      { question: 'O que significa “período parcial”?', answer: [
        'A concentração do ano corrente pode mudar: o ano ainda pode receber notas. O cartão mostra os meses observados (por exemplo, jan–set/2026) e a data da coleta.'] },
      { question: 'O que é o “valor das despesas nos alertas”?', answer: [
        'A soma das notas que estão em algum alerta do mandato, contando cada lançamento uma vez só e preservando estornos. É a soma de despesas observadas, não estimativa de prejuízo.'] },
      { question: 'Os alertas estão ordenados por gravidade?', answer: [
        'Não. Eles aparecem dos mais recentes aos mais antigos, com títulos factuais e sem selo de intensidade. Ter menos alertas não torna ninguém “melhor”: os alertas não medem irregularidade.'] },
      { question: 'Posso refazer as contas?', answer: [
        'Sim. O cálculo está num único arquivo do código aberto, usado para gerar os alertas, explicar cada cartão e rodar a simulação. A simulação é somente leitura, usa semente fixa e grava os parâmetros, a fotografia do banco e os resultados por Casa e ano.'],
        links: [METHODOLOGY_LINKS.alertRule, METHODOLOGY_LINKS.alertDocs] },
    ] },
  { id: 'cost', title: 'Quanto custa por mês', view: ['politicians', 'Ver os políticos'],
    lead: 'O custo mensal soma as partes publicadas por cada Casa. Câmara e Senado publicam partes diferentes, então os valores servem para comparar dentro da mesma Casa, nunca entre elas.',
    questions: [
      { question: 'O que entra no custo de um deputado(a)?', answer: [
        'Salário bruto, auxílios, cota parlamentar e verba do gabinete. A média usa só os meses com as quatro partes publicadas; meses parciais não são estimados para o mês inteiro.',
        'Ficam de fora: 13º salário (mostrado à parte), diárias, vantagens indenizatórias, encargos do gabinete e apartamento funcional.'] },
      { question: 'E de um senador(a)?', answer: [
        'Remuneração do(a) senador(a), equipe do gabinete e cota, com a média de cada parte nos meses em que as três foram publicadas, somadas. São partes diferentes das da Câmara, por isso os números não são comparáveis.'] },
      { question: 'Os valores são corrigidos pela inflação?', answer: ['Não. São valores da época em que foram pagos.'] },
    ] },
  { id: 'quota', title: 'Cota parlamentar', view: ['politicians', 'Ver os políticos'],
    lead: 'A Cota para o Exercício da Atividade Parlamentar reembolsa despesas do trabalho, como divulgação, escritório, combustível e passagens. Não é salário.',
    questions: [
      { question: 'Como é calculada a média mensal da cota?', answer: [
        'É o total dividido pelos meses com notas no período indicado. Mês sem nota é ausência de dado, não gasto zero, então licenças e trocas de suplente não diluem a média. Estornos são preservados nos totais. Valores altos não indicam irregularidade.'] },
      { question: 'De onde vêm as notas?', answer: [
        'Dos dados abertos da Câmara e do portal de transparência do Senado. Na Câmara, as passagens aéreas não estão no arquivo aberto das notas e ficam fora da conta. No Senado, a análise usa os registros publicados; a imagem do documento não está disponível nesta base.'] },
    ] },
  { id: 'attendance', title: 'Presença', view: ['attendance', 'Ver a presença'],
    lead: 'Dias com sessão deliberativa no Plenário da Câmara, no mandato atual, pela página de presença de cada deputado(a).',
    questions: [
      { question: 'O que conta como falta justificada?', answer: [
        'O motivo informado pela Câmara, como missão autorizada, licença e atestado. Quem assumiu no meio do mandato tem menos dias na conta.'] },
      { question: 'E no Senado?', answer: [
        'O Senado publica só os registros de presença, por isso a presença de senadores(as) aparece em número de sessões, e não em porcentagem. As medidas das duas Casas são diferentes e não se comparam.'] },
    ] },
  { id: 'scoreboard', title: 'Placar', view: ['votes', 'Ver o Placar'],
    lead: 'Votações nominais do Plenário da Câmara sobre o texto principal de projetos de lei e de mudanças na Constituição, conferidas uma a uma nas fontes oficiais.',
    questions: [
      { question: 'Quais votações entram?', answer: [
        'Só as votações do texto principal de PL, PLP e PEC no Plenário, com o voto de cada deputado(a) registrado. Entram aprovações e rejeições, pela mesma regra, sem escolha por partido, autor ou tema.',
        'Essa é a contagem do Placar. Em alguns projetos, destaques, emendas e pedidos de urgência já conferidos aparecem à parte, dentro da votação do projeto, sem entrar na contagem nem nas comparações. Procedimentos, redação final e votações simbólicas ficam de fora. O Placar não é tudo o que a Câmara votou, e um projeto aprovado ainda pode não ter virado lei.'] },
      { question: 'Como são escritos o resumo e o que significava votar Sim e Não?', answer: [
        'Cada votação é conferida no registro do resultado, no texto efetivamente votado e no relatório nominal. O resumo e os significados de Sim e Não partem desse texto, e a página de cada votação mostra a data da revisão. Quando não dá para identificar com segurança a versão votada, a votação fica pendente e não é publicada.'],
        links: [METHODOLOGY_LINKS.scoreboardDocs] },
      { question: 'Por que quase todas foram aprovadas?', answer: [
        'Aprovação não quer dizer consenso: um texto aprovado por margem estreita pode ter sido muito disputado, e o placar de cada votação mostra o tamanho da divisão. O Placar também não mostra os projetos que não chegaram a uma votação nominal do texto principal, como os que ficaram nas comissões ou foram decididos em votação simbólica. Parte das disputas aparece nos destaques, emendas e pedidos de urgência, mostrados à parte quando já conferidos.'] },
    ] },
  { id: 'city', title: 'Minha cidade', view: ['city', 'Ver Minha cidade'],
    lead: 'Dados do município a partir do IBGE, do TSE, do Tesouro Nacional (Siconfi) e do Portal da Transparência.',
    questions: [
      { question: 'O que é “empenhado” e “pago” nas emendas?', answer: [
        'Empenhado é o valor reservado no orçamento: um compromisso, que ainda não é pagamento. Pago é o que de fato saiu do caixa federal. Restos a pagar pagos são pagamentos de agora de compromissos de anos anteriores.'] },
      { question: 'Como é o gasto por morador?', answer: [
        'A despesa empenhada da prefeitura no ano, dividida pela população do mesmo ano. Saúde e educação também incluem salários, então essas linhas não devem ser somadas. O valor “típico” é a mediana entre cidades de porte parecido; não é meta nem ranking.'] },
    ] },
  { id: 'taxes', title: 'Contador de impostos', view: ['home', 'Ver o contador'],
    lead: 'Impostos federais e estaduais pagos no ano, a partir da arrecadação publicada pela Receita Federal e pelos estados.',
    questions: [
      { question: 'O contador é exato?', answer: [
        'Não. É uma estimativa: os valores oficiais até o último mês publicado mais a média diária do ano.'] },
      { question: 'O que entra na conta?', answer: [
        'No federal, os impostos e contribuições administrados pela Receita Federal. No estadual, ICMS, IPVA e ITCD dos 27 estados, pelos relatórios entregues ao Tesouro Nacional (Siconfi). Ficam de fora os impostos municipais (IPTU, ISS e ITBI), porque nem todas as cidades publicam o dado mensal, e as taxas e contribuições estaduais.'] },
    ] },
  { id: 'sources', title: 'Fontes, datas e erros', lead: 'Cada tela informa a fonte e a data da coleta.',
    questions: [
      { question: 'Por que alguns valores aparecem como “não informado”?', answer: [
        'Dado ausente não significa zero. Quando a fonte oficial não publicou um valor, o painel diz isso, em vez de estimar ou completar com zero.'] },
      { question: 'Encontrei um erro. O que faço?', answer: [
        'Abra um aviso no GitHub com o link da página e o que está diferente da fonte oficial, ou escreva para contato@painelpublico.com.'],
        links: [METHODOLOGY_LINKS.reportError] },
      { question: 'Posso usar os dados?', answer: [
        'Sim. A base do painel é publicada sob a licença CC BY 4.0: pode ser usada e redistribuída, citando “Painel Público” e o link do release. As informações continuam pertencendo às fontes oficiais.'],
        links: [METHODOLOGY_LINKS.dataReleases] },
      { question: 'O painel tem vínculo com algum partido ou governo?', answer: [
        'Não. É um projeto pessoal e independente, sem vínculo com partidos, políticos, governos ou órgãos públicos.'],
        links: [METHODOLOGY_LINKS.legalNotice] },
    ] },
];
const methodologyAnchor = section => `methodology-${section.id}`;
function methodologyAnswer(part) {
  return Array.isArray(part) ? `<ul>${part.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : `<p>${esc(part)}</p>`;
}
function methodologyQuestion({ question, answer, links = [] }) {
  return `<details class="methodology-question"><summary>${esc(question)}</summary>
    <div class="methodology-answer">${answer.map(methodologyAnswer).join('')}
      ${links.length ? `<p class="methodology-links">${links.map(([label, url]) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`).join('')}</p>` : ''}</div>
  </details>`;
}
function methodologyView() {
  return `<div class="methodology-page">
    <section class="methodology-intro">
      <h1 class="h ph-t">Como o painel funciona</h1>
      <p class="ph-lead">Cada número do site vem de uma fonte oficial e segue uma regra escrita aqui. As regras são iguais para todos(as) e o código é aberto: qualquer pessoa pode refazer as contas.</p>
      <p class="card methodology-notice"><span><b>Alertas não indicam irregularidade.</b> Eles detectam variação de gasto e concentração em fornecedor. Um contrato recorrente legítimo pode gerar um alerta, e um gasto problemático pode não gerar nenhum. Confira sempre as notas na fonte oficial.</span></p>
    </section>
    <div class="methodology-layout">
      <nav class="methodology-toc" aria-label="Nesta página"><span class="k">Nesta página</span>
        ${METHODOLOGY_SECTIONS.map(section => `<a href="#${methodologyAnchor(section)}">${esc(section.title)}</a>`).join('')}
      </nav>
      <div class="methodology-sections">
        ${METHODOLOGY_SECTIONS.map(section => `<section class="methodology-section" id="${methodologyAnchor(section)}">
          <header><h2 class="h">${esc(section.title)}</h2><p>${esc(section.lead)}</p></header>
          <div class="methodology-questions">${section.questions.map(methodologyQuestion).join('')}</div>
          ${section.view ? `<a class="methodology-view-link" href="${PATH_BY_VIEW[section.view[0]]}" data-go="${section.view[0]}">${esc(section.view[1])} →</a>` : ''}
        </section>`).join('')}
      </div>
    </div>
  </div>`;
}
