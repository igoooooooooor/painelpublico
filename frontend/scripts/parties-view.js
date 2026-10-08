/* Comparar partidos: registros e cota (API /api/c/partidos), presença e votos (helpers compartilhados).
   Ausência não vira zero: presença depende dos registros válidos de cada casa e voto só usa linha da fonte. */
const partyState = { selected: [], data: null, error: null, loading: false, chamberVoteLimit: 20, senateVoteLimit: 20 };
const PARTY_PATH = '/api/c/partidos';

function loadParties() {
  // Com erro, espera o "Tentar de novo": recarregar sozinho a cada render prendia a tela no loading.
  if (partyState.data || partyState.loading || partyState.error) return;
  partyState.loading = true; partyState.error = null;
  citizenGet(PARTY_PATH).then(d => {
    partyState.data = d; partyState.loading = false;
    if (partyState.selected.length < 2) partyState.selected = d.itens.slice(0, 2).map(p => p.sigla);
    if (state.view === 'parties') rerender();
  }).catch(e => { partyState.loading = false; partyState.error = citizenErrorMessage(e); if (state.view === 'parties') rerender(); });
}

/* Votos do partido em cada votação aberta. Só Sim/Não formam a maioria e a unidade do voto. */
function partyVotes(partyCode, chamber = 'camara') {
  if (chamber === 'senado' && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const votes = typeof profileVoteList === 'function' ? profileVoteList(chamber) : chamber === 'camara' ? DATA.votacoes || [] : [];
  return votes.filter(v => !v.secreta).map(v => {
    const voteRows = (typeof voteRowsForItem === 'function' ? voteRowsForItem(v) : null) || [];
    // voteRowsForItem contém somente linhas registradas na fonte; não completar ausentes pela lista atual.
    const partyVotes = voteRows.filter(row => row[2] === partyCode);
    const yesCount = partyVotes.filter(row => row[4] === 'Sim').length;
    const noCount = partyVotes.filter(row => row[4] === 'Não').length;
    const majority = !yesCount && !noCount ? null : yesCount > noCount ? 'Sim' : noCount > yesCount ? 'Não' : 'Dividido';
    return { vote: v, yesCount, noCount, otherCount: partyVotes.length - yesCount - noCount, majority };
  });
}
function partyVoteAlignment(votes) {
  const recordedCount = votes.reduce((sum, record) => sum + record.yesCount + record.noCount, 0);
  return recordedCount ? votes.reduce((sum, record) => sum + Math.max(record.yesCount, record.noCount), 0) / recordedCount : null;
}
function partyAttendance(partyCode, chamber = 'camara') {
  if (chamber === 'senado' && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  if (chamber === 'senado') {
    const rows = typeof profileRegisteredPresenceRows === 'function' ? profileRegisteredPresenceRows() : [];
    const members = rows.filter(person => person && person.partido === partyCode && Number.isFinite(person.presente) && person.presente > 0);
    return members.length ? { media: members.reduce((sum, p) => sum + p.presente, 0) / members.length, n: members.length } : null;
  }
  const rows = typeof profilePresenceRows === 'function' ? profilePresenceRows(chamber) : (chamber === 'camara' ? DATA.presencaTodos || [] : []);
  const members = rows.filter(person => person && person.partido === partyCode && Number.isFinite(person.dias) && person.dias > 0
    && [person.presente, person.falta, person.justificadas].every(value => Number.isFinite(value) && value >= 0)
    && person.presente + person.falta + person.justificadas === person.dias);
  return members.length ? { media: members.reduce((sum, person) => sum + person.presente / person.dias, 0) / members.length, n: members.length } : null;
}

const PARTY_UNAVAILABLE_LABEL = '<span class="muted">Sem dados</span>';
function registeredAttendanceRow(a, b, pending, source) {
  const show = p => pending ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : p
    ? `<b>${p.media.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}</b><small> sessões em média · ${p.n} ${p.n === 1 ? 'senador(a)' : 'senadores(as)'} com registro</small>` : PARTY_UNAVAILABLE_LABEL;
  const sourceHtml = !source ? '' : typeof profileSource === 'function' ? profileSource(source, 'Fonte e período') : source.period ? `<span class="src">${esc(source.period)}</span>` : '';
  const sessionCount = Number.isFinite(source?.sessionCount) ? source.sessionCount : null;
  const detail = 'Média somente de parlamentares com presença registrada, pela legenda do cadastro atual. Faltas e justificativas não apuradas; ausência de linha não equivale a zero.';
  return `<div class="cmp-row"><span class="cmp-l">Presenças registradas por senador(a) · Senado</span><div class="cmp-v">${show(a)}</div><div class="cmp-v">${show(b)}</div></div>
    <div class="cmp-row"><div class="cmp-v muted cmp-source" style="grid-column:1 / -1">${sessionCount === null ? '' : `${sessionCount} listas de sessões consultadas. `}${esc(detail)}${sourceHtml}</div></div>`;
}
function comparisonRow(label, valueA, valueB, format, betterWhen, pending = false) {
  // betterWhen: 'lower', 'higher' or null (information only). Missing values never get highlighted.
  const isNumber = value => value !== null && value !== undefined && Number.isFinite(value);
  const winner = !betterWhen || !isNumber(valueA) || !isNumber(valueB) || valueA === valueB ? '' : (valueA < valueB) === (betterWhen === 'lower') ? 'a' : 'b';
  const show = value => pending ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : isNumber(value) ? format(value) : PARTY_UNAVAILABLE_LABEL;
  return `<div class="cmp-row"><span class="cmp-l">${label}</span><div class="cmp-v ${!pending && winner === 'a' ? 'best' : ''}">${show(valueA)}</div><div class="cmp-v ${!pending && winner === 'b' ? 'best' : ''}">${show(valueB)}</div></div>`;
}
const formatPercent = v => `<b>${Math.round(v * 100)}%</b>`;
function partyVoteChip(record) {
  if (!record.majority) return PARTY_UNAVAILABLE_LABEL;
  const className = record.majority === 'Sim' ? 'yes' : record.majority === 'Não' ? 'no' : '';
  return `<span class="vchip ${className}">${esc(record.majority.toLowerCase())}</span><small class="party-score mono">${record.yesCount}–${record.noCount}</small>`;
}

/* Cartão para compartilhar a comparação de partidos, com as mesmas métricas da tabela. */
function partyShareCard(a, b) {
  const money = value => Number.isFinite(value) ? formatCitizenAmount(value) : 'Sem dados';
  const percentText = value => Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'Sem dados';
  const perTen = party => { const alerts = (party.deputado?.alertas || 0) + (party.senador?.alertas || 0); const members = (party.deputado?.comDados || 0) + (party.senador?.comDados || 0);
    return members ? (alerts / members * 10).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) : 'Sem dados'; };
  return {
    kicker: 'Comparação de partidos', title: `${a.sigla} × ${b.sigla}`, columns: [a.sigla, b.sigla],
    rows: [
      { label: 'Registros na lista (deputados(as) + senadores(as))', values: [String(a.membros), String(b.membros)] },
      { label: 'Gasto médio de cota por deputado(a) em 2026', values: [money(a.deputado?.media), money(b.deputado?.media)] },
      { label: 'Alertas a cada 10 parlamentares', values: [perTen(a), perTen(b)] },
      { label: 'Presença média no Plenário · Câmara', values: [percentText(partyAttendance(a.sigla)?.media), percentText(partyAttendance(b.sigla)?.media)] },
      { label: 'Unidade nas votações · Câmara', values: [percentText(partyVoteAlignment(partyVotes(a.sigla))), percentText(partyVoteAlignment(partyVotes(b.sigla)))] },
    ],
    fileName: `${a.sigla}-x-${b.sigla}`,
    footnote: 'Fontes: notas da cota, presença e votações publicadas pela Câmara e pelo Senado. Legenda pelo cadastro atual.',
  };
}

function partyComparisonTable(a, b) {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const va = partyVotes(a.sigla), vb = partyVotes(b.sigla), sa = partyVotes(a.sigla, 'senado'), sb = partyVotes(b.sigla, 'senado');
  const pa = partyAttendance(a.sigla), pb = partyAttendance(b.sigla);
  const psa = partyAttendance(a.sigla, 'senado'), psb = partyAttendance(b.sigla, 'senado');
  const isSenateLoading = typeof profileSenateLoading === 'function' && profileSenateLoading();
  const senatePresenceSource = typeof profileSenateSource === 'function' ? profileSenateSource('presenca') : null;
  const senateVoteSource = typeof profileSenateSource === 'function' ? profileSenateSource('votacoes') : null;
  const alertsPerTenMembers = party => { const alertCount = (party.deputado?.alertas || 0) + (party.senador?.alertas || 0); const memberCount = (party.deputado?.comDados || 0) + (party.senador?.comDados || 0); return memberCount ? alertCount / memberCount * 10 : null; };
  const comparableVotes = va.map((record, index) => [record, vb[index]]).filter(([first, second]) => first.majority && second.majority);
  const matchingVoteCount = comparableVotes.filter(([first, second]) => first.majority === second.majority).length;
  const senateComparableVotes = sa.map((record, index) => [record, sb[index]]).filter(([first, second]) => first?.majority && second?.majority);
  const senateMatchingVoteCount = senateComparableVotes.filter(([first, second]) => first.majority === second.majority).length;
  const sourceMeta = section => {
    if (!section) return '';
    if (typeof profileSource === 'function') return profileSource(section, 'Fonte e período');
    const url = /^https?:\/\//i.test(section.sourceUrl || '') ? section.sourceUrl : '';
    return `<span class="src">${section.period ? `${esc(section.period)}. ` : ''}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Fonte e período ↗</a>` : ''}</span>`;
  };
  const senateVoteRows = sa.slice(0, partyState.senateVoteLimit).map((record, index) => {
    const pair = sb[index];
    if (!pair) return '';
    const content = `<span>${esc(record.vote.titulo || record.vote.proposicao || 'Votação nominal')}</span><span class="party-v">${partyVoteChip(record)}</span><span class="party-v">${partyVoteChip(pair)}</span><em>${record.majority && pair.majority ? (record.majority === pair.majority ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em>`;
    return typeof profileVoteButton === 'function' ? profileVoteButton(record.vote, content, 'cmp-vote party-vote') : `<button type="button" class="cmp-vote party-vote" data-vote="${esc(record.vote.id)}">${content}</button>`;
  }).join('');
  const chamberVoteRows = va.slice(0, partyState.chamberVoteLimit).map((record, index) => `<button type="button" class="cmp-vote party-vote" data-vote="${esc(record.vote.id)}"><span>${esc(record.vote.titulo)}</span><span class="party-v">${partyVoteChip(record)}</span><span class="party-v">${partyVoteChip(vb[index])}</span><em>${record.majority && vb[index]?.majority ? (record.majority === vb[index].majority ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em></button>`).join('');
  const recordSummary = party => `<b>${party.membros}</b><small>${[party.deputado ? `${party.deputado.membros} dep.` : '', party.senador ? `${party.senador.membros} sen.` : ''].filter(Boolean).join(' · ')}</small>`;
  return `<section class="card cmp wide party-cmp">
    <div class="cmp-head"><span></span>${[a, b].map(party => `<div class="party-who"><span class="party-acronym" style="--fit:${Math.min(30, Math.round(170 / Math.max(5, party.sigla.length)))}px">${esc(party.sigla)}</span><small>${party.membros} registros da lista</small></div>`).join('')}</div>
    <div class="cmp-row"><span class="cmp-l">Registros na lista disponível</span><div class="cmp-v party-stack">${recordSummary(a)}</div><div class="cmp-v party-stack">${recordSummary(b)}</div></div>
    ${comparisonRow('Gasto médio de cota por deputado(a) em 2026', a.deputado?.media, b.deputado?.media, value => `<b class="mono">${formatCitizenAmount(value)}</b>`, 'lower')}
    ${comparisonRow('Gasto médio de cota por senador(a) em 2026', a.senador?.media, b.senador?.media, value => `<b class="mono">${formatCitizenAmount(value)}</b>`, 'lower')}
    ${comparisonRow('Alertas a cada 10 parlamentares', alertsPerTenMembers(a), alertsPerTenMembers(b), value => `<b>${value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}</b>`, 'lower')}
    ${comparisonRow('Presença média dos(as) deputados(as) no Plenário · Câmara', pa?.media, pb?.media, formatPercent, 'higher')}
    ${registeredAttendanceRow(psa, psb, isSenateLoading, senatePresenceSource)}
    ${comparisonRow('Unidade nas votações · Câmara', partyVoteAlignment(va), partyVoteAlignment(vb), formatPercent, null)}
    ${comparisonRow('Unidade nas votações nominais · Senado', partyVoteAlignment(sa), partyVoteAlignment(sb), formatPercent, null, isSenateLoading)}
  </section>
  ${comparableVotes.length ? `<section class="card wide"><span class="k">Como votaram · Câmara</span>
    <h2 class="h" style="font-size:21px">${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${matchingVoteCount} de ${comparableVotes.length} ${comparableVotes.length === 1 ? 'votação' : 'votações'}.</h2>
    ${chamberVoteRows}${va.length > partyState.chamberVoteLimit ? `<button type="button" class="opt citizen-more" data-party-chamber-votes-more>Mostrar mais (${va.length - partyState.chamberVoteLimit})</button>` : ''}
    <span class="muted">Placar dentro de cada partido: votos sim–não dos(as) deputados(as) da legenda. Votações secretas ficam de fora.</span>
  </section>` : ''}
  <section class="card wide"><span class="k">Como votaram · Senado</span>
    ${isSenateLoading ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : senateVoteSource ? `<h2 class="h" style="font-size:21px">${senateComparableVotes.length ? `${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${senateMatchingVoteCount} de ${senateComparableVotes.length} votações nominais comparáveis.` : 'Sem votações com escolhas nominais registradas para ambos os partidos.'}</h2>
      ${sa.length ? senateVoteRows : '<p class="muted">Sem votações nominais do Senado com registro neste recorte.</p>'}
      ${sa.length > partyState.senateVoteLimit ? `<button type="button" class="opt citizen-more" data-party-senate-votes-more>Mostrar mais (${sa.length - partyState.senateVoteLimit})</button>` : ''}
      ${senateVoteSource.detail ? `<p class="muted">${esc(senateVoteSource.detail)}</p>` : ''}${sourceMeta(senateVoteSource)}`
      : `<p class="muted">Votações nominais do Senado ainda não importadas.</p>${sourceMeta(senateVoteSource)}`}
  </section>
  <section class="card wide"><span class="k">Quem mais gastou a cota em cada partido</span>
    <div class="party-tops">${[a, b].map(party => `<div><b class="party-acronym sm">${esc(party.sigla)}</b>${party.top.length ? party.top.map(person => `<button type="button" class="citizen-row" data-politician="${esc(person.id)}">${citizenAvatar(person, 40)}<span class="citizen-rowtxt"><b>${esc(citizenName(person.name))}</b><small>${esc(ROLE_LABELS[person.role] || '')}</small></span><span class="citizen-rowval"><b class="mono">${person.gasto === null || person.gasto === undefined ? 'Sem dados' : formatCitizenAmount(person.gasto)}</b></span></button>`).join('') : '<p class="muted">Sem notas importadas.</p>'}</div>`).join('')}</div>
  </section>`;
}

function partiesView() {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  loadParties();
  const head = `<button type="button" class="back" data-back>‹ Voltar</button>
  ${pageHead('Câmara e Senado', 'Comparar partidos', 'Registros da lista, gastos com a cota, presença e votos de dois partidos lado a lado.')}`;
  if (partyState.error) return `${head}<section class="card wide"><p>Não deu para carregar os partidos agora.</p><p class="muted">${esc(partyState.error)}</p><button type="button" class="more" data-party-retry>Tentar de novo</button></section>`;
  if (!partyState.data) return `${head}<section class="card wide party-pick sk-card">${skL('140px', 10)}${skel('chips', 12)}</section>${skel('cmp')}`;
  const partiesByAcronym = Object.fromEntries(partyState.data.itens.map(party => [party.sigla, party]));
  const [a, b] = partyState.selected.map(acronym => partiesByAcronym[acronym]).filter(Boolean);
  return `${head}
  <section class="card wide party-pick"><span class="k">Escolha dois partidos</span>
    <div class="chips" role="group" aria-label="Partidos">${partyState.data.itens.map(p => `<button type="button" class="fchip" data-party="${esc(p.sigla)}" aria-pressed="${partyState.selected.includes(p.sigla)}">${esc(p.sigla)} <b>${p.membros}</b></button>`).join('')}</div>
    <span class="muted">O número ao lado conta registros incluídos na lista (deputados(as) + senadores(as)); o Senado tem 81 cadeiras e a lista pode incluir suplentes em transição. Toque para trocar; o mais antigo da comparação sai.</span>
  </section>
  ${a && b ? shareActionsHTML(partyShareCard(a, b)) + partyComparisonTable(a, b) : '<p class="note">Escolha dois partidos para comparar.</p>'}
  <span class="src">Destaque em roxo: menor gasto médio, menos alertas ou mais presença na Câmara. Registros de presença do Senado são contagens informativas, sem ranking, e não contam sessões sem linha publicada. Partidos maiores tendem a ter mais variação interna; compare a média, não o total. Gastos pelas notas da cota (sem passagens aéreas da Câmara); presença e votos são mostrados separadamente por casa e pelos recortes das respectivas fontes.</span>`;
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-party-chamber-votes-more]')) { partyState.chamberVoteLimit += 20; return rerender(); }
  if (e.target.closest('[data-party-senate-votes-more]')) { partyState.senateVoteLimit += 20; return rerender(); }
  if (e.target.closest('[data-party-retry]')) { partyState.error = null; citizenState.cache.delete(PARTY_PATH); rerender(); return; }
  const t = e.target.closest('[data-party]');
  if (!t) return;
  const s = t.dataset.party;
  partyState.selected = partyState.selected.includes(s) ? partyState.selected.filter(x => x !== s) : [...partyState.selected, s].slice(-2);
  rerender();
});
