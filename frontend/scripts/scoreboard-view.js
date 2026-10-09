/* Catálogo amplo de votações: carregado só ao entrar no Placar. */
const scoreboardState = {
  list: { status: 'idle', data: null, error: null, available: null, query: '', type: '', theme: '', page: 1, pageSize: 12 },
  listSequence: 0,
  detail: { id: null, status: 'idle', data: null, error: null, visibleParticipants: 20 },
  detailSequence: 0,
  detailCache: new Map(),
};
const SCOREBOARD_DETAIL_CACHE_LIMIT = 20;
const SCOREBOARD_VOTE_ID = /^\d+-\d+$/;
const SCOREBOARD_VOTE_LABELS = ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'];
const scoreboardParticipantGroup = person => SCOREBOARD_VOTE_LABELS.includes(person?.vote) ? person.vote : person?.vote ? 'Outro registro' : 'Escolha não informada';

const scoreboardEscape = value => String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));
const scoreboardText = value => typeof value === 'string' ? value.trim() : '';
const scoreboardCount = value => Number.isFinite(value) ? Number(value).toLocaleString('pt-BR') : '—';
function scoreboardDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'data não informada';
  return typeof formatShortDate === 'function' ? formatShortDate(value) : value.slice(0, 10).split('-').reverse().join('/');
}
function scoreboardPeriodDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'data não informada';
  return `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)}`;
}
function scoreboardSafeSource(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    if (host !== 'camara.leg.br' && !host.endsWith('.camara.leg.br')) return null;
    return url.href;
  } catch (error) { return null; }
}
function scoreboardSourceLink(url, label) {
  const safeUrl = scoreboardSafeSource(url);
  return safeUrl ? `<a href="${scoreboardEscape(safeUrl)}" target="_blank" rel="noopener">${scoreboardEscape(label)} ↗</a>` : '';
}
function scoreboardOutcome(outcome) {
  return ({ approved: 'Aprovado nesta votação', rejected: 'Rejeitado nesta votação', not_approved: 'Não aprovado nesta votação' })[outcome] || 'Resultado não informado';
}
function scoreboardVoteType(item) {
  const type = scoreboardText(item?.type);
  if (['PL', 'PLP', 'PEC'].includes(type)) return type;
  const proposal = scoreboardText(item?.proposition);
  return (proposal.match(/^(PLP|PEC|PL)\b/i) || [])[1]?.toUpperCase() || '';
}
function scoreboardListUrl() {
  const list = scoreboardState.list;
  const query = new URLSearchParams();
  if (list.query) query.set('q', list.query);
  if (list.type) query.set('type', list.type);
  if (list.theme) query.set('theme', list.theme);
  query.set('page', String(list.page));
  query.set('pageSize', String(list.pageSize));
  return `/api/c/votes?${query.toString()}`;
}
async function scoreboardGetJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Não foi possível carregar as votações.');
    error.status = response.status;
    throw error;
  }
  return data;
}
function scoreboardRefresh() {
  if (typeof rerender === 'function') rerender();
}
function scoreboardLegacyVotes() {
  return Array.isArray(DATA?.votacoes) ? DATA.votacoes : [];
}
function scoreboardLegacyVisibleVotes() {
  const list = scoreboardState.list;
  const query = list.query.toLocaleLowerCase('pt-BR');
  return scoreboardLegacyVotes().filter(vote => {
    const type = scoreboardVoteType({ proposition: vote.proposicao });
    const haystack = [vote.proposicao, vote.titulo, vote.curto].filter(Boolean).join(' ').toLocaleLowerCase('pt-BR');
    return (!query || haystack.includes(query)) && (!list.type || list.type === type) && !list.theme;
  });
}
function scoreboardCoverage(data) {
  const period = data?.period || {};
  const coverage = data?.coverage || {};
  const range = period.start || period.end ? `<p>Período consultado: ${scoreboardPeriodDate(period.start)} a ${scoreboardPeriodDate(period.end)}.</p>` : '';
  const year = /^\d{4}-/.test(period.start || '') && period.start?.slice(0, 4) === period.end?.slice(0, 4) ? period.start.slice(0, 4) : '';
  const timeframe = year ? `em ${year}` : 'no período consultado';
  const reviewed = scoreboardCount(coverage.reviewedCount);
  const published = scoreboardCount(coverage.publishedCount);
  const pending = scoreboardCount(coverage.pendingCount);
  const candidates = scoreboardCount(coverage.candidateCount);
  const excluded = Number.isInteger(coverage.excludedCount) && coverage.excludedCount >= 0
    ? `${scoreboardCount(coverage.excludedCount)} foram excluídos, cada um com o motivo e a fonte, e ` : '';
  const inventory = scoreboardCount(coverage.inventoryCount);
  const review = Number.isInteger(coverage.reviewedCount) && coverage.reviewedCount === coverage.candidateCount ? 'Revisamos todos' : `Revisamos ${reviewed}`;
  const pendingNote = coverage.pendingCount === 0 ? 'Nenhum ficou pendente.' : `${pending} ainda estão pendentes.`;
  const gapFields = ['missingTextCount', 'missingAbstentionCount', 'missingThemeCount'];
  const hasGapCounts = gapFields.every(field => Number.isInteger(coverage[field]) && coverage[field] >= 0);
  const gaps = [
    [coverage.missingTextCount, 'votação não tem link seguro para o texto exato votado.', 'votações não têm link seguro para o texto exato votado.'],
    [coverage.missingAbstentionCount, 'votação não tem a contagem de abstenções nas fontes que usamos.', 'votações não têm a contagem de abstenções nas fontes que usamos.'],
    [coverage.missingThemeCount, 'votação não tem tema oficial.', 'votações não têm tema oficial.'],
  ].filter(([count]) => Number.isInteger(count) && count >= 0)
    .map(([count, singular, plural]) => `<li>${scoreboardCount(count)} ${count === 1 ? singular : plural}</li>`).join('');
  const detail = scoreboardText(coverage.detail);
  return `<div class="scoreboard-coverage"><h2 class="h">O que é o Placar</h2>
    <p>Aqui estão votações da Câmara ${timeframe} em que os deputados votaram o texto principal de um projeto de lei ou de uma mudança na Constituição, com o voto de cada um registrado.</p>
    <p>Escolhemos <strong>${published} votações</strong>, conferidas uma a uma. Elas não são tudo o que a Câmara votou ${year ? 'no ano' : 'no período'}. Um projeto aprovado aqui ainda pode não ter virado lei.</p>
    ${range}
    <details><summary>Como montamos este Placar</summary>
      <p><strong>De onde vêm as votações.</strong> A Câmara publicou ${inventory} registros de votação ${timeframe}. Muitos são etapas do mesmo projeto: urgência, emendas, destaques, procedimentos e redação final. Ficamos só com as votações do texto principal de PL, PLP e PEC no Plenário. Votações simbólicas (sem registro de voto de cada deputado) e outros tipos de proposta ficam de fora.</p>
      <p><strong>Como escolhemos.</strong> Dos ${inventory} registros, ${candidates} pareciam votações do texto principal. ${review}: ${excluded}${published} entraram no Placar. ${pendingNote}</p>
      <p><strong>Limites.</strong></p>
      <ul>${gaps}
        <li>O Placar ainda não cobre todo o mandato${year ? `, só ${year}` : ''}.</li>
        <li>O tema é o que a Câmara atribui ao projeto.</li>
        <li>Dado ausente não significa zero.</li>
        <li>O resultado mostrado é o daquela votação, não a situação atual do projeto.</li>
      </ul>
      ${!hasGapCounts && detail ? `<p>${scoreboardEscape(detail)}</p>` : ''}
    </details></div>`;
}
function scoreboardLegacyCard(vote) {
  const id = scoreboardText(vote.id);
  const type = scoreboardVoteType({ proposition: vote.proposicao });
  const tally = [vote.sim, vote.nao].map(scoreboardCount).join(' × ');
  const outcome = vote.aprovada === true ? 'Aprovado' : vote.aprovada === false ? 'Rejeitado' : 'Resultado não informado';
  return `<article class="card scoreboard-card">
    <span class="k">${scoreboardEscape(vote.proposicao || 'Proposição não informada')} · ${scoreboardEscape(scoreboardDate(vote.data))}</span>
    <h2 class="h">${scoreboardEscape(vote.titulo || 'Título não informado')}</h2>
    <p class="scoreboard-meta">${type ? `<span class="pill">${scoreboardEscape(type)}</span>` : ''}<span>${scoreboardEscape(tally)} · ${scoreboardEscape(outcome)}</span></p>
    ${vote.curto ? `<p class="muted">${scoreboardEscape(vote.curto)}</p>` : ''}
    ${SCOREBOARD_VOTE_ID.test(id) ? `<button type="button" class="more" data-vote="${scoreboardEscape(id)}">Entender essa votação</button>` : ''}
  </article>`;
}
function scoreboardItemCard(item) {
  const id = scoreboardText(item?.id);
  const themes = Array.isArray(item?.themes) ? item.themes.map(theme => scoreboardText(theme?.label)).filter(Boolean) : [];
  const tally = item?.tally || {};
  return `<article class="card scoreboard-card">
    <span class="k">${scoreboardEscape(item?.proposition || 'Proposição não informada')} · ${scoreboardEscape(scoreboardDate(item?.date))}</span>
    <h2 class="h">${scoreboardEscape(item?.title || 'Título não informado')}</h2>
    <p class="scoreboard-meta">${scoreboardVoteType(item) ? `<span class="pill">${scoreboardEscape(scoreboardVoteType(item))}</span>` : ''}<span>Sim ${scoreboardCount(tally.yes)} · Não ${scoreboardCount(tally.no)} · ${scoreboardEscape(scoreboardOutcome(item?.outcome))}</span></p>
    ${item?.summary ? `<p class="muted">${scoreboardEscape(item.summary)}</p>` : ''}
    ${themes.length ? `<p class="scoreboard-themes">${themes.map(theme => `<span class="pill">${scoreboardEscape(theme)}</span>`).join(' ')}</p>` : ''}
    ${SCOREBOARD_VOTE_ID.test(id) ? `<button type="button" class="more" data-vote="${scoreboardEscape(id)}">Ver decisão e votos →</button>` : '<p class="muted">Identificador desta votação indisponível.</p>'}
  </article>`;
}
function scoreboardFilterForm(data, fallback) {
  const filters = data?.filters || {};
  const types = Array.isArray(filters.types) ? filters.types : ['PL', 'PLP', 'PEC'];
  const themes = Array.isArray(filters.themes) ? filters.themes : [];
  const list = scoreboardState.list;
  return `<form class="card scoreboard-filters" data-scoreboard-filter-form aria-label="Filtros do Placar">
    <label>Buscar votação<input class="search" name="q" type="search" value="${scoreboardEscape(list.query)}" maxlength="120" placeholder="Proposição, título ou resumo"></label>
    <label>Tipo<select name="type"><option value="">Todos</option>${types.map(type => `<option value="${scoreboardEscape(type)}"${list.type === type ? ' selected' : ''}>${scoreboardEscape(type)}</option>`).join('')}</select></label>
    ${fallback ? `<p class="muted">Temas oficiais ficam disponíveis quando o catálogo ampliado está ativo.</p>` : `<label>Tema oficial<select name="theme"><option value="">Todos os temas</option>${themes.map(theme => `<option value="${scoreboardEscape(theme.id)}"${list.theme === theme.id ? ' selected' : ''}>${scoreboardEscape(theme.label)}</option>`).join('')}</select></label>`}
    <button class="fchip" type="submit">Aplicar filtros</button>
  </form>`;
}
function scoreboardPagination(data, fallbackCount) {
  const page = Number.isInteger(data?.page) ? data.page : scoreboardState.list.page;
  const pageCount = Number.isInteger(data?.pageCount) ? data.pageCount : Math.max(1, Math.ceil(fallbackCount / scoreboardState.list.pageSize));
  const total = Number.isFinite(data?.total) ? data.total : fallbackCount;
  if (pageCount <= 1) return `<p class="muted scoreboard-result-count">${scoreboardCount(total)} votações neste resultado.</p>`;
  return `<nav class="scoreboard-pagination" aria-label="Paginação das votações">
    <button type="button" class="fchip" data-scoreboard-page="${Math.max(1, page - 1)}"${page <= 1 ? ' disabled' : ''} aria-label="Página anterior">‹ Anterior</button>
    <span aria-live="polite">Página ${page} de ${pageCount} · ${scoreboardCount(total)} votações</span>
    <button type="button" class="fchip" data-scoreboard-page="${Math.min(pageCount, page + 1)}"${page >= pageCount ? ' disabled' : ''} aria-label="Próxima página">Próxima ›</button>
  </nav>`;
}
function scoreboardVotesView() {
  const list = scoreboardState.list;
  const fallback = list.available === false || (list.status === 'error' && (!list.data || list.data.available === false));
  const data = list.data && list.data.available !== false ? list.data : null;
  const legacyVotes = fallback ? scoreboardLegacyVisibleVotes() : [];
  const legacyStart = (list.page - 1) * list.pageSize;
  const visibleLegacy = legacyVotes.slice(legacyStart, legacyStart + list.pageSize);
  const items = Array.isArray(data?.items) ? data.items : [];
  const unavailableNote = fallback ? '<p class="scoreboard-fallback" role="status">O catálogo ampliado está indisponível. Esta tela mostra apenas as votações selecionadas que já existem neste painel.</p>' : '';
  const loading = list.status === 'loading' ? '<p class="scoreboard-status" role="status" aria-live="polite">Carregando votações…</p>' : '';
  const error = list.status === 'error' ? `<div class="scoreboard-error" role="alert"><p>${scoreboardEscape(list.error || 'Não foi possível carregar o catálogo ampliado.')}</p><button type="button" class="fchip" data-scoreboard-retry>Tentar novamente</button></div>` : '';
  const result = fallback ? visibleLegacy.map(scoreboardLegacyCard).join('') : items.map(scoreboardItemCard).join('');
  const empty = list.status === 'ready' && !fallback && items.length === 0 || fallback && legacyVotes.length === 0
    ? '<p class="card scoreboard-empty">Nenhuma votação encontrada com esses filtros.</p>' : '';
  const paginationData = fallback ? null : data;
  return `${pageHead('Câmara · Plenário', 'Placar', fallback ? 'Consulte as votações selecionadas e suas fontes oficiais.' : 'Veja o que foi decidido sobre o texto principal dos projetos e como cada deputado votou.')}
    ${data ? scoreboardCoverage(data) : ''}
    ${unavailableNote}
    ${scoreboardFilterForm(data, fallback)}
    ${loading}${error}
    <div class="scoreboard-results" aria-live="polite">${result || empty}</div>
    ${result ? scoreboardPagination(paginationData, fallback ? legacyVotes.length : Number(data?.total) || 0) : ''}
    <span class="src">Fonte: Câmara dos Deputados · dados abertos do Plenário.</span>`;
}
function scoreboardDetailSources(sources, dataNotes) {
  const source = sources || {};
  const links = [
    scoreboardSourceLink(source.vote, 'Registro da votação'),
    scoreboardSourceLink(source.rollCall, 'Relatório nominal'),
    scoreboardSourceLink(source.text, 'Texto votado'),
    scoreboardSourceLink(source.decision, 'Decisão na Câmara'),
    scoreboardSourceLink(source.proposition, 'Ficha da proposição'),
  ].filter(Boolean);
  const notes = Array.isArray(dataNotes) ? dataNotes.filter(note => typeof note === 'string').map(note => `<p class="muted">${scoreboardEscape(note)}</p>`).join('') : '';
  const missingText = source.text === null ? '<p class="muted">O link seguro para o texto exato votado ainda não está disponível. O relatório e o registro da decisão permanecem nas fontes.</p>' : '';
  return `<section class="card"><span class="k">Fontes oficiais</span>${links.length ? `<div class="scoreboard-source-links">${links.join('')}</div>` : '<p class="muted">Links oficiais não informados para esta votação.</p>'}${missingText}${notes}</section>`;
}
function scoreboardParticipants(participants) {
  const search = typeof document !== 'undefined' ? document.querySelector('[data-scoreboard-participant-search]')?.value || '' : '';
  const query = search.trim().toLocaleLowerCase('pt-BR');
  const rows = Array.isArray(participants) ? participants : [];
  const matches = rows.filter(person => `${person?.name || ''} ${person?.party || ''} ${person?.uf || ''} ${person?.vote || ''}`.toLocaleLowerCase('pt-BR').includes(query));
  const visible = matches.slice(0, scoreboardState.detail.visibleParticipants);
  const sections = SCOREBOARD_VOTE_LABELS.concat(['Outro registro', 'Escolha não informada']).map(label => {
    const group = visible.filter(person => scoreboardParticipantGroup(person) === label);
    if (!group.length) return '';
    return `<section class="scoreboard-voter-group"><h3>${scoreboardEscape(label)} <span>${scoreboardCount(matches.filter(person => scoreboardParticipantGroup(person) === label).length)}</span></h3><ul>${group.map(person => {
      const name = scoreboardText(person?.name) || 'Nome não informado';
      const id = scoreboardText(person?.id);
      const politician = id.match(/^camara:(\d+)$/);
      const href = politician ? `/deputado/${politician[1]}` : '';
      const meta = [SCOREBOARD_VOTE_LABELS.includes(person?.vote) ? '' : scoreboardText(person?.vote), scoreboardText(person?.party), scoreboardText(person?.uf)].filter(Boolean).join(' · ');
      return `<li>${href ? `<a href="${href}">${scoreboardEscape(name)}</a>` : `<span>${scoreboardEscape(name)}</span>`}${meta ? `<small>${scoreboardEscape(meta)}</small>` : ''}</li>`;
    }).join('')}</ul></section>`;
  }).join('');
  const more = matches.length > visible.length ? `<button type="button" class="fchip" data-scoreboard-more>Mostrar mais ${Math.min(20, matches.length - visible.length)} (${scoreboardCount(matches.length - visible.length)} restantes)</button>` : '';
  const empty = matches.length === 0 ? '<p class="muted">Nenhum registro individual corresponde à busca.</p>' : '';
  return `<section class="card scoreboard-voters"><span class="k">Votos individuais</span>
    <label>Buscar parlamentar<input class="search" type="search" data-scoreboard-participant-search value="${scoreboardEscape(search)}" maxlength="100" placeholder="Nome, partido, UF ou voto" aria-label="Buscar nos votos individuais"></label>
    ${rows.length ? `<p class="muted">${scoreboardCount(matches.length)} registros${query ? ' encontrados' : ' nesta votação'}.</p>` : '<p class="muted">Nenhum registro individual foi fornecido para esta consulta.</p>'}
    ${sections}${empty}${more}</section>`;
}
function scoreboardPartyTotals(partyTotals) {
  const rows = Array.isArray(partyTotals) ? partyTotals : [];
  if (!rows.length) return '';
  return `<section class="card"><span class="k">Resumo por partido</span><div class="scoreboard-party-totals">${rows.map(row => `<div><b>${scoreboardEscape(row?.party || 'Partido não informado')}</b><span>Sim ${scoreboardCount(row?.yes)} · Não ${scoreboardCount(row?.no)} · Outros ${scoreboardCount(row?.other)}</span></div>`).join('')}</div></section>`;
}
function scoreboardDetailView() {
  const detail = scoreboardState.detail;
  if (detail.id !== String(state.voteId || '')) return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><p class="scoreboard-status" role="status" aria-live="polite">Carregando detalhes e votos individuais…</p>`;
  if (detail.status === 'legacy') return typeof selectedVoteView === 'function' ? selectedVoteView() : '<p class="note">Esta votação está disponível no recorte selecionado.</p>';
  if (detail.status === 'loading' || detail.status === 'idle') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><p class="scoreboard-status" role="status" aria-live="polite">Carregando detalhes e votos individuais…</p>`;
  if (detail.status === 'missing') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><section class="card scoreboard-error" role="alert"><h1 class="h">Votação não encontrada</h1><p>O identificador não está disponível no catálogo público.</p></section>`;
  if (detail.status === 'error') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><section class="card scoreboard-error" role="alert"><p>${scoreboardEscape(detail.error || 'Não foi possível carregar esta votação.')}</p><button type="button" class="fchip" data-scoreboard-retry>Carregar novamente</button></section>`;
  const payload = detail.data || {};
  const vote = payload.vote || {};
  const tally = vote.tally || {};
  const themes = Array.isArray(vote.themes) ? vote.themes.map(theme => scoreboardText(theme?.label)).filter(Boolean) : [];
  const outcome = scoreboardOutcome(vote.outcome);
  const hasParticipants = payload.participantsAvailable !== false;
  return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button>
    <span class="k">${scoreboardEscape(vote.proposition || 'Proposição não informada')} · votado em ${scoreboardEscape(scoreboardDate(vote.date))}</span>
    <h1 class="h scoreboard-detail-title">${scoreboardEscape(vote.title || 'Título não informado')}</h1>
    ${themes.length ? `<p class="scoreboard-themes">${themes.map(theme => `<span class="pill">${scoreboardEscape(theme)}</span>`).join(' ')}</p>` : ''}
    <section class="card"><span class="k">O que foi decidido</span><h2 class="h">${scoreboardEscape(vote.decisionLabel || 'Decisão não informada')}</h2>${vote.summary ? `<p>${scoreboardEscape(vote.summary)}</p>` : '<p class="muted">Resumo não informado para esta versão.</p>'}<p class="scoreboard-outcome">${scoreboardEscape(outcome)}</p></section>
    <section class="card scoreboard-meaning"><div><span class="k">Sim significava</span><p>${scoreboardEscape(vote.yesMeaning || 'Informação não disponível neste registro.')}</p></div><div><span class="k">Não significava</span><p>${scoreboardEscape(vote.noMeaning || 'Informação não disponível neste registro.')}</p></div></section>
    <section class="card"><span class="k">Resultado desta votação</span><dl class="scoreboard-tally"><div><dt>Sim</dt><dd>${scoreboardCount(tally.yes)}</dd></div><div><dt>Não</dt><dd>${scoreboardCount(tally.no)}</dd></div><div><dt>Abstenção</dt><dd>${scoreboardCount(tally.abstention)}</dd></div><div><dt>Total</dt><dd>${scoreboardCount(tally.total)}</dd></div></dl><p class="muted">${scoreboardEscape(outcome)}. O resultado se refere a esta decisão registrada.</p></section>
    ${scoreboardDetailSources(vote.sources, vote.dataNotes)}
    ${hasParticipants ? scoreboardParticipants(payload.participants) : '<section class="card scoreboard-voters"><span class="k">Votos individuais</span><p class="muted">A lista individual não está disponível para esta votação.</p></section>'}
    ${scoreboardPartyTotals(payload.partyTotals)}
    <span class="src">Fonte: Câmara dos Deputados · revisão em ${scoreboardEscape(scoreboardPeriodDate(vote.reviewedAt))}. O resultado descreve esta votação, sem indicar a situação atual da proposta.</span>`;
}
function scoreboardLoadList() {
  const list = scoreboardState.list;
  const sequence = ++scoreboardState.listSequence;
  list.status = 'loading';
  list.error = null;
  const url = scoreboardListUrl();
  scoreboardRefresh();
  return scoreboardGetJson(url).then(data => {
    if (sequence !== scoreboardState.listSequence) return;
    if (!data || data.available === false) {
      list.available = false;
      list.data = data || null;
      list.status = 'ready';
    } else {
      list.available = true;
      list.data = data;
      list.status = 'ready';
    }
    scoreboardRefresh();
  }).catch(error => {
    if (sequence !== scoreboardState.listSequence) return;
    if (error.status === 404) {
      list.available = false;
      list.data = { available: false };
      list.status = 'ready';
      list.error = null;
    } else {
      list.status = 'error';
      list.error = error.message || 'Não foi possível carregar o catálogo ampliado.';
    }
    scoreboardRefresh();
  });
}
function scoreboardCacheDetail(id, payload) {
  const cache = scoreboardState.detailCache;
  if (cache.has(id)) cache.delete(id);
  cache.set(id, payload);
  while (cache.size > SCOREBOARD_DETAIL_CACHE_LIMIT) cache.delete(cache.keys().next().value);
}
function scoreboardLoadDetail(id) {
  if (!SCOREBOARD_VOTE_ID.test(String(id || ''))) {
    scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    return Promise.resolve();
  }
  const cached = scoreboardState.detailCache.get(id);
  const sequence = ++scoreboardState.detailSequence;
  if (cached) {
    scoreboardState.detail = { id, status: 'ready', data: cached, error: null, visibleParticipants: 20 };
    scoreboardRefresh();
    return Promise.resolve();
  }
  scoreboardState.detail = { id, status: 'loading', data: null, error: null, visibleParticipants: 20 };
  scoreboardRefresh();
  return scoreboardGetJson(`/api/c/votes/${encodeURIComponent(id)}`).then(data => {
    if (sequence !== scoreboardState.detailSequence || state.view !== 'vote' || String(state.voteId) !== id) return;
    if (!data || data.available === false) {
      if (VOTES_BY_ID[id]) scoreboardState.detail = { id, status: 'legacy', data: null, error: null, visibleParticipants: 20 };
      else scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    } else {
      scoreboardCacheDetail(id, data);
      scoreboardState.detail = { id, status: 'ready', data, error: null, visibleParticipants: 20 };
    }
    scoreboardRefresh();
  }).catch(error => {
    if (sequence !== scoreboardState.detailSequence || state.view !== 'vote' || String(state.voteId) !== id) return;
    if (VOTES_BY_ID[id]) scoreboardState.detail = { id, status: 'legacy', data: null, error: null, visibleParticipants: 20 };
    else if (error.status === 404) scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    else scoreboardState.detail = { id, status: 'error', data: null, error: error.message || 'Não foi possível carregar esta votação.', visibleParticipants: 20 };
    scoreboardRefresh();
  });
}
function scoreboardViewEntered(view) {
  if (view !== 'vote' && scoreboardState.detail.status === 'loading') {
    scoreboardState.detailSequence++;
    scoreboardState.detail.status = 'idle';
  }
  if (view === 'votes' && scoreboardState.list.status === 'idle') scoreboardLoadList();
  if (view === 'vote' && scoreboardState.detail.id !== String(state.voteId)) scoreboardLoadDetail(String(state.voteId || ''));
  if (view === 'vote' && scoreboardState.detail.id === String(state.voteId) && scoreboardState.detail.status === 'idle') scoreboardLoadDetail(String(state.voteId || ''));
}
function scoreboardApplyFilters(values) {
  const list = scoreboardState.list;
  list.query = scoreboardText(values?.query).slice(0, 120);
  list.type = ['PL', 'PLP', 'PEC'].includes(values?.type) ? values.type : '';
  list.theme = scoreboardText(values?.theme).slice(0, 80);
  list.page = 1;
  return scoreboardLoadList();
}
function scoreboardHandlePage(page) {
  const data = scoreboardState.list.data;
  const pageCount = Number.isInteger(data?.pageCount) ? data.pageCount : Math.max(1, Math.ceil(scoreboardLegacyVisibleVotes().length / scoreboardState.list.pageSize));
  const target = Number(page);
  if (!Number.isInteger(target) || target < 1 || target > pageCount || target === scoreboardState.list.page) return;
  scoreboardState.list.page = target;
  return scoreboardLoadList();
}
function scoreboardHandleClick(event, target) {
  if (target?.hasAttribute('data-scoreboard-page')) { scoreboardHandlePage(target.dataset.scoreboardPage); return true; }
  if (target?.hasAttribute('data-scoreboard-retry')) {
    if (state.view === 'vote') scoreboardLoadDetail(String(state.voteId || ''));
    else scoreboardLoadList();
    return true;
  }
  if (target?.hasAttribute('data-scoreboard-more')) {
    scoreboardState.detail.visibleParticipants += 20;
    scoreboardRefresh();
    return true;
  }
  return false;
}
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('submit', event => {
    const form = event.target?.closest?.('[data-scoreboard-filter-form]');
    if (!form) return;
    event.preventDefault();
    const formData = new FormData(form);
    scoreboardApplyFilters({ query: formData.get('q'), type: formData.get('type'), theme: formData.get('theme') });
  });
  document.addEventListener('input', event => {
    if (!event.target?.matches?.('[data-scoreboard-participant-search]')) return;
    scoreboardState.detail.visibleParticipants = 20;
    const caret = event.target.selectionStart;
    scoreboardRefresh();
    const replacement = document.querySelector('[data-scoreboard-participant-search]');
    if (replacement?.focus) {
      replacement.focus();
      if (caret != null && replacement.setSelectionRange) replacement.setSelectionRange(caret, caret);
    }
  });
}
