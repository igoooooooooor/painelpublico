const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(data) {
  const context = {
    DATA: data, CARGO: { deputado: 'Deputado(a) federal' }, state: { view: 'x' },
    document: { addEventListener() {} }, esc: String, cidNome: String, cidAvatar: () => '',
    cidMil: value => `R$ ${value}`,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/partidos-view.js'), 'utf8'), context);
  context.extVotos = v => data.votosCompletos[v.id];
  return context;
}
const voto = (id, partido, v) => [id, `Dep ${id}`, partido, 'SP', v];
const DATA = {
  votacoes: [{ id: 'v1', titulo: 'Aberta', secreta: false }, { id: 'v2', titulo: 'Secreta', secreta: true }],
  votosCompletos: {
    v1: [voto(1, 'AAA', 'Sim'), voto(2, 'AAA', 'Sim'), voto(3, 'AAA', 'Não'), voto(4, 'BBB', 'Não'), voto(5, 'BBB', 'Não Votou'), voto(6, 'BBB', 'Não votou')],
    v2: [voto(1, 'AAA', 'Presente')],
  },
  presencaTodos: [{ id: 1, partido: 'AAA', presente: 9, dias: 10 }, { id: 2, partido: 'AAA', presente: 7, dias: 10 }],
};
const party = (sigla, deputado) => ({ sigla, membros: 3, deputado, senador: null, top: [] });

test('party votes ignore secret ballots and absentees, and report the majority side', () => {
  const ctx = load(DATA);
  const [aaa] = ctx.parVotos('AAA');
  assert.equal(aaa.sim, 2); assert.equal(aaa.nao, 1); assert.equal(aaa.maioria, 'Sim');
  assert.equal(ctx.parVotos('AAA').length, 1);
  assert.equal(ctx.parUnidade(ctx.parVotos('AAA')), 2 / 3);
  assert.equal(ctx.parVotos('BBB')[0].maioria, 'Não');
  assert.equal(ctx.parVotos('CCC')[0].maioria, null);
});

test('party comparison shows missing data as unavailable and never highlights it', () => {
  const ctx = load(DATA);
  const html = ctx.parTabela(party('AAA', { membros: 3, comDados: 2, media: 100, alertas: 1 }),
    party('BBB', { membros: 3, comDados: 0, media: null, alertas: 0 }));
  assert.match(html, /Sem dados/);
  assert.match(html, /80%/);
  assert.match(html, /lados opostos/);
  assert.doesNotMatch(html, /NaN|Infinity|R\$ null|cmp-v best/);
});
