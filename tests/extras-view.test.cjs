const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function comparison(a, b) {
  const senate = { presenca: null, votacoes: null, loading: false };
  const context = {
    DATA: { votacoes: [], presencaTodos: [] }, ROLE_LABELS: { senador: 'Senador(a)' },
    document: { querySelector: () => null, getElementById: () => ({}), addEventListener() {} },
    MutationObserver: class { observe() {} }, addEventListener() {}, setTimeout() {},
    esc: String, citizenName: String, citizenAvatar: () => '', formatCitizenAmount: value => `R$ ${value}`, citizenRoleDescription: () => 'Deputado(a)',
    citizenState: { cache: new Map() }, state: { view: 'compare' }, skel: () => '<loading>',
    pageHead: () => '<header>', citizenErrorMessage: error => error.message, formatShortDate: String,
    brl: value => `R$ ${value}`, SHORT_MONTHS: ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
    citizenSourceUrl: p => p.id === 'senado:55' ? 'https://www25.senado.leg.br/web/senadores/senador/-/perfil/55' : null,
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
    return context.profileVoteList(chamber).map(vote => ({
      vote, recordedVote: (() => {
        const row = context.profileVoteRows(vote).find(record => String(record[0]) === key);
        return row ? (chamber === 'senado' ? row[4] ?? null : (vote.secreta ? 'Presente' : row[4] ?? 'Presente')) : null;
      })(),
    }));
  };
  context.profileVoteButton = (vote, content, className = 'vt') => String(vote.id).startsWith('senado:')
    ? `<a class="${className}" href="${vote.sourceUrl || ''}">${content}</a>`
    : `<button type="button" class="${className}" data-vote="${vote.id}">${content}</button>`;
  context.profileData = value => ({ id: value.id, person: value, contact: null, projects: null, compensation: null, mandate: null });
  context.profileHref = id => /^camara:\d+$/.test(String(id)) ? `/deputado/${String(id).slice(7)}` : /^senado:\d+$/.test(String(id)) ? `/senador/${String(id).slice(7)}` : null;
  context.profileLinkOpen = (id, className) => context.profileHref(id) ? `<a class="${className}" href="${context.profileHref(id)}" data-politician="${id}">` : `<button type="button" class="${className}" data-politician="${id}">`;
  context.profileLinkClose = id => context.profileHref(id) ? '</a>' : '</button>';
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/dates.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, '../frontend/scripts/profile-cost.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, '../frontend/scripts/share-card.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, '../frontend/scripts/extras-view.js'), 'utf8') +
    '\nthis.__api = { extrasState, comparisonTable, comparisonShareCard, searchComparisonPeople, comparisonPickerList, comparisonView, taxCard, taxWidget, taxTick, voteRowsForItem, votesForPerson, attendanceForPerson, attendanceRows, attendanceBar, attendanceView, comparisonPersonCard, profileExtras };', context);
  return { html: context.__api.comparisonTable([a, b]), api: context.__api, context, senate };
}
const profile = (id, total) => ({ pessoa: { id, name: id, role: 'senador' }, total, mediaMensal: total, media: 100,
  categorias: [], fornecedores: [], alertas: [], meses: [] });

test('an empty Placar list names the period covered since February 2023, not a single year', () => {
  const { api } = comparison(profile('senado:a', 100), profile('senado:b', 100));
  const html = api.profileExtras('camara:404');
  assert.match(html, /Nenhuma votação do Placar com registro para esta pessoa desde fev\/2023\./);
  assert.doesNotMatch(html, /Placar em 2026/);
});

test('comparison shows the period of the settled-months quota average, not of every note', () => {
  const a = { ...profile('senado:a', 100), periodo: { inicio: '2026-07', fim: '2026-10', meses: 4 }, mediaPeriodo: { inicio: '2026-07', fim: '2026-07', meses: 1 } };
  const b = { ...profile('senado:b', 100), periodo: { inicio: '2026-01', fim: '2026-03', meses: 3 } };
  const { api, context } = comparison(a, b);
  const months = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const label = value => `${months[Number(value.slice(5)) - 1]}/${value.slice(0, 4)}`;
  context.citizenQuotaPeriod = (start, end) => (start === end ? label(start) : `${label(start)}–${label(end)}`);
  const html = api.comparisonTable([a, b]);
  assert.match(html, /<div class="cmp-v muted cmp-source">jul\/2026<\/div><div class="cmp-v muted cmp-source">jan\/2026–mar\/2026<\/div>/);
});

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
  const rows = api.attendanceRows();
  assert.equal(rows.length, 1);
  assert.equal(api.attendanceForPerson(1).presente, 1);
  assert.equal(api.attendanceForPerson(2), null);
  assert.equal(api.attendanceBar({ presente: 0, falta: 0, justificadas: 0, dias: 0 }), '');
});

