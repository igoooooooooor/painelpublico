const DATA = /*DATA*/null;
const VOTES_BY_ID = Object.fromEntries(DATA.votacoes.map(v => [v.id, v]));
const $app = document.getElementById('app');
const SHORT_MONTHS = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const brl = (v, d = 0) => 'R$ ' + v.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const mi = v => (v / 1e6).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const mil = v => (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
const pct = (a, b) => b > 0 ? Math.round(a / b * 100) : 0;
const formatShortDate = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}/.test(s) ? `${+s.slice(8, 10)}/${SHORT_MONTHS[+s.slice(5, 7)]}` : 'data não informada';
const first = n => n.split(' ')[0];
const CATS = ['--cat1', '--cat2', '--cat3', '--cat4', '--cat5', '--cat6'];
const CATS_H = ['--cat1', '--hero-fg', '--cat3', '--cat4', '--cat5', '--cat6']; // em fundo escuro, o tom escuro some
let state = { view: 'home', deputyId: null, voteId: null, politicianId: null, quiz: null };

function voteCard(v) {
  return `<article class="card">
    <span class="k">${esc(v.proposicao)} · ${formatShortDate(v.data)}</span>
    <h3 class="h" style="font-size:20px">${esc(v.titulo)}</h3>
    <div class="score"><span class="big">${v.sim}×${v.nao}</span><span class="tag ${v.aprovada ? '' : 'soft'}">${v.aprovada ? 'APROVADO' : 'REJEITADO'}</span></div>
    <div class="vbar" role="img" aria-label="${v.sim} sim, ${v.nao} não"><i style="width:${v.sim / Math.max(1, v.sim + v.nao) * 100}%"></i><i style="width:${v.nao / Math.max(1, v.sim + v.nao) * 100}%"></i></div>
    <p style="margin:0;font-size:14px;color:var(--ink-2)">${esc(v.curto)}</p>
    ${v.secreta ? `<div class="secret"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>Voto secreto: só o total é público.</div>` :
      `<div style="display:flex;flex-direction:column;gap:6px">${v.partidos.slice(0, 4).map(partyRow).join('')}</div>`}
    <button type="button" class="more" data-vote="${v.id}">Entender essa votação</button>
  </article>`;
}
function partyRow(p) { const t = p.sim + p.nao + p.outros; return `<div class="party"><b>${esc(p.p)}</b><div class="bar"><i style="width:${p.sim / t * 100}%"></i><i style="width:${p.nao / t * 100}%"></i></div><span>${p.sim}–${p.nao}</span></div>`; }

