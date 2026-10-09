/* Resumos da base completa. Limites visuais não definem o conjunto calculado. */
const HOME_PATH = '/api/c/resumo';
const home = { data: null, loading: false, error: null };
function homeReset() {
  home.error = null;
  home.data = null;
  citizenState.cache.delete(HOME_PATH);
}
function homeLoad() {
  if (home.loading || home.data || home.error) return;
  home.loading = true;
  citizenGet(HOME_PATH).then(data => { home.data = data; }).catch(error => { home.error = citizenErrorMessage(error); })
    .finally(() => { home.loading = false; if (state.view === 'home') rerender(); });
}
function homePeriod(period) {
  const label = value => {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}(?:-\d{2})?$/.test(value)) return null;
    const month = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(value.slice(5, 7)) - 1];
    return month ? `${value.length === 10 ? Number(value.slice(8, 10)) + '/' : ''}${month}/${value.slice(0, 4)}` : null;
  };
  const start = label(period?.inicio), end = label(period?.fim);
  return start && end ? `${start} a ${end}` : 'período não informado';
}
function homeCostCard(data) {
  if (!data) return home.error ? `<section class="card hero"><span class="k">Resumo da base</span><p>${esc(home.error)}</p><button type="button" class="opt" data-summary-retry>Tentar novamente</button></section>` : skel('ficha');
  const deputies = data.parlamentares.deputado, quota = data.reembolsos.deputado;
  const salary = PROFILE_SALARY.deputado;
  return `<section class="card hero">
    <span class="k">Cota parlamentar por deputado(a)</span>
    <div class="huge">${Number.isFinite(quota.media) ? `<small>R$</small>${mil(quota.media)} mil<small>/mês</small>` : 'Sem dados'}</div>
    <span class="muted">Média mensal, nos meses com notas, entre os(as) ${quota.comRegistros} deputados(as) com reembolsos observados, dos ${deputies.total} registros da lista. Mandato atual: ${esc(homePeriod(quota.periodo))}. Valores da época.</span>
    <div>
      <div class="cost-row"><i style="background:var(--hero-fg)"></i><b>Salário de referência</b><span class="val">${brl(salary.amount, 2)}</span><p>Subsídio bruto mensal do cargo. O pagamento individual não foi importado.</p></div>
      <div class="cost-row"><i style="background:var(--cat1)"></i><b>Cota parlamentar</b><span class="val">${Number.isFinite(quota.total) ? formatCitizenAmount(quota.total) : 'Sem dados'}</span><p>Total observado no mandato para os(as) deputados(as) da lista. Reembolsa despesas do trabalho; não é salário.</p></div>
      <div class="cost-row"><i style="background:var(--cat3)"></i><b>Verba de gabinete</b><span class="val">Por perfil</span><p>Gasto da equipe, com os meses publicados na ficha. Os valores têm recortes próprios e não são somados ao subsídio.</p></div>
    </div>
    <button type="button" class="opt" data-go="politicians" style="justify-content:center">Ver quanto gasta cada um(a)</button>
  </section>`;
}
function homePresenceCard() {
  const rows = profilePresenceRows();
  const person = [...rows].sort((a, b) => a.presente / a.dias - b.presente / b.dias || String(a.id).localeCompare(String(b.id)))[0];
  if (!person) return `<section class="card"><span class="k">Presença no Plenário</span><p class="muted">Sem registros de presença importados.</p></section>`;
  const identity = { id: profileId(person.id), name: person.nome, party: person.partido, uf: person.uf, role: 'deputado' };
  return `<section class="card alarm"><span class="k">Menor presença proporcional no recorte</span>
    <button type="button" class="citizen-who" data-politician="${esc(identity.id)}">${citizenAvatar(identity, 52)}<span><b>${esc(person.nome)}</b><small>${esc(person.partido || '')} · ${esc(person.uf || '')}</small></span></button>
    <div><span class="big">${person.presente} de ${person.dias}</span><span class="muted"> dias com sessão de votação no mandato</span></div>
    ${attendanceBar(person)}
    <p class="muted">Comparação entre todos os ${rows.length} registros válidos de presença. Ausências justificadas: ${person.justificadas}; não justificadas: ${person.falta}. Os dias observados podem variar entre mandatos.</p>
    <div class="citizen-actions"><button type="button" class="fchip" data-politician="${esc(identity.id)}">Abrir a ficha</button><button type="button" class="fchip citizen-cta" data-go="attendance">Ver presença dos deputados →</button></div>
  </section>`;
}
function homeCategoriesCard(data) {
  if (!data) return '';
  const categories = data.categoriasCamara, quota = data.reembolsos.deputado;
  if (!categories.length) return '<section class="card hero"><span class="k">Categorias da cota</span><p>Sem despesas importadas para os(as) deputados(as) da lista.</p></section>';
  const answered = state.quiz !== null, options = categories.slice(0, 3).sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'));
  // Negative adjustments stay in the totals; a distribution bar shows positive categories only.
  const positive = categories.filter(category => category.valor > 0), scale = positive.reduce((total, category) => total + category.valor, 0);
  return `<section class="card hero"><span class="k">Cota dos(as) deputados(as) da lista · reembolsos observados</span>
    <div class="huge" style="font-size:clamp(40px,12vw,54px)">${formatCitizenAmount(quota.total)}</div>
    <h2 class="h" style="font-size:21px">Qual categoria teve o maior gasto?</h2>
    <div class="opts">${options.map(category => `<button type="button" class="opt" data-quiz="${esc(category.nome)}" data-state="${!answered ? '' : category.nome === categories[0].nome ? 'right' : 'wrong'}" ${answered ? 'disabled' : ''}><span>${esc(category.nome)}</span><span>${answered ? brl(category.valor) : ''}</span></button>`).join('')}</div>
    ${answered ? `<p>${state.quiz === categories[0].nome ? 'Acertou!' : 'A maior categoria foi ' + esc(categories[0].nome) + '.'} Total observado: ${brl(categories[0].valor)}.</p>` : ''}
    <div class="stack" role="img" aria-label="Distribuição das categorias com saldo positivo">${positive.map((category, index) => `<i style="width:${category.valor / scale * 100}%;background:var(${CATS_H[index % CATS_H.length]})"></i>`).join('')}</div>
    <div class="legend" style="color:var(--hero-muted)">${categories.map((category, index) => `<span><i style="background:var(${CATS_H[index % CATS_H.length]})"></i>${esc(category.nome)} ${brl(category.valor)}</span>`).join('')}</div>
    <span class="muted">${esc(homePeriod(quota.periodo))}. O resumo considera todos os registros de reembolso importados dos(as) deputados(as) da lista, preservando estornos.</span>
  </section>`;
}
function homeCoverageCard(data) {
  if (!data) return '';
  const deputyStats = data.parlamentares.deputado, senatorStats = data.parlamentares.senador;
  return `<section class="card hero"><span class="k">Câmara e Senado · base disponível</span>
    <h2 class="h">${deputyStats.total} deputados(as) e ${senatorStats.total} registros do Senado.</h2>
    <p>${deputyStats.comReembolsos} deputados(as) e ${senatorStats.comReembolsos} registros do Senado têm reembolsos observados. A busca inclui todos os cadastros dessas listas.</p>
    <p class="muted">Registros do Senado podem incluir suplentes em transição; não são uma contagem de cadeiras. Resultados eleitorais ainda não foram importados para este conjunto.</p>
    <button type="button" class="opt" data-go="politicians">Consultar a lista de parlamentares</button>
  </section>`;
}
function homeTopCard(data) {
  if (!data) return '';
  const ranking = data.topCamara, top = ranking.slice(0, 5), max = Math.max(1, ...top.map(p => p.gastoMensal));
  return `<section class="card"><span class="k">Maiores gastos médios de cota por mês entre os(as) deputados(as) da lista</span>
    ${top.length ? `<div>${top.map((p, i) => `<button type="button" class="who" data-politician="${esc(p.id)}" style="${i ? '' : 'border-top:0'}">${citizenAvatar({ id: p.id, name: p.nome }, 40)}<span class="n">${i + 1}. ${esc(p.nome)}</span><span class="v">${mil(p.gastoMensal)} mil/mês</span><span class="s">${esc(p.partido || '')} · ${esc(p.uf || '')}</span><span class="b"><i class="grow-x" style="width:${Math.max(0, p.gastoMensal) / max * 100}%"></i></span></button>`).join('')}</div>` : '<p>Sem reembolsos importados para ordenar.</p>'}
    <span class="muted">Os cinco maiores valores entre ${ranking.length} deputados(as) com dados. ${esc(homePeriod(data.reembolsos.deputado.periodo))}. Média nos meses com notas; valores altos não indicam irregularidade.</span>
    <button type="button" class="more" data-go="politicians">Consultar a lista completa</button>
  </section>`;
}
function homeView() {
  homeLoad();
  const data = home.data;
  return `<div class="top">${brandMark()}<span class="pill"><i></i>${DATA.ultimaVotacao ? 'Placar selecionado · ' + formatShortDate(DATA.ultimaVotacao) : 'Base disponível'}</span>${themeToggleHTML()}</div>
    ${homeCostCard(data)}${taxCard(data?.reembolsos.deputado.total)}${homeAlertCard()}
    ${homePresenceCard()}${homeCategoriesCard(data)}
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:6px"><h2 class="h">Placar da Câmara</h2><button class="more" data-go="votes">Ver tudo</button></div>
    <div class="carousel">${DATA.votacoes.map(voteCard).join('') || '<p class="note">Sem votações disponíveis neste recorte.</p>'}</div>
    ${homeCoverageCard(data)}${homeTopCard(data)}
    <span class="src">Listas e reembolsos: Câmara dos Deputados e Senado Federal. ${data?.snapshotAt ? 'Fotografia da base: ' + esc(dateBR(data.snapshotAt)) + '.' : ''} Presença e votações têm a cobertura indicada em suas telas.</span>`;
}
