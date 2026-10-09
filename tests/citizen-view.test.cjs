const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'citizen-view.js'),
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
const profileCostSource = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'profile-cost.js'),
  'utf8',
);
const senateCostSource = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'profile-senate-cost.js'),
  'utf8',
);
const shareSource = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'share-card.js'),
  'utf8',
);

function makeView({ fetchImpl = async () => { throw new Error('Unexpected fetch'); }, schedule = setTimeout } = {}) {
  const events = {};
  const elements = {
    'citizen-politician-summary': { innerHTML: '' },
    'citizen-politician-list': { innerHTML: '' },
  };
  const state = { view: 'politicians', politicianId: null };
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
    profileExtras() { return ''; },
    fetch: fetchImpl,
    first(value) { return String(value || '').split(' ')[0]; },
    brl(value, digits = 0) { return 'R$ ' + Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits }); },
    SHORT_MONTHS: ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
    matchMedia() { return { matches: false, addEventListener() {} }; },
    navigateToView(view) { state.view = view; },
    rerender() {},
    setTimeout: schedule,
    URL,
    state,
  };
  vm.createContext(context);
  vm.runInContext(profileSource + '\n' + profileCostSource + '\n' + senateCostSource + '\n' + shareSource + '\n' + source + '\nthis.__api = { senateCostAnswer, senateCostDetails, senateCostMonths, citizenState, openPolitician, citizenAvatar, citizenHasProfile, politicianRow, politicianCoverageHTML, politicianCoverageNotesHTML, loadPoliticians, politiciansView, homeAlertCard, profileData, profileSectionsHTML, profileView, profileQuotaDifferenceNote, profileMandateStartNote, alertCard, skel };', context);
  context.votesForPerson = id => context.profileVotes(id).filter(record => String(record.vote.data || '').startsWith('2026'));
  context.attendanceBar = presence => presence
    ? `<span class="pbar" data-presence-days="${presence.dias}"></span>` : '';
  return { api: context.__api, elements, state, events, context };
}

function setProfileFixture(api, state, id, fields = {}) {
  state.politicianId = id;
  api.citizenState.profileId = id;
  api.citizenState.profile = {
    pessoa: { id, name: 'Pessoa Parlamentar', role: id.startsWith('senado:') ? 'senador' : 'deputado', party: 'PT', uf: 'SP' },
    total: null, media: 100000, hasExpenseData: false, expenseCount: 0,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
    ...fields,
  };
}

test('the home profile skeleton remains byte-for-byte intact while a loading politician gets the three-answer shape', () => {
  const { api, state } = makeView();
  const oldProfileSkeleton = [
    '<span class="sr-only" role="status">Carregando…</span><div class="profile" aria-hidden="true"><i class="sk sk-o" style="width:64px;height:64px"></i><span class="sk-col" style="flex:1"><i class="sk " style="width:55%;height:24px"></i><i class="sk " style="width:40%;height:12px"></i></span></div>',
    '    <section class="card hero sk-card" aria-hidden="true"><i class="sk " style="width:40%;height:10px"></i><i class="sk " style="width:62%;height:56px"></i><i class="sk " style="width:90%;height:12px"></i><i class="sk " style="width:100%;height:10px"></i><i class="sk " style="width:100%;height:10px"></i></section>',
    '    <section class="card sk-card" aria-hidden="true"><i class="sk " style="width:35%;height:10px"></i><i class="sk " style="width:50%;height:30px"></i><i class="sk " style="width:100%;height:8px"></i><i class="sk " style="width:88%;height:12px"></i><i class="sk " style="width:70%;height:12px"></i></section><section class="card sk-card" aria-hidden="true"><i class="sk " style="width:35%;height:10px"></i><i class="sk " style="width:50%;height:30px"></i><i class="sk " style="width:100%;height:8px"></i><i class="sk " style="width:88%;height:12px"></i><i class="sk " style="width:70%;height:12px"></i></section>',
  ].join('\n');
  assert.equal(api.skel('ficha'), oldProfileSkeleton);
  assert.doesNotMatch(api.skel('ficha'), /Em 3 respostas/);

  state.politicianId = 'camara:55';
  api.citizenState.profileId = state.politicianId;
  api.citizenState.profile = null;
  const loadingProfile = api.profileView();
  assert.match(loadingProfile, /Em 3 respostas/);
  assert.match(loadingProfile, /class="citizen-answers"/);
  assert.equal([...loadingProfile.matchAll(/<section class="card(?:\s+hero)?\s+sk-card"/g)].length, 3);
});