test('attendance page keeps the three absence categories, the reported reason and the source note', () => {
  const { api, context } = comparison(profile('camara:a', 1), profile('camara:b', 2));
  context.chamberPersonId = id => `camara:${id}`;
  context.DATA.presencaTodos = [
    { id: 1, nome: 'Bia', partido: 'AAA', uf: 'SP', dias: 10, presente: 4, falta: 1, justificadas: 5, motivos: [['Licença', 2], ['Missão Autorizada', 3]], inicio: '2023-02', fim: '2026-09' },
    { id: 2, nome: 'Ana', partido: 'BBB', uf: 'RJ', dias: 10, presente: 10, falta: 0, justificadas: 0, inicio: '2023-02', fim: '2026-09' },
  ];
  api.extrasState.attendanceOrder = 'less';
  const html = api.attendanceView();
  assert.ok(html.indexOf('Bia') < html.indexOf('Ana'));
  assert.match(html, /5 faltas justificadas \(mais comum: missão autorizada, 3\) · 1 falta/);
  assert.match(html, /Nenhuma ausência/);
  assert.match(html, /Falta justificada<\/span><span><i class="absent"><\/i>Falta/);
  assert.match(html, /entre os\(as\) 2 deputados\(as\) com dados de presença disponíveis/);
  assert.match(html, /Fonte: página de presença em Plenário/);
});

test('empty attendance data stays unavailable instead of displaying zero presence', () => {
  const { api, context } = comparison(profile('camara:a', 1), profile('camara:b', 2));
  context.DATA.presencaTodos = [];
  const html = api.attendanceView();
  assert.match(html, /Dados de presença indisponíveis neste recorte/);
  assert.match(html, /Sem dados/);
  assert.match(html, /Não há registros de presença para calcular a média/);
  assert.doesNotMatch(html, /0%|0 dias com sessão|entre os\(as\) 0 deputados/);
});

