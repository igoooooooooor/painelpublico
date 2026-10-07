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
function profileEditorial(id) {
  const canonical = profileId(id);
  return canonical.startsWith('camara:') ? (DATA.deputados || []).find(d => String(d.id) === canonical.slice(7)) || null : null;
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
function profileData(value) {
  const id = profileId(value), supplied = typeof value === 'object' && value !== null ? value : {};
  const snapshot = DATA.perfis?.profiles?.[id] || {};
  const editorial = profileEditorial(id);
  const role = supplied.role || snapshot.role || (id.startsWith('camara:') ? 'deputado' : id.startsWith('senado:') ? 'senador' : null);
  const pessoa = { id, name: snapshot.name || editorial?.nome, party: snapshot.party || editorial?.partido,
    uf: snapshot.uf || editorial?.uf, ...supplied, role };
  let contato = snapshot.contato || null;
  if (!contato && editorial?.contato) {
    const c = editorial.contato;
    contato = { email: c.email || null, telefones: c.telefone ? [c.telefone] : [],
      endereco: [c.endereco, c.cidade].filter(Boolean).join(' · '), redes: c.redes || [],
      sourceUrl: `https://www.camara.leg.br/deputados/${editorial.id}?ano=2026`,
      fetchedAt: DATA.geradoEm, status: 'partial', detail: 'Complemento da amostra editorial.' };
  }
  let projetos = snapshot.projetos || null;
  if ((!projetos || projetos.status === 'unavailable') && editorial?.projetos?.lista?.length) {
    projetos = { status: 'partial', period: 'Desde fevereiro de 2023 · amostra editorial', total: null,
      sourceUrl: `https://www.camara.leg.br/deputados/${editorial.id}?ano=2026`, fetchedAt: DATA.geradoEm,
      detail: 'Lista preservada da amostra editorial; não representa uma coleta atual completa.',
      items: editorial.projetos.lista.map(p => ({ id: p.id, titulo: p.t, ementa: p.e, situacao: p.s,
        url: `https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=${p.id}` })) };
  }
  const cost = editorial?.custo;
  const gabinete = snapshot.gabinete?.amount != null || snapshot.gabinete?.staffActive != null ? snapshot.gabinete
    : Number.isFinite(cost?.gabineteGasto) ? { status: 'partial', amount: cost.gabineteGasto, months: {},
      staffActive: cost.pessoal?.ativos ?? null, period: `${cost.gabineteMeses} meses no recorte editorial`,
      sourceUrl: `https://www.camara.leg.br/deputados/${editorial.id}?ano=2026`, fetchedAt: DATA.geradoEm,
      detail: 'Complemento da amostra editorial. Verba da equipe, separada do subsídio e dos reembolsos.' }
      : snapshot.gabinete || null;
  return { id, pessoa, contato, projetos, editorial, gabinete, mandato: snapshot.mandato || null,
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
