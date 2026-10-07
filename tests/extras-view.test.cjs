const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function comparison(a, b) {
  const senate = { presenca: null, votacoes: null, loading: false };
  const context = {
    DATA: { votacoes: [], presencaTodos: [] }, CARGO: { senador: 'Senador(a)' },
    document: { querySelector: () => null, getElementById: () => ({}), addEventListener() {} },
    MutationObserver: class { observe() {} }, addEventListener() {}, setTimeout() {},
    esc: String, cidNome: String, cidAvatar: () => '', cidMil: value => `R$ ${value}`, cidQuem: () => 'Deputado(a)',
    cid: { cache: new Map() }, state: { view: 'comparar' }, skel: () => '<loading>',
    pageHead: () => '<header>', cidErroMsg: error => error.message, dmy: String,
    cidFonte: p => p.id === 'senado:55' ? 'https://www25.senado.leg.br/web/senadores/senador/-/perfil/55' : null,
  };
  vm.createContext(context);
  context.senate = senate;
  context.profilePresenceRows = (chamber = 'camara') => (chamber === 'senado' ? senate.presenca?.items || [] : context.DATA.presencaTodos || []).filter(p => p && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
  context.profilePresence = id => {
    const canonical = String(id).startsWith('senado:') ? String(id) : `camara:${String(id).replace(/^camara:/, '')}`;
    const chamber = canonical.startsWith('senado:') ? 'senado' : 'camara';
    return context.profilePresenceRows(chamber).find(p => (chamber === 'senado' ? String(p.id) : `camara:${p.id}`) === canonical) || null;
  };
  context.profileRegisteredPresenceRows = () => (senate.presenca?.items || []).filter(p => Number.isFinite(p.presente) && p.presente > 0);
  context.profileRegisteredPresence = id => context.profileRegisteredPresenceRows().find(p => String(p.id) === String(id)) || null;
  context.profileSenateEnsure = () => {};
  context.profileSenateLoading = () => senate.loading;
  context.profileSenateSource = section => senate[section];
  context.profileVoteList = chamber => chamber === 'senado' ? senate.votacoes?.items || [] : context.DATA.votacoes || [];
  context.profileVoteRows = vote => String(vote.id).startsWith('senado:') ? vote.rows || [] : context.DATA.votosCompletos?.[vote.id] || [];
  context.profileVotes = id => {
    const canonical = String(id).startsWith('senado:') ? String(id) : `camara:${String(id).replace(/^camara:/, '')}`;
    const chamber = canonical.startsWith('senado:') ? 'senado' : 'camara';
    const key = canonical.startsWith('senado:') ? canonical : canonical.slice(7);
    return context.profileVoteList(chamber).map(v => ({
      v, voto: (() => {
        const row = context.profileVoteRows(v).find(record => String(record[0]) === key);
        return row ? (chamber === 'senado' ? row[4] ?? null : (v.secreta ? 'Presente' : row[4] ?? 'Presente')) : null;
      })(),
    }));
  };
  context.profileVoteButton = (vote, content, className = 'vt') => String(vote.id).startsWith('senado:')
    ? `<a class="${className}" href="${vote.sourceUrl || ''}">${content}</a>`
    : `<button type="button" class="${className}" data-vote="${vote.id}">${content}</button>`;
  context.profileData = value => ({ id: value.id, pessoa: value, contato: null, projetos: null, remuneracao: null, mandato: null });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/extras-view.js'), 'utf8') +
    '\nthis.__api = { ext, extCmpTabela, extCmpBusca, extCmpPickerList, vComparar, extImpostoCard, extVotos, extVotosDe, extPres, extPresRows, extPresBar, extFichaExtra };', context);
  return { html: context.__api.extCmpTabela([a, b]), api: context.__api, context, senate };
}
const profile = (id, total) => ({ pessoa: { id, name: id, role: 'senador' }, total, media: 100,
  categorias: [], fornecedores: [], alertas: [], meses: [] });

test('comparison keeps missing spending unavailable instead of awarding it a zero or -100% result', () => {
  const { html } = comparison(profile('senado:a', null), profile('senado:b', 100));
  assert.match(html, /Sem dados/);
  assert.doesNotMatch(html, /R\$ null|R\$ 0<|NaN|Infinity|-100%|cmp-v best/);
});

