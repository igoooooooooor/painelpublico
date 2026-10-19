/* Contador de impostos, presença de todos(as), quem votou o quê e comparação de perfis.
   A leitura de presença e votos passa pelos helpers compartilhados de perfil. */
// Votações por vez em "Como votaram" da comparação: listas longas cansam; "Mostrar mais" abre o próximo bloco.
const COMPARISON_VOTE_PAGE = 10;
const extrasState = { votes: {}, voteLimit: 40, voteQuery: '', attendanceOrder: 'less', attendanceQuery: '', attendanceLimit: 40, senateVoteLimit: 20, comparisonVoteLimit: COMPARISON_VOTE_PAGE, comparisonIds: [], comparisonQuery: '', comparisonKey: null, comparisonResults: null, comparisonError: null, comparisonLoading: false };
const chamberPersonId = id => 'camara:' + id;
const percent = (a, b) => b ? Math.round(a / b * 100) : 0;
const TAX_DATE_FORMATTER = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' });

/* ---------- Contador de impostos (estimativa a partir do dado oficial) ----------
   Soma a arrecadação federal (Receita Federal) e a estadual (ICMS, IPVA e ITCD dos RREOs dos 27 estados).
   Cada esfera segue no ritmo médio diário do próprio ano depois da última data publicada. */
function taxLocalDate(now) {
  if (!Number.isFinite(now)) return null;
  try {
    const parts = TAX_DATE_FORMATTER.formatToParts(new Date(now));
    const part = type => parts.find(item => item.type === type)?.value;
    const year = part('year'), month = part('month'), day = part('day');
    return year && month && day ? { year, date: `${year}-${month}-${day}` } : null;
  } catch (error) { return null; }
}
function taxDateTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) return null;
  const [, year, month, day] = match, utc = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (Number(year) < 1900 || utc.getUTCFullYear() !== Number(year) || utc.getUTCMonth() + 1 !== Number(month) || utc.getUTCDate() !== Number(day)) return null;
  const timestamp = Date.parse(`${value}T00:00:00-03:00`);
  return Number.isFinite(timestamp) ? timestamp : null;
}
function taxRate(source, local = taxLocalDate(Date.now())) {
  if (!local || !source || !Number.isFinite(source.acumulado) || source.acumulado <= 0) return null;
  if (source.inicio !== `${local.year}-01-01` || typeof source.ate !== 'string' || source.ate < source.inicio || source.ate > local.date) return null;
  const startTime = taxDateTime(source.inicio), endDateTime = taxDateTime(source.ate);
  if (startTime === null || endDateTime === null) return null;
  const endTime = endDateTime + 864e5, duration = endTime - startTime;
  if (!(duration > 0) || !Number.isFinite(endTime)) return null;
  const perMillisecond = source.acumulado / duration;
  if (!(perMillisecond > 0) || !Number.isFinite(perMillisecond)) return null;
  return { amount: source.acumulado, endTime, perMillisecond, source };
}
function taxWidget(now = Date.now()) {
  const local = taxLocalDate(now);
  const federal = taxRate(DATA.arrecadacao, local);
  if (!federal) return null;
  const stateCandidate = taxRate(DATA.arrecadacaoEstadual, local);
  const state = stateCandidate?.source.inicio === federal.source.inicio ? stateCandidate : null;
  const valueOf = part => part ? part.amount + part.perMillisecond * Math.max(0, now - part.endTime) : 0;
  const perMillisecond = federal.perMillisecond + (state ? state.perMillisecond : 0);
  const value = valueOf(federal) + valueOf(state), federalValue = valueOf(federal), stateValue = state ? valueOf(state) : null;
  const perSecond = perMillisecond * 1000;
  if (![value, federalValue, perSecond].every(Number.isFinite) || !(perSecond > 0) || (stateValue !== null && !Number.isFinite(stateValue))) return null;
  return { value, federal: federalValue, state: stateValue, perSecond, source: federal.source, stateSource: state ? state.source : null };
}
const formatCurrency = v => 'R$ ' + Math.floor(v).toLocaleString('pt-BR');
const formatTrillions = v => 'R$ ' + (v / 1e12).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' tri';
function taxPerPerson(tax) {
  const population = tax?.source?.populacao;
  if (!Number.isSafeInteger(population) || population <= 0) return 'Sem dados';
  const amount = tax.value / population;
  return Number.isFinite(amount) ? formatCurrency(amount) : 'Sem dados';
}
function taxCard(quota = null, now = Date.now()) {
  const tax = taxWidget(now);
  if (!tax) return '';
  const observedQuota = Number.isFinite(quota) ? quota : 0, minutes = observedQuota / tax.perSecond / 60;
  const perPerson = taxPerPerson(tax);
  const scope = tax.state != null ? 'federais e estaduais' : 'federais';
  const sameDate = !tax.stateSource || tax.stateSource.ate === tax.source.ate;
  const dates = sameDate ? `até ${formatShortDate(tax.source.ate)}` : `até ${formatShortDate(tax.source.ate)} (federal) e ${formatShortDate(tax.stateSource.ate)} (estadual)`;
  const split = tax.state != null ? `<div class="tax-split" role="img" aria-label="Federal ${formatTrillions(tax.federal)}, estadual ${formatTrillions(tax.state)}">
      <span class="tax-split-bar"><i style="flex-grow:${tax.federal}"></i><i style="flex-grow:${tax.state}"></i></span>
      <span class="tax-split-legend"><span><i></i>Federal <b class="mono" data-tax-federal>${formatTrillions(tax.federal)}</b></span><span><i></i>Estadual <b class="mono" data-tax-state>${formatTrillions(tax.state)}</b></span></span>
    </div>` : '';
  return `<section class="card tax-card">
    <div class="tax-card-top"><span class="k">Contador de impostos · ${esc(String(tax.source.inicio).slice(0, 4))}</span><span class="live"><i></i>ao vivo</span></div>
    <div class="tax-value mono" data-tax aria-live="off">${formatCurrency(tax.value)}</div>
    <span class="muted">em impostos ${scope} pagos pelos brasileiros desde 1º de janeiro. Estimativa: os valores oficiais ${dates} mais a média diária do ano.</span>
    ${split}
    <div class="tax-grid">
      <div><b class="mono" data-tax-second>${formatCurrency(tax.perSecond)}</b><span>por segundo</span></div>
      <div><b class="mono" data-tax-person>${perPerson}</b><span>por pessoa no ano</span></div>
    </div>
    ${observedQuota ? `<p class="tax-related">A cota registrada para os deputados(as) da lista no recorte (${formatCitizenAmount(observedQuota)}) equivale ao que o país paga de impostos ${scope} em <b>${minutes < 1 ? Math.round(minutes * 60) + ' segundos' : Math.round(minutes) + ' minutos'}</b>.</p>` : ''}
    <p class="tax-sources src">Fontes: <a href="${esc(tax.source.url)}" target="_blank" rel="noopener">Receita Federal (impostos e contribuições administrados pela Receita até ${formatShortDate(tax.source.ate)}) ↗</a>${tax.stateSource ? `; <a href="${esc(tax.stateSource.url)}" target="_blank" rel="noopener">Tesouro Nacional, Siconfi (ICMS, IPVA e ITCD dos 27 estados até ${formatShortDate(tax.stateSource.ate)}) ↗</a>` : ''}. ${tax.stateSource ? 'Não inclui impostos municipais (IPTU, ISS e ITBI), porque nem todas as cidades publicam o dado mensal, nem taxas e contribuições estaduais.' : 'Não inclui impostos estaduais e municipais.'}</p>
  </section>`;
}
function taxTick(now = Date.now()) {
  const el = document.querySelector('[data-tax]');
  if (el) { // troca só o texto (characterData), sem disparar o reencaixe da grade
    const tax = taxWidget(now), card = document.querySelector('.tax-card');
    if (!tax) card?.remove();
    else {
      const set = (node, value) => { if (node && node.firstChild) node.firstChild.data = value; };
      const perPerson = taxPerPerson(tax);
      set(el, formatCurrency(tax.value)); set(document.querySelector('[data-tax-person]'), perPerson);
      if (tax.state != null) { set(document.querySelector('[data-tax-federal]'), formatTrillions(tax.federal)); set(document.querySelector('[data-tax-state]'), formatTrillions(tax.state)); }
    }
  }
  setTimeout(taxTick, 120);
}
taxTick();

