const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'scripts', 'cidadao-view.js'),
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
    byId: {},
    clearTimeout,
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
    setTimeout: schedule,
    state,
  };
  vm.createContext(context);
  vm.runInContext(source + '\nthis.__api = { cid, cidPolRow, cidPolCoverageHTML, cidPolCoverageNotesHTML, cidLoadPol, vPolitico };', context);
  return { api: context.__api, elements, state, events };
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
  assert.doesNotMatch(profile, /cid-months|Nenhum alerta|R\$.*0 mil/);
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