test('comparison preserves an observed zero reimbursement', () => {
  const { html } = comparison(profile('senado:a', 0), profile('senado:b', 100));
  assert.match(html, /R\$ 0</);
  assert.match(html, /-100%/);
  assert.match(html, /Presença registrada · Senado/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('presence helpers omit invalid and zero-day rows, and missing presence stays unavailable', () => {
  const { api, context } = comparison(profile('camara:a', 1), profile('camara:b', 2));
  context.DATA.presencaTodos = [
    { id: 1, nome: 'Pessoa válida', partido: 'AAA', uf: 'SP', dias: 2, presente: 1, falta: 1, justificadas: 0 },
    { id: 2, nome: 'Sem dias', partido: 'BBB', uf: 'RJ', dias: 0, presente: 0, falta: 0, justificadas: 0 },
    { id: 3, nome: 'Inconsistente', partido: 'CCC', uf: 'MG', dias: 3, presente: 1, falta: 0, justificadas: 0 },
  ];
  const rows = api.extPresRows();
  assert.equal(rows.length, 1);
  assert.equal(api.extPres(1).presente, 1);
  assert.equal(api.extPres(2), null);
  assert.equal(api.extPresBar({ presente: 0, falta: 0, justificadas: 0, dias: 0 }), '');
});

test('voter lists contain source rows only and never infer non-voters from the current presence roster', () => {
  const { api, context } = comparison(profile('camara:1', 1), profile('camara:2', 2));
  context.DATA.votacoes = [
    { id: 'open', data: '2026-09-01', titulo: 'Aberta', secreta: false },
    { id: 'secret', data: '2026-09-02', titulo: 'Secreta', secreta: true },
  ];
  context.DATA.presencaTodos = [
    { id: 1, nome: 'Registrada', partido: 'AAA', uf: 'SP', dias: 1, presente: 1, falta: 0, justificadas: 0 },
    { id: 2, nome: 'Sem linha de voto', partido: 'BBB', uf: 'RJ', dias: 1, presente: 1, falta: 0, justificadas: 0 },
  ];
  context.DATA.votosCompletos = {
    open: [[1, 'Registrada', 'AAA', 'SP', 'Sim']],
    secret: [[1, 'Registrada', 'AAA', 'SP', null]],
  };
  assert.deepEqual(Array.from(api.extVotos(context.DATA.votacoes[0]), row => Array.from(row)), [[1, 'Registrada', 'AAA', 'SP', 'Sim']]);
  assert.deepEqual(Array.from(api.extVotos(context.DATA.votacoes[1]), row => Array.from(row)), [[1, 'Registrada', 'AAA', 'SP', 'Presente']]);
  const ficha = api.extFichaExtra('camara:2');
  assert.match(ficha, /1\/1/);
  assert.match(ficha, /Votações selecionadas do Placar · 2/);
  assert.match(ficha, /Sem registro importado/);
  assert.match(api.extFichaExtra('camara:3'), /Sem registro importado para este perfil/);
  const secretFicha = api.extFichaExtra('camara:1');
  assert.match(secretFicha, /Presença registrada · voto secreto/);
  assert.match(secretFicha, /Presença no Plenário ↗/);
  assert.doesNotMatch(ficha, /Sim|Não votou/);
  assert.match(api.extFichaExtra('senado:55'), /Sem dados de presença do Senado importados/);
  assert.match(api.extFichaExtra('senado:55'), /Votações nominais do Senado ainda não importadas/);
  assert.match(api.extFichaExtra('senado:55'), /https:\/\/www25\.senado\.leg\.br\/web\/senadores\/senador\/-\/perfil\/55/);
  assert.doesNotMatch(api.extFichaExtra('senado:55'), /Sim|Não votou/);
});

test('profile comparison adds neutral availability and mandate details without ranking them', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.profileData = value => value.id.endsWith(':1') ? ({
    id: value.id, pessoa: value, mandato: { participacao: 'Titular', exercicio: 'Em exercício' },
    contato: { email: 'a@example.test', status: 'partial' }, projetos: { status: 'partial', items: [{}] },
    gabinete: { amount: 125000, staffActive: 4, period: 'Jan–Jun/2026', months: 6, fetchedAt: '2026-10-07' },
    remuneracao: { amount: 46366.19 },
  }) : ({ id: value.id, pessoa: value, mandato: null, contato: null, projetos: null, gabinete: null, remuneracao: null });
  const html = api.extCmpTabela([profile('camara:1', 100), profile('camara:2', 200)]);
  assert.match(html, /Participação e exercício/);
  assert.match(html, /Disponível em recorte parcial/);
  assert.match(html, /Disponíveis em recorte parcial/);
  assert.match(html, /125\.000,00/);
  assert.match(html, /Jan–Jun\/2026/);
  assert.match(html, /4 pessoas ativas/);
  assert.match(html, /referência do cargo, não pagamento individual/);
  assert.match(html, /Sem dados importados/);
  for (const label of ['Participação e exercício', 'Contato institucional', 'Projetos', 'Equipe e verba de gabinete', 'Remuneração de referência']) {
    const row = html.split('\n').find(line => line.includes(label));
    assert.ok(row, `linha ausente: ${label}`);
    assert.doesNotMatch(row, /class="cmp-v best"/);
  }
});

test('Senate profile comparison keeps presence and registered nominal votes within the Senate source', () => {
  const { api, senate } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  senate.presenca = { status: 'partial', period: '2026 · 18 sessões', sessionCount: 18, sourceUrl: 'https://senado.example.test/presenca', items: [
    { id: 'senado:55', nome: 'Senadora A', partido: 'AAA', uf: 'SP', dias: null, presente: 7, falta: null, justificadas: null },
    { id: 'senado:56', nome: 'Senador B', partido: 'BBB', uf: 'RJ', dias: null, presente: 12, falta: null, justificadas: null },
  ] };
  senate.votacoes = { status: 'imported', period: 'Votações nominais em 2026', sourceUrl: 'https://senado.example.test/votos', items: [
    { id: 'senado:V1', data: '2026-09-01', titulo: 'Matéria 1', secreta: false, sourceUrl: 'https://senado.example.test/v1', rows: [
      ['senado:55', 'Senadora A', 'AAA', 'SP', 'Sim'], ['senado:56', 'Senador B', 'BBB', 'RJ', 'Não'],
    ] },
    { id: 'senado:V2', data: '2026-09-02', titulo: 'Matéria 2', secreta: false, sourceUrl: 'https://senado.example.test/v2', rows: [
      ['senado:55', 'Senadora A', 'AAA', 'SP', 'Presente'], ['senado:56', 'Senador B', 'BBB', 'RJ', 'Sim'],
    ] },
    { id: 'senado:V3', data: '2026-09-03', titulo: 'Matéria 3', secreta: false, sourceUrl: 'https://senado.example.test/v3', rows: [
      ['senado:55', 'Senadora A', 'AAA', 'SP', 'Sim'],
    ] },
  ] };
  const html = api.extCmpTabela([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.match(html, /Presença registrada · Senado/);
  assert.match(html, /<b>7<\/b>/);
  assert.match(html, /<b>12<\/b>/);
  assert.match(html, /2026 · 18 sessões/);
  assert.match(html, /18 listas de sessões consultadas/);
  const presenceRow = html.split('\n').find(line => line.includes('Presença registrada · Senado'));
  assert.ok(presenceRow);
  assert.doesNotMatch(presenceRow, /%|class="cmp-v best"/);
  assert.match(html, /Fonte e período/);
  assert.match(html, /registraram o mesmo voto em 0 de 1 votações nominais comparáveis no Senado/);
  assert.match(html, /Matéria 1/);
  assert.doesNotMatch(html, /Matéria 2|Matéria 3/);
  assert.match(html, /href="https:\/\/senado\.example\.test\/v1"/);
  assert.match(html, /Como votaram · Senado/);
  const ficha = api.extFichaExtra('senado:55');
  assert.match(ficha, /Presença registrada · sem voto/);
  assert.match(ficha, /Votações secretas foram excluídas/);
});

test('cross-house profile comparison leaves presence methods unranked and omits vote agreement', () => {
  const { api, context, senate } = comparison(profile('camara:1', 100), profile('senado:55', 200));
  context.DATA.presencaTodos = [{ id: 1, nome: 'Deputado A', partido: 'AAA', uf: 'SP', dias: 4, presente: 4, falta: 0, justificadas: 0 }];
  senate.presenca = { status: 'partial', period: '18 sessões', sessionCount: 18, sourceUrl: 'https://senado.example.test/presenca', items: [
    { id: 'senado:55', nome: 'Senadora B', partido: 'BBB', uf: 'RJ', dias: null, presente: 3, falta: null, justificadas: null },
  ] };
  senate.votacoes = { status: 'imported', period: '2026', sourceUrl: 'https://senado.example.test/votos', items: [
    { id: 'senado:V1', titulo: 'Matéria Senado', secreta: false, sourceUrl: 'https://senado.example.test/v1', rows: [] },
  ] };
  const html = api.extCmpTabela([profile('camara:1', 100), profile('senado:55', 200)]);
  assert.match(html, /Presença · Câmara/);
  assert.match(html, /Presença registrada · Senado/);
  assert.match(html, /Metodologias de presença de casas diferentes não são comparadas/);
  assert.match(html, /Votações de casas diferentes não são comparadas/);
  const rows = html.split('\n').filter(line => line.includes('Presença · Câmara') || line.includes('Presença registrada · Senado'));
  assert.equal(rows.length, 2);
  rows.forEach(row => assert.doesNotMatch(row, /class="cmp-v best"/));
  assert.doesNotMatch(html, /Matéria Senado|1 votação nominal com registro/);
});

test('Senate profile absence remains unavailable and loading uses a skeleton', () => {
  const { api, senate } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  senate.loading = true;
  const loading = api.extFichaExtra('senado:55');
  assert.match(loading, /loading/);
  senate.loading = false;
  const absent = api.extFichaExtra('senado:55');
  assert.match(absent, /Sem dados de presença do Senado importados/);
  assert.match(absent, /Votações nominais do Senado ainda não importadas/);
  assert.doesNotMatch(absent, /0\/0|0% presente|Votações nominais do Senado · 0/);
  const comparisonHtml = api.extCmpTabela([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.match(comparisonHtml, /Sem votos nominais comparáveis/);
  assert.doesNotMatch(comparisonHtml, /0 de 0/);
});

test('Senate vote rows preserve null individual votes and source statuses', () => {
  const { api } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  const vote = { id: 'senado:V1', secreta: false, rows: [
    ['senado:55', 'Senadora A', 'AAA', 'SP', null],
    ['senado:56', 'Senador B', 'BBB', 'RJ', 'Atividade parlamentar'],
  ] };
  const rows = api.extVotos(vote);
  assert.equal(rows[0][4], null);
  assert.equal(rows[1][4], 'Atividade parlamentar');
  assert.doesNotMatch(JSON.stringify(rows), /"Presente"/);
});

test('comparison suggestions load from the full API with an empty query and use its results', async () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const picker = { innerHTML: '' };
  context.document.getElementById = id => id === 'ext-cmp-res' ? picker : null;
  const calls = [];
  const roster = Array.from({ length: 8 }, (_, i) => ({ id: `camara:${i === 7 ? 513 : 500 + i}`,
    name: `Pessoa ${i + 1}`, role: 'deputado', party: 'PT', uf: 'SP' }));
  context.cidGet = async path => { calls.push(path); return { itens: roster }; };

  const html = api.vComparar();
  assert.deepEqual(calls, ['/api/c/politicos?pageSize=8&page=1&ordem=nome']);
  assert.match(html, /loading/);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(picker.innerHTML, /data-cmp-add="camara:513"/);
  assert.doesNotMatch(picker.innerHTML, /data-cmp-add="camara:7"/);
});

test('comparison suggestions show an API error and a retry control', async () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const picker = { innerHTML: '' };
  context.document.getElementById = id => id === 'ext-cmp-res' ? picker : null;
  context.cidGet = async () => { throw new Error('offline'); };
  api.vComparar();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(picker.innerHTML, /offline/);
  assert.match(picker.innerHTML, /data-cmp-retry/);
});

test('tax card receives the observed Chamber roster total as an argument', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.DATA.arrecadacao = {
    inicio: '2026-01-01', ate: '2026-10-06', acumulado: 1000000,
    populacao: 100, url: 'https://example.test/arrecadacao',
  };
  const html = api.extImpostoCard(300000);
  assert.match(html, /cota registrada para os deputados\(as\) da lista no recorte \(R\$ 300000\)/);
  assert.doesNotMatch(html, /Tudo o que a Câmara gastou/);
});
