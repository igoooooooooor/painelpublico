/* Leitura compartilhada das fichas. Dados ausentes permanecem ausentes.
   O snapshot complementar tem fontes/datas próprias; a cota continua vindo da API. */
const PROFILE_SALARY = {
  deputado: { amount: 46366.19, since: '2025-02-01', checkedAt: '2026-10-07',
    sourceUrl: 'https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/salario-de-deputados' },
  senador: { amount: 46366.19, since: '2025-02-01', checkedAt: '2026-10-07',
    sourceUrl: 'https://www12.senado.leg.br/perguntas-frequentes/perguntas-frequentes/canais-de-atendimento/transparencia-1' },
};

function profileId(value) {
  const id = String(value?.id ?? value ?? '');
  return /^\d+$/.test(id) ? 'camara:' + id : id;
}
function profileSafeUrl(value) {
  if (typeof value !== 'string') return null;
  try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; }
  catch { return null; }
}
const PROFILE_PROJECT_GROUPS = new Set(['lei', 'tramitando', 'arquivado', 'emenda']);
const PROFILE_PROJECT_GROUP_LABELS = {
  lei: 'Virou lei', tramitando: 'Tramitando', arquivado: 'Arquivado/rejeitado', emenda: 'Emenda constitucional',
};
const PROFILE_PROJECT_FILTERS = new Set(['todos', ...PROFILE_PROJECT_GROUPS, 'sem-situacao']);
const PROFILE_PROJECT_FILTER_STATE = new Map();
function profileProjectDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  return Number.isFinite(Date.parse(value)) ? dateBR(value) : null;
}
function profileProjectConsulted(item) {
  return !!profileProjectDate(item?.situacaoAtual?.consultadoEm);
}
function profileProjectGroup(item) {
  const situation = item?.situacaoAtual;
  if (!situation || situation.status !== 'imported' || !PROFILE_PROJECT_GROUPS.has(situation.grupo)
      || !profileProjectConsulted(item)) return null;
  return situation.grupo;
}
function profileProjectFilter(button) {
  const filter = button?.dataset?.projectFilter || button?.getAttribute?.('data-project-filter');
  const profile = button?.dataset?.projectProfile || button?.getAttribute?.('data-project-profile');
  const root = button?.closest?.('[data-project-filter-root]');
  if (!PROFILE_PROJECT_FILTERS.has(filter) || profile == null || !root
      || typeof root.querySelectorAll !== 'function') return false;
  PROFILE_PROJECT_FILTER_STATE.set(String(profile), filter);
  let visible = 0;
  root.querySelectorAll('[data-project-filter]').forEach(control => {
    const value = control.dataset?.projectFilter || control.getAttribute('data-project-filter');
    control.setAttribute('aria-pressed', String(value === filter));
  });
  root.querySelectorAll('[data-project-item]').forEach(item => {
    const group = item.dataset?.projectGroup || item.getAttribute('data-project-group') || 'sem-situacao';
    const show = filter === 'todos' || (filter === 'sem-situacao' ? group === 'sem-situacao' : group === filter);
    item.hidden = !show;
    if (show) visible += 1;
  });
  const empty = typeof root.querySelector === 'function' ? root.querySelector('[data-project-empty]') : null;
  if (empty) empty.hidden = visible > 0;
  return true;
}
if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('click', event => {
    const button = event.target?.closest?.('[data-project-filter]');
    if (button) profileProjectFilter(button);
  });
}
/* Atividade do Senado é carregada só nas fichas/comparações que precisam dela. */
const SENATE_LOAD = { pending: false, done: false, data: null, error: null };
function profileSenateEnsure() {
  if (!DATA.senado?.sobDemanda || SENATE_LOAD.pending || SENATE_LOAD.done || typeof fetch !== 'function') return;
  SENATE_LOAD.pending = true;
  fetch('/api/c/senado/atividade', { headers: { Accept: 'application/json' } })
    .then(r => { if (!r.ok) throw new Error('Atividade do Senado indisponível'); return r.json(); })
    .then(d => { SENATE_LOAD.data = d; })
    .catch(() => { SENATE_LOAD.error = 'Não foi possível carregar a atividade do Senado.'; })
    .finally(() => { SENATE_LOAD.pending = false; SENATE_LOAD.done = true; if (typeof rerender === 'function') rerender(); });
}
function profileSenateLoading() { return SENATE_LOAD.pending; }
function profileSenateSource(section) { return SENATE_LOAD.data?.[section] || null; }
function profileRegisteredPresenceRows() {
  profileSenateEnsure();
  const rows = profileSenateSource('presenca')?.items;
  return (Array.isArray(rows) ? rows : []).filter(p => /^senado:\d+$/.test(p.id)
    && Number.isInteger(p.presente) && p.presente > 0);
}
function profileRegisteredPresence(id) {
  return profileRegisteredPresenceRows().find(p => p.id === profileId(id)) || null;
}
function profileAttendanceSources(id) {
  const sessions = profileSenateSource('presenca')?.sessions;
  const records = (Array.isArray(sessions) ? sessions : []).filter(s => Array.isArray(s.presentIds)
    && s.presentIds.includes(profileId(id)) && profileSafeUrl(s.sourceUrl));
  if (!records.length) return '';
  return `<p class="muted">Sessões com presença registrada no Diário:</p><div class="chips">${records.map(s =>
    `<a class="fchip" href="${esc(profileSafeUrl(s.sourceUrl))}" target="_blank" rel="noopener">${esc(dateBR(s.date))} ↗</a>`).join('')}</div>`;
}
function profilePresenceRows(chamber = 'camara') {
  if (chamber === 'senado') profileSenateEnsure();
  const rows = chamber === 'senado' ? profileSenateSource('presenca')?.items : DATA.presencaTodos;
  return (Array.isArray(rows) ? rows : []).filter(p => Number.isFinite(p.dias) && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
}
function profilePresence(id) {
  const canonical = profileId(id), chamber = canonical.split(':')[0];
  if (!['camara', 'senado'].includes(chamber)) return null;
  return profilePresenceRows(chamber).find(p => (chamber === 'camara' ? profileId(p.id) : String(p.id)) === canonical) || null;
}
function profileVoteList(chamber = 'camara') {
  if (chamber === 'senado') profileSenateEnsure();
  const rows = chamber === 'senado' ? profileSenateSource('votacoes')?.items : DATA.votacoes;
  return Array.isArray(rows) ? rows.filter(v => chamber !== 'senado' || !v.secreta) : [];
}
function profileVoteRows(v) {
  const senate = String(v.id).startsWith('senado:');
  if (senate && v.secreta) return [];
  const raw = senate ? v.rows : DATA.votosCompletos?.[v.id];
  if (!Array.isArray(raw)) return [];
  // Apenas linhas da fonte comprovam participação; uma linha ausente continua ausente.
  return raw.filter(r => Array.isArray(r) && r.length >= 5 && r[0] != null).map(r => {
    let vote = r[4] || (senate ? null : 'Presente');
    if (senate && /^(P-NRV|Presente\s*[–-]\s*Não registrou voto)$/i.test(vote)) vote = 'Presente';
    if (senate && /^(AP|Atividade parlamentar)$/i.test(vote)) vote = 'Atividade parlamentar';
    if (vote === 'Artigo 17' || (senate && /^Presidente\b/i.test(vote))) vote = 'Presidiu';
    return [r[0], r[1], r[2], r[3], v.secreta && (!senate || vote === 'Votou') ? 'Presente' : vote];
  });
}
function profileVotes(id) {
  const canonical = profileId(id), chamber = canonical.split(':')[0];
  if (!['camara', 'senado'].includes(chamber)) return [];
  return profileVoteList(chamber).map(vote => ({ vote, recordedVote: profileVoteRows(vote)
    .find(row => (chamber === 'camara' ? profileId(row[0]) : String(row[0])) === canonical)?.[4] ?? null }));
}
function profileVoteButton(v, content, className = 'vt') {
  if (!String(v.id).startsWith('senado:')) return `<button type="button" class="${esc(className)}" data-vote="${esc(v.id)}">${content}</button>`;
  const url = profileSafeUrl(v.sourceUrl);
  return url ? `<a class="${esc(className)}" href="${esc(url)}" target="_blank" rel="noopener">${content}</a>` : `<div class="${esc(className)}">${content}</div>`;
}
/* Perfis complementares chegam um a um pela API (antes iam todos dentro da página, ~14 MB). */
const PROFILE_LOAD = { pending: new Set(), done: new Set() };
function profileEnsure(id) {
  if (!DATA.perfis) DATA.perfis = { profiles: {} };
  const stored = DATA.perfis.profiles || (DATA.perfis.profiles = {});
  if (id in stored || PROFILE_LOAD.pending.has(id) || PROFILE_LOAD.done.has(id)) return;
  // Só busca se o build encontrou perfis.json; sem o snapshot, a ficha mostra os dados como ausentes.
  if (!DATA.perfis.sobDemanda || typeof fetch !== 'function' || !/^(camara|senado):\d+$/.test(id)) return;
  PROFILE_LOAD.pending.add(id);
  fetch('/api/c/perfil/' + encodeURIComponent(id), { headers: { Accept: 'application/json' } })
    .then(r => (r.ok ? r.json() : null)).then(d => { if (d) stored[id] = d; })
    .catch(() => {})
    .finally(() => { PROFILE_LOAD.pending.delete(id); PROFILE_LOAD.done.add(id); if (typeof rerender === 'function') rerender(); });
}
function profileData(value) {
  const id = profileId(value), supplied = typeof value === 'object' && value !== null ? value : {};
  profileEnsure(id);
  const snapshot = DATA.perfis?.profiles?.[id] || {};
  const role = supplied.role || snapshot.role || (id.startsWith('camara:') ? 'deputado' : id.startsWith('senado:') ? 'senador' : null);
  const person = { id, name: snapshot.name, party: snapshot.party, uf: snapshot.uf, ...supplied,
    sourceUrl: supplied.sourceUrl || snapshot.sourceUrl, fetchedAt: supplied.fetchedAt || snapshot.fetchedAt, role };
  return { id, person, contact: snapshot.contato || null, projects: snapshot.projetos || null,
    office: snapshot.gabinete || null, mandate: snapshot.mandato || null, election: snapshot.eleicao2026 || null,
    cost: snapshot.mandateCost || null, senateCost: snapshot.senateCost || null,
    loading: PROFILE_LOAD.pending.has(id), presence: profilePresence(id),
    registeredPresence: role === 'senador' ? profileRegisteredPresence(id) : null, votes: profileVotes(id),
    compensation: PROFILE_SALARY[role] ? { ...PROFILE_SALARY[role], individual: null } : null };
}
const PROFILE_ELECTION_ROLES = {
  'DEPUTADO FEDERAL': 'deputado(a) federal', 'DEPUTADO ESTADUAL': 'deputado(a) estadual', 'DEPUTADO DISTRITAL': 'deputado(a) distrital',
  SENADOR: 'senador(a)', GOVERNADOR: 'governador(a)', 'VICE-GOVERNADOR': 'vice-governador(a)', PRESIDENTE: 'presidente',
  'VICE-PRESIDENTE': 'vice-presidente', '1º SUPLENTE': '1º(ª) suplente de senador(a)', '2º SUPLENTE': '2º(ª) suplente de senador(a)',
};
const formatBrazilianDate = iso => typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${+iso.slice(8, 10)}/${+iso.slice(5, 7)}/${iso.slice(0, 4)}` : null;
/* Eleição de 2026 em linguagem simples. Só afirma algo quando a ficha foi ligada a uma única candidatura do TSE. */
function profileElection(profile) {
  const election = profile?.election;
  if (!election || typeof election !== 'object') return null;
  const base = { status: election.status, source: election.fonte || null, method: election.metodo || null, tone: 'neutral', summary: null };
  if (election.status !== 'encontrada') {
    return { ...base, sentence: election.status === 'sem-correspondencia'
      ? 'Não encontramos candidatura em 2026 com o nome civil e a data de nascimento desta pessoa nos dados do TSE.'
      : 'Não foi possível ligar esta ficha aos dados do TSE com segurança.' };
  }
  const roleLabel = PROFILE_ELECTION_ROLES[election.cargo] || String(election.cargo || 'cargo não informado').toLowerCase();
  const locationLabel = election.uf && election.uf !== 'BR' ? ` por ${election.uf}` : '';
  const role = profile.person?.role;
  const sameRole = (role === 'deputado' && election.cargo === 'DEPUTADO FEDERAL') || (role === 'senador' && election.cargo === 'SENADOR');
  const electionDate = formatBrazilianDate(election.dataEleicao);
  const resultCode = String(election.situacao || '');
  if (resultCode.startsWith('ELEITO')) {
    return { ...base, tone: 'ok', summary: sameRole ? 'Reeleito(a) em 2026' : `Eleito(a) ${roleLabel} em 2026`,
      sentence: `${sameRole ? 'Reeleito(a)' : 'Eleito(a)'} ${roleLabel}${locationLabel}${electionDate ? ` na eleição de ${electionDate}` : ' em 2026'}.` };
  }
  if (resultCode === '2º TURNO') {
    const secondRoundDate = formatBrazilianDate(election.segundoTurno);
    return { ...base, tone: 'info', summary: `2º turno para ${roleLabel}`, sentence: `Disputa o 2º turno para ${roleLabel}${locationLabel}${secondRoundDate ? ` em ${secondRoundDate}` : ''}.` };
  }
  if (resultCode === 'SUPLENTE' || resultCode === 'NÃO ELEITO') {
    const resultLabel = resultCode === 'SUPLENTE' ? 'ficou como suplente' : 'não foi eleito(a)';
    return { ...base, summary: sameRole ? 'Não reeleito(a) em 2026' : `Não eleito(a) para ${roleLabel}`,
      sentence: `${sameRole ? `Concorreu à reeleição para ${roleLabel}` : `Concorreu a ${roleLabel}`}${locationLabel} em 2026 e ${resultLabel}.` };
  }
  return { ...base, summary: `Candidato(a) a ${roleLabel} em 2026`, sentence: `Candidatura a ${roleLabel}${locationLabel} em 2026. O arquivo do TSE não traz resultado para ela.` };
}
function profileSource(section, label = 'Conferir na fonte', dateLabel = 'Fotografia') {
  const url = profileSafeUrl(section?.sourceUrl);
  const date = typeof section?.fetchedAt === 'string' ? dateBR(section.fetchedAt) : null;
  if (!url && !date && !section?.period) return '';
  return `<span class="src">${section?.period ? `${esc(datesInTextBR(section.period))}. ` : ''}${date ? `${esc(dateLabel)}: ${esc(date)}. ` : ''}
    ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : ''}</span>`;
}
const PROFILE_SECTION_STATE = new Map();
function profileAccordionHTML(id, key, title, content, { desktopOpen = false, mobileOpen = false } = {}) {
  const profile = String(id ?? '');
  const section = String(key ?? '');
  const stateKey = `${profile}\u0000${section}`;
  const desktop = typeof matchMedia === 'function' && matchMedia('(min-width: 900px)').matches;
  const open = PROFILE_SECTION_STATE.has(stateKey) ? PROFILE_SECTION_STATE.get(stateKey) : (desktop ? !!desktopOpen : !!mobileOpen);
  const safeId = value => String(value).replace(/[^a-zA-Z0-9_-]/g, '-');
  const bodyId = `profile-section-${safeId(profile)}-${safeId(section)}`;
  return `<section class="card citizen-detail" data-profile-section="${esc(section)}">
    <h3 class="citizen-detail-heading"><button type="button" class="citizen-detail-toggle" data-profile-toggle="${esc(section)}" data-profile-id="${esc(profile)}" data-profile-desktop-open="${!!desktopOpen}" data-profile-mobile-open="${!!mobileOpen}" aria-expanded="${open}" aria-controls="${esc(bodyId)}">${esc(title)}</button></h3>
    <div class="citizen-detail-body" id="${esc(bodyId)}"${open ? '' : ' hidden'}>${content}</div>
  </section>`;
}
function profileToggle(button, forceOpen = false) {
  if (!button || typeof button.getAttribute !== 'function' || typeof button.setAttribute !== 'function') return false;
  const open = forceOpen ? true : button.getAttribute('aria-expanded') !== 'true';
  button.setAttribute('aria-expanded', String(open));
  const bodyId = button.getAttribute('aria-controls');
  const body = bodyId && typeof document !== 'undefined' ? document.getElementById(bodyId) : null;
  if (body) body.hidden = !open;
  const key = button.dataset?.profileToggle || button.getAttribute('data-profile-toggle');
  const profile = button.dataset?.profileId || button.getAttribute('data-profile-id');
  if (key && profile != null) PROFILE_SECTION_STATE.set(`${profile}\u0000${key}`, open);
  return open;
}
function profileRefreshAccordions() {
  if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return;
  const desktop = typeof matchMedia === 'function' && matchMedia('(min-width: 900px)').matches;
  document.querySelectorAll('.citizen-detail-toggle[data-profile-toggle][data-profile-id]').forEach(button => {
    const key = button.dataset?.profileToggle || button.getAttribute('data-profile-toggle');
    const profile = button.dataset?.profileId || button.getAttribute('data-profile-id');
    if (!key || profile == null || PROFILE_SECTION_STATE.has(`${profile}\u0000${key}`)) return;
    const open = (desktop ? button.getAttribute('data-profile-desktop-open') : button.getAttribute('data-profile-mobile-open')) === 'true';
    button.setAttribute('aria-expanded', String(open));
    const bodyId = button.getAttribute('aria-controls');
    const body = bodyId ? document.getElementById(bodyId) : null;
    if (body) body.hidden = !open;
  });
}
function profileSectionsHTML(value, slots = {}) {
  const profile = profileData(value);
  if (!['deputado', 'senador'].includes(profile.person.role)) return '';
  const money = v => Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const contactInfo = profile.contact, salary = profile.compensation, office = profile.office, mandate = profile.mandate, person = profile.person;
  const hasOffice = Number.isFinite(office?.amount);
  const months = Object.keys(office?.months || {}).map(Number).filter(n => n >= 1 && n <= 12).sort((a, b) => a - b);
  const monthNames = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const contactRows = [
    ['E-mail institucional', contactInfo?.email],
    ['Telefone do gabinete', (contactInfo?.telefones || []).filter(Boolean).join(' · ') || null],
    ['Endereço do gabinete', contactInfo?.endereco],
  ];
  const networks = (contactInfo?.redes || []).filter(network => profileSafeUrl(network.url));
  const projects = profile.projects, items = Array.isArray(projects?.items) ? projects.items.filter(item => item && typeof item === 'object') : [];
  const total = projects?.status === 'imported' && Number.isInteger(projects.total) && projects.total >= 0 ? projects.total : null;
  const projectCount = total !== null ? total : items.length ? items.length : null;
  const confirmedProjectGroups = items.map(profileProjectGroup);
  const confirmedProjectCount = confirmedProjectGroups.filter(Boolean).length;
  const consultedProjectCount = items.filter(profileProjectConsulted).length;
  const confirmedLawCount = confirmedProjectGroups.filter(group => group === 'lei').length;
  const confirmedAmendmentCount = confirmedProjectGroups.filter(group => group === 'emenda').length;
  const unclassifiedProjectCount = items.length - confirmedProjectCount;
  const projectTotalMatchesItems = total === null || total === items.length;
  const partialSituationCoverage = confirmedProjectCount > 0
    && (unclassifiedProjectCount > 0 || !projectTotalMatchesItems);
  const projectCountLabel = projectCount === null ? 'total não confirmado'
    : `${projectCount} ${projectCount === 1 ? 'projeto' : 'projetos'}`;
  const amendmentLabel = confirmedAmendmentCount
    ? ` · ${confirmedAmendmentCount} ${confirmedAmendmentCount === 1 ? 'emenda' : 'emendas'}` : '';
  const projectSituationLabel = partialSituationCoverage
    ? `${confirmedLawCount
      ? `${confirmedLawCount} ${confirmedLawCount === 1 ? 'lei confirmada' : 'leis confirmadas'} · situação parcial`
      : 'leis: consulta parcial'}${amendmentLabel}`
    : confirmedProjectCount
      ? `${confirmedLawCount} ${confirmedLawCount === 1 ? 'virou' : 'viraram'} lei${amendmentLabel}`
      : consultedProjectCount ? 'situação consultada · classificação não confirmada' : 'situação não consultada';
  const projectTitle = profile.loading ? 'Projetos apresentados · carregando'
    : `Projetos apresentados · ${projectCountLabel} · ${projectSituationLabel}`;
  const savedProjectFilter = PROFILE_PROJECT_FILTER_STATE.get(profile.id) || 'todos';
  const selectedProjectFilter = savedProjectFilter === 'emenda' && !confirmedAmendmentCount ? 'todos' : savedProjectFilter;
  if (selectedProjectFilter !== savedProjectFilter) PROFILE_PROJECT_FILTER_STATE.set(profile.id, selectedProjectFilter);
  const visibleProjects = items.filter(item => {
    const group = profileProjectGroup(item) || 'sem-situacao';
    return selectedProjectFilter === 'todos' || selectedProjectFilter === group;
  }).length;
  const loading = () => typeof skel === 'function' ? skel('linhas', 3) : '<p class="muted">Carregando complemento…</p>';
  const slot = key => typeof slots?.[key] === 'string' && slots[key].trim() ? slots[key] : null;
  const projectContent = profile.loading ? loading() : `<p>${total !== null ? `${total} ${total === 1 ? 'projeto no recorte consultado' : 'projetos no recorte consultado'}.`
      : items.length ? `${items.length} projetos disponíveis neste recorte parcial.` : projects?.status === 'partial' || projects?.status === 'unavailable' ? 'Consulta de projetos incompleta ou indisponível; total não confirmado.' : 'Projetos ainda não importados para este perfil.'}</p>
    ${items.length ? `<p class="muted citizen-project-coverage">${consultedProjectCount
      ? `Consulta registrada em ${consultedProjectCount} de ${items.length} projetos; grupo confirmado em ${confirmedProjectCount}; ${unclassifiedProjectCount} sem grupo confirmado${items.length - consultedProjectCount ? ` (${items.length - consultedProjectCount} sem consulta)` : ''}.`
      : `Nenhuma consulta de situação registrada: 0 de ${items.length} consultados; ${items.length} sem confirmação.`}${total !== null && !projectTotalMatchesItems ? ` A lista mostra ${items.length} ${items.length === 1 ? 'projeto' : 'projetos'} de ${total} no total; as situações contam apenas os itens listados.` : ''}</p>` : ''}
    ${confirmedAmendmentCount ? '<p class="muted citizen-project-explanation">PEC aprovada e promulgada é emenda constitucional; por isso não entra na contagem de leis.</p>' : ''}
    ${unclassifiedProjectCount ? '<p class="muted citizen-project-explanation">“Outras / sem classificação” reúne situações que não confirmam um dos resultados acima e projetos ainda sem consulta. A descrição da fonte permanece visível.</p>' : ''}
    ${projects?.detail ? `<p class="muted">${esc(datesInTextBR(projects.detail))}</p>` : ''}
    ${items.length ? `<div class="citizen-projects" data-project-filter-root data-project-profile="${esc(profile.id)}">
      <div class="citizen-project-filters" aria-label="Filtrar projetos por situação">
        ${[['todos', 'Todos'], ['lei', 'Viraram lei'], ['tramitando', 'Tramitando'], ['arquivado', 'Arquivados/rejeitados'],
          ...(confirmedAmendmentCount ? [['emenda', 'Emendas promulgadas']] : []), ['sem-situacao', 'Outras / sem classificação']].map(([filter, label]) =>
          `<button type="button" class="fchip" data-project-filter="${filter}" data-project-profile="${esc(profile.id)}" aria-pressed="${selectedProjectFilter === filter}">${label}</button>`).join('')}
      </div>
      <div class="citizen-project-list">${items.map(item => {
      const url = profileSafeUrl(item.url);
      const situation = item.situacaoAtual;
      const group = profileProjectGroup(item) || 'sem-situacao';
      const title = `<b>${esc(item.titulo || 'Projeto sem título informado')}</b><span class="e">${esc(item.ementa || 'Ementa não informada')}</span>`;
      const originalSituation = typeof situation?.descricao === 'string' && situation.descricao
        ? situation.descricao : typeof item.situacao === 'string' && item.situacao
          ? item.situacao : PROFILE_PROJECT_GROUP_LABELS[group] || 'Situação não confirmada';
      const status = `<span class="st${group === 'lei' ? ' lei' : ''}">${esc(originalSituation)}</span>`;
      const main = url ? `<a class="citizen-project-main" href="${esc(url)}" target="_blank" rel="noopener">${title}</a>` : `<div class="citizen-project-main">${title}</div>`;
      const consulted = profileProjectDate(situation?.consultadoEm);
      const source = profileSafeUrl(situation?.sourceUrl);
      const norms = Array.isArray(situation?.normas) ? situation.normas.map(norm => {
        const normUrl = profileSafeUrl(norm?.url);
        const label = [norm?.tipo, norm?.numero, norm?.ano].filter(value => value != null && String(value).trim()).map(esc).join(' ');
        return label ? normUrl ? `<a href="${esc(normUrl)}" target="_blank" rel="noopener">${label} ↗</a>` : `<span>${label}</span>` : '';
      }).filter(Boolean) : [];
      const meta = [consulted ? `<span>Consulta da situação: ${esc(consulted)}</span>` : '',
        source ? `<a href="${esc(source)}" target="_blank" rel="noopener">Fonte da situação ↗</a>` : '', ...norms].filter(Boolean).join(' · ');
      const detail = typeof situation?.detail === 'string' && situation.detail.trim()
        ? `<p class="citizen-project-detail muted">${esc(datesInTextBR(situation.detail))}</p>` : '';
      const show = selectedProjectFilter === 'todos' || selectedProjectFilter === group;
      return `<article class="proj" data-project-item data-project-group="${group}"${show ? '' : ' hidden'}>${main}${status}${meta ? `<div class="citizen-project-meta">${meta}</div>` : ''}${detail}</article>`;
    }).join('')}</div>
      <p class="muted citizen-project-empty" data-project-empty role="status" aria-live="polite"${visibleProjects ? ' hidden' : ''}>Nenhum projeto nesta situação neste recorte.</p>
    </div>` : ''}
    ${profileSource(projects)}`;
  const officeContent = profile.loading ? loading() : `${hasOffice ? `<div><span class="big">${money(office.amount)}</span><span class="muted"> · gasto publicado no recorte</span></div>`
      : '<p class="muted">Gastos com a equipe ainda não importados para este perfil. Ausência de dado não significa gasto zero.</p>'}
    ${Number.isFinite(office?.staffActive) ? `<p>${esc(office.staffActive)} pessoas ativas na fotografia da fonte.</p>` : '<p class="muted">Quantidade de assessores não importada.</p>'}
    ${months.length ? `<p class="muted">Meses informados: ${months.map(m => monthNames[m]).join(', ')}.</p>` : ''}
    ${office?.sourceUpdatedAt ? `<p class="muted">Gastos atualizados pela fonte em ${esc(dateBR(office.sourceUpdatedAt))}.</p>` : ''}
    ${office?.detail ? `<p class="muted">${esc(datesInTextBR(office.detail))}</p>` : ''}${profileSource(office)}`;
  const contactContent = profile.loading ? loading() : `${contactRows.map(([label, text]) => `<div class="contact"><span class="muted">${label}</span><span class="cv">${esc(text || 'Não informado no recorte')}</span>
      ${text && label !== 'Endereço do gabinete' ? `<button type="button" class="fchip" data-copy="${esc(text)}">Copiar</button>` : ''}</div>`).join('')}
    ${networks.length ? `<div class="chips">${networks.map(network => `<a class="fchip" href="${esc(profileSafeUrl(network.url))}" target="_blank" rel="noopener">${esc(network.nome || 'Rede social')} ↗</a>`).join('')}</div>` : ''}
    ${contactInfo?.detail ? `<p class="muted">${esc(datesInTextBR(contactInfo.detail))}</p>` : ''}${profileSource(contactInfo)}`;
  const senateParticipation = mandate?.participacao || person.position;
  const senateExercise = mandate?.exercicio || person.employmentStatus;
  const senateMandateContent = profile.loading && !senateParticipation && !senateExercise ? loading() : `${senateParticipation || senateExercise ? '<span class="k">Na fotografia da fonte</span>' : ''}
    <p>${senateParticipation ? `<b>Participação no mandato:</b> ${esc(senateParticipation)}` : 'Participação no mandato sem informação importada.'}</p>
    <p>${senateExercise ? `<b>Situação publicada:</b> ${esc(senateExercise)}` : 'Situação publicada sem informação importada.'}</p>
    ${mandate?.detail ? `<p class="muted">${esc(datesInTextBR(mandate.detail))}</p>` : ''}
    ${profileSource({ ...mandate, sourceUrl: mandate?.sourceUrl || person.sourceUrl, fetchedAt: mandate?.fetchedAt || person.fetchedAt }, 'Fonte do Senado')}`;
  const hasMandateSource = mandate?.sourceUrl || person.sourceUrl || mandate?.participacao || mandate?.exercicio || mandate?.detail;
  const mandateSource = hasMandateSource ? `<article class="citizen-source"><b>${profile.person.role === 'deputado' ? 'Na fotografia da fonte' : 'Mandato e situação'}</b>
      ${profile.person.role === 'deputado' && mandate?.participacao ? `<p><b>Condição eleitoral:</b> ${esc(mandate.participacao)}</p>` : ''}
      ${profile.person.role === 'deputado' && mandate?.exercicio ? `<p><b>Situação publicada:</b> ${esc(mandate.exercicio)}</p>` : ''}
      ${profile.person.role === 'deputado' && mandate?.detail ? `<p class="muted">${esc(datesInTextBR(mandate.detail))}</p>` : ''}
      ${profileSource({ ...mandate, sourceUrl: mandate?.sourceUrl || person.sourceUrl, fetchedAt: mandate?.fetchedAt || person.fetchedAt }, profile.person.role === 'senador' ? 'Fonte do Senado' : 'Fonte do mandato')}</article>` : '';
  const salarySource = salary ? `<article class="citizen-source"><b>Subsídio parlamentar</b>
    <p><span class="big">${money(salary.amount)}</span> · subsídio bruto mensal de referência do cargo.</p>
    <p class="muted">Valor previsto desde ${esc(dateBR(salary.since))}. Fonte conferida em ${esc(dateBR(salary.checkedAt))}. ${profile.cost || profile.senateCost ? 'Este é o valor de referência do cargo; o valor bruto pago mês a mês, pela folha da Casa, está em “Quanto custa?” e em “Gastos em detalhe”.' : 'Pagamento individual, descontos e outras verbas não foram importados nesta ficha.'}</p>
    ${profileSource({ sourceUrl: salary.sourceUrl, fetchedAt: salary.checkedAt, period: `${money(salary.amount)} mensais desde ${dateBR(salary.since)}` }, 'Fonte do subsídio', 'Fonte consultada')}</article>` : '<p class="muted">Sem remuneração importada.</p>';
  const election = profileElection(profile);
  const electionSource = election ? `<article class="citizen-source"><b>Eleição de 2026</b><p>${esc(election.sentence)}</p>
    ${profileSource({ sourceUrl: election.source?.sourceUrl, fetchedAt: election.source?.fetchedAt,
      period: election.source?.geradoNoTse ? `Arquivo gerado pelo TSE em ${election.source.geradoNoTse}` : null }, 'Fonte do TSE', 'Consulta')}
    ${election.method ? `<p class="muted">${esc(election.method)}</p>` : ''}</article>` : '';
  const sourcesContent = `${salarySource}
    ${mandateSource}
    ${electionSource}
    ${profile.loading ? loading() : `<div class="citizen-source-list">
      <article class="citizen-source"><b>Contato e gabinete</b>${contactInfo?.detail ? `<p class="muted">${esc(datesInTextBR(contactInfo.detail))}</p>` : ''}${profileSource(contactInfo, 'Fonte do contato')}</article>
      <article class="citizen-source"><b>Projetos apresentados</b>${projects?.detail ? `<p class="muted">${esc(datesInTextBR(projects.detail))}</p>` : ''}${profileSource(projects, 'Fonte dos projetos')}</article>
      <article class="citizen-source"><b>Equipe e verba de gabinete</b>${office?.detail ? `<p class="muted">${esc(datesInTextBR(office.detail))}</p>` : ''}${profileSource(office, 'Fonte do gabinete')}</article>
    </div>`}
    ${typeof slots?.sources === 'string' ? slots.sources : ''}`;
  const sections = [
    ['expenses', 'Gastos em detalhe', slot('expenses'), {}],
    ['alerts', 'Alertas em detalhe', slot('alerts'), {}],
    ['votes', 'Como votou', slot('votes'), {}],
    ['projects', projectTitle, projectContent, {}],
    ['staff', 'Equipe e verba de gabinete', officeContent, {}],
    ['contact', 'Fale com ele(a)', contactContent, {}],
    ...(profile.person.role === 'senador' ? [['mandate', 'Mandato', senateMandateContent, {}]] : []),
    ['sources', 'Fontes e datas', sourcesContent, {}],
  ];
  return `<div class="citizen-details">${sections.filter(([, , content]) => content !== null && content !== undefined)
    .map(([key, title, content, options]) => profileAccordionHTML(profile.id, key, title, content, options)).join('')}</div>`;
}