test('clearing a search updates state before debounce so another filter cannot restore the old query', () => {
  const { api, events } = makeView({ schedule: () => 1 });
  api.citizenState.politicians.query = 'Gilmar Machado';
  events.input({ target: { id: 'citizen-search', value: '' } });
  assert.equal(api.citizenState.politicians.query, '');
});

test('roster counts are visible while coverage details stay collapsed', () => {
  const { api } = makeView();
  const coverage = {
    deputado: { count: 513, withExpenses: 509 },
    senador: { count: 82, withExpenses: 79 },
  };

  assert.match(api.politicianCoverageHTML(coverage), /513 deputados\(as\).*82 registros do Senado/);
  const details = api.politicianCoverageNotesHTML(coverage);
  assert.match(details, /<details/);
  assert.match(details, /509 de 513/);
  assert.match(details, /79 de 82/);
  assert.match(details, /81 cadeiras/);
  assert.match(details, /suplentes em transição/);
});

test('the roster and profile distinguish missing reimbursements from an observed zero', () => {
  const { api, state } = makeView();
  const missing = api.politicianRow({
    id: 'camara:no-data', name: 'Pessoa sem dado', role: 'deputado',
    gasto: null, hasExpenseData: false, alertas: 0,
  }, 100);
  const zero = api.politicianRow({
    id: 'camara:zero', name: 'Pessoa com zero', role: 'deputado',
    gasto: 0, gastoMensal: 0, hasExpenseData: true, alertas: 0,
  }, 100);

  assert.match(missing, /Sem dados/);
  assert.match(missing, /sem despesa observada/);
  assert.match(missing, /width:0%/);
  assert.match(zero, /R\$ 0/);
  assert.doesNotMatch(zero, /Sem dados|0 mil/);
  assert.match(zero, /width:0%/);

  state.politicianId = 'camara:no-data';
  api.citizenState.profileId = state.politicianId;
  api.citizenState.profile = {
    pessoa: { id: state.politicianId, name: 'Pessoa sem dado', role: 'deputado', party: 'PT', uf: 'SP' },
    total: null, hasExpenseData: false, expenseCount: 0,
  };
  const profile = api.profileView();
  assert.match(profile, /Sem dados/);
  assert.match(profile, /Nenhuma despesa de reembolso foi observada/);
  assert.match(profile, /Salário à parte:.*46\.366/);
  assert.match(profile, /Equipe e verba de gabinete/);
  assert.match(profile, /Projetos apresentados/);
  assert.doesNotMatch(profile, /Detalhes da amostra editorial|data-editorial-profile|data-pdf/);
  assert.doesNotMatch(profile, /citizen-months|Nenhum alerta|R\$\s?0 mil/);
  assert.match(profile, /Dados insuficientes para avaliar/);
});

test('home alert loading failures show a retry card instead of a sample fallback', async () => {
  const { api, events } = makeView({ fetchImpl: async () => { throw new Error('offline'); } });
  const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
  const loading = api.homeAlertCard();
  assert.match(loading, /Carregando/);
  await new Promise(resolve => setImmediate(resolve));
  const failed = api.homeAlertCard();
  assert.match(failed, /data-home-retry/);
  assert.doesNotMatch(failed, /radarHome|amostra|editorial/);
  const retry = { dataset: {}, hasAttribute: name => name === 'data-home-retry' };
  retry.closest = () => retry;
  events.click({ target: { closest: () => retry }, preventDefault() {} });
  assert.equal(api.citizenState.cache.has(path), false);
});

test('all federal identifiers use the same profile route and avatar URL without a local sample roster', () => {
  const { api, state } = makeView();
  assert.equal(api.citizenHasProfile('camara:513'), true);
  assert.equal(api.citizenHasProfile('senado:82'), true);
  assert.equal(api.citizenHasProfile('camara:abc'), false);
  const avatar = api.citizenAvatar({ id: 'camara:513', name: 'Deputada Nova' }, 48);
  assert.match(avatar, /https:\/\/www\.camara\.leg\.br\/internet\/deputado\/bandep\/513\.jpg/);
  assert.doesNotMatch(avatar, /undefined|Amostra editorial/);
  const snapshotPhoto = api.citizenAvatar({ id: 'camara:513', name: 'Deputada Nova', photo: 'https://example.test/photos/513.jpg' });
  assert.match(snapshotPhoto, /src="https:\/\/example\.test\/photos\/513\.jpg"/);

  api.openPolitician('123');
  assert.equal(state.view, 'profile');
  assert.equal(state.politicianId, 'camara:123');
  assert.equal(state.deputyId, '123');

  api.openPolitician('camara:987');
  assert.equal(state.view, 'profile');
  assert.equal(state.politicianId, 'camara:987');
  assert.equal(state.deputyId, '987');
});

