const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ pathname, search, history, includeScoreboard = false, fetch: fetchImpl } = {}) {
  const app = { innerHTML: '' };
  const listeners = {};
  const document = {
    body: { dataset: {} },
    getElementById: id => id === 'app' ? app : null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document, window: { scrollY: 0, scrollTo() {} },
    location: { protocol: 'http:', ...(pathname ? { pathname } : {}), ...(search !== undefined ? { search } : {}) }, URL, URLSearchParams, AbortController,
    ...(history ? { history } : {}),
    fetch: fetchImpl || (() => new Promise(() => {})),
    setTimeout: () => 1, clearTimeout() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: class { observe() {} },
    addEventListener() {}, requestAnimationFrame() {},
  });
  const votes = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/votes.json'), 'utf8'));
  const data = { votacoes: votes.map(vote => ({ ...vote, partidos: [] })), presencaTodos: [],
    votosCompletos: {}, arrecadacao: null, perfis: { profiles: {} }, senado: {}, ultimaVotacao: null };
  const names = ['dates.js', 'profile-data.js', 'profile-cost.js', 'profile-senate-cost.js', 'share-card.js', 'citizen-view.js', 'extras-view.js', 'parties-view.js', 'home-view.js', 'city-view.js', ...(includeScoreboard ? ['scoreboard-view.js'] : []), 'methodology-view.js', 'app.script.js'];
  const source = names.map(name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8')).join('\n');
  vm.runInContext(source.replace('/*DATA*/null', JSON.stringify(data)), context);
  const click = dataset => {
    const target = { dataset, hasAttribute: name => Object.hasOwn(dataset, name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())) };
    for (const handler of listeners.click || []) {
      handler({ target: { closest: selector => selector.split(',').some(item => target.hasAttribute(item.slice(1, -1))) ? target : null }, preventDefault() {} });
    }
  };
  return { context, app, document, votes, click, listeners };
}

test('combined scripts boot and navigate through all public views with unavailable data', () => {
  const { context, document, app } = loadApp();
  assert.equal(document.body.dataset.view, 'home');
  for (const view of ['votes', 'politicians', 'alerts', 'attendance', 'compare', 'parties', 'city', 'methodology', 'home']) {
    vm.runInContext(`navigateToView(${JSON.stringify(view)})`, context);
    assert.equal(document.body.dataset.view, view);
    assert.ok(app.innerHTML.length > 50);
    if (view === 'city') assert.match(app.innerHTML, /Sua cidade/);
  }
});

test('vote buttons open the selected detail and back navigation restores the list', () => {
  const { context, document, app, votes, click } = loadApp();
  click({ go: 'votes' });
  click({ vote: String(votes[0].id) });
  assert.equal(document.body.dataset.view, 'vote');
  assert.ok(app.innerHTML.includes('O que muda na prática'));
  assert.equal(vm.runInContext('state.voteId', context), String(votes[0].id));
  click({ back: '' });
  assert.equal(document.body.dataset.view, 'votes');
  vm.runInContext("navigateToView('votacoes')", context);
  assert.equal(document.body.dataset.view, 'votes');
});

test('deep links open the profile and navigation updates the address bar', () => {
  const pushed = [];
  const history = { pushState: (_, __, url) => { pushed.push(['push', url]); context.location.pathname = url; },
    replaceState: (_, __, url) => { pushed.push(['replace', url]); context.location.pathname = url; } };
  const { context, document } = loadApp({ pathname: '/deputado/73604-rui-falcao', history });
  assert.equal(document.body.dataset.view, 'profile');
  assert.equal(vm.runInContext('state.politicianId', context), 'camara:73604');
  assert.deepEqual(pushed, [], 'o endereço com nome continua valendo para a mesma ficha');
  vm.runInContext('navigateToView("alerts")', context);
  assert.deepEqual(pushed.at(-1), ['push', '/alertas']);
  vm.runInContext('openPolitician("senado:22")', context);
  assert.deepEqual(pushed.at(-1), ['push', '/senador/22']);
});

