const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ pathname, history, includeScoreboard = false, fetch: fetchImpl } = {}) {
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
    location: { protocol: 'http:', ...(pathname ? { pathname } : {}) }, URL, AbortController,
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