test('compare person card links to the profile and swaps the person out of the comparison', () => {
  const { api, context } = comparison(profile('camara:a', 1), profile('camara:b', 2));
  context.citizenState.cache.set('/api/c/politico/camara%3A7', { pessoa: { id: 'camara:7', name: 'Ana Lima', role: 'deputado', party: 'AAA', uf: 'SP' } });
  const card = api.comparisonPersonCard('camara:7');
  assert.match(card, /data-politician="camara:7">Ana Lima<\/button>/);
  assert.match(card, /AAA · SP/);
  assert.match(card, /data-cmp-del="camara:7" aria-label="Trocar Ana Lima">Trocar/);
  assert.doesNotMatch(api.comparisonPersonCard('camara:8'), /data-politician/);
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
  assert.deepEqual(Array.from(api.voteRowsForItem(context.DATA.votacoes[0]), row => Array.from(row)), [[1, 'Registrada', 'AAA', 'SP', 'Sim']]);
  assert.deepEqual(Array.from(api.voteRowsForItem(context.DATA.votacoes[1]), row => Array.from(row)), [[1, 'Registrada', 'AAA', 'SP', 'Presente']]);
  const profileHtml = api.profileExtras('camara:2');
  assert.match(profileHtml, /1\/1/);
  assert.match(profileHtml, /Votações selecionadas do Placar · 2/);
  assert.match(profileHtml, /Sem registro importado/);
  assert.match(api.profileExtras('camara:3'), /Sem registro importado para este perfil/);
  const secretProfileHtml = api.profileExtras('camara:1');
  assert.match(secretProfileHtml, /Presença registrada · voto secreto/);
  assert.match(secretProfileHtml, /presenca-plenario\/\d{4}" target="_blank" rel="noopener">Presença no Plenário ↗/);
  assert.doesNotMatch(profileHtml, /Sim|Não votou/);
  assert.match(api.profileExtras('senado:55'), /Sem dados de presença do Senado importados/);
  assert.match(api.profileExtras('senado:55'), /Votações nominais do Senado ainda não importadas/);
  assert.match(api.profileExtras('senado:55'), /https:\/\/www25\.senado\.leg\.br\/web\/senadores\/senador\/-\/perfil\/55/);
  assert.doesNotMatch(api.profileExtras('senado:55'), /Sim|Não votou/);
});

test('profile comparison adds neutral availability and mandate details without ranking them', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.profileData = value => value.id.endsWith(':1') ? ({
    id: value.id, person: value, mandate: { participacao: 'Titular', exercicio: 'Em exercício' },
    contact: { email: 'a@example.test', status: 'partial' }, projects: { status: 'partial', total: null, startDate: '2023-02-01', endDate: '2026-10-08', items: [{}] },
    office: { amount: 125000, staffActive: 4, period: 'Jan–Jun/2026', months: 6, fetchedAt: '2026-10-07' },
    compensation: { amount: 46366.19 },
  }) : ({ id: value.id, person: value, mandate: null, contact: null, projects: null, office: null, compensation: null });
  // Mesmos contadores da ficha (profile-data.js); aqui um retorno fixo para testar a célula.
  context.profileProjectStats = value => ({ count: 1, collection: 'cobertura parcial', confirmed: 1, consulted: 1, status: '1 virou lei' });
  const html = api.comparisonTable([profile('camara:1', 100), profile('camara:2', 200)]);
  assert.match(html, /Participação e exercício/);
  assert.match(html, /Disponível em recorte parcial/);
  assert.match(html, /Projetos apresentados · PL, PLP e PEC desde fev\/2023/);
  assert.match(html, /<b>1<\/b><small> projeto · cobertura parcial<\/small><br><small>1 virou lei<\/small>/);
  assert.match(html, /125\.000,00/);
  assert.match(html, /Jan–Jun\/2026/);
  assert.match(html, /4 pessoas ativas/);
  assert.match(html, /referência do cargo, não pagamento individual/);
  assert.match(html, /Sem dados importados/);
  for (const label of ['Participação e exercício', 'Contato institucional', 'Projetos', 'Equipe e verba de gabinete', 'Remuneração']) {
    const row = html.split('\n').find(line => line.includes(label));
    assert.ok(row, `linha ausente: ${label}`);
    assert.doesNotMatch(row, /class="cmp-v best"/);
  }
});

/* Meses do mandato a partir de fev/2023, no formato do snapshot. */
const mandatePeriods = count => Array.from({ length: count }, (_, index) => {
  const serial = 2023 * 12 + 1 + index;
  return `${Math.floor(serial / 12)}-${String(serial % 12 + 1).padStart(2, '0')}`;
});

