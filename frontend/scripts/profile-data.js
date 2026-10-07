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
function profilePresenceRows() {
  return (DATA.presencaTodos || []).filter(p => Number.isFinite(p.dias) && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
}
function profilePresence(id) {
  const canonical = profileId(id);
  return canonical.startsWith('camara:') ? profilePresenceRows().find(p => String(p.id) === canonical.slice(7)) || null : null;
}
function profileVoteRows(v) {
  const raw = DATA.votosCompletos?.[v.id];
  if (!Array.isArray(raw)) return [];
  // Only source rows establish participation. The current roster cannot tell
  // whether an absent row voted, was eligible, or had already taken office.
  return raw.filter(r => Array.isArray(r) && r.length >= 5 && r[0] != null).map(r => [
    r[0], r[1], r[2], r[3], v.secreta ? 'Presente' : (r[4] === 'Artigo 17' ? 'Presidiu' : r[4] || 'Presente'),
  ]);
}
function profileVotes(id) {
  const canonical = profileId(id);
  if (!canonical.startsWith('camara:')) return [];
  const num = canonical.slice(7);
  return (DATA.votacoes || []).map(v => ({ v, voto: profileVoteRows(v).find(r => String(r[0]) === num)?.[4] ?? null }));
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
  const pessoa = { id, name: snapshot.name, party: snapshot.party, uf: snapshot.uf, ...supplied,
    sourceUrl: supplied.sourceUrl || snapshot.sourceUrl, fetchedAt: supplied.fetchedAt || snapshot.fetchedAt, role };
  return { id, pessoa, contato: snapshot.contato || null, projetos: snapshot.projetos || null,
    gabinete: snapshot.gabinete || null, mandato: snapshot.mandato || null,
    loading: PROFILE_LOAD.pending.has(id),
    presenca: profilePresence(id), votos: profileVotes(id),
    remuneracao: PROFILE_SALARY[role] ? { ...PROFILE_SALARY[role], individual: null } : null };
}
function profileSource(section, label = 'Conferir na fonte', dateLabel = 'Fotografia') {
  const url = profileSafeUrl(section?.sourceUrl);
  const date = typeof section?.fetchedAt === 'string' ? section.fetchedAt.slice(0, 10) : null;
  if (!url && !date && !section?.period) return '';
  return `<span class="src">${section?.period ? `${esc(section.period)}. ` : ''}${date ? `${esc(dateLabel)}: ${esc(date)}. ` : ''}
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
  return `<section class="card cid-detail" data-profile-section="${esc(section)}">
    <h3 class="cid-detail-heading"><button type="button" class="cid-detail-toggle" data-profile-toggle="${esc(section)}" data-profile-id="${esc(profile)}" data-profile-desktop-open="${!!desktopOpen}" data-profile-mobile-open="${!!mobileOpen}" aria-expanded="${open}" aria-controls="${esc(bodyId)}">${esc(title)}</button></h3>
    <div class="cid-detail-body" id="${esc(bodyId)}"${open ? '' : ' hidden'}>${content}</div>
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
  document.querySelectorAll('.cid-detail-toggle[data-profile-toggle][data-profile-id]').forEach(button => {
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
  const p = profileData(value);
  if (!['deputado', 'senador'].includes(p.pessoa.role)) return '';
  const money = v => Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const c = p.contato, salary = p.remuneracao, office = p.gabinete, mandate = p.mandato, person = p.pessoa;
  const hasOffice = Number.isFinite(office?.amount);
  const months = Object.keys(office?.months || {}).map(Number).filter(n => n >= 1 && n <= 12).sort((a, b) => a - b);
  const monthNames = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const contact = [
    ['E-mail institucional', c?.email],
    ['Telefone do gabinete', (c?.telefones || []).filter(Boolean).join(' · ') || null],
    ['Endereço do gabinete', c?.endereco],
  ];
  const networks = (c?.redes || []).filter(r => profileSafeUrl(r.url));
  const projects = p.projetos, items = projects?.items || [];
  const total = projects?.status === 'imported' && Number.isInteger(projects.total) ? projects.total : null;
  const loading = () => typeof skel === 'function' ? skel('linhas', 3) : '<p class="muted">Carregando complemento…</p>';
  const slot = key => typeof slots?.[key] === 'string' && slots[key].trim() ? slots[key] : null;
  const projectContent = p.loading ? loading() : `<p>${total !== null ? `${total} ${total === 1 ? 'projeto no recorte consultado' : 'projetos no recorte consultado'}.`
      : items.length ? `${items.length} projetos disponíveis neste recorte parcial.` : 'Projetos ainda não importados para este perfil.'}</p>
    ${projects?.detail ? `<p class="muted">${esc(projects.detail)}</p>` : ''}
    ${items.length ? `<div>${items.map(item => {
      const url = profileSafeUrl(item.url);
      const content = `<b>${esc(item.titulo || 'Projeto sem título informado')}</b><span class="e">${esc(item.ementa || 'Ementa não informada')}</span><span class="st">${esc(item.situacao || 'Situação não importada')}</span>`;
      return url ? `<a class="proj" href="${esc(url)}" target="_blank" rel="noopener">${content}</a>` : `<div class="proj">${content}</div>`;
    }).join('')}</div>` : ''}
    ${profileSource(projects)}`;
  const officeContent = p.loading ? loading() : `${hasOffice ? `<div><span class="big">${money(office.amount)}</span><span class="muted"> · gasto publicado no recorte</span></div>`
      : '<p class="muted">Gastos com a equipe ainda não importados para este perfil. Ausência de dado não significa gasto zero.</p>'}
    ${Number.isFinite(office?.staffActive) ? `<p>${esc(office.staffActive)} pessoas ativas na fotografia da fonte.</p>` : '<p class="muted">Quantidade de assessores não importada.</p>'}
    ${months.length ? `<p class="muted">Meses informados: ${months.map(m => monthNames[m]).join(', ')}.</p>` : ''}
    ${office?.sourceUpdatedAt ? `<p class="muted">Gastos atualizados pela fonte em ${esc(office.sourceUpdatedAt)}.</p>` : ''}
    ${office?.detail ? `<p class="muted">${esc(office.detail)}</p>` : ''}${profileSource(office)}`;
  const contactContent = p.loading ? loading() : `${contact.map(([label, text]) => `<div class="contact"><span class="muted">${label}</span><span class="cv">${esc(text || 'Não informado no recorte')}</span>
      ${text && label !== 'Endereço do gabinete' ? `<button type="button" class="fchip" data-copy="${esc(text)}">Copiar</button>` : ''}</div>`).join('')}
    ${networks.length ? `<div class="chips">${networks.map(r => `<a class="fchip" href="${esc(profileSafeUrl(r.url))}" target="_blank" rel="noopener">${esc(r.nome || 'Rede social')} ↗</a>`).join('')}</div>` : ''}
    ${c?.detail ? `<p class="muted">${esc(c.detail)}</p>` : ''}${profileSource(c)}`;
  const senateParticipation = mandate?.participacao || person.position;
  const senateExercise = mandate?.exercicio || person.employmentStatus;
  const senateMandateContent = p.loading && !senateParticipation && !senateExercise ? loading() : `${senateParticipation || senateExercise ? '<span class="k">Na fotografia da fonte</span>' : ''}
    <p>${senateParticipation ? `<b>Participação no mandato:</b> ${esc(senateParticipation)}` : 'Participação no mandato sem informação importada.'}</p>
    <p>${senateExercise ? `<b>Situação publicada:</b> ${esc(senateExercise)}` : 'Situação publicada sem informação importada.'}</p>
    ${mandate?.detail ? `<p class="muted">${esc(mandate.detail)}</p>` : ''}
    ${profileSource({ ...mandate, sourceUrl: mandate?.sourceUrl || person.sourceUrl, fetchedAt: mandate?.fetchedAt || person.fetchedAt }, 'Fonte do Senado')}`;
  const hasMandateSource = mandate?.sourceUrl || person.sourceUrl || mandate?.participacao || mandate?.exercicio || mandate?.detail;
  const mandateSource = hasMandateSource ? `<article class="cid-source"><b>${p.pessoa.role === 'deputado' ? 'Na fotografia da fonte' : 'Mandato e situação'}</b>
      ${p.pessoa.role === 'deputado' && mandate?.participacao ? `<p><b>Condição eleitoral:</b> ${esc(mandate.participacao)}</p>` : ''}
      ${p.pessoa.role === 'deputado' && mandate?.exercicio ? `<p><b>Situação publicada:</b> ${esc(mandate.exercicio)}</p>` : ''}
      ${p.pessoa.role === 'deputado' && mandate?.detail ? `<p class="muted">${esc(mandate.detail)}</p>` : ''}
      ${profileSource({ ...mandate, sourceUrl: mandate?.sourceUrl || person.sourceUrl, fetchedAt: mandate?.fetchedAt || person.fetchedAt }, p.pessoa.role === 'senador' ? 'Fonte do Senado' : 'Fonte do mandato')}</article>` : '';
  const salarySource = salary ? `<article class="cid-source"><b>Subsídio parlamentar</b>
    <p><span class="big">${money(salary.amount)}</span> · subsídio bruto mensal de referência do cargo.</p>
    <p class="muted">Valor previsto desde ${esc(salary.since)}. Fonte conferida em ${esc(salary.checkedAt)}. Pagamento individual, descontos e outras verbas não foram importados nesta ficha.</p>
    ${profileSource({ sourceUrl: salary.sourceUrl, fetchedAt: salary.checkedAt, period: `${money(salary.amount)} mensais desde ${salary.since}` }, 'Fonte do subsídio', 'Fonte consultada')}</article>` : '<p class="muted">Sem remuneração importada.</p>';
  const sourcesContent = `${salarySource}
    ${mandateSource}
    ${p.loading ? loading() : `<div class="cid-source-list">
      <article class="cid-source"><b>Contato e gabinete</b>${c?.detail ? `<p class="muted">${esc(c.detail)}</p>` : ''}${profileSource(c, 'Fonte do contato')}</article>
      <article class="cid-source"><b>Projetos apresentados</b>${projects?.detail ? `<p class="muted">${esc(projects.detail)}</p>` : ''}${profileSource(projects, 'Fonte dos projetos')}</article>
      <article class="cid-source"><b>Equipe e verba de gabinete</b>${office?.detail ? `<p class="muted">${esc(office.detail)}</p>` : ''}${profileSource(office, 'Fonte do gabinete')}</article>
    </div>`}
    ${typeof slots?.fontes === 'string' ? slots.fontes : ''}`;
  const sections = [
    ['gastos', 'Gastos em detalhe', slot('gastos'), { desktopOpen: true, mobileOpen: true }],
    ['alertas', 'Alertas em detalhe', slot('alertas'), {}],
    ['votos', 'Como votou', slot('votos'), { desktopOpen: true }],
    ['projetos', 'Projetos apresentados', projectContent, {}],
    ['equipe', 'Equipe e verba de gabinete', officeContent, {}],
    ['contato', 'Fale com ele', contactContent, {}],
    ...(p.pessoa.role === 'senador' ? [['mandato', 'Mandato', senateMandateContent, {}]] : []),
    ['fontes', 'Fontes e datas', sourcesContent, {}],
  ];
  return `<div class="cid-details">${sections.filter(([, , content]) => content !== null && content !== undefined)
    .map(([key, title, content, options]) => profileAccordionHTML(p.id, key, title, content, options)).join('')}</div>`;
}
