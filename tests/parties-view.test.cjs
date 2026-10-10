const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(data, senate = { presenca: null, votacoes: null, loading: false }, chamberCatalog = CHAMBER_CATALOG) {
  const context = {
    citizenGet: () => new Promise(() => {}), citizenErrorMessage: String, citizenState: { cache: new Map() },
    DATA: data, ROLE_LABELS: { deputado: 'Deputado(a) federal' }, state: { view: 'x' },
    document: { addEventListener() {} }, esc: String, citizenName: String, citizenAvatar: () => '',
    formatCitizenAmount: value => `R$ ${value}`,
    skel: () => '<loading>', skL: () => '<loading>',
    profilePresenceRows() { return (data.presencaTodos || []).filter(p => p.dias > 0
      && p.presente >= 0 && p.falta >= 0 && p.justificadas >= 0
      && p.presente + p.falta + p.justificadas === p.dias); },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/dates.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, '../frontend/scripts/parties-view.js'), 'utf8'), context);
  context.senate = senate;
  context.profileSenateEnsure = () => {};
  context.profileSenateLoading = () => senate.loading;
  context.profileSenateSource = section => senate[section];
  context.profileVoteList = chamber => chamber === 'senado' ? senate.votacoes?.items || [] : data.votacoes || [];
  context.profilePresenceRows = (chamber = 'camara') => (chamber === 'senado' ? senate.presenca?.items || [] : data.presencaTodos || []).filter(p => p.dias > 0
    && p.presente >= 0 && p.falta >= 0 && p.justificadas >= 0
    && p.presente + p.falta + p.justificadas === p.dias);
  context.profileRegisteredPresenceRows = () => (senate.presenca?.items || []).filter(p => Number.isFinite(p.presente) && p.presente > 0);
  context.profileSource = section => {
    const period = section.period || (section.startDate && section.endDate ? `de ${section.startDate} a ${section.endDate}` : '');
    const annual = (section.sources || []).map(source => source.sourceUrl
      ? `<a href="${source.sourceUrl}">${source.year} · ${source.status}</a>` : `${source.year} · ${source.status}`).join(' · ');
    return `<span class="src">${period}${section.sourceUrl ? `<a href="${section.sourceUrl}">Fonte e período</a>` : ''}${annual ? `Fontes por ano: ${annual}` : ''}</span>`;
  };
  context.profileVoteButton = (vote, content, className = 'vt') => String(vote.id).startsWith('senado:')
    ? `<a class="${className}" href="${vote.sourceUrl || ''}">${content}</a>`
    : `<button type="button" class="${className}" data-vote="${vote.id}">${content}</button>`;
  context.voteRowsForItem = v => String(v.id).startsWith('senado:') ? v.rows || [] : data.votosCompletos?.[v.id] || [];
  if (chamberCatalog) vm.runInContext('partyState', context).chamberCatalog = chamberCatalog;
  return context;
}
const voteRow = (id, partyCode, choice) => [id, `Dep ${id}`, partyCode, 'SP', choice];
const DATA = {
  votacoes: [{ id: 'v1', titulo: 'Aberta', secreta: false }, { id: 'v2', titulo: 'Secreta', secreta: true }],
  votosCompletos: {
    v1: [voteRow(1, 'AAA', 'Sim'), voteRow(2, 'AAA', 'Sim'), voteRow(3, 'AAA', 'Não'), voteRow(4, 'BBB', 'Não'), voteRow(5, 'BBB', 'Não Votou'), voteRow(6, 'BBB', 'Não votou')],
    v2: [voteRow(1, 'AAA', 'Presente')],
  },
  presencaTodos: [
    { id: 1, partido: 'AAA', presente: 9, falta: 1, justificadas: 0, dias: 10 },
    { id: 2, partido: 'AAA', presente: 7, falta: 3, justificadas: 0, dias: 10 },
    // A legenda atual pode divergir da legenda registrada na votação antiga (id 4 = BBB).
    { id: 4, partido: 'AAA', presente: 8, falta: 2, justificadas: 0, dias: 10 },
    { id: 7, partido: 'BBB', presente: 0, falta: 0, justificadas: 0, dias: 0 },
    { id: 8, partido: 'BBB', presente: 1, falta: 0, justificadas: 0, dias: 2 },
  ],
};
// Catálogo do Placar: totais por sigla publicada; partido ausente ou detalhe ausente não vira zero.
const CHAMBER_CATALOG = {
  available: true, period: { start: '2023-02-01', end: '2026-10-09' },
  coverage: { detail: '2 decisões nominais conferidas.' },
  items: [
    { id: '1-1', date: '2026-10-01', proposition: 'PL 1/2026', title: 'Aberta', partyTotals: {
      AAA: { yes: 2, no: 1, other: 0 }, BBB: { yes: 0, no: 1, other: 2 }, PCDOB: { yes: 1, no: 0, other: 0 } } },
    { id: '2-1', date: '2026-09-01', proposition: 'PEC 2/2026', title: 'Sem detalhe', partyTotals: null },
  ],
};
const party = (acronym, deputyData) => ({ sigla: acronym, membros: 3, deputado: deputyData, senador: null, top: [] });

