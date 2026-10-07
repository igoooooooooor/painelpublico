const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const viewSource = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'scripts', 'public-data-view.js'), 'utf8');
const profileSource = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'scripts', 'profile-data.js'), 'utf8');
const CASES_KEY = 'nl-public-investigations-v1';
const FOLLOW_KEY = 'nl-public-authorities-v1';

function makeView({ failSet = false, seed = {}, fetchImpl, caseTitle = 'Investigation', caseNote = '', data } = {}) {
  const values = new Map();
  const failedKeys = new Set(failSet === true ? [CASES_KEY] : Array.isArray(failSet) ? failSet : []);
  for (const [key, value] of Object.entries(seed)) values.set(key, JSON.stringify(value));
  const localStorage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) {
      if (failedKeys.has(key)) throw new Error('storage full');
      values.set(key, String(value));
    }
  };
  const content = { innerHTML: '' };
  const followStatus = { textContent: '' };
  const listFollowStatus = { textContent: '' };
  const savedFiles = [];
  const renders = [];
  const navigations = [];
  const state = { view: 'despesas' };
  const document = {
    querySelector(selector) {
      if (selector === '[data-public-content="base"]') return content;
      if (selector === '[data-public-follow-status]') return followStatus;
      if (selector === '[data-public-list-follow-status]') return listFollowStatus;
      return null;
    },
    querySelectorAll() { return []; },
    getElementById(id) {
      if (id === 'public-case-title') return { value: caseTitle };
      if (id === 'public-case-note') return { value: caseNote };
      return null;
    },
    addEventListener() {}
  };
  const context = {
    Blob,
    URL,
    URLSearchParams,
    location: { protocol: 'http:' },
    document,
    localStorage,
    state,
    DATA: data || { deputados: [], geradoEm: '2026-10-07', perfis: { profiles: {} }, presencaTodos: [], votacoes: [], votosCompletos: {} },
    fetch: fetchImpl || (async () => { throw new Error('Unexpected fetch'); }),
    esc(value) {
      return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
    },
    brl(value, digits = 2) { return `R$ ${Number(value).toFixed(digits).replace('.', ',')}`; },
    render() { renders.push(state.view); },
    go(view) { navigations.push(view); state.view = view; },
    cidSenadoFotografia(person) {
      return person?.role === 'senador'
        ? `<section class="test-senate-photo">${String(person.position || '')} ${String(person.employmentStatus || '')}</section>`
        : '';
    },
    extFichaExtra() { return ''; },
    salvarArquivo(blob, name) { savedFiles.push({ blob, name }); }
  };
  vm.createContext(context);
  vm.runInContext(`${profileSource}\n${viewSource}\nthis.__publicTest = {
    publicState, publicRead, publicAuthorityDetailHTML, publicExpenseRow, publicSaveCase,
    publicGoToAuthorityExpenses, publicInvestigateSignal, publicSignalCard,
    publicExportRows, publicToggleFollow, publicUnfollow, loadPublicView
  };`, context);
  return { api: context.__publicTest, context, values, localStorage, content, state, savedFiles, renders, navigations, followStatus, listFollowStatus };
}

test('authority summary preserves real zero and distinguishes an absent kind', () => {
  const { api } = makeView();
  const html = api.publicAuthorityDetailHTML({
    authority: { id: 'official-1' },
    summary: [{ kind: 'reembolso', amount: 0, count: 1 }],
    benchmark: { available: false }
  });

  assert.match(html, /R\$ 0,00/);
  assert.match(html, /Sem valores importados/);
  assert.match(html, /1 registros/);
});

test('federal legislative authority profiles include shared contacts and projects while retaining public expenses', () => {
  const data = {
    deputados: [], geradoEm: '2026-10-07', presencaTodos: [], votacoes: [], votosCompletos: {},
    perfis: { profiles: { 'camara:123': {
      role: 'deputado', name: 'Ana Parlamentar', party: 'PV', uf: 'SP',
      contato: { email: 'ana@example.test', telefones: ['(11) 4000-1234'], endereco: 'Gabinete 123', redes: [], sourceUrl: 'https://camara.example.test/perfil', fetchedAt: '2026-10-07', status: 'imported' },
      projetos: { status: 'imported', period: '2023–2026', total: 1, sourceUrl: 'https://camara.example.test/projetos', fetchedAt: '2026-10-07', items: [
        { id: '42', titulo: 'Projeto de exemplo', ementa: 'Resumo do projeto', situacao: 'Em tramitação', url: 'https://camara.example.test/projeto/42' }
      ] }
    } } }
  };
  const { api } = makeView({ data });
  api.publicState.publicAuthority = { id: 'camara:123', name: 'Ana Parlamentar', role: 'deputado', party: 'PV', uf: 'SP' };

  const html = api.publicAuthorityDetailHTML({
    authority: { id: 'camara:123', role: 'deputado' },
    summary: [{ kind: 'reembolso', amount: 12345.67, count: 2 }],
    benchmark: { available: false }
  });

  assert.match(html, /Salário parlamentar/);
  assert.match(html, /Contato e gabinete/);
  assert.match(html, /ana@example\.test/);
  assert.match(html, /Projetos apresentados/);
  assert.match(html, /Projeto de exemplo/);
  assert.match(html, /R\$ 12345,67/);
  assert.match(html, /data-pol="camara:123"/);
  assert.match(html, /data-public-authority-expenses="camara:123"/);
});