test('the full public roster request runs with an empty query and an empty result stays explicit', async () => {
  const calls = [];
  const { api, elements } = makeView({ fetchImpl: async url => {
    calls.push(url);
    return { ok: true, async json() { return { itens: [], total: 0, cobertura: null, medias: {} }; } };
  } });
  api.loadPoliticians(false);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['/api/c/politicos?pageSize=25&page=1&ordem=nome']);
  assert.match(elements['citizen-politician-list'].innerHTML, /Ninguém encontrado/);
  assert.match(elements['citizen-politician-list'].innerHTML, /mandato em curso/);
});

test('politicians view has no editorial sample block', () => {
  const { api } = makeView();
  api.citizenState.politicians.key = 'q=&cargo=&ordem=nome';
  const html = api.politiciansView();
  assert.doesNotMatch(html, /Detalhes editoriais|amostra editorial|data-editorial-profile|data-pdf/);
});

test('legacy profile alias preserves canonical Senate identity', () => {
  const match = appSource.match(/function legacyProfileView\(\) \{[\s\S]*?\n\}/);
  assert.ok(match, 'legacy legacyProfileView compatibility function exists');
  const state = { deputyId: 'senado:77', politicianId: null };
  const context = { state, profileView() { return state.politicianId; } };
  vm.createContext(context);
  vm.runInContext(`${match[0]}\nthis.__vFicha = legacyProfileView;`, context);

  assert.equal(context.__vFicha(), 'senado:77');
  context.state.deputyId = '77';
  assert.equal(context.__vFicha(), 'camara:77');
});

test('profiles with observed expenses still receive shared sections and separate cota from pay', () => {
  const { api, state } = makeView();
  state.politicianId = 'camara:55';
  api.citizenState.profileId = state.politicianId;
  api.citizenState.profile = {
    pessoa: { id: state.politicianId, name: 'Perfil com despesas', role: 'deputado', party: 'PV', uf: 'RJ' },
    total: 80000, mediaMensal: 80000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, media: 70000, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
  };

  const profile = api.profileView();
  assert.match(profile, /Salário à parte:.*46\.366/);
  assert.match(profile, /Equipe e verba de gabinete/);
  assert.match(profile, /Cota é reembolso/);
  assert.match(profile, /subsídio bruto mensal de referência do cargo/);
  assert.doesNotMatch(profile, /Não é o salário, que é de/);
  assert.match(profile, /<a class="fchip" href="\/api\/c\/gastos\.csv\?id=camara%3A55" download>Baixar todas as notas \(CSV\)<\/a>/);
});

test('profile starts with three ordered answers and keeps the complementary details', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:55', {
    total: 80000, mediaMensal: 80000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [],
    alertas: [{ nivel: 'medio', tipo: 'valor', titulo: 'Alerta preservado', frase: 'Conferir registro.' }],
  });
  const html = api.profileView();
  const answers = [...html.matchAll(/data-profile-answer="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(answers, ['expenses', 'work', 'alerts']);
  assert.match(html, /Em 3 respostas/);
  assert.ok(html.indexOf('Quanto custa?') < html.indexOf('Trabalha?'));
  assert.ok(html.indexOf('Trabalha?') < html.indexOf('Algum alerta na cota?'));
  assert.match(html, /class="citizen-details/);
  const detailKeys = [...html.matchAll(/data-profile-section="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(detailKeys, ['expenses', 'alerts', 'votes', 'projects', 'staff', 'contact', 'sources']);
  assert.match(html, /Alerta preservado/);
});

test('profile without alerts explains which rules were checked and keeps neutral contact wording', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:56', {
    total: 80000, mediaMensal: 80000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true, meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
    coberturaAlertas: [
      { regra: 'fornecedor', ano: 2026, avaliado: true, parcial: true, periodo: 'jan–set/2026' },
      { regra: 'pico', ano: 2026, avaliados: [4, 5, 6], marcados: [], naoAvaliados: [
        { motivo: 'sem_base', texto: 'menos de 3 meses anteriores com notas no mesmo ano', meses: [1, 2, 3] },
        { motivo: 'prazo_aberto', texto: 'prazo de apresentação das notas ainda aberto na data da coleta', meses: [7, 8, 9] }] },
    ],
  });
  const html = api.profileView();
  const answer = html.slice(html.indexOf('data-profile-answer="alerts"'));
  assert.match(answer, /Nenhum alerta nos meses avaliados/);
  assert.match(answer, /avaliados abr–jun\/2026/);
  assert.match(answer, /jul–set\/2026: prazo de apresentação das notas ainda aberto/);
  assert.match(answer, /período parcial/);
  assert.match(html, /Mês acima da referência:<\/b> um mês com gasto 1,75 vez/);
  assert.match(html, /Concentração em fornecedor:<\/b> metade ou mais/);
  assert.doesNotMatch(html, /regras do painel|fora do normal|estranho/);
  assert.match(html, /Fale com ele\(a\)/);
});

