/* Telas do cidadão: "Gastos incomuns" (Home), "Alertas", "Políticos" (busca) e a ficha leve.
   Tudo em linguagem simples. */
const citizenState = {
  cache: new Map(), pending: new Set(),
  alerts: { type: 'pico,fornecedor', role: '', page: 1, items: [], total: null, loading: false, error: null, key: '', counts: null },
  politicians: { query: '', role: '', order: 'nome', page: 1, items: [], total: null, loading: false, error: null, key: '', averageSpend: null, coverage: null },
  profile: null, profileId: null, profileLoading: false, profileError: null,
};
/* Peças de identidade usadas em todas as abas */
function brandMark() {
  return `<span class="brand"><svg class="brand-ic" width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="8" fill="var(--accent)"/><rect x="6" y="13" width="3.2" height="7" rx="1.2" fill="#fff"/><rect x="11.4" y="9" width="3.2" height="11" rx="1.2" fill="#fff"/><rect x="16.8" y="5.5" width="3.2" height="14.5" rx="1.2" fill="#fff" opacity=".7"/></svg>Painel Público</span>`;
}
/* Skeleton: a forma do conteúdo em cinza, com brilho suave, enquanto os dados chegam.
   Toda espera do app usa uma destas formas; o texto fica só para leitores de tela. */
const skL = (w = '100%', h = 12, extra = '') => `<i class="sk ${extra}" style="width:${w};height:${h}px"></i>`;
const skO = (s = 44) => `<i class="sk sk-o" style="width:${s}px;height:${s}px"></i>`;
const SK_MSG = '<span class="sr-only" role="status">Carregando…</span>';
function skel(kind = 'cards', n = 3) {
  const rep = (k, f) => Array.from({ length: k }, (_, i) => f(i)).join('');
  const rowSkeletons = count => rep(count, index => `<div class="sk-row">${skO(44)}<span class="sk-col">${skL(index % 2 ? '58%' : '70%', 13)}${skL('42%', 10)}${skL('80%', 5)}</span>${skL('64px', 14)}</div>`);
  if (kind === 'alerta') return SK_MSG + rep(n, () => `<div class="card sk-card citizen-alert" aria-hidden="true"><div class="sk-between">${skL('118px', 22, 'sk-pill')}${skL('56px', 12)}</div>
    <div class="sk-row sk-flat">${skO(40)}<span class="sk-col">${skL('52%', 13)}${skL('70%', 10)}</span></div>${skL('86%', 22)}${skL('60%', 22)}
    <div class="sk-bars">${rep(9, i => `<i class="sk" style="height:${[22, 30, 18, 40, 86, 26, 20, 34, 16][i]}%"></i>`)}</div>${skL('96%')}${skL('72%')}
    <div class="sk-between sk-start">${skL('92px', 36, 'sk-pill')}${skL('132px', 36, 'sk-pill')}</div></div>`);
  if (kind === 'lista') return `${SK_MSG}<section class="card citizen-list sk-card" aria-hidden="true">${rowSkeletons(n)}</section>`;
  if (kind === 'linhas') return `${SK_MSG}<div aria-hidden="true">${rowSkeletons(n)}</div>`;
  if (kind === 'chips') return `<div class="chips" aria-hidden="true">${rep(n, i => skL(`${[64, 56, 72, 60, 84, 58][i % 6]}px`, 40, 'sk-pill'))}</div>`;
  if (kind === 'numeros') return `${SK_MSG}<div class="row2 sk-tiles" aria-hidden="true">${rep(3, () => `<div class="tile">${skL('60%', 10)}${skL('80%', 22)}</div>`)}</div>`;
  if (kind === 'ficha') return `${SK_MSG}<div class="profile" aria-hidden="true">${skO(64)}<span class="sk-col" style="flex:1">${skL('55%', 24)}${skL('40%', 12)}</span></div>
    <section class="card hero sk-card" aria-hidden="true">${skL('40%', 10)}${skL('62%', 56)}${skL('90%')}${skL('100%', 10)}${skL('100%', 10)}</section>
    ${rep(2, () => `<section class="card sk-card" aria-hidden="true">${skL('35%', 10)}${skL('50%', 30)}${skL('100%', 8)}${skL('88%')}${skL('70%')}</section>`)}`;
  if (kind === 'ficha-respostas') return `${SK_MSG}<div class="profile" aria-hidden="true">${skO(64)}<span class="sk-col" style="flex:1">${skL('55%', 24)}${skL('40%', 12)}</span></div>
    <span class="k">Em 3 respostas</span><div class="citizen-answers" aria-hidden="true">${rep(3, i => `<section class="card ${i === 0 ? 'hero' : ''} sk-card">${skL('50%', 24)}${skL('65%', 56)}${skL('90%')}${skL('100%', 10)}${skL('100%', 10)}</section>`)}</div>
    ${skL('110px', 24)}${rep(4, () => `<div class="card sk-card" aria-hidden="true">${skL('70%', 24)}</div>`)}`;
  if (kind === 'cmp') return `${SK_MSG}<section class="card wide sk-card cmp" aria-hidden="true"><div class="cmp-head"><span></span>${rep(2, () => `<div class="sk-colc">${skO(56)}${skL('70%', 13)}${skL('50%', 10)}</div>`)}</div>
    ${rep(5, () => `<div class="cmp-row">${skL('80%', 11)}${skL('70%', 16)}${skL('70%', 16)}</div>`)}</section>`;
  return SK_MSG + rep(n, () => `<section class="card sk-card" aria-hidden="true">${skL('35%', 10)}${skL('70%', 20)}${skL('100%')}${skL('92%')}${skL('64%')}</section>`);
}
function pageHead(kicker, title, lead) {
  return `<header class="ph"><span class="k">${kicker}</span><h1 class="h ph-t">${title}</h1>${lead ? `<p class="ph-lead">${lead}</p>` : ''}</header>`;
}
const ROLE_LABELS = { deputado: 'Deputado(a) federal', senador: 'Senador(a)' };
const ROLE_LABELS_PLURAL = { deputado: 'deputados(as)', senador: 'senadores(as)' };
const MONTH_NAMES_LONG = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