test('deputy and senator costs sit side by side with their composition and no highlight', () => {
  const { api, context } = comparison(profile('camara:1', 24000), profile('senado:70', 27000));
  context.profileData = value => value.id === 'camara:1'
    ? { id: value.id, person: value, cost: { monthlyAverageCents: 18828630, usedMonths: mandatePeriods(42),
        parts: { remuneration: { averageCents: 4411268, months: Array(42).fill('2026-01') }, office: { averageCents: 12636486, months: 41 } } } }
    : { id: value.id, person: value, senateCost: { months: {} } };
  context.senateCostFigures = () => ({ total: { cents: 37586984, months: 43 }, remuneration: { cents: 4428269, months: 44 }, office: { cents: 30413582, months: 44 }, officePeople: 21 });
  const html = api.comparisonTable([{ ...profile('camara:1', 24000), pessoa: { id: 'camara:1', name: 'AJ', role: 'deputado' } }, profile('senado:70', 27000)]);
  const row = label => html.split('\n').find(line => line.includes(label)) || '';
  assert.match(row('Quanto custa por mês'), /R\$ 188286\.3<\/b>[\s\S]*salário, auxílios, cota e verba de gabinete[\s\S]*R\$ 375869\.84<\/b>[\s\S]*remuneração, equipe do gabinete e cota/);
  assert.doesNotMatch(row('Quanto custa por mês'), /cmp-v best/);
  assert.doesNotMatch(row('Cota parlamentar por mês'), /cmp-v best/);
  assert.match(html, /parte da diferença vem do que cada Casa inclui/);
  assert.doesNotMatch(html, /Não se aplica<\/div><div class="cmp-v">[^<]*R\$/);
  const card = api.comparisonShareCard([{ ...profile('camara:1', 24000), pessoa: { id: 'camara:1', name: 'AJ', role: 'deputado' } }, profile('senado:70', 27000)]);
  assert.equal(card.layout, 'faceoff');
  assert.equal(card.people[0].stats[0].label, 'Média por mês*');
  assert.deepEqual([...card.people.map(person => person.stats[0].value)], ['R$ 188286.3', 'R$ 375869.84']);
  // Casas diferentes: sem etiqueta de quem custa menos nem número apagado, e o rodapé explica.
  assert.ok(card.people.every(person => person.stats.every(stat => !stat.tag && !stat.behind)));
  assert.match(card.footnote, /Médias mensais do mandato/);
  assert.match(card.footnote, /Câmara e Senado publicam partes diferentes do custo/);
  assert.equal(card.agreement, null);
  assert.match(row('Equipe e verba de gabinete'), /R\$ 126364\.86<\/b>[\s\S]*verba de gabinete \(Câmara\)[\s\S]*R\$ 304135\.82<\/b>[\s\S]*equipe comissionada do gabinete \(Senado\) · 21 pessoas/);
  assert.match(row('Remuneração'), /média de 42 meses[\s\S]*bruto pago, pela folha da Câmara[\s\S]*bruto pago, pela folha do Senado/);
  assert.doesNotMatch(html, /não pagamento individual/);
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
  const html = api.comparisonTable([profile('senado:55', 100), profile('senado:56', 200)]);
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
  const profileHtml = api.profileExtras('senado:55');
  assert.match(profileHtml, /Presença registrada · sem voto/);
  assert.match(profileHtml, /Votações secretas foram excluídas/);
});

