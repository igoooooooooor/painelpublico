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
  const pessoa = { id, name: snapshot.name, party: snapshot.party, uf: snapshot.uf, ...supplied, role };
  return { id, pessoa, contato: snapshot.contato || null, projetos: snapshot.projetos || null,
    gabinete: snapshot.gabinete || null, mandato: snapshot.mandato || null,
    loading: PROFILE_LOAD.pending.has(id),
    presenca: profilePresence(id), votos: profileVotes(id),
    remuneracao: PROFILE_SALARY[role] ? { ...PROFILE_SALARY[role], individual: null } : null };
}
function profileSource(section, label = 'Conferir na fonte') {
  const url = profileSafeUrl(section?.sourceUrl);
  const date = typeof section?.fetchedAt === 'string' ? section.fetchedAt.slice(0, 10) : null;
  return `<span class="src">${section?.period ? `${esc(section.period)}. ` : ''}${date ? `Fotografia: ${esc(date)}. ` : ''}
    ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : ''}</span>`;
}
function profileSectionsHTML(value) {
  const p = profileData(value);
  if (!['deputado', 'senador'].includes(p.pessoa.role)) return '';
  if (p.loading) return typeof skel === 'function' ? skel('cards', 2) : '';
  const money = v => Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const c = p.contato, salary = p.remuneracao, office = p.gabinete, mandate = p.mandato;
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
  return `${p.pessoa.role === 'deputado' && (mandate?.participacao || mandate?.exercicio) ? `<section class="card"><span class="k">Na fotografia da fonte</span>
    ${mandate.participacao ? `<p><b>Condição eleitoral:</b> ${esc(mandate.participacao)}</p>` : ''}
    ${mandate.exercicio ? `<p><b>Situação publicada:</b> ${esc(mandate.exercicio)}</p>` : ''}
    ${profileSource(mandate)}
  </section>` : ''}<section class="card"><span class="k">Salário parlamentar</span>
    ${salary ? `<div><span class="big">${money(salary.amount)}</span><span class="muted"> · subsídio bruto mensal de referência do cargo</span></div>
      <p class="muted">Valor previsto desde 1º/2/2025. Pagamento individual, descontos e outras verbas não foram importados nesta ficha.</p>
      ${profileSource({ sourceUrl: salary.sourceUrl, fetchedAt: salary.checkedAt }, 'Fonte do subsídio')}` : '<p class="muted">Sem remuneração importada.</p>'}
  </section>
  <section class="card"><span class="k">Equipe e verba de gabinete</span>
    ${hasOffice ? `<div><span class="big">${money(office.amount)}</span><span class="muted"> · gasto publicado no recorte</span></div>`
      : '<p class="muted">Gastos com a equipe ainda não importados para este perfil. Ausência de dado não significa gasto zero.</p>'}
    ${Number.isFinite(office?.staffActive) ? `<p>${esc(office.staffActive)} pessoas ativas na fotografia da fonte.</p>` : '<p class="muted">Quantidade de assessores não importada.</p>'}
    ${months.length ? `<p class="muted">Meses informados: ${months.map(m => monthNames[m]).join(', ')}.</p>` : ''}
    ${office?.sourceUpdatedAt ? `<p class="muted">Gastos atualizados pela fonte em ${esc(office.sourceUpdatedAt)}.</p>` : ''}
    ${office?.detail ? `<p class="muted">${esc(office.detail)}</p>` : ''}${profileSource(office)}
  </section>
  <section class="card"><span class="k">Contato e gabinete</span>
    ${contact.map(([label, text]) => `<div class="contact"><span class="muted">${label}</span><span class="cv">${esc(text || 'Não informado no recorte')}</span>
      ${text && label !== 'Endereço do gabinete' ? `<button type="button" class="fchip" data-copy="${esc(text)}">Copiar</button>` : ''}</div>`).join('')}
    ${networks.length ? `<div class="chips">${networks.map(r => `<a class="fchip" href="${esc(profileSafeUrl(r.url))}" target="_blank" rel="noopener">${esc(r.nome || 'Rede social')} ↗</a>`).join('')}</div>` : ''}
    ${c?.detail ? `<p class="muted">${esc(c.detail)}</p>` : ''}${profileSource(c)}
  </section>
  <section class="card"><span class="k">Projetos apresentados</span>
    <p>${total !== null ? `${total} ${total === 1 ? 'projeto no recorte consultado' : 'projetos no recorte consultado'}.`
      : items.length ? `${items.length} projetos disponíveis neste recorte parcial.` : 'Projetos ainda não importados para este perfil.'}</p>
    ${projects?.detail ? `<p class="muted">${esc(projects.detail)}</p>` : ''}
    ${items.length ? `<details><summary>Ver projetos e situação publicada</summary><div>${items.map(item => {
      const url = profileSafeUrl(item.url);
      const content = `<b>${esc(item.titulo || 'Projeto sem título informado')}</b><span class="e">${esc(item.ementa || 'Ementa não informada')}</span><span class="st">${esc(item.situacao || 'Situação não importada')}</span>`;
      return url ? `<a class="proj" href="${esc(url)}" target="_blank" rel="noopener">${content}</a>` : `<div class="proj">${content}</div>`;
    }).join('')}</div></details>` : ''}
    ${profileSource(projects)}
  </section>`;
}