function citizenErrorMessage(e) {
  if (e && e.status === 404) return 'O servidor que está rodando é de uma versão anterior. Feche-o (Ctrl+C no terminal) e rode de novo: python3 -m backend.server --port 8000';
  if (location.protocol === 'file:') return 'Abra o app pelo servidor (python3 -m backend.server --port 8000), não pelo arquivo direto.';
  if (e && e.name === 'AbortError') return 'O servidor demorou demais para responder.';
  return (e && e.message) || 'Não deu para carregar agora.';
}
async function citizenGet(path) {
  if (citizenState.cache.has(path)) return citizenState.cache.get(path);
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 15000);
  let r;
  try { r = await fetch(path, { headers: { Accept: 'application/json' }, signal: ctl.signal }); }
  finally { clearTimeout(timer); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const err = new Error(data.error || 'Não deu para carregar agora.'); err.status = r.status; throw err; }
  citizenState.cache.set(path, data);
  return data;
}
const citizenLocalId = id => String(id || '').startsWith('camara:') ? String(id).slice(7) : null;
const citizenHasProfile = id => /^(?:camara|senado):\d+$/.test(String(id || ''));
function citizenInitials(name) { return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase(); }
/* Foto oficial (Câmara/Senado); se não carregar, ficam as iniciais por baixo */
function citizenPhoto(id) {
  const [chamber, personNumber] = String(id || '').split(':');
  if (!/^\d+$/.test(personNumber || '')) return null;
  return chamber === 'camara' ? `https://www.camara.leg.br/internet/deputado/bandep/${personNumber}.jpg` : chamber === 'senado' ? `https://www.senado.leg.br/senadores/img/fotos-oficiais/senador${personNumber}.jpg` : null;
}
function citizenAvatar(p, size = 44) {
  const dim = `width:${size}px;height:${size}px`;
  const initials = `<span class="citizen-av citizen-initials" style="${dim};font-size:${Math.round(size / 2.8)}px" aria-hidden="true">${esc(citizenInitials(citizenName(p.name)))}</span>`;
  const rawPhoto = p.photo || p.foto;
  const url = (typeof profileSafeUrl === 'function' && profileSafeUrl(rawPhoto)) || citizenPhoto(p.id);
  return url ? `<span class="citizen-avs" style="${dim}">${initials}<img class="citizen-av" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()" style="${dim}"></span>` : initials;
}
const citizenName = n => { const s = String(n || ''); return s === s.toUpperCase() ? s.toLowerCase().replace(/(^|\s)\S/g, c => c.toUpperCase()) : s; };
function citizenRoleDescription(p) {
  return [ROLE_LABELS[p.role] || 'Parlamentar', p.party, p.uf].filter(Boolean).map(esc).join(' · ') + (p.foraDaLista ? ' · fora da lista atual' : '');
}
function senateProfileSnapshot(p) {
  if (p?.role !== 'senador') return '';
  const position = String(p.position || '').trim();
  const employmentStatus = String(p.employmentStatus || '').trim();
  if (!position && !employmentStatus) return '';
  return `<section class="card"><span class="k">Na fotografia da fonte</span>
    ${position ? `<p><b>Participação no mandato:</b> ${esc(position)}</p>` : ''}
    ${employmentStatus ? `<p>${esc(employmentStatus)}</p>` : ''}
    ${p.sourceUrl ? `<a class="fchip" href="${esc(p.sourceUrl)}" target="_blank" rel="noopener">Fonte do Senado ↗</a>` : ''}
  </section>`;
}
const formatCitizenAmount = v => v >= 1e6 ? 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi' : 'R$ ' + Math.round(v / 1e3).toLocaleString('pt-BR') + ' mil';
const citizenSourceUrl = person => {
  const [chamber, personNumber] = String(person.id || '').split(':');
  return chamber === 'camara' ? `https://www.camara.leg.br/deputados/${personNumber}?ano=2026` : chamber === 'senado' ? `https://www25.senado.leg.br/web/senadores/senador/-/perfil/${personNumber}` : null;
};

/* ---------- Cartão de alerta: o coração da consulta simples ---------- */
function alertLevel(a) {
  return a.nivel === 'alto' ? ['high', 'Incomum'] : a.nivel === 'medio' ? ['medium', 'Acima do habitual'] : ['info', 'Para conferir'];
}
function alertVisualization(a) {
  if (a.tipo === 'pico' && a.serie?.length) {
    const max = Math.max(...a.serie.map(s => s.valor || 0), 1), refH = a.referencia / max * 64;
    return `<div class="citizen-spark" role="img" aria-label="Gasto por mês. Em ${MONTH_NAMES_LONG[a.mes]} foi ${brl(a.valor)}; o habitual era ${brl(a.referencia)}.">
      <div class="citizen-ref" style="bottom:${refH + 16}px"><span>habitual: ${formatCitizenAmount(a.referencia)}</span></div>
      ${a.serie.map(s => `<div class="citizen-col ${s.mes === a.mes ? 'hot' : s.mes > a.mes ? 'after' : ''}"><i style="height:${Math.max(2, (s.valor || 0) / max * 64)}px"></i><span>${SHORT_MONTHS[s.mes]}</span></div>`).join('')}
    </div>`;
  }
  if (a.tipo === 'fornecedor' && a.parte) {
    return `<div class="citizen-share" role="img" aria-label="${Math.round(a.parte * 100)}% para ${esc(a.fornecedor)}">
      <div class="citizen-sharebar"><i style="width:${a.parte * 100}%"></i></div>
      <div class="citizen-sharelbl"><span><b>${Math.round(a.parte * 100)}%</b> ${esc(citizenName(a.fornecedor))}</span><span>${100 - Math.round(a.parte * 100)}% outros</span></div>
    </div>`;
  }
  return '';
}
function alertExplanation(a) {
  if (a.tipo === 'pico') return `Aparece quando o gasto de um mês passa de 1,75 vez o habitual da própria pessoa nos meses anteriores, a diferença é de pelo menos R$ 10 mil e o mês também fica acima do que um(a) parlamentar costuma gastar por mês. "Habitual" é o valor do meio dos meses anteriores (a mediana). Meses seguidos acima do habitual contam como um alerta só. A mesma regra vale para todos(as), de qualquer partido.`;
  if (a.tipo === 'fornecedor') return `Aparece quando metade ou mais do dinheiro da cota no ano foi para uma mesma empresa, somando pelo menos R$ 30 mil. Pode ser um contrato fixo de divulgação ou escritório; vale conferir as notas.`;
  return `Aparece para toda nota de R$ 10 mil ou mais. É só um corte de valor.`;
}
function alertCard(a, opts = {}) {
  const [cls, label] = alertLevel(a), p = a.pessoa || {};
  return `<article class="card citizen-alert" data-level="${cls}">
    <div class="citizen-top"><span class="citizen-chip ${cls}"><i></i>${label}</span><span class="muted">${a.tipo === 'pico' ? SHORT_MONTHS[a.mes] + '/' + String(a.periodo).slice(0, 4) : 'em ' + String(a.periodo).slice(0, 4)}</span></div>
    ${opts.semPessoa ? '' : `<button type="button" class="citizen-who" data-politician="${esc(p.id)}">${citizenAvatar(p, 40)}<span><b>${esc(citizenName(p.name))}</b><small>${citizenRoleDescription(p)}</small></span></button>`}
    <h3 class="citizen-title">${esc(a.titulo)}</h3>
    ${alertVisualization(a)}
    <p class="citizen-statement">${esc(a.frase)}</p>
    ${a.contexto?.frase ? `<p class="citizen-context">${esc(a.contexto.frase)}</p>` : ''}
    <details class="citizen-why"><summary>Por que apareceu aqui?</summary><p>${alertExplanation(a)}</p><p class="muted">Incomum não quer dizer irregular. É um convite para conferir as notas na fonte oficial.</p></details>
    <div class="citizen-actions">${opts.semPessoa ? '' : `<button type="button" class="fchip" data-politician="${esc(p.id)}">Ver a ficha</button>`}${citizenSourceUrl(p) ? `<a class="fchip" href="${esc(citizenSourceUrl(p))}" target="_blank" rel="noopener">Conferir na fonte ↗</a>` : ''}</div>
  </article>`;
}

