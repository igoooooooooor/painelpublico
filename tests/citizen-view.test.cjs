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
const profileSource = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'scripts', 'dates.js'), 'utf8') + '\n' + fs.readFileSync(
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
  vm.runInContext(profileSource + '\n' + profileCostSource + '\n' + senateCostSource + '\n' + shareSource + '\n' + source + '\nthis.__api = { profileTenureLabel, senateCostAnswer, senateCostDetails, senateCostMonths, citizenState, openPolitician, citizenAvatar, citizenHasProfile, politicianRow, politicianCoverageHTML, politicianCoverageNotesHTML, loadPoliticians, politiciansView, homeAlertCard, profileData, profileSectionsHTML, profileAttendanceCard, profileVoteCountHTML, profileView, profileQuotaDifferenceNote, profileMandateStartNote, alertCard, skel };', context);
  context.votesForPerson = id => context.profileVotes(id).filter(record => record?.vote);
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

// Conteúdo de uma seção recolhível de "Mais detalhes".
// Cartão de presença em "Como trabalha".
// Votos de um(a) deputado(a) no catálogo do Placar, como /api/c/votes/person devolve.
const setChamberVotes = (context, id, items) => {
  vm.runInContext('CHAMBER_PERSON_VOTES', context).data[id] = { available: true, items };
};
const placarVote = (id, date, title, vote) => ({ id, date, title, proposition: 'PL 1/2026', type: 'PL', outcome: 'approved', vote, detailsAvailable: true });
const presenceCard = html => html.match(/<article class="card profile-work-card profile-presence-card">[\s\S]*?<\/article>/)?.[0] || '';
const profileSection = (html, key) => html.match(new RegExp(`<section[^>]*data-profile-section="${key}"[\\s\\S]*?</section>`))?.[0] || '';

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

  assert.match(missing, /Sem custo/);
  assert.match(missing, /sem despesa de cota observada/);
  assert.match(missing, /width:0%/);
  assert.match(zero, /cota R\$ 0/);
  assert.doesNotMatch(zero, /0 mil/);
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

test('roster rows show the monthly cost of the own house, with the quota apart', () => {
  const { api } = makeView();
  api.citizenState.politicians.averageCost = { senador: { media: 300000 }, deputado: { media: 200000 } };
  const row = api.politicianRow({ id: 'senado:70', name: 'Renan Calheiros', role: 'senador', custoMensal: 375869.84, custoMeses: 43,
    gastoMensal: 27451.33, hasExpenseData: true, alertas: 0 }, 400000);
  assert.match(row, /R\$ 376 mil<\/b><small>\/mês<\/small>/);
  assert.match(row, /média de 43 meses · cota R\$ 27 mil · acima da média do Senado/);
  assert.match(row, /width:93\.9/);  // 375,9 mil sobre a escala de 400 mil do Senado
});

test('ordering by cost with all houses shows Câmara and Senado in separate blocks', async () => {
  const people = role => Array.from({ length: 10 }, (_, i) => ({ id: `${role === 'senador' ? 'senado' : 'camara'}:${i}`, name: `P${i}`, role,
    custoMensal: 100000 - i, custoMeses: 42, gastoMensal: 30000, hasExpenseData: true, alertas: 0 }));
  const calls = [];
  const { api } = makeView({ fetchImpl: async url => { calls.push(String(url)); const role = String(url).includes('cargo=senador') ? 'senador' : 'deputado';
    return { ok: true, json: async () => ({ itens: people(role), total: role === 'senador' ? 81 : 513, medias: {}, custoMedias: {}, cobertura: null }) }; } });
  Object.assign(api.citizenState.politicians, { order: 'gasto', role: '', query: '', key: '' });
  api.loadPoliticians(false);
  await new Promise(resolve => setTimeout(resolve, 0)); await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
  assert.ok(calls.every(url => /ordem=gasto/.test(url) && /pageSize=10/.test(url)));
  const html = api.politiciansView();
  assert.match(html, /Câmara · quem mais custa por mês[\s\S]*Senado · quem mais custa por mês/);
  assert.match(html, /data-politician-role="deputado">Ver todos os 513 deputados\(as\)/);
  assert.match(html, /data-politician-role="senador">Ver todos os 81 senadores\(as\)/);
});

test('senate participation in nominal votes is summarized without calling missing rows absences', () => {
  const { context } = makeView();
  const participation = { sessions: 92, counts: { participou: 57, presente_sem_voto: 12, ausencia_com_motivo: 22, nao_compareceu: 1, sem_registro: 0, outro: 0 },
    reasons: { 'Atividade parlamentar': 18, 'Licença saúde': 4 }, period: { start: '2023-02-01', end: '2026-10-09' },
    leaves: [{ start: '2026-07-15', end: '2026-07-15', type: 'Missão política ou cultural de interesse parlamentar' },
      { start: '2025-03-01', end: '2025-03-10', type: 'Licença Saúde (até a 120 dias)' }] };
  const summary = vm.runInContext('senateParticipationSummary', context)(participation);
  assert.match(summary, /votou em 57 de 92 sessões em exercício · 22 ausências com motivo · 12 presente sem votar · 1 sem comparecer/);
  const detail = vm.runInContext('senateParticipationHTML', context)(participation);
  assert.match(detail, /Em 92 sessões com votação nominal pública em que estava em exercício \(01\/02\/2023 a 09\/10\/2026\)/);
  assert.match(detail, /Licença Saúde \(até a 120 dias\)<\/span><b class="mono">1× · 10 dias/);
  assert.match(detail, /“sem registro” não vira falta/);
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
  const answers = [...html.matchAll(/href="#profile-([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(answers, ['cost', 'work', 'alerts']);
  assert.match(html, /aria-label="Resumo da ficha"/);
  assert.ok(html.indexOf('Quanto custa?') < html.indexOf('Aparece para trabalhar?'));
  assert.ok(html.indexOf('Aparece para trabalhar?') < html.indexOf('Algum alerta na cota?'));
  assert.match(html, /class="citizen-details/);
  const detailKeys = [...html.matchAll(/data-profile-section="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(detailKeys, ['expenses', 'alerts', 'votes', 'projects', 'staff', 'contact', 'sources']);
  assert.match(html, /Alerta preservado/);
});

test('Senate work answer keeps attendance in 2026 and labels votes from their collected range', () => {
  const { api, context } = makeView();
  const endDate = '2026-10-08';
  context.profileSenateEnsure = () => {};
  context.profileSenateLoading = () => false;
  context.profilePresenceRows = () => [];
  context.profileSenateSource = section => section === 'votacoes' ? ({
    status: 'partial', startDate: '2023-02-01', endDate,
    sources: [
      { year: 2023, status: 'imported', sourceUrl: 'https://senado.example.test/votes/2023', startDate: '2023-02-01', endDate: '2023-12-31' },
      { year: 2024, status: 'unavailable', sourceUrl: null, startDate: null, endDate: null },
      { year: 2026, status: 'imported', sourceUrl: 'https://senado.example.test/votes/2026', startDate: '2026-01-01', endDate },
    ],
  }) : null;
  context.profileVotes = () => [{ vote: { id: 'senado:V1', data: '2023-02-01' }, recordedVote: 'Sim' }];
  context.votesForPerson = context.profileVotes;
  const shared = { id: 'senado:9', person: { role: 'senador', name: 'Senadora' }, presence: null, registeredPresence: null };
  const html = api.profileAttendanceCard(shared) + api.profileVoteCountHTML(shared);
  assert.match(html, /Presença no Plenário · 2026/);
  assert.match(html, /Voto identificado em <b>1 de 1<\/b> votações do Senado com registro individual · de 01\/02\/2023 a 08\/10\/2026/);
  assert.doesNotMatch(html, /Presença no Plenário · 2023|Presença no Plenário ·.*10\/2026/);

  context.profileSenateSource = section => section === 'votacoes' ? ({ status: 'unavailable' }) : null;
  const unavailable = api.profileVoteCountHTML(shared);
  assert.match(unavailable, /Dados de votações nominais do Senado indisponíveis neste recorte/);
  assert.doesNotMatch(unavailable, /Voto identificado em <b>0|0 de 0/);
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
  const answer = html.slice(html.indexOf('id="profile-alerts"'));
  assert.match(answer, /Nenhum alerta nos períodos avaliados/);
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
  assert.deepEqual(Array.from(card.rows, row => row.label), ['Cota parlamentar por mês', 'Presença no Plenário · mandato', 'Gastos incomuns na cota']);
  assert.equal(card.rows[2].values[0], '1 alerta');
  assert.match(card.footnote, /Retrato de 07\/10\/2026/);
});

test('profile distinguishes missing cota from an observed zero and treats a difference under ten percent as similar', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:55');
  const missing = api.profileView();
  const missingAnswer = missing.match(/<div[^>]*data-profile-expense-details[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(missingAnswer, /Sem dados/);
  assert.match(missingAnswer, /Ausência não significa gasto zero/);
  assert.match(missingAnswer, /Salário à parte:.*46\.366/);
  assert.doesNotMatch(missingAnswer, /R\$ 0/);

  setProfileFixture(api, state, 'camara:55', { total: 0, mediaMensal: 0, periodo: { inicio: '2026-01', fim: '2026-01', meses: 1 }, hasExpenseData: true });
  const zero = api.profileView();
  const zeroAnswer = zero.match(/<div[^>]*data-profile-expense-details[\s\S]*?<\/section>/)?.[0] || '';
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
  setChamberVotes(context, 'camara:1', [
    placarVote('1-1', '2026-09-01', 'Votação com sim', 'Sim'),
    placarVote('2-1', '2026-09-02', 'Sem linha individual', null),
    placarVote('3-1', '2023-03-03', 'Abstenção em 2023', 'Abstenção'),
  ]);
  setProfileFixture(api, state, 'camara:1');
  const html = api.profileView();
  const work = presenceCard(html);
  assert.match(work, /201<\/b><span>de 250 dias/);
  assert.match(work, /média da Câmara: 80%/);
  assert.match(work, /Perto da média/);
  // Sem linha da pessoa a votação conta no total, com o motivo em aberto; 2023 também entra (mandato inteiro).
  assert.match(profileSection(html, 'votes'), /Votou em <b>2 de 3<\/b> votações do Placar/);
  assert.match(profileSection(html, 'votes'), /Em 1 votação não há registro individual na lista oficial: pode ser ausência, licença ou período fora do mandato/);
  assert.match(html, /Sem registro importado[\s\S]*Sem linha individual/);
  assert.match(profileSection(html, 'votes'), /data-vote="3-1"><b>abstenção<\/b>/);
  assert.match(html, /Presença em voto secreto e quem presidiu aparecem à parte/);
});

test('chairing is shown as a record, not a nominal vote or an inferred absence', () => {
  const { api, state, context } = makeView();
  setChamberVotes(context, 'camara:1', [
    placarVote('1-1', '2026-09-02', 'Presidência da sessão', 'Presidiu'),
    placarVote('2-1', '2026-09-03', 'Sem linha individual', null),
  ]);
  setProfileFixture(api, state, 'camara:1');
  const html = api.profileView();
  const votes = profileSection(html, 'votes');
  assert.match(votes, /Sem voto nominal identificado neste recorte/);
  assert.match(votes, /1 registro só de presença ou presidência/);
  assert.doesNotMatch(votes, /Votou em <b>0 de/);
  assert.match(html, /data-vote="1-1"><b>presidiu<\/b>/);
  assert.match(html, /data-vote="2-1"><b>Sem registro importado<\/b>/);
  assert.doesNotMatch(presenceCard(html), /Não votou|não compareceu|faltou à votação/);
});

test('chamber votes cover the whole Placar catalog, ten at a time, with a skeleton while loading', () => {
  const { api, state, context } = makeView();
  setChamberVotes(context, 'camara:1', Array.from({ length: 12 }, (_, n) => placarVote(`${n + 1}-1`, `2024-0${(n % 9) + 1}-01`, `Votação ${n + 1}`, 'Sim')));
  setProfileFixture(api, state, 'camara:1');
  const votes = profileSection(api.profileView(), 'votes');
  assert.match(votes, /Votações do Placar · texto principal de PL, PLP e PEC desde fev\/2023 · 12/);
  assert.equal((votes.match(/data-vote="\d+-1"/g) || []).length, 10);
  assert.match(votes, /Mostrar mais votações \(2\)/);
  vm.runInContext('CHAMBER_PERSON_VOTES', context).pending.add('camara:2');
  setProfileFixture(api, state, 'camara:2');
  assert.match(profileSection(api.profileView(), 'votes'), /Carregando/);
});

test('Senate work answer stays unavailable even when a Câmara record has the same number', () => {
  const { api, state, context } = makeView();
  context.DATA.presencaTodos = [{ id: 77, dias: 10, presente: 8, falta: 2, justificadas: 0 }];
  context.DATA.votacoes = [{ id: 'camara-77', data: '2026-09-01', titulo: 'Votação da Câmara', secreta: false }];
  context.DATA.votosCompletos = { 'camara-77': [[77, 'Homônimo numérico', 'PT', 'SP', 'Sim']] };
  setProfileFixture(api, state, 'senado:77');
  const html = api.profileView();
  const work = presenceCard(html);
  assert.match(work, /Sem registro de presença/);
  assert.match(html, /Votos nominais do Senado ainda não disponíveis neste recorte/);
  assert.doesNotMatch(work, /8\/10|201 de 250|Votou em|votações do Placar · 1/);
  assert.doesNotMatch(profileSection(html, 'votes'), /Votou em|votações do Placar · 1/);
});

test('Senate profile shows fetched votes with skeletons and never counts parliamentary activity as a vote', async () => {
  let release;
  const { api, state, context } = makeView({ fetchImpl: () => new Promise(resolve => { release = resolve; }) });
  context.DATA.senado = { sobDemanda: true };
  setProfileFixture(api, state, 'senado:77');
  assert.match(profileSection(api.profileView(), 'votes'), /Carregando/);
  release({ ok: true, json: async () => ({
    presenca: { status: 'unavailable', items: [] },
    votacoes: { status: 'partial', startDate: '2023-02-01', endDate: '2026-10-08', sources: [
      { year: 2023, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2023', startDate: '2023-02-01', endDate: '2023-12-31' },
      { year: 2024, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2024', startDate: '2024-01-01', endDate: '2024-12-31' },
      { year: 2025, status: 'unavailable', sourceUrl: null, startDate: null, endDate: null },
      { year: 2026, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2026', startDate: '2026-01-01', endDate: '2026-10-08' },
    ], items: ['Sim', 'Atividade parlamentar', 'Presente – Não registrou voto', null].map((vote, n) => ({
      id: `senado:${n}`, titulo: `Votação ${n}`, data: ['2023-02-01', '2024-06-15', '2026-01-03', '2026-10-08'][n], sourceUrl: 'https://legis.senado.leg.br/voto/' + n,
      rows: vote === null ? [] : [['senado:77', 'Senador', 'PT', 'SP', vote]],
    })) },
  }) });
  await new Promise(resolve => setImmediate(resolve));
  const html = api.profileView();
  const work = presenceCard(html);
  assert.match(profileSection(html, 'votes'), /Voto identificado em <b>1 de 3<\/b> votações do Senado com registro individual/);
  assert.match(work, /Sem registro de presença/);
  assert.doesNotMatch(work, /class="huge"|0%|média da Câmara/);
  assert.match(profileSection(html, 'votes'), /Voto identificado em <b>1 de 3<\/b> votações do Senado com registro individual · de 01\/02\/2023 a 08\/10\/2026/);
  const voteDetails = html.match(/<section[^>]*data-profile-section="votes"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(voteDetails, /Votações nominais do Senado · de 01\/02\/2023 a 08\/10\/2026 · 4/);
  assert.match(voteDetails, /Votação 0/);
  assert.match(voteDetails, /Votação 3/);
  assert.doesNotMatch(voteDetails, /Votações nominais do Senado · 2026/);
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
  const work = presenceCard(api.profileView());
  assert.match(work, /9<\/b><span>sessões com presença registrada/);
  assert.match(work, /12 listas consultadas/);
  assert.match(work, /Faltas e justificativas não apuradas/);
  assert.doesNotMatch(work, /75%|Justificada 0|Falta 3|média do Senado/);
  setProfileFixture(api, state, 'senado:78');
  assert.match(presenceCard(api.profileView()), /Sem registro de presença/);
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
  const answer = html.match(/<a[^>]*href="#profile-alerts"[\s\S]*?<\/a>/)?.[0] || '';
  assert.match(answer, /4<small> alertas/);
  assert.match(answer, /Primeiro alerta informativo/);
  assert.doesNotMatch(answer, /Primeiro alerta alto|Alerta médio|Segundo alerta alto/);
  const details = html.slice(html.indexOf('id="profile-alerts"'), html.indexOf('class="profile-detail-area"'));
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
  const answer = api.profileView().match(/<a[^>]*href="#profile-alerts"[\s\S]*?<\/a>/)?.[0] || '';
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
  assert.match(html, /Despesas identificadas · Senado/);
  // jul e ago completos: (46.366,19 + 300.000 + 40.000 + 46.366,19 + 200.000 + 20.000) / 2
  assert.match(html, /Em média<\/span><b class="mono">R\$ 326 mil<\/b>[\s\S]*Valor exato: <span class="mono">R\$\s?326\.366,19<\/span>/);
  assert.match(html, /2 meses com as três partes identificadas, de 3 no recorte/);
  assert.doesNotMatch(html, /reajustado/);  // mesmo subsídio nos meses da média
  const raised = senateFixture();
  raised.months['2026-07'].remunerationCents = 4400852;
  assert.match(api.senateCostAnswer(raised, senateQuota), /Média do período, que inclui reajustes do subsídio\. Valor atual: R\$\s?46\.366,19, pago desde ago\/2026/);
  assert.match(api.senateCostDetails(senateFixture(), senateQuota), /Não compare com o custo de deputados\(as\)/);
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

test('profile shows how long the person has been in office without interruption', () => {
  const { api } = makeView();
  assert.match(api.profileTenureLabel({ tenure: { house: 'camara', since: '2007-02-01' } }), />Na Câmara desde 2007</);
  assert.match(api.profileTenureLabel({ tenure: { house: 'senado', since: '2019-02-01' } }), /title="Sem interrupção desde 01\/02\/2019[^"]*">No Senado desde 2019</);
  assert.equal(api.profileTenureLabel({ tenure: null }), '');
  assert.equal(api.profileTenureLabel({ tenure: { house: 'senado', since: '2019' } }), '');
});

test('quota-only card says it is not comparable with the deputy mandate cost', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:59', {
    total: 80000, mediaMensal: 40000, periodo: { inicio: '2026-01', fim: '2026-02', meses: 2 }, hasExpenseData: true,
    meses: [], categorias: [], fornecedores: [], maiores: [], alertas: [],
  });
  const answer = api.profileView().match(/<div[^>]*data-profile-expense-details[\s\S]*?<\/section>/)?.[0] || '';
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

test('redesigned profile keeps real quota totals, suppliers and all alerts in the page', () => {
  const { api, state } = makeView();
  setProfileFixture(api, state, 'camara:55', {
    total: 123456, mediaMensal: 61728, expenseCount: 17,
    periodo: { inicio: '2026-01', fim: '2026-02', meses: 2 }, hasExpenseData: true,
    categorias: [{ nome: 'Categoria da fonte', valor: 123456 }],
    fornecedores: [{ name: 'Fornecedor da fonte', valor: 123456, notas: 17 }],
    alertas: [
      { tipo: 'valor', titulo: 'Registro mais recente', frase: 'Conferir registro recente.', periodo: '2026-02' },
      { tipo: 'valor', titulo: 'Registro anterior', frase: 'Conferir registro anterior.', periodo: '2026-01' },
    ],
    coberturaAlertas: [{ regra: 'pico', ano: 2026, avaliados: [1, 2], marcados: [1, 2], naoAvaliados: [] }],
  });
  const html = api.profileView();
  assert.match(html, /Como trabalha/);
  assert.match(html, /Alertas na cota/);
  assert.match(html, /O que foi avaliado/);
  assert.match(html, /Categoria da fonte/);
  assert.match(html, /Fornecedor da fonte/);
  assert.match(html, /17 notas/);
  assert.match(html, /Registro mais recente/);
  assert.match(html, /Registro anterior/);
  assert.match(html, /avaliados jan–fev\/2026/);
  assert.doesNotMatch(html, /\[voto real\]|\[Confirmar|confirmar na cobertura gravada/);
});

test('profile project preview never turns unknown situations into zero laws', () => {
  const { context } = makeView();
  const shared = { id: 'camara:55', person: { role: 'deputado' }, projects: {
    status: 'imported', total: 43, items: [{ titulo: 'Projeto consultado', situacaoAtual: {
      grupo: 'tramitando', status: 'imported', consultadoEm: '2026-10-03T12:00:00Z',
    } }],
  } };
  const html = context.profileProjectsCard(shared);
  assert.match(html, /43/);
  assert.match(html, /parcial|não.*conferida|não.*consultada/i);
  assert.doesNotMatch(html, /0 (?:virou|viraram|leis)/);
  const missing = context.profileProjectsCard({ ...shared, projects: null });
  assert.doesNotMatch(missing, />0<|0 projetos/);
});

test('profile vote preview keeps actual votes, missing records and newest dates', () => {
  const { context } = makeView();
  setChamberVotes(context, 'camara:55', []);
  context.votesForPerson = () => [
    { vote: { id: 'old', titulo: 'Voto antigo', data: '2026-01-01' }, recordedVote: 'Sim' },
    { vote: { id: 'new', titulo: 'Voto recente', data: '2026-10-01' }, recordedVote: 'Não' },
    { vote: { id: 'missing', titulo: 'Sem linha individual', data: '2026-09-01' }, recordedVote: null },
  ];
  const html = context.profileRecentVotesCard({ id: 'camara:55', person: { role: 'deputado' } });
  assert.ok(html.indexOf('Voto recente') < html.indexOf('Voto antigo'));
  assert.match(html, /Não/);
  assert.match(html, /Sim/);
  assert.match(html, /Sem registro/);
  assert.doesNotMatch(html, /\[voto real\]/);
});

test('profile summary does not substitute quota for an incomplete mandate cost', () => {
  const { context } = makeView();
  const shared = { person: { role: 'deputado' }, cost: { usedMonths: [], monthlyAverageCents: null } };
  const html = context.profileSummaryCards(shared, { mediaMensal: 50000 }, [], true);
  assert.match(html, /Sem total/);
  assert.doesNotMatch(html, /R\$ 50 mil/);
});

test('visible profile alerts are chronological and keep their source and explanation', () => {
  const { context } = makeView();
  const alerts = [
    { tipo: 'pico', titulo: 'Alerta antigo', periodo: '2024-07', ano: 2024, mes: 7, frase: 'Registro anterior.', pessoa: { id: 'camara:55', role: 'deputado' } },
    { tipo: 'pico', titulo: 'Alerta recente', periodo: '2026-06', ano: 2026, mes: 6, frase: 'Registro recente.', pessoa: { id: 'camara:55', role: 'deputado' } },
  ];
  const html = context.profileAlertsSection(alerts, []);
  assert.ok(html.indexOf('Alerta recente') < html.indexOf('Alerta antigo'));
  assert.match(html, /href="https:\/\/www.camara.leg.br\/deputados\/55\?ano=2026"/);
  assert.match(html, /Conferir na fonte/);
  assert.match(html, /Por que apareceu aqui/);
  assert.match(html, /não indicam irregularidade/);
});

test('presence card lists the published justifications without inventing missing ones', () => {
  const { api } = makeView();
  const person = { id: 'camara:1', role: 'deputado', name: 'Pessoa' };
  const card = api.profileAttendanceCard({ id: 'camara:1', person, presence: { presente: 142, dias: 324, justificadas: 182, falta: 0, inicio: '2023-02', fim: '2026-09',
    motivos: [['Missão autorizada', 120], ['Licença para tratamento de saúde', 62]] } });
  assert.match(card, /<b>Justificativas:<\/b> missão autorizada \(120\), licença para tratamento de saúde \(62\)\./);
  const without = api.profileAttendanceCard({ id: 'camara:1', person, presence: { presente: 10, dias: 10, justificadas: 0, falta: 0 } });
  assert.doesNotMatch(without, /Justificativas/);
});
