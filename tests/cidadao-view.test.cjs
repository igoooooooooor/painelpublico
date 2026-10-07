const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'cidadao-view.js'),
  'utf8',
);
const appSource = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'app.script.js'),
  'utf8',
);
const profileSource = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'profile-data.js'),
  'utf8',
);

function makeView({ fetchImpl = async () => { throw new Error('Unexpected fetch'); }, schedule = setTimeout } = {}) {
  const events = {};
  const elements = {
    'cid-pol-summary': { innerHTML: '' },
    'cid-pol-list': { innerHTML: '' },
  };
  const state = { view: 'politicos', pol: null };
  const context = {
    AbortController,
    clearTimeout,
    DATA: { deputados: [], geradoEm: '2026-10-07', perfis: { profiles: {} }, presencaTodos: [], votacoes: [], votosCompletos: {} },
    document: {
      addEventListener(name, handler) { events[name] = handler; },
      getElementById(id) { return elements[id] || null; },
    },
    esc(value) {
      return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    },
    extFichaExtra() { return ''; },
    fetch: fetchImpl,
    first(value) { return String(value || '').split(' ')[0]; },
    brl(value, digits = 0) { return 'R$ ' + Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits }); },
    MES: ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
    matchMedia() { return { matches: false, addEventListener() {} }; },
    go(view) { state.view = view; },
    rerender() {},
    setTimeout: schedule,
    URL,
    state,
  };
  vm.createContext(context);
  vm.runInContext(profileSource + '\n' + source + '\nthis.__api = { cid, cidOpenPol, cidAvatar, cidTemFicha, cidPolRow, cidPolCoverageHTML, cidPolCoverageNotesHTML, cidLoadPol, vPoliticos, cidHomeCard, profileData, profileSectionsHTML, vPolitico, skel };', context);
  context.extVotosDe = id => context.profileVotes(id).filter(row => String(row.v.data || '').startsWith('2026'));
  context.extPresBar = presence => presence
    ? `<span class="pbar" data-presence-days="${presence.dias}"></span>` : '';
  return { api: context.__api, elements, state, events, context };
}

function ficha(api, state, id, fields = {}) {
  state.pol = id;
  api.cid.fichaId = id;
  api.cid.ficha = {
    pessoa: { id, name: 'Pessoa Parlamentar', role: id.startsWith('senado:') ? 'senador' : 'deputado', party: 'PT', uf: 'SP' },
    total: null, media: 100000, hasExpenseData: false, expenseCount: 0,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
    ...fields,
  };
}

test('the home ficha skeleton remains byte-for-byte intact while a loading politician gets the three-answer shape', () => {
  const { api, state } = makeView();
  const oldFichaSkeleton = [
    '<span class="sr-only" role="status">Carregando…</span><div class="profile" aria-hidden="true"><i class="sk sk-o" style="width:64px;height:64px"></i><span class="sk-col" style="flex:1"><i class="sk " style="width:55%;height:24px"></i><i class="sk " style="width:40%;height:12px"></i></span></div>',
    '    <section class="card hero sk-card" aria-hidden="true"><i class="sk " style="width:40%;height:10px"></i><i class="sk " style="width:62%;height:56px"></i><i class="sk " style="width:90%;height:12px"></i><i class="sk " style="width:100%;height:10px"></i><i class="sk " style="width:100%;height:10px"></i></section>',
    '    <section class="card sk-card" aria-hidden="true"><i class="sk " style="width:35%;height:10px"></i><i class="sk " style="width:50%;height:30px"></i><i class="sk " style="width:100%;height:8px"></i><i class="sk " style="width:88%;height:12px"></i><i class="sk " style="width:70%;height:12px"></i></section><section class="card sk-card" aria-hidden="true"><i class="sk " style="width:35%;height:10px"></i><i class="sk " style="width:50%;height:30px"></i><i class="sk " style="width:100%;height:8px"></i><i class="sk " style="width:88%;height:12px"></i><i class="sk " style="width:70%;height:12px"></i></section>',
  ].join('\n');
  assert.equal(api.skel('ficha'), oldFichaSkeleton);
  assert.doesNotMatch(api.skel('ficha'), /Em 3 respostas/);

  state.pol = 'camara:55';
  api.cid.fichaId = state.pol;
  api.cid.ficha = null;
  const loadingProfile = api.vPolitico();
  assert.match(loadingProfile, /Em 3 respostas/);
  assert.match(loadingProfile, /class="cid-answers"/);
  assert.equal([...loadingProfile.matchAll(/<section class="card(?:\s+hero)?\s+sk-card"/g)].length, 3);
});