test('profile offers sharing with the same three answers on the card', () => {
  const { api, state, context } = makeView();
  setProfileFixture(api, state, 'camara:57', {
    total: 80000, mediaMensal: 80000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true, meses: [], categorias: [], fornecedores: [], maiores: [],
    alertas: [{ nivel: 'medio', tipo: 'valor', titulo: 'A', frase: 'B' }], snapshotAt: '2026-10-07T12:00:00Z',
  });
  const html = api.profileView();
  assert.match(html, /data-share="image"/);
  const card = vm.runInContext('SHARE_STATE.card', context);
  assert.deepEqual(Array.from(card.rows, row => row.label), ['Cota parlamentar por mês', 'Presença no Plenário em 2026', 'Gastos incomuns na cota']);
  assert.equal(card.rows[2].values[0], '1 alerta');
  assert.match(card.footnote, /Retrato de 2026-10-07/);
});

test('profile distinguishes missing cota from an observed zero and treats a difference under ten percent as similar', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:55');
  const missing = api.profileView();
  const missingAnswer = missing.match(/<section[^>]*data-profile-answer="expenses"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(missingAnswer, /Sem dados/);
  assert.match(missingAnswer, /Ausência não significa gasto zero/);
  assert.match(missingAnswer, /Salário à parte:.*46\.366/);
  assert.doesNotMatch(missingAnswer, /R\$ 0/);

  setProfileFixture(api, state, 'camara:55', { total: 0, mediaMensal: 0, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true });
  const zero = api.profileView();
  const zeroAnswer = zero.match(/<section[^>]*data-profile-answer="expenses"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(zeroAnswer, /R\$ 0/);
  assert.doesNotMatch(zeroAnswer, /Sem dados/);

  setProfileFixture(api, state, 'camara:55', { total: 109000, mediaMensal: 109000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true, media: 100000 });
  const nearAverage = api.profileView();
  assert.match(nearAverage, /<span class="fchip citizen-verdict">Parecido com a média<\/span>/);
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
  setProfileFixture(api, state, 'camara:1');
  const html = api.profileView();
  const work = html.match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
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
  setProfileFixture(api, state, 'camara:1');
  let html = api.profileView();
  let work = html.match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Sem voto nominal identificado neste recorte/);
  assert.match(work, /2 registros só de presença ou presidência/);
  assert.doesNotMatch(work, /Votou em <b>0 de/);
  assert.match(html, /data-vote="secret"><b>Presença registrada · voto secreto<\/b>/);
  assert.match(html, /data-vote="chair"><b>presidiu<\/b>/);
  assert.match(html, /data-vote="missing"><b>Sem registro importado<\/b>/);
  assert.doesNotMatch(work, /Não votou|não compareceu|faltou à votação/);

  context.DATA.votacoes = [{ id: 'not-voted', data: '2026-09-04', titulo: 'Ausência publicada', secreta: false }];
  context.DATA.votosCompletos = { 'not-voted': [[1, 'Pessoa Parlamentar', 'PT', 'SP', 'Não votou']] };
  html = api.profileView();
  work = html.match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Votou em <b>0 de 1<\/b> votações do Placar/);
  assert.match(html, /data-vote="not-voted"><b>não votou<\/b>/);
});

test('Senate work answer stays unavailable even when a Câmara record has the same number', () => {
  const { api, state, context } = makeView();
  context.DATA.presencaTodos = [{ id: 77, dias: 10, presente: 8, falta: 2, justificadas: 0 }];
  context.DATA.votacoes = [{ id: 'camara-77', data: '2026-09-01', titulo: 'Votação da Câmara', secreta: false }];
  context.DATA.votosCompletos = { 'camara-77': [[77, 'Homônimo numérico', 'PT', 'SP', 'Sim']] };
  setProfileFixture(api, state, 'senado:77');
  const html = api.profileView();
  const work = html.match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /Presença do Senado sem registro importado/);
  assert.match(html, /Votos nominais do Senado ainda não disponíveis neste recorte/);
  assert.doesNotMatch(work, /8\/10|201 de 250|Votou em|votações do Placar · 1/);
});

