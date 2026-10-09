const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ pathname = '/', fetch: fetchImpl = () => Promise.resolve(jsonResponse({ available: true, items: [], total: 0, page: 1, pageSize: 12, pageCount: 0 })) } = {}) {
  const app = { innerHTML: '' };
  const listeners = {};
  const document = {
    body: { dataset: {} },
    getElementById: id => id === 'app' ? app : null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const votes = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/votes.json'), 'utf8'));
  const data = { votacoes: votes.map(vote => ({ ...vote, partidos: [] })), presencaTodos: [], votosCompletos: {},
    arrecadacao: null, perfis: { profiles: {} }, senado: {}, ultimaVotacao: null };
  const names = ['dates.js', 'profile-data.js', 'profile-cost.js', 'profile-senate-cost.js', 'share-card.js', 'citizen-view.js',
    'extras-view.js', 'parties-view.js', 'home-view.js', 'city-view.js', 'scoreboard-view.js', 'app.script.js'];
  const source = names.map(name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8')).join('\n');
  const context = vm.createContext({
    document, window: { scrollY: 0, scrollTo() {}, addEventListener() {} }, location: { protocol: 'http:', pathname }, URL, URLSearchParams, FormData,
    history: { pushState() {}, replaceState() {} }, fetch: fetchImpl,
    setTimeout: () => 1, clearTimeout() {}, matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: class { observe() {} }, addEventListener() {}, requestAnimationFrame() {},
  });
  vm.runInContext(source.replace('/*DATA*/null', JSON.stringify(data)), context);
  const click = dataset => {
    const target = { dataset, hasAttribute: name => Object.hasOwn(dataset, name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())) };
    for (const handler of listeners.click || []) {
      handler({ target: { closest: selector => selector.split(',').some(item => target.hasAttribute(item.slice(1, -1))) ? target : null }, preventDefault() {} });
    }
  };
  return { context, app, document, votes, click };
}
function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function listPayload({ items = [], page = 1, pageCount = 1, total = items.length } = {}) {
  return { available: true, items, total, page, pageSize: 12, pageCount,
    period: { start: '2023-02-01', end: '2026-10-09' },
    coverage: { inventoryCount: 1339, candidateCount: 162, reviewedCount: 40, publishedCount: 7, pendingCount: 155, detail: 'metodologia' },
    filters: { types: ['PL', 'PLP', 'PEC'], themes: [{ id: 'tributos', label: 'Tributos' }] }, generatedAt: '2026-10-09T12:00:00Z' };
}
function item(id, title, extra = {}) {
  return { id, date: '2026-10-08', proposition: 'PL 123/2026', type: 'PL', title, summary: 'Resumo da decisão', decisionLabel: 'Substitutivo aprovado',
    yesMeaning: 'Aprovar a versão descrita.', noMeaning: 'Rejeitar a versão descrita.', outcome: 'approved', tally: { yes: 250, no: 100, abstention: null, total: 350 },
    themes: [{ id: 'tributos', label: 'Tributos' }], sources: {}, ...extra };
}

test('the home makes no Placar request; entering the view loads the catalogue', async () => {
  const calls = [];
  const { context, app } = loadApp({ fetch: async url => { calls.push(url); return jsonResponse(listPayload()); } });
  assert.deepEqual(calls, []);
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.equal(calls.length, 1);
  assert.match(calls[0], /^\/api\/c\/votes\?/);
  assert.match(app.innerHTML, /Cobertura nominal do Plenário/);
});

test('filter parameters, coverage counts and page navigation follow the API result', async () => {
  const calls = [];
  const { context, app } = loadApp({ fetch: async url => {
    calls.push(url);
    const page = Number(new URL(url, 'https://local.test').searchParams.get('page'));
    return jsonResponse(listPayload({ items: [item(`2611313-${page}`, `Votação da página ${page}`)], page, pageCount: 3, total: 25 }));
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  await vm.runInContext("scoreboardApplyFilters({query:'benefício', type:'PL', theme:'tributos'})", context);
  assert.match(calls.at(-1), /q=benef%C3%ADcio/);
  assert.match(calls.at(-1), /type=PL/);
  assert.match(calls.at(-1), /theme=tributos/);
  assert.match(app.innerHTML, /40 revisadas · 155 pendentes/);
  assert.match(app.innerHTML, /Página 1 de 3 · 25 votações/);
  await vm.runInContext('scoreboardHandlePage(2)', context);
  assert.match(calls.at(-1), /page=2/);
  assert.match(app.innerHTML, /Votação da página 2/);
  assert.match(app.innerHTML, /Página 2 de 3 · 25 votações/);
});

test('stale catalogue responses cannot replace the newest filter result', async () => {
  const pending = [];
  const { context, app } = loadApp({ fetch: url => new Promise(resolve => pending.push({ url, resolve })) });
  vm.runInContext("navigateToView('votes')", context);
  const newest = vm.runInContext("scoreboardApplyFilters({query:'novo', type:'PEC', theme:''})", context);
  pending[1].resolve(jsonResponse(listPayload({ items: [item('2611313-32', 'Resultado novo')] })));
  await newest;
  assert.match(app.innerHTML, /Resultado novo/);
  pending[0].resolve(jsonResponse(listPayload({ items: [item('2611313-31', 'Resultado antigo')] })));
  await flush();
  assert.match(app.innerHTML, /Resultado novo/);
  assert.doesNotMatch(app.innerHTML, /Resultado antigo/);
});

test('a stale vote detail cannot replace the currently open decision', async () => {
  const pending = [];
  const { context, app, click } = loadApp({ fetch: url => {
    if (url.startsWith('/api/c/votes?')) return Promise.resolve(jsonResponse(listPayload({ items: [item('2611313-31', 'Primeira'), item('2611313-32', 'Segunda')] })));
    return new Promise(resolve => pending.push({ url, resolve }));
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  click({ vote: '2611313-31' });
  click({ vote: '2611313-32' });
  assert.deepEqual(pending.map(request => request.url), ['/api/c/votes/2611313-31', '/api/c/votes/2611313-32']);
  pending[1].resolve(jsonResponse({ available: true, vote: item('2611313-32', 'Decisão atual'), participants: [], partyTotals: [], participantsAvailable: true }));
  await flush();
  assert.match(app.innerHTML, /Decisão atual/);
  pending[0].resolve(jsonResponse({ available: true, vote: item('2611313-31', 'Decisão antiga'), participants: [], partyTotals: [], participantsAvailable: true }));
  await flush();
  assert.match(app.innerHTML, /Decisão atual/);
  assert.doesNotMatch(app.innerHTML, /Decisão antiga/);
});

test('detail loads lazily, preserves missing values and escapes text and source links', async () => {
  const calls = [];
  const participants = Array.from({ length: 21 }, (_, index) => ({ id: `camara:${1000 + index}`, name: `Deputado ${index}`, party: 'ABC', uf: 'SP',
    vote: ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'][index % 5] }));
  participants[19].vote = null;
  const detail = { available: true, vote: item('2611313-31', '<img src=x onerror=alert(1)>', {
    summary: '<script>ruim</script>', tally: { yes: 12, no: 3, abstention: null },
    sources: { vote: 'javascript:alert(1)', rollCall: 'https://fora.example/nominal', text: 'https://www.camara.leg.br/texto?id=4', proposition: 'https://camara.leg.br/prop/123' },
  }), participants, partyTotals: [], participantsAvailable: true };
  const { context, app, click } = loadApp({ fetch: async url => {
    calls.push(url);
    return url.startsWith('/api/c/votes?') ? jsonResponse(listPayload({ items: [item('2611313-31', 'Decisão')] })) : jsonResponse(detail);
  } });
  assert.deepEqual(calls, []);
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.deepEqual(calls, ['/api/c/votes?page=1&pageSize=12']);
  click({ vote: '2611313-31' });
  await flush();
  assert.ok(calls.includes('/api/c/votes/2611313-31'));
  assert.match(app.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(app.innerHTML, /&lt;script&gt;ruim&lt;\/script&gt;/);
  assert.doesNotMatch(app.innerHTML, /href="javascript:|href="https:\/\/fora\.example/);
  assert.match(app.innerHTML, /href="https:\/\/www\.camara\.leg\.br\/texto\?id=4/);
  assert.match(app.innerHTML, /Abstenção<\/dt><dd>—/);
  assert.match(app.innerHTML, /Total<\/dt><dd>—/);
  assert.match(app.innerHTML, /Escolha não informada/);
  assert.match(app.innerHTML, /Mostrar mais 1/);
  assert.doesNotMatch(app.innerHTML, /Não votou/);
  vm.runInContext("scoreboardHandleClick({}, {hasAttribute: name => name === 'data-scoreboard-more', dataset: {}})", context);
  assert.match(app.innerHTML, /Deputado 20/);
  assert.match(app.innerHTML, /href="\/deputado\/1020"/);
});

test('an unavailable catalogue shows only selected legacy cards and legacy detail still opens', async () => {
  const calls = [];
  const { context, app, votes, click } = loadApp({ fetch: async url => {
    calls.push(url);
    return jsonResponse({ error: 'rota indisponível' }, 404);
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.match(app.innerHTML, /O catálogo ampliado está indisponível/);
  assert.match(app.innerHTML, /votações selecionadas que já existem neste painel/);
  assert.ok(votes.some(vote => app.innerHTML.includes(vote.titulo)));
  click({ vote: String(votes[0].id) });
  await flush();
  assert.match(app.innerHTML, /O que muda na prática/);
  assert.ok(calls.includes(`/api/c/votes/${votes[0].id}`));
});
