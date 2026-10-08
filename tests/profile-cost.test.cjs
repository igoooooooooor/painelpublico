const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8');

function load() {
  const context = {
    DATA: { deputados: [], votacoes: [], presencaTodos: [] }, URL,
    document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  };
  vm.createContext(context);
  vm.runInContext(read('profile-data.js') + '\n' + read('profile-cost.js'), context);
  return context;
}

const PERIODS = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07'];
const payrollUrl = period => `https://www.camara.leg.br/deputados/1/remuneracao-deputado-detalhado?mesAno=${period.slice(5)}2026`;

function costFixture({ used = PERIODS, exercise = 'in_office' } = {}) {
  const months = Object.fromEntries(PERIODS.map(period => [period, {
    period, exercise, daysInOffice: 31, eligible: used.includes(period), exclusionReasons: used.includes(period) ? [] : ['missing_parts'],
    valuesCents: { remuneration: 4636619, allowances: 425300, quota: 3000000, office: 14000000 },
    christmasBonusCents: period === '2026-06' ? 2270997 : null,
    sources: Object.fromEntries(['remuneration', 'allowances', 'quota', 'office'].map(key => [key, { url: payrollUrl(period), period }])),
  }]));
  const part = value => ({ months: used, amountCents: value * used.length, averageCents: value, usedMonthsAverageCents: used.length ? value : null,
    sources: used.map(period => ({ url: payrollUrl(period), period })) });
  return {
    id: 'camara:1', house: 'camara', periodStart: '2026-01', periodEnd: '2026-07', months, usedMonths: used,
    monthlyAverageCents: used.length ? 22061919 : null,
    parts: { remuneration: part(4636619), allowances: part(425300), quota: part(3000000), office: part(14000000) },
    christmasBonus: { months: ['2026-06'], amountCents: 2270997, sources: [] },
    complement: { months: ['2026-01'], signedAmountCents: -174700 },
    payrollInventoryPartialMonths: ['2026-01'],
  };
}

const JARGON = /competência|rubrica|folha complementar|livro original|composição/i;

test('principal shows the monthly average, the months used and the 13th apart', () => {
  const { profileCostAnswer } = load();
  const html = profileCostAnswer(costFixture());
  assert.match(html, /Custa em média/);
  assert.match(html, /R\$\s?220\.619,19/);
  assert.match(html, /jan–jul\/2026, 7 meses/);
  assert.match(html, /13º adiantado em junho: <b class="mono">R\$\s?22\.709,97<\/b>/);
  assert.equal((html.match(/data-cost-part=/g) || []).length, 4);
  assert.match(html, /remuneracao-deputado-detalhado\?mesAno=072026/);
  assert.doesNotMatch(html, /pelo menos/);
  assert.doesNotMatch(html, JARGON);
});

test('non-consecutive months are listed instead of shown as a range', () => {
  const { profileCostAnswer } = load();
  assert.match(profileCostAnswer(costFixture({ used: ['2026-01', '2026-03'] })), /jan, mar\/2026, 2 meses/);
});

test('outside the mandate is neither zero nor missing data', () => {
  const { profileCostAnswer } = load();
  const html = profileCostAnswer(costFixture({ used: [], exercise: 'outside_mandate' }));
  assert.match(html, /Não estava no mandato entre janeiro e julho de 2026/);
  assert.doesNotMatch(html, /R\$\s?0,00/);
  assert.doesNotMatch(html, /Custa em média/);
});

test('without a month with all four parts there is no average, only parts and the reason', () => {
  const { profileCostAnswer } = load();
  const html = profileCostAnswer(costFixture({ used: [] }));
  assert.match(html, /Sem média mensal/);
  assert.match(html, /quatro partes/);
  assert.doesNotMatch(html, /Custa em média/);
  assert.doesNotMatch(html, JARGON);
});

test('details keep the complement signed and the anonymous inventory as a footnote', () => {
  const { profileCostDetails } = load();
  const html = profileCostDetails(costFixture());
  assert.match(html, /-R\$\s?1\.747,00/);
  assert.match(html, /sinal negativo/);
  assert.match(html, /citizen-cost-footnote/);
  assert.equal((html.match(/entra na média/g) || []).length, 7);
});
