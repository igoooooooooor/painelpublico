const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const SpendingAnalysis = require('../frontend/scripts/spending-analysis.js');
const editorialPath = path.join(__dirname, '..', 'data', 'snapshots', 'editorial.json');

const baseDeputy = (overrides = {}) => ({
  id: 42,
  cota: {
    total: 100000,
    limite: 120000,
    notas: 4,
    porMes: { '1': 10000, '2': 10000, '3': 10000, '4': 10000 },
    categorias: [],
    lancamentos: [],
  },
  ...overrides,
});

test('rules expose the agreed inclusive thresholds', () => {
  assert.deepEqual(SpendingAnalysis.rules, {
    spikeRatio: 1.75,
    spikeDelta: 10000,
    minPreviousMonths: 3,
    invoiceMinimum: 10000,
    categoryShare: 0.5,
    categoryMinimum: 30000,
  });
});

test('spike fires at both boundaries and reports a January-to-current baseline', () => {
  const deputy = baseDeputy({ cota: {
    total: 120000,
    limite: 120000,
    notas: 0,
    porMes: { '1': 10000, '2': 20000, '3': 10000, '4': 10000, '5': 20000 },
    categorias: [],
    lancamentos: [],
  } });
  const result = SpendingAnalysis.analyze([deputy], { closedThrough: 5, year: 2026 });
  const alert = result.alerts.find(item => item.type === 'pico');
  assert.ok(alert);
  assert.equal(alert.month, 5);
  assert.equal(alert.baseline, 10000);
  assert.equal(alert.amount, 20000);
  assert.equal(alert.ratio, 2);
  assert.deepEqual(alert.previousMonths, [
    { month: 1, amount: 10000 },
    { month: 2, amount: 20000 },
    { month: 3, amount: 10000 },
    { month: 4, amount: 10000 },
  ]);

  const exact = baseDeputy({ cota: {
    total: 100000, limite: 100000, notas: 0,
    porMes: { '1': 20000, '2': 20000, '3': 20000, '4': 35000 },
    categorias: [], lancamentos: [],
  } });
  const boundary = SpendingAnalysis.analyze([exact], { closedThrough: 4 }).alerts;
  assert.equal(boundary.length, 1);
  assert.equal(boundary[0].ratio, 1.75);
});

test('spike history must be complete and consecutive from January; zero baseline is ignored', () => {
  const missingMonth = baseDeputy({ cota: {
    total: 50000, limite: 50000, notas: 0,
    porMes: { '1': 10000, '2': 10000, '4': 10000, '5': 50000 },
    categorias: [], lancamentos: [],
  } });
  const zeroBaseline = baseDeputy({ id: 43, cota: {
    total: 50000, limite: 50000, notas: 0,
    porMes: { '1': 0, '2': 0, '3': 0, '4': 50000 },
    categorias: [], lancamentos: [],
  } });
  const alerts = SpendingAnalysis.analyze([missingMonth, zeroBaseline], { closedThrough: 5 }).alerts;
  assert.equal(alerts.length, 0);
});

test('invoice and category thresholds are inclusive and exclude incomplete categories', () => {
  const deputy = baseDeputy({ cota: {
    total: 60000,
    limite: 90000,
    notas: 2,
    porMes: {},
    categorias: [
      { nome: 'Divulgação', valor: 30000 },
      { nome: 'Sem detalhe no arquivo aberto', valor: 50000 },
      { nome: 'Escritório', valor: 29999.99 },
    ],
    lancamentos: [
      { data: '2026-07-01', fornecedor: 'Fornecedor A', cat: 'Divulgação', valor: 10000, url: 'https://example.test/a.pdf' },
      { data: '2026-07-02', fornecedor: 'Fornecedor B', cat: 'Escritório', valor: 9999.99 },
    ],
  } });
  const result = SpendingAnalysis.analyze([deputy]);
  assert.equal(result.alerts.length, 2);
  const invoiceAlert = result.alerts.find(item => item.type === 'nota');
  const categoryAlert = result.alerts.find(item => item.type === 'categoria');
  assert.equal(invoiceAlert.amount, 10000);
  assert.equal(invoiceAlert.invoice, deputy.cota.lancamentos[0]);
  assert.equal(invoiceAlert.evidence.invoiceIndex, 0);
  assert.equal(categoryAlert.category, 'Divulgação');
  assert.equal(categoryAlert.amount, 30000);
  assert.equal(categoryAlert.share, 0.5);
});