/* ---------- VOTAÇÃO (detalhe) ---------- */
function selectedVoteView() {
  const v = VOTES_BY_ID[state.voteId];
  if (!v) return '<p class="note">Votação não disponível neste recorte.</p>';
  return `<button type="button" class="back" data-back>‹ Voltar</button>
  <span class="k">${esc(v.proposicao)} · votado em ${formatShortDate(v.data)}</span>
  <h1 class="h" style="font-size:30px">${esc(v.titulo)}</h1>
  <section class="card hero">
    <div class="score"><span class="huge" style="font-size:clamp(44px,14vw,60px)">${v.sim}×${v.nao}</span></div>
    <div class="stack grow-x" role="img" aria-label="${v.sim} sim e ${v.nao} não"><i style="width:${v.sim / Math.max(1, v.sim + v.nao) * 100}%;background:var(--accent-2)"></i><i style="width:${v.nao / Math.max(1, v.sim + v.nao) * 100}%;background:var(--hero-muted)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Sim ${v.sim}</span><span><i style="background:var(--hero-muted)"></i>Não ${v.nao}</span></div>
    <span class="muted">${v.sim} deputados(as) votaram sim e ${v.nao} votaram não. ${v.aprovada ? 'Aprovado.' : 'Rejeitado.'} Hoje: ${esc(v.situacao.toLowerCase())}.</span>
  </section>
  <section class="card">
    <span class="k">O que muda na prática</span>
    <p style="margin:0;font-size:16px;line-height:1.5">${esc(v.naPratica)}</p>
    <div style="display:flex;gap:14px;flex-wrap:wrap"><a href="${esc(v.texto)}" target="_blank" rel="noopener">Texto aprovado</a><a href="${esc(v.ficha)}" target="_blank" rel="noopener">Andamento na Câmara</a></div>
  </section>
  ${whoVotedSection(v)}
  ${v.secreta ? `<section class="card">
    <span class="k">Por que o voto foi secreto?</span>
    <p style="margin:0">Quando a Câmara escolhe uma autoridade, como um ministro do Tribunal de Contas da União, o regimento manda o voto ser secreto. O painel mostra só o total, então não existe registro de como cada deputado(a) votou.</p>
  </section>` : `<section class="card wide">
    <span class="k">Como cada partido votou</span>
    ${v.partidos.length ? `<div class="party-grid">${v.partidos.map(partyRow).join('')}</div>
    <div class="legend"><span><i style="background:var(--accent)"></i>Sim</span><span><i style="background:var(--no)"></i>Não</span></div>
    <button type="button" class="more" data-go="parties">Comparar dois partidos →</button>` : '<p class="muted">Sem dados de votos por partido neste recorte.</p>'}
  </section>`}
  <span class="src">Fonte: Câmara dos Deputados. O resumo foi escrito a partir do texto aprovado.</span>`;
}

/* ---------- PLACAR ---------- */
function selectedVotesView() {
  const votes = DATA.votacoes, approvedVoteCount = votes.filter(vote => vote.aprovada).length;
  if (!votes.length) return pageHead('Câmara · Plenário', 'Placar', 'Nenhuma votação disponível neste recorte.');
  const closestVote = votes.filter(vote => !vote.secreta).map(vote => ({ vote, gap: Math.abs(vote.sim - vote.nao) / Math.max(1, vote.sim + vote.nao) })).sort((first, second) => first.gap - second.gap)[0];
  const totalVoteCount = votes.reduce((sum, vote) => sum + vote.sim + vote.nao, 0), yesVoteCount = votes.reduce((sum, vote) => sum + vote.sim, 0);
  return `${pageHead('Câmara · Plenário', 'Placar', 'Como os(as) deputados(as) votaram nas propostas selecionadas. Toque numa votação para entender o que muda.')}
  <section class="card hero">
    <span class="k">${votes.length} votações selecionadas</span>
    <div class="huge">${approvedVoteCount}<small style="margin-left:6px">de ${votes.length}</small></div>
    <span class="muted">foram aprovadas. A mais recente deste recorte foi em ${formatShortDate(DATA.ultimaVotacao)}.</span>
    <div class="hero-split">
      <div><b class="mono">${pct(yesVoteCount, totalVoteCount)}%</b><span>dos votos foram “sim”</span></div>
      ${closestVote ? `<div><b class="mono">${closestVote.vote.sim}×${closestVote.vote.nao}</b><span>a mais apertada: ${esc(closestVote.vote.titulo)}</span></div>` : ''}
    </div>
    <div class="stack grow-x" role="img" aria-label="Todos os votos: ${pct(yesVoteCount, totalVoteCount)}% sim"><i style="width:${pct(yesVoteCount, totalVoteCount)}%;background:var(--accent-2)"></i><i style="width:${pct(totalVoteCount - yesVoteCount, totalVoteCount)}%;background:var(--hero-muted)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Sim · ${yesVoteCount.toLocaleString('pt-BR')} votos</span><span><i style="background:var(--hero-muted)"></i>Não · ${(totalVoteCount - yesVoteCount).toLocaleString('pt-BR')}</span></div>
  </section>
  <div class="citizen-actions"><button type="button" class="fchip" data-go="parties">Comparar partidos →</button></div>
  ${votes.map(voteCard).join('')}
  <span class="src">Fonte: Câmara dos Deputados (dados abertos de votações do Plenário).</span>`;
}
function voteView() {
  return typeof scoreboardDetailView === 'function' ? scoreboardDetailView() : selectedVoteView();
}
function votesView() {
  return typeof scoreboardVotesView === 'function' ? scoreboardVotesView() : selectedVotesView();
}

