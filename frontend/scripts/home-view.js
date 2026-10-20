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
    return `<section class="card home-cost"><span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span><div class="home-cost-value">Sem dados</div><p class="muted">O custo mensal ainda não foi calculado para a lista atual.</p><a class="more" href="/politicos" data-go="politicians">Ver a lista de políticos →</a></section>`;
  }
  const hasRange = Number.isFinite(chamber.minimo) && Number.isFinite(chamber.maximo) && chamber.maximo > chamber.minimo;
  const position = hasRange ? (chamber.media - chamber.minimo) / (chamber.maximo - chamber.minimo) * 100 : 50;
  return `<section class="card home-cost">
    <span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span>
    <div class="home-cost-value">R$ ${mil(chamber.media)}<small> mil</small></div>
    <p class="home-cost-parts">Salário, auxílios, cota parlamentar e verba do gabinete, somados.</p>
    ${hasRange ? `<div class="home-range" role="img" aria-label="Média de R$ ${mil(chamber.media)} mil, entre R$ ${mil(chamber.minimo)} mil e R$ ${mil(chamber.maximo)} mil"><span class="home-range-track"><i style="left:${position.toFixed(1)}%"></i></span><span class="home-range-ends"><span>menor R$ ${mil(chamber.minimo)} mil</span><span>maior R$ ${mil(chamber.maximo)} mil</span></span></div>` : ''}
    ${senate && Number.isFinite(senate.media) ? `<div class="home-cost-senate"><span>Senador(a), em média</span><b>R$ ${mil(senate.media)} mil/mês</b></div>` : ''}
    <p class="home-cost-note">Média de ${chamber.comCusto} deputados(as) com custo identificado, dos ${chamber.total} da lista atual, nos meses com todas as partes publicadas e as notas da cota já assentadas (3 meses de folga); valores da época. Na Câmara, ficam fora 13º, encargos do gabinete e apartamento funcional. Câmara e Senado publicam partes diferentes do custo: compare só dentro da mesma Casa.${chamber.foraDaFaixa > 0 ? ` O menor e o maior deixam de fora ${chamber.foraDaFaixa} ${chamber.foraDaFaixa === 1 ? 'deputado(a)' : 'deputados(as)'} com verba de gabinete publicada pela Câmara como R$ 0,00 em algum mês, que entram só na média.` : ''}</p>
    <a class="more" href="/politicos" data-go="politicians">Ver quanto custa cada um(a) →</a>
  </section>`;
}
function homeStats(data) {
  if (!data) return '';
  const quota = data.reembolsos?.deputado || {}, alerts = citizenState.cache.get(HOME_ALERTS_PATH);
  const positive = (data.categoriasCamara || []).filter(category => category.valor > 0);
  const positiveTotal = positive.reduce((total, category) => total + category.valor, 0);
  const checked = homeCheckedVotes(citizenState.cache.get(HOME_VOTES_PATH)?.coverage);
  const stats = [
    Number.isFinite(quota.total) && [formatCitizenAmount(quota.total), `de cota usada pelos deputados(as) da lista, ${esc(homePeriod(quota.periodo))}`],
    Number.isFinite(alerts?.total) && [alerts.total.toLocaleString('pt-BR'), 'picos e concentrações na cota pelas regras do painel; não indicam irregularidade'],
    positive.length && positiveTotal > 0 && [`${Math.round(positive[0].valor / positiveTotal * 100)}%`, `da cota foi para ${esc(positive[0].nome.toLocaleLowerCase('pt-BR'))}`],
    checked && [checked.total.toLocaleString('pt-BR'), 'votações da Câmara conferidas no Placar, com o voto de cada deputado(a)'],
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
    <span class="muted">${esc(homePeriod(quota.periodo))}. Todos os reembolsos importados dos(as) deputados(as) da lista, preservando estornos. Percentuais consideram categorias com saldo positivo; estornos permanecem no total líquido.</span>
  </section>`;
}
function homeTopCard(data) {
  if (!data) return '';
  const ranking = data.topCamara, top = ranking.slice(0, 5), max = Math.max(1, ...top.map(p => p.gastoMensal));
  return `<section class="card home-panel">
    <div class="home-panel-head"><h2 class="h">Quem mais usa a cota</h2><span class="muted">Média mensal nos meses com notas já assentadas</span></div>
    ${top.length ? `<ol class="home-ranking">${top.map((p, i) => `<li>${profileLinkOpen(p.id, '')}<span class="home-rank">${i + 1}</span><span class="home-rank-name"><b>${esc(p.nome)}</b><small>${esc(p.partido || '')} · ${esc(p.uf || '')}</small></span><span class="home-rank-value">R$ ${mil(p.gastoMensal)} mil</span><i style="width:${(Math.max(0, p.gastoMensal) / max * 100).toFixed(2)}%"></i>${profileLinkClose(p.id)}</li>`).join('')}</ol>` : '<p>Sem reembolsos importados para ordenar.</p>'}
    <span class="muted">Os cinco maiores valores entre ${ranking.length} deputados(as) com dados. ${esc(homePeriod(data.reembolsos.deputado.mediaPeriodo || data.reembolsos.deputado.periodo))}. Valores altos não indicam irregularidade.</span>
    <button type="button" class="more" data-home-quota-list>Ver a lista completa →</button>
  </section>`;
}
/* "Como trabalham": presença no Plenário e a votação mais recente do Placar, com os mesmos números das telas /presenca e /placar. */
const HOME_VOTES_PATH = '/api/c/votes?pageSize=1';
const homePlural = (count, singular, plural) => `${count.toLocaleString('pt-BR')} ${count === 1 ? singular : plural}`;
/* Total conferido do Placar (texto principal, trechos e urgências), como no topo de /placar; sem as três partes, nada. */
function homeCheckedVotes(coverage) {
  const urgency = Number.isInteger(coverage?.urgencyCount) && Number.isInteger(coverage?.standaloneUrgencyCount) ? coverage.urgencyCount + coverage.standaloneUrgencyCount : null;
  const parts = { text: coverage?.publishedCount, segment: coverage?.segmentCount, urgency };
  if (!Object.values(parts).every(count => Number.isInteger(count) && count >= 0)) return null;
  return { ...parts, total: parts.text + parts.segment + parts.urgency };
}
function homeAttendanceCard() {
  const all = typeof attendanceRows === 'function' ? attendanceRows() : [];
  const summary = all.length && typeof attendanceSummary === 'function' ? attendanceSummary(all) : null;
  const link = '<a class="more" href="/presenca" data-go="attendance">Ver a presença de todos(as) →</a>';
  if (!summary) return `<section class="card home-panel"><div class="home-panel-head"><h3 class="h">Presença no Plenário</h3><span class="muted">Dados de presença indisponíveis neste recorte.</span></div>${link}</section>`;
  const rate = person => person.presente / person.dias;
  const least = all.slice().sort((first, second) => rate(first) - rate(second) || first.nome.localeCompare(second.nome)).slice(0, 3);
  return `<section class="card home-panel">
    <div class="home-panel-head"><h3 class="h">Presença no Plenário</h3><span class="muted">${all.length} deputados(as) · ${summary.sessionCount} dias com sessão deliberativa${summary.period ? `, ${esc(summary.period)}` : ''}</span></div>
    <p class="home-work-value"><b>${Math.round(summary.average * 100)}%</b><span>de presença média</span></p>
    <dl class="home-work-facts">
      <div><dt>${summary.fullAttendanceCount === 1 ? 'não faltou nenhum dia, com o mandato inteiro' : 'não faltaram nenhum dia, com o mandato inteiro'}</dt><dd>${summary.fullAttendanceCount}</dd></div>
      <div><dt>${summary.belowHalfCount === 1 ? 'foi a menos da metade' : 'foram a menos da metade'}</dt><dd>${summary.belowHalfCount}</dd></div>
    </dl>
    <span class="home-work-label">Menos presentes</span>
    <ol class="home-attendance">${least.map(person => `<li>${profileLinkOpen(chamberPersonId(person.id), '')}
      <span class="home-rank-name"><b>${esc(person.nome)}</b><small>${esc(person.partido)} · ${esc(person.uf)}${attendanceStartTag(person, all)}</small></span>
      <span class="home-attendance-value"><b class="mono${rate(person) < 0.5 ? ' warn' : ''}">${percent(person.presente, person.dias)}%</b><small class="mono">${person.presente} de ${person.dias}</small></span>
      ${attendanceBar(person)}<small class="home-attendance-why">${attendanceAbsences(person)}</small>${profileLinkClose(chamberPersonId(person.id))}</li>`).join('')}</ol>
    <span class="muted">Falta justificada é qualquer motivo publicado pela Câmara (missão autorizada, licença, atestado, decisão da Mesa). Quem assumiu no meio do mandato tem menos dias na conta.</span>
    ${link}
  </section>`;
}
function homeVoteCard() {
  const data = citizenState.cache.get(HOME_VOTES_PATH);
  const head = '<div class="home-panel-head"><h3 class="h">Última votação no Placar</h3><span class="muted">Votação nominal do texto principal no Plenário da Câmara, conferida nas fontes oficiais</span></div>';
  const link = '<a class="more" href="/placar" data-go="votes">Ver o Placar →</a>';
  if (!data) {
    if (!citizenState.pending?.has(HOME_VOTES_PATH)) {
      citizenState.pending?.add(HOME_VOTES_PATH);
      citizenGet(HOME_VOTES_PATH).catch(() => citizenState.cache.set(HOME_VOTES_PATH, { error: true }))
        .finally(() => { citizenState.pending?.delete(HOME_VOTES_PATH); if (state.view === 'home') rerender(); });
    }
    return `<section class="card home-panel">${head}<p class="muted">Carregando a votação mais recente…</p></section>`;
  }
  if (data.error) return `<section class="card home-panel">${head}<p>Não deu para carregar o Placar agora.</p><button type="button" class="more" data-home-votes-retry>Tentar de novo</button></section>`;
  const item = data.available ? data.items?.[0] : null;
  if (!item || typeof scoreboardTallyBar !== 'function') return `<section class="card home-panel">${head}<p>Nenhuma votação conferida neste recorte.</p>${link}</section>`;
  const id = String(item.id || ''), tally = item.tally || {}, abstention = scoreboardAbstention(tally);
  const themes = (item.themes || []).map(theme => theme?.label).filter(Boolean);
  const checked = homeCheckedVotes(data.coverage), period = data.period || {};
  const range = period.start && period.end ? ` de ${scoreboardPeriodDate(period.start)} a ${scoreboardPeriodDate(period.end)}` : '';
  return `<section class="card home-panel">
    ${head}
    <p class="scoreboard-kicker">${scoreboardTypeBadge(scoreboardVoteType(item))}<span class="k">${esc(item.proposition || 'Proposição não informada')} · ${esc(scoreboardDate(item.date))}</span></p>
    <div class="home-vote-body"><b class="home-vote-title">${esc(item.title || 'Título não informado')}</b>${item.summary ? `<p class="muted">${esc(item.summary)}</p>` : ''}</div>
    ${themes.length ? `<p class="scoreboard-themes">${themes.map(theme => `<span class="pill">${esc(theme)}</span>`).join(' ')}</p>` : ''}
    <div class="home-vote-result">
      <p class="scoreboard-outcome" data-outcome="${esc(item.outcome || '')}">${esc(scoreboardOutcome(item.outcome, item.related))}</p>
      ${scoreboardTallyBar(tally)}
      <p class="scoreboard-meta"><span><b>${scoreboardCount(tally.yes)}</b> sim</span><span><b>${scoreboardCount(tally.no)}</b> não</span><span>${abstention.count === null ? 'abst. não publicada' : `${scoreboardCount(abstention.count)} abst.`}</span></p>
    </div>
    ${SCOREBOARD_VOTE_ID.test(id) ? `<a class="more" href="/placar/${esc(id)}" data-vote="${esc(id)}">Ver decisão e votos →</a>` : ''}
    ${checked ? `<dl class="home-work-facts home-work-facts-3">
      <div><dt>do texto principal</dt><dd>${checked.text.toLocaleString('pt-BR')}</dd></div>
      <div><dt>sobre trechos</dt><dd>${checked.segment.toLocaleString('pt-BR')}</dd></div>
      <div><dt>pedidos de urgência</dt><dd>${checked.urgency.toLocaleString('pt-BR')}</dd></div>
    </dl>
    <span class="muted">${homePlural(checked.total, 'votação conferida', 'votações conferidas')}${range}. Não são tudo o que a Câmara votou no período, e um projeto aprovado aqui ainda pode não ter virado lei.</span>` : ''}
    ${link}
  </section>`;
}
function homeWorkSection() {
  return `<section class="home-work">
    <div class="home-work-head"><h2 class="h">Como trabalham</h2><span class="muted">Presença nas sessões de votação e o que o Plenário decidiu, com o voto de cada deputado(a). Fonte: Câmara dos Deputados.</span></div>
    <div class="home-pair">${homeAttendanceCard()}${homeVoteCard()}</div>
  </section>`;
}
function homeHero() {
  return `<div class="home-intro">
    <h1 class="home-title">Quanto custa cada parlamentar — e como ele trabalha.</h1>
    <p class="home-lead">Gastos, presença e votos de deputados(as) e senadores(as), a partir dos dados oficiais da Câmara e do Senado.</p>
    <form class="home-search" data-home-search action="/politicos" method="get" role="search">
      <label for="home-search-input">Busque um nome, partido ou estado</label>
      <div class="home-search-box"><input id="home-search-input" name="q" type="search" maxlength="120" autocomplete="off" placeholder="Ex.: Tabata, PL, Minas Gerais"><button type="submit">Buscar</button></div>
    </form>
    <div class="home-shortcuts"><a href="/minha-cidade" data-go="city">Minha cidade</a><button type="button" data-cmp-start="">Comparar dois políticos</button><a href="/placar" data-go="votes">Placar das votações</a></div>
  </div>`;
}
function homeView() {
  homeLoad();
  const data = home.data;
  // Conteúdo do servidor (os mesmos números) fica até o resumo chegar; some só se a API falhar, para mostrar o aviso.
  if (!data && !home.error && typeof serverRendered === 'function' && serverRendered('/')) return `<div class="top">${brandMark()}${themeToggleHTML()}</div>${serverRendered('/')}`;
  return `<div class="top">${brandMark()}${themeToggleHTML()}</div>
    <section class="home-hero">${homeHero()}${homeCostCard(data)}</section>
    ${homeStats(data)}
    ${homeAlertCard()}
    <div class="home-pair">${homeTopCard(data)}${homeCategoriesCard(data)}</div>
    ${homeWorkSection()}
    <span class="src">Listas e reembolsos: Câmara dos Deputados e Senado Federal. ${data?.snapshotAt ? 'Fotografia da base: ' + esc(dateBR(data.snapshotAt)) + '.' : ''} Presença e votações têm a cobertura indicada em suas telas.</span>`;
}
if (typeof document !== 'undefined' && document.addEventListener) {
  // "Quem mais usa a cota" abre a lista completa na mesma conta: deputados(as), pela média mensal da cota.
  document.addEventListener('click', event => {
    if (event.target?.closest?.('[data-home-votes-retry]')) { citizenState.cache.delete(HOME_VOTES_PATH); return rerender(); }
    if (!event.target?.closest?.('[data-home-quota-list]')) return;
    Object.assign(citizenState.politicians, { query: '', role: 'deputado', order: 'cota', key: '' });
    navigateToView('politicians');
  });
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