test('clearing a search updates state before debounce so another filter cannot restore the old query', () => {
  const { api, events } = makeView({ schedule: () => 1 });
  api.cid.pol.q = 'Gilmar Machado';
  events.input({ target: { id: 'cid-busca', value: '' } });
  assert.equal(api.cid.pol.q, '');
});

test('roster counts are visible while coverage details stay collapsed', () => {
  const { api } = makeView();
  const coverage = {
    deputado: { count: 513, withExpenses: 509 },
    senador: { count: 82, withExpenses: 79 },
  };

  assert.match(api.cidPolCoverageHTML(coverage), /513 deputados\(as\).*82 registros do Senado/);
  const details = api.cidPolCoverageNotesHTML(coverage);
  assert.match(details, /<details/);
  assert.match(details, /509 de 513/);
  assert.match(details, /79 de 82/);
  assert.match(details, /81 cadeiras/);
  assert.match(details, /suplentes em transição/);
});

test('the roster and profile distinguish missing reimbursements from an observed zero', () => {
  const { api, state } = makeView();
  const missing = api.cidPolRow({
    id: 'camara:no-data', name: 'Pessoa sem dado', role: 'deputado',
    gasto: null, hasExpenseData: false, alertas: 0,
  }, 100);
  const zero = api.cidPolRow({
    id: 'camara:zero', name: 'Pessoa com zero', role: 'deputado',
    gasto: 0, hasExpenseData: true, alertas: 0,
  }, 100);

  assert.match(missing, /Sem dados/);
  assert.match(missing, /sem despesa observada/);
  assert.match(missing, /width:0%/);
  assert.match(zero, /R\$ 0/);
  assert.doesNotMatch(zero, /Sem dados|0 mil/);
  assert.match(zero, /width:0%/);

  state.pol = 'camara:no-data';
  api.cid.fichaId = state.pol;
  api.cid.ficha = {
    pessoa: { id: state.pol, name: 'Pessoa sem dado', role: 'deputado', party: 'PT', uf: 'SP' },
    total: null, hasExpenseData: false, expenseCount: 0,
  };
  const profile = api.vPolitico();
  assert.match(profile, /Sem dados/);
  assert.match(profile, /Nenhuma despesa de reembolso foi observada/);
  assert.match(profile, /Salário à parte:.*46\.366/);
  assert.match(profile, /Equipe e verba de gabinete/);
  assert.match(profile, /Projetos apresentados/);
  assert.doesNotMatch(profile, /Detalhes da amostra editorial|data-editorial-ficha|data-pdf/);
  assert.doesNotMatch(profile, /cid-months|Nenhum alerta|R\$.*0 mil/);
});

test('home alert loading failures show a retry card instead of a sample fallback', async () => {
  const { api, events } = makeView({ fetchImpl: async () => { throw new Error('offline'); } });
  const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
  const loading = api.cidHomeCard();
  assert.match(loading, /Carregando/);
  await new Promise(resolve => setImmediate(resolve));
  const failed = api.cidHomeCard();
  assert.match(failed, /data-home-retry/);
  assert.doesNotMatch(failed, /radarHome|amostra|editorial/);
  const retry = { dataset: {}, hasAttribute: name => name === 'data-home-retry' };
  retry.closest = () => retry;
  events.click({ target: { closest: () => retry }, preventDefault() {} });
  assert.equal(api.cid.cache.has(path), false);
});

