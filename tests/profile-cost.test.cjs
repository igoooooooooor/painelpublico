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
  vm.runInContext(read('dates.js') + '\n' + read('profile-data.js') + '\n' + read('profile-cost.js'), context);
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
    id: 'camara:1', house: 'camara', periodStart: '2023-02', periodEnd: '2026-07', months, usedMonths: used,
    monthlyAverageCents: used.length ? 22061919 : null,
    parts: { remuneration: part(4636619), allowances: part(425300), quota: part(3000000), office: part(14000000) },
    christmasBonus: { months: ['2026-06'], amountCents: 2270997, sources: [] },
    complement: { months: ['2026-01'], signedAmountCents: -174700 },
    payrollInventoryPartialMonths: ['2026-01'],
  };
}

/* Julho com valores diferentes da média, como o caso real que motivou o número principal do mês. */
function latestFixture() {
  const cost = costFixture();
  cost.months['2026-07'].valuesCents = { remuneration: 4636619, allowances: 0, quota: 3370100, office: 16023700 };
  return cost;
}

const JARGON = /competência|rubrica|folha complementar|livro original|composição/i;

test('principal shows the latest complete month, with the mandate average as context', () => {
  const { profileCostAnswer, profileCostDetails } = load();
  const html = profileCostAnswer(latestFixture());
  assert.match(html, /<span>Custou<\/span><b class="mono">R\$ 240 mil<\/b><span>em jul\/2026<\/span>/);
  assert.match(html, /Valor exato: <span class="mono">R\$\s?240\.304,19<\/span>, a soma das quatro partes abaixo/);
  assert.match(html, /Média do mandato: <span class="mono">R\$\s?220\.619,19<\/span> por mês, jan\/2026–jul\/2026, 7 meses em exercício\./);
  assert.match(html, /Mês mais recente · Câmara · mandato 2023–2027/);
  assert.doesNotMatch(html, /Custa em média|\(média\)|<small>\/mês/);
  assert.match(html, /Só entram meses com salário, auxílios, cota e verba de gabinete publicados\./);
  assert.match(profileCostDetails(costFixture()), /13º salário em junho de 2026: <b class="mono">R\$\s?22\.709,97<\/b>/);
  assert.match(html, /data-profile-open="expenses">Como calculamos/);
  assert.doesNotMatch(html, /class="citizen-cost-note"|13º salário/);
  assert.match(profileCostDetails(costFixture()), /os números não são comparáveis/);
  assert.match(profileCostDetails(costFixture()), /Fora da conta: encargos do gabinete e apartamento funcional/);
  assert.equal((html.match(/data-cost-part=/g) || []).length, 4);
  assert.match(html, /remuneracao-deputado-detalhado\?mesAno=072026/);
  assert.doesNotMatch(html, /pelo menos/);
  assert.doesNotMatch(html, JARGON);
});

test('the rows are the parts of that same month and add up to the total', () => {
  const { profileCostAnswer } = load();
  const html = profileCostAnswer(latestFixture());
  const row = key => html.match(new RegExp(`data-cost-part="${key}">[\\s\\S]*?<b class="mono">([^<]*)<`))[1];
  assert.match(row('remuneration'), /R\$\s?46\.366,19/);
  assert.match(row('office'), /R\$\s?160\.237,00/);
  assert.match(row('quota'), /R\$\s?33\.701,00/);
  assert.match(row('allowances'), /R\$\s?0,00/);
  const cents = text => Number(text.replace(/[^\d]/g, ''));
  assert.equal(['remuneration', 'office', 'quota', 'allowances'].reduce((sum, key) => sum + cents(row(key)), 0), 24030419);
  assert.match(html, /Ver as notas de jul\/2026/);
});

test('a confirmed gap in the latest month stays out of the sum and is never shown as zero', () => {
  const { profileCostAnswer } = load();
  const cost = latestFixture();
  cost.months['2026-07'].valuesCents.office = null;
  cost.months['2026-07'].sourceGaps = ['office'];
  const html = profileCostAnswer(cost);
  assert.match(html, /data-cost-part="office">[\s\S]*?Não publicado pela Câmara/);
  assert.match(html, /R\$\s?80\.067,19/);
});

test('a 13th salary paid in the latest month is shown apart from the sum', () => {
  const { profileCostAnswer } = load();
  const cost = costFixture({ used: PERIODS.slice(0, 6) });
  const html = profileCostAnswer(cost);
  assert.match(html, /em jun\/2026/);
  assert.match(html, /13º salário em jun\/2026: <b class="mono">R\$\s?22\.709,97<\/b> <span>\(fora da soma\)/);
});

test('the principal month needs three months of margin before the data snapshot', () => {
  const { profileCostAnswer, profileCostLatest } = load();
  assert.equal(profileCostLatest(latestFixture(), '2026-10-13T03:17:32+00:00').period, '2026-07');
  assert.doesNotMatch(profileCostAnswer(latestFixture(), '2026-10-13'), /fica fora|ainda pode receber/);
  const earlier = profileCostAnswer(latestFixture(), '2026-09-20');
  assert.match(earlier, /<span>Custou<\/span><b class="mono">R\$ 221 mil<\/b><span>em jun\/2026/);
  assert.match(earlier, /Jul\/2026 fica fora do número principal: a cota desses meses ainda recebe notas\./);
  // A média do mandato continua com todos os meses com as quatro partes.
  assert.match(earlier, /Média do mandato: <span class="mono">R\$\s?220\.619,19<\/span> por mês, jan\/2026–jul\/2026, 7 meses/);
  const recent = profileCostAnswer(costFixture({ used: ['2026-07'] }), '2026-08-05');
  assert.match(recent, /em jul\/2026[\s\S]*A cota de jul\/2026 ainda pode receber notas; o valor pode subir\./);
});