test('Senate detail metadata fills a basic selected authority in the public profile', () => {
  const { api } = makeView();
  api.publicState.publicAuthority = { id: 'senado:77', name: 'Senadora Exemplo', role: 'senador' };

  const html = api.publicAuthorityDetailHTML({
    authority: {
      id: 'senado:77', role: 'senador', position: 'Titular em exercício',
      employmentStatus: 'Exercício desde 2023', sourceUrl: 'https://senado.example.test/perfil'
    },
    summary: [], benchmark: { available: false }
  });

  assert.match(html, /Titular em exercício/);
  assert.match(html, /Exercício desde 2023/);
  assert.match(html, /data-pol="senado:77"/);
});

test('empty authority detail fields do not erase metadata already known by the selected profile', async () => {
  const response = data => ({ ok: true, json: async () => data });
  const fetchImpl = async url => {
    if (url.startsWith('/api/authorities/')) return response({ authority: {
      id: 'authority-2', name: 'Pessoa Exemplo', role: 'servidor',
      position: '', employmentStatus: null, sourceUrl: ''
    }, summary: [] });
    if (url.startsWith('/api/expenses?')) return response({ items: [], total: 0 });
    if (url.startsWith('/api/signals?')) return response({ items: [], total: 0 });
    throw new Error(`Unexpected URL: ${url}`);
  };
  const { api, state } = makeView({ fetchImpl });
  api.publicState.coverage = { sources: [] };
  api.publicState.publicAuthority = {
    id: 'authority-2', name: 'Pessoa Exemplo', role: 'servidor',
    position: 'Analista', employmentStatus: 'Ativo', sourceUrl: 'https://data.example.test/profile'
  };
  state.view = 'autoridade';

  await api.loadPublicView('autoridade');

  assert.equal(api.publicState.publicAuthority.position, 'Analista');
  assert.equal(api.publicState.publicAuthority.employmentStatus, 'Ativo');
  assert.equal(api.publicState.publicAuthority.sourceUrl, 'https://data.example.test/profile');
});

test('state and local deputies do not inherit federal parliamentary profile sections', () => {
  const { api } = makeView({ data: {
    deputados: [], geradoEm: '2026-10-07', presencaTodos: [], votacoes: [], votosCompletos: {},
    perfis: { profiles: { 'camara:123': {
      role: 'deputado', contato: { email: 'federal@example.test' },
      projetos: { status: 'imported', total: 1, items: [{ titulo: 'Projeto federal' }] }
    } } }
  } });
  api.publicState.publicAuthority = { id: '123', name: 'Deputado Estadual', role: 'deputado_estadual' };

  const html = api.publicAuthorityDetailHTML({
    authority: { id: '123', role: 'deputado_estadual' },
    summary: [{ kind: 'reembolso', amount: 50, count: 1 }],
    benchmark: { available: false }
  });

  assert.doesNotMatch(html, /Salário parlamentar|Contato e gabinete|Projetos apresentados|data-pol=/);
  assert.doesNotMatch(html, /federal@example\.test|Projeto federal/);
  assert.match(html, /R\$ 50,00/);
});

test('external expense and source text is escaped before entering profile HTML', () => {
  const { api } = makeView();
  api.publicState.coverage = {
    sources: [{ id: 'source-1', label: '<img src=x onerror=alert(1)>', url: 'https://data.example.test/source' }]
  };
  const html = api.publicExpenseRow({
    id: 'expense-1', amount: 5, year: 2026, month: 1, date: '2026-01-01',
    category: '<script>alert(1)</script>', kind: 'reembolso', supplierKey: 'supplier-1',
    supplierName: '<svg onload=alert(1)>', authorityId: 'authority-1',
    authorityName: '<b onmouseover=alert(1)>', role: 'deputado', sourceId: 'source-1',
    documentUrl: 'https://data.example.test/receipt'
  });

  assert.doesNotMatch(html, /<script>|<svg|<img/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /&lt;svg onload=alert\(1\)&gt;/);
  assert.match(html, /Fonte do registro: &lt;img/);
  assert.match(html, /href="https:\/\/data\.example\.test\/source"/);
});

