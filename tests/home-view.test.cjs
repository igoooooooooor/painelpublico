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
  for (const file of ['profile-data.js', 'home-view.js']) {
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

test('home attendance considers every valid record, including a person beyond the former ten', () => {
  const rows = Array.from({ length: 13 }, (_, i) => ({ id: i + 1, nome: `Pessoa ${i + 1}`,
    dias: 20, presente: i === 12 ? 1 : 19, justificadas: i === 12 ? 19 : 1, falta: 0 }));
  rows.push({ id: 14, dias: 0, presente: 0, justificadas: 0, falta: 0 });
  const html = load(rows).homePresenceCard();
  assert.match(html, /Pessoa 13/);
  assert.match(html, /data-politician="camara:13"/);
  assert.match(html, /todos os 13 registros válidos/);
  assert.doesNotMatch(html, /Pessoa 14|NaN/);
});

test('home cost and coverage use API denominators without inventing a combined monthly cost', () => {
  const ctx = load(), data = summary(), html = ctx.homeCostCard(data) + ctx.homeCoverageCard(data);
  assert.match(html, /509 deputados\(as\) com reembolsos observados, dos 513/);
  assert.match(html, /513 deputados\(as\) e 82 registros do Senado/);
  assert.match(html, /não são somados ao subsídio/);
  assert.match(html, /jan\/2026 a out\/2026/);
  assert.doesNotMatch(html, /dos 10|se elegeram|por mês, em média/);
  data.reembolsos.deputado = { total: null, media: null, comRegistros: 0, periodo: {} };
  assert.match(ctx.homeCostCard(data), /Sem dados/);
});

test('home category answer and ranking reflect complete API results, not named sample people', () => {
  const ctx = load(), data = summary();
  ctx.state.quiz = 'Viagens';
  const html = ctx.homeCategoriesCard(data);
  assert.match(html, /A maior categoria foi Serviços/);
  assert.match(html, /Estorno R\$ -5/);
  assert.doesNotMatch(html, /Divulgação levou|NaN/);
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