test('Senate profile shows fetched votes with skeletons and never counts parliamentary activity as a vote', async () => {
  let release;
  const { api, state, context } = makeView({ fetchImpl: () => new Promise(resolve => { release = resolve; }) });
  context.DATA.senado = { sobDemanda: true };
  setProfileFixture(api, state, 'senado:77');
  assert.match(api.profileView(), /data-profile-answer="work"[\s\S]*?Carregando/);
  release({ ok: true, json: async () => ({
    presenca: { status: 'unavailable', items: [] },
    votacoes: { status: 'imported', items: ['Sim', 'Atividade parlamentar', 'Presente – Não registrou voto', null].map((vote, n) => ({
      id: `senado:${n}`, titulo: `Votação ${n}`, data: '2026-09-01', sourceUrl: 'https://legis.senado.leg.br/voto/' + n,
      rows: vote === null ? [] : [['senado:77', 'Senador', 'PT', 'SP', vote]],
    })) },
  }) });
  await new Promise(resolve => setImmediate(resolve));
  const html = api.profileView();
  const work = html.match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
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
  setProfileFixture(api, state, 'senado:77');
  api.profileView();
  await new Promise(resolve => setImmediate(resolve));
  const work = api.profileView().match(/<section[^>]*data-profile-answer="work"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(work, /9<small> sessões/);
  assert.match(work, /12 listas de sessões consultadas/);
  assert.match(work, /Faltas e justificativas não apuradas/);
  assert.doesNotMatch(work, /75%|Justificada 0|Falta 3|média do Senado/);
  setProfileFixture(api, state, 'senado:78');
  assert.match(api.profileView(), /Presença do Senado sem registro importado/);
});

test('three-answer alert shows the first alert in API order, without a severity ranking, and details keep every alert', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:55', {
    total: 120000, mediaMensal: 120000, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, media: 100000, hasExpenseData: true,
    alertas: [
      { nivel: 'info', tipo: 'valor', titulo: 'Primeiro alerta informativo', frase: 'Informação inicial.' },
      { nivel: 'alto', tipo: 'valor', titulo: 'Primeiro alerta alto', frase: 'Maior gravidade, primeiro.' },
      { nivel: 'medio', tipo: 'valor', titulo: 'Alerta médio', frase: 'Gravidade média.' },
      { nivel: 'alto', tipo: 'valor', titulo: 'Segundo alerta alto', frase: 'Mesmo nível, depois.' },
    ],
  });
  const html = api.profileView();
  const answer = html.match(/<section[^>]*data-profile-answer="alerts"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(answer, /4 alertas/);
  assert.match(answer, /Primeiro alerta informativo/);
  assert.doesNotMatch(answer, /Primeiro alerta alto|Alerta médio|Segundo alerta alto/);
  const details = html.slice(html.indexOf('data-profile-section="alerts"'));
  const order = ['Primeiro alerta informativo', 'Primeiro alerta alto', 'Alerta médio', 'Segundo alerta alto'];
  assert.ok(order.every(title => details.includes(title)));
  assert.deepEqual(order.map(title => details.indexOf(title)), [...order.map(title => details.indexOf(title))].sort((a, b) => a - b));
});

test('profile header shows the 2026 election result only for a unique TSE match', () => {
  const { api, state, context } = makeView();
  context.DATA.perfis = { profiles: {
    'camara:55': { role: 'deputado', eleicao2026: { status: 'encontrada', cargo: 'SENADOR', uf: 'SP', situacao: 'ELEITO', dataEleicao: '2026-10-04' } },
    'camara:56': { role: 'deputado', eleicao2026: { status: 'sem-correspondencia' } },
  } };
  setProfileFixture(api, state, 'camara:55');
  assert.match(api.profileView(), /<span class="pill citizen-election" data-tone="ok"><i><\/i>Eleito\(a\) senador\(a\) em 2026<\/span>/);
  setProfileFixture(api, state, 'camara:56');
  const withoutMatch = api.profileView();
  assert.doesNotMatch(withoutMatch, /citizen-election/);
});