test('saving an investigation persists its selected expense, annotation, and source fields', () => {
  const { api, values, state } = makeView({ caseTitle: 'Conferir recibo', caseNote: 'Rever o documento.' });
  const expense = {
    id: 'expense-9', authorityName: 'Pessoa', kind: 'reembolso', amount: 120,
    sourceId: 'judiciary-dataset', sourceUrl: 'https://data.example.test/expense'
  };
  api.publicState.selectedExpenseIds.add(expense.id);
  api.publicState.expenseRowsById.set(expense.id, expense);
  api.publicState.expenseNotes.set(expense.id, 'Nota ainda não localizada');

  api.publicSaveCase();

  const saved = api.publicRead(CASES_KEY, []);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].title, 'Conferir recibo');
  assert.equal(saved[0].note, 'Rever o documento.');
  assert.equal(saved[0].expenses[0].annotation, 'Nota ainda não localizada');
  assert.equal(saved[0].expenses[0].sourceId, 'judiciary-dataset');
  assert.equal(saved[0].expenses[0].sourceUrl, 'https://data.example.test/expense');
  assert.equal(api.publicState.selectedExpenseIds.size, 0);
  assert.equal(state.view, 'despesas');
});

test('storage failure keeps the selected evidence and reports the failure', () => {
  const { api, renders } = makeView({ failSet: true });
  const expense = { id: 'expense-10', amount: 1 };
  api.publicState.selectedExpenseIds.add(expense.id);
  api.publicState.expenseRowsById.set(expense.id, expense);

  api.publicSaveCase();

  assert.equal(api.publicState.selectedExpenseIds.has(expense.id), true);
  assert.match(api.publicState.storageMessage, /armazenamento.*cheio ou indisponível/);
  assert.equal(renders.length, 1);
});

test('payroll-only authority opens the remuneration filter on page one', () => {
  const { api, state, navigations } = makeView();
  api.publicState.authorities = [{ id: 'payroll-1', expenseCount: 0, remunerationCount: 1 }];
  api.publicState.expense = {
    q: 'old search', kind: 'reembolso', category: 'old', from: '2024-01', to: '2024-02',
    minAmount: '99', sort: 'amount_desc', page: 6, pageSize: 30
  };

  api.publicGoToAuthorityExpenses('payroll-1');

  assert.equal(api.publicState.expense.kind, 'remuneracao');
  assert.equal(api.publicState.expense.page, 1);
  assert.equal(api.publicState.expense.q, '');
  assert.equal(state.view, 'despesas');
  assert.deepEqual(navigations, ['despesas']);
});

test('a highlighted expense opens the matching authority, source, and period without stale filters', () => {
  for (const [period, from, to] of [['2026-08', '2026-08', '2026-08'], ['2026', '2026-01', '2026-12']]) {
    const { api, navigations } = makeView();
    api.publicState.publicSupplier = { key: 'old-supplier' };
    api.publicState.expense = { q: 'old search', kind: 'remuneracao', category: 'old', minAmount: '999', page: 8 };
    api.publicSignalCard({
      id: 'signal-1', type: 'pico', authorityId: 'authority-2', authorityName: 'Pessoa',
      period, sourceId: 'source-2', amount: 12000
    });

    api.publicInvestigateSignal('signal-1');

    assert.equal(api.publicState.publicAuthority.id, 'authority-2');
    assert.equal(api.publicState.publicAuthority.name, 'Pessoa');
    assert.equal(api.publicState.publicSupplier, null);
    assert.deepEqual(JSON.parse(JSON.stringify(api.publicState.expense)), {
      q: '', kind: 'reembolso', sourceId: 'source-2', category: '', from, to,
      minAmount: '', sort: 'amount_desc', page: 1, pageSize: 30
    });
    assert.deepEqual(navigations, ['despesas']);
  }
});

test('CSV export prefixes formula-like values with an apostrophe', async () => {
  const { api, savedFiles } = makeView();
  api.publicExportRows([{
    id: 'expense-1', authorityName: 'Pessoa', role: 'servidor',
    supplierName: '=HYPERLINK("https://bad.example")', kind: 'reembolso', amount: 10
  }], 'evidencias.csv');

  assert.equal(savedFiles.length, 1);
  assert.equal(savedFiles[0].name, 'evidencias.csv');
  const csv = (await savedFiles[0].blob.text()).replace(/^\uFEFF/, '');
  assert.ok(csv.includes('"\'=HYPERLINK(""https://bad.example"")"'));
});

