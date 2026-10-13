/* Comparar partidos: registros e cota (API /api/c/partidos), presença e votos (helpers compartilhados).
   Ausência não vira zero: presença depende dos registros válidos de cada casa e voto só usa linha da fonte. */
// Votações por vez em cada casa: listas longas cansam; "Mostrar mais" abre o próximo bloco.
const PARTY_VOTE_PAGE = 10;
const partyState = { selected: [], data: null, error: null, loading: false, chamberVoteLimit: PARTY_VOTE_PAGE, senateVoteLimit: PARTY_VOTE_PAGE,
  chamberCatalog: null, chamberCatalogLoading: false, chamberCatalogError: null };
const PARTY_PATH = '/api/c/partidos';
const PARTY_CHAMBER_VOTES_PATH = '/api/c/votes/party-totals';

function loadParties() {
  // Com erro, espera o "Tentar de novo": recarregar sozinho a cada render prendia a tela no loading.
  if (partyState.data || partyState.loading || partyState.error) return;
  partyState.loading = true; partyState.error = null;
  citizenGet(PARTY_PATH).then(d => {
    partyState.data = d; partyState.loading = false;
    // Siglas vindas do endereço valem sem diferença de maiúsculas; desconhecidas dão lugar ao padrão.
    const byKey = new Map(d.itens.map(p => [partyVoteKey(p.sigla), p.sigla]));
    const resolved = [...new Set(partyState.selected.map(code => byKey.get(partyVoteKey(code))).filter(Boolean))];
    partyState.selected = resolved.length === 2 ? resolved : d.itens.slice(0, 2).map(p => p.sigla);
    if (state.view === 'parties' && typeof syncLocation === 'function') syncLocation('replace');
    if (state.view === 'parties') rerender();
  }).catch(e => { partyState.loading = false; partyState.error = citizenErrorMessage(e); if (state.view === 'parties') rerender(); });
}

/* Endereço compartilhável da comparação: /partidos/PL-vs-PT. */
function partyPairPath(selected = partyState.selected) {
  return selected.length === 2 ? `/partidos/${selected.map(code => encodeURIComponent(code)).join('-vs-')}` : '/partidos';
}
function partyPairFromPath(path) {
  const match = String(path || '').match(/^\/partidos\/(.+?)-vs-(.+)$/);
  if (!match) return null;
  try { return [decodeURIComponent(match[1]), decodeURIComponent(match[2])]; } catch { return null; }
}
/* Catálogo do Placar com totais por partido: mesma base de votações nominais conferidas para todas as legendas. */
function loadPartyChamberVotes() {
  if (partyState.chamberCatalog || partyState.chamberCatalogLoading || partyState.chamberCatalogError) return;
  partyState.chamberCatalogLoading = true;
  citizenGet(PARTY_CHAMBER_VOTES_PATH).then(d => {
    partyState.chamberCatalog = d; partyState.chamberCatalogLoading = false;
    if (state.view === 'parties') rerender();
  }).catch(e => { partyState.chamberCatalogLoading = false; partyState.chamberCatalogError = citizenErrorMessage(e); if (state.view === 'parties') rerender(); });
}
// Mesma normalização do backend: a fonte publica siglas com grafias diferentes (ex.: PCdoB).
const partyVoteKey = partyCode => String(partyCode || '').trim().toUpperCase();
function partyVoteMajority(yesCount, noCount) {
  return !yesCount && !noCount ? null : yesCount > noCount ? 'Sim' : noCount > yesCount ? 'Não' : 'Dividido';
}