test('Senate profiles show source snapshot metadata safely and omit empty fields', () => {
  const { api, state } = makeView();
  state.politicianId = 'senado:current';
  api.citizenState.profileId = state.politicianId;
  api.citizenState.profile = {
    pessoa: {
      id: state.politicianId, name: 'Dora Senadora', role: 'senador',
      position: 'Mandato <titular> & participação',
      employmentStatus: 'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular',
      sourceUrl: 'https://senado.example.test/lista?x=" onmouseover="alert(1)',
    },
    total: null, hasExpenseData: false, expenseCount: 0,
  };

  const profile = api.profileView();
  assert.match(profile, /data-profile-section="mandate"/);
  assert.match(profile, /Mandato &lt;titular&gt; &amp; participação/);
  assert.match(profile, /Exercício de 05\/08\/2026 a 06\/10\/2026 — Retorno do titular/);
  assert.match(profile, /href="https:\/\/senado\.example\.test\/lista\?x=%22%20onmouseover=%22alert\(1\)" target="_blank"/);
  assert.doesNotMatch(profile, /href="[^"]*" onmouseover=/);
  assert.doesNotMatch(profile, /Busca avançada|data-public-/);
  assert.doesNotMatch(profile, /gastos\.csv/);

  state.politicianId = 'senado:without-metadata';
  api.citizenState.profileId = state.politicianId;
  api.citizenState.profile = {
    pessoa: { id: state.politicianId, name: 'Sem Metadados', role: 'senador' },
    total: null, hasExpenseData: false, expenseCount: 0,
  };
  assert.doesNotMatch(api.profileView(), /Na fotografia da fonte|Fonte do Senado/);
});

test('a stale roster response cannot overwrite newer coverage counts', async () => {
  const pending = [];
  const fetchImpl = url => new Promise(resolve => pending.push({ url, resolve }));
  const { api, elements } = makeView({ fetchImpl });
  api.citizenState.politicians.query = 'older query';
  api.loadPoliticians(false);
  api.citizenState.politicians.query = 'newer query';
  api.loadPoliticians(false);

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
  const summary = elements['citizen-politician-summary'].innerHTML;
  assert.match(summary, /9 deputados/);

  stale.resolve(payload(3, 1));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements['citizen-politician-summary'].innerHTML, summary);
});

test('deputy profile explains why the quota in the mandate cost differs from the quota average', () => {
  const { api } = makeView();
  const profile = { pessoa: { id: 'camara:1', role: 'deputado' }, mediaMensal: 30243.22, periodo: { inicio: '2023-02', fim: '2026-09', meses: 41 } };
  const cost = { usedMonths: Array.from({ length: 39 }, (_, i) => `p${i}`), parts: { quota: { usedMonthsAverageCents: 3114493 } } };
  const note = api.profileQuotaDifferenceNote(profile, cost);
  assert.match(note, /31\.144,93 por mês porque usa só os 39 meses/);
  assert.match(note, /todos os 41 meses com notas/);
  assert.equal(api.profileQuotaDifferenceNote(profile, null), '');
  assert.equal(api.profileQuotaDifferenceNote({ ...profile, mediaMensal: 31144.93 }, cost), '');
});

test('senators whose mandate began before 2023 are told the quota counts from February 2023', () => {
  const { api } = makeView();
  assert.match(api.profileMandateStartNote({ exercicio: 'Exercício sem término informado desde 01/02/2019' }),
    /O mandato começou em fevereiro de 2019; antes de fev\/2023 a cota não entra aqui/);
  assert.equal(api.profileMandateStartNote({ exercicio: 'Exercício sem término informado desde 01/02/2023' }), '');
  assert.equal(api.profileMandateStartNote(null), '');
});

test('profile with notes but nothing evaluable says data are insufficient instead of "no alert"', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:58', {
    total: 80000, mediaMensal: 80000, periodo: { inicio: '2024-01', fim: '2024-03', meses: 3 }, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [], coberturaAlertas: [],
  });
  const answer = api.profileView().match(/<section[^>]*data-profile-answer="alerts"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(answer, /Dados insuficientes para avaliar/);
  assert.doesNotMatch(answer, /Nenhum alerta/);
});

test('year-end peak keeps the alert and adds the yearly balance context', () => {
  const { api } = makeView();
  const alert = { tipo: 'pico', mes: 12, periodo: '2025-12', valor: 40000, referencia: 4000, titulo: 'Mês acima da referência: dezembro',
    frase: 'Em dezembro...', meses: [{ mes: 12 }], serie: [{ mes: 11, valor: 4000 }, { mes: 12, valor: 40000 }], fimDeAno: [12], pessoa: {} };
  const html = api.alertCard(alert);
  assert.match(html, /Mês acima da referência/);
  assert.match(html, /expira em 31 de dezembro\. Dezembro pode incluir gastos feitos com esse saldo/);
  assert.doesNotMatch(api.alertCard({ ...alert, fimDeAno: [] }), /expira em 31 de dezembro\. Dezembro/);
});