test('chamber party votes come from the scoreboard catalog without turning missing totals into zero votes', () => {
  const ctx = load(DATA);
  const [aaa, missing] = ctx.partyVotes('AAA');
  assert.equal(aaa.yesCount, 2); assert.equal(aaa.noCount, 1); assert.equal(aaa.majority, 'Sim');
  assert.equal(missing.majority, null);
  assert.equal(ctx.partyVoteAlignment(ctx.partyVotes('AAA')), 2 / 3);
  assert.equal(ctx.partyVotes('BBB')[0].majority, 'Não');
  assert.equal(ctx.partyVotes('BBB')[0].otherCount, 2);
  assert.equal(ctx.partyVotes('CCC')[0].majority, null);
  assert.equal(ctx.partyVotes('PCdoB')[0].majority, 'Sim');
  assert.deepEqual(ctx.partyAttendance('BBB'), null);
});

test('chamber vote comparison waits for the catalog and explains its scope', () => {
  const pending = load(DATA, undefined, null).partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(pending, /Como votaram · Câmara[\s\S]*loading/);
  const html = load(DATA).partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(html, /ficaram do mesmo lado em 0,00% das vezes \(0 de 1 votação nominal comparável\)/);
  assert.match(html, /texto principal de PL, PLP e PEC no Plenário, de 01\/02\/2023 a 09\/10\/2026/);
  assert.match(html, /2 decisões nominais conferidas/);
  assert.match(html, /data-vote="1-1"/);
});

test('party comparison shows missing data as unavailable and never highlights it', () => {
  const ctx = load(DATA);
  const html = ctx.partyComparisonTable(party('AAA', { membros: 3, comDados: 2, media: 100, alertas: 1 }),
    party('BBB', { membros: 3, comDados: 0, media: null, alertas: 0 }));
  assert.match(html, /Sem dados/);
  assert.match(html, /80%/);
  assert.match(html, /lados opostos/);
  assert.match(html, /Registros na lista disponível/);
  assert.doesNotMatch(html, /Bancada no Congresso|parlamentares em exercício/);
  assert.doesNotMatch(html, /NaN|Infinity|R\$ null|cmp-v best/);
});

test('party comparison adds Senate registered presence counts and nominal vote records without mixing Chamber data', () => {
  const senate = {
    loading: false,
    presenca: { status: 'partial', period: '2026 · 20 sessões', sessionCount: 20, sourceUrl: 'https://senado.example.test/presenca', items: [
      { id: 'senado:1', partido: 'AAA', presente: 1, falta: null, justificadas: null, dias: null },
      { id: 'senado:2', partido: 'AAA', presente: 4, falta: null, justificadas: null, dias: null },
      { id: 'senado:3', partido: 'BBB', presente: 6, falta: null, justificadas: null, dias: null },
      { id: 'senado:4', partido: 'AAA', presente: 0, falta: null, justificadas: null, dias: null },
    ] },
    votacoes: { status: 'imported', period: 'Votações nominais em 2026', sourceUrl: 'https://senado.example.test/votos', items: [
      { id: 'senado:V1', titulo: 'Matéria do Senado', secreta: false, sourceUrl: 'https://senado.example.test/v1', rows: [
        ['senado:1', 'Senadora 1', 'AAA', 'SP', 'Sim'], ['senado:2', 'Senador 2', 'AAA', 'RJ', 'Sim'], ['senado:3', 'Senador 3', 'BBB', 'MG', 'Não'],
      ] },
      { id: 'senado:V2', titulo: 'Participação sem voto', secreta: false, sourceUrl: 'https://senado.example.test/v2', rows: [
        ['senado:1', 'Senadora 1', 'AAA', 'SP', 'Presente'], ['senado:3', 'Senador 3', 'BBB', 'MG', 'Sim'],
      ] },
    ] },
  };
  const ctx = load(DATA, senate);
  assert.equal(ctx.partyAttendance('AAA', 'senado').media, 2.5);
  assert.equal(ctx.partyAttendance('AAA', 'senado').n, 2);
  assert.equal(ctx.partyVotes('AAA', 'senado')[0].majority, 'Sim');
  assert.equal(ctx.partyVoteAlignment(ctx.partyVotes('AAA', 'senado')), 1);
  const html = ctx.partyComparisonTable(party('AAA', { membros: 3, comDados: 2, media: 100, alertas: 1 }),
    party('BBB', { membros: 3, comDados: 1, media: 200, alertas: 0 }));
  assert.match(html, /Presenças registradas por senador\(a\) · Senado/);
  assert.match(html, /<b>2,5<\/b><small> sessões em média/);
  assert.match(html, /<b>6<\/b><small> sessões em média/);
  assert.match(html, /20 listas de sessões consultadas/);
  assert.match(html, /votações nominais · Senado/);
  assert.match(html, /Como votaram · Senado/);
  assert.match(html, /Matéria do Senado/);
  assert.match(html, /Votações nominais em 2026/);
  assert.match(html, /href="https:\/\/senado\.example\.test\/v1"/);
  assert.doesNotMatch(html, /href="https:\/\/senado\.example\.test\/v1"[^>]*data-vote/);
  const presenceRow = html.split('\n').find(line => line.includes('Presenças registradas por senador(a) · Senado'));
  assert.ok(presenceRow);
  assert.doesNotMatch(presenceRow, /class="cmp-v best"|%/);
});

