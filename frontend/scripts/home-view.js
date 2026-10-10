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
const HOME_ALERTS_PATH = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
function homeCostCard(data) {
  if (!data) return home.error ? `<section class="card home-cost"><span class="k">Resumo da base</span><p>${esc(home.error)}</p><button type="button" class="opt" data-summary-retry>Tentar novamente</button></section>` : skel('ficha');
  const chamber = data.custoMensal?.deputado, senate = data.custoMensal?.senador;
  if (!chamber || !Number.isFinite(chamber.media)) {
    return `<section class="card home-cost"><span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span><div class="home-cost-value">Sem dados</div><p class="muted">O custo mensal ainda não foi calculado para a lista atual.</p><button type="button" class="more" data-go="politicians">Ver a lista de políticos →</button></section>`;
  }
  const hasRange = Number.isFinite(chamber.minimo) && Number.isFinite(chamber.maximo) && chamber.maximo > chamber.minimo;
  const position = hasRange ? (chamber.media - chamber.minimo) / (chamber.maximo - chamber.minimo) * 100 : 50;
  return `<section class="card home-cost">
    <span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span>
    <div class="home-cost-value">R$ ${mil(chamber.media)}<small> mil</small></div>
    <p class="home-cost-parts">Salário, auxílios, cota parlamentar e verba do gabinete, somados.</p>
    ${hasRange ? `<div class="home-range" role="img" aria-label="Média de R$ ${mil(chamber.media)} mil, entre R$ ${mil(chamber.minimo)} mil e R$ ${mil(chamber.maximo)} mil"><span class="home-range-track"><i style="left:${position.toFixed(1)}%"></i></span><span class="home-range-ends"><span>menor R$ ${mil(chamber.minimo)} mil</span><span>maior R$ ${mil(chamber.maximo)} mil</span></span></div>` : ''}
    ${senate && Number.isFinite(senate.media) ? `<div class="home-cost-senate"><span>Senador(a), em média</span><b>R$ ${mil(senate.media)} mil/mês</b></div>` : ''}
    <p class="home-cost-note">Média de ${chamber.comCusto} deputados(as) com custo identificado, dos ${chamber.total} da lista atual, nos meses com todas as partes publicadas; valores da época. Na Câmara, ficam fora 13º, encargos do gabinete e apartamento funcional. Câmara e Senado publicam partes diferentes do custo: compare só dentro da mesma Casa.</p>
    <button type="button" class="more" data-go="politicians">Ver quanto custa cada um(a) →</button>
  </section>`;
}
function homeStats(data) {
  if (!data) return '';
  const quota = data.reembolsos?.deputado || {}, alerts = citizenState.cache.get(HOME_ALERTS_PATH);
  const positive = (data.categoriasCamara || []).filter(category => category.valor > 0);
  const positiveTotal = positive.reduce((total, category) => total + category.valor, 0);
  const tax = typeof taxWidget === 'function' ? taxWidget() : null;
  const stats = [
    Number.isFinite(quota.total) && [formatCitizenAmount(quota.total), `de cota usada pelos deputados(as) da lista, ${esc(homePeriod(quota.periodo))}`],
    Number.isFinite(alerts?.total) && [alerts.total.toLocaleString('pt-BR'), 'alertas na cota pelas regras do painel; não indicam irregularidade'],
    positive.length && positiveTotal > 0 && [`${Math.round(positive[0].valor / positiveTotal * 100)}%`, `da cota foi para ${esc(positive[0].nome.toLocaleLowerCase('pt-BR'))}`],
    tax && Number.isFinite(quota.total) && quota.total > 0 && [`${Math.round(quota.total / tax.perSecond / 60).toLocaleString('pt-BR')} min`, 'de impostos federais pagam toda essa cota (estimativa)'],
  ].filter(Boolean);
  return stats.length ? `<dl class="home-stats">${stats.map(([value, label]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</dl>` : '';
}
function homeCategoriesCard(data) {
  if (!data) return '';
  const categories = data.categoriasCamara || [], quota = data.reembolsos.deputado;
  if (!categories.length) return '<section class="card home-panel"><h2 class="h">Para onde vai a cota</h2><p>Sem despesas importadas para os(as) deputados(as) da lista.</p></section>';
  // Estornos ficam no total e na lista; a barra mostra só as categorias com saldo positivo.
  const max = Math.max(1, ...categories.map(category => category.valor));
  const positiveTotal = categories.filter(category => category.valor > 0).reduce((total, category) => total + category.valor, 0);
  return `<section class="card home-panel">
    <div class="home-panel-head"><h2 class="h">Para onde vai a cota</h2><span class="muted">${categories.length} categorias · ${formatCitizenAmount(quota.total)} no mandato</span></div>
    <ul class="home-category-list">${categories.map(category => `<li><span>${esc(category.nome)}</span><b>${Math.abs(category.valor) >= 1e3 ? formatCitizenAmount(category.valor) : brl(category.valor)}${category.valor > 0 && positiveTotal ? ` <small>${(category.valor / positiveTotal * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%</small>` : ''}</b><i style="width:${Math.max(0.5, Math.max(0, category.valor) / max * 100).toFixed(2)}%"></i></li>`).join('')}</ul>
    <span class="muted">${esc(homePeriod(quota.periodo))}. Todos os reembolsos importados dos(as) deputados(as) da lista, preservando estornos.</span>
  </section>`;
}
function homeTopCard(data) {
  if (!data) return '';
  const ranking = data.topCamara, top = ranking.slice(0, 5), max = Math.max(1, ...top.map(p => p.gastoMensal));
  return `<section class="card home-panel">
    <div class="home-panel-head"><h2 class="h">Quem mais usa a cota</h2><span class="muted">Média mensal nos meses com notas</span></div>
    ${top.length ? `<ol class="home-ranking">${top.map((p, i) => `<li><button type="button" data-politician="${esc(p.id)}"><span class="home-rank">${i + 1}</span><span class="home-rank-name"><b>${esc(p.nome)}</b><small>${esc(p.partido || '')} · ${esc(p.uf || '')}</small></span><span class="home-rank-value">R$ ${mil(p.gastoMensal)} mil</span><i style="width:${(Math.max(0, p.gastoMensal) / max * 100).toFixed(2)}%"></i></button></li>`).join('')}</ol>` : '<p>Sem reembolsos importados para ordenar.</p>'}
    <span class="muted">Os cinco maiores valores entre ${ranking.length} deputados(as) com dados. ${esc(homePeriod(data.reembolsos.deputado.periodo))}. Valores altos não indicam irregularidade.</span>
    <button type="button" class="more" data-go="politicians">Ver a lista completa →</button>
  </section>`;
}
function homeHero() {
  return `<div class="home-intro">
    <h1 class="home-title">Quanto custa cada parlamentar — e como ele trabalha.</h1>
    <p class="home-lead">Gastos, presença e votos de deputados(as) e senadores(as), a partir dos dados oficiais da Câmara e do Senado.</p>
    <form class="home-search" data-home-search role="search">
      <label for="home-search-input">Busque um nome, partido ou estado</label>
      <div class="home-search-box"><input id="home-search-input" name="q" type="search" maxlength="120" autocomplete="off" placeholder="Ex.: Tabata, PL, Minas Gerais"><button type="submit">Buscar</button></div>
    </form>
    <div class="home-shortcuts"><button type="button" data-go="city">Minha cidade</button><button type="button" data-cmp-start="">Comparar dois políticos</button><button type="button" data-go="votes">Placar das votações</button></div>
  </div>`;
}
function homeView() {
  homeLoad();
  const data = home.data;
  return `<div class="top">${brandMark()}${themeToggleHTML()}</div>
    <section class="home-hero">${homeHero()}${homeCostCard(data)}</section>
    ${homeStats(data)}
    ${homeAlertCard()}
    <div class="home-pair">${homeTopCard(data)}${homeCategoriesCard(data)}</div>
    ${taxCard(data?.reembolsos.deputado.total)}
    <span class="src">Listas e reembolsos: Câmara dos Deputados e Senado Federal. ${data?.snapshotAt ? 'Fotografia da base: ' + esc(dateBR(data.snapshotAt)) + '.' : ''} Presença e votações têm a cobertura indicada em suas telas.</span>`;
}
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('submit', event => {
    const form = event.target?.closest?.('[data-home-search]');
    if (!form) return;
    event.preventDefault();
    const query = String(new FormData(form).get('q') || '').trim().slice(0, 120);
    citizenState.politicians.query = query;
    citizenState.politicians.key = '';
    navigateToView('politicians');
  });
}
