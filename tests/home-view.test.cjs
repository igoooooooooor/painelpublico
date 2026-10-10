const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(presence = [], request = async () => ({})) {
  const context = {
    DATA: { presencaTodos: presence, votacoes: [], votosCompletos: {}, perfis: { profiles: {} } }, URL,
    state: { view: 'home', quiz: null }, citizenState: { cache: new Map() }, citizenGet: request,
    citizenErrorMessage: error => error.message, rerender() {},
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    brl: value => 'R$ ' + value.toLocaleString('pt-BR'), mil: value => String(Math.round(value / 1000)),
    formatCitizenAmount: value => 'R$ ' + value, formatShortDate: value => value.slice(0, 10),
    citizenAvatar: person => `<img data-id="${person.id}">`, attendanceBar: () => '<span>barra</span>',
    skel: () => 'Carregando', CATS_H: ['--cat1', '--cat2'],
  };
  vm.createContext(context);
  for (const file of ['dates.js', 'profile-data.js', 'home-view.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts', file), 'utf8'), context);
  }
  return context;
}
function summary() {
  return {
    parlamentares: { deputado: { total: 513, comReembolsos: 509 }, senador: { total: 82, comReembolsos: 79 } },
    reembolsos: { deputado: { total: 129_000_000, media: 253_438.11, comRegistros: 509,
      periodo: { inicio: '2026-01', fim: '2026-10' } } },
    categoriasCamara: [{ nome: 'Serviços', valor: 80 }, { nome: 'Viagens', valor: 40 }, { nome: 'Estorno', valor: -5 }],
    topCamara: Array.from({ length: 13 }, (_, i) => ({ id: `camara:${100 - i}`, nome: `Pessoa ${100 - i}`, gasto: 100 - i })),
  };
}

test('home cost card uses the monthly cost from the API per House and keeps missing values explicit', () => {
  const ctx = load(), data = summary();
  data.custoMensal = {
    deputado: { media: 199_365, minimo: 52_037, maximo: 259_578, comCusto: 510, total: 513 },
    senador: { media: 301_532, minimo: 126_481, maximo: 556_592, comCusto: 76, total: 82 },
  };
  const html = ctx.homeCostCard(data);
  assert.match(html, /R\$ 199<small> mil/);
  assert.match(html, /menor R\$ 52 mil/);
  assert.match(html, /maior R\$ 260 mil/);
  assert.match(html, /Senador\(a\), em média<\/span><b>R\$ 302 mil\/mês/);
  assert.match(html, /Média de 510 deputados\(as\) com custo identificado, dos 513/);
  assert.match(html, /compare só dentro da mesma Casa/);
  data.custoMensal = { deputado: { media: null, minimo: null, maximo: null, comCusto: 0, total: 513 } };
  assert.match(ctx.homeCostCard(data), /Sem dados/);
  assert.doesNotMatch(ctx.homeCostCard(data), /NaN/);
});

test('home categories list every category with refunds kept and the ranking uses complete API results', () => {
  const ctx = load(), data = summary();
  const html = ctx.homeCategoriesCard(data);
  assert.match(html, /3 categorias/);
  assert.match(html, /Serviços/);
  assert.match(html, /Estorno<\/span><b>R\$ -5/);
  assert.match(html, /preservando estornos/);
  assert.doesNotMatch(html, /NaN/);
  const ranking = ctx.homeTopCard(data);
  assert.match(ranking, /data-politician="camara:100"/);
  assert.match(ranking, /entre 13 deputados\(as\) com dados/);
  assert.equal((ranking.match(/data-politician=/g) || []).length, 5);
});

test('failed home summary stays explicit and can retry without any sample fallback', async () => {
  let calls = 0;
  const ctx = load([], async () => { calls += 1; if (calls === 1) throw new Error('Falha de rede'); return summary(); });
  ctx.homeLoad();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(ctx.homeCostCard(null), /Falha de rede/);
  assert.match(ctx.homeCostCard(null), /data-summary-retry/);
  ctx.homeLoad();
  assert.equal(calls, 1);
  ctx.homeReset(); ctx.homeLoad();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
});