test('single-month peak shows reference and month bars with the difference written, without a legend', () => {
  const { api } = makeView();
  const serie = [
    ...[6, 7, 8, 9, 10, 11, 12].map(mes => ({ ano: 2025, mes, valor: 36000, estado: 'evaluated' })),
    ...[1, 2, 3, 4, 5].map(mes => ({ ano: 2026, mes, valor: 37000, estado: 'evaluated' })),
    { ano: 2026, mes: 6, valor: 69765, estado: 'flagged' },
    { ano: 2026, mes: 7, valor: 42100, estado: 'prazo_aberto' }, { ano: 2026, mes: 8, valor: null, estado: 'sem_notas' },
  ];
  const alert = { tipo: 'pico', mes: 6, ano: 2026, periodo: '2026-06', base: 'rolling12', referencia: 36719, titulo: 'Mês acima da referência: junho de 2026',
    frase: '...', meses: [{ ano: 2026, mes: 6, valor: 69765, referencia: 36719, vezes: 1.9 }], serie, pessoa: { id: 'camara:1' } };
  const html = api.alertCard(alert);
  assert.match(html, /Junho ficou R\$ 33 mil acima da referência <span>\(\+90%\)<\/span>/);
  assert.match(html, /Referência · jun\/2025–mai\/2026[\s\S]*<b>R\$ 36,7 mil<\/b>/);
  assert.match(html, /Junho de 2026[\s\S]*<b>R\$ 69,8 mil<\/b>[\s\S]*R\$ 33 mil acima \(\+90%\)/);
  assert.match(html, /Referência: mediana dos 12 meses anteriores\./);
  assert.doesNotMatch(html, /citizen-peak-key|acima da referência<\/span><span>/);  // sem legenda
  // Meses seguintes só no histórico, marcados como provisórios; mês sem notas não vira zero.
  const [card, history] = html.split('<details class="citizen-peak-history">');
  assert.doesNotMatch(card, /jul\/2026|42\.100/);
  assert.match(history, /Ver histórico e notas/);
  assert.match(history, /citizen-peak-col provisional" title="jul\/2026: R\$ 42\.100 \(provisório: prazo das notas aberto\)"/);
  assert.match(history, /title="ago\/2026: sem notas"/);
  assert.match(history, /mediana R\$ 36,7 mil/);
});

test('multi-month peak lists each month against its own reference', () => {
  const { api } = makeView();
  const alert = { tipo: 'pico', mes: 4, ano: 2026, periodo: '2026-04', base: 'rolling12', referencia: 3460, titulo: 'Meses acima da referência: abril a maio', frase: '...',
    meses: [{ ano: 2026, mes: 4, valor: 43997, referencia: 3460, vezes: 12.7 }, { ano: 2026, mes: 5, valor: 137821, referencia: 23728, vezes: 5.8 }],
    serie: [{ ano: 2026, mes: 3, valor: 3000, estado: 'evaluated' }, { ano: 2026, mes: 4, valor: 43997, estado: 'flagged' }, { ano: 2026, mes: 5, valor: 137821, estado: 'flagged' }], pessoa: {} };
  const html = api.alertCard(alert);
  assert.match(html, /Abril a maio ficaram acima da referência/);
  assert.match(html, /Referência de abril/);
  assert.match(html, /Maio de 2026[\s\S]*R\$ 114,1 mil acima \(\+481%\) sobre a referência de R\$ 23,7 mil/);
  assert.equal((html.match(/citizen-peak-bar flagged/g) || []).length, 2);
});

function senateFixture() {
  const month = (remuneration, office, extra = {}) => ({ exercise: 'em_exercicio', remunerationCents: remuneration, remunerationReason: remuneration === null ? 'outra_lotacao' : null,
    officeCents: office, officeReason: office === null ? 'nao_identificado' : null, officePeople: office === null ? null : 20, ...extra });
  return {
    id: 'senado:1', office: 'Fulano', periodStart: '2026-06', periodEnd: '2026-09', exerciseSource: 'https://legis.senado.leg.br/dadosabertos/senador/{codigo}/mandatos.json',
    sources: [{ competence: '2026-07', url: 'https://www.senado.leg.br/transparencia/LAI/secrh/x_202607.csv' }],
    months: {
      '2026-06': { exercise: 'fora', remunerationCents: null, remunerationReason: 'fora_do_exercicio', officeCents: null, officeReason: 'fora_do_exercicio', officePeople: null },
      '2026-07': month(4636619, 30000000),
      '2026-08': month(4636619, 20000000),
      '2026-09': month(null, 25000000),
    },
  };
}
const senateQuota = { meses: [{ year: 2026, month: 7, valor: 40000 }, { year: 2026, month: 8, valor: 20000 }, { year: 2026, month: 9, valor: 30000 }] };

test('senate cost card averages only months with all three parts and never compares with deputies', () => {
  const { api } = makeView();
  const html = api.senateCostAnswer(senateFixture(), senateQuota);
  assert.match(html, /Senado · despesas identificadas do mandato/);
  // jul e ago completos: (46.366,19 + 300.000 + 40.000 + 46.366,19 + 200.000 + 20.000) / 2
  assert.match(html, /Em média<\/span><b class="mono">R\$\s?326\.366,19<\/b>/);
  assert.match(html, /2 meses com as três partes identificadas, de 3 no recorte/);
  assert.match(html, /Não compare com o custo de deputados\(as\)/);
  assert.doesNotMatch(html, /Custa em média|custo do mandato/);
});

test('senate monthly history shows partial totals and the reason for each gap', () => {
  const { api } = makeView();
  const html = api.senateCostDetails(senateFixture(), senateQuota);
  assert.match(html, /data-cost-month="2026-09"[\s\S]*Total parcial: <b class="mono">R\$\s?280\.000,00<\/b> — remuneração do\(a\) senador\(a\) não identificada/);
  assert.match(html, /Não identificada no próprio gabinete \(pode estar na Mesa ou numa liderança\)/);
  assert.match(html, /data-cost-month="2026-07"[\s\S]*Total do mês: <b class="mono">R\$\s?386\.366,19<\/b>/);
  assert.match(html, /\(20 pessoas\)/);
  assert.doesNotMatch(html, /data-cost-month="2026-06"/);  // fora do exercício e sem dado: fora do histórico
});

test('senate absence says "not identified" unless the exercise history confirms it', () => {
  const { api } = makeView();
  const cost = senateFixture();
  cost.months['2026-09'] = { exercise: 'em_exercicio', remunerationCents: null, remunerationReason: 'nao_identificado', officeCents: null, officeReason: 'nao_identificado', officePeople: null };
  const html = api.senateCostDetails(cost, senateQuota);
  const september = html.split('data-cost-month="2026-09"')[1].split('data-cost-month=')[0];
  assert.match(september, /Não identificado nesta fonte/);
  assert.doesNotMatch(september, /Fora do exercício/);
  const noOffice = api.senateCostAnswer({ ...cost, office: null, months: { '2026-09': { exercise: 'em_exercicio', remunerationCents: null, remunerationReason: 'sem_lotacao_propria', officeCents: null, officeReason: 'sem_lotacao_propria' } } }, senateQuota);
  assert.match(noOffice, /Sem gabinete com o próprio nome no arquivo de remuneração do Senado: remuneração e equipe não identificadas/);
  assert.doesNotMatch(noOffice, /Em média/);
});

test('quota-only card says it is not comparable with the deputy mandate cost', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:59', {
    total: 80000, mediaMensal: 40000, periodo: { inicio: '2026-01', fim: '2026-02', meses: 2 }, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
  });
  const answer = api.profileView().match(/<section[^>]*data-profile-answer="expenses"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(answer, /Só a cota parlamentar\./);
  assert.match(answer, /Não compare com o custo de deputados\(as\) que soma salário, auxílios, cota e gabinete/);
});

test('senate alert cards point to the official breakdown and say the document image is unavailable', () => {
  const { api } = makeView();
  const html = api.alertCard({ tipo: 'fornecedor', periodo: '2025', valor: 1, parte: 0.6, fornecedor: 'X', titulo: 'T', frase: 'F', pessoa: {},
    fontesOficiais: [{ label: 'Escritório · 2025', url: 'https://www6g.senado.leg.br/transparencia/sen/1/ceaps/1/?ano=2025' }],
    notaDocumento: 'Análise dos registros publicados; imagem do documento não disponível nesta base.' });
  assert.match(html, /Detalhamento oficial: <a href="https:\/\/www6g\.senado\.leg\.br\/transparencia\/sen\/1\/ceaps\/1\/\?ano=2025"/);
  assert.match(html, /imagem do documento não disponível nesta base/);
});