test('Senate vote views show the collected mandate bounds and annual source coverage', () => {
  const { api, senate } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  senate.votacoes = {
    status: 'partial', startDate: '2023-02-01', endDate: '2026-10-08',
    detail: 'A cobertura de 2024 está incompleta.',
    sources: [
      { year: 2023, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2023', startDate: '2023-02-01', endDate: '2023-12-31' },
      { year: 2024, status: 'partial', sourceUrl: 'https://senado.example.test/votos/2024', startDate: '2024-01-01', endDate: '2024-06-30' },
      { year: 2025, status: 'unavailable', sourceUrl: null, startDate: null, endDate: null },
      { year: 2026, status: 'imported', sourceUrl: 'https://senado.example.test/votos/2026', startDate: '2026-01-01', endDate: '2026-10-08' },
    ],
    items: [
      { id: 'senado:oldest', data: '2023-02-01', titulo: 'Voto no início do recorte', secreta: false, sourceUrl: 'https://senado.example.test/voto/oldest', rows: [
        ['senado:55', 'Senadora A', 'AAA', 'SP', 'Sim'], ['senado:56', 'Senador B', 'BBB', 'RJ', 'Não'],
      ] },
      { id: 'senado:latest', data: '2026-10-08', titulo: 'Voto no fim do recorte', secreta: false, sourceUrl: 'https://senado.example.test/voto/latest', rows: [
        ['senado:55', 'Senadora A', 'AAA', 'SP', 'Não'], ['senado:56', 'Senador B', 'BBB', 'RJ', 'Não'],
      ] },
    ],
  };
  const comparisonHtml = api.comparisonTable([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.match(comparisonHtml, /Voto no início do recorte/);
  assert.match(comparisonHtml, /Voto no fim do recorte/);
  assert.match(comparisonHtml, /de 01\/02\/2023 a 08\/10\/2026/);
  assert.match(comparisonHtml, /2024 · parcial/);
  assert.match(comparisonHtml, /2025 · indisponível/);
  assert.match(comparisonHtml, /href="https:\/\/senado\.example\.test\/votos\/2023"/);
  assert.match(comparisonHtml, /href="https:\/\/senado\.example\.test\/votos\/2026"/);

  const profileHtml = api.profileExtras('senado:55');
  assert.match(profileHtml, /Votações nominais do Senado · de 01\/02\/2023 a 08\/10\/2026 · 2/);
  assert.match(profileHtml, /Voto no início do recorte/);
  assert.match(profileHtml, /Voto no fim do recorte/);
  assert.match(profileHtml, /Presença registrada · Senado/);
});

test('unavailable Senate vote coverage does not read as an empty comparison or zero votes', () => {
  const { api, senate } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  senate.votacoes = { status: 'unavailable', startDate: '2023-02-01', endDate: '2026-10-08', sources: [
    { year: 2025, sourceUrl: null },
  ], items: [] };
  const profileHtml = api.profileExtras('senado:55');
  assert.match(profileHtml, /Dados de votações nominais do Senado indisponíveis neste recorte/);
  assert.match(profileHtml, /Votações nominais do Senado · de 01\/02\/2023 a 08\/10\/2026/);
  assert.match(profileHtml, /2025 · indisponível/);
  assert.doesNotMatch(profileHtml, /Votações nominais do Senado · 0/);

  const comparisonHtml = api.comparisonTable([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.match(comparisonHtml, /Dados de votações nominais do Senado indisponíveis neste recorte/);
  assert.doesNotMatch(comparisonHtml, /Sem votos nominais comparáveis para estes\(as\) senadores\(as\)/);
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
  const html = api.comparisonTable([profile('camara:1', 100), profile('senado:55', 200)]);
  const presence = html.split('\n').find(line => line.includes('<span class="cmp-l">Presença</span>')) || '';
  assert.match(presence, /<b>100%<\/b><br><small>das sessões deliberativas da Câmara[\s\S]*<b>3<\/b><small> sessões<\/small><br><small>com presença registrada no Senado, de 18 listas consultadas/);
  assert.doesNotMatch(presence, /Não se aplica|cmp-v best/);
  assert.match(html, /as medidas são diferentes e nenhuma é destacada/i);
  assert.doesNotMatch(html, /Metodologias de presença de casas diferentes não são comparadas/);
  assert.match(html, /Votações de casas diferentes não são comparadas/);
  assert.doesNotMatch(html, /Matéria Senado|1 votação nominal com registro/);
});

test('Senate profile absence remains unavailable and loading uses a skeleton', () => {
  const { api, senate } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  senate.loading = true;
  const loading = api.profileExtras('senado:55');
  assert.match(loading, /loading/);
  senate.loading = false;
  const absent = api.profileExtras('senado:55');
  assert.match(absent, /Sem dados de presença do Senado importados/);
  assert.match(absent, /Votações nominais do Senado ainda não importadas/);
  assert.doesNotMatch(absent, /0\/0|0% presente|Votações nominais do Senado · 0/);
  const comparisonHtml = api.comparisonTable([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.match(comparisonHtml, /Sem votos nominais comparáveis/);
  assert.doesNotMatch(comparisonHtml, /0 de 0/);
});

test('Senate vote rows preserve null individual votes and source statuses', () => {
  const { api } = comparison(profile('senado:55', 100), profile('senado:56', 200));
  const vote = { id: 'senado:V1', secreta: false, rows: [
    ['senado:55', 'Senadora A', 'AAA', 'SP', null],
    ['senado:56', 'Senador B', 'BBB', 'RJ', 'Atividade parlamentar'],
  ] };
  const rows = api.voteRowsForItem(vote);
  assert.equal(rows[0][4], null);
  assert.equal(rows[1][4], 'Atividade parlamentar');
  assert.doesNotMatch(JSON.stringify(rows), /"Presente"/);
});

test('comparison suggestions load from the full API with an empty query and use its results', async () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const picker = { innerHTML: '' };
  context.document.getElementById = id => id === 'comparison-res' ? picker : null;
  const calls = [];
  const roster = Array.from({ length: 8 }, (_, i) => ({ id: `camara:${i === 7 ? 513 : 500 + i}`,
    name: `Pessoa ${i + 1}`, role: 'deputado', party: 'PT', uf: 'SP' }));
  context.citizenGet = async path => { calls.push(path); return { itens: roster }; };

  const html = api.comparisonView();
  assert.deepEqual(calls, ['/api/c/politicos?pageSize=8&page=1&ordem=nome']);
  assert.match(html, /loading/);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(picker.innerHTML, /data-cmp-add="camara:513"/);
  assert.doesNotMatch(picker.innerHTML, /data-cmp-add="camara:7"/);
});

test('comparison suggestions show an API error and a retry control', async () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const picker = { innerHTML: '' };
  context.document.getElementById = id => id === 'comparison-res' ? picker : null;
  context.citizenGet = async () => { throw new Error('offline'); };
  api.comparisonView();
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
  const html = api.taxCard(300000, Date.parse('2026-10-07T12:00:00-03:00'));
  assert.match(html, /cota registrada para os deputados\(as\) da lista no recorte \(R\$ 300000\)/);
  assert.doesNotMatch(html, /Tudo o que a Câmara gastou/);
});

test('tax counter adds the 27 states to the federal revenue and says what is still missing', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.DATA.arrecadacao = { inicio: '2026-01-01', ate: '2026-08-31', acumulado: 2_000_000_000_000, populacao: 200, url: 'https://example.test/federal' };
  const federalOnly = context.taxWidget(Date.parse('2026-08-31T12:00:00-03:00'));
  assert.equal(Math.round(federalOnly.value), 2_000_000_000_000);
  assert.equal(federalOnly.state, null);
  assert.match(api.taxCard(null, Date.parse('2026-08-31T12:00:00-03:00')), /Não inclui impostos estaduais e municipais/);
  context.DATA.arrecadacaoEstadual = { inicio: '2026-01-01', ate: '2026-08-31', acumulado: 700_000_000_000, url: 'https://example.test/siconfi' };
  const both = context.taxWidget(Date.parse('2026-08-31T12:00:00-03:00'));
  assert.equal(Math.round(both.value), 2_700_000_000_000);
  assert.ok(both.perSecond > federalOnly.perSecond);
  const html = api.taxCard(1_000_000, Date.parse('2026-08-31T12:00:00-03:00'));
  assert.match(html, /impostos federais e estaduais pagos/);
  assert.match(html, /Federal <b class="mono" data-tax-federal>R\$ [0-9],[0-9][0-9] tri/);
  assert.match(html, /Estadual <b class="mono" data-tax-state>R\$ 0,[0-9][0-9] tri/);
  assert.match(html, /ICMS, IPVA e ITCD dos 27 estados/);
  assert.match(html, /Não inclui impostos municipais \(IPTU, ISS e ITBI\)/);
  assert.match(html, /href="https:\/\/example\.test\/siconfi"/);
});

test('tax counter becomes unavailable when the federal source belongs to the previous year', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.DATA.arrecadacao = { inicio: '2026-01-01', ate: '2026-12-31', acumulado: 2_000_000_000_000, populacao: 200, url: 'https://example.test/federal' };
  context.DATA.arrecadacaoEstadual = { inicio: '2026-01-01', ate: '2026-12-31', acumulado: 700_000_000_000, url: 'https://example.test/siconfi' };
  const utcNewYearButSaoPauloStill2026 = Date.parse('2027-01-01T02:30:00Z');
  assert.ok(api.taxWidget(utcNewYearButSaoPauloStill2026));
  const newYear = Date.parse('2027-01-01T00:30:00-03:00');
  assert.equal(api.taxWidget(newYear), null);
  assert.equal(api.taxCard(1_000_000, newYear), '');
});

test('tax counter ignores state data from a different annual period and guards population', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const now = Date.parse('2026-08-31T12:00:00-03:00');
  context.DATA.arrecadacao = { inicio: '2026-01-01', ate: '2026-08-31', acumulado: 2_000_000_000_000, populacao: 0, url: 'https://example.test/federal' };
  context.DATA.arrecadacaoEstadual = { inicio: '2025-01-01', ate: '2025-12-31', acumulado: 700_000_000_000, url: 'https://example.test/siconfi' };
  const tax = api.taxWidget(now);
  assert.equal(tax.state, null);
  assert.equal(Math.round(tax.value), 2_000_000_000_000);
  const html = api.taxCard(null, now);
  assert.match(html, /Sem dados<\/b><span>por pessoa no ano/);
  assert.doesNotMatch(html, /NaN|Infinity|federais e estaduais pagos/);
});

test('tax counter tick removes the stale widget after the year changes', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  context.DATA.arrecadacao = { inicio: '2026-01-01', ate: '2026-12-31', acumulado: 2_000_000_000_000, populacao: 200, url: 'https://example.test/federal' };
  let removed = 0;
  const card = { remove() { removed += 1; } };
  const value = { firstChild: { data: 'R$ 2 tri' } };
  context.document.querySelector = selector => selector === '[data-tax]' ? value : selector === '.tax-card' ? card : null;
  api.taxTick(Date.parse('2027-01-01T00:30:00-03:00'));
  assert.equal(removed, 1);
});

test('tax counter rejects malformed or non-current federal periods', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 200));
  const now = Date.parse('2026-08-31T12:00:00-03:00');
  context.DATA.arrecadacao = { inicio: '2026-02-01', ate: '2026-08-31', acumulado: 2_000_000_000_000, populacao: 200 };
  assert.equal(api.taxWidget(now), null);
  context.DATA.arrecadacao = { inicio: '2026-01-01', ate: '2026-02-31', acumulado: 2_000_000_000_000, populacao: 200 };
  assert.equal(api.taxWidget(now), null);
});