test('negative, missing, nonnumeric and incomplete evidence is ignored without mutating inputs', () => {
  const deputy = baseDeputy({ cota: {
    total: '100000',
    limite: 0,
    notas: '7',
    porMes: { '1': -100, '2': 10000, '3': 10000, '4': 10000, '5': 50000 },
    categorias: [{ nome: 'Aluguel', valor: 50000 }],
    lancamentos: [
      { valor: -12000 },
      { valor: '20000' },
      { valor: Infinity },
    ],
  } });
  const before = structuredClone(deputy);
  const result = SpendingAnalysis.analyze([deputy], { closedThrough: 5 });
  assert.deepEqual(result.alerts, []);
  assert.deepEqual(result.rankings, [{ depId: 42, total: null, limit: 0, share: null }]);
  assert.equal(result.coverage.invoicesIncluded, 3);
  assert.equal(result.coverage.invoicesReported, 0);
  assert.deepEqual(deputy, before);
});

test('stable IDs and deterministic order follow deputy, type, month and source index', () => {
  const deputies = [
    baseDeputy({ id: 8, cota: {
      total: 80000, limite: 100000, notas: 2,
      porMes: { '1': 10000, '2': 10000, '3': 10000, '4': 30000 },
      categorias: [{ nome: 'Divulgação', valor: 40000 }],
      lancamentos: [{ valor: 15000 }, { valor: 12000 }],
    } }),
    baseDeputy({ id: 3, cota: {
      total: 40000, limite: 50000, notas: 1,
      porMes: {}, categorias: [], lancamentos: [{ valor: 10000 }],
    } }),
  ];
  const first = SpendingAnalysis.analyze(deputies, { closedThrough: 4 });
  const second = SpendingAnalysis.analyze(deputies, { closedThrough: 4 });
  assert.deepEqual(first, second);
  assert.deepEqual(first.alerts.map(item => item.id), [
    'nota:3:0',
    'categoria:8:Divulgação',
    'nota:8:0',
    'nota:8:1',
    'pico:8:4',
  ]);
  assert.deepEqual(first.rankings.map(item => item.depId), [8, 3]);
});

test('rankings keep over-limit shares and mark unavailable numbers as null', () => {
  const result = SpendingAnalysis.analyze([
    baseDeputy({ id: 2, cota: { total: 120, limite: 100 } }),
    baseDeputy({ id: 1, cota: { total: 50, limite: 0 } }),
    baseDeputy({ id: 3, cota: {} }),
  ]);
  assert.deepEqual(result.rankings, [
    { depId: 2, total: 120, limit: 100, share: 1.2 },
    { depId: 1, total: 50, limit: 0, share: null },
    { depId: 3, total: null, limit: null, share: null },
  ]);
});

test('real dataset sanity: coverage counts the six included records per deputy', {
  skip: !fs.existsSync(editorialPath) && 'Snapshot editorial local não disponível no clone público',
}, () => {
  const source = fs.readFileSync(editorialPath, 'utf8');
  const data = JSON.parse(source);
  const result = SpendingAnalysis.analyze(data.deputados);
  const reported = data.deputados.reduce((sum, deputy) => sum + deputy.cota.notas, 0);
  assert.equal(result.coverage.deputies, data.deputados.length);
  assert.equal(result.coverage.invoicesIncluded, data.deputados.length * 6);
  assert.equal(result.coverage.invoicesReported, reported);
  assert.ok(result.rankings.every(item => Number.isFinite(item.total) && Number.isFinite(item.limit)));
  assert.ok(result.alerts.every(item => ['pico', 'nota', 'categoria'].includes(item.type)));
  assert.ok(result.alerts.every(item => !item.invoice || data.deputados.some(dep => dep.cota.lancamentos.includes(item.invoice))));
});