/* Votos do partido em cada votação aberta. Só Sim/Não formam a maioria e a unidade do voto. */
function partyVotes(partyCode, chamber = 'camara') {
  if (chamber === 'camara') {
    const items = partyState.chamberCatalog?.available ? partyState.chamberCatalog.items || [] : [];
    return items.map(item => {
      // Totais ausentes (sem arquivo de detalhe) ou partido sem linha ficam sem maioria, nunca zero votos.
      const totals = item.partyTotals ? item.partyTotals[partyVoteKey(partyCode)] : null;
      const yesCount = totals?.yes || 0, noCount = totals?.no || 0;
      return { vote: { id: item.id, titulo: item.title, proposicao: item.proposition, data: item.date }, yesCount, noCount,
        otherCount: totals?.other || 0, majority: partyVoteMajority(yesCount, noCount) };
    });
  }
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const votes = typeof profileVoteList === 'function' ? profileVoteList(chamber) : [];
  return votes.filter(v => !v.secreta).map(v => {
    const voteRows = (typeof voteRowsForItem === 'function' ? voteRowsForItem(v) : null) || [];
    // voteRowsForItem contém somente linhas registradas na fonte; não completar ausentes pela lista atual.
    const partyVotes = voteRows.filter(row => row[2] === partyCode);
    const yesCount = partyVotes.filter(row => row[4] === 'Sim').length;
    const noCount = partyVotes.filter(row => row[4] === 'Não').length;
    return { vote: v, yesCount, noCount, otherCount: partyVotes.length - yesCount - noCount, majority: partyVoteMajority(yesCount, noCount) };
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
  const sourceHtml = !source ? '' : typeof profileSource === 'function' ? profileSource(source, 'Fonte e período') : source.period ? `<span class="src">${esc(datesInTextBR(source.period))}</span>` : '';
  const sessionCount = Number.isFinite(source?.sessionCount) ? source.sessionCount : null;
  const detail = 'Média somente de parlamentares com presença registrada, pela legenda do cadastro atual. Faltas e justificativas não apuradas; ausência de linha não equivale a zero.';
  return `<div class="cmp-row"><span class="cmp-l">Presenças registradas por senador(a) · Senado</span><div class="cmp-v">${show(a)}</div><div class="cmp-v">${show(b)}</div></div>
    <div class="cmp-row"><div class="cmp-v muted cmp-source" style="grid-column:1 / -1">${sessionCount === null ? '' : `${sessionCount} listas de sessões consultadas. `}${esc(detail)}${sourceHtml}</div></div>`;
}
function comparisonRow(label, valueA, valueB, format, betterWhen, pending = false, bars = null) {
  // betterWhen: 'lower', 'higher' or null (information only). Missing values never get highlighted.
  // bars: 'max' (escala do maior dos dois), 'share' (proporção de 0 a 1) ou null. Só com os dois valores.
  const isNumber = value => value !== null && value !== undefined && Number.isFinite(value);
  const winner = !betterWhen || !isNumber(valueA) || !isNumber(valueB) || valueA === valueB ? '' : (valueA < valueB) === (betterWhen === 'lower') ? 'a' : 'b';
  const scale = bars === 'share' ? 1 : Math.max(valueA || 0, valueB || 0);
  const bar = value => bars && !pending && isNumber(valueA) && isNumber(valueB) && scale > 0 ? `<span class="party-bar" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, value / scale * 100)).toFixed(1)}%"></i></span>` : '';
  const show = value => pending ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : isNumber(value) ? format(value) + bar(value) : PARTY_UNAVAILABLE_LABEL;
  return `<div class="cmp-row"><span class="cmp-l">${label}</span><div class="cmp-v ${!pending && winner === 'a' ? 'best' : ''}">${show(valueA)}</div><div class="cmp-v ${!pending && winner === 'b' ? 'best' : ''}">${show(valueB)}</div></div>`;
}
const formatPercent = v => `<b>${Math.round(v * 100)}%</b>`;
/* Quantos(as) parlamentares têm ao menos um alerta, entre os(as) que têm notas. Sem taxa "a cada 10": em
   partidos pequenos ela extrapola (1 pessoa com 2 alertas virava 20) e passa de 10 porque uma pessoa pode ter
   vários alertas. Sem o campo na resposta, fica sem dados (ausência não é zero). */
function partyAlertPeople(party) {
  const roles = [party.deputado, party.senador].filter(Boolean);
  if (!roles.length || roles.some(role => !Number.isFinite(role.comAlerta))) return null;
  const base = roles.reduce((sum, role) => sum + (role.comDados || 0), 0);
  if (!base) return null;
  return { flagged: roles.reduce((sum, role) => sum + role.comAlerta, 0), base, alerts: roles.reduce((sum, role) => sum + (role.alertas || 0), 0),
    members: roles.reduce((sum, role) => sum + (role.membros || 0), 0) };
}
function partyAlertRow(a, b) {
  const show = party => {
    const people = partyAlertPeople(party);
    if (!people) return PARTY_UNAVAILABLE_LABEL;
    // Quem não tem notas não pode ser avaliado(a) pelas regras: fica fora da base, e a tela diz quantos(as).
    const outside = people.members - people.base;
    return `<b>${people.flagged}</b><small> de ${people.base} com notas · ${people.alerts} ${people.alerts === 1 ? 'alerta' : 'alertas'} no total</small>${outside > 0
      ? `<small class="party-note">${outside} dos(as) ${people.members} na lista não ${outside === 1 ? 'tem' : 'têm'} notas da cota e ${outside === 1 ? 'fica' : 'ficam'} fora da conta.</small>` : ''}`;
  };
  return `<div class="cmp-row"><span class="cmp-l">Parlamentares com algum alerta na cota<small>Mandato atual. Alertas não indicam irregularidade; sem destaque.</small></span><div class="cmp-v">${show(a)}</div><div class="cmp-v">${show(b)}</div></div>`;
}
const partyVoteDate = vote => /^\d{4}-\d{2}-\d{2}/.test(String(vote?.data || '')) && typeof dateBR === 'function' ? `${dateBR(vote.data)} · ` : '';
function partyVoteChip(record) {
  if (!record.majority) return PARTY_UNAVAILABLE_LABEL;
  const className = record.majority === 'Sim' ? 'yes' : record.majority === 'Não' ? 'no' : '';
  return `<span class="vchip ${className}">${esc(record.majority.toLowerCase())}</span><small class="party-score mono">${record.yesCount}–${record.noCount}</small>`;
}

/* Cartão para compartilhar a comparação de partidos, no mesmo desenho da comparação de políticos: um card por
   partido (cota e presença dos deputados(as), para onde vai a cota, unidade nas votações) e os votos das bancadas.
   Etiquetas só para fatos comparáveis (cota menor, presença maior); alertas sem destaque. */
function partyShareCard(a, b) {
  const parties = [a, b];
  const quota = parties.map(party => Number.isFinite(party.deputado?.media) ? party.deputado.media : null);
  const presence = parties.map(party => partyAttendance(party.sigla)?.media ?? null);
  const winner = (values, lowerWins) => values.every(value => value != null) && values[0] !== values[1] ? ((values[0] < values[1]) === lowerWins ? 0 : 1) : null;
  const quotaWinner = winner(quota.map(value => value == null ? null : Math.round(value / 100)), true);
  const presenceWinner = winner(presence.map(value => value == null ? null : Math.round(value * 100)), false);
  const votes = parties.map(party => partyVotes(party.sigla));
  const flaggedText = party => { const people = partyAlertPeople(party); return people ? `${people.flagged} de ${people.base}` : 'Sem dados'; };
  const people = parties.map((party, index) => {
    const unity = partyVoteAlignment(votes[index]);
    const categories = party.cotaCategorias?.total > 0 ? party.cotaCategorias.itens.map(item => ({ name: item.nome, share: item.valor / party.cotaCategorias.total })) : [];
    return {
      name: party.sigla,
      meta: `${party.membros} na lista · ${party.deputado?.membros || 0} dep. + ${party.senador?.membros || 0} sen.`,
      stats: [
        { label: 'Cota por mês, média por deputado(a)', value: quota[index] == null ? 'Sem dados' : formatCitizenAmount(quota[index]),
          tag: quotaWinner === index ? `${formatCitizenAmount(Math.abs(quota[0] - quota[1]))} a menos por mês` : '', behind: quotaWinner !== null && quotaWinner !== index },
        { label: 'Presença média no Plenário', value: presence[index] == null ? 'Sem dados' : `${Math.round(presence[index] * 100)}%`,
          tag: presenceWinner === index ? 'mais presente' : '', behind: presenceWinner !== null && presenceWinner !== index },
      ],
      categories,
      meter: { label: 'Unidade nas votações', share: unity, note: 'deputados(as) votando com a maioria da bancada' },
    };
  });
  const majorities = votes.map(list => new Map(list.filter(record => ['Sim', 'Não'].includes(record.majority)).map(record => [record.vote.id, record.majority])));
  const shared = [...majorities[0].keys()].filter(id => majorities[1].has(id));
  return {
    layout: 'faceoff', title: `${a.sigla} × ${b.sigla}`, people,
    agreement: shared.length ? { lead: 'As bancadas votaram igual em', matching: shared.filter(id => majorities[0].get(id) === majorities[1].get(id)).length,
      total: shared.length, source: 'votações do Placar · Câmara' } : null,
    alertsLabel: 'Parlamentares com algum alerta', alerts: parties.map(flaggedText),
    fileName: `${a.sigla}-x-${b.sigla}`,
    footnote: 'Câmara e Senado, mandato atual. Cota, presença e votações: deputados(as). Legenda pelo cadastro atual.',
  };
}

function partyComparisonTable(a, b) {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const va = partyVotes(a.sigla), vb = partyVotes(b.sigla), sa = partyVotes(a.sigla, 'senado'), sb = partyVotes(b.sigla, 'senado');
  const pa = partyAttendance(a.sigla), pb = partyAttendance(b.sigla);
  const psa = partyAttendance(a.sigla, 'senado'), psb = partyAttendance(b.sigla, 'senado');
  loadPartyChamberVotes();
  const chamberCatalog = partyState.chamberCatalog?.available ? partyState.chamberCatalog : null;
  const isSenateLoading = typeof profileSenateLoading === 'function' && profileSenateLoading();
  const senatePresenceSource = typeof profileSenateSource === 'function' ? profileSenateSource('presenca') : null;
  const senateVoteSource = typeof profileSenateSource === 'function' ? profileSenateSource('votacoes') : null;
  const comparableVotes = va.map((record, index) => [record, vb[index]]).filter(([first, second]) => first.majority && second.majority);
  const matchingVoteCount = comparableVotes.filter(([first, second]) => first.majority === second.majority).length;
  // Porcentagem em destaque, com a contagem entre parênteses para mostrar a base.
  const sameSideHeadline = (matching, total, noun) => `${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${(matching / total * 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}% das vezes (${matching} de ${total} ${total === 1 ? noun[0] : noun[1]}).`;
  const nominalNoun = ['votação nominal comparável', 'votações nominais comparáveis'];
  const senateComparableVotes = sa.map((record, index) => [record, sb[index]]).filter(([first, second]) => first?.majority && second?.majority);
  const senateMatchingVoteCount = senateComparableVotes.filter(([first, second]) => first.majority === second.majority).length;
  const sourceMeta = section => {
    if (!section) return '';
    if (typeof profileSource === 'function') return profileSource(section, 'Fonte e período');
    const url = /^https?:\/\//i.test(section.sourceUrl || '') ? section.sourceUrl : '';
    const period = typeof profileSectionPeriod === 'function' ? profileSectionPeriod(section)
      : section.startDate && section.endDate ? `de ${dateBR(section.startDate)} a ${dateBR(section.endDate)}` : section.period || '';
    const annual = (Array.isArray(section.sources) ? section.sources : []).map(source => {
      const href = /^https?:\/\//i.test(source?.sourceUrl || '') ? source.sourceUrl : '';
      const status = source?.status === 'partial' ? 'parcial' : ['imported', 'complete', 'completed', 'success', 'ok'].includes(source?.status) ? 'consultado' : 'indisponível';
      const fetchedAt = source?.fetchedAt ? ` · fotografia ${dateBR(source.fetchedAt)}` : '';
      const label = `${source?.year || ''} · ${status}${fetchedAt}`;
      return href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : `<span>${esc(label)}</span>`;
    });
    return `<span class="src">${period ? `${esc(datesInTextBR(period))}. ` : ''}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Fonte e período ↗</a>` : ''}${annual.length ? `Fontes por ano: ${annual.join(' · ')}` : ''}</span>`;
  };
  const senateVoteRows = sa.slice(0, partyState.senateVoteLimit).map((record, index) => {
    const pair = sb[index];
    if (!pair) return '';
    const content = `<span>${esc(record.vote.titulo || record.vote.proposicao || 'Votação nominal')}</span><span class="party-v"><small class="party-code">${esc(a.sigla)}</small>${partyVoteChip(record)}</span><span class="party-v"><small class="party-code">${esc(b.sigla)}</small>${partyVoteChip(pair)}</span><em>${partyVoteDate(record.vote)}${record.majority && pair.majority ? (record.majority === pair.majority ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em>`;
    return typeof profileVoteButton === 'function' ? profileVoteButton(record.vote, content, 'cmp-vote party-vote') : `<button type="button" class="cmp-vote party-vote" data-vote="${esc(record.vote.id)}">${content}</button>`;
  }).join('');
  const senateVotesUnavailable = senateVoteSource?.status === 'unavailable';
  const chamberVoteRows = va.slice(0, partyState.chamberVoteLimit).map((record, index) => `<button type="button" class="cmp-vote party-vote" data-vote="${esc(record.vote.id)}"><span>${esc(record.vote.titulo)}</span><span class="party-v"><small class="party-code">${esc(a.sigla)}</small>${partyVoteChip(record)}</span><span class="party-v"><small class="party-code">${esc(b.sigla)}</small>${partyVoteChip(vb[index])}</span><em>${partyVoteDate(record.vote)}${record.majority && vb[index]?.majority ? (record.majority === vb[index].majority ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em></button>`).join('');
  const recordSummary = party => [party.deputado ? `${party.deputado.membros} ${party.deputado.membros === 1 ? 'deputado(a)' : 'deputados(as)'}` : '', party.senador ? `${party.senador.membros} ${party.senador.membros === 1 ? 'senador(a)' : 'senadores(as)'}` : ''].filter(Boolean).join(' + ');
  return `<section class="party-cards" aria-label="Registros na lista disponível">${[a, b].map(party => `<div class="card party-card"><span class="party-acronym" style="--fit:${Math.min(56, Math.round(300 / Math.max(5, party.sigla.length)))}px">${esc(party.sigla)}</span><span class="party-card-count"><b class="mono">${party.membros} na lista</b><small>${recordSummary(party)}</small></span></div>`).join('')}</section>
  <section class="card cmp wide party-cmp">
    <div class="cmp-head"><span></span>${[a, b].map(party => `<div class="party-who"><span class="party-acronym" style="--fit:${Math.min(30, Math.round(170 / Math.max(5, party.sigla.length)))}px">${esc(party.sigla)}</span><small>${party.membros} registros da lista</small></div>`).join('')}</div>
    ${comparisonRow('Cota por mês, média por deputado(a) · desde fev/2023', a.deputado?.media, b.deputado?.media, value => `<b class="mono">${formatCitizenAmount(value)}</b>`, 'lower', false, 'max')}
    ${comparisonRow('Cota por mês, média por senador(a) · desde fev/2023', a.senador?.media, b.senador?.media, value => `<b class="mono">${formatCitizenAmount(value)}</b>`, 'lower', false, 'max')}
    ${partyAlertRow(a, b)}
    ${comparisonRow('Presença média dos(as) deputados(as) no Plenário · Câmara', pa?.media, pb?.media, formatPercent, 'higher', false, 'share')}
    ${registeredAttendanceRow(psa, psb, isSenateLoading, senatePresenceSource)}
    ${comparisonRow('Unidade nas votações · Câmara', partyVoteAlignment(va), partyVoteAlignment(vb), formatPercent, null, false, 'share')}
    ${comparisonRow('Unidade nas votações nominais · Senado', partyVoteAlignment(sa), partyVoteAlignment(sb), formatPercent, null, isSenateLoading, 'share')}
  </section>
  <section class="card wide"><span class="k">Como votaram · Câmara</span>
    ${chamberCatalog ? `<h2 class="h party-votes-headline">${comparableVotes.length ? `${sameSideHeadline(matchingVoteCount, comparableVotes.length, nominalNoun)}` : 'Sem votações com escolhas nominais registradas para ambos os partidos neste recorte.'}</h2>
    ${chamberVoteRows}${va.length > partyState.chamberVoteLimit ? `<button type="button" class="opt citizen-more" data-party-chamber-votes-more>Mostrar mais (${va.length - partyState.chamberVoteLimit})</button>` : ''}
    <p class="muted">Votações do Placar: texto principal de PL, PLP e PEC no Plenário${chamberCatalog.period ? `, de ${dateBR(chamberCatalog.period.start)} a ${dateBR(chamberCatalog.period.end)}` : ''}. Placar dentro de cada partido: votos sim–não dos(as) deputados(as) pela sigla publicada em cada votação. Votações secretas, simbólicas e de outros tipos de proposição ficam de fora.</p>
    ${chamberCatalog.coverage?.detail ? `<p class="muted">${esc(datesInTextBR(chamberCatalog.coverage.detail))}</p>` : ''}`
    : partyState.chamberCatalogError ? `<p class="muted">Não deu para carregar as votações da Câmara agora. ${esc(partyState.chamberCatalogError)}</p><button type="button" class="more" data-party-chamber-retry>Tentar de novo</button>`
    : partyState.chamberCatalogLoading || !partyState.chamberCatalog ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>')
    : '<p class="muted">Catálogo de votações nominais da Câmara ainda não disponível.</p>'}
  </section>
  <section class="card wide"><span class="k">Como votaram · Senado</span>
    ${isSenateLoading ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : senateVoteSource ? `<h2 class="h party-votes-headline">${senateVotesUnavailable ? 'Dados de votações nominais do Senado indisponíveis neste recorte.' : senateComparableVotes.length ? sameSideHeadline(senateMatchingVoteCount, senateComparableVotes.length, nominalNoun) : 'Sem votações com escolhas nominais registradas para ambos os partidos neste recorte.'}</h2>
      ${sa.length ? senateVoteRows : `<p class="muted">${senateVotesUnavailable ? 'Dados de votações nominais indisponíveis neste recorte.' : 'Sem votações nominais do Senado com registro neste recorte.'}</p>`}
      ${sa.length > partyState.senateVoteLimit ? `<button type="button" class="opt citizen-more" data-party-senate-votes-more>Mostrar mais (${sa.length - partyState.senateVoteLimit})</button>` : ''}
      ${senateVoteSource.detail ? `<p class="muted">${esc(datesInTextBR(senateVoteSource.detail))}</p>` : ''}${sourceMeta(senateVoteSource)}`
      : `<p class="muted">Votações nominais do Senado ainda não importadas.</p>${sourceMeta(senateVoteSource)}`}
  </section>
  <section class="card wide"><span class="k">Maior gasto médio mensal da cota em cada partido</span>
    <div class="party-tops">${[a, b].map(party => `<div><b class="party-acronym sm">${esc(party.sigla)}</b>${party.top.length ? party.top.map(person => `<button type="button" class="citizen-row" data-politician="${esc(person.id)}">${citizenAvatar(person, 40)}<span class="citizen-rowtxt"><b>${esc(citizenName(person.name))}</b><small>${esc(ROLE_LABELS[person.role] || '')}</small></span><span class="citizen-rowval"><b class="mono">${person.gastoMensal === null || person.gastoMensal === undefined ? 'Sem dados' : `${formatCitizenAmount(person.gastoMensal)}<small>/mês</small>`}</b></span></button>`).join('') : '<p class="muted">Sem notas importadas.</p>'}</div>`).join('')}</div>
  </section>`;
}

function partiesView() {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  loadParties();
  const head = `<div class="compare-intro">
      <button type="button" class="back" data-back>‹ Voltar</button>
      <span class="k">Câmara e Senado</span>
      <h1 class="h ph-t">Partidos lado a lado</h1>
      <p class="ph-lead">Registros da lista, gastos com a cota, presença e votos de dois partidos. Compare a média, não o total: partidos maiores têm mais gente.</p>
    </div>`;
  const page = content => `<div class="parties-page">${head}${content}</div>`;
  if (partyState.error) return page(`<section class="card wide"><p>Não deu para carregar os partidos agora.</p><p class="muted">${esc(partyState.error)}</p><button type="button" class="more" data-party-retry>Tentar de novo</button></section>`);
  if (!partyState.data && !partyState.error && typeof serverRendered === 'function' && serverRendered('/partidos')) return serverRendered('/partidos');
  if (!partyState.data) return page(`<section class="card wide party-pick sk-card">${skL('140px', 10)}${skel('chips', 12)}</section>${skel('cmp')}`);
  const partiesByAcronym = Object.fromEntries(partyState.data.itens.map(party => [party.sigla, party]));
  const [a, b] = partyState.selected.map(acronym => partiesByAcronym[acronym]).filter(Boolean);
  return page(`<section class="party-pick" aria-label="Escolha dois partidos">
    <div class="chips" role="group" aria-label="Partidos">${partyState.data.itens.map(p => `<button type="button" class="fchip" data-party="${esc(p.sigla)}" aria-pressed="${partyState.selected.includes(p.sigla)}">${esc(p.sigla)} <b>${p.membros}</b></button>`).join('')}</div>
    <span class="muted">O número ao lado conta registros incluídos na lista (deputados(as) + senadores(as)); o Senado tem 81 cadeiras e a lista pode incluir suplentes em transição. Toque para trocar; o mais antigo da comparação sai.</span>
  </section>
  ${a && b ? partyComparisonTable(a, b) : '<p class="note">Escolha dois partidos para comparar.</p>'}
  <span class="src">Destaque em roxo: menor gasto médio ou mais presença na Câmara; alertas e unidade nas votações só informam, sem destaque. Registros de presença do Senado são contagens informativas, sem ranking, e não contam sessões sem linha publicada. Partidos maiores tendem a ter mais variação interna; compare a média, não o total. Gastos pelas notas da cota (sem passagens aéreas da Câmara); presença e votos são mostrados separadamente por casa e pelos recortes das respectivas fontes.</span>
  ${a && b ? `<div class="compare-actions">${shareActionsHTML(partyShareCard(a, b), 'Compartilhar imagem')}<button type="button" class="fchip" data-cmp-start="">Comparar políticos →</button></div>` : ''}`);
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-party-chamber-votes-more]')) { partyState.chamberVoteLimit += PARTY_VOTE_PAGE; return rerender(); }
  if (e.target.closest('[data-party-senate-votes-more]')) { partyState.senateVoteLimit += PARTY_VOTE_PAGE; return rerender(); }
  if (e.target.closest('[data-party-chamber-retry]')) { partyState.chamberCatalogError = null; citizenState.cache.delete(PARTY_CHAMBER_VOTES_PATH); rerender(); return; }
  if (e.target.closest('[data-party-retry]')) { partyState.error = null; citizenState.cache.delete(PARTY_PATH); rerender(); return; }
  const t = e.target.closest('[data-party]');
  if (!t) return;
  const s = t.dataset.party;
  partyState.selected = partyState.selected.includes(s) ? partyState.selected.filter(x => x !== s) : [...partyState.selected, s].slice(-2);
  partyState.chamberVoteLimit = partyState.senateVoteLimit = PARTY_VOTE_PAGE;
  rerender();
  // Troca de partido atualiza o endereço sem empilhar uma entrada por toque.
  if (typeof syncLocation === 'function') syncLocation('replace');
});
