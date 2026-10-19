const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const context = {
    document: { addEventListener() {}, querySelectorAll() { return []; } },
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/share-card.js'), 'utf8'), context);
  return context;
}

// Mede 10px por caractere, o bastante para testar quebra e reticências.
const fakeContext = { measureText: text => ({ width: String(text).length * 10 }), font: '' };

test('file names are ascii slugs without accents', () => {
  const { shareSlug } = load();
  assert.equal(shareSlug('Rui Falcão-x-Adriana Ventura'), 'rui-falcao-x-adriana-ventura');
  assert.equal(shareSlug(''), 'painel');
});

test('long names wrap and the last allowed line ends with an ellipsis', () => {
  const { shareWrap } = load();
  assert.deepEqual(Array.from(shareWrap(fakeContext, 'Maria da Silva', 200, 2)), ['Maria da Silva']);
  const lines = shareWrap(fakeContext, 'Nome muito longo de uma pessoa com vários sobrenomes', 120, 2);
  assert.equal(lines.length, 2);
  assert.ok(lines[1].endsWith('…'));
  assert.ok(lines.every(line => line.length * 10 <= 120));
});

test('actions render the image button and keep the current card', () => {
  const context = load();
  const html = context.shareActionsHTML({ title: 'Rui Falcão', fileName: 'Rui Falcão', rows: [] });
  assert.match(html, /data-share="image"/);
  assert.doesNotMatch(html, /pdf/i);
  assert.equal(vm.runInContext('SHARE_STATE.card', context).title, 'Rui Falcão');
  assert.equal(context.shareActionsHTML(null), '');
});