test('deputy cost in the comparison leaves out months whose quota still receives notes', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 100));
  const values = quota => ({ remuneration: 4636619, allowances: 0, quota, office: 15000000 });
  const months = { '2026-06': { valuesCents: values(3000000) }, '2026-07': { valuesCents: values(3000000) }, '2026-08': { valuesCents: values(600000) } };
  context.profileData = value => ({ id: value.id, person: value, cost: { monthlyAverageCents: 21836619, usedMonths: Object.keys(months), months, parts: {} } });
  const person = id => ({ ...profile(id, 100), pessoa: { id, name: id, role: 'deputado' }, snapshotAt: '2026-10-13T03:17:32+00:00' });
  const row = api.comparisonTable([person('camara:1'), person('camara:2')]).split('\n').find(line => line.includes('Custa por mês · Câmara'));
  // Só jun e jul: 46.366,19 + 150.000 + 30.000; ago ainda recebe notas.
  assert.match(row, /R\$ 226366\.19<\/b><small> \/mês · média de 2 meses/);
});

test('share card for two deputies tags only who costs less and who attended more, never alerts', () => {
  const { api, context } = comparison(profile('camara:1', 100), profile('camara:2', 100));
  context.profileData = value => ({ id: value.id, person: value, cost: { monthlyAverageCents: value.id === 'camara:1' ? 19315614 : 21836534, usedMonths: mandatePeriods(40), parts: {} } });
  context.DATA.presencaTodos = [{ id: 1, dias: 361, presente: 333, falta: 2, justificadas: 26 }, { id: 2, dias: 391, presente: 374, falta: 5, justificadas: 12 }];
  context.chamberPairAgreement = () => 0.74;
  const person = (id, name, extra) => ({ ...profile(id, 100), pessoa: { id, name, role: 'deputado', party: 'ABC', uf: 'SP' },
    total: 1000, categorias: [{ nome: 'Divulgação', valor: 590 }, { nome: 'Combustível', valor: 90 }],
    maiores: [{ valor: 99992.1, categoria: 'Divulgação', year: 2026, month: 5, fornecedor: 'Fornecedor A' }], ...extra });
  const card = api.comparisonShareCard([person('camara:1', 'Ana', { alertas: [{}, {}] }), person('camara:2', 'Bia', { alertas: [{}, {}, {}, {}] })]);
  const [ana, bia] = card.people;
  assert.equal(ana.stats[0].tag, 'R$ 25209.2 a menos por mês');
  assert.equal(bia.stats[0].behind, true);
  assert.equal(bia.stats[1].tag, 'mais presente');
  assert.equal(ana.stats[1].behind, true);
  assert.deepEqual(ana.categories.map(category => [category.name, Math.round(category.share * 100)]), [['Divulgação', 87], ['Combustível', 13]]);
  assert.equal(ana.top.what, 'Divulgação · mai/2026');
  assert.equal(ana.meta, 'ABC · SP');
  assert.deepEqual([...card.alerts], ['2', '4']);
  assert.equal(JSON.stringify(card).includes('menos alertas'), false);
});