/* ---------- Home: "Gastos incomuns" ---------- */
function homeAlertCard() {
  const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
  const data = citizenState.cache.get(path);
  if (!data) {
    if (!citizenState.pending.has(path)) { citizenState.pending.add(path); citizenGet(path).then(() => { citizenState.pending.delete(path); if (state.view === 'home') rerender(); }).catch(() => { citizenState.pending.delete(path); citizenState.cache.set(path, { error: true }); if (state.view === 'home') rerender(); }); }
    return `<section class="citizen-home"><div class="citizen-head"><h2 class="h">Gastos incomuns</h2></div><div class="carousel citizen-carousel">${skel('alerta', 3)}</div></section>`;
  }
  if (data.error) return `<section class="citizen-home"><div class="citizen-head"><div><h2 class="h">Gastos incomuns</h2><span class="muted">Os alertas da Câmara e do Senado não carregaram.</span></div></div><section class="card"><p>Não deu para carregar os alertas agora.</p><button type="button" class="more" data-home-retry>Tentar de novo</button></section></section>`;
  const alerts = [...data.itens].sort((first, second) => (second.nivel === 'alto') - (first.nivel === 'alto'));
  return `<section class="citizen-home">
    <div class="citizen-head"><div><h2 class="h">Gastos incomuns</h2><span class="muted">Gastos de deputados(as) e senadores(as) em 2026 que fogem do padrão, pelos dados oficiais. Não indicam irregularidade.</span></div></div>
    <div class="carousel citizen-carousel">${alerts.map(alert => alertCard(alert)).join('')}</div>
    <button type="button" class="opt citizen-cta" data-go="alerts">Ver os ${data.total} alertas</button>
  </section>`;
}