test('face-off cards draw on a dark canvas without throwing, even with missing data', () => {
  const context = load();
  const calls = [];
  const fake = new Proxy({ measureText: text => ({ width: String(text).length * 10 }), canvas: { id: 'canvas' } }, {
    get: (target, key) => key in target ? target[key] : (...args) => calls.push([key, ...args]),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  const canvas = { getContext: () => fake };
  const person = { name: 'Ana', meta: 'ABC · SP', stats: [{ label: 'Custa por mês', value: 'Sem dados', tag: '', behind: false }], categories: [], top: null };
  const result = context.shareDrawCard({ layout: 'faceoff', people: [person, { ...person, name: 'Bia' }], agreement: null, alerts: ['Sem avaliação', '0'], footnote: 'Fontes.' }, canvas);
  assert.equal(result.id, 'canvas');
  assert.equal(canvas.width, 1080);
  assert.ok(calls.some(([name, text]) => name === 'fillText' && text === 'Sem votações em comum para comparar'));
  assert.ok(calls.some(([name, text]) => name === 'fillText' && text === 'painelpublico.com'));
});

test('profile cards draw the name, cost parts and site address without the brand on top', () => {
  const context = load();
  const calls = [];
  const fake = new Proxy({ measureText: text => ({ width: String(text).length * 10 }), canvas: { id: 'canvas' } }, {
    get: (target, key) => key in target ? target[key] : (...args) => calls.push([key, ...args]),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  const canvas = { getContext: () => fake };
  const card = { layout: 'profile', title: 'Ana Lima', initials: 'AL', kicker: 'Ficha · Câmara', subtitle: 'Deputado(a) federal · ABC · SP',
    cost: { label: 'Custa em média por mês', value: 'R$ 193 mil', exact: 'R$ 193.156,14', totalCents: 19315614,
      parts: [{ name: 'Gabinete', cents: 11353006 }, { name: 'Salário', cents: 4275680 }, { name: 'Cota', cents: 3686927 }, { name: 'Auxílios', cents: 0 }], note: 'Média.' },
    presence: { label: 'Presença no Plenário', value: '92%', detail: '333 de 361 dias', share: 0.92, average: 0.92, averageLabel: 'média da Câmara: 92%' },
    categories: [{ name: 'Divulgação', share: 0.5897 }, { name: 'Aluguel de carro', share: 0.2224 }, { name: 'Combustível', share: 0.0856 }],
    categoryNote: 'Percentuais dos saldos positivos; estornos mantidos no total.', top: { value: 'R$ 99.992', who: 'Empresa', what: 'Divulgação · mai/2026' },
    footnote: 'Fontes.', disclaimer: 'Projeto pessoal.' };
  assert.equal(context.shareDrawCard(card, canvas).id, 'canvas');
  const texts = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
  for (const text of ['Ana Lima', 'R$ 193 mil', 'R$ 193.156,14', 'Gabinete', 'R$ 114 mil', 'R$ 0', '92%', 'R$ 99.992', '59%', '22%', '9%', '10%', 'Outras', 'Percentuais dos saldos positivos; estornos mantidos no total.', 'painelpublico.com']) assert.ok(texts.includes(text), text);
  assert.ok(!texts.includes('Painel Público'));
  // As porcentagens da cota fecham 100.
  assert.equal(['59%', '22%', '9%', '10%'].reduce((sum, text) => sum + parseInt(text, 10), 0), 100);
  // Sem dados: não quebra e diz o que falta.
  calls.length = 0;
  context.shareDrawCard({ layout: 'profile', title: 'Bia', cost: { label: 'Cota parlamentar por mês', value: 'Sem dados', parts: [], note: 'Ausência de dado não é zero.' },
    presence: { label: 'Presença no Plenário', value: 'Sem registro', note: 'Ausência de dado não significa zero presença.' }, categories: [], top: null, footnote: '' }, canvas);
  const empty = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
  for (const text of ['Sem dados', 'Sem registro', 'Sem notas da cota no período']) assert.ok(empty.includes(text), text);
});

test('quota legends close 100% with "Outras" in profile and face-off cards', () => {
  const context = load();
  const legend = context.shareQuotaLegend([{ name: 'A', share: 0.6549 }, { name: 'B', share: 0.2251 }, { name: 'C', share: 0.0549 }, { name: 'D', share: 0.03 }]);
  assert.deepEqual(Array.from(legend, item => item.name), ['A', 'B', 'C', 'Outras']);
  assert.equal(legend.reduce((sum, item) => sum + item.pct, 0), 100);
  assert.equal(context.shareQuotaLegend([{ name: 'A', share: 1 }]).length, 1);
  assert.equal(context.shareQuotaLegend([]).length, 0);
  const calls = [];
  const fake = new Proxy({ measureText: text => ({ width: String(text).length * 10 }), canvas: { id: 'canvas' } }, {
    get: (target, key) => key in target ? target[key] : (...args) => calls.push([key, ...args]),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  const person = { name: 'Ana', meta: 'ABC · SP', stats: [], categories: [{ name: 'Divulgação', share: 0.59 }, { name: 'Carro', share: 0.22 }, { name: 'Combustível', share: 0.09 }], top: null };
  context.shareDrawCard({ layout: 'faceoff', people: [person, { ...person, name: 'Bia' }], agreement: null, alerts: ['0', '0'], footnote: '' }, { getContext: () => fake });
  const texts = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
  assert.ok(texts.includes('Outras'));
  assert.ok(texts.includes('10%'));
});

test('face-off refund note and four category rows fit above the card footer', () => {
  const context = load();
  const calls = [];
  const fake = new Proxy({ measureText: text => ({ width: String(text).length * 10 }), canvas: { id: 'canvas' } }, {
    get: (target, key) => key in target ? target[key] : (...args) => calls.push([key, ...args]),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  const categories = [
    { name: 'Divulgação', share: 0.5 }, { name: 'Veículos', share: 0.25 },
    { name: 'Telefonia', share: 0.15 }, { name: 'Hospedagem', share: 0.1 },
  ];
  const person = { name: 'Ana', meta: 'ABC · AP', stats: [
    { label: 'Custo médio por mês', value: 'R$ 100 mil' }, { label: 'Presença no Plenário', value: '90%' },
  ], categories, categoryNote: 'Percentuais dos saldos positivos; estornos mantidos no total.', top: null };
  context.shareDrawCard({ layout: 'faceoff', people: [person, { ...person, name: 'Bia' }], agreement: null, alerts: ['0', '0'], footnote: '' }, { getContext: () => fake });
  const footerY = Math.max(...calls.filter(([name, , , width, height]) => name === 'fillRect' && width === 419 && height === 1).map(([, , y]) => y));
  const categoryLabels = new Set(['Divulgação', 'Veículos', 'Telefonia', 'Outras']);
  const categoryCalls = calls.filter(([name, text]) => name === 'fillText' && categoryLabels.has(text));
  assert.equal(footerY, 796);
  assert.equal(categoryCalls.length, 8);
  assert.ok(categoryCalls.every(([, , , y]) => y <= footerY - 18));
  assert.ok(calls.some(([name, text]) => name === 'fillText' && text.includes('estornos mantidos no total.')));
});

test('quota category distribution excludes refunds from percentage shares without hiding them from callers', () => {
  const context = load();
  const distribution = context.shareQuotaCategories([
    { nome: 'Divulgação', valor: 52000 },
    { nome: 'Locação de veículos', valor: 38100 },
    { nome: 'Telefonia', valor: 1.14 },
    { nome: 'Passagem aérea', valor: -4045.94 },
  ]);
  assert.deepEqual(Array.from(distribution.items, item => item.name), ['Divulgação', 'Locação de veículos', 'Telefonia']);
  assert.ok(Math.abs(distribution.items.reduce((sum, item) => sum + item.share, 0) - 1) < 1e-9);
  assert.equal(distribution.hasRefunds, true);
  assert.deepEqual(Array.from(context.shareQuotaCategories([{ nome: 'Estorno', valor: -5 }]).items), []);
  assert.equal(context.shareQuotaCategories([{ nome: 'Estorno', valor: -5 }]).hasRefunds, true);
  assert.equal(context.shareQuotaCategories(null).hasRefunds, false);
});

test('official photos are drawn in a circle with a source credit, and only same-domain photo URLs are loaded', async () => {
  const context = load();
  assert.equal(context.sharePhotoUrl('camara:204515'), '/api/c/foto/camara%3A204515');
  assert.equal(context.sharePhotoUrl('senado:5672'), '/api/c/foto/senado%3A5672');
  assert.equal(context.sharePhotoUrl('https://www.camara.leg.br/x.jpg'), null);
  const requested = [];
  context.fetch = async url => { requested.push(url); return { ok: true, headers: { get: () => 'image/jpeg' }, blob: async () => 'blob' }; };
  context.createImageBitmap = async () => ({ width: 300, height: 400 });
  Object.assign(context, { AbortController, setTimeout, clearTimeout });
  const images = await context.shareLoadImages({ photo: 'https://www.camara.leg.br/x.jpg', people: [{ photo: '/api/c/foto/camara%3A1' }, { photo: '/api/c/foto/senado%3A2' }] });
  assert.deepEqual(requested, ['/api/c/foto/camara%3A1', '/api/c/foto/senado%3A2']);
  assert.equal(images.size, 2);
  const calls = [];
  const fake = new Proxy({ measureText: text => ({ width: String(text).length * 10 }), canvas: { id: 'canvas' } }, {
    get: (target, key) => key in target ? target[key] : (...args) => calls.push([key, ...args]),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  const photo = '/api/c/foto/camara%3A1';
  context.shareDrawCard({ layout: 'profile', title: 'Ana', initials: 'AN', photo, photoCredit: 'Câmara dos Deputados', cost: { value: 'Sem dados', parts: [] },
    presence: { value: 'Sem registro' }, categories: [], top: null, footnote: 'Fontes.' }, { getContext: () => fake }, new Map([[photo, { width: 300, height: 400 }]]));
  assert.ok(calls.some(([name]) => name === 'drawImage'));
  assert.ok(calls.some(([name]) => name === 'clip'));
  const texts = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
  assert.ok(!texts.includes('AN'));  // com foto, sem as iniciais
  assert.ok(texts.some(text => String(text).includes('Foto: Câmara dos Deputados.')));
  calls.length = 0;
  context.shareDrawCard({ layout: 'profile', title: 'Ana', initials: 'AN', photo, photoCredit: 'Câmara dos Deputados', cost: { value: 'Sem dados', parts: [] },
    presence: { value: 'Sem registro' }, categories: [], top: null, footnote: 'Fontes.' }, { getContext: () => fake });
  const fallback = calls.filter(([name]) => name === 'fillText').map(([, text]) => text);
  assert.ok(fallback.includes('AN'));
  assert.ok(!fallback.some(text => String(text).includes('Foto:')));
});