test('comparison quota categories use positive amounts and explain refunds', () => {
  const { api } = comparison(profile('camara:204353', 86055.2), profile('camara:1', 100));
  const person = (id, name, categories, suppliers = []) => ({ ...profile(id, 86055.2), pessoa: { id, name, role: 'deputado', party: 'UNIÃO', uf: 'AP' },
    categorias: categories, fornecedores: suppliers, maiores: [], alertas: [] });
  const categories = [
    { nome: 'Divulgação', valor: 52000 },
    { nome: 'Locação de veículos', valor: 38100 },
    { nome: 'Telefonia', valor: 1.14 },
    { nome: 'Passagem aérea', valor: -4045.94 },
  ];
  const suppliers = [
    { name: 'Fornecedor principal', valor: 52000, notas: 4 },
    { name: 'GOL', valor: -4045.94, notas: 4 },
  ];
  const card = api.comparisonShareCard([person('camara:204353', 'Aline Gurgel', categories, suppliers), person('camara:1', 'Outra pessoa', [])]);
  const [aline] = card.people;
  assert.equal(aline.stats[0].label, 'Custo médio por mês');
  assert.ok(Math.abs(aline.categories.reduce((sum, category) => sum + category.share, 0) - 1) < 1e-9);
  assert.match(aline.categoryNote, /Percentuais dos saldos positivos; estornos mantidos no total/);
  assert.equal(aline.categoryEmptyLabel, '');

  const table = api.comparisonTable([person('camara:204353', 'Aline Gurgel', categories, suppliers), person('camara:1', 'Outra pessoa', [])]);
  assert.match(table, /58% dos saldos positivos/);
  assert.match(table, /Percentuais consideram categorias com saldo positivo; estornos permanecem no total líquido/);
  const supplierRow = table.match(/<span class="cmp-l">Empresa que mais recebeu<\/span>([\s\S]*?)<\/div>/)?.[1] || '';
  assert.match(supplierRow, /Fornecedor principal <small>R\$ 52000 · 4 notas/);
  assert.doesNotMatch(supplierRow, /%/);
  const negativeOnly = api.comparisonTable([
    person('camara:204353', 'Aline Gurgel', categories, [{ name: 'GOL', valor: -4045.94, notas: 4 }]),
    person('camara:1', 'Outra pessoa', []),
  ]);
  assert.match(negativeOnly, /Empresa que mais recebeu<\/span><div class="cmp-v">Sem valor positivo listado/);
  const senateCard = api.comparisonShareCard([profile('senado:55', 100), profile('senado:56', 200)]);
  assert.equal(senateCard.people[0].stats[0].label, 'Despesas médias por mês');
});

