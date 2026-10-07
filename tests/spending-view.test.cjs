const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const SpendingAnalysis = require('../frontend/scripts/spending-analysis.js');
const editorialPath = path.join(__dirname, '..', 'data', 'snapshots', 'editorial.json');
const editorialTest = {
  skip: !fs.existsSync(editorialPath) && 'Snapshot editorial local não disponível no clone público',
};

const viewSource = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'scripts', 'spending-view.js'), 'utf8');

function deputy(id, name, overrides = {}) {
  return {
    id,
    nome: name,
    partido: 'ABC',
    uf: 'DF',
    cota: {
      total: 80000,
      limite: 100000,
      notas: 3,
      porMes: {},
      lancamentos: [],
      categorias: [],
    },
    ...overrides,
  };
}

function makeView({ deputies, radar, state: stateOverrides = {}, scrollY = 17 } = {}) {
  const D = deputies || [];
  const byId = Object.fromEntries(D.map(item => [item.id, item]));
  const state = {
    view: 'gastos', dep: null, vote: null,
    spendingMode: 'alertas', spendingType: 'todos', spendingDep: 'todos', spendingSort: 'valor',
    ...stateOverrides,
  };
  const savedFiles = [];
  const calls = [];
  const hist = [];
  const context = {
    RADAR: radar || { alerts: [], rankings: [], coverage: { invoicesIncluded: 0, invoicesReported: 0 } },
    DATA: { geradoEm: '2026-10-06' },
    SpendingAnalysis,
    D,
    byId,
    state,
    hist,
    window: { scrollY },
    MES: ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro'],
    URL,
    Blob,
    dmy: value => value,
    brl: (value, digits = 0) => `R$ ${Number(value).toFixed(digits).replace('.', ',')}`,
    esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;'),
    mil: value => String(Math.round(value / 1000)),
    go: (...args) => { calls.push(args); state.view = args[0]; },
    salvarArquivo: (blob, name) => savedFiles.push({ blob, name }),
  };
  vm.createContext(context);
  vm.runInContext(`${viewSource}\nthis.__api = { filteredSpendingAlerts, radarHome, vGastos, exportSpendingAlerts, invoiceURL, goSpendingDetail };`, context);
  return { api: context.__api, context, state, savedFiles, calls, hist, byId };
}

function parseCsvRow(line) {
  const values = [];
  let value = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted && char === '"' && line[i + 1] === '"') {
      value += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === ';' && !quoted) {
      values.push(value);
      value = '';
    } else {
      value += char;
    }
  }
  values.push(value);
  return values;
}

function readRealData() {
  const source = fs.readFileSync(editorialPath, 'utf8');
  return JSON.parse(source);
}

test('view filters real dataset signals by deputy and type, with stable value sorting and matching counts', editorialTest, () => {
  const data = readRealData();
  const radar = SpendingAnalysis.analyze(data.deputados);
  const selectedId = '204536';
  const { api, state } = makeView({ deputies: data.deputados, radar });

  state.spendingDep = selectedId;
  state.spendingType = 'pico';
  state.spendingSort = 'valor';
  const filtered = api.filteredSpendingAlerts();
  assert.equal(filtered.length, 3);
  assert.ok(filtered.every(alert => alert.depId === selectedId && alert.type === 'pico'));
  assert.deepEqual(filtered.map(alert => alert.amount), [...filtered.map(alert => alert.amount)].sort((a, b) => b - a));

  state.spendingType = 'todos';
  const html = api.vGastos();
  assert.match(html, /5 sinais encontrados/);
  assert.match(html, /Picos mensais <b>3<\/b>/);
  assert.match(html, /Notas altas <b>1<\/b>/);
  assert.match(html, /Concentração <b>1<\/b>/);

  state.spendingDep = 'todos';
  state.spendingSort = 'sinais';
  const byType = api.filteredSpendingAlerts();
  const typeOrder = byType.map(alert => ({ pico: 0, nota: 1, categoria: 2 }[alert.type]));
  assert.deepEqual(typeOrder, [...typeOrder].sort((a, b) => a - b));
  state.spendingSort = 'nome';
  const names = api.filteredSpendingAlerts().map(alert => data.deputados.find(item => item.id === alert.depId).nome);
  assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b, 'pt-BR')));

  const home = api.radarHome();
  assert.match(home, /data-go="radar"/);
});

test('CSV exports only the filtered real-data category and uses the cota total as its denominator', editorialTest, async () => {
  const data = readRealData();
  const radar = SpendingAnalysis.analyze(data.deputados);
  const chosen = radar.alerts.find(alert => alert.type === 'categoria' && alert.depId === '160674');
  assert.ok(chosen);
  const { api, state, savedFiles } = makeView({ deputies: data.deputados, radar });
  state.spendingDep = chosen.depId;
  state.spendingType = 'categoria';
  api.exportSpendingAlerts();

  assert.equal(savedFiles.length, 1);
  assert.equal(savedFiles[0].name, 'painel-publico-sinais-2026-10-06.csv');
  const csv = await savedFiles[0].blob.text();
  const lines = csv.replace(/^\uFEFF/, '').split('\r\n');
  assert.equal(lines.length, 2, 'one header and exactly the selected alert');
  const cells = parseCsvRow(lines[1]);
  assert.equal(cells[0], data.deputados.find(item => item.id === chosen.depId).nome);
  assert.equal(cells[3], 'Concentração por categoria');
  assert.equal(cells[4], chosen.amount.toFixed(2).replace('.', ','));
  assert.equal(cells[6], data.deputados.find(item => item.id === chosen.depId).cota.total.toFixed(2).replace('.', ','));
  assert.equal(cells[8], `https://www.camara.leg.br/deputados/${chosen.depId}?ano=2026`);
  assert.match(cells[5], /representa/);
});

test('CSV neutralizes formula-like values after leading whitespace', async () => {
  const person = deputy('7', ' \t=SUM(1,1)');
  const radar = {
    alerts: [{
      id: 'categoria:7:Divulgação', depId: '7', type: 'categoria', title: 'Categoria',
      amount: 40000, share: 0.5, category: 'Divulgação',
    }],
    rankings: [], coverage: { invoicesIncluded: 0, invoicesReported: 0 },
  };
  const { api, savedFiles } = makeView({ deputies: [person], radar });
  api.exportSpendingAlerts();
  const csv = await savedFiles[0].blob.text();
  const cells = parseCsvRow(csv.replace(/^\uFEFF/, '').split('\r\n')[1]);
  assert.equal(cells[0], "' \t=SUM(1,1)");
});

test('invoice links accept only HTTPS Câmara hosts and reject script and lookalike URLs', () => {
  const { api } = makeView();
  assert.equal(api.invoiceURL({ url: 'https://www.camara.leg.br/cota/documento.pdf' }), 'https://www.camara.leg.br/cota/documento.pdf');
  assert.equal(api.invoiceURL({ url: 'https://dados.camara.leg.br/documento.pdf' }), 'https://dados.camara.leg.br/documento.pdf');
  assert.equal(api.invoiceURL({ url: 'javascript:alert(1)' }), null);
  assert.equal(api.invoiceURL({ url: 'http://www.camara.leg.br/documento.pdf' }), null);
  assert.equal(api.invoiceURL({ url: 'https://camara.leg.br.evil.example/documento.pdf' }), null);
  assert.equal(api.invoiceURL({ url: 'https://camara.leg.br@evil.example/documento.pdf' }), null);
});
