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
    go(view) { state.view = view; },
    rerender() {},
    setTimeout: schedule,
    URL,
    state,
  };
  vm.createContext(context);
  vm.runInContext(profileSource + '\n' + source + '\nthis.__api = { cid, cidOpenPol, cidAvatar, cidTemFicha, cidPolRow, cidPolCoverageHTML, cidPolCoverageNotesHTML, cidLoadPol, vPoliticos, cidHomeCard, profileData, profileSectionsHTML, vPolitico };', context);
  return { api: context.__api, elements, state, events, context };
}

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
  assert.match(profile, /Salário parlamentar/);
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
  assert.match(profile, /Salário parlamentar/);
  assert.match(profile, /Equipe e verba de gabinete/);
  assert.match(profile, /Cota é reembolso/);
  assert.match(profile, /subsídio bruto mensal de referência do cargo/);
  assert.doesNotMatch(profile, /Não é o salário, que é de/);
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
  assert.match(profile, /Na fotografia da fonte/);
  assert.match(profile, /Mandato &lt;titular&gt; &amp; participação/);
  assert.match(profile, /Exercício de 05\/08\/2026 a 06\/10\/2026 — Retorno do titular/);
  assert.match(profile, /href="https:\/\/senado\.example\.test\/lista\?x=&quot; onmouseover=&quot;alert\(1\)" target="_blank"/);
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