test('presiding stays visible but does not count as agreement or disagreement', () => {
  const a = profile('camara:1', 100), b = profile('camara:2', 100);
  const { api, context } = comparison(a, b);
  context.DATA.votacoes = [{ id: 'v1', titulo: 'Voto nominal' }, { id: 'v2', titulo: 'Presidência' }];
  context.DATA.votosCompletos = {
    v1: [[1, 'Ana', 'ABC', 'SP', 'Sim'], [2, 'Bia', 'ABC', 'RJ', 'Sim']],
    v2: [[1, 'Ana', 'ABC', 'SP', 'Presidiu'], [2, 'Bia', 'ABC', 'RJ', 'Não']],
  };
  const html = api.comparisonTable([a, b]);
  assert.match(html, /mesmo voto em 1 de 1 votações/);
  assert.match(html, /presidiu<\/span>[\s\S]*sem registro comparável/);
  const card = api.comparisonShareCard([a, b]);
  assert.equal(card.agreement.matching, 1);
  assert.equal(card.agreement.total, 1);
});

test('comparison shows votes ten at a time and each "Mostrar mais" opens ten more', () => {
  const { api, context } = comparison(profile('camara:1', 1), profile('camara:2', 2));
  context.DATA.votacoes = Array.from({ length: 25 }, (_, index) => ({ id: `v${index}`, data: '2026-09-01', titulo: `Votação ${index}`, secreta: false }));
  context.DATA.votosCompletos = Object.fromEntries(context.DATA.votacoes.map(vote => [vote.id, [[1, 'A', 'AAA', 'SP', 'Sim'], [2, 'B', 'BBB', 'RJ', 'Não']]]));
  const rows = html => (html.match(/class="cmp-vote"/g) || []).length;
  let html = api.comparisonTable([profile('camara:1', 1), profile('camara:2', 2)]);
  assert.equal(rows(html), 10);
  assert.match(html, /Mostrar mais \(15\)/);
  api.extrasState.comparisonVoteLimit += 10;
  html = api.comparisonTable([profile('camara:1', 1), profile('camara:2', 2)]);
  assert.equal(rows(html), 20);
  assert.match(html, /Mostrar mais \(5\)/);
});