test('all federal identifiers use the same profile route and avatar URL without a local sample roster', () => {
  const { api, state } = makeView();
  assert.equal(api.cidTemFicha('camara:513'), true);
  assert.equal(api.cidTemFicha('senado:82'), true);
  assert.equal(api.cidTemFicha('camara:abc'), false);
  const avatar = api.cidAvatar({ id: 'camara:513', name: 'Deputada Nova' }, 48);
  assert.match(avatar, /https:\/\/www\.camara\.leg\.br\/internet\/deputado\/bandep\/513\.jpg/);
  assert.doesNotMatch(avatar, /undefined|Amostra editorial/);
  const snapshotPhoto = api.cidAvatar({ id: 'camara:513', name: 'Deputada Nova', photo: 'https://example.test/photos/513.jpg' });
  assert.match(snapshotPhoto, /src="https:\/\/example\.test\/photos\/513\.jpg"/);

  api.cidOpenPol('123');
  assert.equal(state.view, 'politico');
  assert.equal(state.pol, 'camara:123');
  assert.equal(state.dep, '123');

  api.cidOpenPol('camara:987');
  assert.equal(state.view, 'politico');
  assert.equal(state.pol, 'camara:987');
  assert.equal(state.dep, '987');
});

test('the full public roster request runs with an empty query and an empty result stays explicit', async () => {
  const calls = [];
  const { api, elements } = makeView({ fetchImpl: async url => {
    calls.push(url);
    return { ok: true, async json() { return { itens: [], total: 0, cobertura: null, medias: {} }; } };
  } });
  api.cidLoadPol(false);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['/api/c/politicos?pageSize=25&page=1&ordem=nome']);
  assert.match(elements['cid-pol-list'].innerHTML, /Ninguém encontrado/);
});

test('politicians view has no editorial sample block', () => {
  const { api } = makeView();
  api.cid.pol.key = 'q=&cargo=&ordem=nome';
  const html = api.vPoliticos();
  assert.doesNotMatch(html, /Detalhes editoriais|amostra editorial|data-editorial-ficha|data-pdf/);
});

test('legacy ficha alias preserves canonical Senate identity', () => {
  const match = appSource.match(/function vFicha\(\) \{[\s\S]*?\n\}/);
  assert.ok(match, 'legacy vFicha compatibility function exists');
  const state = { dep: 'senado:77', pol: null };
  const context = { state, vPolitico() { return state.pol; } };
  vm.createContext(context);
  vm.runInContext(`${match[0]}\nthis.__vFicha = vFicha;`, context);

  assert.equal(context.__vFicha(), 'senado:77');
  context.state.dep = '77';
  assert.equal(context.__vFicha(), 'camara:77');
});

test('profiles with observed expenses still receive shared sections and separate cota from pay', () => {
  const { api, state } = makeView();
  state.pol = 'camara:55';
  api.cid.fichaId = state.pol;
  api.cid.ficha = {
    pessoa: { id: state.pol, name: 'Perfil com despesas', role: 'deputado', party: 'PV', uf: 'RJ' },
    total: 80000, media: 70000, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
  };

  const profile = api.vPolitico();
  assert.match(profile, /Salário à parte:.*46\.366/);
  assert.match(profile, /Equipe e verba de gabinete/);
  assert.match(profile, /Cota é reembolso/);
  assert.match(profile, /subsídio bruto mensal de referência do cargo/);
  assert.doesNotMatch(profile, /Não é o salário, que é de/);
});

