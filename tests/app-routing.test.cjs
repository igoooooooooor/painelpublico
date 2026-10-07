const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp() {
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
    location: { protocol: 'http:' }, URL, AbortController,
    fetch: () => new Promise(() => {}),
    setTimeout: () => 1, clearTimeout() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: class { observe() {} },
    addEventListener() {}, requestAnimationFrame() {},
  });
  const votes = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/votes.json'), 'utf8'));
  const data = { votacoes: votes.map(vote => ({ ...vote, partidos: [] })), presencaTodos: [],
    votosCompletos: {}, arrecadacao: null, perfis: { profiles: {} }, senado: {}, ultimaVotacao: null };
  const names = ['profile-data.js', 'citizen-view.js', 'extras-view.js', 'parties-view.js', 'home-view.js', 'city-view.js', 'app.script.js'];
  const source = names.map(name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8')).join('\n');
  vm.runInContext(source.replace('/*DATA*/null', JSON.stringify(data)), context);
  const click = dataset => {
    const target = { dataset, hasAttribute: name => Object.hasOwn(dataset, name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())) };
    for (const handler of listeners.click || []) {
      handler({ target: { closest: selector => selector.split(',').some(item => target.hasAttribute(item.slice(1, -1))) ? target : null }, preventDefault() {} });
    }
  };
  return { context, app, document, votes, click };
}

test('combined scripts boot and navigate through all public views with unavailable data', () => {
  const { context, document, app } = loadApp();
  assert.equal(document.body.dataset.view, 'home');
  for (const view of ['votes', 'politicians', 'alerts', 'attendance', 'compare', 'parties', 'city', 'home']) {
    vm.runInContext(`navigateToView(${JSON.stringify(view)})`, context);
    assert.equal(document.body.dataset.view, view);
    assert.ok(app.innerHTML.length > 50);
    if (view === 'city') assert.match(app.innerHTML, /Qual cidade você quer consultar\?/);
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