/* Compatibilidade para entradas antigas que ainda chamem a rota ficha. */
function legacyProfileView() {
  if (state.deputyId) state.politicianId = String(state.deputyId).includes(':') ? String(state.deputyId) : 'camara:' + state.deputyId;
  return profileView();
}

const LEGACY_VIEWS = {
  inicio: 'home', hoje: 'home', votacoes: 'votes', deputados: 'politicians', ficha: 'profile',
  votacao: 'vote', gastos: 'alerts', gasto: 'profile', lupa: 'alerts', politicos: 'politicians',
  politico: 'profile', presenca: 'attendance', comparar: 'compare', partidos: 'parties',
};
const normalizeView = view => LEGACY_VIEWS[view] || view;

function render() {
  state.view = normalizeView(state.view);
  const views = { home: homeView, votes: votesView, politicians: politiciansView, profile: profileView, vote: voteView,
    alerts: alertsView, attendance: attendanceView, compare: comparisonView, parties: partiesView, city: cityView };
  if (!views[state.view]) state.view = 'home';
  const v = state.view;
  $app.innerHTML = `<div class="view">${views[v]()}</div>`;
  if (typeof scoreboardViewEntered === 'function') scoreboardViewEntered(v);
  document.body.dataset.view = v;
  syncTitle();
  const tab = ['profile', 'politicians', 'attendance', 'compare', 'parties'].includes(v) ? 'politicians' : v === 'vote' ? 'votes' : v;
  document.querySelectorAll('nav.tabs button').forEach(b => b.dataset.go === tab ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
}
/* Endereços próprios: /deputado/<id>, /senador/<id> e seções. O servidor entrega a mesma página com
   resumo e metadados para buscadores; aqui o app lê o endereço ao abrir e o atualiza ao navegar. */
const PATH_BY_VIEW = { home: '/', alerts: '/alertas', votes: '/placar', vote: '/placar', politicians: '/politicos',
  parties: '/partidos', compare: '/comparar', attendance: '/presenca', city: '/minha-cidade' };
const currentPath = () => (typeof location === 'undefined' || typeof location.pathname !== 'string' ? '/' : location.pathname.replace(/\/+$/, '') || '/');
const TITLE_BY_VIEW = { alerts: 'Alertas', votes: 'Placar', vote: 'Placar', politicians: 'Políticos', parties: 'Comparar partidos',
  compare: 'Comparar políticos', attendance: 'Presença', city: 'Minha cidade', profile: 'Ficha' };
function syncTitle() {
  const person = state.view === 'profile' ? citizenState.profile?.pessoa : null;
  const page = person && person.id === state.politicianId ? person.name : TITLE_BY_VIEW[state.view];
  document.title = page ? `${page} · Painel Público` : 'Painel Público: quanto custa e como trabalha cada parlamentar';
}
function viewPath() {
  if (state.view === 'compare' && typeof comparisonPath === 'function') return comparisonPath();
  if (state.view === 'parties' && typeof partyPairPath === 'function') return partyPairPath();
  if (state.view === 'vote' && typeof SCOREBOARD_VOTE_ID !== 'undefined' && SCOREBOARD_VOTE_ID.test(String(state.voteId || ''))) return `/placar/${state.voteId}`;
  const [house, number] = String(state.politicianId || '').split(':');
  if (state.view === 'profile' && /^\d+$/.test(number || '') && (house === 'camara' || house === 'senado')) {
    return `/${house === 'camara' ? 'deputado' : 'senador'}/${number}`;
  }
  return PATH_BY_VIEW[state.view] || '/';
}
function applyLocation() {
  const path = currentPath();
  const vote = path.match(/^\/placar\/(\d+-\d+)$/);
  if (vote) {
    state.view = 'vote';
    state.voteId = vote[1];
    return;
  }
  const comparison = typeof comparisonIdsFromPath === 'function' ? comparisonIdsFromPath(path) : null;
  if (comparison) {
    state.view = 'compare';
    extrasState.comparisonIds = [];
    comparison.forEach(addComparisonPerson);
    return;
  }
  const pair = typeof partyPairFromPath === 'function' ? partyPairFromPath(path) : null;
  if (pair) {
    state.view = 'parties';
    partyState.selected = pair;
    return;
  }
  const profile = path.match(/^\/(deputado|senador)\/(\d+)(?:-|$)/);
  if (profile) {
    state.view = 'profile';
    state.politicianId = `${profile[1] === 'deputado' ? 'camara' : 'senado'}:${profile[2]}`;
    state.deputyId = profile[1] === 'deputado' ? profile[2] : null;
    return;
  }
  const view = Object.keys(PATH_BY_VIEW).find(key => key !== 'vote' && PATH_BY_VIEW[key] === path);
  if (view) state.view = view;
}
function syncLocation(mode = 'push') {
  if (typeof history === 'undefined' || typeof history.pushState !== 'function') return;
  const path = viewPath(), current = currentPath();
  // Endereços com o nome (/deputado/123-nome) continuam valendo para a mesma ficha.
  if (current === path || current.startsWith(path + '-')) return;
  history[mode === 'replace' ? 'replaceState' : 'pushState'](null, '', path);
}
const navigationHistory = [];
function navigateToView(view, keep) {
  view = normalizeView(view);
  if (view === 'profile' && state.deputyId) state.politicianId = String(state.deputyId).includes(':') ? state.deputyId : 'camara:' + state.deputyId;
  if (!keep) navigationHistory.push({ view: state.view, deputyId: state.deputyId, voteId: state.voteId, politicianId: state.politicianId, y: window.scrollY });
  state.view = view; render(); syncLocation(); window.scrollTo(0, 0);
}
function navigateBack() { const h = navigationHistory.pop() || { view: state.view === 'vote' ? 'votes' : 'home', y: 0 }; Object.assign(state, { view: h.view, deputyId: h.deputyId, voteId: h.voteId, politicianId: h.politicianId }); render(); syncLocation('replace'); window.scrollTo(0, h.y || 0); }
// A ficha chega pela API: guardamos a âncora até a seção existir no DOM.
let pendingProfileAnchor = null;
function scrollToProfileAnchor(fromLocation = false) {
  if (fromLocation) pendingProfileAnchor = typeof location !== 'undefined' ? location.hash : null;
  if (state.view !== 'profile' || !/^#profile-(cost|work|alerts)$/.test(pendingProfileAnchor || '')) {
    pendingProfileAnchor = null;
    return false;
  }
  const target = document.getElementById(pendingProfileAnchor.slice(1));
  if (!target) return false;
  target.scrollIntoView({ block: 'start', behavior: 'instant' });
  pendingProfileAnchor = null;
  return true;
}
const rerender = () => { const y = window.scrollY; render(); if (!scrollToProfileAnchor()) window.scrollTo(0, y); };

document.addEventListener('click', e => {
  const t = e.target.closest('[data-copy],[data-go],[data-deputy],[data-quiz],[data-vote],[data-back],[data-summary-retry],[data-city-select],[data-city-search],[data-city-search-submit],[data-city-retry-search],[data-city-retry-detail],[data-scoreboard-page],[data-scoreboard-retry],[data-scoreboard-more]');
  if (!t) return;
  if (typeof scoreboardHandleClick === 'function' && scoreboardHandleClick(e, t)) return;
  if (t.dataset.copy) {
    const done = () => { t.textContent = 'Copiado'; setTimeout(() => { t.textContent = 'Copiar'; }, 1500); };
    const pick = () => { const r = document.createRange(); r.selectNodeContents(t.previousElementSibling); const s = getSelection(); s.removeAllRanges(); s.addRange(r); t.textContent = 'Selecionado'; };
    try { navigator.clipboard.writeText(t.dataset.copy).then(done, pick); } catch (err) { pick(); }
    return;
  }
  if (t.hasAttribute('data-summary-retry')) { homeReset(); return rerender(); }
  if (t.hasAttribute('data-city-select')) return citySelect(t.dataset.citySelect);
  if (t.hasAttribute('data-city-search')) {
    cityViewState.selectedId = null; cityViewState.selectedCity = null; cityViewState.detail = null;
    cityViewState.detailError = null; cityViewState.detailLoading = false; cityViewState.detailSequence++;
    cityViewState.suggestionsOpen = true;
    return navigateToView('city', true);
  }
  if (t.hasAttribute('data-city-search-submit')) return citySearchSubmit();
  if (t.hasAttribute('data-city-retry-search')) return citySearchSubmit();
  if (t.hasAttribute('data-city-retry-detail')) return cityLoadDetail();
  if (t.hasAttribute('data-back')) return navigateBack();
  if (t.dataset.quiz) { state.quiz = t.dataset.quiz; return rerender(); }
  if (t.dataset.vote) { state.voteId = t.dataset.vote; return navigateToView('vote'); }
  if (t.dataset.deputy) {
    // Links reais continuam abrindo em nova aba com Ctrl/Cmd/Shift ou botão do meio.
    if (t.tagName === 'A' && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button)) return;
    e.preventDefault();
    return openPolitician(t.dataset.deputy);
  }
  if (t.dataset.go) { navigationHistory.length = 0; navigateToView(t.dataset.go, true); }
});
/* Alterna tema claro/escuro; o padrão é escuro e a escolha fica salva neste navegador. */
const THEME_ICON = '<svg class="theme-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path class="theme-moon" d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/><g class="theme-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></g></svg>';
const currentTheme = () => document.documentElement?.dataset?.theme === 'light' ? 'light' : 'dark';
const themeLabel = () => currentTheme() === 'light' ? 'Tema escuro' : 'Tema claro';
function themeToggleHTML(extraClass = 'theme-toggle-top') {
  return `<button type="button" class="theme-toggle ${extraClass}" data-theme-toggle aria-pressed="${currentTheme() === 'light'}" aria-label="Mudar para ${themeLabel().toLowerCase()}">${THEME_ICON}<span>${themeLabel()}</span></button>`;
}
function syncThemeToggles() {
  document.querySelectorAll('[data-theme-toggle]').forEach(button => {
    button.setAttribute('aria-pressed', String(currentTheme() === 'light'));
    button.setAttribute('aria-label', `Mudar para ${themeLabel().toLowerCase()}`);
    button.title = `Mudar para ${themeLabel().toLowerCase()}`;
    const label = button.querySelector('span');
    if (label) label.textContent = themeLabel();
  });
}
function toggleTheme() {
  const next = currentTheme() === 'light' ? 'dark' : 'light';
  if (!document.documentElement) return;
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('painel-theme', next); } catch (error) { /* Sem armazenamento, vale só nesta visita. */ }
  syncThemeToggles();
}
document.addEventListener('click', event => { if (event.target.closest('[data-theme-toggle]')) toggleTheme(); });
applyLocation();
render();
syncLocation('replace');
scrollToProfileAnchor(true);
syncThemeToggles();
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('popstate', () => { applyLocation(); render(); if (!scrollToProfileAnchor(true)) window.scrollTo(0, 0); });
}