test('missing Senate activity stays unavailable and loading uses skeletons', () => {
  const absent = load(DATA);
  assert.equal(absent.partyAttendance('AAA', 'senado'), null);
  assert.equal(absent.partyVotes('AAA', 'senado').length, 0);
  const html = absent.partyComparisonTable(party('AAA', { membros: 3, comDados: 2, media: 100, alertas: 1 }),
    party('BBB', { membros: 3, comDados: 0, media: null, alertas: 0 }));
  assert.match(html, /Votações nominais do Senado ainda não importadas/);
  assert.match(html, /Sem dados/);
  assert.doesNotMatch(html, /NaN|Infinity|R\$ null/);
  const presenceRow = html.split('\n').find(line => line.includes('Presenças registradas por senador(a) · Senado'));
  assert.ok(presenceRow);
  assert.doesNotMatch(presenceRow, /<b>0<\/b>|%|class="cmp-v best"/);

  const withoutComparable = load(DATA, { loading: false, presenca: null, votacoes: { status: 'imported', items: [] } });
  const emptyVotes = withoutComparable.partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(emptyVotes, /Sem votações com escolhas nominais registradas para ambos os partidos/);
  assert.doesNotMatch(emptyVotes, /0 de 0/);

  const loading = load(DATA, { loading: true, presenca: null, votacoes: null });
  const pending = loading.partyComparisonTable(party('AAA', { membros: 3, comDados: 2, media: 100, alertas: 1 }),
    party('BBB', { membros: 3, comDados: 0, media: null, alertas: 0 }));
  assert.match(pending, /loading/);
});

test('party vote comparison labels Senate source bounds and does not infer missing data as no votes', () => {
  const senate = {
    loading: false, presenca: null,
    votacoes: {
      status: 'partial', startDate: '2023-02-01', endDate: '2026-10-08',
      sources: [
        { year: 2023, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2023' },
        { year: 2024, status: 'unavailable', sourceUrl: null },
        { year: 2026, status: 'partial', sourceUrl: 'https://senado.example.test/votos/2026' },
      ],
      items: [{ id: 'senado:V1', titulo: 'Votação do Senado', secreta: false, rows: [
        ['senado:1', 'Senadora 1', 'AAA', 'SP', 'Sim'], ['senado:2', 'Senador 2', 'BBB', 'RJ', 'Não'],
      ] }],
    },
  };
  const ctx = load(DATA, senate);
  const html = ctx.partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(html, /de 2023-02-01 a 2026-10-08/);
  assert.match(html, /2023 · imported/);
  assert.match(html, /2024 · unavailable/);
  assert.match(html, /2026 · partial/);
  assert.match(html, /href="https:\/\/senado\.example\.test\/votos\/2023"/);
  assert.match(html, /Votação do Senado/);

  senate.votacoes = { status: 'unavailable', startDate: '2023-02-01', endDate: '2026-10-08', sources: [], items: [] };
  const unavailable = ctx.partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(unavailable, /Dados de votações nominais do Senado indisponíveis neste recorte/);
  assert.doesNotMatch(unavailable, /Sem votações com escolhas nominais registradas para ambos os partidos neste recorte/);
});

test('party votes show ten per page and the pair has a shareable path', () => {
  const items = Array.from({ length: 12 }, (_, index) => ({ id: `${index + 1}-1`, date: '2026-10-01', proposition: 'PL', title: `Votação ${index + 1}`,
    partyTotals: { AAA: { yes: 1, no: 0, other: 0 }, BBB: { yes: index < 9 ? 1 : 0, no: index < 9 ? 0 : 1, other: 0 } } }));
  const ctx = load(DATA, undefined, { ...CHAMBER_CATALOG, items });
  const html = ctx.partyComparisonTable(party('AAA', { membros: 3 }), party('BBB', { membros: 3 }));
  assert.match(html, /ficaram do mesmo lado em 75,00% das vezes \(9 de 12 votações nominais comparáveis\)/);
  assert.equal((html.match(/data-vote="\d+-1"/g) || []).length, 10);
  assert.match(html, /Mostrar mais \(2\)/);
  vm.runInContext("partyState.selected = ['PCdoB', 'S/Partido']", ctx);
  assert.equal(ctx.partyPairPath(), '/partidos/PCdoB-vs-S%2FPartido');
  assert.deepEqual([...ctx.partyPairFromPath('/partidos/PCdoB-vs-S%2FPartido')], ['PCdoB', 'S/Partido']);
  assert.equal(ctx.partyPairFromPath('/partidos'), null);
});