test('non-consecutive months are listed instead of shown as a range', () => {
  const { profileCostAnswer } = load();
  assert.match(profileCostAnswer(costFixture({ used: ['2026-01', '2026-03'] })), /jan\/2026, mar\/2026, 2 meses/);
});

test('outside the mandate is neither zero nor missing data', () => {
  const { profileCostAnswer } = load();
  const html = profileCostAnswer(costFixture({ used: [], exercise: 'outside_mandate' }));
  assert.match(html, /Não estava no mandato entre fevereiro de 2023 e julho de 2026/);
  assert.doesNotMatch(html, /R\$\s?0,00/);
  assert.doesNotMatch(html, /Custa em média/);
});

test('the period ends at the snapshot month, not at a fixed month', () => {
  const { profileCostAnswer, profileCostDetails } = load();
  const cost = costFixture();
  const period = '2026-09';
  cost.months[period] = { ...cost.months['2026-07'], period, christmasBonusCents: null,
    sources: Object.fromEntries(['remuneration', 'allowances', 'quota', 'office'].map(key => [key, { url: payrollUrl(period), period }])) };
  cost.periodEnd = period;
  cost.usedMonths = [...PERIODS, period];
  for (const part of Object.values(cost.parts)) part.sources.push({ url: payrollUrl(period), period });
  assert.match(profileCostAnswer(cost), /Ver as notas de set\/2026/);
  assert.match(profileCostDetails(cost), /Custo do mandato mês a mês · fev\/2023–set\/2026/);
  assert.match(profileCostDetails(cost), /data-cost-month="2026-09"/);
  const outside = costFixture({ used: [], exercise: 'outside_mandate' });
  outside.periodEnd = period;
  assert.match(profileCostAnswer(outside), /entre fevereiro de 2023 e setembro de 2026/);
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

test('month ranges cross years and the mandate period is named', () => {
  const { profileCostMonthList, profileCostAnswer, profileCostDetails } = load();
  assert.equal(profileCostMonthList(['2023-02', '2023-03', '2024-11', '2025-01', '2025-02']),
    'fev/2023–mar/2023, nov/2024, jan/2025–fev/2025, 5 meses');
  assert.equal(profileCostMonthList(['2023-01', '2027-02']), 'nenhum mês');
  const html = profileCostAnswer(costFixture());
  assert.match(html, /mandato 2023–2027/);
  assert.match(profileCostDetails(costFixture()), /Valores da época, sem correção pela inflação/);
});

test('a confirmed source gap is shown empty, never as zero', () => {
  const { profileCostAnswer, profileCostDetails } = load();
  const cost = costFixture();
  cost.sourceGapMonths = { '2026-03': ['office'] };
  cost.months['2026-03'].valuesCents.office = null;
  cost.months['2026-03'].sourceGaps = ['office'];
  assert.doesNotMatch(profileCostAnswer(cost), /não publicou a verba do gabinete/);
  assert.match(profileCostDetails(cost), /não publicou a verba do gabinete de mar\/2026/);
  const details = profileCostDetails(cost);
  assert.match(details, /data-cost-month="2026-03"[\s\S]*Não publicado pela Câmara/);
  assert.match(details, /data-cost-year="2026"><summary>/);  // nenhum ano abre sozinho
});

test('quota source of a mandate month opens the month notes instead of the annual file', () => {
  const { profileCostDetails, profileCostNotesHTML } = load();
  const details = profileCostDetails(costFixture());
  assert.match(details, /data-cost-notes="2026-03" data-cost-person="camara:1"/);
  assert.match(details, /Ver as notas da cota deste mês/);
  assert.match(profileCostNotesToggleSafe(load(), 'camara:1', '2025-03'), /data-cost-notes="2025-03"/);
  assert.doesNotMatch(profileCostNotesToggleSafe(load(), 'camara:1', '2023-01'), /details/);
  const html = profileCostNotesHTML({ periodo: '2026-03', total: 77262.6, complemento: null,
    fonte: { url: 'https://www.camara.leg.br/cotas/Ano-2026.csv.zip' },
    notas: [{ data: '2026-03-20', fornecedor: 'Táxi Aéreo', categoria: 'Fretamento de avião', valor: 67750,
      documentUrl: 'https://www.camara.leg.br/cota-parlamentar/documentos/publ/1/2026/1.pdf' }] }, 'camara:220714');
  assert.match(html, /Táxi Aéreo[\s\S]*20\/03\/2026 · Fretamento de avião/);
  assert.match(html, /R\$\s?77\.262,60/);
  assert.match(html, /ideCadastro<\/code> = 220714 e <code>numMes<\/code> = 3/);
  assert.match(html, /1\.pdf/);
  assert.match(html, /Todas as notas vêm do arquivo oficial da Câmara, com ou sem documento/);
  const withoutDocument = profileCostNotesHTML({ periodo: '2026-01', total: 114.08, complemento: null,
    notas: [{ data: null, fornecedor: 'CELULAR FUNCIONAL', categoria: 'Telefone', valor: 114.08, documentUrl: null }] }, 'camara:1');
  assert.match(withoutDocument, /Documento não publicado pela Câmara/);
  assert.doesNotMatch(withoutDocument, /Sem link/);
});

function profileCostNotesToggleSafe(context, id, period) {
  return context.profileCostNotesToggle(id, period, 'x');
}
