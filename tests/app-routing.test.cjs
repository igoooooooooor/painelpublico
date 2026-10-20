const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SITE_PAGES = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/site-pages.json'), 'utf8'));

function loadApp({ pathname, search = '', history, includeScoreboard = false, fetch: fetchImpl, serverRender = null, title = 'Painel Público' } = {}) {
  // serverRender = { path, html }: o que o servidor pôs em #app (data-server-render) antes de o app rodar.
  const app = { innerHTML: '', querySelector: selector => selector === '[data-server-render]' && serverRender
    ? { getAttribute: () => serverRender.path, innerHTML: serverRender.html } : null };
  const listeners = {};
  const head = { canonical: { href: '', setAttribute(_, value) { this.href = value; } }, description: { content: '', setAttribute(_, value) { this.content = value; } }, robots: null };
  const document = {
    body: { dataset: {} }, title,
    head: { appendChild(node) { head.robots = node; } },
    createElement: () => ({ attributes: {}, setAttribute(name, value) { this.attributes[name] = value; }, remove() { head.robots = null; } }),
    getElementById: id => id === 'app' ? app : null,
    querySelector: selector => selector === 'link[rel="canonical"]' ? head.canonical : selector === 'meta[name="description"]' ? head.description
      : selector === 'meta[name="robots"]' ? head.robots : null,
    querySelectorAll: () => [],
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document, window: { scrollY: 0, scrollTo() {} },
    location: { protocol: 'http:', origin: 'https://painel.test', search, ...(pathname ? { pathname } : {}) }, URL, URLSearchParams, AbortController,
    ...(history ? { history } : {}),
    fetch: fetchImpl || (() => new Promise(() => {})),
    setTimeout: () => 1, clearTimeout() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: class { observe() {} },
    addEventListener() {}, requestAnimationFrame() {},
  });
  const votes = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/votes.json'), 'utf8'));
  const data = { votacoes: votes.map(vote => ({ ...vote, partidos: [] })), presencaTodos: [],
    votosCompletos: {}, arrecadacao: null, perfis: { profiles: {} }, senado: {}, ultimaVotacao: null, sitePages: SITE_PAGES };
  const names = ['dates.js', 'profile-data.js', 'profile-cost.js', 'profile-senate-cost.js', 'share-card.js', 'citizen-view.js', 'extras-view.js', 'parties-view.js', 'home-view.js', 'city-view.js', ...(includeScoreboard ? ['scoreboard-view.js'] : []), 'methodology-view.js', 'app.script.js'];
  const source = names.map(name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8')).join('\n');
  vm.runInContext(source.replace('/*DATA*/null', JSON.stringify(data)), context);
  const click = (dataset, { tagName, modifiers = {} } = {}) => {
    const target = { dataset, tagName, hasAttribute: name => Object.hasOwn(dataset, name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())) };
    const event = { target: { closest: selector => selector.split(',').some(item => target.hasAttribute(item.slice(1, -1))) ? target : null }, prevented: false, preventDefault() { this.prevented = true; }, ...modifiers };
    for (const handler of listeners.click || []) handler(event);
    return event;
  };
  return { context, app, document, votes, click, listeners, head };
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
  assert.deepEqual(pushed.at(-1), ['push', '/picos-e-concentracoes']);
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
  assert.equal(context.document.title, 'Metodologia e perguntas · Painel Público', 'mesmo título que o servidor entrega no HTML');
  for (const text of ['Como o painel funciona', 'Picos e concentrações não indicam irregularidade', 'id="methodology-alerts"', 'href="#methodology-sources"',
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

test('server content stays on screen while the profile loads and never leaks to another person', () => {
  const summary = '<article class="seo-summary"><h1>Rui Falcão</h1><ul><li>R$ 1.234 por mês</li></ul></article>';
  const serverTitle = 'Rui Falcão (PT-SP): quanto custa e como trabalha · Painel Público';
  const { context, app, document, head } = loadApp({ pathname: '/deputado/73604-rui-falcao', title: serverTitle, serverRender: { path: '/deputado/73604', html: summary } });
  assert.equal(document.body.dataset.view, 'profile');
  assert.ok(app.innerHTML.includes(summary), 'o resumo do servidor fica enquanto a API não responde');
  assert.doesNotMatch(app.innerHTML, /class="sk /, 'sem esqueleto por cima do conteúdo real');
  assert.equal(document.title, serverTitle, 'o título da aba não vira "Ficha" durante o carregamento');
  assert.equal(head.canonical.href, '', 'o canonical do servidor (com o nome) não é reescrito na página de entrada');
  // API falhou: o aviso aparece e o resumo continua disponível.
  vm.runInContext("citizenState.profileError = 'Falhou'; rerender()", context);
  assert.match(app.innerHTML, /Não deu para abrir esta ficha/);
  assert.ok(app.innerHTML.includes(summary));
  // Outra pessoa: endereço diferente, nada do resumo anterior; título e canonical próprios.
  vm.runInContext("citizenState.profileError = null; openPolitician('senado:22')", context);
  assert.ok(!app.innerHTML.includes('Rui Falcão'));
  assert.match(app.innerHTML, /class="sk /);
  assert.equal(document.title, 'Ficha · Painel Público');
  assert.equal(head.canonical.href, 'https://painel.test/senador/22');
  // Ficha carregada: título igual ao do servidor e canonical com o nome.
  vm.runInContext("citizenState.profileId = 'senado:22'; citizenState.profile = { pessoa: { id: 'senado:22', name: 'Ana Ávila', role: 'senador', party: 'BBB', uf: 'RJ' }, alertas: [], meses: [], categorias: [], fornecedores: [], maiores: [] }; citizenState.profileLoading = false; rerender()", context);
  assert.equal(document.title, 'Ana Ávila (BBB-RJ): quanto custa e como trabalha · Painel Público');
  assert.equal(head.canonical.href, 'https://painel.test/senador/22-ana-avila');
});

test('section titles and descriptions follow the shared site pages file on internal navigation', () => {
  const { context, document, head } = loadApp({ pathname: '/' });
  assert.equal(document.title, 'Painel Público: quanto custa e como trabalha cada parlamentar');
  vm.runInContext("navigateToView('alerts')", context);
  const alerts = SITE_PAGES.sections.find(section => section.path === '/picos-e-concentracoes');
  assert.equal(document.title, `${alerts.title} · Painel Público`);
  assert.equal(head.description.content, alerts.description);
  assert.equal(head.canonical.href, 'https://painel.test/picos-e-concentracoes');
  assert.equal(head.robots, null);
  vm.runInContext("partyState.selected = ['PL', 'PT']; navigateToView('parties')", context);
  assert.equal(head.canonical.href, 'https://painel.test/partidos/PL-vs-PT');
  assert.equal(head.robots?.attributes?.content, 'noindex', 'pares compartilháveis continuam fora do índice ao navegar');
  vm.runInContext("navigateToView('about')", context);
  assert.equal(document.title, 'Sobre o projeto · Painel Público');
  assert.equal(head.robots, null);
});

test('home and section content from the server is kept until the API answers', () => {
  const served = '<section class="home-hero"><h1 class="home-title">Quanto custa</h1></section><dl class="home-stats"></dl>';
  const { context, app } = loadApp({ pathname: '/', serverRender: { path: '/', html: served } });
  assert.ok(app.innerHTML.includes(served));
  assert.doesNotMatch(app.innerHTML, /class="sk /);
  vm.runInContext("home.error = 'Falhou'; rerender()", context);
  assert.match(app.innerHTML, /Tentar novamente/);
  assert.ok(!app.innerHTML.includes(served), 'com erro, o cartão de tentativa substitui o conteúdo do servidor');
  const list = '<ul class="seo-directory"><li><a href="/deputado/1">Ana</a></li></ul>';
  const politicians = loadApp({ pathname: '/politicos', serverRender: { path: '/politicos', html: list } });
  assert.ok(politicians.app.innerHTML.includes(list));
  vm.runInContext("navigateToView('alerts')", politicians.context);
  assert.ok(!politicians.app.innerHTML.includes(list), 'outra seção não herda o conteúdo do servidor');
});

test('unknown addresses render the not found page and the home search query prefills the list', () => {
  const { document, app, head } = loadApp({ pathname: '/nao-existe' });
  assert.equal(document.body.dataset.view, 'notFound');
  assert.match(app.innerHTML, /Página não encontrada/);
  assert.equal(document.title, 'Página não encontrada · Painel Público');
  assert.equal(head.robots?.attributes?.content, 'noindex');
  const served = loadApp({ pathname: '/nao-existe', serverRender: { path: '/nao-existe', html: '<h1>404 do servidor</h1>' } });
  assert.match(served.app.innerHTML, /404 do servidor/);
  const search = loadApp({ pathname: '/politicos', search: '?q=Tabata' });
  assert.equal(search.document.body.dataset.view, 'politicians');
  assert.equal(vm.runInContext('citizenState.politicians.query', search.context), 'Tabata');
});

test('real links keep working as links with modifier keys and as app navigation on plain clicks', () => {
  const { document, click } = loadApp({ pathname: '/' });
  const plain = click({ go: 'alerts' }, { tagName: 'A' });
  assert.ok(plain.prevented);
  assert.equal(document.body.dataset.view, 'alerts');
  const newTab = click({ go: 'votes' }, { tagName: 'A', modifiers: { metaKey: true } });
  assert.ok(!newTab.prevented, 'Cmd/Ctrl+clique fica com o navegador');
  assert.equal(document.body.dataset.view, 'alerts');
  const vote = click({ vote: '2611313-31' }, { tagName: 'A', modifiers: { ctrlKey: true } });
  assert.ok(!vote.prevented);
  assert.equal(document.body.dataset.view, 'alerts');
  click({ vote: '2611313-31' }, { tagName: 'A' });
  assert.equal(document.body.dataset.view, 'vote');
  assert.match(vm.runInContext('viewPath()', loadApp({ pathname: '/placar/2611313-31' }).context), /^\/placar\/2611313-31$/);
});
