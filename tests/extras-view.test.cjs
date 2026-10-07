const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function comparison(a, b) {
  const context = {
    DATA: { votacoes: [], presencaTodos: [] }, CARGO: { senador: 'Senador(a)' },
    document: { querySelector: () => null, getElementById: () => ({}), addEventListener() {} },
    MutationObserver: class { observe() {} }, addEventListener() {}, setTimeout() {},
    esc: String, cidNome: String, cidAvatar: () => '', cidMil: value => `R$ ${value}`,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/extras-view.js'), 'utf8'), context);
  return context.extCmpTabela([a, b]);
}
const profile = (id, total) => ({ pessoa: { id, name: id, role: 'senador' }, total, media: 100,
  categorias: [], fornecedores: [], alertas: [], meses: [] });

test('comparison keeps missing spending unavailable instead of awarding it a zero or -100% result', () => {
  const html = comparison(profile('senado:a', null), profile('senado:b', 100));
  assert.match(html, /Sem dados/);
  assert.doesNotMatch(html, /R\$ null|R\$ 0<|NaN|Infinity|-100%|cmp-v best/);
});

test('comparison preserves an observed zero reimbursement', () => {
  const html = comparison(profile('senado:a', 0), profile('senado:b', 100));
  assert.match(html, /R\$ 0</);
  assert.match(html, /-100%/);
  assert.doesNotMatch(html, /Sem dados|NaN|Infinity/);
});
