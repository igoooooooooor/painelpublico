/* Exploração das bases públicas de despesas e autoridades. A tela só resume o que a API disponibiliza. */
const PUBLIC_ROLE_OPTIONS = [
  ['deputado', 'Deputado(a) federal'], ['senador', 'Senador(a)'],
  ['presidente', 'Presidente da República'], ['ministro', 'Ministro(a) de Estado'],
  ['magistrado', 'Juiz(a) ou magistrado(a)'], ['servidor', 'Servidor(a) público(a)'],
  ['governador', 'Governador(a)'], ['prefeito', 'Prefeito(a)'], ['vereador', 'Vereador(a)'],
  ['deputado_estadual', 'Deputado(a) estadual'], ['conta_institucional', 'Conta institucional']
];
const PUBLIC_KIND_LABEL = { reembolso: 'Reembolso', remuneracao: 'Remuneração' };
const PUBLIC_MONTHS = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const publicState = {
  authority: { q: '', role: '', sphere: '', uf: '', page: 1, pageSize: 30 },
  expense: { q: '', kind: 'reembolso', sourceId: '', category: '', from: '', to: '', minAmount: '', sort: 'date_desc', page: 1, pageSize: 30 },
  supplier: { q: '', page: 1, pageSize: 30 },
  signal: { type: '', page: 1, pageSize: 12 },
  publicAuthority: null, publicSupplier: null,
  authoritySnapshotAt: null, followMessage: '',
  authorityDetail: null, supplierDetail: null, coverage: null,
  signalRowsById: new Map(), expenseRows: [], selectedExpenseIds: new Set(), expenseRowsById: new Map(),
  expenseNotes: new Map(),
  authorities: [], suppliers: [], savedCases: [], followed: []
};
const PUBLIC_STORAGE = {
  cases: 'nl-public-investigations-v1', follow: 'nl-public-authorities-v1'
};
const publicRead = (key, fallback) => { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } };
const publicWrite = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } };
const publicText = value => value === null || value === undefined || value === '' ? 'Sem dado' : String(value);
const publicMoney = (value, digits = 2) => Number.isFinite(Number(value)) && value !== null && value !== '' ? brl(Number(value), digits) : 'Sem dado';
const publicCount = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value).toLocaleString('pt-BR') : 'Sem dado';
function publicMergeKnown(base, incoming) {
  const known = Object.fromEntries(Object.entries(incoming || {}).filter(([, value]) => value !== null && value !== undefined && value !== ''));
  return { ...(base || {}), ...known };
}
const publicAmountForCount = (amount, count) => count !== null && count !== undefined && count !== '' && Number(count) === 0 ? 'Sem valores importados' : publicMoney(amount);
const PUBLIC_ROLE_LABELS = { deputado: 'Deputado(a) federal', senador: 'Senador(a)', presidente: 'Presidente da República', ministro: 'Ministro(a) de Estado', magistrado: 'Juiz(a) ou magistrado(a)', servidor: 'Servidor(a) público(a)', governador: 'Governador(a)', prefeito: 'Prefeito(a)', vereador: 'Vereador(a)', deputado_estadual: 'Deputado(a) estadual', conta_institucional: 'Conta institucional' };
const publicRoleLabel = role => PUBLIC_ROLE_LABELS[String(role || '').toLowerCase()] || publicText(role);
function publicAuthorityValueSummary(item) {
  const expenseCount = item.expenseCount, remunerationCount = item.remunerationCount;
  const knownExpense = expenseCount !== null && expenseCount !== undefined && expenseCount !== '';
  const knownRemuneration = remunerationCount !== null && remunerationCount !== undefined && remunerationCount !== '';
  if (knownExpense && Number(expenseCount) === 0 && knownRemuneration && Number(remunerationCount) === 0) return 'Sem valores importados';
  const expense = knownExpense ? Number(expenseCount) === 0 ? 'Sem reembolsos importados' : `${publicCount(expenseCount)} ${Number(expenseCount) === 1 ? 'reembolso' : 'reembolsos'} · ${publicMoney(item.expenseTotal)}` : item.expenseTotal !== null && item.expenseTotal !== undefined ? `Reembolsos: ${publicMoney(item.expenseTotal)} · quantidade sem dado` : 'Reembolsos sem dado';
  const remuneration = knownRemuneration ? Number(remunerationCount) === 0 ? 'Sem remuneração importada' : `${publicCount(remunerationCount)} ${Number(remunerationCount) === 1 ? 'remuneração' : 'remunerações'} · ${publicMoney(item.remunerationTotal)}` : item.remunerationTotal !== null && item.remunerationTotal !== undefined ? `Remuneração: ${publicMoney(item.remunerationTotal)} · quantidade sem dado` : 'Remuneração sem dado';
  if (!knownExpense && !knownRemuneration && (item.expenseTotal === null || item.expenseTotal === undefined) && (item.remunerationTotal === null || item.remunerationTotal === undefined)) return 'Valores sem dado';
  return `${expense} · ${remuneration}`;
}
function publicKindTotals(summary, kind) {
  const rows = (summary || []).filter(row => row.kind === kind);
  if (!rows.length) return { count: 0, amount: 0 };
  const amountsKnown = rows.every(row => row.amount !== null && row.amount !== undefined && row.amount !== '' && Number.isFinite(Number(row.amount)));
  return {
    count: rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0),
    amount: amountsKnown ? rows.reduce((sum, row) => sum + Number(row.amount), 0) : undefined
  };
}
const publicDate = value => {
  if (!value) return 'Data não informada';
  const month = String(value).match(/^(\d{4})-(\d{2})$/);
  if (month) return `${PUBLIC_MONTHS[Number(month[2])] || month[2]}/${month[1]}`;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : esc(value);
};
const publicCompetence = row => row?.year && row?.month ? `${PUBLIC_MONTHS[Number(row.month)] || String(row.month)}/${row.year}` : 'Competência sem dado';
const publicPeriod = (start, end) => start && end ? `${publicDate(start)} a ${publicDate(end)}` : start || end ? publicDate(start || end) : 'Período não informado';
function publicBenchmarkPeriod(benchmark) {
  const value = benchmark?.period;
  if (typeof value === 'string') {
    const month = value.match(/^(\d{4})-(\d{2})$/);
    return month ? `${PUBLIC_MONTHS[Number(month[2])] || month[2]}/${month[1]}` : value;
  }
  return publicPeriod(value?.start || benchmark?.periodStart, value?.end || benchmark?.periodEnd);
}
const publicSafeURL = value => {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
};
const publicSourceLink = (url, label = 'Conferir fonte ↗') => {
  const safe = publicSafeURL(url);
  return safe ? `<a class="public-link" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '';
};
function publicOptions(options, selected, allLabel) {
  return `<option value="">${allLabel}</option>${options.map(([value, label]) => `<option value="${esc(value)}" ${selected === value ? 'selected' : ''}>${esc(label)}</option>`).join('')}`;
}
function publicRoleOptions(selected = '') {
  const dynamic = (publicState.coverage?.groups || []).map(g => String(g.role || '')).filter(Boolean);
  const seen = new Set();
  const options = [...PUBLIC_ROLE_OPTIONS.map(([value, label]) => [value, label]), ...dynamic.map(role => [role, publicRoleLabel(role)])]
    .filter(([value]) => !seen.has(value) && seen.add(value));
  return publicOptions(options, selected, 'Todos os cargos');
}
function publicNavChips(active = '') {
  const entries = [['radar', 'Gastos em destaque'], ['despesas', 'Buscar despesas'], ['fornecedores', 'Fornecedores'], ['autoridades', 'Pessoas e órgãos'], ['investigacoes', 'Investigações salvas'], ['cobertura', 'Fontes e cobertura'], ['gastos', 'Comparar deputados acompanhados'], ['base', 'Resumo da base']];
  return `<details class="public-tools"><summary>Mais opções</summary><nav class="public-nav" aria-label="Explorar dados públicos">${entries.filter(([view]) => view !== active).map(([view, label]) => `<button type="button" class="fchip" data-public-go="${view}">${label}</button>`).join('')}</nav></details>`;
}
function vAutoridades() {
  const f = publicState.authority;
  return `<div class="public-view">${publicNavChips('autoridades')}<span class="k">Busca avançada</span><h1 class="h radar-title">Pessoas e órgãos</h1>
    <p class="public-intro">Políticos(as), ministros(as), juízes(as) e servidores(as): busque pelo nome de uma pessoa ou órgão.</p>
    <form class="public-filters card" id="public-authority-form"><label class="public-search">Nome, instituição ou órgão<input name="q" value="${esc(f.q)}" placeholder="Ex.: nome ou instituição" autocomplete="off"></label>
      <button class="fchip" type="submit">Buscar</button><details class="public-filter-details"><summary>Filtrar por cargo, esfera ou estado</summary><label>Cargo<select name="role">${publicRoleOptions(f.role)}</select></label><div class="public-filter-grid"><label>Esfera<select name="sphere">${publicOptions([['federal', 'Federal'], ['estadual', 'Estadual'], ['municipal', 'Municipal'], ['distrital', 'Distrital']], f.sphere, 'Todas')}</select></label>
      <label>UF<input name="uf" value="${esc(f.uf)}" maxlength="2" placeholder="Todas" autocapitalize="characters"></label></div>
      <button class="fchip" type="submit">Aplicar filtros</button><button class="public-clear" type="button" data-public-clear="authority">Limpar filtros</button></details></form>
    <div class="public-results" data-public-content="autoridades" aria-live="polite">${skel('lista', 8)}</div>
  </div>`;
}
function vBasePublica() {
  return `<div class="public-view">${publicNavChips('base')}<span class="k">Dados disponíveis</span><h1 class="h radar-title">Resumo da base</h1>
    <p class="note">Explore despesas, remunerações e vínculos nas fontes importadas. O recorte pode ser parcial e varia por órgão e período; consulte a cobertura antes de comparar.</p>
    <div class="public-actions public-home-actions"><button type="button" class="fchip" data-public-go="despesas">Explorar despesas</button><button type="button" class="fchip" data-public-go="autoridades">Buscar pessoas e órgãos</button><button type="button" class="fchip" data-public-go="fornecedores">Buscar fornecedores</button></div>
    <p class="public-home-links"><button type="button" class="public-clear" data-public-go="radar">Sinais para conferir</button><span>·</span><button type="button" class="public-clear" data-public-go="investigacoes">Investigações</button><span>·</span><button type="button" class="public-clear" data-public-go="cobertura">Fontes e cobertura</button></p>
    <div class="public-results" data-public-content="base" aria-live="polite">${skel('numeros')}${skel('cards', 2)}</div>
    <section class="card"><span class="k">Comece pela evidência</span><p class="radar-note">Reembolsos e remunerações são mostrados separadamente. Uma despesa ou sinal precisa ser entendido no contexto do cargo, do período e do documento oficial. Os sinais exploratórios não comprovam irregularidade.</p></section>
  </div>`;
}
function vDespesas() {
  const f = publicState.expense;
  const authority = publicState.publicAuthority;
  const supplier = publicState.publicSupplier;
  const context = authority ? `<p class="note">Despesas associadas a <b>${esc(authority.name || authority.id)}</b>. <button type="button" class="public-clear" data-public-clear-context>Remover esse recorte</button></p>` : supplier ? `<p class="note">Despesas de <b>${esc(supplier.name || supplier.key)}</b>. <button type="button" class="public-clear" data-public-clear-context>Remover esse recorte</button></p>` : '';
  return `<div class="public-view">${publicNavChips('despesas')}<span class="k">Busca avançada</span><h1 class="h radar-title">Buscar despesas</h1>
    <p class="public-intro">Encontre o valor, o fornecedor e o documento de cada despesa.</p>${context}${f.from || f.to ? `<p class="muted">Período: ${esc(f.from === f.to ? publicDate(f.from) : publicPeriod(f.from, f.to))}</p>` : ''}
    <form class="public-filters card" id="public-expense-form"><label class="public-search">Busca<input name="q" value="${esc(f.q)}" placeholder="Autoridade, fornecedor ou CNPJ" autocomplete="off"></label>
      <button class="fchip" type="submit">Buscar</button><details class="public-filter-details"><summary>Filtros: período, valor e tipo de despesa</summary><div class="public-filter-grid"><label>Tipo<select name="kind">${publicOptions([['reembolso', 'Reembolso'], ['remuneracao', 'Remuneração']], f.kind, 'Todos os tipos')}</select></label>
      <label>Fonte<select name="sourceId">${publicOptions((publicState.coverage?.sources || []).filter(source => source.expenseCount > 0).map(source => [source.id, source.label]), f.sourceId, 'Todas as fontes')}</select></label><label>Categoria<input name="category" value="${esc(f.category)}" placeholder="Todas"></label><label>Competência de<input type="month" name="from" value="${esc(f.from)}"></label><label>Competência até<input type="month" name="to" value="${esc(f.to)}"></label>
      <label>Valor mínimo (R$)<input name="minAmount" inputmode="decimal" value="${esc(f.minAmount)}" placeholder="Sem mínimo"></label>
      <label>Ordenar<select name="sort">${publicOptions([['date_desc', 'Mais recentes'], ['amount_desc', 'Maior valor']], f.sort, 'Mais recentes')}</select></label></div>
      <button class="fchip" type="submit">Aplicar filtros</button><button class="public-clear" type="button" data-public-clear="expense">Limpar filtros</button></details></form>
    <button type="button" class="public-clear" data-public-go="fornecedores">Buscar fornecedores pelo histórico de despesas →</button>
    <div class="public-export"><a class="fchip public-download" data-public-csv href="/api/expenses.csv?${esc(publicQuery('despesas'))}">Baixar todos os resultados em CSV ↓</a><span class="muted">A exportação segue os filtros desta consulta.</span></div>
    <div class="public-results" data-public-content="despesas" aria-live="polite">${skel('lista', 8)}</div>
  </div>`;
}
function vFornecedor() {
  const supplier = publicState.publicSupplier;
  if (!supplier) return `<div class="public-view">${publicNavChips()}<button type="button" class="back" data-public-go="despesas">‹ Voltar às despesas</button><section class="card empty"><h1 class="h">Fornecedor não selecionado</h1><button type="button" class="more" data-public-go="fornecedores">Buscar fornecedores</button></section></div>`;
  return `<div class="public-view">${publicNavChips('despesas')}<button type="button" class="back" data-public-go="despesas">‹ Voltar às despesas</button><span class="k">Perfil de fornecedor</span><h1 class="h radar-title">${esc(supplier.name || 'Fornecedor')}</h1><span class="muted">${supplier.cnpj ? `CNPJ ${esc(supplier.cnpj)}` : 'CNPJ sem dado'} · identificador estável: ${esc(supplier.key)}</span>
    <p class="note">O perfil usa a chave do fornecedor fornecida pela base; nomes iguais não são tratados como a mesma pessoa jurídica sem essa identificação.</p>
    <div class="public-results" data-public-content="fornecedor" aria-live="polite">${skel('numeros')}${skel('cards', 2)}</div></div>`;
}
function vFornecedores() {
  const f = publicState.supplier;
  return `<div class="public-view">${publicNavChips('fornecedores')}<span class="k">Busca avançada</span><h1 class="h radar-title">Fornecedores</h1><p class="note">Os perfis usam a chave estável da fonte e o CNPJ quando publicado. Nomes iguais, por si só, não agrupam pessoas jurídicas.</p>
    <form class="public-filters card" id="public-supplier-form"><label class="public-search">Nome ou CNPJ<input name="q" value="${esc(f.q)}" placeholder="Buscar fornecedor" autocomplete="off"></label><button type="submit" class="fchip">Buscar</button></form>
    <div class="public-results" data-public-content="fornecedores" aria-live="polite">${skel('lista', 8)}</div></div>`;
}
function vRadarPublico() {
  const filters = [['', 'Todos'], ['pico', 'Saltos no mês'], ['nota', 'Gastos altos'], ['fornecedor', 'Mesmo fornecedor']];
  return `<div class="public-view"><div class="public-page-heading"><div><span class="k">Busca avançada</span><h1 class="h radar-title">Gastos</h1></div>${publicNavChips('radar')}</div>
    <p class="public-intro">O que chama atenção nos gastos de deputados e senadores.</p>
    <div class="chips public-quick-filters" role="group" aria-label="Que gastos você quer ver?">${filters.map(([value, label]) => `<button type="button" class="fchip" data-public-signal-type="${value}" aria-pressed="${publicState.signal.type === value}">${label}</button>`).join('')}</div>
    <div class="public-actions"><button type="button" class="more" data-public-go="despesas">Buscar uma despesa →</button><button type="button" class="more" data-public-go="investigacoes">Minhas investigações</button></div>
    <p class="radar-note">São pontos para conferir, não conclusões de irregularidade.</p>
    <div class="public-results public-radar-results" data-public-content="radar" aria-live="polite">${skel('cards', 3)}</div></div>`;
}
function vAutoridade() {
  const authority = publicState.publicAuthority;
  if (!authority) return `<div class="public-view">${publicNavChips('autoridades')}<section class="card empty"><h1 class="h">Ninguém selecionado</h1><button type="button" class="more" data-public-go="autoridades">Buscar pessoas e órgãos</button></section></div>`;
  return `<div class="public-view">${publicNavChips('autoridades')}<button type="button" class="back" data-back>‹ Voltar</button><div class="public-profile">${publicAvatar(authority)}<div><span class="k">Busca avançada · perfil</span><h1 class="h radar-title" data-public-authority-title>${authority.name ? esc(authority.name) : skL('260px', 30)}</h1></div></div><p class="muted" data-public-authority-meta>${[authority.role ? publicRoleLabel(authority.role) : '', authority.position, authority.employmentStatus, authority.institution, authority.sphere, authority.uf].filter(Boolean).map(esc).join(' · ') || 'Cargo ou instituição sem dado'}</p>
    <div class="public-actions"><button type="button" class="fchip" data-public-watch="${esc(authority.id)}" aria-pressed="false">Acompanhar</button><button type="button" class="fchip" data-public-authority-expenses="${esc(authority.id)}">Ver despesas</button>${publicSourceLink(authority.sourceUrl, 'Ver fonte ↗')}</div>
    <p class="radar-note">O acompanhamento fica salvo neste navegador. Ao abrir este perfil, a lista consulta registros novos ou alterados desde sua última visita; não há alertas nem verificação em segundo plano.</p><p class="radar-note" data-public-follow-status role="status">${esc(publicState.followMessage || '')}</p>
    <div class="public-results" data-public-content="autoridade" aria-live="polite">${skel('numeros')}${skel('cards', 2)}</div></div>`;
}
function vCobertura() {
  return `<div class="public-view">${publicNavChips('cobertura')}<span class="k">O que esta base cobre</span><h1 class="h radar-title">Fontes e cobertura</h1><p class="note">A disponibilidade depende do órgão, do período e dos dados abertos que cada fonte publica. Um campo vazio ou um recorte sem resultados não demonstra ausência de despesa.</p>
    <div class="public-results" data-public-content="cobertura" aria-live="polite">${skel('numeros')}${skel('cards', 2)}</div></div>`;
}
function vInvestigacoes() {
  publicState.savedCases = publicRead(PUBLIC_STORAGE.cases, []);
  publicState.followed = publicRead(PUBLIC_STORAGE.follow, []);
  const selectedCount = publicState.selectedExpenseIds.size;
  return `<div class="public-view">${publicNavChips('investigacoes')}<span class="k">Anotações neste navegador</span><h1 class="h radar-title">Investigações</h1>
    <p class="note">Guarde despesas selecionadas e suas anotações para retomar a conferência. Os registros ficam só neste navegador e não são enviados a nenhum serviço.</p>
    <section class="card public-save"><label>Título da investigação<input id="public-case-title" maxlength="120" placeholder="Ex.: conferir notas de março"></label><label>Anotação geral<textarea id="public-case-note" rows="3" maxlength="2000" placeholder="O que ainda precisa ser verificado?"></textarea></label>
      <span class="muted">${selectedCount} ${selectedCount === 1 ? 'despesa selecionada' : 'despesas selecionadas'} da lista carregada</span><button type="button" class="fchip" data-public-save-case ${selectedCount ? '' : 'disabled'}>Salvar investigação</button><button type="button" class="public-clear" data-public-export-selected ${selectedCount ? '' : 'disabled'}>Exportar seleção CSV</button><p class="public-save-status" role="status">${esc(publicState.storageMessage || '')}</p></section>
    <section class="card"><span class="k">Acompanhamento manual</span><p class="radar-note">A lista mostra a última visita registrada neste navegador; não indica que houve mudança nos dados.</p><p class="public-save-status" data-public-list-follow-status role="status">${esc(publicState.followMessage || '')}</p><div class="public-follow-list">${publicFollowRows()}</div></section>
    <section class="public-cases"><h2 class="h">Investigações salvas</h2><div class="public-case-list">${publicCasesHTML()}</div></section>
  </div>`;
}
function publicFollowRows() {
  const list = publicRead(PUBLIC_STORAGE.follow, []);
  if (!list.length) return '<p class="muted">Você ainda não está acompanhando autoridades.</p>';
  return list.map(item => `<article class="public-follow-row"><div><b>${esc(item.name || item.id)}</b><small>${esc(publicRoleLabel(item.role || 'Cargo não informado'))} · última visita: ${item.lastVisit ? esc(new Date(item.lastVisit).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })) : 'ainda não visitada'}</small></div><button type="button" class="public-clear" data-public-open-authority="${esc(item.id)}">Abrir</button><button type="button" class="public-clear" data-public-unwatch="${esc(item.id)}">Remover</button></article>`).join('');
}
function publicCasesHTML() {
  const cases = publicRead(PUBLIC_STORAGE.cases, []);
  if (!cases.length) return '<section class="card empty"><p class="muted">Nenhuma investigação salva ainda. Selecione despesas e anote o que deseja conferir.</p></section>';
  return cases.map(item => `<article class="card public-case"><div class="signal-heading"><h3>${esc(item.title || 'Investigação sem título')}</h3><button type="button" class="public-clear" data-public-delete-case="${esc(item.id)}">Excluir</button></div><p class="radar-note">Salva em ${publicDate((item.createdAt || '').slice(0, 10))} · ${publicCount(item.expenses?.length || 0)} despesas</p>${item.note ? `<p>${esc(item.note)}</p>` : ''}<details><summary>Ver registros guardados</summary><div>${(item.expenses || []).map(row => `<div class="public-case-expense"><b>${esc(row.supplierName || row.authorityName || row.id)}</b><span>Competência ${esc(publicCompetence(row))} · emissão ${publicDate(row.date)} · ${publicMoney(row.amount)}</span><small>${esc(row.category || row.kind || 'Categoria sem dado')} · ${esc(row.documentId || 'Documento sem identificador')}</small>${row.annotation ? `<p>${esc(row.annotation)}</p>` : ''}${publicSourceLink(row.documentUrl, 'Abrir documento ↗')}</div>`).join('')}</div></details><button type="button" class="public-clear" data-public-export-case="${esc(item.id)}">Exportar evidências CSV</button></article>`).join('');
}
function publicNotice(message, type = 'note') { return `<p class="${type}" role="status">${esc(message)}</p>`; }
function publicPagination(data, page, action) {
  const pages = Math.max(1, Math.ceil((Number(data.total) || 0) / (Number(data.pageSize) || 30)));
  if (pages < 2) return '';
  return `<div class="public-pagination"><span class="muted">Página ${page} de ${pages}</span><button type="button" class="fchip" data-public-page="${page - 1}" data-public-page-for="${action}" ${page <= 1 ? 'disabled' : ''}>Anterior</button><button type="button" class="fchip" data-public-page="${page + 1}" data-public-page-for="${action}" ${page >= pages ? 'disabled' : ''}>Próxima</button></div>`;
}
function publicAuthorityCard(item) {
  const tags = [item.role ? publicRoleLabel(item.role) : '', item.position, item.employmentStatus, item.institution, item.sphere, item.uf].filter(Boolean).map(esc).join(' · ');
  return `<article class="public-result-row"><button type="button" class="public-result-main" data-public-authority="${esc(item.id)}" data-public-authority-name="${esc(item.name || '')}" data-public-authority-role="${esc(item.role || '')}" data-public-authority-position="${esc(item.position || '')}" data-public-authority-status="${esc(item.employmentStatus || '')}" data-public-authority-institution="${esc(item.institution || '')}" data-public-authority-sphere="${esc(item.sphere || '')}" data-public-authority-uf="${esc(item.uf || '')}" data-public-authority-source="${esc(item.sourceUrl || '')}"><b>${esc(item.name)}</b><span>${tags || 'Cargo ou instituição sem dado'}</span><small>${publicAuthorityValueSummary(item)}</small></button><button type="button" class="public-clear" data-public-authority-expenses="${esc(item.id)}" aria-label="Ver despesas de ${esc(item.name)}">Despesas</button></article>`;
}
function publicExpenseRow(item) {
  publicState.expenseRowsById.set(String(item.id), item);
  const selected = publicState.selectedExpenseIds.has(String(item.id));
  const documentLink = publicSourceLink(item.documentUrl, 'Abrir recibo/documento ↗');
  const sourceLink = publicRecordSource(item);
  const supplier = item.kind === 'remuneracao' ? 'Remuneração publicada' : item.supplierKey ? `<button type="button" class="public-inline" data-public-supplier="${esc(item.supplierKey)}" data-public-supplier-name="${esc(item.supplierName || '')}" data-public-cnpj="${esc(item.cnpj || '')}">${esc(item.supplierName || item.supplierKey)}</button>${item.cnpj ? `<small>CNPJ ${esc(item.cnpj)}</small>` : ''}` : esc(item.supplierName || 'Fornecedor sem identificador');
  return `<article class="public-expense-row"><label class="public-select"><input type="checkbox" data-public-select-expense="${esc(item.id)}" ${selected ? 'checked' : ''}><span>Guardar</span></label><div class="public-expense-head"><b>${publicMoney(item.amount)}</b><span>Competência ${esc(publicCompetence(item))}</span></div><div class="public-expense-body"><b>${supplier}</b><span>${esc(item.category || 'Categoria sem dado')} · ${esc(PUBLIC_KIND_LABEL[item.kind] || item.kind || 'Tipo sem dado')}</span><span>${item.authorityId ? `<button type="button" class="public-inline" data-public-authority="${esc(item.authorityId)}" data-public-authority-name="${esc(item.authorityName || '')}" data-public-authority-role="${esc(item.role || '')}" data-public-authority-institution="${esc(item.institution || '')}">${esc(item.authorityName || item.authorityId)}</button>` : esc(item.authorityName || 'Autoridade sem dado')}${item.role ? ` · ${esc(publicRoleLabel(item.role))}` : ''}${item.institution ? ` · ${esc(item.institution)}` : ''}</span><small>Emissão ${publicDate(item.date)} · ${item.documentId ? `documento ${esc(item.documentId)}` : 'documento sem identificador'}</small>${selected ? `<label class="public-row-note">Anotação para este lançamento<input type="text" maxlength="300" data-public-expense-note="${esc(item.id)}" value="${esc(publicState.expenseNotes.get(String(item.id)) || '')}" placeholder="Observação opcional"></label>` : ''}<div class="public-actions">${documentLink}${sourceLink}</div></div></article>`;
}
function publicSignalSummary(item) {
  const description = String(item.description || '');
  if (item.type === 'pico') {
    const ratio = description.match(/([\d.]+) vezes a mediana de (R\$ [\d.,]+)/);
    return ratio ? `${ratio[1].replace('.', ',')} vezes o valor típico de ${ratio[2]} nos meses anteriores.` : 'Um salto em relação aos meses anteriores.';
  }
  if (item.type === 'fornecedor') {
    const share = description.match(/\(([\d.]+)%\)/);
    return share ? `${share[1].replace('.', ',')}% dos reembolsos do ano foram para o mesmo fornecedor.` : 'Grande parte dos reembolsos foi para um único fornecedor.';
  }
  return 'Um lançamento de pelo menos R$ 10 mil para conferir.';
}
function publicSignalCard(item) {
  publicState.signalRowsById.set(String(item.id), item);
  const typeLabel = { pico: 'Salto no mês', fornecedor: 'Mesmo fornecedor', nota: 'Gasto alto' }[item.type] || 'Para conferir';
  return `<article class="card public-signal"><div class="signal-heading"><span class="badge">${esc(typeLabel)}</span>${item.period ? `<span class="muted">${esc(publicDate(item.period))}</span>` : ''}</div><h2 class="h">${esc(item.authorityName || item.title || typeLabel)}</h2><div class="signal-value">${publicMoney(item.amount)}</div><p>${esc(publicSignalSummary(item))}</p>
    <button type="button" class="fchip public-investigate" data-public-investigate-signal="${esc(item.id)}">Ver os gastos →</button>
    <details class="public-signal-explanation"><summary>Por que apareceu aqui?</summary><p>${esc(item.description || 'Confira os registros e o período na fonte.')}</p><div class="public-actions">${publicRecordSource(item)}</div></details></article>`;
}
function publicInvestigateSignal(id) {
  const item = publicState.signalRowsById.get(String(id));
  if (!item?.authorityId) return;
  publicSetAuthority(item.authorityId, { name: item.authorityName });
  publicState.publicSupplier = null;
  const period = String(item.period || '');
  const month = /^\d{4}-\d{2}$/.test(period);
  const year = /^\d{4}$/.test(period);
  publicState.expense = { q: '', kind: 'reembolso', sourceId: item.sourceId || '', category: '', from: month ? period : year ? `${period}-01` : '', to: month ? period : year ? `${period}-12` : '', minAmount: '', sort: 'amount_desc', page: 1, pageSize: 30 };
  go('despesas');
}
function publicRecordSource(item) {
  const source = (publicState.coverage?.sources || []).find(row => String(row.id) === String(item.sourceId));
  const url = item.sourceUrl || source?.url;
  const label = source?.label;
  const attribution = label ? `<small>Fonte do registro: ${esc(label)}</small>` : item.sourceId ? '<small>Fonte do registro</small>' : '';
  return `${attribution}${url ? publicSourceLink(url, 'Ver fonte ↗') : ''}`;
}
function publicAuthorityDetailHTML(data) {
  const detail = data.authority || {};
  const authority = publicMergeKnown(publicState.publicAuthority, detail);
  const role = String(authority.role || detail.role || '').toLowerCase();
  const rawId = authority.id || detail.id;
  const rawText = String(rawId || '');
  const senator = role === 'senador' && /^\d+$/.test(rawText);
  const deputy = ['deputado', 'deputado_federal'].includes(role) && /^\d+$/.test(rawText);
  const legislativeId = rawText.startsWith('camara:') || rawText.startsWith('senado:') ? rawText
    : senator ? 'senado:' + rawText : deputy ? 'camara:' + rawText : null;
  const parliamentary = !!legislativeId;
  const profile = parliamentary && legislativeId ? profileData({ ...authority, id: legislativeId }) : null;
  const person = profile?.pessoa || authority;
  const legislativeProfile = parliamentary ? `${cidSenadoFotografia(person)}${profileSectionsHTML(person)}${extFichaExtra(profile?.id || legislativeId)}
    <button type="button" class="fchip" data-pol="${esc(profile?.id || legislativeId)}">Abrir ficha parlamentar</button>` : '';
  const summary = data.summary || [];
  const categories = data.categories || [];
  const monthly = data.monthly || [];
  const reembolso = publicKindTotals(summary, 'reembolso');
  const remuneration = publicKindTotals(summary, 'remuneracao');
  const positions = Array.isArray(authority.positions) ? authority.positions : [];
  const positionCount = Number(authority.positionCount) || positions.length;
  const positionsHTML = positionCount > 1 ? `<section class="card"><span class="k">Vínculos funcionais</span><p>${publicCount(positionCount)} cargos registrados; remuneração não atribuível a um único cargo.</p></section>` : '';
  const b = data.benchmark || {};
  const benchmark = b.available && Number(b.peerCount) >= 5
    ? `<section class="card"><span class="k">Comparação contextual</span><p>Mediana de ${publicMoney(b.median)}${b.q1 !== null && b.q1 !== undefined && b.q3 !== null && b.q3 !== undefined ? ` · faixa central ${publicMoney(b.q1)} a ${publicMoney(b.q3)}` : ''}</p><p class="radar-note">${publicCount(b.peerCount)} pares · ${esc(publicBenchmarkPeriod(b))}${b.scope ? ` · ${esc(b.scope)}` : ''}. Comparação calculada pelo Painel Público a partir dos registros importados.</p></section>`
    : `<section class="card"><span class="k">Comparação contextual</span><p class="muted">${esc(b.reason || 'Não há pelo menos cinco registros comparáveis nesta fonte e neste recorte.')}</p><p class="radar-note">Sem referência suficiente, não exibimos ranking nem avaliação de valor.</p></section>`;
  return `${positionsHTML}<div class="row2 public-metrics"><div class="tile"><span class="muted">Registros de despesa</span><b>${publicCount(reembolso.count)}</b></div><div class="tile"><span class="muted">Reembolsos informados</span><b>${publicAmountForCount(reembolso.amount, reembolso.count)}</b></div><div class="tile"><span class="muted">Remuneração informada</span><b>${publicAmountForCount(remuneration.amount, remuneration.count)}</b></div></div>
    ${summary.length ? `<section class="card"><span class="k">Totais por tipo e período</span>${summary.map(row => `<div class="public-stat-row"><b>${esc(PUBLIC_KIND_LABEL[row.kind] || row.kind || 'Tipo sem dado')}</b><span>${publicAmountForCount(row.amount, row.count)} · ${publicCount(row.count)} registros</span><small>${esc(publicPeriod(row.periodStart, row.periodEnd))}</small></div>`).join('')}</section>` : publicNotice('A fonte não informou um resumo por tipo e período.')}
    ${legislativeProfile}${categories.length ? publicCategoryBars(categories) : ''}
    ${monthly.length ? publicMonthChart(monthly) : ''}${benchmark}
    ${authority.sourceUrl ? `<section class="card"><span class="k">Origem do perfil</span>${publicSourceLink(authority.sourceUrl, 'Ver fonte ↗')}<p class="radar-note">Identificador ${esc(authority.id || 'não informado')} · dados podem cobrir períodos diferentes conforme o órgão.</p></section>` : ''}
    <button type="button" class="fchip" data-public-authority-expenses="${esc(publicState.publicAuthority?.id || detail.id || '')}">Abrir lista de despesas</button>`;
}
/* Visual do perfil: mesmas peças das telas simples (barras e meses) */
const publicCap = text => { const t = String(text || '').trim().replace(/\s*,\s*/g, ', ').replace(/[.\s]+$/, ''); return t === t.toUpperCase() ? t.charAt(0) + t.slice(1).toLowerCase() : t; };
function publicAvatar(authority) {
  return `<span class="cid-av-wrap">${cidAvatar({ id: authority.id, name: authority.name || '?' }, 56)}</span>`;
}
function publicCategoryBars(categories) {
  const rows = categories.filter(row => Number(row.amount) > 0).sort((a, b) => b.amount - a.amount);
  if (!rows.length) return '';
  const max = rows[0].amount, total = rows.reduce((sum, row) => sum + Number(row.amount), 0) || 1;
  return `<section class="card"><span class="k">Com o que gastou</span>${rows.slice(0, 8).map(row => `<div class="cid-bar"><div><span>${esc(publicCap(row.category || 'Categoria sem dado'))}</span><b class="mono">${cidMil(row.amount)}</b></div><div class="bar"><i style="width:${row.amount / max * 100}%"></i></div><small class="muted">${Math.round(row.amount / total * 100)}% · ${publicCount(row.count)} ${Number(row.count) === 1 ? 'registro' : 'registros'}${row.kind && row.kind !== 'reembolso' ? ' · ' + esc(PUBLIC_KIND_LABEL[row.kind] || row.kind) : ''}</small></div>`).join('')}</section>`;
}
function publicMonthChart(monthly) {
  const kind = monthly.some(row => row.kind === 'reembolso') ? 'reembolso' : monthly[0]?.kind;
  const rows = monthly.filter(row => (!row.kind || row.kind === kind) && Number.isFinite(Number(row.amount))).slice(-12);
  if (!rows.length) return '';
  const max = Math.max(1, ...rows.map(row => Number(row.amount)));
  return `<section class="card"><span class="k">Mês a mês${kind === 'remuneracao' ? ' · remuneração' : ''}</span><div class="cid-months">${rows.map(row => `<div><small>${Math.round(row.amount / 1e3)}k</small><b class="mt"><i style="height:${Math.max(2, row.amount / max * 100)}%"></i></b><span>${esc(PUBLIC_MONTHS[Number(row.month)] || String(row.month || ''))}</span></div>`).join('')}</div><span class="muted">${rows.length > 1 ? `De ${publicDate(`${rows[0].year}-${String(rows[0].month).padStart(2, '0')}`)} a ${publicDate(`${rows.at(-1).year}-${String(rows.at(-1).month).padStart(2, '0')}`)}` : ''}. Os últimos meses podem crescer: as notas são publicadas com atraso.</span></section>`;
}
function publicSupplierDetailHTML(data) {
  const supplier = data.supplier || {};
  const summary = data.summary || {};
  const authorities = data.authorities || [];
  const categories = data.categories || [];
  const monthly = data.monthly || [];
  return `<section class="card hero"><span class="k">Total registrado nesta base</span><div class="signal-value">${publicAmountForCount(summary.amount, summary.count)}</div><span class="muted">${publicCount(summary.count)} registros · ${publicCount(summary.authorityCount)} autoridades associadas</span><p class="radar-note">Soma dos reembolsos importados associados a este fornecedor, incluindo estornos. Confira os documentos e o período de cada lançamento.</p></section>
    ${categories.length ? `<section class="card"><span class="k">Categorias registradas</span>${categories.map(row => `<div class="public-stat-row"><b>${esc(row.category || 'Categoria sem dado')}</b><span>${publicAmountForCount(row.amount, row.count)} · ${publicCount(row.count)} registros</span></div>`).join('')}</section>` : publicNotice('A fonte não publicou categorias para este fornecedor.')}
    ${monthly.length ? `<section class="card"><span class="k">Série mensal</span>${monthly.map(row => `<div class="public-stat-row"><b>${esc(PUBLIC_MONTHS[Number(row.month)] || String(row.month || ''))}/${esc(row.year || '')}</b><span>${publicMoney(row.amount)}</span></div>`).join('')}</section>` : ''}
    ${authorities.length ? `<section class="card"><span class="k">Autoridades associadas</span>${authorities.map(row => `<article class="public-result-row"><button type="button" class="public-result-main" data-public-authority="${esc(row.id)}" data-public-authority-name="${esc(row.name || '')}" data-public-authority-role="${esc(row.role || '')}"><b>${esc(row.name)}</b><span>${esc(publicRoleLabel(row.role || ''))}</span><small>${publicMoney(row.amount)} · ${publicCount(row.count)} registros</small></button></article>`).join('')}</section>` : publicNotice('A fonte não publicou autoridades associadas neste recorte.')}
    <button type="button" class="fchip" data-public-supplier-expenses="${esc(supplier.key || publicState.publicSupplier?.key || '')}">Ver despesas deste fornecedor</button>`;
}
function publicCoverageHTML(data) {
  const totals = data.totals || {};
  const sources = data.sources || [];
  const groups = data.groups || [];
  const statusLabel = status => ({ ok: 'Importado', available: 'Importado', current: 'Importado', imported: 'Importado', partial: 'Parcial', unavailable: 'Não importado', missing: 'Não importado', not_imported: 'Não importado', stale: 'Desatualizada', error: 'Erro na coleta' }[String(status || '').toLowerCase()] || publicText(status));
  return `<div class="row2 public-metrics"><div class="tile"><span class="muted">Cadastros</span><b>${publicCount(totals.authorities)}</b></div><div class="tile"><span class="muted">Despesas</span><b>${publicCount(totals.expenses)}</b></div><div class="tile"><span class="muted">Fornecedores</span><b>${publicCount(totals.suppliers)}</b></div></div>
    <p class="radar-note">${data.snapshotAt ? `Retrato da base: ${esc(publicDate(data.snapshotAt))}.` : 'Data do retrato não informada.'} Totais são os que a base atual expõe; não são necessariamente o universo de todo o setor público.</p>
    <section class="card"><span class="k">Fontes e recortes</span>${sources.length ? sources.map(source => `<article class="public-source"><div class="signal-heading"><b>${esc(source.label || source.id)}</b><span class="public-status">${esc(statusLabel(source.status))}</span></div><p>${esc(source.scope || 'Escopo não informado')}${source.period ? ` · ${esc(source.period)}` : ''}</p><details class="public-source-method"><summary>Escopo e método</summary><p>${esc(source.detail || 'Limitações não descritas pela fonte.')}</p></details><div class="public-source-counts">${publicCount(source.authorityCount)} cadastros associados · ${publicCount(source.expenseCount)} despesas${source.fetchedAt ? ` · coleta em ${esc(publicDate(source.fetchedAt))}` : ''}</div>${publicSourceLink(source.url, 'Ver fonte ↗')}</article>`).join('') : publicNotice('A API ainda não retornou fontes de cobertura.')}</section>
    ${groups.length ? `<section class="card"><span class="k">Cargos na base</span><p class="radar-note">Os números abaixo indicam apenas registros carregados para cada cargo.</p>${groups.map(group => `<div class="public-stat-row"><b>${esc(publicRoleLabel(group.role || 'Cargo sem dado'))}</b><span>${publicCount(group.count)}</span></div>`).join('')}</section>` : ''}
    <section class="card"><span class="k">Limites desta consulta</span><p class="radar-note">O conjunto pode estar incompleto, ter períodos distintos entre órgãos e conter campos sem publicação. Ausência de registro neste site não prova ausência de gasto, remuneração ou vínculo. Confira sempre os documentos e a fonte oficial.</p></section>`;
}
function publicQuery(view) {
  const p = new URLSearchParams();
  const add = (key, value) => { if (value !== '' && value !== null && value !== undefined) p.set(key, String(value)); };
  if (view === 'autoridades') {
    const f = publicState.authority; add('q', f.q); add('role', f.role); add('sphere', f.sphere); add('uf', f.uf.toUpperCase()); add('page', f.page); add('pageSize', f.pageSize);
  } else if (view === 'despesas') {
    const f = publicState.expense; add('authorityId', publicState.publicAuthority?.id); add('supplierKey', publicState.publicSupplier?.key); add('q', f.q); add('kind', f.kind); add('sourceId', f.sourceId); add('category', f.category); add('from', f.from); add('to', f.to); add('minAmount', f.minAmount.includes(',') ? f.minAmount.replaceAll('.', '').replace(',', '.') : f.minAmount); add('sort', f.sort); add('page', f.page); add('pageSize', f.pageSize);
  } else if (view === 'fornecedores') {
    const f = publicState.supplier; add('q', f.q); add('page', f.page); add('pageSize', f.pageSize);
  } else if (view === 'radar') {
    const f = publicState.signal; add('type', f.type); add('authorityId', f.authorityId); add('page', f.page); add('pageSize', f.pageSize);
  }
  return p.toString();
}
async function publicFetch(path) {
  if (location.protocol === 'file:') throw new Error('Abra o site com o servidor local para consultar a API de dados públicos.');
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error || (response.status === 404 ? 'A API ainda não está disponível neste servidor.' : `A consulta falhou (HTTP ${response.status}).`));
  }
  return response.json();
}
function publicCachedCoverage() {
  return publicState.coverage ? Promise.resolve(publicState.coverage) : publicFetch('/api/coverage');
}
function publicErrorHTML(error) {
  return `<section class="card public-error"><b>Não consegui carregar esses dados.</b><p>${esc(error?.message || 'Falha de conexão com a API.')}</p><p class="radar-note">Tente de novo mais tarde ou consulte a fonte oficial. Nenhum valor foi presumido.</p><button type="button" class="fchip" data-public-retry>Tentar de novo</button></section>`;
}
function publicWriteHTML(name, html) {
  const target = document.querySelector(`[data-public-content="${name}"]`);
  if (target) target.innerHTML = html;
}
function publicSetFollowMessage(message) {
  publicState.followMessage = message;
  for (const selector of ['[data-public-follow-status]', '[data-public-list-follow-status]']) {
    const node = document.querySelector(selector);
    if (node) node.textContent = message;
  }
}
function publicTrackVisit(authority, snapshotAt) {
  const followed = publicRead(PUBLIC_STORAGE.follow, []);
  const index = followed.findIndex(row => String(row.id) === String(authority.id));
  if (index < 0) return false;
  const previous = followed[index];
  const sinceCursor = snapshotAt || previous.sinceCursor || previous.lastVisit;
  followed[index] = {
    ...previous,
    name: authority.name || previous.name,
    role: authority.role || previous.role,
    lastVisit: new Date().toISOString(),
    ...(sinceCursor ? { sinceCursor } : {})
  };
  return publicWrite(PUBLIC_STORAGE.follow, followed);
}
let publicLoadToken = 0;
async function loadPublicView(view) {
  const token = ++publicLoadToken;
  const isCurrent = () => token === publicLoadToken && state.view === view;
  const query = publicQuery(view);
  const authoritySnapshot = publicState.publicAuthority ? { ...publicState.publicAuthority } : null;
  const supplierSnapshot = publicState.publicSupplier ? { ...publicState.publicSupplier } : null;
  try {
    if (view === 'base') {
      const data = await publicFetch('/api/coverage');
      if (!isCurrent()) return;
      publicState.coverage = data;
      const sources = data.sources || [];
      const importedStatuses = new Set(['ok', 'available', 'current', 'imported']);
      const notImportedStatuses = new Set(['unavailable', 'missing', 'not_imported']);
      const statusOf = source => String(source.status || '').toLowerCase();
      const importedCount = sources.filter(source => importedStatuses.has(statusOf(source))).length;
      const partialCount = sources.filter(source => statusOf(source) === 'partial').length;
      const notImportedCount = sources.filter(source => notImportedStatuses.has(statusOf(source))).length;
      const otherCount = sources.length - importedCount - partialCount - notImportedCount;
      const gaps = sources.filter(source => !importedStatuses.has(statusOf(source)));
      const statusLabel = status => ({ partial: 'Parcial', unavailable: 'Não importado', missing: 'Não importado', not_imported: 'Não importado', stale: 'Desatualizada', error: 'Falha na coleta' }[String(status || '').toLowerCase()] || publicText(status));
      publicWriteHTML('base', `<section class="card"><span class="k">Registros nas fontes importadas</span><div class="row2 public-metrics"><div class="tile"><span class="muted">Cadastros</span><b>${publicCount(data.totals?.authorities)}</b></div><div class="tile"><span class="muted">Despesas</span><b>${publicCount(data.totals?.expenses)}</b></div><div class="tile"><span class="muted">Fornecedores</span><b>${publicCount(data.totals?.suppliers)}</b></div></div><p class="radar-note">${data.snapshotAt ? `Retrato em ${esc(publicDate(data.snapshotAt))}.` : 'Data do retrato sem dado.'} Os totais descrevem os registros disponíveis nesta base e não são um custo agregado.</p></section>
        <section class="card public-home-coverage"><span class="k">Estado das fontes</span><p>${publicCount(importedCount)} importadas · ${publicCount(partialCount)} parciais · ${publicCount(notImportedCount)} não importadas${otherCount ? ` · ${publicCount(otherCount)} em outro estado` : ''}</p>${gaps.length ? `<details class="public-home-gaps"><summary>Ver recortes parciais e pendências</summary>${gaps.map(source => `<article class="public-source"><div class="signal-heading"><b>${esc(source.label || source.id)}</b><span class="public-status">${esc(statusLabel(source.status))}</span></div><p>${esc((source.scope || 'Escopo não informado').slice(0, 180))}${(source.scope || '').length > 180 ? '…' : ''}${source.period ? ` · ${esc(source.period)}` : ''}</p></article>`).join('')}</details>` : '<p class="muted">Nenhum recorte parcial ou sem importação foi informado neste retrato.</p>'}<button type="button" class="public-clear" data-public-go="cobertura">Ver todas as fontes e os limites →</button></section>`);
    } else if (view === 'autoridades') {
      const [data, coverage] = await Promise.all([publicFetch(`/api/authorities?${query}`), publicCachedCoverage()]);
      if (!isCurrent()) return;
      publicState.coverage = coverage;
      publicState.authorities = data.items || [];
      const select = document.querySelector('#public-authority-form select[name="role"]');
      if (select) { const selected = publicState.authority.role; select.innerHTML = publicRoleOptions(selected); select.value = selected; }
      publicWriteHTML('autoridades', `<p class="public-count" role="status">${publicCount(data.total)} cadastros nesta cobertura</p>${(data.items || []).length ? `<section class="card public-results-list">${data.items.map(publicAuthorityCard).join('')}</section>` : '<section class="card empty"><h2 class="h">Nenhum cadastro neste recorte</h2><p class="muted">Não há registros que correspondam aos filtros na base consultada. Isso pode refletir limites de cobertura ou período.</p></section>'}${publicPagination(data, Number(data.page) || publicState.authority.page, 'authority')}`);
    } else if (view === 'despesas') {
      const [data, coverage] = await Promise.all([publicFetch(`/api/expenses?${query}`), publicCachedCoverage()]);
      if (!isCurrent()) return;
      publicState.coverage = coverage;
      publicState.expenseRows = data.items || [];
      const sourceSelect = document.querySelector('#public-expense-form select[name="sourceId"]');
      if (sourceSelect) sourceSelect.innerHTML = publicOptions((coverage.sources || []).filter(source => source.expenseCount > 0).map(source => [source.id, source.label]), publicState.expense.sourceId, 'Todas as fontes');
      for (const row of publicState.expenseRows) publicState.expenseRowsById.set(String(row.id), row);
      const exportLink = document.querySelector('[data-public-csv]');
      if (exportLink) exportLink.href = `/api/expenses.csv?${query}`;
      const totalLabel = publicState.expense.kind ? ` · total de ${PUBLIC_KIND_LABEL[publicState.expense.kind] || publicState.expense.kind}: ${publicAmountForCount(data.totalAmount, data.total)}` : ' · total não somado entre reembolsos e remunerações';
      publicWriteHTML('despesas', `<p class="public-count" role="status">${publicCount(data.total)} registros${totalLabel}</p>${(data.items || []).length ? `<section class="card public-expense-list">${data.items.map(publicExpenseRow).join('')}</section>` : '<section class="card empty"><h2 class="h">Nenhuma despesa neste recorte</h2><p class="muted">A base consultada não retornou registros para esses filtros. Confira as datas e os limites de cobertura.</p></section>'}${publicPagination(data, Number(data.page) || publicState.expense.page, 'expense')}`);
    } else if (view === 'fornecedores') {
      const data = await publicFetch(`/api/suppliers?${query}`);
      if (!isCurrent()) return;
      publicState.suppliers = data.items || [];
      publicWriteHTML('fornecedores', `<p class="public-count" role="status">${publicCount(data.total)} fornecedores nesta cobertura</p>${(data.items || []).length ? `<section class="card public-results-list">${data.items.map(item => `<article class="public-result-row"><button type="button" class="public-result-main" data-public-supplier="${esc(item.key)}" data-public-supplier-name="${esc(item.name || '')}" data-public-cnpj="${esc(item.cnpj || '')}"><b>${esc(item.name || 'Fornecedor sem nome')}</b><span>${item.cnpj ? `CNPJ ${esc(item.cnpj)}` : `Chave ${esc(item.key)}`}</span><small>${publicAmountForCount(item.total, item.count)} · ${publicCount(item.count)} despesas · ${publicCount(item.authorityCount)} autoridades</small></button><button type="button" class="public-clear" data-public-supplier="${esc(item.key)}" data-public-supplier-name="${esc(item.name || '')}" data-public-cnpj="${esc(item.cnpj || '')}">Abrir</button></article>`).join('')}</section>` : '<section class="card empty"><h2 class="h">Nenhum fornecedor neste recorte</h2><p class="muted">A base consultada não retornou fornecedores para esta busca.</p></section>'}${publicPagination(data, Number(data.page) || publicState.supplier.page, 'supplier')}`);
    } else if (view === 'radar') {
      const [data, coverage] = await Promise.all([publicFetch(`/api/signals?${query}`), publicCachedCoverage()]);
      if (!isCurrent()) return;
      publicState.coverage = coverage;
      publicWriteHTML('radar', `<p class="public-count" role="status">${publicCount(data.total)} ${Number(data.total) === 1 ? 'destaque para conferir' : 'destaques para conferir'}</p>${(data.items || []).length ? data.items.map(publicSignalCard).join('') : '<section class="card empty"><h2 class="h">Nenhum destaque por aqui</h2><p class="muted">Não encontramos gastos com esse critério nos dados disponíveis.</p></section>'}${publicPagination(data, Number(data.page) || publicState.signal.page, 'signal')}`);
    } else if (view === 'autoridade') {
      publicState.authorityProfileLoadedId = null;
      publicState.authoritySnapshotAt = null;
      const authority = authoritySnapshot;
      if (!authority) return;
      const followedBefore = publicRead(PUBLIC_STORAGE.follow, []).find(row => String(row.id) === String(authority.id));
      const signalQuery = new URLSearchParams({ authorityId: authority.id, page: '1', pageSize: '5' });
      const sinceCursor = followedBefore?.sinceCursor || followedBefore?.lastVisit;
      const updateQuery = sinceCursor ? new URLSearchParams({ authorityId: authority.id, since: sinceCursor, page: '1', pageSize: '1' }) : null;
      const signalsRequest = publicFetch(`/api/signals?${signalQuery}`).then(data => ({ data, error: null }), error => ({ data: null, error }));
      const updatesRequest = updateQuery ? publicFetch(`/api/expenses?${updateQuery}`).then(data => ({ data, error: null }), error => ({ data: null, error })) : Promise.resolve(null);
      const [data, expenses, coverage, signalsResult, updatesResult] = await Promise.all([publicFetch(`/api/authorities/${encodeURIComponent(authority.id)}`), publicFetch(`/api/expenses?${new URLSearchParams({ authorityId: authority.id, page: '1', pageSize: '5', sort: 'date_desc' })}`), publicCachedCoverage(), signalsRequest, updatesRequest]);
      if (!isCurrent()) return;
      publicState.coverage = coverage;
      publicState.authorityDetail = data;
      if (data.authority) {
        publicState.publicAuthority = { ...publicMergeKnown(authority, data.authority), id: data.authority.id || authority.id };
        const meta = document.querySelector('[data-public-authority-meta]');
        const title = document.querySelector('[data-public-authority-title]');
        if (title) title.textContent = publicState.publicAuthority.name || publicState.publicAuthority.id;
        const av = document.querySelector('.public-profile .cid-av-wrap');
        if (av && publicState.publicAuthority.name) av.outerHTML = publicAvatar(publicState.publicAuthority);
        if (meta) meta.textContent = [publicState.publicAuthority.role ? publicRoleLabel(publicState.publicAuthority.role) : '', publicState.publicAuthority.position, publicState.publicAuthority.employmentStatus, publicState.publicAuthority.institution, publicState.publicAuthority.sphere, publicState.publicAuthority.uf].filter(Boolean).join(' · ') || 'Cargo ou instituição sem dado';
      }
      const signals = signalsResult.data;
      const signalHTML = signalsResult.error ? `<section class="card public-error"><span class="k">Sinais exploratórios</span><p>Não consegui consultar os sinais deste perfil. Tente recarregar.</p></section>` : signals?.items?.length ? `<section class="public-signal-section"><span class="k">Sinais exploratórios em reembolsos</span><p class="radar-note">Ajudam a localizar registros para conferência. Não comprovam irregularidade.</p>${signals.items.map(publicSignalCard).join('')}<button type="button" class="public-clear" data-public-go="radar">Ver todos os sinais públicos →</button></section>` : '';
      let updateHTML = '';
      if (followedBefore?.lastVisit) {
        updateHTML = updatesResult?.error ? `<section class="card"><span class="k">Desde a última visita</span><p>Não foi possível verificar registros novos ou alterados. A data da última visita ficou preservada para uma nova tentativa.</p></section>` : `<section class="card"><span class="k">Desde a última visita</span><p>${publicCount(updatesResult?.data?.total)} registros novos ou alterados desde ${esc(new Date(followedBefore.lastVisit).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }))}.</p></section>`;
      } else if (followedBefore) {
        updateHTML = `<section class="card"><span class="k">Acompanhamento</span><p>Esta é sua primeira visita registrada. Na próxima abertura, a consulta poderá identificar registros novos ou alterados desde agora.</p></section>`;
      }
      publicWriteHTML('autoridade', `${updateHTML}${publicAuthorityDetailHTML(data)}${signalHTML}<section class="card"><span class="k">Despesas recentes incluídas</span>${(expenses.items || []).length ? expenses.items.map(publicExpenseRow).join('') : '<p class="muted">A fonte não retornou despesas neste período ou recorte.</p>'}</section>`);
      const stillFollowed = publicRead(PUBLIC_STORAGE.follow, []).some(row => String(row.id) === String(authority.id));
      publicState.authorityProfileLoadedId = String(authority.id);
      const visitCursor = updateQuery ? updatesResult?.data?.snapshotAt : expenses?.snapshotAt;
      publicState.authoritySnapshotAt = updatesResult?.error ? null : (visitCursor || null);
      if (stillFollowed && !updatesResult?.error) {
        const savedVisit = publicTrackVisit(publicState.publicAuthority || authority, visitCursor);
        publicSetFollowMessage(savedVisit ? '' : 'Não consegui atualizar a data da visita no armazenamento local.');
      }
      publicSyncWatchButtons();
    } else if (view === 'fornecedor') {
      const supplier = supplierSnapshot;
      if (!supplier) return;
      const [data, expenses, coverage] = await Promise.all([publicFetch(`/api/suppliers/${encodeURIComponent(supplier.key)}`), publicFetch(`/api/expenses?${new URLSearchParams({ supplierKey: supplier.key, page: '1', pageSize: '10', sort: 'date_desc' })}`), publicCachedCoverage()]);
      if (!isCurrent()) return;
      publicState.coverage = coverage;
      publicState.supplierDetail = data;
      publicWriteHTML('fornecedor', `${publicSupplierDetailHTML(data)}<section class="card"><span class="k">Despesas recentes incluídas</span>${(expenses.items || []).length ? expenses.items.map(publicExpenseRow).join('') : '<p class="muted">A fonte não retornou despesas neste período ou recorte.</p>'}</section>`);
    } else if (view === 'cobertura') {
      const data = await publicFetch('/api/coverage');
      if (!isCurrent()) return;
      publicState.coverage = data;
      publicWriteHTML('cobertura', publicCoverageHTML(data));
    } else if (view === 'investigacoes') {
      publicState.savedCases = publicRead(PUBLIC_STORAGE.cases, []);
      publicState.followed = publicRead(PUBLIC_STORAGE.follow, []);
    }
  } catch (error) {
    if (isCurrent()) publicWriteHTML({ base: 'base', autoridades: 'autoridades', despesas: 'despesas', fornecedores: 'fornecedores', radar: 'radar', autoridade: 'autoridade', fornecedor: 'fornecedor', cobertura: 'cobertura' }[view], publicErrorHTML(error));
  }
}
function publicSyncWatchButtons() {
  const followed = publicRead(PUBLIC_STORAGE.follow, []);
  document.querySelectorAll('[data-public-watch]').forEach(button => {
    const found = followed.some(item => String(item.id) === String(button.dataset.publicWatch));
    button.setAttribute('aria-pressed', String(found)); button.textContent = found ? 'Acompanhando' : 'Acompanhar';
  });
}
function publicCurrentFilters(form, target) {
  const values = Object.fromEntries(new FormData(form).entries());
  const current = publicState[target];
  for (const key of Object.keys(current)) if (key !== 'page' && key !== 'pageSize' && key in values) current[key] = values[key].trim ? values[key].trim() : values[key];
  if (target === 'authority') current.uf = current.uf.toUpperCase();
  current.page = 1;
}
function publicCSVCell(value) {
  const text = String(value ?? '');
  const safe = /^[\s\u0000-\u001f]*[=+@\-]/.test(text) || /^[\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}
function publicExportRows(rows, name) {
  const headers = ['ID', 'Autoridade', 'Cargo', 'Instituição', 'Competência', 'Data de emissão', 'Categoria', 'Tipo', 'Valor R$', 'Fornecedor', 'CNPJ', 'Chave do fornecedor', 'Documento', 'Link do documento', 'ID da fonte', 'Link da fonte', 'Anotação', 'Data da coleta', 'Primeira importação', 'Última alteração', 'Evidência salva em'];
  const csv = [headers, ...rows.map(row => {
    const source = (publicState.coverage?.sources || []).find(item => String(item.id) === String(row.sourceId));
    return [row.id, row.authorityName, publicRoleLabel(row.role), row.institution, publicCompetence(row), row.date, row.category, PUBLIC_KIND_LABEL[row.kind] || row.kind, row.amount, row.supplierName, row.cnpj, row.supplierKey, row.documentId, row.documentUrl, row.sourceId, row.sourceUrl || source?.url, row.annotation, row.fetchedAt || source?.fetchedAt, row.firstSeen, row.lastChanged, row.savedAt];
  })]
    .map(row => row.map(publicCSVCell).join(';')).join('\r\n');
  const blob = new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' });
  if (typeof salvarArquivo === 'function') salvarArquivo(blob, name);
  else { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url); }
}
function publicRefresh() { loadPublicView(state.view); }
function publicSelectExpense(id, selected) {
  const key = String(id);
  if (selected) {
    publicState.selectedExpenseIds.add(key);
    const row = publicState.expenseRows.find(item => String(item.id) === key);
    if (row) publicState.expenseRowsById.set(key, row);
  } else publicState.selectedExpenseIds.delete(key);
  const checkbox = Array.from(document.querySelectorAll('[data-public-select-expense]')).find(input => input.dataset.publicSelectExpense === key);
  const rowElement = checkbox?.closest('.public-expense-row');
  const note = rowElement?.querySelector('.public-row-note');
  if (selected && rowElement && !note) {
    const label = document.createElement('label'); label.className = 'public-row-note'; label.append(document.createTextNode('Anotação para este lançamento'));
    const input = document.createElement('input'); input.type = 'text'; input.maxLength = 300; input.dataset.publicExpenseNote = key; input.placeholder = 'Observação opcional'; input.value = publicState.expenseNotes.get(key) || ''; label.append(input);
    rowElement.querySelector('.public-expense-body')?.insertBefore(label, rowElement.querySelector('.public-actions'));
  } else if (!selected) note?.remove();
  const count = publicState.selectedExpenseIds.size;
  document.querySelectorAll('[data-public-save-case], [data-public-export-selected]').forEach(button => { button.disabled = count === 0; });
  const counter = document.querySelector('.public-selected-count');
  if (counter) counter.textContent = `${count} selecionadas`;
}
function publicToggleFollow(id) {
  const authority = (publicState.publicAuthority && String(publicState.publicAuthority.id) === String(id) ? publicState.publicAuthority : null)
    || publicState.authorities.find(item => String(item.id) === String(id)) || {};
  const profileLoaded = publicState.authorityProfileLoadedId === String(id);
  const snapshotAt = profileLoaded ? publicState.authoritySnapshotAt : null;
  const rows = publicRead(PUBLIC_STORAGE.follow, []);
  const index = rows.findIndex(item => String(item.id) === String(id));
  if (index >= 0) rows.splice(index, 1);
  else rows.push({ id, name: authority.name || id, role: authority.role || '', lastVisit: profileLoaded ? new Date().toISOString() : null, sinceCursor: snapshotAt || null });
  if (!publicWrite(PUBLIC_STORAGE.follow, rows)) {
    publicSetFollowMessage('Não consegui salvar o acompanhamento neste navegador. A lista continua como estava.');
    return false;
  }
  publicSetFollowMessage('');
  publicSyncWatchButtons();
  return true;
}
function publicUnfollow(id, rowElement) {
  const rows = publicRead(PUBLIC_STORAGE.follow, []).filter(item => String(item.id) !== String(id));
  if (!publicWrite(PUBLIC_STORAGE.follow, rows)) {
    publicSetFollowMessage('Não consegui remover o acompanhamento neste navegador. A lista continua como estava.');
    return false;
  }
  publicSetFollowMessage('');
  rowElement?.remove();
  return true;
}
function publicSaveCase() {
  const rows = [...publicState.selectedExpenseIds].map(id => { const row = publicState.expenseRowsById.get(id); return row ? { ...row, annotation: publicState.expenseNotes.get(id) || '', savedAt: new Date().toISOString() } : null; }).filter(Boolean);
  if (!rows.length) return;
  const title = document.getElementById('public-case-title')?.value.trim() || 'Investigação sem título';
  const note = document.getElementById('public-case-note')?.value.trim() || '';
  const cases = publicRead(PUBLIC_STORAGE.cases, []);
  cases.unshift({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, title, note, createdAt: new Date().toISOString(), expenses: rows });
  if (!publicWrite(PUBLIC_STORAGE.cases, cases)) {
    publicState.storageMessage = 'Não consegui salvar: o armazenamento deste navegador está cheio ou indisponível. A seleção continua intacta; exporte o CSV para guardar uma cópia.';
    render();
    return;
  }
  publicState.savedCases = cases;
  publicState.selectedExpenseIds.clear();
  for (const row of rows) publicState.expenseNotes.delete(String(row.id));
  publicState.storageMessage = 'Investigação salva neste navegador.';
  render();
}
function publicRemoveCase(id) { const cases = publicRead(PUBLIC_STORAGE.cases, []).filter(item => String(item.id) !== String(id)); publicWrite(PUBLIC_STORAGE.cases, cases); render(); }
function publicSetAuthority(id, details = {}) {
  const followed = publicRead(PUBLIC_STORAGE.follow, []).find(row => String(row.id) === String(id));
  const item = publicState.authorities.find(row => String(row.id) === String(id)) || (publicState.publicAuthority && String(publicState.publicAuthority.id) === String(id) ? publicState.publicAuthority : followed) || {};
  publicState.publicAuthority = { ...publicMergeKnown(item, details), id };
}
function publicSetSupplier(key, name, cnpj) {
  const old = publicState.publicSupplier;
  const known = publicState.suppliers.find(row => String(row.key) === String(key));
  const previous = old && String(old.key) === String(key) ? old : {};
  publicState.publicSupplier = { key, name: name || known?.name || previous.name || key, cnpj: cnpj || known?.cnpj || previous.cnpj || '' };
}
function publicGoToAuthorityExpenses(id) {
  publicSetAuthority(id);
  publicState.publicSupplier = null;
  const authority = publicState.publicAuthority || {};
  const detailId = publicState.authorityDetail?.authority?.id;
  const summary = String(detailId) === String(id) ? publicState.authorityDetail?.summary || [] : [];
  const expenseCount = authority.expenseCount ?? publicKindTotals(summary, 'reembolso').count;
  const remunerationCount = authority.remunerationCount ?? publicKindTotals(summary, 'remuneracao').count;
  publicState.expense.kind = Number(remunerationCount) > 0 && Number(expenseCount) === 0 ? 'remuneracao' : 'reembolso';
  publicState.expense = { q: '', kind: publicState.expense.kind, sourceId: '', category: '', from: '', to: '', minAmount: '', sort: 'date_desc', page: 1, pageSize: 30 };
  go('despesas');
}
function initPublicData() {
  if (publicState.initialized) return;
  publicState.initialized = true;
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-public-signal-type],[data-public-investigate-signal],[data-public-go],[data-public-authority],[data-public-supplier],[data-public-authority-expenses],[data-public-supplier-expenses],[data-public-watch],[data-public-unwatch],[data-public-open-authority],[data-public-clear],[data-public-clear-context],[data-public-page],[data-public-select-expense],[data-public-save-case],[data-public-export-selected],[data-public-delete-case],[data-public-export-case],[data-public-retry]');
    if (!target) return;
    if (target.hasAttribute('data-public-signal-type')) { publicState.signal.type = target.dataset.publicSignalType; publicState.signal.page = 1; render(); return; }
    if (target.dataset.publicInvestigateSignal) { publicInvestigateSignal(target.dataset.publicInvestigateSignal); return; }
    if (target.dataset.publicGo) {
      event.preventDefault();
      if (target.dataset.publicGo === 'despesas' && (target.closest('.public-nav') || target.closest('.public-home-actions') || state.view === 'radar')) {
        publicState.publicAuthority = null; publicState.publicSupplier = null;
        publicState.expense = { q: '', kind: 'reembolso', sourceId: '', category: '', from: '', to: '', minAmount: '', sort: 'date_desc', page: 1, pageSize: 30 };
      }
      go(target.dataset.publicGo); return;
    }
    if (target.dataset.publicAuthority) { event.preventDefault(); publicSetAuthority(target.dataset.publicAuthority, { name: target.dataset.publicAuthorityName, role: target.dataset.publicAuthorityRole, position: target.dataset.publicAuthorityPosition, employmentStatus: target.dataset.publicAuthorityStatus, institution: target.dataset.publicAuthorityInstitution, sphere: target.dataset.publicAuthoritySphere, uf: target.dataset.publicAuthorityUf, sourceUrl: target.dataset.publicAuthoritySource }); go('autoridade'); return; }
    if (target.dataset.publicSupplier) { event.preventDefault(); publicSetSupplier(target.dataset.publicSupplier, target.dataset.publicSupplierName, target.dataset.publicCnpj); go('fornecedor'); return; }
    if (target.dataset.publicAuthorityExpenses) { event.preventDefault(); publicGoToAuthorityExpenses(target.dataset.publicAuthorityExpenses); return; }
    if (target.dataset.publicSupplierExpenses) { event.preventDefault(); publicSetSupplier(target.dataset.publicSupplierExpenses, publicState.publicSupplier?.name, publicState.publicSupplier?.cnpj); publicState.publicAuthority = null; publicState.expense.kind = 'reembolso'; publicState.expense.page = 1; go('despesas'); return; }
    if (target.dataset.publicWatch) { publicToggleFollow(target.dataset.publicWatch); return; }
    if (target.dataset.publicUnwatch) { publicUnfollow(target.dataset.publicUnwatch, target.closest('.public-follow-row')); return; }
    if (target.dataset.publicOpenAuthority) { publicSetAuthority(target.dataset.publicOpenAuthority); go('autoridade'); return; }
    if (target.dataset.publicClear) {
      const kind = target.dataset.publicClear;
      publicState[kind] = kind === 'authority' ? { q: '', role: '', sphere: '', uf: '', page: 1, pageSize: 30 } : { q: '', kind: 'reembolso', sourceId: '', category: '', from: '', to: '', minAmount: '', sort: 'date_desc', page: 1, pageSize: 30 };
      render(); return;
    }
    if (target.hasAttribute('data-public-clear-context')) { publicState.publicAuthority = null; publicState.publicSupplier = null; render(); return; }
    if (target.dataset.publicPage) {
      const type = target.dataset.publicPageFor === 'authority' ? 'authority' : target.dataset.publicPageFor === 'supplier' ? 'supplier' : target.dataset.publicPageFor === 'signal' ? 'signal' : 'expense';
      publicState[type].page = Math.max(1, Number(target.dataset.publicPage)); publicRefresh(); return;
    }
    if (target.matches('[data-public-select-expense]')) { publicSelectExpense(target.dataset.publicSelectExpense, target.checked); return; }
    if (target.hasAttribute('data-public-save-case')) { publicSaveCase(); return; }
    if (target.hasAttribute('data-public-export-selected')) { publicExportRows([...publicState.selectedExpenseIds].map(id => { const row = publicState.expenseRowsById.get(id); return row ? { ...row, annotation: publicState.expenseNotes.get(id) || '' } : null; }).filter(Boolean), 'evidencias-selecionadas.csv'); return; }
    if (target.dataset.publicDeleteCase) { publicRemoveCase(target.dataset.publicDeleteCase); return; }
    if (target.dataset.publicExportCase) { const item = publicRead(PUBLIC_STORAGE.cases, []).find(row => String(row.id) === String(target.dataset.publicExportCase)); if (item) publicExportRows(item.expenses || [], 'investigacao-evidencias.csv'); return; }
    if (target.hasAttribute('data-public-retry')) { publicRefresh(); return; }
  });
  document.addEventListener('submit', event => {
    if (event.target.id === 'public-authority-form') { event.preventDefault(); publicCurrentFilters(event.target, 'authority'); render(); }
    if (event.target.id === 'public-expense-form') { event.preventDefault(); publicCurrentFilters(event.target, 'expense'); render(); }
    if (event.target.id === 'public-supplier-form') { event.preventDefault(); publicCurrentFilters(event.target, 'supplier'); render(); }
    if (event.target.id === 'public-signal-form') { event.preventDefault(); publicCurrentFilters(event.target, 'signal'); render(); }
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-public-expense-note]')) publicState.expenseNotes.set(String(event.target.dataset.publicExpenseNote), event.target.value);
  });
}
