/* Interface do radar. Os critérios e cálculos ficam em spending-analysis.js. */
function radarType(type) {
  return { pico: 'Pico mensal', nota: 'Nota de valor alto', categoria: 'Concentração por categoria' }[type];
}
function radarPercent(value) {
  return (value * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%';
}
function radarDate() { return `${dmy(DATA.geradoEm)}/${DATA.geradoEm.slice(0, 4)}`; }
function radarSource(d) { return `https://www.camara.leg.br/deputados/${encodeURIComponent(d.id)}?ano=2026`; }
function invoiceURL(invoice) {
  try {
    const u = new URL(invoice.url);
    return u.protocol === 'https:' && (u.hostname === 'camara.leg.br' || u.hostname.endsWith('.camara.leg.br')) ? u.href : null;
  } catch { return null; }
}
function radarHome() {
  return `<section class="card radar-intro">
    <span class="k">Gastos para conferir</span>
    <h2 class="h">O que merece uma segunda olhada?</h2>
    <p class="radar-note">Gastos altos, saltos de um mês para outro e valores concentrados em um fornecedor. Veja o que aconteceu e confira os documentos.</p>
    <button type="button" class="more" data-go="radar">Ver gastos que chamam atenção →</button>
  </section>`;
}
function radarMethod() {
  const r = SpendingAnalysis.rules;
  return `<details class="method"><summary>Como os sinais são calculados</summary>
    <p><b>Pico mensal:</b> gasto de pelo menos ${r.spikeRatio.toLocaleString('pt-BR')} vez a mediana dos meses anteriores, com aumento de pelo menos ${brl(r.spikeDelta)}. Exige ${r.minPreviousMonths} meses anteriores ou mais, sem lacunas desde janeiro e com mediana positiva. A mediana é o valor central da série ordenada.</p>
    <p><b>Nota alta:</b> lançamento de pelo menos ${brl(r.invoiceMinimum)} entre as notas incluídas. É um corte de valor para triagem, não uma comparação com preços de mercado.</p>
    <p><b>Concentração:</b> categoria com pelo menos ${radarPercent(r.categoryShare)} do total da cota e ${brl(r.categoryMinimum)}. Mostra o perfil de uso da verba; passagens, por exemplo, dependem da distância até Brasília.</p>
    <p>Os critérios são exploratórios e aplicados igualmente aos ${D.length} deputados desta base. Não são limites legais nem detectores de fraude. Reembolsos acumulados e diferenças na atividade parlamentar podem explicar os sinais.</p>
    <p>Para picos, usamos apenas janeiro a julho de 2026, intervalo tratado como fechado na coleta fornecida. Agosto a outubro podem estar incompletos. Não há comparação estatística com os 513 deputados.</p>
  </details>`;
}
function filteredSpendingAlerts() {
  return RADAR.alerts.filter(a => (state.spendingType === 'todos' || a.type === state.spendingType) &&
    (state.spendingDep === 'todos' || a.depId === state.spendingDep)).sort((a, b) =>
      state.spendingSort === 'nome' ? byId[a.depId].nome.localeCompare(byId[b.depId].nome, 'pt-BR') || b.amount - a.amount :
      (state.spendingSort === 'sinais' ? ({ pico: 0, nota: 1, categoria: 2 }[a.type] - { pico: 0, nota: 1, categoria: 2 }[b.type]) : 0) || b.amount - a.amount || a.id.localeCompare(b.id));
}
function radarExplanation(a) {
  if (a.type === 'pico') return `${MES[a.month]}/2026 atingiu ${a.ratio.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}× a referência de ${brl(a.baseline, 2)} (mediana dos meses anteriores). Diferença de ${brl(a.amount - a.baseline, 2)}.`;
  if (a.type === 'nota') return `${a.invoice.fornecedor} · ${a.invoice.cat} · ${dmy(a.invoice.data)}/2026. Atinge o corte de ${brl(SpendingAnalysis.rules.invoiceMinimum)} para conferência.`;
  return `A categoria ${a.category} representa ${radarPercent(a.share)} da cota acumulada deste deputado.`;
}
function radarCard(a, inDetail = false) {
  const d = byId[a.depId], source = a.type === 'nota' ? invoiceURL(a.invoice) : radarSource(d);
  const reason = a.type === 'pico'
    ? `Referência: janeiro a ${MES[a.month - 1]}/2026. Mediana de ${brl(a.baseline, 2)}; corte de ${brl(a.baseline * SpendingAnalysis.rules.spikeRatio, 2)} e diferença mínima de ${brl(SpendingAnalysis.rules.spikeDelta)}. O valor é o total mensal da cota, incluindo passagens.`
    : a.type === 'nota'
      ? `Este lançamento está entre as ${d.cota.lancamentos.length} notas recentes incluídas, de ${d.cota.notas} registros contabilizados na coleta. A lista não permite concluir que esta é a maior nota do ano. O PDF é a evidência disponível para conferir fornecedor e descrição.`
      : `${brl(a.amount, 2)} ÷ ${brl(d.cota.total, 2)} = ${radarPercent(a.share)}. Corte: ${radarPercent(SpendingAnalysis.rules.categoryShare)} e ${brl(SpendingAnalysis.rules.categoryMinimum)}. Concentração em uma categoria não significa concentração em um fornecedor.`;
  return `<article class="card signal" data-type="${a.type}">
    <div class="signal-heading"><span class="badge">${radarType(a.type)}</span><span class="muted">${a.type === 'pico' ? MES[a.month] + '/2026' : a.type === 'nota' ? 'Amostra de notas' : 'Acumulado de 2026'}</span></div>
    ${inDetail ? '' : `<h3>${esc(d.nome)} <span class="muted">${esc(d.partido)} · ${d.uf}</span></h3>`}
    <div class="signal-value">${brl(a.amount, 2)}</div>
    <p style="font-size:14px">${esc(radarExplanation(a))}</p>
    <details><summary>Ver cálculo e contexto</summary><p class="muted">${esc(reason)}</p><p class="radar-note">Base recebida em ${radarDate()}. Sinal para investigação, sem conclusão de irregularidade.</p></details>
    <div class="chips">${inDetail ? '' : `<button type="button" class="fchip" data-spending-detail="${d.id}">Investigar gastos</button>`}
    ${source ? `<a class="fchip evidence-link" href="${esc(source)}" target="_blank" rel="noopener noreferrer">${a.type === 'nota' ? 'Abrir nota fiscal ↗' : 'Conferir na Câmara ↗'}</a>` : '<span class="muted">Documento sem link disponível.</span>'}</div>
  </article>`;
}
function radarRanking() {
  const list = RADAR.rankings.filter(r => state.spendingDep === 'todos' || r.depId === state.spendingDep)
    .sort((a, b) => state.spendingSort === 'nome' ? byId[a.depId].nome.localeCompare(byId[b.depId].nome, 'pt-BR') :
      state.spendingSort === 'limite' ? (b.share ?? -1) - (a.share ?? -1) : (b.total ?? -1) - (a.total ?? -1));
  const max = Math.max(1, ...list.map(r => r.total ?? 0));
  return `<section class="card"><span class="k">Comparação no recorte de ${D.length} deputados</span>
    <p class="radar-note">Cota acumulada em 2026, conforme a base de ${radarDate()}, incluindo passagens. Os limites variam por estado e pelo período disponível. O percentual usa o limite acumulado informado na coleta; não indica excesso nem irregularidade.</p>
    <div>${list.map((r, i) => { const d = byId[r.depId]; return `<button type="button" class="rank-row" data-spending-detail="${d.id}" aria-label="Investigar gastos de ${esc(d.nome)}">
      <span class="muted">${i + 1}</span><span><b>${esc(d.nome)}</b><small>${esc(d.partido)} · ${d.uf}</small><span class="rank-track" aria-hidden="true"><i style="width:${state.spendingSort === 'limite' ? Math.min(100, Math.max(0, r.share ?? 0) * 100) : r.total === null ? 0 : Math.max(0, r.total) / max * 100}%"></i></span></span>
      <span class="rank-value">${r.total === null ? 'Sem dado' : brl(r.total)}<small>${r.share === null ? 'Limite indisponível' : radarPercent(r.share) + ' do limite'}</small></span>
    </button>`; }).join('')}</div></section>`;
}
function vGastos() {
  const alerts = filteredSpendingAlerts();
  const relevant = RADAR.alerts.filter(a => state.spendingDep === 'todos' || a.depId === state.spendingDep);
  const count = type => relevant.filter(a => type === 'todos' || a.type === type).length;
  const isRanking = state.spendingMode === 'ranking';
  return `<span class="k">Transparência que dá para conferir</span><h1 class="h radar-title">Gastos para conferir</h1>
    <p class="note">${D.length} deputados acompanhados · base de ${radarDate()}. Os sinais ajudam a escolher o que investigar. Não comprovam irregularidade.</p>
    <div class="chips" role="group" aria-label="Modo de análise">${[['alertas', 'Sinais para conferir'], ['ranking', 'Comparar gastos']].map(([key, label]) => `<button type="button" class="fchip" data-spending-mode="${key}" aria-pressed="${state.spendingMode === key}">${label}</button>`).join('')}</div>
    <div class="radar-filters"><label for="spending-dep">Deputado(a)<select id="spending-dep"><option value="todos">Todos (${D.length})</option>${D.map(d => `<option value="${d.id}" ${state.spendingDep === d.id ? 'selected' : ''}>${esc(d.nome)} · ${d.uf}</option>`).join('')}</select></label>
      <label for="spending-sort">Ordenar por<select id="spending-sort">${!isRanking ? `<option value="sinais" ${state.spendingSort === 'sinais' ? 'selected' : ''}>Tipo de sinal</option>` : ''}<option value="valor" ${state.spendingSort === 'valor' || (isRanking && state.spendingSort === 'sinais') || (!isRanking && state.spendingSort === 'limite') ? 'selected' : ''}>Maior valor</option>${isRanking ? `<option value="limite" ${state.spendingSort === 'limite' ? 'selected' : ''}>Maior uso do limite</option>` : ''}<option value="nome" ${state.spendingSort === 'nome' ? 'selected' : ''}>Nome</option></select></label></div>
    ${isRanking ? radarRanking() : `<div class="chips" role="group" aria-label="Tipo de sinal">${[['todos', 'Todos'], ['pico', 'Picos mensais'], ['nota', 'Notas altas'], ['categoria', 'Concentração']].map(([key, label]) => `<button type="button" class="fchip" data-spending-type="${key}" aria-pressed="${state.spendingType === key}">${label} <b>${count(key)}</b></button>`).join('')}</div>
      <div class="signal-heading"><span class="muted" role="status">${alerts.length} ${alerts.length === 1 ? 'sinal encontrado' : 'sinais encontrados'}</span><button type="button" class="more" data-export-alerts ${alerts.length ? '' : 'disabled'}>Exportar CSV</button></div>
      ${alerts.length ? alerts.map(a => radarCard(a)).join('') : '<section class="card empty"><h2 class="h">Nenhum sinal neste filtro</h2><p class="muted">Nenhum registro atende a estes critérios na base disponível. Isso não atesta ausência de problemas.</p></section>'}`}
    <section class="card"><span class="k">Até onde os dados permitem ir</span><p class="radar-note">${RADAR.coverage.invoicesIncluded} notas recentes incluídas, de ${RADAR.coverage.invoicesReported} registros contabilizados na coleta. O total e as categorias usam valores agregados; as notas são uma amostra limitada.</p>
      <p class="radar-note">Duplicidades, fornecedores recorrentes e preços fora de mercado exigem a relação completa de documentos e informações sobre o serviço. Esses cruzamentos ainda não estão disponíveis.</p>${radarMethod()}</section>`;
}
function goSpendingDetail(id) {
  if (!byId[id]) return;
  hist.push({ view: state.view, dep: state.dep, vote: state.vote, y: window.scrollY });
  state.dep = id; go('gasto', true);
}
function spendingChart(d) {
  const months = d.cota.porMes || {}, keys = Array.from({ length: 10 }, (_, i) => i + 1);
  const max = Math.max(1, ...keys.map(m => Number.isFinite(months[m]) ? Math.max(0, months[m]) : 0));
  const spikes = RADAR.alerts.filter(a => a.depId === d.id && a.type === 'pico');
  return `<section class="card"><span class="k">Evolução mensal da cota · 2026</span>
    <p class="radar-note">Janeiro a julho entram na análise de picos. Meses posteriores aparecem hachurados e podem estar incompletos.</p>
    <div class="month-chart" role="img" aria-label="Gastos mensais da cota. Valores exatos disponíveis na tabela a seguir.">${keys.map(m => {
      const value = months[m], known = Number.isFinite(value), spike = spikes.some(a => a.month === m);
      return `<div class="month-col ${m > 7 ? 'partial' : spike ? 'flag' : ''}" title="${MES[m]}: ${known ? brl(value, 2) : 'sem dado'}"><small>${known ? mil(value) + 'k' : '—'}</small><i style="height:${known ? Math.max(0, value) / max * 106 : 0}px"></i><span>${MES[m]}</span></div>`;
    }).join('')}</div>
    <div class="legend"><span><i style="background:var(--accent)"></i>Período analisado</span><span><i style="background:var(--warn)"></i>Pico sinalizado</span></div>
    <details class="method"><summary>Ver valores de cada mês</summary><table class="monthly-table"><caption>Valores registrados na base de ${radarDate()}</caption><thead><tr><th scope="col">Mês</th><th scope="col">Cota</th><th scope="col">Análise</th></tr></thead><tbody>${keys.map(m => `<tr><th scope="row">${MES[m]}</th><td>${Number.isFinite(months[m]) ? brl(months[m], 2) : 'Sem dado'}</td><td>${!Number.isFinite(months[m]) ? 'Sem dado' : m > 7 ? 'Parcial' : m < 4 ? 'Histórico inicial' : spikes.some(a => a.month === m) ? 'Pico' : 'Sem pico'}</td></tr>`).join('')}</tbody></table></details></section>`;
}
function vGasto() {
  const d = byId[state.dep], own = RADAR.alerts.filter(a => a.depId === d.id).sort((a, b) =>
    ({ pico: 0, nota: 1, categoria: 2 }[a.type] - { pico: 0, nota: 1, categoria: 2 }[b.type]) || b.amount - a.amount);
  const rank = RADAR.rankings.find(r => r.depId === d.id);
  const invoices = [...d.cota.lancamentos].sort((a, b) => b.valor - a.valor);
  return `<button type="button" class="back" data-back>‹ Voltar</button><span class="k">Investigação de gastos · ${d.uf}</span><h1 class="h radar-title">${esc(d.nome)}</h1><span class="muted">${esc(d.partido)} · base de ${radarDate()}</span>
    <section class="card hero"><span class="k">Cota acumulada em 2026</span><div class="signal-value">${rank.total === null ? 'Sem dado' : brl(rank.total, 2)}</div><span class="muted">${rank.share === null ? 'Limite indisponível' : `${radarPercent(rank.share)} de ${brl(rank.limit, 2)} de limite acumulado informado.`}</span><p class="radar-note muted">Inclui passagens. O limite considera o período disponível na fonte e varia por estado. Não é um limite mensal.</p></section>
    ${spendingChart(d)}
    <h2 class="h">${own.length} sinais para conferir</h2><p class="radar-note">Sinais exploratórios; podem ter explicações legítimas e não comprovam irregularidade.</p>
    ${own.length ? own.map(a => radarCard(a, true)).join('') : '<p class="note">Nenhum registro atende aos critérios nesta base. Isso não atesta ausência de problemas.</p>'}
    <section class="card"><span class="k">Notas disponíveis para conferência</span><p class="radar-note">As ${invoices.length} notas mais recentes exportadas, ordenadas por valor. São ${d.cota.notas} registros no total da coleta. Passagens aéreas não estão neste arquivo de notas.</p>
    <div>${invoices.map(invoice => { const url = invoiceURL(invoice); return `<article class="audit-invoice"><div class="signal-heading"><span>${dmy(invoice.data)}/2026 · ${esc(invoice.cat)}</span><strong class="mono">${brl(invoice.valor, 2)}</strong></div><b>${esc(invoice.fornecedor)}</b>${url ? `<a class="evidence-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Abrir documento na Câmara ↗</a>` : '<span class="muted">Documento sem link disponível.</span>'}</article>`; }).join('')}</div>
    <a class="evidence-link" href="${radarSource(d)}" target="_blank" rel="noopener noreferrer">Consultar a página oficial e demais despesas ↗</a></section>
    <section class="card">${radarMethod()}<button type="button" class="more" data-dep="${d.id}">Abrir ficha completa</button></section>`;
}
function exportSpendingAlerts() {
  const rows = [['Deputado', 'Partido', 'UF', 'Tipo', 'Valor (R$)', 'Explicação', 'Base de comparação (R$)', 'Critério', 'Fonte', 'Base recebida', 'Escopo']];
  for (const a of filteredSpendingAlerts()) {
    const d = byId[a.depId];
    const reference = a.type === 'categoria' ? d.cota.total : a.type === 'nota' ? SpendingAnalysis.rules.invoiceMinimum : a.baseline;
    const criterion = a.type === 'pico' ? 'Pelo menos 1,75x a mediana anterior e R$ 10.000 de aumento; mínimo de 3 meses anteriores sem lacunas.' : a.type === 'nota' ? 'Pelo menos R$ 10.000 entre as notas recentes incluídas.' : 'Pelo menos 50% da cota acumulada e R$ 30.000 na categoria.';
    rows.push([d.nome, d.partido, d.uf, radarType(a.type), a.amount.toFixed(2).replace('.', ','), radarExplanation(a), reference?.toFixed(2).replace('.', ',') || '', criterion, a.type === 'nota' ? invoiceURL(a.invoice) || '' : radarSource(d), DATA.geradoEm, 'Sinal exploratório, não comprova irregularidade. Picos: jan-jul/2026; notas: amostra recente; categorias: acumulado.']);
  }
  const cell = value => {
    const text = String(value);
    const safe = /^[\s\u0000-\u001f]*[=+@\-]/.test(text) || /^[\t\r\n]/.test(text) ? "'" + text : text;
    return '"' + safe.replaceAll('"', '""') + '"';
  };
  salvarArquivo(new Blob(['\uFEFF' + rows.map(row => row.map(cell).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' }), `painel-publico-sinais-${DATA.geradoEm}.csv`);
}