test('a stale response cannot replace newer results for the same view', async () => {
  const pending = [];
  const fetchImpl = () => new Promise(resolve => pending.push(resolve));
  const { api, content, state } = makeView({ fetchImpl });
  state.view = 'base';

  const first = api.loadPublicView('base');
  const second = api.loadPublicView('base');
  pending[1]({ ok: true, json: async () => ({ totals: { authorities: 2, expenses: 20, suppliers: 3 }, sources: [] }) });
  await second;
  const newestHTML = content.innerHTML;
  assert.match(newestHTML, />2</);

  pending[0]({ ok: true, json: async () => ({ totals: { authorities: 1, expenses: 10, suppliers: 1 }, sources: [] }) });
  await first;

  assert.equal(content.innerHTML, newestHTML);
  assert.match(content.innerHTML, />2</);
});

test('follow cursors use the successful API snapshot and remain unchanged on query failure', async () => {
  const paths = [];
  let failUpdates = false;
  const response = data => ({ ok: true, json: async () => data });
  const fetchImpl = async url => {
    paths.push(url);
    if (url.includes('since=')) {
      if (failUpdates) throw new Error('temporary query failure');
      return response({ items: [], total: 4, snapshotAt: 'snapshot:after-success' });
    }
    if (url.startsWith('/api/authorities/')) return response({ authority: { id: 'authority-1', name: 'Alex' }, summary: [] });
    if (url.startsWith('/api/expenses?')) return response({ items: [], total: 0, snapshotAt: 'snapshot:profile' });
    if (url.startsWith('/api/signals?')) return response({ items: [], total: 0 });
    throw new Error(`Unexpected URL: ${url}`);
  };
  const followed = [{ id: 'authority-1', name: 'Alex', lastVisit: '2026-08-01T10:00:00.000Z', sinceCursor: 'snapshot:before' }];
  const { api, values, state } = makeView({ fetchImpl, seed: { [FOLLOW_KEY]: followed } });
  api.publicState.coverage = { sources: [] };
  api.publicState.publicAuthority = { id: 'authority-1', name: 'Alex' };
  state.view = 'autoridade';

  await api.loadPublicView('autoridade');
  const afterSuccess = api.publicRead(FOLLOW_KEY, [])[0];
  assert.ok(paths.some(url => url.includes('since=snapshot%3Abefore')));
  assert.equal(afterSuccess.sinceCursor, 'snapshot:after-success');
  assert.notEqual(afterSuccess.lastVisit, 'snapshot:after-success');
  assert.ok(Number.isFinite(Date.parse(afterSuccess.lastVisit)));
  assert.equal(api.publicState.authoritySnapshotAt, 'snapshot:after-success');

  const savedLastVisit = afterSuccess.lastVisit;
  paths.length = 0;
  failUpdates = true;
  await api.loadPublicView('autoridade');
  const afterFailure = JSON.parse(values.get(FOLLOW_KEY))[0];
  assert.ok(paths.some(url => url.includes('since=snapshot%3Aafter-success')));
  assert.equal(afterFailure.sinceCursor, 'snapshot:after-success');
  assert.equal(afterFailure.lastVisit, savedLastVisit);
});

test('follow toggles do not reuse another profile cursor; failed follow writes keep the saved list', () => {
  const { api, values, followStatus } = makeView({ failSet: [FOLLOW_KEY], seed: { [FOLLOW_KEY]: [] } });
  api.publicState.publicAuthority = { id: 'authority-a', name: 'Authority A' };
  api.publicState.authorities = [{ id: 'authority-b', name: 'Authority B' }];
  api.publicState.authorityProfileLoadedId = 'authority-a';
  api.publicState.authoritySnapshotAt = 'snapshot:authority-a';

  assert.equal(api.publicToggleFollow('authority-b'), false);
  assert.deepEqual(JSON.parse(values.get(FOLLOW_KEY)), []);
  assert.match(followStatus.textContent, /Não consegui salvar o acompanhamento/);

  const { api: removeApi, values: removeValues, listFollowStatus } = makeView({
    failSet: [FOLLOW_KEY], seed: { [FOLLOW_KEY]: [{ id: 'authority-c', name: 'Authority C', lastVisit: '2026-08-01T00:00:00.000Z' }] }
  });
  let removed = false;
  assert.equal(removeApi.publicUnfollow('authority-c', { remove() { removed = true; } }), false);
  assert.equal(removed, false);
  assert.equal(JSON.parse(removeValues.get(FOLLOW_KEY)).length, 1);
  assert.match(listFollowStatus.textContent, /Não consegui remover o acompanhamento/);
});