test('section paths open their view', () => {
  const { document } = loadApp({ pathname: '/partidos' });
  assert.equal(document.body.dataset.view, 'parties');
});

test('methodology page has its own address and its links open the page at the right section', () => {
  const calls = [];
  const history = { pushState: (_, __, url) => { calls.push(['push', url]); context.location.pathname = url; },
    replaceState: (_, __, url) => { calls.push(['replace', url]); context.location.pathname = url.split('#')[0]; } };
  const { context, document, app, listeners } = loadApp({ pathname: '/metodologia', history });
  assert.equal(document.body.dataset.view, 'methodology');
  assert.equal(context.document.title, 'Metodologia · Painel Público');
  for (const text of ['Como o painel funciona', 'Alertas não indicam irregularidade', 'id="methodology-alerts"', 'href="#methodology-sources"',
    '1,75 vez a referência', '50% e pelo menos R$ 30 mil', 'cota-alertas-v3', 'Dado ausente não significa zero']) assert.ok(app.innerHTML.includes(text), text);
  assert.doesNotMatch(app.innerHTML, /\[Confirmar/);
  vm.runInContext("navigateToView('alerts')", context);
  assert.match(app.innerHTML, /href="\/metodologia#methodology-alerts" data-go="methodology"/);
  // O link "Como as regras funcionam" abre a metodologia já na seção dos alertas.
  const section = { scrollIntoView: options => calls.push(['scroll', options.block]) };
  document.getElementById = id => id === 'app' ? app : id === 'methodology-alerts' ? section : null;
  const link = { tagName: 'A', hash: '#methodology-alerts', dataset: { go: 'methodology' }, hasAttribute: () => false };
  let prevented = false;
  const event = { target: { closest: selector => selector.split(',').includes('[data-go]') ? link : null }, preventDefault() { prevented = true; } };
  for (const handler of listeners.click) handler(event);
  assert.ok(prevented);
  assert.equal(document.body.dataset.view, 'methodology');
  assert.deepEqual(calls.slice(-3), [['push', '/metodologia'], ['replace', '/metodologia#methodology-alerts'], ['scroll', 'start']]);
});

test('party comparison paths open the selected pair', () => {
  const { context, document } = loadApp({ pathname: '/partidos/PL-vs-PT' });
  assert.equal(document.body.dataset.view, 'parties');
  assert.deepEqual([...vm.runInContext('partyState.selected', context)], ['PL', 'PT']);
  assert.equal(vm.runInContext('viewPath()', context), '/partidos/PL-vs-PT');
});

test('politician comparison paths open both people and keep the address', () => {
  const requested = [];
  const { context, document } = loadApp({ pathname: '/comparar/deputado-73604-vs-senador-22',
    fetch: url => { requested.push(url); return new Promise(() => {}); } });
  assert.equal(document.body.dataset.view, 'compare');
  assert.deepEqual([...vm.runInContext('extrasState.comparisonIds', context)], ['camara:73604', 'senado:22']);
  assert.equal(vm.runInContext('viewPath()', context), '/comparar/deputado-73604-vs-senador-22');
  assert.ok(requested.some(url => String(url).includes('/api/c/politico/camara%3A73604')));
  assert.equal(vm.runInContext("comparisonIdsFromPath('/comparar/deputado-1-vs-deputado-1')", context), null);
  vm.runInContext("extrasState.comparisonIds = ['camara:73604']", context);
  assert.equal(vm.runInContext('viewPath()', context), '/comparar');
});

test('direct Placar vote paths load the vote view and keep the address', () => {
  const requested = [];
  const history = { pushState: (_, __, url) => requested.push(['push', url]), replaceState: (_, __, url) => requested.push(['replace', url]) };
  const { context, document } = loadApp({ pathname: '/placar/2611313-31', history, includeScoreboard: true,
    fetch: url => { requested.push(['fetch', url]); return new Promise(() => {}); } });
  assert.equal(document.body.dataset.view, 'vote');
  assert.equal(vm.runInContext('state.voteId', context), '2611313-31');
  assert.ok(requested.some(([kind, url]) => kind === 'fetch' && url === '/api/c/votes/2611313-31'));
  assert.deepEqual(requested.filter(([kind]) => kind !== 'fetch'), []);
});

const jsonResponse = body => Promise.resolve({ ok: true, status: 200, json: async () => body });
const settle = () => new Promise(resolve => setImmediate(resolve));

test('city paths open the city, load it by its IBGE code and complete the address with the name', async () => {
  const calls = [];
  const history = { pushState: (_, __, url) => { calls.push(['push', url]); context.location.pathname = url; },
    replaceState: (_, __, url) => { calls.push(['replace', url]); context.location.pathname = url; } };
  const requested = [];
  const { context, document, app } = loadApp({ pathname: '/minha-cidade/3550308', history,
    fetch: url => { requested.push(String(url)); return jsonResponse({ municipality: { id: '3550308', name: 'São Paulo', uf: 'SP', population: 11451245 },
      sources: {}, municipalElected: [], stateElected: [], topFederalVotes: [], currentFederal: [], messages: {} }); } });
  assert.equal(document.body.dataset.view, 'city');
  assert.equal(vm.runInContext('cityViewState.selectedId', context), '3550308');
  assert.ok(requested.includes('/api/c/cities/3550308'));
  assert.equal(vm.runInContext('viewPath()', context), '/minha-cidade/3550308');
  await settle();
  assert.equal(vm.runInContext('viewPath()', context), '/minha-cidade/3550308-sao-paulo');
  assert.deepEqual(calls.at(-1), ['replace', '/minha-cidade/3550308-sao-paulo']);
  assert.equal(context.document.title, 'São Paulo · Minha cidade · Painel Público');
  assert.match(app.innerHTML, /São Paulo em 3 respostas/);
  // Voltar do navegador para a busca sem cidade limpa a seleção; o endereço com o nome continua valendo.
  context.location.pathname = '/minha-cidade';
  vm.runInContext('applyLocation(); render(); syncLocation("replace")', context);
  assert.equal(vm.runInContext('cityViewState.selectedId', context), null);
  assert.match(app.innerHTML, /Sua cidade/);
  context.location.pathname = '/minha-cidade/3550308-sao-paulo';
  vm.runInContext('applyLocation(); render(); syncLocation("replace")', context);
  assert.equal(vm.runInContext('cityViewState.selectedCity.name', context), 'São Paulo');
  assert.equal(calls.filter(([, url]) => url === '/minha-cidade/3550308-sao-paulo').length, 1, 'o endereço já certo não é reescrito');
  assert.equal(vm.runInContext("cityIdFromPath('/minha-cidade/12345')", context), null);
});

test('list filters are read from the query string, written back on change and reset when the address loses them', () => {
  const calls = [];
  const setAddress = url => { context.location.pathname = url.split('?')[0]; context.location.search = url.includes('?') ? '?' + url.split('?')[1] : ''; };
  const history = { pushState: (_, __, url) => { calls.push(['push', url]); setAddress(url); }, replaceState: (_, __, url) => { calls.push(['replace', url]); setAddress(url); } };
  const requested = [];
  const { context, document, click } = loadApp({ pathname: '/alertas', search: '?tipo=pico&casa=senado&ano=2025&lixo=1', history,
    fetch: url => { requested.push(String(url)); return new Promise(() => {}); } });
  assert.equal(document.body.dataset.view, 'alerts');
  assert.deepEqual([...vm.runInContext('[citizenState.alerts.type, citizenState.alerts.role, citizenState.alerts.year]', context)], ['pico', 'senador', '2025']);
  assert.ok(requested.some(url => url.includes('/api/c/radar?') && url.includes('tipo=pico') && url.includes('cargo=senador') && url.includes('ano=2025')));
  assert.deepEqual(calls, [['replace', '/alertas?tipo=pico&casa=senado&ano=2025']], 'o parâmetro desconhecido sai do endereço');
  click({ alertRole: 'deputado' });
  assert.deepEqual(calls.at(-1), ['replace', '/alertas?tipo=pico&casa=camara&ano=2025']);
  click({ alertType: 'pico,fornecedor' });
  click({ alertYear: '' });
  assert.deepEqual(calls.at(-1), ['replace', '/alertas?casa=camara']);
  // Valores fora da lista caem no padrão e o padrão não aparece no endereço.
  context.location.search = '?tipo=qualquer&casa=prefeitura&ano=25';
  vm.runInContext('applyLocation(); render(); syncLocation("replace")', context);
  assert.deepEqual([...vm.runInContext('[citizenState.alerts.type, citizenState.alerts.role, citizenState.alerts.year]', context)], ['pico,fornecedor', '', '']);
  assert.deepEqual(calls.at(-1), ['replace', '/alertas']);
  // Políticos: busca, cargo e ordem; a ordem A–Z é o padrão.
  vm.runInContext("Object.assign(citizenState.politicians, { query: 'Tabata Amaral', role: 'deputado', order: 'cota', key: '' }); navigateToView('politicians')", context);
  assert.deepEqual(calls.at(-1), ['push', '/politicos?q=Tabata%20Amaral&cargo=deputado&ordem=cota']);
  context.location.search = '?q=PL&ordem=nome&cargo=vereador';
  vm.runInContext('applyLocation()', context);
  assert.deepEqual([...vm.runInContext('[citizenState.politicians.query, citizenState.politicians.role, citizenState.politicians.order]', context)], ['PL', '', 'nome']);
  // Presença: ordem e busca.
  context.location.pathname = '/presenca'; context.location.search = '?ordem=mais&q=MG';
  vm.runInContext('applyLocation(); render()', context);
  assert.equal(document.body.dataset.view, 'attendance');
  assert.deepEqual([...vm.runInContext('[extrasState.attendanceOrder, extrasState.attendanceQuery]', context)], ['more', 'MG']);
  click({ attendanceOrder: 'less' });
  assert.deepEqual(calls.at(-1), ['replace', '/presenca?q=MG']);
});

test('Placar filters and page travel in the address with public names and reach the API with its own names', () => {
  const calls = [];
  const history = { pushState: (_, __, url) => calls.push(['push', url]), replaceState: (_, __, url) => calls.push(['replace', url]) };
  const requested = [];
  const { context, document } = loadApp({ pathname: '/placar', search: '?q=sa%C3%BAde&tipo=PEC&resultado=aprovadas&decisao=urgencia&pagina=2', history, includeScoreboard: true,
    fetch: url => { requested.push(String(url)); return new Promise(() => {}); } });
  assert.equal(document.body.dataset.view, 'votes');
  const list = vm.runInContext('({ ...scoreboardState.list, data: null })', context);
  assert.deepEqual([list.query, list.type, list.result, list.kind, list.page], ['saúde', 'PEC', 'approved', 'urgency', 2]);
  const api = requested.find(url => url.startsWith('/api/c/votes?'));
  assert.ok(api, 'a lista é pedida com os filtros do endereço');
  for (const part of ['q=sa%C3%BAde', 'type=PEC', 'result=approved', 'kind=urgency', 'page=2']) assert.ok(api.includes(part), part);
  assert.equal(vm.runInContext('viewPath() + viewQuery()', context), '/placar?q=sa%C3%BAde&tipo=PEC&resultado=aprovadas&decisao=urgencia&pagina=2');
  vm.runInContext("scoreboardApplyFilters({ query: '', type: 'PL', theme: '', result: 'not_approved', kind: '' })", context);
  assert.deepEqual(calls.at(-1), ['replace', '/placar?tipo=PL&resultado=rejeitadas']);
  // Parâmetros inválidos caem no padrão sem derrubar a tela.
  context.location.search = '?tipo=XYZ&resultado=talvez&decisao=outra&pagina=abc';
  vm.runInContext('applyLocation()', context);
  const reset = vm.runInContext('({ ...scoreboardState.list, data: null })', context);
  assert.deepEqual([reset.type, reset.result, reset.kind, reset.page], ['', '', '', 1]);
});