/* ---------- Presença de todos(as) ---------- */
function attendanceRows(chamber = 'camara') {
  const rows = typeof profilePresenceRows === 'function' ? profilePresenceRows(chamber) : (chamber === 'camara' ? DATA.presencaTodos || [] : []);
  return rows.filter(p => p && Number.isFinite(p.dias) && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
}
function attendanceForPerson(id) {
  const p = typeof profilePresence === 'function'
    ? profilePresence(String(id).includes(':') ? String(id) : chamberPersonId(id))
    : attendanceRows().find(x => String(x.id) === String(id));
  return p && Number.isFinite(p.dias) && p.dias > 0 ? p : null;
}
function attendanceBar(p) {
  if (!p || !Number.isFinite(p.dias) || p.dias <= 0) return '';
  return `<span class="pbar" role="img" aria-label="${p.presente} presenças, ${p.justificadas} faltas justificadas, ${p.falta} faltas em ${p.dias} dias"><i style="width:${p.presente / p.dias * 100}%"></i><i class="j" style="width:${p.justificadas / p.dias * 100}%"></i><i class="f" style="width:${p.falta / p.dias * 100}%"></i></span>`;
}
function attendanceSorted(all = attendanceRows()) {
  const q = foldText(extrasState.attendanceQuery);
  const rate = person => person.presente / person.dias;
  return all.filter(person => !q || foldText(`${person.nome} ${person.partido} ${person.uf}`).includes(q))
    .sort((first, second) => (extrasState.attendanceOrder === 'less' ? rate(first) - rate(second) : rate(second) - rate(first)) || first.nome.localeCompare(second.nome));
}
function attendanceView() {
  const all = attendanceRows(), people = attendanceSorted(all);
  const average = all.length ? all.reduce((sum, person) => sum + person.presente / person.dias, 0) / all.length : null;
  // "Não faltaram nenhum dia" só entre quem tem o período inteiro: 14 de 14 dias de quem chegou agora não é o mesmo feito.
  const firstStart = all.map(person => person.inicio).filter(Boolean).sort()[0] || null;
  const fullAttendanceCount = all.filter(person => person.presente === person.dias && (!firstStart || person.inicio === firstStart)).length;
  const belowHalfCount = all.filter(person => person.presente / person.dias < 0.5).length;
  const sessionCount = all.length ? Math.max(...all.map(person => person.dias)) : null;
  const starts = all.map(person => person.inicio).filter(Boolean).sort(), ends = all.map(person => person.fim).filter(Boolean).sort();
  const period = typeof citizenQuotaPeriod === 'function' && starts.length ? citizenQuotaPeriod(starts[0], ends.at(-1)) : '';
  const stat = (value, label) => `<div class="card attendance-stat"><b class="mono">${value}</b><span>${label}</span></div>`;
  return `<div class="attendance-page">
    <section class="attendance-hero">
      <div class="attendance-intro">
        <button type="button" class="back" data-back>‹ Voltar</button>
        <span class="k">Câmara · ${period || 'mandato'}</span>
        <h1 class="h ph-t">Presença no Plenário</h1>
        <p class="ph-lead">${sessionCount === null ? 'Dados de presença indisponíveis neste recorte.' : `Quantos dos ${sessionCount} dias com sessão deliberativa do Plenário cada deputado(a) foi, no mandato atual${period ? ` (${period})` : ''}.`}</p>
      </div>
      <div class="attendance-summary">
        <div class="attendance-stats">
          ${stat(average === null ? 'Sem dados' : `${Math.round(average * 100)}%`, 'presença média')}
          ${stat(average === null ? '—' : fullAttendanceCount, 'não faltaram nenhum dia, com o mandato inteiro')}
          ${stat(average === null ? '—' : belowHalfCount, 'foram a menos da metade')}
        </div>
        <p class="muted">${average === null ? 'Não há registros de presença para calcular a média.' : `Média dos dados disponíveis: dos dias com sessão, em média, entre os(as) ${all.length} deputados(as) com dados de presença disponíveis.`}</p>
      </div>
    </section>
    <section class="attendance-filters" aria-label="Filtros">
      <div class="alerts-seg" role="group" aria-label="Ordenar">${[['less', 'Menos presentes'], ['more', 'Mais presentes']].map(([key, label]) => `<button type="button" data-attendance-order="${key}" aria-pressed="${extrasState.attendanceOrder === key}">${label}</button>`).join('')}</div>
      <label class="search attendance-search" for="attendance-q"><span class="sr-only">Buscar deputado(a)</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="attendance-q" type="search" placeholder="Nome, partido ou estado" value="${esc(extrasState.attendanceQuery)}" autocomplete="off"></label>
      <div class="legend attendance-legend"><span><i></i>Presente</span><span><i class="justified"></i>Falta justificada</span><span><i class="absent"></i>Falta</span></div>
    </section>
    <div id="attendance-list" class="attendance-results">${attendanceList(people)}</div>
    <p class="src attendance-source">${sessionCount === null ? 'Fonte: página de presença em Plenário de cada deputado(a) na Câmara; nenhum registro está disponível neste recorte.' : `Fonte: página de presença em Plenário de cada deputado(a) na Câmara, ${sessionCount} dias com sessão deliberativa no mandato atual${period ? ` (${period})` : ''}. Falta justificada é qualquer motivo publicado pela Câmara (missão autorizada, licença, atestado, decisão da Mesa). Quem assumiu no meio do mandato tem menos dias na conta e aparece com o mês de início.`}</p>
  </div>`;
}
/* "· desde jun/2026" para quem não tem o período inteiro: a contagem de dias não é comparável à dos demais. */
function attendanceStartTag(person, all = attendanceRows()) {
  const firstStart = all.map(row => row.inicio).filter(Boolean).sort()[0];
  if (!firstStart || !/^\d{4}-\d{2}$/.test(String(person.inicio || '')) || person.inicio <= firstStart) return '';
  const label = `${['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(person.inicio.slice(5)) - 1]}/${person.inicio.slice(0, 4)}`;
  return ` · desde ${esc(label)}`;
}
/* Linha de apoio: ausências justificadas (com o motivo mais comum informado pela Câmara) e faltas. */
function attendanceAbsences(person) {
  const top = (person.motivos || []).filter(([reason, count]) => reason && count > 0).sort((a, b) => b[1] - a[1])[0];
  const parts = [];
  if (person.justificadas) parts.push(`${person.justificadas} ${person.justificadas === 1 ? 'falta justificada' : 'faltas justificadas'}${top ? ` (mais comum: ${esc(top[0].toLowerCase())}, ${top[1]})` : ''}`);
  if (person.falta) parts.push(`${person.falta} ${person.falta === 1 ? 'falta' : 'faltas'}`);
  return parts.join(' · ') || 'Nenhuma ausência';
}
function attendanceList(people) {
  if (!people.length) return '<section class="card"><p>Ninguém encontrado.</p></section>';
  return `<span class="muted" role="status">${people.length} deputados(as)</span><ol class="attendance-list">${people.slice(0, extrasState.attendanceLimit).map(person => `<li>${profileLinkOpen(chamberPersonId(person.id), 'attendance-row')}${citizenAvatar({ id: chamberPersonId(person.id), name: person.nome }, 44)}
    <span class="attendance-who"><b>${esc(person.nome)}</b><small>${esc(person.partido)} · ${esc(person.uf)}${attendanceStartTag(person)}</small></span>
    <span class="attendance-bar">${attendanceBar(person)}<small>${attendanceAbsences(person)}</small></span>
    <span class="attendance-value"><b class="mono ${person.presente / person.dias < 0.5 ? 'warn' : ''}">${percent(person.presente, person.dias)}%</b><small class="mono">${person.presente} de ${person.dias}</small></span>${profileLinkClose(chamberPersonId(person.id))}</li>`).join('')}</ol>
  ${people.length > extrasState.attendanceLimit ? `<button type="button" class="opt alerts-more" data-attendance-more>Mostrar mais (${people.length - extrasState.attendanceLimit})</button>` : ''}`;
}
const foldText = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/* ---------- Quem votou o quê ---------- */
const VOTE_LABELS = { 'Sim': 'Sim', 'Não': 'Não', 'Abstenção': 'Abstenção', 'Obstrução': 'Obstrução', 'Artigo 17': 'Presidiu' };
function voteRowsForItem(v) {
  const voteRows = typeof profileVoteRows === 'function' ? profileVoteRows(v) : DATA.votosCompletos?.[v.id];
  if (!Array.isArray(voteRows)) return null;
  if (String(v.id).startsWith('senado:')) return voteRows;
  return voteRows.map(row => [row[0], row[1], row[2], row[3], v.secreta ? 'Presente' : (row[4] ? (VOTE_LABELS[row[4]] || row[4]) : 'Presente')]);
}
function whoVotedSection(v) {
  const allVotes = voteRowsForItem(v);
  if (!allVotes?.length) return `<section class="card wide" id="who-voted"><span class="k">Quem votou o quê</span><p class="muted">Sem registros individuais importados para esta votação.</p></section>`;
  const voteGroups = {};
  allVotes.forEach(row => (voteGroups[row[4]] = voteGroups[row[4]] || []).push(row));
  const groupOrder = ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu', 'Presente', 'Não votou'].filter(group => voteGroups[group]);
  if (!extrasState.votes[v.id]) extrasState.votes[v.id] = v.secreta ? 'Presente' : (voteGroups['Não']?.length || 0) <= (voteGroups['Sim']?.length || 0) && voteGroups['Não'] ? 'Não' : 'Sim';
  const selectedGroup = extrasState.votes[v.id], query = foldText(extrasState.voteQuery);
  const voters = (voteGroups[selectedGroup] || []).filter(row => !query || foldText(`${row[1]} ${row[2]} ${row[3]}`).includes(query)).sort((a, b) => a[1].localeCompare(b[1]));
  const partyCounts = {};
  (voteGroups[selectedGroup] || []).forEach(row => partyCounts[row[2]] = (partyCounts[row[2]] || 0) + 1);
  const topParties = Object.entries(partyCounts).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return `<section class="card wide" id="who-voted">
    <span class="k">Quem votou o quê</span>
    ${v.secreta ? '<p class="note">Voto secreto: a Câmara só publica quem marcou presença na votação, não o voto de cada um(a).</p>' : ''}
    <div class="chips" role="group" aria-label="Filtrar por voto">${groupOrder.map(group => `<button type="button" class="fchip" data-vote-group="${esc(group)}" data-vote-id="${esc(v.id)}" aria-pressed="${selectedGroup === group}">${group === 'Presente' ? 'Marcaram presença' : group} <b>${voteGroups[group].length}</b></button>`).join('')}</div>
    ${(voteGroups[selectedGroup] || []).length > 8 ? `<label class="search" for="vote-search-q"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="vote-search-q" type="search" placeholder="Procurar nome, partido ou estado" value="${esc(extrasState.voteQuery)}" autocomplete="off"></label>` : ''}
    ${topParties.length > 1 && selectedGroup !== 'Não votou' ? `<span class="muted">Partidos com mais votos “${esc(selectedGroup.toLowerCase())}”: ${topParties.map(([party, count]) => `${esc(party)} ${count}`).join(' · ')}</span>` : ''}
    <div class="citizen-list ext-vlist">${voters.slice(0, extrasState.voteLimit).map(row => `<button type="button" class="citizen-row" data-politician="${chamberPersonId(row[0])}">${citizenAvatar({ id: chamberPersonId(row[0]), name: row[1] }, 44)}<span class="citizen-rowtxt"><b>${esc(row[1])}</b><small>${esc(row[2])} · ${esc(row[3])}</small></span><span class="citizen-rowval"><span class="vchip ${selectedGroup === 'Sim' ? 'yes' : selectedGroup === 'Não' ? 'no' : ''}">${esc(selectedGroup === 'Presente' ? 'presente' : selectedGroup.toLowerCase())}</span></span></button>`).join('') || '<p class="muted">Ninguém com esse nome neste grupo.</p>'}</div>
    ${voters.length > extrasState.voteLimit ? `<button type="button" class="opt citizen-more" data-vote-more>Mostrar mais (${voters.length - extrasState.voteLimit})</button>` : ''}
    <span class="muted">Toque num nome para ver a ficha: quanto gastou, presença e como votou.</span>
  </section>`;
}

/* ---------- Ficha leve: presença e votos de quem é deputado(a) ---------- */
function votesForPerson(personNumber) {
  const id = String(personNumber).includes(':') ? String(personNumber) : chamberPersonId(personNumber);
  const senate = id.startsWith('senado:');
  const rows = typeof profileVotes === 'function' ? profileVotes(id) : (DATA.votacoes || []).map(vote => {
    const rows = voteRowsForItem(vote) || [];
    const match = rows.find(row => String(row[0]) === String(personNumber).replace(/^camara:/, ''));
    return { vote, recordedVote: match?.[4] ?? null };
  });
  return (rows || []).filter(record => record?.vote)
    .sort((first, second) => String(second.vote.data).localeCompare(String(first.vote.data)));
}
function activitySource(section, label = 'Conferir na fonte do Senado') {
  if (!section) return '';
  if (typeof profileSource === 'function') return profileSource(section, label);
  const url = typeof section.sourceUrl === 'string' ? section.sourceUrl : '';
  const href = /^https?:\/\//i.test(url) ? url : '';
  const period = activityPeriod(section);
  const annualSources = (Array.isArray(section.sources) ? section.sources : []).map(source => {
    const sourceUrl = typeof source?.sourceUrl === 'string' && /^https?:\/\//i.test(source.sourceUrl) ? source.sourceUrl : '';
    const status = source?.status === 'partial' ? 'parcial' : ['imported', 'complete', 'completed', 'success', 'ok'].includes(source?.status) ? 'consultado' : 'indisponível';
    const annualRange = source?.startDate && source?.endDate ? ` · ${dateBR(source.startDate)} a ${dateBR(source.endDate)}` : '';
    const fetchedAt = source?.fetchedAt ? ` · fotografia ${dateBR(source.fetchedAt)}` : '';
    const caption = `${source?.year || ''} · ${status}${annualRange}${fetchedAt}`;
    return sourceUrl ? `<a href="${esc(sourceUrl)}" target="_blank" rel="noopener">${esc(caption)} ↗</a>` : `<span>${esc(caption)}</span>`;
  }).filter(Boolean);
  return `<span class="src">${period ? `${esc(datesInTextBR(period))}. ` : ''}${section.fetchedAt ? `Fotografia: ${esc(dateBR(section.fetchedAt))}. ` : ''}${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : ''}${annualSources.length ? `Fontes por ano: ${annualSources.join(' · ')}` : ''}</span>`;
}
function activityPeriod(section) {
  return typeof profileSectionPeriod === 'function' ? profileSectionPeriod(section)
    : section?.startDate && section?.endDate ? `de ${dateBR(section.startDate)} a ${dateBR(section.endDate)}` : section?.period ? datesInTextBR(section.period) : '';
}
function senateLoading() {
  return typeof profileSenateLoading === 'function' && profileSenateLoading();
}
function senateRegisteredPresence(id) {
  if (typeof profileRegisteredPresence !== 'function') return null;
  const row = profileRegisteredPresence(id);
  return row && Number.isFinite(row.presente) && row.presente > 0 ? row : null;
}
function profileExtras(id) {
  const [chamber, personNumber] = String(id).split(':');
  if (chamber === 'senado') {
    if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
    const presenceSource = typeof profileSenateSource === 'function' ? profileSenateSource('presenca') : null;
    const voteSource = typeof profileSenateSource === 'function' ? profileSenateSource('votacoes') : null;
    const loading = senateLoading();
    const presenceRecord = senateRegisteredPresence(id);
    const sessionCount = Number.isFinite(presenceSource?.sessionCount) ? presenceSource.sessionCount : null;
    const votes = votesForPerson(id);
    const votePeriod = activityPeriod(voteSource);
    const official = typeof citizenSourceUrl === 'function' ? citizenSourceUrl({ id })
      : /^\d+$/.test(personNumber || '') ? `https://www25.senado.leg.br/web/senadores/senador/-/perfil/${encodeURIComponent(personNumber)}` : null;
    const presence = presenceRecord ? `<section class="card">
      <span class="k">Presença registrada · Senado</span>
      <div><span class="big">${presenceRecord.presente}</span> <span class="muted">sessões com presença registrada</span></div>
      ${sessionCount === null ? '' : `<p class="muted">${sessionCount} listas de sessões consultadas no recorte.</p>`}
      <p class="muted">A fonte deste recorte registra presenças; ausência de linha não confirma falta.</p>
      ${presenceSource?.detail ? `<p class="muted">${esc(datesInTextBR(presenceSource.detail))}</p>` : ''}
      ${activitySource(presenceSource)}
    </section>` : `<section class="card"><span class="k">Presença registrada · Senado</span>${loading ? (typeof skel === 'function' ? skel('linhas', 2) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : '<p class="muted">Sem dados de presença do Senado importados para este perfil. Ausência de registro não significa zero presença nem falta.</p>'}${presenceSource?.detail ? `<p class="muted">${esc(datesInTextBR(presenceSource.detail))}</p>` : ''}${activitySource(presenceSource)}</section>`;
    const voteList = votes.slice(0, extrasState.senateVoteLimit).map(({ vote, recordedVote }) => {
      const voteLabel = recordedVote === 'Presente' ? 'Presença registrada · sem voto' : recordedVote == null ? 'Sem registro importado' : String(recordedVote).toLowerCase();
      const content = `<b>${esc(voteLabel)}</b><span>${esc(vote.titulo || vote.proposicao || 'Votação nominal')}</span>${vote.data ? `<small>${esc(dateBR(vote.data))}</small>` : ''}`;
      return typeof profileVoteButton === 'function' ? profileVoteButton(vote, content, 'vt') : `<a class="vt" href="${esc(vote.sourceUrl || '')}" target="_blank" rel="noopener">${content}</a>`;
    }).join('');
    return `${presence}
    <section class="card"><span class="k">Votações nominais do Senado${votePeriod ? ` · ${esc(votePeriod)}` : ''}${votes.length ? ` · ${votes.length}` : ''}</span>
      ${loading && !voteSource ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : votes.length ? `<div class="votes">${voteList}</div>${votes.length > extrasState.senateVoteLimit ? `<button type="button" class="opt citizen-more" data-senate-votes-more>Mostrar mais (${votes.length - extrasState.senateVoteLimit})</button>` : ''}` : `<p class="muted">${!voteSource ? 'Votações nominais do Senado ainda não importadas.' : voteSource.status === 'unavailable' ? 'Dados de votações nominais do Senado indisponíveis neste recorte.' : voteSource.status === 'partial' ? 'Sem registros individuais disponíveis neste recorte parcial.' : 'Sem registros individuais de votação do Senado para este perfil neste recorte.'}</p>`}
      <p class="muted">Votações secretas foram excluídas; a lista mostra somente votações nominais abertas e seus registros individuais.</p>
      ${voteSource?.detail ? `<p class="muted">${esc(datesInTextBR(voteSource.detail))}</p>` : ''}
      ${activitySource(voteSource)}
      ${official ? `<a class="fchip" href="${esc(official)}" target="_blank" rel="noopener">Conferir perfil no Senado ↗</a>` : ''}
    </section>`;
  }
  if (chamber !== 'camara') return '';
  const presenceRecord = attendanceForPerson(personNumber), votes = votesForPerson(id), attendanceRecords = attendanceRows();
  const averagePresence = attendanceRecords.length ? attendanceRecords.reduce((sum, record) => sum + record.presente / record.dias, 0) / attendanceRecords.length : null;
  const voteCount = votes.length;
  // Um link por ano publicado pela Câmara (helper da ficha); sem ele, o ano do fim do período observado.
  const presenceLinks = typeof chamberPresenceSourceLinks === 'function' ? chamberPresenceSourceLinks(personNumber, presenceRecord, 'Presença no Plenário')
    : /^\d+$/.test(personNumber || '') ? `<a href="https://www.camara.leg.br/deputados/${encodeURIComponent(personNumber)}/presenca-plenario/${esc(String(presenceRecord?.fim || '2026').slice(0, 4))}" target="_blank" rel="noopener">Presença no Plenário ↗</a>` : '';
  return `${presenceRecord ? `<section class="card ${presenceRecord.presente / presenceRecord.dias < 0.5 ? 'alarm' : ''}">
    <span class="k">Presença nas sessões de votação · ${esc(typeof citizenQuotaPeriod === 'function' ? citizenQuotaPeriod(presenceRecord.inicio, presenceRecord.fim) || 'mandato' : 'mandato')}</span>
    <div><span class="big">${presenceRecord.presente}/${presenceRecord.dias}</span> <span class="muted">dias${averagePresence === null ? '' : ` · média dos registros válidos ${Math.round(averagePresence * 100)}%`}</span></div>
    ${attendanceBar(presenceRecord)}
    <div class="legend"><span><i style="background:var(--accent)"></i>Presente ${presenceRecord.presente}</span><span><i style="background:var(--muted);opacity:.55"></i>Justificada ${presenceRecord.justificadas}</span><span><i style="background:var(--warn)"></i>Falta ${presenceRecord.falta}</span></div>
    ${presenceRecord.motivos?.length ? `<p class="note">Justificativas: ${presenceRecord.motivos.map(([reason, count]) => `${esc(reason.toLowerCase())} (${count})`).join(', ')}.</p>` : ''}
    <button type="button" class="more" data-go="attendance">Ver a presença de todos(as)</button>
  </section>` : `<section class="card"><span class="k">Presença nas sessões de votação · mandato</span><p class="muted">Sem registro importado para este perfil. Ausência de dado não significa zero presença.</p></section>`}
  <section class="card"><span class="k">Votações selecionadas do Placar · ${voteCount}</span>
    ${voteCount ? `<div class="votes">${votes.map(({ vote, recordedVote }) => {
      const voteLabel = recordedVote == null ? 'Sem registro importado' : vote.secreta ? 'Presença registrada · voto secreto' : String(recordedVote).toLowerCase();
      const content = `<b>${esc(voteLabel)}</b><span>${esc(vote.titulo)}</span>`;
      return typeof profileVoteButton === 'function' ? profileVoteButton(vote, content, 'vt') : `<button type="button" class="vt" data-vote="${esc(vote.id)}">${content}</button>`;
    }).join('')}</div>` : '<p class="muted">Nenhuma votação do Placar com registro para esta pessoa desde fev/2023.</p>'}
    <span class="muted">A lista cobre apenas as votações selecionadas no Placar; falta de registro não identifica motivo nem situação do mandato.</span>
  </section>
  <span class="src">Fonte: Câmara dos Deputados. ${presenceLinks ? `${presenceLinks} ` : ''}Os botões de votação abrem o resumo e as fontes oficiais de cada votação.</span>`;
}

/* ---------- Comparar perfis ---------- */
/* Endereço compartilhável: /comparar/deputado-73604-vs-senador-22 (mesmos prefixos das fichas). */
const COMPARISON_PREFIX = { camara: 'deputado', senado: 'senador' };
function comparisonPath(ids = extrasState.comparisonIds) {
  const parts = ids.map(id => { const [house, number] = String(id).split(':'); return COMPARISON_PREFIX[house] && /^\d+$/.test(number || '') ? `${COMPARISON_PREFIX[house]}-${number}` : null; });
  return parts.length === 2 && parts.every(Boolean) ? `/comparar/${parts.join('-vs-')}` : '/comparar';
}
function comparisonIdsFromPath(path) {
  const match = String(path || '').match(/^\/comparar\/(deputado|senador)-(\d+)-vs-(deputado|senador)-(\d+)$/);
  if (!match) return null;
  const id = (prefix, number) => `${prefix === 'deputado' ? 'camara' : 'senado'}:${number}`;
  const ids = [id(match[1], match[2]), id(match[3], match[4])];
  return ids[0] === ids[1] ? null : ids;
}
// Troca de pessoa atualiza o endereço sem empilhar histórico.
function syncComparisonLocation() { if (state.view === 'compare' && typeof syncLocation === 'function') syncLocation('replace'); }
function addComparisonPerson(id) {
  if (!extrasState.comparisonIds.includes(id)) extrasState.comparisonIds = [...extrasState.comparisonIds, id].slice(-2);
  extrasState.comparisonQuery = ''; extrasState.comparisonKey = null; extrasState.comparisonResults = null; extrasState.comparisonError = null;
  extrasState.comparisonIds.forEach(x => citizenGet('/api/c/politico/' + encodeURIComponent(x)).then(() => state.view === 'compare' && rerender()).catch(e => { extrasState.comparisonError = citizenErrorMessage(e); if (state.view === 'compare') rerender(); }));
}
function searchComparisonPeople(q) {
  const query = String(q || '').trim(), key = query;
  extrasState.comparisonQuery = String(q || '');
  if (extrasState.comparisonLoading && extrasState.comparisonKey === key) return;
  extrasState.comparisonKey = key; extrasState.comparisonLoading = true; extrasState.comparisonError = null; extrasState.comparisonResults = null; renderComparisonPicker();
  const path = `/api/c/politicos?pageSize=8&page=1&ordem=nome${query ? '&q=' + encodeURIComponent(query) : ''}`;
  citizenGet(path).then(d => { if (extrasState.comparisonKey !== key || extrasState.comparisonQuery.trim() !== query) return; extrasState.comparisonResults = d.itens; extrasState.comparisonLoading = false; renderComparisonPicker(); })
    .catch(e => { if (extrasState.comparisonKey !== key || extrasState.comparisonQuery.trim() !== query) return; extrasState.comparisonLoading = false; extrasState.comparisonResults = []; extrasState.comparisonError = citizenErrorMessage(e); renderComparisonPicker(); });
}
function comparisonPickerList() {
  if (extrasState.comparisonLoading) return skel('linhas', 3);
  if (extrasState.comparisonError) return `<p class="muted">Não deu para carregar a lista. ${esc(extrasState.comparisonError)}</p><button type="button" class="more" data-cmp-retry>Tentar de novo</button>`;
  if (extrasState.comparisonResults === null) return skel('linhas', 3);
  if (!extrasState.comparisonResults.length) return '<p class="muted">Ninguém encontrado.</p>';
  return extrasState.comparisonResults.filter(x => !extrasState.comparisonIds.includes(x.id)).map(x => `<button type="button" class="citizen-row" data-cmp-add="${esc(x.id)}">${citizenAvatar(x, 40)}<span class="citizen-rowtxt"><b>${esc(citizenName(x.name))}</b><small>${citizenRoleDescription(x)}</small></span><span class="citizen-rowval"><span class="fchip">Escolher</span></span></button>`).join('');
}
function renderComparisonPicker() { const el = document.getElementById('comparison-res'); if (el) el.innerHTML = comparisonPickerList(); }
function comparisonView() {
  if (extrasState.comparisonIds.length < 2 && extrasState.comparisonResults === null && !extrasState.comparisonLoading && !extrasState.comparisonError) searchComparisonPeople(extrasState.comparisonQuery);
  const profiles = extrasState.comparisonIds.map(id => ({ id, data: citizenState.cache.get('/api/c/politico/' + encodeURIComponent(id)) }));
  const readyProfiles = profiles.filter(item => item.data).map(item => item.data);
  const pickerSection = extrasState.comparisonIds.length < 2 ? `<section class="card wide"><span class="k">${extrasState.comparisonIds.length ? 'Com quem comparar?' : 'Escolha dois(duas) políticos(as)'}</span>
      <label class="search" for="comparison-q"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="comparison-q" type="search" placeholder="Nome, partido ou estado" value="${esc(extrasState.comparisonQuery)}" autocomplete="off"></label>
      <div id="comparison-res" class="citizen-list">${comparisonPickerList()}</div></section>` : '';
  let content = '', footer = '';
  if (extrasState.comparisonIds.length === 2 && readyProfiles.length === 2) {
    content = comparisonTable(readyProfiles);
    footer = `<div class="compare-actions">${shareActionsHTML(comparisonShareCard(readyProfiles), 'Compartilhar imagem')}<a class="fchip" href="/partidos" data-go="parties">Comparar partidos →</a></div>`;
  } else if (extrasState.comparisonIds.length === 2) content = extrasState.comparisonError ? `<section class="card wide"><p>Não deu para abrir as fichas.</p><p class="muted">${esc(extrasState.comparisonError)}</p></section>` : skel('cmp');
  return `<div class="compare-page">
    <div class="compare-intro">
      <button type="button" class="back" data-back>‹ Voltar</button>
      <span class="k">Comparar</span>
      <h1 class="h ph-t">Lado a lado</h1>
      <p class="ph-lead">Gastos, alertas, presença e votos de dois(duas) políticos(as) na mesma tela.</p>
    </div>
    ${extrasState.comparisonIds.length ? `<div class="compare-people">${extrasState.comparisonIds.map(comparisonPersonCard).join('')}</div>` : ''}
    ${pickerSection}${content}${footer}
  </div>`;
}
/* Cartão de cada pessoa escolhida: "Trocar" tira da comparação e reabre a busca. */
function comparisonPersonCard(id) {
  const f = citizenState.cache.get('/api/c/politico/' + encodeURIComponent(id));
  const p = f?.pessoa || { id, name: '…' }, name = esc(citizenName(p.name));
  return `<div class="card compare-person">${citizenAvatar(p, 64)}
    <span class="compare-person-name">${f ? `<button type="button" data-politician="${esc(id)}">${name}</button>` : `<b>${name}</b>`}<small>${ROLE_LABELS[p.role] ? `<span class="compare-person-role">${esc(ROLE_LABELS[p.role])} · </span>` : ''}${esc([p.party, p.uf].filter(Boolean).join(' · '))}</small></span>
    <button type="button" class="compare-swap" data-cmp-del="${esc(id)}" aria-label="Trocar ${name}">Trocar</button>
  </div>`;
}
/* Número de alertas só quando alguma regra pôde avaliar a pessoa; senão, "sem avaliação" (não é zero). */
function alertCountOrNull(profile) {
  const evaluated = typeof alertCoverageState === 'function' ? alertCoverageState(profile.coberturaAlertas).evaluated : profile.total != null;
  return evaluated || profile.alertas?.length ? (profile.alertas || []).length : null;
}
/* Cartão para compartilhar a comparação: um card por pessoa (custo, presença, para onde vai a cota, maior nota),
   e os votos em comum. A etiqueta só diz o fato (custa menos, mais presente) e só aparece quando os números se
   comparam: mesma Casa e mesma regra. Alertas não ganham etiqueta; dado ausente fica "Sem dados". */
function comparisonShareCard([a, b]) {
  const name = f => citizenName(f.pessoa.name);
  const chamber = f => String(f.pessoa.id).split(':')[0];
  const sameHouse = chamber(a) === chamber(b);
  const figures = [a, b].map(comparisonCostFigures);
  const costs = figures.map(item => item.total ? item.total.cents / 100 : null);
  const costLabel = !sameHouse ? 'Média por mês*' : chamber(a) === 'senado' ? 'Despesas médias por mês' : 'Custo médio por mês';
  const presence = [a, b].map(f => {
    if (chamber(f) === 'senado') { const record = senateRegisteredPresence(f.pessoa.id); return record ? { text: `${record.presente} sessões`, share: null } : null; }
    const p = attendanceForPerson(f.pessoa.id);
    return p ? { text: `${Math.round(p.presente / p.dias * 100)}%`, share: p.presente / p.dias } : null;
  });
  const costWinner = sameHouse && costs.every(v => v != null) && costs[0] !== costs[1] ? (costs[0] < costs[1] ? 0 : 1) : null;
  const shares = presence.map(p => p?.share ?? null);
  const presenceWinner = sameHouse && shares.every(v => v != null) && Math.round(shares[0] * 100) !== Math.round(shares[1] * 100) ? (shares[0] > shares[1] ? 0 : 1) : null;
  const costGap = costWinner === null ? '' : `${formatCitizenAmount(Math.abs(figures[0].total.cents - figures[1].total.cents) / 100)} a menos por mês`;
  const monthLabel = item => item?.month && item?.year ? `${SHORT_MONTHS[item.month]}/${item.year}` : '';
  const quotaCategories = [a, b].map(f => shareQuotaCategories(f.categorias));
  const people = [a, b].map((f, index) => ({
    name: name(f), photo: typeof sharePhotoUrl === 'function' ? sharePhotoUrl(f.pessoa.id) : null, photoCredit: chamber(f) === 'senado' ? 'Senado Federal' : 'Câmara dos Deputados',
    meta: [f.pessoa.party, f.pessoa.uf].filter(Boolean).join(' · '),
    stats: [
      { label: costLabel, value: costs[index] == null ? 'Sem dados' : formatCitizenAmount(costs[index]),
        tag: costWinner === index ? costGap : '', behind: costWinner !== null && costWinner !== index },
      { label: chamber(f) === 'senado' ? 'Presença registrada · Senado' : 'Presença no Plenário', value: presence[index]?.text || 'Sem dados',
        tag: presenceWinner === index ? 'mais presente' : '', behind: presenceWinner !== null && presenceWinner !== index },
    ],
    categories: quotaCategories[index].items,
    categoryNote: quotaCategories[index].hasRefunds ? 'Percentuais dos saldos positivos; estornos mantidos no total.' : '',
    categoryEmptyLabel: quotaCategories[index].items.length ? '' : Array.isArray(f.categorias) && f.categorias.length
      ? 'Sem categorias com saldo positivo' : 'Sem notas da cota no período',
    top: f.maiores?.[0] ? { value: brl(f.maiores[0].valor), what: [f.maiores[0].categoria, monthLabel(f.maiores[0])].filter(Boolean).join(' · '),
      who: f.maiores[0].fornecedor ? citizenName(f.maiores[0].fornecedor) : '' } : null,
  }));
  const { chamber: voteChamber, votes } = comparisonVotes(a, b);
  const comparable = votes.filter(comparableVotePair);
  const typical = voteChamber === 'camara' && typeof chamberPairAgreement === 'function' ? chamberPairAgreement() : null;
  const agreement = comparable.length ? { matching: comparable.filter(record => record.voteA === record.voteB).length, total: comparable.length,
    source: voteChamber === 'senado' ? 'votações nominais do Senado' : 'votações do Placar', typical } : null;
  return {
    layout: 'faceoff', title: `${name(a)} × ${name(b)}`, people, agreement,
    alerts: [a, b].map(f => alertCountOrNull(f) == null ? 'Sem avaliação' : String(f.alertas.length)),
    fileName: `${name(a)}-x-${name(b)}`,
    footnote: sameHouse
      ? `Médias mensais do mandato. Dados ${chamber(a) === 'senado' ? 'do Senado' : 'da Câmara'}. Custo: ${COST_COMPOSITION[chamber(a)] || 'partes publicadas'}.`
      : '*Médias mensais do mandato. Câmara e Senado publicam partes diferentes do custo e medem presença de jeitos diferentes: sem destaque entre as Casas.',
  };
}
function comparisonProfile(f) {
  return typeof profileData === 'function' ? profileData(f.pessoa || f.pessoa?.id) || {} : {};
}
function comparisonParticipation(profile) {
  const mandate = profile.mandate || {}, person = profile.person || {};
  const values = [mandate.participacao || person.position, mandate.exercicio || person.employmentStatus].filter(Boolean);
  if (!values.length && person.foraDaLista) values.push('Fora da lista atual');
  return values.length ? values.map(esc).join('<br>') : 'Sem informação importada';
}
function comparisonContact(profile) {
  const contact = profile.contact;
  if (!contact) return 'Sem dados importados';
  const available = [contact.email, contact.endereco, ...(Array.isArray(contact.telefones) ? contact.telefones : []), ...(Array.isArray(contact.redes) ? contact.redes.map(network => network.url) : [])].some(Boolean);
  if (!available) return 'Sem contato informado neste recorte';
  return contact.status === 'partial' ? 'Disponível em recorte parcial' : 'Dados disponíveis';
}
/* Quantos PL, PLP e PEC a pessoa apresentou e o que virou lei, pelos mesmos contadores da ficha.
   Mais projetos não é melhor nem pior: a linha informa, sem destaque. */
function comparisonProjects(profile) {
  if (!profile.projects || typeof profileProjectStats !== 'function') return '<span class="muted">Sem dados importados</span>';
  const stats = profileProjectStats(profile);
  if (stats.count === null) return `<span class="muted">${stats.collection ? 'Consulta incompleta; total não confirmado' : 'Sem dados importados'}</span>`;
  const outcome = stats.confirmed ? stats.status : stats.consulted ? 'situação consultada, sem classificação confirmada' : 'situação não consultada';
  return `<b>${stats.count}</b><small> ${stats.count === 1 ? 'projeto' : 'projetos'}${stats.collection ? ` · ${stats.collection}` : ''}</small><br><small>${esc(outcome)}</small>`;
}
function comparisonCompensation(profile) {
  const salary = profile.compensation;
  if (!salary || !Number.isFinite(salary.amount)) return 'Sem referência importada';
  return `${salary.amount.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} por mês · referência do cargo, não pagamento individual`;
}
function comparisonOffice(profile) {
  const office = profile.office;
  if (!office) return 'Sem dados importados';
  const value = Number.isFinite(office.amount)
    ? office.amount.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
    : 'valor não informado';
  const period = office.period || (Number.isFinite(office.months) ? `${office.months} meses` : 'período não informado');
  const monthNames = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const months = Object.keys(office.months || {}).map(Number).filter(n => n >= 1 && n <= 12).sort((a, b) => a - b);
  const observed = months.length ? ` · meses: ${months.map(m => monthNames[m]).join(', ')}` : '';
  const staff = Number.isFinite(office.staffActive) ? `${office.staffActive} pessoas ativas` : 'equipe não informada';
  const fetched = office.fetchedAt ? `fotografia ${dateBR(office.fetchedAt)}` : 'fotografia sem data';
  return `${value} · ${esc(period)}${observed} · ${staff} · ${esc(fetched)}`;
}
/* Custo e partes de cada um pela própria Casa: Câmara pela composição do mandato, Senado pelas despesas
   identificadas. As Casas não publicam as mesmas partes: entre Casas os valores ficam lado a lado, com a
   composição escrita e sem destaque de menor (decisão de 10/10/2026, docs/mandate-cost-collection.md). */
const COST_COMPOSITION = { camara: 'salário, auxílios, cota e verba de gabinete', senado: 'remuneração, equipe do gabinete e cota' };
function comparisonCostFigures(f) {
  const profile = comparisonProfile(f), house = String(f.pessoa?.id || '').split(':')[0];
  const money = cents => Number.isSafeInteger(cents) ? { cents } : null;
  if (house === 'camara' && profile.cost) {
    const part = key => profile.cost.parts?.[key];
    /* `months` vem como lista de períodos (snapshot expandido) ou como contagem. */
    const monthCount = value => Array.isArray(value) ? value.length : Number.isInteger(value) ? value : null;
    const withMonths = key => money(part(key)?.averageCents) && { cents: part(key).averageCents, months: monthCount(part(key).months) };
    const average = typeof profileCostAverage === 'function' ? profileCostAverage(profile.cost, f.snapshotAt) : null;
    return { house, total: average ? { cents: average.cents, months: average.months.length } : null,
      remuneration: withMonths('remuneration'), office: withMonths('office'), officePeople: null };
  }
  if (house === 'senado' && profile.senateCost && typeof senateCostFigures === 'function') return { house, ...senateCostFigures(profile.senateCost, f) };
  return { house, total: null, remuneration: null, office: null, officePeople: null };
}
/* `partOnly`: a parte é média de todos os meses em que foi publicada, não só dos meses assentados do total. */
const comparisonCostMoney = (item, partOnly = false) => item ? `<b class="mono">${esc(formatCitizenAmount(item.cents / 100))}</b><small> /mês${Number.isInteger(item.months) ? ` · média de ${item.months} ${item.months === 1 ? 'mês' : 'meses'}${partOnly ? ' com a parte publicada' : ''}` : ''}</small>` : 'Sem dados';
function comparisonCostRows(a, b, sideHtml) {
  const [costA, costB] = [a, b].map(comparisonCostFigures);
  if (costA.house === costB.house) {
    const label = costA.house === 'senado' ? 'Despesas identificadas por mês · Senado' : 'Custa por mês · Câmara';
    return `<div class="cmp-row"><span class="cmp-l">${label}</span>${sideHtml(costA.total ? costA.total.cents : null, costB.total ? costB.total.cents : null, (value, side) => comparisonCostMoney(side === 'a' ? costA.total : costB.total))}</div>`;
  }
  const cell = figures => `${comparisonCostMoney(figures.total)}${COST_COMPOSITION[figures.house] ? `<br><small>${COST_COMPOSITION[figures.house]}</small>` : ''}`;
  return `${comparisonInfoRow('Quanto custa por mês', cell(costA), cell(costB))}
    <div class="cmp-row"><span class="cmp-l"></span><div class="cmp-v muted cmp-source" style="grid-column: 2 / -1">Câmara e Senado publicam partes diferentes: parte da diferença vem do que cada Casa inclui, não só do quanto cada um gasta. Por isso nenhum valor é destacado como menor.</div></div>`;
}
function comparisonOfficeCell(f) {
  const figures = comparisonCostFigures(f);
  if (!figures.office) return comparisonOffice(comparisonProfile(f));
  const what = figures.house === 'senado' ? 'equipe comissionada do gabinete (Senado)' : 'verba de gabinete (Câmara)';
  return `${comparisonCostMoney(figures.office, true)}<br><small>${what}${figures.officePeople ? ` · ${figures.officePeople} pessoas no mês mais recente` : ''}</small>`;
}
function comparisonCompensationCell(f) {
  const figures = comparisonCostFigures(f);
  if (!figures.remuneration) return esc(comparisonCompensation(comparisonProfile(f)));
  return `${comparisonCostMoney(figures.remuneration, true)}<br><small>bruto pago, pela folha ${figures.house === 'senado' ? 'do Senado' : 'da Câmara'}</small>`;
}
function comparisonInfoRow(label, a, b) {
  return `<div class="cmp-row"><span class="cmp-l">${esc(label)}</span><div class="cmp-v">${a}</div><div class="cmp-v">${b}</div></div>`;
}
function comparisonAttendanceRows(a, b, pA, pB) {
  const chamberA = String(a.pessoa.id).split(':')[0], chamberB = String(b.pessoa.id).split(':')[0];
  const senate = chamberA === 'senado' || chamberB === 'senado';
  if (senate && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const loading = senate && senateLoading();
  const source = senate && typeof profileSenateSource === 'function' ? profileSenateSource('presenca') : null;
  const value = p => p ? p.presente / p.dias : null;
  const display = (p, applies = true) => !applies ? '<span class="muted">Não se aplica</span>' : loading && !p ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : p ? `<b>${Math.round(value(p) * 100)}%</b>` : '<span class="muted">Sem dados</span>';
  const line = (label, x, y, rank, sourceMeta = '', applicableA = true, applicableB = true) => {
    const okX = Number.isFinite(x), okY = Number.isFinite(y);
    const winner = rank && okX && okY && x !== y ? ((x > y) === (rank === 'maior') ? 'a' : 'b') : '';
    return `<div class="cmp-row"><span class="cmp-l">${label}${sourceMeta ? `<small>${sourceMeta}</small>` : ''}</span><div class="cmp-v ${winner === 'a' ? 'best' : ''}">${display(okX ? { presente: x, dias: 1 } : null, applicableA)}</div><div class="cmp-v ${winner === 'b' ? 'best' : ''}">${display(okY ? { presente: y, dias: 1 } : null, applicableB)}</div></div>`;
  };
  if (chamberA === chamberB) {
    if (chamberA === 'senado') {
    const firstRecord = senateRegisteredPresence(a.pessoa.id), secondRecord = senateRegisteredPresence(b.pessoa.id);
    const sessionCount = Number.isFinite(source?.sessionCount) ? source.sessionCount : null;
    const show = record => loading && !record ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>'
      : record ? `<b>${record.presente}</b><small> sessões com presença registrada</small>` : '<span class="muted">Sem dados</span>';
    const detail = 'Contagem de registros positivos. Faltas e justificativas não apuradas; ausência de linha não confirma falta.';
      return `<div class="cmp-row"><span class="cmp-l">Presença registrada · Senado</span><div class="cmp-v">${show(firstRecord)}</div><div class="cmp-v">${show(secondRecord)}</div></div>
        <div class="cmp-row"><div class="cmp-v muted cmp-source" style="grid-column:1 / -1">${sessionCount === null ? '' : `${sessionCount} listas de sessões consultadas. `}${esc(detail)}${activitySource(source, 'Fonte e período')}</div></div>`;
    }
    return line('Presença no Plenário · Câmara', value(pA), value(pB), 'maior');
  }
  const firstRecord = chamberA === 'senado' ? senateRegisteredPresence(a.pessoa.id) : null;
  const secondRecord = chamberB === 'senado' ? senateRegisteredPresence(b.pessoa.id) : null;
  const sessionCount = Number.isFinite(source?.sessionCount) ? source.sessionCount : null;
  const sourceDetail = 'Contagem de registros positivos. Faltas e justificativas não apuradas; ausência de linha não confirma falta.';
  /* Cada Casa com a própria medida, na mesma linha e sem destaque: a Câmara publica presença e faltas por
     sessão (porcentagem); o Senado, só os registros de presença (contagem). */
  const cell = (chamber, attendance, record) => {
    if (chamber === 'camara') return attendance ? `<b>${Math.round(value(attendance) * 100)}%</b><br><small>das sessões deliberativas da Câmara</small>` : '<span class="muted">Sem dados</span>';
    if (loading && !record) return '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>';
    return record ? `<b>${record.presente}</b><small> sessões</small><br><small>com presença registrada no Senado${sessionCount === null ? '' : `, de ${sessionCount} listas consultadas`}</small>` : '<span class="muted">Sem dados</span>';
  };
  return `<div class="cmp-row"><span class="cmp-l">Presença</span><div class="cmp-v">${cell(chamberA, pA, firstRecord)}</div><div class="cmp-v">${cell(chamberB, pB, secondRecord)}</div></div>
    <div class="cmp-row"><div class="cmp-v muted cmp-source" style="grid-column:1 / -1">A Câmara publica presença e faltas de cada sessão, por isso aparece em porcentagem; o Senado publica só os registros de presença, por isso aparece em número de sessões. As medidas são diferentes e nenhuma é destacada. No Senado: ${esc(sourceDetail.charAt(0).toLowerCase() + sourceDetail.slice(1))}${activitySource(source, 'Fonte e período')}</div></div>`;
}
function comparableVotePair(record) {
  const choices = ['Sim', 'Não', 'Abstenção', 'Obstrução'];
  return choices.includes(record.voteA) && choices.includes(record.voteB);
}
function comparisonVotes(a, b) {
  const idA = String(a.pessoa.id), idB = String(b.pessoa.id);
  const chamberA = idA.split(':')[0], chamberB = idB.split(':')[0];
  if (chamberA !== chamberB || !['camara', 'senado'].includes(chamberA)) return { chamber: null, votes: [] };
  const chamber = chamberA;
  if (chamber === 'camara' && typeof profileChamberVotesLoading === 'function') {
    // Catálogo do Placar: votações em que ao menos um(a) dos(as) dois(duas) tem registro.
    const loading = profileChamberVotesLoading(idA) | profileChamberVotesLoading(idB);
    const second = new Map(votesForPerson(idB).map(record => [record.vote.id, record.recordedVote]));
    const votes = votesForPerson(idA).map(record => ({ vote: record.vote, voteA: record.recordedVote, voteB: second.get(record.vote.id) ?? null }))
      .filter(record => record.voteA !== null || record.voteB !== null);
    return { chamber, votes, loading: Boolean(loading) };
  }
  if (chamber === 'senado' && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const list = typeof profileVoteList === 'function' ? profileVoteList(chamber) : chamber === 'camara' ? DATA.votacoes || [] : [];
  const key = id => chamber === 'senado' ? id : id.slice(id.indexOf(':') + 1);
  const votes = list.filter(vote => !vote.secreta).map(vote => {
    const rows = voteRowsForItem(vote) || [];
    const firstVote = rows.find(row => String(row[0]) === key(idA));
    const secondVote = rows.find(row => String(row[0]) === key(idB));
    return { vote, voteA: firstVote?.[4] ?? null, voteB: secondVote?.[4] ?? null };
  });
  return { chamber, votes: chamber === 'senado'
    ? votes.filter(comparableVotePair)
    : votes };
}
function comparisonTable([a, b]) {
  const personA = a.pessoa, personB = b.pessoa, maxMonthly = Math.max(a.mediaMensal || 0, b.mediaMensal || 0, 1);
  const profileA = comparisonProfile(a), profileB = comparisonProfile(b);
  // Cotas de Casas diferentes têm tetos diferentes: lado a lado, sem destacar a menor.
  const sameHouse = String(personA.id).split(':')[0] === String(personB.id).split(':')[0];
  const firstName = person => esc(citizenName(person.name).split(' ')[0]);
  // higherIsWorse null: só informa, sem marcar "melhor" (ex.: alertas, que não medem conduta).
  const sideHtml = (valueA, valueB, format, higherIsWorse = true) => {
    const winner = higherIsWorse === null || valueA == null || valueB == null || valueA === valueB || valueA < 0 || valueB < 0 ? '' : (valueA > valueB) === higherIsWorse ? 'b' : 'a';
    return `<div class="cmp-v ${winner === 'a' ? 'best' : ''}">${valueA == null ? 'Sem dados' : format(valueA, 'a')}</div><div class="cmp-v ${winner === 'b' ? 'best' : ''}">${valueB == null ? 'Sem dados' : format(valueB, 'b')}</div>`;
  };
  const vsAverage = profile => profile.mediaMensal != null && profile.media ? Math.round((profile.mediaMensal / profile.media - 1) * 100) : null;
  // Período da média: só os meses com notas assentadas (`mediaPeriodo`); fichas antigas trazem só `periodo`.
  const quotaPeriod = profile => { const period = profile.mediaPeriodo || profile.periodo; return typeof citizenQuotaPeriod === 'function' && period ? citizenQuotaPeriod(period.inicio, period.fim) : ''; };
  if ([a, b].some(f => String(f.pessoa.id).startsWith('senado:')) && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const pA = attendanceForPerson(a.pessoa.id), pB = attendanceForPerson(b.pessoa.id);
  const topCategory = f => {
    const categories = shareQuotaCategories(f.categorias);
    return categories.items[0] ? `${esc(categories.items[0].name)} <small>${Math.round(categories.items[0].share * 100)}% dos saldos positivos</small>` : '—';
  };
  const hasCategoryRefunds = f => Array.isArray(f.categorias) && f.categorias.some(category => Number.isFinite(category?.valor) && category.valor < 0);
  const topSupplier = f => {
    const suppliers = Array.isArray(f.fornecedores) ? f.fornecedores : [];
    const supplier = suppliers.find(item => Number.isFinite(item?.valor) && item.valor > 0);
    if (!supplier) return suppliers.length ? 'Sem valor positivo listado' : '—';
    const noteCount = Number.isSafeInteger(supplier.notas) && supplier.notas >= 0
      ? `${supplier.notas} ${supplier.notas === 1 ? 'nota' : 'notas'}` : 'notas não informadas';
    return `${esc(citizenName(supplier.name || 'Fornecedor não informado'))} <small>${formatCitizenAmount(supplier.valor)} · ${noteCount}</small>`;
  };
  const { chamber: voteChamber, votes, loading: chamberVotesLoading } = comparisonVotes(a, b);
  const comparableVotes = votes.filter(comparableVotePair);
  const matchingVoteCount = comparableVotes.filter(record => record.voteA === record.voteB).length;
  const senateVoteSource = voteChamber === 'senado' && typeof profileSenateSource === 'function' ? profileSenateSource('votacoes') : null;
  const isSenateLoading = voteChamber === 'senado' && senateLoading();
  const senateVotesUnavailable = senateVoteSource?.status === 'unavailable';
  const voteLabel = voteChamber === 'senado' ? 'Como votaram · Senado' : 'Como votaram';
  const voteSummary = voteChamber === 'senado'
    ? (senateVotesUnavailable ? 'Dados de votações nominais do Senado indisponíveis neste recorte.'
      : comparableVotes.length ? `${firstName(personA)} e ${firstName(personB)} registraram o mesmo voto em ${matchingVoteCount} de ${comparableVotes.length} votações nominais comparáveis no Senado.` : 'Sem votos nominais comparáveis para estes(as) senadores(as) neste recorte.')
    : `${firstName(personA)} e ${firstName(personB)} registraram o mesmo voto em ${matchingVoteCount} de ${comparableVotes.length} votações do Placar comparáveis.`;
  const voteRows = votes.slice(0, extrasState.comparisonVoteLimit || COMPARISON_VOTE_PAGE).map(record => {
    const voteAClass = record.voteA === 'Sim' ? 'yes' : record.voteA === 'Não' ? 'no' : '';
    const voteBClass = record.voteB === 'Sim' ? 'yes' : record.voteB === 'Não' ? 'no' : '';
    const voteA = record.voteA === null ? 'Sem registro importado' : String(record.voteA).toLowerCase();
    const voteB = record.voteB === null ? 'Sem registro importado' : String(record.voteB).toLowerCase();
    const content = `<span>${esc(record.vote.titulo || record.vote.proposicao || 'Votação nominal')}</span><span class="vchip ${voteAClass}">${esc(voteA)}</span><span class="vchip ${voteBClass}">${esc(voteB)}</span><em>${!comparableVotePair(record) ? 'sem registro comparável' : record.voteA === record.voteB ? 'igual' : 'diferente'}</em>`;
    return typeof profileVoteButton === 'function' ? profileVoteButton(record.vote, content, 'cmp-vote') : `<button type="button" class="cmp-vote" data-vote="${esc(record.vote.id)}">${content}</button>`;
  }).join('');
  return `<section class="card cmp wide">
    <div class="cmp-head"><span></span>${[a, b].map(profile => `<button type="button" class="cmp-who" data-politician="${esc(profile.pessoa.id)}">${citizenAvatar(profile.pessoa, 56)}<b>${esc(citizenName(profile.pessoa.name))}</b><small>${esc([ROLE_LABELS[profile.pessoa.role], profile.pessoa.party, profile.pessoa.uf].filter(Boolean).join(' · '))}</small></button>`).join('')}</div>
    ${comparisonCostRows(a, b, sideHtml)}
    <div class="cmp-row"><span class="cmp-l">Cota parlamentar por mês</span>${sideHtml(a.mediaMensal, b.mediaMensal, value => `<b class="mono">${formatCitizenAmount(value)}</b>`, sameHouse ? true : null)}</div>
    <div class="cmp-row cmp-bars"><span class="cmp-l"></span><div><i style="width:${a.mediaMensal == null ? 0 : a.mediaMensal / maxMonthly * 100}%"></i></div><div><i style="width:${b.mediaMensal == null ? 0 : b.mediaMensal / maxMonthly * 100}%"></i></div></div>
    <div class="cmp-row"><span class="cmp-l"></span><div class="cmp-v muted cmp-source">${esc(quotaPeriod(a))}</div><div class="cmp-v muted cmp-source">${esc(quotaPeriod(b))}</div></div>
    <div class="cmp-row"><span class="cmp-l">Comparado à média do cargo</span>${sideHtml(vsAverage(a), vsAverage(b), value => `<b>${value > 0 ? '+' : ''}${value}%</b>`)}</div>
    <div class="cmp-row"><span class="cmp-l">Alertas na cota (mandato)</span>${sideHtml(alertCountOrNull(a), alertCountOrNull(b), value => `<b>${value}</b>`, null)}</div>
    ${comparisonAttendanceRows(a, b, pA, pB)}
    ${comparisonInfoRow('Participação e exercício', comparisonParticipation(profileA), comparisonParticipation(profileB))}
    ${comparisonInfoRow('Contato institucional', esc(comparisonContact(profileA)), esc(comparisonContact(profileB)))}
    ${comparisonInfoRow('Projetos apresentados · PL, PLP e PEC desde fev/2023', comparisonProjects(profileA), comparisonProjects(profileB))}
    ${comparisonInfoRow('Equipe e verba de gabinete', comparisonOfficeCell(a), comparisonOfficeCell(b))}
    ${comparisonInfoRow('Remuneração', comparisonCompensationCell(a), comparisonCompensationCell(b))}
    <div class="cmp-row"><span class="cmp-l">Onde mais gastou</span><div class="cmp-v">${topCategory(a)}</div><div class="cmp-v">${topCategory(b)}</div></div>
    ${[a, b].some(hasCategoryRefunds) ? '<div class="cmp-row"><span class="cmp-l"></span><div class="cmp-v muted cmp-source" style="grid-column:2 / -1">Percentuais consideram categorias com saldo positivo; estornos permanecem no total líquido.</div></div>' : ''}
    <div class="cmp-row"><span class="cmp-l">Empresa que mais recebeu</span><div class="cmp-v">${topSupplier(a)}</div><div class="cmp-v">${topSupplier(b)}</div></div>
  </section>
  ${voteChamber === 'senado' || comparableVotes.length || chamberVotesLoading ? `<section class="card wide"><span class="k">${voteLabel}</span>
    ${isSenateLoading || chamberVotesLoading ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : `<h2 class="h" style="font-size:21px">${voteSummary}</h2>
    ${voteRows || (voteChamber === 'senado' ? `<p class="muted">${senateVotesUnavailable ? 'Dados de votações nominais indisponíveis neste recorte.' : 'Sem votações nominais do Senado com registro para ambos neste recorte.'}</p>` : '')}
    ${votes.length > (extrasState.comparisonVoteLimit || COMPARISON_VOTE_PAGE) ? `<button type="button" class="opt citizen-more" data-cmp-votes-more>Mostrar mais (${votes.length - (extrasState.comparisonVoteLimit || COMPARISON_VOTE_PAGE)})</button>` : ''}`}
    ${voteChamber === 'senado' ? `${senateVoteSource?.detail ? `<p class="muted">${esc(datesInTextBR(senateVoteSource.detail))}</p>` : ''}${activitySource(senateVoteSource, 'Fonte e período')}` : '<span class="muted">Votações do Placar: texto principal de PL, PLP e PEC no Plenário desde fev/2023. A comparação considera apenas votos registrados por ambos; ausência de registro não significa que a pessoa não votou.</span>'}
  </section>` : String(personA.id).split(':')[0] !== String(personB.id).split(':')[0] ? '<section class="card wide"><span class="k">Votações</span><p class="muted">Votações de casas diferentes não são comparadas.</p></section>' : ''}
  <span class="src">Destaque em roxo: quem gastou menos, teve menos alertas ou teve maior presença na Câmara. O Senado aparece como contagem de presenças registradas, sem ranking; votações entre casas não são comparadas. Gastos pelas notas da cota publicadas pela Câmara e pelo Senado (na Câmara, sem as passagens aéreas que ficam fora do arquivo aberto das notas).</span>`;
}

/* ---------- Eventos ---------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-attendance-order],[data-attendance-more],[data-vote-group],[data-vote-more],[data-senate-votes-more],[data-cmp-votes-more],[data-cmp-add],[data-cmp-del],[data-cmp-start],[data-cmp-retry]');
  if (!t) return;
  if (t.dataset.attendanceOrder) { extrasState.attendanceOrder = t.dataset.attendanceOrder; extrasState.attendanceLimit = 40; return rerender(); }
  if (t.hasAttribute('data-attendance-more')) { extrasState.attendanceLimit += 60; return rerender(); }
  if (t.dataset.voteGroup) { extrasState.votes[t.dataset.voteId] = t.dataset.voteGroup; extrasState.voteLimit = 40; extrasState.voteQuery = ''; return rerender(); }
  if (t.hasAttribute('data-vote-more')) { extrasState.voteLimit += 80; return rerender(); }
  if (t.hasAttribute('data-senate-votes-more')) { extrasState.senateVoteLimit += 20; return rerender(); }
  if (t.hasAttribute('data-cmp-votes-more')) { extrasState.comparisonVoteLimit += COMPARISON_VOTE_PAGE; return rerender(); }
  if (t.dataset.cmpAdd) { e.stopPropagation(); addComparisonPerson(t.dataset.cmpAdd); if (state.view !== 'compare') return navigateToView('compare'); rerender(); return syncComparisonLocation(); }
  if (t.hasAttribute('data-cmp-retry')) { extrasState.comparisonError = null; extrasState.comparisonResults = null; extrasState.comparisonLoading = false; return searchComparisonPeople(extrasState.comparisonQuery); }
  if (t.dataset.cmpDel) { extrasState.comparisonIds = extrasState.comparisonIds.filter(x => x !== t.dataset.cmpDel); extrasState.comparisonQuery = ''; extrasState.comparisonKey = null; extrasState.comparisonResults = null; extrasState.comparisonError = null; rerender(); return syncComparisonLocation(); }
  if (t.hasAttribute('data-cmp-start')) { if (t.dataset.cmpStart) { extrasState.comparisonIds = []; addComparisonPerson(t.dataset.cmpStart); } navigateToView('compare'); }
}, true);
let extrasTimer = null;
document.addEventListener('input', e => {
  const id = e.target.id;
  if (id === 'attendance-q') { extrasState.attendanceQuery = e.target.value; extrasState.attendanceLimit = 40; const listElement = document.getElementById('attendance-list'); if (listElement) listElement.innerHTML = attendanceList(attendanceSorted()); }
  if (id === 'vote-search-q') { extrasState.voteQuery = e.target.value; const pos = e.target.selectionStart; rerender(); const i = document.getElementById('vote-search-q'); if (i) { i.focus(); i.setSelectionRange(pos, pos); } }
  if (id === 'comparison-q') { clearTimeout(extrasTimer); const v = e.target.value; extrasState.comparisonQuery = v; extrasState.comparisonKey = null; extrasState.comparisonResults = null; extrasState.comparisonError = null; extrasState.comparisonLoading = false; extrasTimer = setTimeout(() => searchComparisonPeople(v), 250); }
});

/* ---------- Encaixe bento no computador ----------
   Os cards ficam em fileiras de 12 colunas. Se uma fileira não fecha (card sozinho ou dois de três),
   os cards dela se alargam para ocupar o espaço: nada de buraco na grade. */
function bentoFix() {
  const desk = matchMedia('(min-width: 900px)').matches;
  document.querySelectorAll('#app .view').forEach(box => {
    const kids = [...box.children];
    kids.forEach(k => { if (k.dataset.bento) { k.style.gridColumn = ''; delete k.dataset.bento; } });
    if (!desk) return;
    let run = [];
    const flush = () => {
      const rows = []; let row = [], used = 0;
      run.forEach(x => { if (used + x.span > 12) { rows.push(row); row = []; used = 0; } row.push(x); used += x.span; });
      if (row.length) rows.push(row);
      rows.forEach(r => {
        if (r.reduce((s, x) => s + x.span, 0) >= 12) return;
        const each = Math.floor(12 / r.length);
        r.forEach((x, i) => { x.el.style.gridColumn = `span ${i === r.length - 1 ? 12 - each * (r.length - 1) : each}`; x.el.dataset.bento = '1'; });
      });
      run = [];
    };
    kids.forEach(k => {
      const cs = getComputedStyle(k);
      if (cs.display === 'none' || cs.position === 'absolute') return;
      const m = /^span (\d+)$/.exec(cs.gridColumnStart);
      if (m && cs.gridColumnEnd === 'auto' && +m[1] < 12) run.push({ el: k, span: +m[1] }); else flush();
    });
    flush();
  });
}
let bentoQueued = false;
const bentoSoon = () => { if (bentoQueued) return; bentoQueued = true; requestAnimationFrame(() => { bentoQueued = false; bentoFix(); }); };
new MutationObserver(bentoSoon).observe(document.getElementById('app'), { childList: true, subtree: true });
addEventListener('resize', bentoSoon);
