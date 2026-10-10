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