test('profile starts with three ordered answers and keeps the complementary details', () => {
  const { api, state } = makeView();
  ficha(api, state, 'camara:55', {
    total: 80000, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [],
    alertas: [{ nivel: 'medio', tipo: 'valor', titulo: 'Alerta preservado', frase: 'Conferir registro.' }],
  });
  const html = api.vPolitico();
  const answers = [...html.matchAll(/data-profile-answer="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(answers, ['custo', 'trabalho', 'alerta']);
  assert.match(html, /Em 3 respostas/);
  assert.ok(html.indexOf('Quanto custa?') < html.indexOf('Trabalha?'));
  assert.ok(html.indexOf('Trabalha?') < html.indexOf('Algum gasto incomum?'));
  assert.match(html, /class="cid-details/);
  const detailKeys = [...html.matchAll(/data-profile-section="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(detailKeys, ['gastos', 'alertas', 'votos', 'projetos', 'equipe', 'contato', 'fontes']);
  assert.match(html, /Alerta preservado/);
});

test('profile distinguishes missing cota from an observed zero and treats a difference under ten percent as similar', () => {
  const { api, state } = makeView();
  ficha(api, state, 'camara:55');
  const missing = api.vPolitico();
  const missingAnswer = missing.match(/<section[^>]*data-profile-answer="custo"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(missingAnswer, /Sem dados/);
  assert.match(missingAnswer, /Ausência não significa gasto zero/);
  assert.match(missingAnswer, /Salário à parte:.*46\.366/);
  assert.doesNotMatch(missingAnswer, /R\$ 0/);

  ficha(api, state, 'camara:55', { total: 0, hasExpenseData: true });
  const zero = api.vPolitico();
  const zeroAnswer = zero.match(/<section[^>]*data-profile-answer="custo"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(zeroAnswer, /R\$ 0/);
  assert.doesNotMatch(zeroAnswer, /Sem dados/);

  ficha(api, state, 'camara:55', { total: 109000, hasExpenseData: true, media: 100000 });
  const nearAverage = api.vPolitico();
  assert.match(nearAverage, /<span class="fchip cid-verdict">Parecido com a média<\/span>/);
});

test('work answer uses the average of individual presence rates and counts only recorded votes', () => {
  const { api, state, context } = makeView();
  context.DATA.presencaTodos = [
    { id: 1, dias: 250, presente: 201, falta: 49, justificadas: 0 },
    { id: 2, dias: 200, presente: 161, falta: 39, justificadas: 0 },
  ];
  context.DATA.votacoes = [
    { id: 'yes', data: '2026-09-01', titulo: 'Votação com sim', secreta: false },
    { id: 'missing', data: '2026-09-02', titulo: 'Sem linha individual', secreta: false },
    { id: 'not-voted', data: '2026-09-03', titulo: 'Registro não votou', secreta: false },
  ];
  context.DATA.votosCompletos = {
    yes: [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Sim']],
    missing: [[2, 'Outra pessoa', 'PL', 'RJ', 'Sim']],
    'not-voted': [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Não votou']],
  };
  ficha(api, state, 'camara:1');
  const html = api.vPolitico();
  const work = html.match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /201 de 250 dias/);
  assert.match(work, /média da Câmara: 80%/);
  assert.match(work, /Perto da média/);
  assert.match(work, /Votou em <b>1 de 3<\/b> votações do Placar/);
  assert.match(html, /Sem registro importado[\s\S]*Sem linha individual/);
  assert.match(html, /Presença em voto secreto e quem presidiu aparecem à parte/);
});

test('secret votes and chairing are shown as records, not nominal votes or inferred absences', () => {
  const { api, state, context } = makeView();
  context.DATA.votacoes = [
    { id: 'secret', data: '2026-09-01', titulo: 'Voto secreto', secreta: true },
    { id: 'chair', data: '2026-09-02', titulo: 'Presidência da sessão', secreta: false },
    { id: 'missing', data: '2026-09-03', titulo: 'Sem linha individual', secreta: false },
  ];
  context.DATA.votosCompletos = {
    secret: [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Sim']],
    chair: [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Artigo 17']],
    missing: [[2, 'Outra pessoa', 'PL', 'RJ', 'Sim']],
  };
  ficha(api, state, 'camara:1');
  let html = api.vPolitico();
  let work = html.match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Sem voto nominal identificado neste recorte/);
  assert.match(work, /2 registros só de presença ou presidência/);
  assert.doesNotMatch(work, /Votou em <b>0 de/);
  assert.match(html, /data-vote="secret"><b>Presença registrada · voto secreto<\/b>/);
  assert.match(html, /data-vote="chair"><b>presidiu<\/b>/);
  assert.match(html, /data-vote="missing"><b>Sem registro importado<\/b>/);
  assert.doesNotMatch(work, /Não votou|não compareceu|faltou à votação/);

  context.DATA.votacoes = [{ id: 'not-voted', data: '2026-09-04', titulo: 'Ausência publicada', secreta: false }];
  context.DATA.votosCompletos = { 'not-voted': [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Não votou']] };
  html = api.vPolitico();
  work = html.match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Votou em <b>0 de 1<\/b> votações do Placar/);
  assert.match(html, /data-vote="not-voted"><b>não votou<\/b>/);
});

test('Senate work answer stays unavailable even when a Câmara record has the same number', () => {
  const { api, state, context } = makeView();
  context.DATA.presencaTodos = [{ id: 77, dias: 10, presente: 8, falta: 2, justificadas: 0 }];
  context.DATA.votacoes = [{ id: 'camara-77', data: '2026-09-01', titulo: 'Votação da Câmara', secreta: false }];
  context.DATA.votosCompletos = { 'camara-77': [[77, 'Homônimo numérico', 'PT', 'SP', 'Sim']] };
  ficha(api, state, 'senado:77');
  const html = api.vPolitico();
  const work = html.match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Presença do Senado sem registro importado/);
  assert.match(html, /Votos nominais do Senado ainda não disponíveis neste recorte/);
  assert.doesNotMatch(work, /8\/10|201 de 250|Votou em|votações do Placar · 1/);
});

test('Senate profile shows fetched votes with skeletons and never counts parliamentary activity as a vote', async () => {
  let release;
  const { api, state, context } = makeView({ fetchImpl: () => new Promise(resolve => { release = resolve; }) });
  context.DATA.senado = { sobDemanda: true };
  ficha(api, state, 'senado:77');
  assert.match(api.vPolitico(), /data-profile-answer="trabalho"[\s\S]*?Carregando/);
  release({ ok: true, json: async () => ({
    presenca: { status: 'unavailable', items: [] },
    votacoes: { status: 'imported', items: ['Sim', 'Atividade parlamentar', 'Presente – Não registrou voto', null].map((vote, n) => ({
      id: `senado:${n}`, titulo: `Votação ${n}`, data: '2026-09-01', sourceUrl: 'https://legis.senado.leg.br/voto/' + n,
      rows: vote === null ? [] : [['senado:77', 'Senador', 'PT', 'SP', vote]],
    })) },
  }) });
  await new Promise(resolve => setImmediate(resolve));
  const html = api.vPolitico();
  const work = html.match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Voto identificado em <b>1 de 3<\/b> votações do Senado com registro individual/);
  assert.match(work, /Presença do Senado sem registro importado/);
  assert.doesNotMatch(work, /class="huge"|0%|média da Câmara/);
  assert.match(html, /href="https:\/\/legis.senado.leg.br\/voto\/0"/);
  assert.match(html, /atividade parlamentar/);
  assert.match(html, /Sem registro importado/);
  assert.doesNotMatch(html, /data-vote="senado:/);
});

test('Senate registered attendance is a positive count without an inferred attendance rate or absence', async () => {
  const { api, state, context } = makeView({ fetchImpl: async () => ({ ok: true, json: async () => ({
    presenca: { status: 'partial', sessionCount: 12, items: [{ id: 'senado:77', presente: 9, dias: null, falta: null, justificadas: null }] },
    votacoes: { status: 'imported', items: [] },
  }) }) });
  context.DATA.senado = { sobDemanda: true };
  ficha(api, state, 'senado:77');
  api.vPolitico();
  await new Promise(resolve => setImmediate(resolve));
  const work = api.vPolitico().match(/<section[^>]*data-profile-answer="trabalho"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /9<small> sessões/);
  assert.match(work, /12 listas de sessões consultadas/);
  assert.match(work, /Faltas e justificativas não apuradas/);
  assert.doesNotMatch(work, /75%|Justificada 0|Falta 3|média do Senado/);
  ficha(api, state, 'senado:78');
  assert.match(api.vPolitico(), /Presença do Senado sem registro importado/);
});

test('three-answer alert highlights only the strongest alert while details retain every alert in source order', () => {
  const { api, state } = makeView();
  ficha(api, state, 'camara:55', {
    total: 120000, media: 100000, hasExpenseData: true,
    alertas: [
      { nivel: 'info', tipo: 'valor', titulo: 'Primeiro alerta informativo', frase: 'Informação inicial.' },
      { nivel: 'alto', tipo: 'valor', titulo: 'Primeiro alerta alto', frase: 'Maior gravidade, primeiro.' },
      { nivel: 'medio', tipo: 'valor', titulo: 'Alerta médio', frase: 'Gravidade média.' },
      { nivel: 'alto', tipo: 'valor', titulo: 'Segundo alerta alto', frase: 'Mesmo nível, depois.' },
    ],
  });
  const html = api.vPolitico();
  const answer = html.match(/<section[^>]*data-profile-answer="alerta"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(answer, /4 alertas/);
  assert.match(answer, /Primeiro alerta alto/);
  assert.doesNotMatch(answer, /Primeiro alerta informativo|Alerta médio|Segundo alerta alto/);
  const details = html.slice(html.indexOf('data-profile-section="alertas"'));
  const order = ['Primeiro alerta informativo', 'Primeiro alerta alto', 'Alerta médio', 'Segundo alerta alto'];
  assert.ok(order.every(title => details.includes(title)));
  assert.deepEqual(order.map(title => details.indexOf(title)), [...order.map(title => details.indexOf(title))].sort((a, b) => a - b));
});

test('Senate profiles show source snapshot metadata safely and omit empty fields', () => {
  const { api, state } = makeView();
  state.pol = 'senado:current';
  api.cid.fichaId = state.pol;
  api.cid.ficha = {
    pessoa: {
      id: state.pol, name: 'Dora Senadora', role: 'senador',
      position: 'Mandato <titular> & participação',
      employmentStatus: 'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular',
      sourceUrl: 'https://senado.example.test/lista?x=" onmouseover="alert(1)',
    },
    total: null, hasExpenseData: false, expenseCount: 0,
  };

  const profile = api.vPolitico();
  assert.match(profile, /data-profile-section="mandato"/);
  assert.match(profile, /Mandato &lt;titular&gt; &amp; participação/);
  assert.match(profile, /Exercício de 05\/08\/2026 a 06\/10\/2026 — Retorno do titular/);
  assert.match(profile, /href="https:\/\/senado\.example\.test\/lista\?x=%22%20onmouseover=%22alert\(1\)" target="_blank"/);
  assert.doesNotMatch(profile, /href="[^"]*" onmouseover=/);
  assert.match(profile, /data-public-authority="senado:current"/);
  assert.match(profile, /data-public-authority-position="Mandato &lt;titular&gt; &amp; participação"/);
  assert.match(profile, /data-public-authority-status="Exercício de 05\/08\/2026 a 06\/10\/2026 — Retorno do titular"/);
  assert.match(profile, /data-public-authority-source="https:\/\/senado\.example\.test\/lista\?x=&quot; onmouseover=&quot;alert\(1\)"/);

  state.pol = 'senado:without-metadata';
  api.cid.fichaId = state.pol;
  api.cid.ficha = {
    pessoa: { id: state.pol, name: 'Sem Metadados', role: 'senador' },
    total: null, hasExpenseData: false, expenseCount: 0,
  };
  assert.doesNotMatch(api.vPolitico(), /Na fotografia da fonte|Fonte do Senado/);
});

test('a stale roster response cannot overwrite newer coverage counts', async () => {
  const pending = [];
  const fetchImpl = url => new Promise(resolve => pending.push({ url, resolve }));
  const { api, elements } = makeView({ fetchImpl });
  api.cid.pol.q = 'older query';
  api.cidLoadPol(false);
  api.cid.pol.q = 'newer query';
  api.cidLoadPol(false);

  const current = pending.find(item => item.url.includes('newer%20query'));
  const stale = pending.find(item => item.url.includes('older%20query'));
  assert.ok(current);
  assert.ok(stale);

  const payload = (deputyCount, senatorCount) => ({
    ok: true,
    async json() {
      return {
        itens: [], total: 0, page: 1, pageSize: 25, medias: {},
        cobertura: {
          deputado: { count: deputyCount, withExpenses: deputyCount },
          senador: { count: senatorCount, withExpenses: senatorCount },
        },
      };
    },
  });
  current.resolve(payload(9, 2));
  await new Promise(resolve => setImmediate(resolve));
  const summary = elements['cid-pol-summary'].innerHTML;
  assert.match(summary, /9 deputados/);

  stale.resolve(payload(3, 1));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements['cid-pol-summary'].innerHTML, summary);
});