/* ---------- Aba "Alertas" ---------- */
function alertFilterKey() { const l = citizenState.alerts; return `tipo=${l.type}&cargo=${l.role}`; }
function loadAlerts(more) {
  const l = citizenState.alerts, key = alertFilterKey();
  if (!more && l.key === key) return;
  if (!more) { l.key = key; l.page = 1; l.items = []; l.total = null; }
  l.loading = true; l.error = null;
  const qs = `/api/c/radar?pageSize=12&page=${l.page}&tipo=${l.type}${l.role ? '&cargo=' + l.role : ''}`;
  citizenGet(qs).then(d => { if (l.key !== key) return; l.items = l.items.concat(d.itens); l.total = d.total; l.counts = d.contagem; l.loading = false; if (state.view === 'alerts') rerender(); })
    .catch(e => { if (l.key !== key) return; l.loading = false; l.error = citizenErrorMessage(e); if (state.view === 'alerts') rerender(); });
}
const TOP_ALERTS_PATH = '/api/c/politicos?pageSize=5&page=1&ordem=alertas';
function loadTopAlerts() {
  if (citizenState.cache.has(TOP_ALERTS_PATH) || citizenState.pending.has(TOP_ALERTS_PATH)) return;
  citizenState.pending.add(TOP_ALERTS_PATH);
  citizenGet(TOP_ALERTS_PATH).then(() => { if (state.view === 'alerts') rerender(); }).catch(() => citizenState.cache.set(TOP_ALERTS_PATH, { itens: [] }));
}
function alertSummaryCard() {
  const alertState = citizenState.alerts;
  const alertCounts = alertState.counts;
  const topPeople = (citizenState.cache.get(TOP_ALERTS_PATH)?.itens || []).filter(person => person.alertas);
  const monthlyPeakCount = alertCounts?.pico || 0;
  const supplierConcentrationCount = alertCounts?.fornecedor || 0;
  const totalCount = monthlyPeakCount + supplierConcentrationCount;
  return `<section class="card hero">
    <span class="k">Alertas em 2026</span>
    <div class="huge">${alertCounts ? totalCount.toLocaleString('pt-BR') : '—'}</div>
    <span class="muted">gastos incomuns para conferir. Incomum não quer dizer irregular.</span>
    ${totalCount ? `<div class="stack" role="img" aria-label="${monthlyPeakCount} picos num mês e ${supplierConcentrationCount} concentrações numa empresa"><i style="width:${monthlyPeakCount / totalCount * 100}%;background:var(--accent-2)"></i><i style="width:${supplierConcentrationCount / totalCount * 100}%;background:var(--hero-fg)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Mês acima do habitual · ${monthlyPeakCount}</span><span><i style="background:var(--hero-fg)"></i>Mesmo fornecedor · ${supplierConcentrationCount}</span></div>` : ''}
    ${topPeople.length ? `<span class="k" style="margin-top:6px">Maiores valores em alerta</span>
    <div class="faces citizen-top5">${topPeople.map(person => `<button type="button" class="face" data-politician="${esc(person.id)}">${citizenAvatar(person, 54)}<span>${esc(citizenName(person.name).split(' ')[0])}</span><em>${person.valorAlertas ? esc(formatCitizenAmount(person.valorAlertas)) : `${person.alertas} ${person.alertas === 1 ? 'ALERTA' : 'ALERTAS'}`}</em></button>`).join('')}</div>` : ''}
  </section>`;
}
function alertsView() {
  const l = citizenState.alerts; loadAlerts(false); loadTopAlerts();
  const types = [['pico,fornecedor', 'Tudo'], ['pico', 'Mês acima do habitual'], ['fornecedor', 'Mesmo fornecedor']];
  const roles = [['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']];
  return `${pageHead('Entenda em 1 minuto', 'Alertas', 'Cada cartão é um gasto incomum na cota de um(a) deputado(a) ou senador(a), segundo regras fixas e iguais para todos(as). Toque para ver de quem é e conferir na fonte.')}
    ${alertSummaryCard()}
    <div class="citizen-filters">
      <div class="chips" role="group" aria-label="Tipo de alerta">${types.map(([k, n]) => `<button type="button" class="fchip" data-alert-type="${k}" aria-pressed="${l.type === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Cargo">${roles.map(([k, n]) => `<button type="button" class="fchip" data-alert-role="${k}" aria-pressed="${l.role === k}">${n}</button>`).join('')}</div>
    </div>
    ${l.error ? `<section class="card"><p>Não deu para carregar os alertas agora.</p><p class="muted">${esc(l.error)}</p><button type="button" class="more" data-alert-retry>Tentar de novo</button></section>` : ''}
    ${l.total !== null ? `<span class="muted" role="status">${l.total} ${l.total === 1 ? 'alerta' : 'alertas'} neste filtro</span>` : ''}
    ${l.items.map(a => alertCard(a)).join('')}
    ${l.loading && !l.error ? skel('alerta', l.items.length ? 1 : 3) : l.total !== null && l.items.length < l.total ? `<button type="button" class="opt citizen-more" data-alert-more>Mostrar mais</button>` : ''}
    <section class="card citizen-how"><span class="k">Como funciona</span>
      <p><b>Mês acima do habitual:</b> o gasto do mês passou de 1,75 vez o habitual dos meses anteriores.</p>
      <p><b>Mesmo fornecedor:</b> metade ou mais do dinheiro do ano foi para a mesma empresa.</p>
      <p class="muted">Pode ter explicação, como um evento no estado ou um contrato fixo. Os dados vêm das notas que a Câmara e o Senado publicam; as passagens aéreas da Câmara não entram nessa conta.</p>
    </section>`;
}

/* ---------- Aba "Políticos" ---------- */
function loadPoliticians(more) {
  const p = citizenState.politicians, key = `q=${p.query}&cargo=${p.role}&ordem=${p.order}`;
  if (!more && p.key === key) return;
  if (!more) { p.key = key; p.page = 1; p.items = []; p.total = null; }
  p.loading = true; p.error = null;
  const qs = `/api/c/politicos?pageSize=25&page=${p.page}&ordem=${p.order}${p.role ? '&cargo=' + p.role : ''}${p.query ? '&q=' + encodeURIComponent(p.query) : ''}`;
  citizenGet(qs).then(d => { if (p.key !== key) return; p.items = p.items.concat(d.itens); p.total = d.total; p.averageSpend = d.medias; p.coverage = d.cobertura; p.loading = false; if (['politicians'].includes(state.view)) renderPoliticianList(); })
    .catch(e => { if (p.key !== key) return; p.loading = false; p.error = citizenErrorMessage(e); if (['politicians'].includes(state.view)) renderPoliticianList(); });
}
function politicianRow(person, max) {
  const hasExpenseData = person.hasExpenseData === undefined ? person.gasto != null : Boolean(person.hasExpenseData);
  const averageSpend = citizenState.politicians.averageSpend?.[person.role]?.media;
  const aboveAverage = hasExpenseData && averageSpend && person.gasto > averageSpend * 1.25;
  const roleLabel = person.role === 'senador' ? 'Senador(a)' : 'Deputado(a)';
  const barWidth = hasExpenseData && person.gasto > 0 ? Math.max(2, person.gasto / max * 100) : 0;
  const spendLabel = hasExpenseData ? (person.gasto === 0 ? 'R$ 0' : formatCitizenAmount(person.gasto)) : 'Sem dados';
  return `<button type="button" class="citizen-row" data-politician="${esc(person.id)}">${citizenAvatar(person, 48)}<span class="citizen-rowtxt"><b>${esc(citizenName(person.name))}</b><small>${[roleLabel, person.party, person.uf].filter(Boolean).map(esc).join(' · ')}</small>
      <span class="citizen-rowbar"><i style="width:${barWidth}%" class="${aboveAverage ? 'hi' : ''}"></i></span></span>
    <span class="citizen-rowval"><b class="mono">${spendLabel}</b>${person.alertas ? `<span class="citizen-chip high citizen-mini"><i></i>${person.alertas} ${person.alertas === 1 ? 'alerta' : 'alertas'}</span>` : `<small>${hasExpenseData ? aboveAverage ? 'acima da média' : 'na cota' : 'sem despesa observada'}</small>`}</span></button>`;
}
function politicianCoverageHTML(coverage) {
  if (!coverage) return skL('260px', 14);
  const deputies = coverage.deputado, senators = coverage.senador;
  if (![deputies?.count, deputies?.withExpenses, senators?.count, senators?.withExpenses].every(Number.isFinite)) return 'Cobertura da lista indisponível.';
  return `<b>${deputies.count} deputados(as)</b> · <b>${senators.count} registros do Senado</b>`;
}
function politicianCoverageNotesHTML(coverage) {
  if (!coverage) return '';
  const deputies = coverage.deputado, senators = coverage.senador;
  if (![deputies?.count, deputies?.withExpenses, senators?.count, senators?.withExpenses].every(Number.isFinite)) return '';
  const senateSeatNote = senators.count > 81
    ? '<p class="muted">O Senado tem 81 cadeiras; registros extras no retrato da fonte podem refletir suplentes em transição.</p>'
    : '';
  return `<details class="card"><summary><b>Sobre estes dados</b></summary>
    <p class="muted">Despesas observadas para ${deputies.withExpenses} de ${deputies.count} deputados(as) e ${senators.withExpenses} de ${senators.count} senadores(as).</p>${senateSeatNote}
  </details>`;
}
function politicianListHTML() {
  const p = citizenState.politicians;
  if (p.error) return `<section class="card"><p>Não deu para carregar a lista agora.</p><p class="muted">${esc(p.error)}</p><button type="button" class="more" data-politician-retry>Tentar de novo</button></section>`;
  if (!p.items.length && p.loading) return skel('lista', 8);
  if (!p.items.length) return `<section class="card"><p>Ninguém encontrado com “${esc(p.query)}”.</p><p class="muted">Tente só o sobrenome, a sigla do partido (PT, PL…) ou do estado (SP, MG…).</p></section>`;
  const observedSpending = p.items.filter(person => person.gasto != null).map(person => person.gasto);
  const max = Math.max(1, ...observedSpending, ...Object.values(p.averageSpend || {}).map(item => (item.media || 0) * 1.5));
  return `<span class="muted" role="status">${p.total} ${p.total === 1 ? 'pessoa' : 'pessoas'} · valor gasto da cota em 2026</span><section class="card citizen-list">${p.items.map(x => politicianRow(x, max)).join('')}</section>
    ${p.loading ? skel('lista', 3) : p.items.length < p.total ? '<button type="button" class="opt citizen-more" data-politician-more>Mostrar mais</button>' : ''}`;
}
function renderPoliticianList() {
  const summaryElement = document.getElementById('citizen-politician-summary');
  if (summaryElement) summaryElement.innerHTML = politicianCoverageHTML(citizenState.politicians.coverage);
  const notesElement = document.getElementById('citizen-politician-notes');
  if (notesElement) notesElement.innerHTML = politicianCoverageNotesHTML(citizenState.politicians.coverage);
  const el = document.getElementById('citizen-politician-list');
  if (el) el.innerHTML = politicianListHTML();
}
function politiciansView() {
  const p = citizenState.politicians; loadPoliticians(false);
  return `${pageHead('Deputados(as) e senadores(as)', 'Políticos', 'Busque qualquer um(a) e veja quanto gastou da cota em 2026, com os alertas.')}
    <div id="citizen-politician-summary" class="citizen-roster-summary" role="status">${politicianCoverageHTML(p.coverage)}</div>
    <label class="search" for="citizen-search"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="citizen-search" type="search" placeholder="Nome, partido ou estado" value="${esc(p.query)}" autocomplete="off"></label>
    <div class="citizen-filters">
      <div class="chips" role="group" aria-label="Cargo">${[['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']].map(([k, n]) => `<button type="button" class="fchip" data-politician-role="${k}" aria-pressed="${p.role === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Ordenar">${[['nome', 'A–Z'], ['gasto', 'Quem mais gastou'], ['alertas', 'Maior valor em alerta']].map(([k, n]) => `<button type="button" class="fchip" data-politician-order="${k}" aria-pressed="${p.order === k}">${n}</button>`).join('')}</div>
    </div>
    <div class="citizen-actions"><button type="button" class="fchip" data-cmp-start="">Comparar dois(duas) lado a lado →</button><button type="button" class="fchip" data-go="parties">Comparar partidos →</button><button type="button" class="fchip" data-go="attendance">Presença dos deputados →</button></div>
    <div id="citizen-politician-list" class="citizen-stack" aria-live="polite">${politicianListHTML()}</div>
    <div id="citizen-politician-notes">${politicianCoverageNotesHTML(p.coverage)}</div>
    <span class="src">Valor: quanto cada um(a) gastou da cota em 2026, pelas notas publicadas. Não é salário. A barra roxa mais forte indica gasto acima da média.</span>`;
}

/* ---------- Ficha leve (qualquer deputado ou senador) ---------- */
function loadProfile(id) {
  if (citizenState.profileId === id) return;
  citizenState.profileId = id; citizenState.profile = null; citizenState.profileError = null; citizenState.profileLoading = true;
  citizenGet('/api/c/politico/' + encodeURIComponent(id)).then(d => { if (citizenState.profileId !== id) return; citizenState.profile = d; citizenState.profileLoading = false; if (state.view === 'profile') rerender(); })
    .catch(e => { if (citizenState.profileId !== id) return; citizenState.profileLoading = false; citizenState.profileError = citizenErrorMessage(e); if (state.view === 'profile') rerender(); });
}
function profileExpenseAnswer(profileRecord, person, hasExpenseData) {
  const averageSpend = profileRecord.media || 0, difference = averageSpend ? profileRecord.total / averageSpend - 1 : 0;
  const totalLabel = profileRecord.total === 0 ? '0' : Math.round(profileRecord.total / 1e3).toLocaleString('pt-BR') + ' mil';
  const verdict = Math.abs(difference) < 0.1 ? 'Parecido com a média' : `${Math.round(Math.abs(difference) * 100)}% ${difference > 0 ? 'acima' : 'abaixo'} da média`;
  const salaryNote = person.role === 'senador'
    ? `<p class="citizen-salary">Salário efetivamente pago não disponível nesta base de forma individual. Subsídio bruto de referência do cargo: ${brl(PROFILE_SALARY[person.role].amount)}/mês.</p>`
    : `<p class="citizen-salary">Salário à parte: ${brl(PROFILE_SALARY[person.role].amount)}/mês</p>`;
  return `<section class="card hero citizen-answer" data-profile-answer="expenses">
    <h2 class="h">Quanto custa?</h2><span class="k">Cota parlamentar · 2026</span>
    <div class="huge">${hasExpenseData ? `<small>R$</small>${totalLabel}` : 'Sem dados'}</div>
    ${salaryNote}
    ${hasExpenseData ? (averageSpend ? `<div class="citizen-vs">
      <div><span>${esc(citizenName(person.name).split(' ')[0])}</span><b class="mono">${profileRecord.total === 0 ? 'R$ 0' : formatCitizenAmount(profileRecord.total)}</b></div><div class="citizen-vsbar"><i style="width:${Math.min(100, profileRecord.total / Math.max(profileRecord.total, averageSpend) * 100)}%"></i></div>
      <div><span>Média dos(as) ${ROLE_LABELS_PLURAL[person.role] || 'colegas'}</span><b class="mono">${formatCitizenAmount(averageSpend)}</b></div><div class="citizen-vsbar avg"><i style="width:${Math.min(100, averageSpend / Math.max(profileRecord.total, averageSpend) * 100)}%"></i></div>
    </div><span class="fchip citizen-verdict">${verdict}</span>` : '<p class="muted">Média do cargo indisponível neste recorte.</p>')
    : '<p class="muted">Nenhuma despesa de reembolso foi observada para este perfil no recorte importado. Ausência não significa gasto zero.</p>'}
  </section>`;
}
function profileWorkAnswer(shared) {
  const head = '<section class="card citizen-answer" data-profile-answer="work"><h2 class="h">Trabalha?</h2>';
  const senate = shared.person.role === 'senador', house = senate ? 'Senado' : 'Câmara';
  if (senate) profileSenateEnsure();
  if (senate && profileSenateLoading()) return `${head}${skel('linhas', 2)}</section>`;
  const presence = shared.presence, rows = profilePresenceRows(senate ? 'senado' : 'camara');
  const registeredPresence = senate ? shared.registeredPresence : null;
  const unit = senate && profileSenateSource('presenca')?.unit === 'sessoes' ? 'sessões' : 'dias';
  const averagePresence = rows.length ? Math.round(rows.reduce((sum, row) => sum + row.presente / row.dias, 0) / rows.length * 100) : null;
  const presencePercent = presence ? Math.round(presence.presente / presence.dias * 100) : null;
  const votes = votesForPerson(shared.id), knownVotes = votes.filter(record => record.recordedVote !== null);
  const presenceOnlyCount = knownVotes.filter(record => ['Presente', 'Presidiu'].includes(record.recordedVote)).length;
  const identifiedVotes = knownVotes.filter(record => senate ? ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Não votou'].includes(record.recordedVote) : !['Presente', 'Presidiu'].includes(record.recordedVote));
  const recordedVoteCount = identifiedVotes.filter(record => record.recordedVote !== 'Não votou').length;
  return `${head}<span class="k">Presença no Plenário · 2026</span>
    ${presence ? `<div class="huge">${presencePercent}<small>%</small></div>
      <p>${presence.presente} de ${presence.dias} ${unit}${averagePresence !== null ? ` · média ${senate ? 'do' : 'da'} ${house}: ${averagePresence}%` : ''}</p>
      ${attendanceBar(presence)}
      <div class="legend"><span><i style="background:var(--accent)"></i>Presente ${presence.presente}</span><span><i style="background:var(--muted);opacity:.55"></i>Justificada ${presence.justificadas}</span><span><i style="background:var(--warn)"></i>Falta ${presence.falta}</span></div>`
      : registeredPresence ? `<div class="huge">${registeredPresence.presente}<small> sessões</small></div><p>Com presença registrada no Diário do Senado.</p>
        <p class="muted">${profileSenateSource('presenca')?.sessionCount || ''} listas de sessões consultadas em 2026. Faltas e justificativas não apuradas; sem percentual de assiduidade.</p>`
        : `<p class="citizen-empty">Presença ${senate ? 'do Senado ' : ''}sem registro importado.</p><p class="muted">Ausência de dado não significa zero presença.</p>`}
    <p class="citizen-vote-count">${identifiedVotes.length ? `${senate ? 'Voto identificado em' : 'Votou em'} <b>${recordedVoteCount} de ${senate ? knownVotes.length : votes.length}</b> ${senate ? 'votações do Senado com registro individual' : 'votações do Placar'}` : presenceOnlyCount || (senate && knownVotes.length) ? 'Sem voto nominal identificado neste recorte.' : `Sem registros individuais ${senate ? 'nas votações nominais do Senado' : 'nas votações do Placar'}.`}</p>
    ${presenceOnlyCount ? `<p class="muted">${presenceOnlyCount} ${presenceOnlyCount === 1 ? 'registro só de presença ou presidência' : 'registros só de presença ou presidência'}.</p>` : ''}
    ${senate ? '<p class="muted">Sem linha individual não significa falta. Atividade parlamentar e registro de presença não contam como voto.</p>' : ''}
    ${senate && profileSenateSource('presenca')?.status !== 'imported' ? `<p class="muted">${registeredPresence ? 'Cobertura parcial de presença' : 'Presença indisponível para este perfil'}; veja Fontes e datas.</p>` : ''}
    ${presence && averagePresence !== null ? `<span class="fchip citizen-verdict">${presencePercent === averagePresence ? 'Perto da média' : presencePercent > averagePresence ? 'Acima da média' : 'Abaixo da média'}</span>` : ''}
  </section>`;
}
function profileAlertAnswer(alerts, hasExpenseData) {
  const ranks = { alto: 3, medio: 2, info: 1 };
  const top = [...alerts].sort((a, b) => (ranks[b.nivel] || 0) - (ranks[a.nivel] || 0))[0];
  return `<section class="card citizen-answer citizen-answer-alert" data-profile-answer="alerts">
    <h2 class="h">Algum gasto incomum?</h2>
    ${top ? `<span class="fchip citizen-alert-count">${alerts.length} ${alerts.length === 1 ? 'alerta' : 'alertas'}</span>
      <h3 class="citizen-title">${esc(top.titulo)}</h3>${alertVisualization(top)}<p class="citizen-statement">${esc(top.frase)}</p>${top.contexto?.frase ? `<p class="citizen-context">${esc(top.contexto.frase)}</p>` : ''}
      <button type="button" class="more" data-profile-open="alerts">${alerts.length > 1 ? `Ver os demais alertas (${alerts.length - 1})` : 'Ver alerta em detalhe'} →</button>`
    : `<p class="citizen-empty">${hasExpenseData ? 'Nenhum gasto incomum pelas regras do painel' : 'Sem dados de cota para checar alertas.'}</p>`}
  </section>`;
}
const PROFILE_VOTE_LIMIT = new Map();
function profileVoteDetails(shared) {
  const senate = shared.person.role === 'senador';
  if (senate) profileSenateEnsure();
  if (senate && profileSenateLoading()) return skel('linhas', 3);
  const votes = votesForPerson(shared.id), presence = shared.presence, limit = PROFILE_VOTE_LIMIT.get(shared.id) || 20;
  const source = senate ? profileSenateSource('votacoes') : null;
  return `<span class="k">${senate ? 'Votações nominais do Senado · 2026' : 'Votações selecionadas do Placar'} · ${votes.length || 'sem registros'}</span>
    ${votes.length ? `<div class="votes">${votes.slice(0, limit).map(({ vote, recordedVote }) => {
      const voteLabel = recordedVote == null ? 'Sem registro importado' : vote.secreta ? 'Presença registrada · voto secreto' : senate && recordedVote === 'Presente' ? 'Presença registrada · sem voto' : String(recordedVote).toLowerCase();
      return profileVoteButton(vote, `<b>${esc(voteLabel)}</b><span>${esc(vote.titulo)}</span>${senate ? `<small>${esc(vote.data?.slice(0, 10) || '')} · fonte oficial ↗</small>` : ''}`);
    }).join('')}</div>` : `<p class="muted">${senate ? 'Votos nominais do Senado ainda não disponíveis neste recorte.' : 'Nenhuma votação selecionada do Placar em 2026.'}</p>`}
    ${votes.length > limit ? `<button type="button" class="more" data-profile-votes-more="${esc(shared.id)}">Mostrar mais votações (${votes.length - limit})</button>` : ''}
    <p class="muted">O resumo conta votos identificados na fonte. ${senate ? 'Presença sem voto, atividade parlamentar, licenças e presidência não contam como voto nominal.' : 'Presença em voto secreto e quem presidiu aparecem à parte.'} Ausência de registro não significa que a pessoa não votou.</p>
    ${source ? `${profileSource(source, 'Fonte das votações do Senado')}${source.detail ? `<p class="muted">${esc(source.detail)}</p>` : ''}` : ''}
    ${presence?.motivos?.length ? `<p class="note">Justificativas de presença: ${presence.motivos.map(([reason, count]) => `${esc(reason.toLowerCase())} (${count})`).join(', ')}.</p>` : ''}
    ${senate ? '' : '<button type="button" class="more" data-go="attendance">Ver a presença de todos(as)</button>'}`;
}
function profileExpenseDetails(f, hasExpenseData) {
  if (!hasExpenseData) return '<p class="muted">Não há lançamentos observados para calcular total, média, série mensal ou alertas.</p>';
  const maxMonth = Math.max(1, ...f.meses.map(month => month.valor));
  const categoryTotal = f.categorias.reduce((sum, category) => sum + category.valor, 0) || 1;
  const monthNames = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const observedMonths = f.meses.filter(month => Number.isInteger(month.month) && month.month >= 1 && month.month <= 12)
    .map(month => monthNames[month.month]);
  const complement = f.complementoMoradia;
  return `<section class="citizen-detail-part citizen-expense-original"><h3 class="k">Cota parlamentar · total de 2026</h3>
    <p><b>Total da cota em 2026:</b> ${brl(f.total, 2)}, somando todas as notas publicadas até agora.</p>
    ${observedMonths.length ? `<p class="muted">Meses com notas: ${esc([...new Set(observedMonths)].join(', '))}.</p>` : ''}
    ${complement && Number.isFinite(complement.valor) ? `<p class="muted">À parte: complemento do auxílio-moradia lançado na cota, ${brl(complement.valor, 2)} em ${complement.notas} ${complement.notas === 1 ? 'nota' : 'notas'}. A Câmara publica esse valor como negativo; ele não reduz o total acima.</p>` : ''}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Mês a mês</h3>
    <div class="citizen-months">${f.meses.map(month => `<div><small>${Math.round(month.valor / 1e3)}k</small><b class="mt"><i style="height:${month.valor > 0 ? Math.max(2, month.valor / maxMonth * 100) : 0}%" class="${f.alertas.some(alert => alert.tipo === 'pico' && alert.mes === month.month) ? 'hot' : ''}"></i></b><span>${SHORT_MONTHS[month.month]}</span></div>`).join('')}</div>
    <p class="muted">Os últimos meses ainda podem crescer: as notas são publicadas com atraso.</p>
  </section>
  <section class="citizen-detail-part"><h3 class="k">Com o que gastou</h3>
    ${f.categorias.slice(0, 6).map(category => `<div class="citizen-bar"><div><span>${esc(category.nome)}</span><b class="mono">${category.valor === 0 ? 'R$ 0' : formatCitizenAmount(category.valor)}</b></div><div class="bar"><i style="width:${f.categorias[0].valor ? category.valor / f.categorias[0].valor * 100 : 0}%"></i></div><small class="muted">${Math.round(category.valor / categoryTotal * 100)}% do total</small></div>`).join('')}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Para quem foi o dinheiro</h3>
    ${f.fornecedores.map(x => `<div class="citizen-bar"><div><span>${esc(citizenName(x.name))}</span><b class="mono">${formatCitizenAmount(x.valor)}</b></div><div class="bar"><i style="width:${f.total ? x.valor / f.total * 100 : 0}%;background:${f.total && x.valor / f.total >= 0.5 ? 'var(--warn)' : 'var(--accent)'}"></i></div><small class="muted">${f.total ? Math.round(x.valor / f.total * 100) : 0}% do total · ${x.notas} ${x.notas === 1 ? 'nota' : 'notas'}</small></div>`).join('')}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Maiores notas do ano</h3>
    ${f.maiores.map(m => `<${m.documentUrl ? `a href="${esc(m.documentUrl)}" target="_blank" rel="noopener"` : 'div'} class="item"><span class="mono muted" style="width:52px">${SHORT_MONTHS[m.month]}/${String(m.year).slice(2)}</span><span class="g"><span>${esc(citizenName(m.fornecedor || 'Fornecedor não informado'))}</span><span class="muted">${esc(m.categoria)}${m.documentUrl ? ' · ver nota ↗' : ''}</span></span><span class="mono" style="font-weight:700">${brl(m.valor)}</span></${m.documentUrl ? 'a' : 'div'}>`).join('')}
  </section>`;
}
function profileView() {
  const id = state.politicianId;
  loadProfile(id);
  const back = '<button type="button" class="back" data-back>‹ Voltar</button>';
  if (citizenState.profileError) return back + `<section class="card"><p>Não deu para abrir esta ficha.</p><p class="muted">${esc(citizenState.profileError)}</p></section>`;
  const f = citizenState.profile;
  if (!f) return back + skel('ficha-respostas');
  const shared = profileData(f.pessoa || id), person = shared.person, election = profileElection(shared);
  const hasExpenseData = f.hasExpenseData === undefined ? f.total != null : Boolean(f.hasExpenseData);
  // Sem composição do custo (ficha fora do recorte), a ficha mantém o cartão da cota.
  const costAnswer = person.role === 'deputado' && shared.cost
    ? profileCostAnswer(shared.cost) : profileExpenseAnswer(f, person, hasExpenseData);
  const alerts = f.alertas || [], isChamberPerson = person.role === 'deputado';
  const personNumber = String(person.id).split(':')[1];
  const presenceUrl = isChamberPerson && /^\d+$/.test(personNumber || '') ? `https://www.camara.leg.br/deputados/${personNumber}/presenca-plenario/2026` : null;
  const sourcesHtml = `<p>Cota é reembolso de gastos com o trabalho: escritório, divulgação, carro e viagens.</p>
    <p class="src">Fonte: notas da cota publicadas ${isChamberPerson ? 'pela Câmara (sem as passagens aéreas, que ficam fora do arquivo aberto)' : 'pelo Senado'}. Retrato de ${f.snapshotAt ? esc(f.snapshotAt.slice(0, 10)) : 'data não informada'}.</p>
    ${isChamberPerson ? `<p class="muted">Presença em sessões deliberativas de 2026. Média da Câmara: média das proporções individuais entre registros válidos. O selo compara os percentuais arredondados. Os dias observados podem variar entre mandatos.</p>
    ${presenceUrl ? `<a class="src" href="${esc(presenceUrl)}" target="_blank" rel="noopener">Fonte da presença no Plenário ↗</a>` : ''}
    <p class="muted">Os votos cobrem apenas a seleção do Placar em 2026. Cada votação abre seu resumo e fontes oficiais.</p>` : ''}
    ${!isChamberPerson ? ['presenca', 'votacoes'].map(key => { const source = profileSenateSource(key); return source ? `<p><b>${key === 'presenca' ? 'Presença' : 'Votações'} do Senado</b></p>${profileSource(source)}<p class="muted">${esc(source.detail || '')}</p>` : ''; }).join('') : ''}
    ${!isChamberPerson ? profileAttendanceSources(shared.id) : ''}
    <p class="muted">Alertas indicam registros para conferir, não conclusões de irregularidade. “Parecido com a média” mantém a faixa de diferença inferior a 10% na cota.</p>
    ${citizenSourceUrl(person) ? `<a class="fchip" href="${esc(citizenSourceUrl(person))}" target="_blank" rel="noopener">Página oficial ↗</a>` : ''}
    ${hasExpenseData ? `<a class="fchip" href="${esc('/api/c/gastos.csv?id=' + encodeURIComponent(person.id))}" download>Baixar todas as notas (CSV)</a>` : ''}`;
  return `${back}
    <div class="citizen-profile-head"><div class="profile">${citizenAvatar(person, 64)}<div><h1 class="n">${esc(citizenName(person.name))}</h1><span class="muted">${citizenRoleDescription(person)}</span>${election?.summary ? `<span class="pill citizen-election" data-tone="${esc(election.tone)}"><i></i>${esc(election.summary)}</span>` : ''}</div></div>
      <button type="button" class="fchip" data-cmp-start="${esc(shared.id)}">Comparar com outro(a) →</button></div>
    <span class="k citizen-answer-label">Em 3 respostas</span>
    <div class="citizen-answers">${costAnswer}${profileWorkAnswer(shared)}${profileAlertAnswer(alerts, hasExpenseData)}</div>
    <h2 class="h">Ver mais</h2>
    ${profileSectionsHTML(person, {
      expenses: (person.role === 'deputado' ? profileCostDetails(shared.cost) : '') + profileExpenseDetails(f, hasExpenseData),
      alerts: alerts.length ? alerts.map(alert => alertCard(alert, { semPessoa: true })).join('') : `<p class="muted">${hasExpenseData ? 'Nenhum gasto incomum pelas regras do painel: nenhum mês muito acima do habitual e nenhum fornecedor com metade do dinheiro.' : 'Sem dados de cota para checar alertas.'}</p>`,
      votes: profileVoteDetails(shared), sources: sourcesHtml,
    })}`;
}

/* ---------- Eventos ---------- */
function openPolitician(id) {
  const canonical = String(id || '').includes(':') ? String(id) : 'camara:' + String(id || '');
  state.politicianId = canonical;
  state.deputyId = citizenLocalId(canonical);
  navigateToView('profile');
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-profile-votes-more],[data-profile-toggle],[data-profile-open],[data-politician],[data-home-retry],[data-alert-type],[data-alert-role],[data-alert-more],[data-alert-retry],[data-politician-role],[data-politician-order],[data-politician-more],[data-politician-retry]');
  if (!t) return;
  if (t.dataset.profileVotesMore) { PROFILE_VOTE_LIMIT.set(t.dataset.profileVotesMore, (PROFILE_VOTE_LIMIT.get(t.dataset.profileVotesMore) || 20) + 20); return rerender(); }
  if (t.dataset.profileToggle) { profileToggle(t); return; }
  if (t.dataset.profileOpen) {
    const button = document.querySelector(`[data-profile-toggle="${t.dataset.profileOpen}"]`);
    if (button) { profileToggle(button, true); button.focus(); button.scrollIntoView({ block: 'start', behavior: 'instant' }); }
    return;
  }
  if (t.dataset.politician) { e.preventDefault(); openPolitician(t.dataset.politician); return; }
  if (t.hasAttribute('data-home-retry')) { const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor'; citizenState.cache.delete(path); citizenState.pending.delete(path); return rerender(); }
  const l = citizenState.alerts, p = citizenState.politicians;
  if (t.dataset.alertType !== undefined) { l.type = t.dataset.alertType; return rerender(); }
  if (t.dataset.alertRole !== undefined) { l.role = t.dataset.alertRole; return rerender(); }
  if (t.hasAttribute('data-alert-more')) { l.page += 1; loadAlerts(true); return rerender(); }
  if (t.hasAttribute('data-alert-retry')) { l.key = ''; citizenState.cache.clear(); return rerender(); }
  if (t.dataset.politicianRole !== undefined) { p.role = t.dataset.politicianRole; return rerender(); }
  if (t.dataset.politicianOrder !== undefined) { p.order = t.dataset.politicianOrder; return rerender(); }
  if (t.hasAttribute('data-politician-more')) { p.page += 1; loadPoliticians(true); renderPoliticianList(); return; }
  if (t.hasAttribute('data-politician-retry')) { p.key = ''; citizenState.cache.clear(); return rerender(); }
});
let citizenSearchTimer = null;
document.addEventListener('input', e => {
  if (e.target.id !== 'citizen-search') return;
  clearTimeout(citizenSearchTimer);
  citizenState.politicians.query = e.target.value.trim();
  citizenSearchTimer = setTimeout(() => { loadPoliticians(false); renderPoliticianList(); }, 250);
});
// Atualiza apenas os padrões responsivos; escolhas feitas nos acordeões são preservadas.
if (typeof matchMedia === 'function') {
  matchMedia('(min-width: 900px)').addEventListener('change', profileRefreshAccordions);
}
