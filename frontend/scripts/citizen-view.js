/* Telas do cidadão: "Gastos incomuns" (Home), "Alertas", "Políticos" (busca) e a ficha leve.
   Tudo em linguagem simples. */
const citizenState = {
  cache: new Map(), pending: new Set(),
  alerts: { type: 'pico,fornecedor', role: '', year: '', years: null, page: 1, items: [], total: null, loading: false, error: null, key: '', counts: null },
  politicians: { query: '', role: '', order: 'nome', page: 1, items: [], total: null, loading: false, error: null, key: '', averageSpend: null, coverage: null },
  profile: null, profileId: null, profileLoading: false, profileError: null,
};
/* Peças de identidade usadas em todas as abas */
function brandMark() {
  return `<span class="brand"><svg class="brand-ic" width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="8" fill="var(--accent)"/><rect x="6" y="13" width="3.2" height="7" rx="1.2" fill="#fff"/><rect x="11.4" y="9" width="3.2" height="11" rx="1.2" fill="#fff"/><rect x="16.8" y="5.5" width="3.2" height="14.5" rx="1.2" fill="#fff" opacity=".7"/></svg><span class="sr-only">Painel Público</span></span>`;
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
    <div class="sk-col">${rep(5, i => skL(`${[30, 38, 26, 92, 44][i]}%`, 10))}</div>${skL('96%')}${skL('72%')}
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
/* Valor curto para as linhas do gráfico: uma casa decimal em milhares, para não arredondar R$ 3.460 em "R$ 3 mil". */
const formatMonthAmount = v => v >= 1e6 ? formatCitizenAmount(v) : v >= 1e3 ? 'R$ ' + (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mil' : brl(v);
const citizenSourceUrl = person => {
  const [chamber, personNumber] = String(person.id || '').split(':');
  return chamber === 'camara' ? `https://www.camara.leg.br/deputados/${personNumber}?ano=2026` : chamber === 'senado' ? `https://www25.senado.leg.br/web/senadores/senador/-/perfil/${personNumber}` : null;
};

/* ---------- Cartão de alerta: o coração da consulta simples ---------- */
/* O selo diz o tipo do alerta, não uma gravidade; a cor só distingue o tipo de informação. */
function alertKind(a) {
  if (a.tipo === 'pico') return ['type-peak', 'Mês acima da referência'];
  if (a.tipo === 'fornecedor') return ['type-supplier', `${a.intermediacao ? 'Passagens intermediadas' : 'Concentração em fornecedor'}${a.parcial ? ' · parcial' : ''}`];
  return ['info', 'Para conferir'];
}
/* Motivos de mês não avaliado, curtos, para o histórico do cartão (o texto completo fica na cobertura). */
const PEAK_SKIP_LABELS = { prazo_aberto: 'provisório: prazo das notas aberto', historico_insuficiente: 'menos de 12 meses de histórico', sem_base: 'mês sem notas nos 12 anteriores', sem_referencia_colegas: 'sem referência dos colegas', sem_notas: 'sem notas' };
const capitalize = text => text ? text[0].toUpperCase() + text.slice(1) : text;
function alertVisualization(a) {
  if (a.tipo === 'pico' && a.serie?.length) {
    /* Só os números gravados pela regra. No cartão: a referência e cada mês marcado em barras na mesma escala,
       com o valor e a diferença escritos ao lado (sem legenda). Em "Ver histórico": a janela de referência, os
       meses marcados e os seguintes (provisórios quando o prazo das notas ainda está aberto), com a mediana. */
    const year = Number(a.ano || String(a.periodo).slice(0, 4));
    const points = a.serie.map(s => ({ ...s, ano: Number(s.ano || year) }));
    const keyOf = p => `${p.ano}-${p.mes}`;
    const months = (a.meses || [{ mes: a.mes, valor: a.valor, referencia: a.referencia, vezes: a.vezes }])
      .map(m => ({ ...m, ano: Number(m.ano || year) }))
      .map(m => ({ ...m, valor: Number.isFinite(m.valor) ? m.valor : points.find(p => keyOf(p) === keyOf(m))?.valor }))
      .filter(m => Number.isFinite(m.valor) && Number.isFinite(m.referencia) && m.referencia > 0);
    if (!months.length) return '';
    const marked = new Set(months.map(keyOf));
    const first = months[0], last = months[months.length - 1];
    const monthName = m => `${MONTH_NAMES_LONG[m.mes]} de ${m.ano}`;
    const shortLabel = p => `${SHORT_MONTHS[p.mes]}/${p.ano}`;
    const difference = m => `${formatMonthAmount(m.valor - m.referencia)} acima (+${Math.round((m.valor / m.referencia - 1) * 100).toLocaleString('pt-BR')}%)`;
    const max = Math.max(...months.map(m => Math.max(m.valor, m.referencia)), 1);
    const width = v => `${Math.max(1, v / max * 100).toFixed(1)}%`;
    const windowPoints = points.filter(p => (p.ano * 12 + p.mes) < (first.ano * 12 + first.mes));
    const windowSpan = windowPoints.length ? `${shortLabel(windowPoints[0])}–${shortLabel(windowPoints[windowPoints.length - 1])}` : '';
    const rolling = a.base && a.base !== 'year';
    const headline = months.length === 1
      ? `${capitalize(MONTH_NAMES_LONG[first.mes])} ficou ${formatMonthAmount(first.valor - first.referencia)} acima da referência`
      : `${capitalize(MONTH_NAMES_LONG[first.mes])} a ${MONTH_NAMES_LONG[last.mes]} ficaram acima da referência`;
    const bar = (label, value, cls, note = '') => `<div class="citizen-peak-bar ${cls}">
        <span class="citizen-peak-bar-label">${label}</span>
        <span class="citizen-peak-bar-row"><span class="citizen-peak-bar-track"><i style="width:${width(value)}"></i></span><b>${formatMonthAmount(value)}</b></span>
        ${note ? `<span class="citizen-peak-bar-note">${note}</span>` : ''}
      </div>`;
    /* Uma barra de referência por valor distinto: num alerta de vários meses, cada mês tem a sua. */
    const bars = months.length === 1
      ? bar(`Referência${windowSpan ? ` · ${windowSpan}` : ''}`, first.referencia, 'reference') + bar(capitalize(monthName(first)), first.valor, 'flagged', difference(first))
      : bar(`Referência de ${MONTH_NAMES_LONG[first.mes]}${windowSpan ? ` · ${windowSpan}` : ''}`, first.referencia, 'reference')
        + months.map(m => bar(capitalize(monthName(m)), m.valor, 'flagged', `${difference(m)} sobre a referência de ${formatMonthAmount(m.referencia)}`)).join('');
    /* Histórico: colunas na escala do histórico, linha tracejada na referência do primeiro mês marcado. */
    const historyMax = Math.max(...points.map(p => p.valor || 0), first.referencia, 1);
    const height = v => `${Math.max(2, v / historyMax * 100).toFixed(1)}%`;
    const history = points.map(p => {
      const flagged = marked.has(keyOf(p)), after = (p.ano * 12 + p.mes) > (last.ano * 12 + last.mes);
      const note = p.valor == null ? 'sem notas' : !flagged && after && p.estado && p.estado !== 'evaluated' && p.estado !== 'flagged' ? PEAK_SKIP_LABELS[p.estado] || '' : '';
      const cls = flagged ? 'flagged' : note && note.startsWith('provisório') ? 'provisional' : '';
      const showLabel = flagged || p === points[0] || p.mes === 1 || p === points[points.length - 1];
      return `<div class="citizen-peak-col ${cls}" title="${esc(`${shortLabel(p)}: ${p.valor == null ? 'sem notas' : brl(p.valor)}${note && p.valor != null ? ` (${note})` : ''}`)}">
          <span class="citizen-peak-col-bar">${p.valor == null ? '' : `<i style="height:${height(p.valor)}"></i>`}</span>
          <small>${showLabel ? `${SHORT_MONTHS[p.mes]}${p.mes === 1 || p === points[0] ? `/${String(p.ano).slice(2)}` : ''}` : ''}</small>
        </div>`;
    }).join('');
    const provisional = points.some(p => p.estado === 'prazo_aberto' && (p.ano * 12 + p.mes) > (last.ano * 12 + last.mes));
    const spoken = [`${headline}.`, ...months.map(m => `${capitalize(monthName(m))}: ${brl(m.valor)}; referência ${brl(m.referencia)}; ${difference(m)}.`)].join(' ');
    return `<figure class="citizen-peak">
      <figcaption class="sr-only">${esc(spoken)}</figcaption>
      <p class="citizen-peak-headline" aria-hidden="true">${esc(headline)}${months.length === 1 ? ` <span>(+${Math.round((first.valor / first.referencia - 1) * 100).toLocaleString('pt-BR')}%)</span>` : ''}</p>
      <div class="citizen-peak-bars" aria-hidden="true">${bars}</div>
      <p class="citizen-peak-foot">Referência: mediana ${rolling ? 'dos 12 meses anteriores' : 'dos meses anteriores do mesmo ano'}.</p>
      <details class="citizen-peak-history">
        <summary>Ver histórico e notas →</summary>
        <div class="citizen-peak-cols" role="img" aria-label="${esc(points.map(p => `${shortLabel(p)}: ${p.valor == null ? 'sem notas' : brl(p.valor)}`).join('; '))}">
          <span class="citizen-peak-median" style="bottom:calc(15px + (100% - 19px) * ${(first.referencia / historyMax).toFixed(3)})"><em>mediana ${formatMonthAmount(first.referencia)}</em></span>
          ${history}
        </div>
        ${provisional ? '<p class="citizen-peak-foot"><i class="citizen-peak-swatch provisional"></i>Listrado: provisório, o prazo de apresentação das notas ainda está aberto.</p>' : ''}
        ${citizenSourceUrl(a.pessoa || {}) ? `<a class="citizen-peak-notes" href="${esc(citizenSourceUrl(a.pessoa || {}))}" target="_blank" rel="noopener">Ver as notas na fonte oficial ↗</a>` : ''}
      </details>
    </figure>`;
  }
  if (a.tipo === 'fornecedor' && a.parte) {
    return `<div class="citizen-share" role="img" aria-label="${Math.round(a.parte * 100)}% para ${esc(a.fornecedor)}">
      <div class="citizen-sharebar"><i style="width:${a.parte * 100}%"></i></div>
      <div class="citizen-sharelbl"><span><b>${Math.round(a.parte * 100)}%</b> ${esc(citizenName(a.fornecedor))}</span><span>${100 - Math.round(a.parte * 100)}% outros</span></div>
      ${Number.isFinite(a.total) ? `<div class="citizen-sharelbl"><span>${esc(formatCitizenAmount(a.valor))} de ${esc(formatCitizenAmount(a.total))}</span><span>${Number.isInteger(a.mesesComNotas) ? `${a.mesesComNotas} ${a.mesesComNotas === 1 ? 'mês' : 'meses'} com notas` : ''}</span></div>` : ''}
    </div>`;
  }
  return '';
}
/* No pico com gráfico, as barras já dizem valor, referência e diferença: a frase só repetiria. */
function alertStatement(a) {
  return a.tipo === 'pico' && alertVisualization(a) ? '' : `<p class="citizen-statement">${esc(a.frase)}</p>`;
}
function alertExplanation(a) {
  if (a.tipo === 'pico') return `Aparece quando o gasto de um mês passa de 1,75 vez a referência da própria pessoa, a diferença é de pelo menos R$ 10 mil e o mês também fica acima do gasto mensal típico dos(as) colegas${Number.isFinite(a.piso) ? ` (${formatCitizenAmount(a.piso)} em ${esc(a.ano || String(a.periodo).slice(0, 4))})` : ''}. ${a.base && a.base !== 'year' ? 'A referência é o valor do meio (a mediana) dos 12 meses anteriores, atravessando o ano, todos com notas. Como o mandato começa em fevereiro de 2023, a avaliação começa em fevereiro de 2024.' : 'A referência é o valor do meio (a mediana) dos meses anteriores do mesmo ano, com pelo menos 3 meses sem lacuna.'} Só entram meses cujo prazo de apresentação das notas já tinha terminado na data da coleta: 90 dias na Câmara; no Senado, até o fim de abril do ano seguinte. Meses seguidos marcados contam como um alerta só. Novembro e dezembro também são avaliados; o cartão avisa que o saldo não usado da cota se acumula no ano e expira em 31 de dezembro. A mesma regra vale para todos(as).`;
  if (a.tipo === 'fornecedor') return `Aparece quando metade ou mais do dinheiro da cota no ano foi para uma mesma empresa, somando pelo menos R$ 30 mil.${a.parcial ? ` Período parcial: o cálculo usa as notas disponíveis de ${esc(a.periodoObservado || 'o ano')}, e o ano ainda pode receber notas.` : ''} ${a.intermediacao ? ' Aqui, a maioria das notas cita uma companhia aérea que não é o fornecedor pago: o fornecedor é uma agência que intermediou passagens. O critério usa a companhia citada no registro oficial do Senado; quando o registro traz o nome da própria agência, não há como saber a companhia.' : ' Pagamentos recorrentes podem ser compatíveis com um contrato; vale conferir as notas.'}`;
  return `Aparece para toda nota de R$ 10 mil ou mais. É só um corte de valor.`;
}
/* Contexto, não atenuante: o alerta continua; o cartão só informa a regra do saldo anual. */
function alertYearEndNote(a) {
  const months = Array.isArray(a.fimDeAno) ? a.fimDeAno : [];
  if (!months.length) return '';
  return `<p class="citizen-context">Fim do ano: o saldo da cota não usado nos meses anteriores se acumula e expira em 31 de dezembro. ${months.length > 1 ? 'Estes meses podem' : `${MONTH_NAMES_LONG[months[0]][0].toUpperCase()}${MONTH_NAMES_LONG[months[0]].slice(1)} pode`} incluir gastos feitos com esse saldo antes de ele expirar.</p>`;
}
function alertCard(a, opts = {}) {
  const [cls, label] = alertKind(a), p = a.pessoa || {};
  return `<article class="card citizen-alert" data-kind="${cls}">
    <div class="citizen-top"><span class="citizen-chip ${cls}"><i></i>${label}</span><span class="muted">${a.tipo === 'pico' ? SHORT_MONTHS[a.mes] + '/' + String(a.periodo).slice(0, 4) : 'em ' + String(a.periodo).slice(0, 4)}</span></div>
    ${opts.semPessoa ? '' : `<button type="button" class="citizen-who" data-politician="${esc(p.id)}">${citizenAvatar(p, 40)}<span><b>${esc(citizenName(p.name))}</b><small>${citizenRoleDescription(p)}</small></span></button>`}
    <h3 class="citizen-title">${esc(a.titulo)}</h3>
    ${alertVisualization(a)}
    ${alertStatement(a)}
    ${a.contexto?.frase ? `<p class="citizen-context">${esc(a.contexto.frase)}</p>` : ''}
    ${alertYearEndNote(a)}
    <details class="citizen-why"><summary>Por que apareceu aqui?</summary><p>${alertExplanation(a)}</p><p class="muted">A regra mostra variação de gasto ou concentração em fornecedor; não mede irregularidade. Confira as notas na fonte oficial.</p></details>
    ${Array.isArray(a.fontesOficiais) && a.fontesOficiais.length ? `<p class="muted">Detalhamento oficial: ${a.fontesOficiais.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.label)} ↗</a>`).join(', ')}.${a.notaDocumento ? ` ${esc(a.notaDocumento)}` : ''}</p>` : ''}
    <div class="citizen-actions">${opts.semPessoa ? '' : `<button type="button" class="fchip" data-politician="${esc(p.id)}">Ver a ficha</button>`}${citizenSourceUrl(p) ? `<a class="fchip" href="${esc(citizenSourceUrl(p))}" target="_blank" rel="noopener">Conferir na fonte ↗</a>` : ''}</div>
  </article>`;
}

/* ---------- Home: "Gastos incomuns" ---------- */
function homeAlertCard() {
  const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
  const data = citizenState.cache.get(path);
  if (!data) {
    if (!citizenState.pending.has(path)) { citizenState.pending.add(path); citizenGet(path).then(() => { citizenState.pending.delete(path); if (state.view === 'home') rerender(); }).catch(() => { citizenState.pending.delete(path); citizenState.cache.set(path, { error: true }); if (state.view === 'home') rerender(); }); }
    return `<section class="citizen-home"><div class="citizen-head"><h2 class="h">Alertas da cota</h2></div><div class="carousel citizen-carousel">${skel('alerta', 3)}</div></section>`;
  }
  if (data.error) return `<section class="citizen-home"><div class="citizen-head"><div><h2 class="h">Alertas da cota</h2><span class="muted">Os alertas da Câmara e do Senado não carregaram.</span></div></div><section class="card"><p>Não deu para carregar os alertas agora.</p><button type="button" class="more" data-home-retry>Tentar de novo</button></section></section>`;
  const alerts = data.itens;
  return `<section class="citizen-home">
    <div class="citizen-head"><div><h2 class="h">Alertas da cota</h2><span class="muted">Meses acima da referência e concentração em fornecedor nas notas do mandato${data.periodo ? ` (${esc(citizenQuotaPeriod(data.periodo.inicio, data.periodo.fim))})` : ''} de deputados(as) e senadores(as), pelas mesmas regras para todos(as), dos mais recentes aos mais antigos. Não indicam irregularidade.</span></div></div>
    <div class="carousel citizen-carousel">${alerts.map(alert => alertCard(alert)).join('')}</div>
    <button type="button" class="opt citizen-cta" data-go="alerts">Ver os ${data.total} alertas</button>
  </section>`;
}

/* ---------- Aba "Alertas" ---------- */
function alertFilterKey() { const l = citizenState.alerts; return `tipo=${l.type}&cargo=${l.role}&ano=${l.year}`; }
function loadAlerts(more) {
  const l = citizenState.alerts, key = alertFilterKey();
  if (!more && l.key === key) return;
  if (!more) { l.key = key; l.page = 1; l.items = []; l.total = null; }
  l.loading = true; l.error = null;
  const qs = `/api/c/radar?pageSize=12&page=${l.page}&tipo=${l.type}${l.role ? '&cargo=' + l.role : ''}${l.year ? '&ano=' + l.year : ''}`;
  citizenGet(qs).then(d => { if (l.key !== key) return; l.items = l.items.concat(d.itens); l.total = d.total; l.counts = d.contagem; l.years = d.anos || []; l.span = d.periodo; l.loading = false; if (state.view === 'alerts') rerender(); })
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
    <span class="k">${alertState.year ? `Alertas em ${esc(alertState.year)}` : `Alertas no mandato${alertState.span ? ` · ${esc(citizenQuotaPeriod(alertState.span.inicio, alertState.span.fim))}` : ''}`}</span>
    <div class="huge">${alertCounts ? totalCount.toLocaleString('pt-BR') : '—'}</div>
    <span class="muted">alertas pelas regras do painel, para conferir. Não indicam irregularidade.</span>
    ${totalCount ? `<div class="stack" role="img" aria-label="${monthlyPeakCount} picos num mês e ${supplierConcentrationCount} concentrações numa empresa"><i style="width:${monthlyPeakCount / totalCount * 100}%;background:var(--accent-2)"></i><i style="width:${supplierConcentrationCount / totalCount * 100}%;background:var(--hero-fg)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Mês acima da referência · ${monthlyPeakCount}</span><span><i style="background:var(--hero-fg)"></i>Concentração em fornecedor · ${supplierConcentrationCount}</span></div>` : ''}
    ${topPeople.length ? `<span class="k" style="margin-top:6px">Valor das despesas nos alertas do mandato</span>
    <div class="faces citizen-top5">${topPeople.map(person => `<button type="button" class="face" data-politician="${esc(person.id)}">${citizenAvatar(person, 54)}<span>${esc(citizenName(person.name).split(' ')[0])}</span><em>${person.valorAlertas ? esc(formatCitizenAmount(person.valorAlertas)) + (person.valorAlertasParcial ? ' · parcial' : '') : `${person.alertas} ${person.alertas === 1 ? 'ALERTA' : 'ALERTAS'}`}</em></button>`).join('')}</div>
    <span class="muted">Soma das despesas observadas nos alertas, cada nota contada uma vez. Não é estimativa de prejuízo. "Parcial": inclui concentração calculada com o ano ainda aberto.</span>` : ''}
  </section>`;
}
function alertsView() {
  const l = citizenState.alerts; loadAlerts(false); loadTopAlerts();
  const types = [['pico,fornecedor', 'Tudo'], ['pico', 'Mês acima da referência'], ['fornecedor', 'Concentração em fornecedor']];
  const roles = [['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']];
  return `${pageHead('Entenda em 1 minuto', 'Alertas', 'Cada cartão mostra um mês acima da referência ou uma concentração em fornecedor na cota de um(a) deputado(a) ou senador(a), segundo regras fixas e iguais para todos(as). Toque para ver de quem é e conferir na fonte.')}
    ${alertSummaryCard()}
    <div class="citizen-filters">
      <div class="chips" role="group" aria-label="Tipo de alerta">${types.map(([k, n]) => `<button type="button" class="fchip" data-alert-type="${k}" aria-pressed="${l.type === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Cargo">${roles.map(([k, n]) => `<button type="button" class="fchip" data-alert-role="${k}" aria-pressed="${l.role === k}">${n}</button>`).join('')}</div>
      ${l.years?.length > 1 || l.year ? `<div class="chips" role="group" aria-label="Ano">${[['', 'Mandato'], ...(l.years || []).map(y => [String(y.ano), String(y.ano)])].map(([k, n]) => `<button type="button" class="fchip" data-alert-year="${k}" aria-pressed="${l.year === k}">${n}</button>`).join('')}</div>` : ''}
    </div>
    ${l.error ? `<section class="card"><p>Não deu para carregar os alertas agora.</p><p class="muted">${esc(l.error)}</p><button type="button" class="more" data-alert-retry>Tentar de novo</button></section>` : ''}
    ${l.total !== null ? `<span class="muted" role="status">${l.total} ${l.total === 1 ? 'alerta' : 'alertas'} neste filtro</span>` : ''}
    ${l.items.map(a => alertCard(a)).join('')}
    ${l.loading && !l.error ? skel('alerta', l.items.length ? 1 : 3) : l.total !== null && l.items.length < l.total ? `<button type="button" class="opt citizen-more" data-alert-more>Mostrar mais</button>` : ''}
    <section class="card citizen-how"><span class="k">Como funciona</span>
      <p><b>Mês acima da referência:</b> o gasto do mês passou de 1,75 vez a mediana dos 12 meses anteriores da própria pessoa. A avaliação começa em fevereiro de 2024, quando há 12 meses de mandato para comparar.</p>
      <p><b>Concentração em fornecedor:</b> metade ou mais do dinheiro do ano foi para a mesma empresa, ano a ano desde 2023.</p>
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
/* "fev/2023–set/2026" a partir de "AAAA-MM"; a cota das duas Casas conta desde fev/2023. */
function citizenQuotaPeriod(start, end) {
  const label = value => typeof value === 'string' && /^\d{4}-\d{2}$/.test(value)
    ? `${['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(value.slice(5)) - 1]}/${value.slice(0, 4)}` : null;
  const from = label(start), to = label(end);
  return from && to ? (from === to ? from : `${from}–${to}`) : '';
}
function politicianRow(person, max) {
  const hasExpenseData = person.hasExpenseData === undefined ? person.gastoMensal != null : Boolean(person.hasExpenseData);
  const averageSpend = citizenState.politicians.averageSpend?.[person.role]?.media;
  const monthly = person.gastoMensal;
  const aboveAverage = hasExpenseData && averageSpend && monthly > averageSpend * 1.25;
  const roleLabel = person.role === 'senador' ? 'Senador(a)' : 'Deputado(a)';
  const barWidth = hasExpenseData && monthly > 0 ? Math.max(2, monthly / max * 100) : 0;
  const spendLabel = hasExpenseData && Number.isFinite(monthly) ? (monthly === 0 ? 'R$ 0' : formatCitizenAmount(monthly)) : 'Sem dados';
  return `<button type="button" class="citizen-row" data-politician="${esc(person.id)}">${citizenAvatar(person, 48)}<span class="citizen-rowtxt"><b>${esc(citizenName(person.name))}</b><small>${[roleLabel, person.party, person.uf].filter(Boolean).map(esc).join(' · ')}</small>
      <span class="citizen-rowbar"><i style="width:${barWidth}%" class="${aboveAverage ? 'hi' : ''}"></i></span></span>
    <span class="citizen-rowval"><b class="mono">${spendLabel}</b>${person.alertas ? `<span class="citizen-chip info citizen-mini"><i></i>${person.alertas} ${person.alertas === 1 ? 'alerta' : 'alertas'}</span>` : `<small>${hasExpenseData ? aboveAverage ? 'acima da média' : 'na cota' : 'sem despesa observada'}</small>`}${citizenState.politicians.order === 'alertas' && person.valorAlertas ? `<small>${esc(formatCitizenAmount(person.valorAlertas))} em alertas${person.valorAlertasParcial ? ' · parcial' : ''}</small>` : ''}</span></button>`;
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
  if (!p.items.length) return `<section class="card"><p>Ninguém encontrado com “${esc(p.query)}”.</p><p class="muted">A busca mostra só deputados(as) federais e senadores(as) com mandato em curso. Eleitos(as) em 2026 aparecem a partir da posse, em 1º de fevereiro de 2027; vereadores(as), prefeitos(as) e governadores(as) não fazem parte da busca.</p><p class="muted">Tente só o sobrenome, a sigla do partido (PT, PL…) ou do estado (SP, MG…).</p></section>`;
  const observedSpending = p.items.filter(person => person.gastoMensal != null).map(person => person.gastoMensal);
  const max = Math.max(1, ...observedSpending, ...Object.values(p.averageSpend || {}).map(item => (item.media || 0) * 1.5));
  return `<span class="muted" role="status">${p.total} ${p.total === 1 ? 'pessoa' : 'pessoas'} · gasto médio da cota por mês</span><section class="card citizen-list">${p.items.map(x => politicianRow(x, max)).join('')}</section>
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
  return `${pageHead('Deputados(as) e senadores(as)', 'Políticos', 'Busque qualquer um(a) e veja quanto gasta da cota por mês, com os alertas.')}
    <div id="citizen-politician-summary" class="citizen-roster-summary" role="status">${politicianCoverageHTML(p.coverage)}</div>
    <label class="search" for="citizen-search"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="citizen-search" type="search" placeholder="Nome, partido ou estado" value="${esc(p.query)}" autocomplete="off"></label>
    <div class="citizen-filters">
      <div class="chips" role="group" aria-label="Cargo">${[['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']].map(([k, n]) => `<button type="button" class="fchip" data-politician-role="${k}" aria-pressed="${p.role === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Ordenar">${[['nome', 'A–Z'], ['gasto', 'Quem mais gastou'], ['alertas', 'Valor das despesas nos alertas']].map(([k, n]) => `<button type="button" class="fchip" data-politician-order="${k}" aria-pressed="${p.order === k}">${n}</button>`).join('')}</div>
    </div>
    <div class="citizen-actions"><button type="button" class="fchip" data-cmp-start="">Comparar dois(duas) lado a lado →</button><button type="button" class="fchip" data-go="parties">Comparar partidos →</button><button type="button" class="fchip" data-go="attendance">Presença dos deputados →</button></div>
    <div id="citizen-politician-list" class="citizen-stack" aria-live="polite">${politicianListHTML()}</div>
    <div id="citizen-politician-notes">${politicianCoverageNotesHTML(p.coverage)}</div>
    <span class="src">Valor: média mensal da cota pelas notas publicadas, nos meses com notas. Deputados(as) e senadores(as): desde fev/2023, início da legislatura atual. Valores da época, sem correção pela inflação. Não é salário. A barra roxa mais forte indica gasto acima da média.</span>`;
}

/* ---------- Ficha leve (qualquer deputado ou senador) ---------- */
function loadProfile(id) {
  if (citizenState.profileId === id) return;
  citizenState.profileId = id; citizenState.profile = null; citizenState.profileError = null; citizenState.profileLoading = true;
  citizenGet('/api/c/politico/' + encodeURIComponent(id)).then(d => { if (citizenState.profileId !== id) return; citizenState.profile = d; citizenState.profileLoading = false; if (state.view === 'profile') rerender(); })
    .catch(e => { if (citizenState.profileId !== id) return; citizenState.profileLoading = false; citizenState.profileError = citizenErrorMessage(e); if (state.view === 'profile') rerender(); });
}
function profileExpenseAnswer(profileRecord, person, hasExpenseData) {
  const monthly = profileRecord.mediaMensal ?? null, period = profileRecord.periodo || {};
  const averageSpend = profileRecord.media || 0, difference = averageSpend && monthly != null ? monthly / averageSpend - 1 : 0;
  const totalLabel = monthly === 0 ? '0' : Math.round((monthly || 0) / 1e3).toLocaleString('pt-BR') + ' mil';
  const verdict = Math.abs(difference) < 0.1 ? 'Parecido com a média' : `${Math.round(Math.abs(difference) * 100)}% ${difference > 0 ? 'acima' : 'abaixo'} da média`;
  const salaryNote = person.role === 'senador'
    ? `<p class="citizen-salary">Salário efetivamente pago não disponível nesta base de forma individual. Subsídio bruto de referência do cargo: ${brl(PROFILE_SALARY[person.role].amount)}/mês.</p>`
    : `<p class="citizen-salary">Salário à parte: ${brl(PROFILE_SALARY[person.role].amount)}/mês</p>`;
  return `<section class="card hero citizen-answer" data-profile-answer="expenses">
    <h2 class="h">Quanto custa?</h2><span class="k">Cota parlamentar · média por mês</span>
    <div class="huge">${hasExpenseData && monthly != null ? `<small>R$</small>${totalLabel}<small>/mês</small>` : 'Sem dados'}</div>
    ${hasExpenseData && monthly != null ? `<p class="muted">${esc(citizenQuotaPeriod(period.inicio, period.fim))}, ${period.meses} ${period.meses === 1 ? 'mês' : 'meses'} com notas · total ${formatCitizenAmount(profileRecord.total)}</p>` : ''}
    <p class="citizen-cost-scope">Só a cota parlamentar. ${person.role === 'senador' ? 'Remuneração e equipe do gabinete do Senado não identificadas para esta ficha.' : 'Salário, auxílios e verba de gabinete desta pessoa não estão compostos nesta ficha.'} Não compare com o custo de deputados(as) que soma salário, auxílios, cota e gabinete.</p>
    ${salaryNote}
    ${hasExpenseData && monthly != null ? (averageSpend ? `<div class="citizen-vs">
      <div><span>${esc(citizenName(person.name).split(' ')[0])}</span><b class="mono">${monthly === 0 ? 'R$ 0' : formatCitizenAmount(monthly)}</b></div><div class="citizen-vsbar"><i style="width:${Math.min(100, monthly / Math.max(monthly, averageSpend) * 100)}%"></i></div>
      <div><span>Média dos(as) ${ROLE_LABELS_PLURAL[person.role] || 'colegas'}</span><b class="mono">${formatCitizenAmount(averageSpend)}</b></div><div class="citizen-vsbar avg"><i style="width:${Math.min(100, averageSpend / Math.max(monthly, averageSpend) * 100)}%"></i></div>
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
  const presencePeriod = !senate && presence ? citizenQuotaPeriod(presence.inicio, presence.fim) : '';
  return `${head}<span class="k">Presença no Plenário · ${senate ? '2026' : presencePeriod || 'mandato'}</span>
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
/* As duas regras de alerta, iguais para todos(as); detalhes na aba Alertas. */
const ALERT_RULES_HTML = `<ul class="citizen-alert-rules">
    <li><b>Mês acima da referência:</b> um mês com gasto 1,75 vez maior que a mediana dos 12 meses anteriores da própria pessoa, com pelo menos R$ 10 mil de diferença e acima do gasto mensal típico dos(as) colegas. Só meses com o prazo de apresentação das notas encerrado; a avaliação começa em fev/2024.</li>
    <li><b>Concentração em fornecedor:</b> metade ou mais da cota do ano paga a uma só empresa, somando pelo menos R$ 30 mil.</li>
  </ul>`;
const ALERT_MONTHS = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
/* "abr–jun" para meses seguidos; senão a lista. */
function alertMonthList(months, year) {
  const sorted = [...(months || [])].sort((a, b) => a - b);
  if (!sorted.length) return '';
  const runs = [];
  sorted.forEach(m => { const last = runs.at(-1); if (last && m === last.at(-1) + 1) last.push(m); else runs.push([m]); });
  return runs.map(run => run.length === 1 ? ALERT_MONTHS[run[0]] : `${ALERT_MONTHS[run[0]]}–${ALERT_MONTHS[run.at(-1)]}`).join(', ') + `/${year}`;
}
/* O que cada regra conseguiu avaliar para a pessoa. "Nenhum alerta" só vale para o que foi avaliado. */
function alertCoverageState(coverage) {
  const rows = Array.isArray(coverage) ? coverage : [];
  const evaluated = rows.some(r => (r.regra === 'pico' && r.avaliados?.length) || (r.regra === 'fornecedor' && r.avaliado));
  const lines = rows.map(r => {
    if (r.regra === 'fornecedor') return r.avaliado
      ? `<li><b>Concentração em fornecedor:</b> avaliada nas notas de ${esc(r.periodo)}${r.parcial ? ' (período parcial: o ano ainda pode receber notas)' : ''}.</li>`
      : `<li><b>Concentração em fornecedor:</b> não avaliada em ${r.ano} (sem total positivo de notas).</li>`;
    const skipped = (r.naoAvaliados || []).filter(n => n.meses?.length).map(n => `${alertMonthList(n.meses, r.ano)}: ${esc(n.texto)}`);
    return `<li><b>Mês acima da referência:</b> ${r.avaliados?.length ? `avaliados ${alertMonthList(r.avaliados, r.ano)}` : `nenhum mês de ${r.ano} pôde ser avaliado`}.${skipped.length ? ` Não avaliados: ${skipped.join('; ')}.` : ''}</li>`;
  });
  return { evaluated, html: lines.length ? `<ul class="citizen-alert-rules">${lines.join('')}</ul>` : '' };
}
function profileAlertAnswer(alerts, coverage) {
  const top = alerts[0], state = alertCoverageState(coverage);
  return `<section class="card citizen-answer citizen-answer-alert" data-profile-answer="alerts">
    <h2 class="h">Algum alerta na cota?</h2>
    ${top ? `<span class="fchip citizen-alert-count">${alerts.length} ${alerts.length === 1 ? 'alerta' : 'alertas'}</span>
      <h3 class="citizen-title">${esc(top.titulo)}</h3>${alertVisualization(top)}${alertStatement(top)}${top.contexto?.frase ? `<p class="citizen-context">${esc(top.contexto.frase)}</p>` : ''}${alertYearEndNote(top)}
      <button type="button" class="more" data-profile-open="alerts">${alerts.length > 1 ? `Ver os demais alertas (${alerts.length - 1})` : 'Ver alerta em detalhe'} →</button>`
    : state.evaluated ? `<p class="citizen-empty">Nenhum alerta nos meses avaliados</p>
      ${state.html}<p class="muted">As regras são as mesmas para todos(as). Isso não é uma auditoria completa das notas.</p>`
    : `<p class="citizen-empty">Dados insuficientes para avaliar</p>${state.html || '<p class="muted">Não há notas do mandato desta pessoa para as regras de alerta.</p>'}`}
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
/* Senadores eleitos em 2018 começaram o mandato antes do recorte comum de fev/2023. */
function profileMandateStartNote(mandate) {
  const match = /desde (\d{2})\/(\d{2})\/(\d{4})/.exec(mandate?.exercicio || '');
  if (!match || `${match[3]}-${match[2]}` >= '2023-02') return '';
  const month = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'][Number(match[2]) - 1];
  return ` O mandato começou em ${month} de ${match[3]}; antes de fev/2023 a cota não entra aqui, para seguir a mesma regra da Câmara.`;
}
function profileExpenseDetails(f, hasExpenseData, cost = null, mandate = null) {
  if (!hasExpenseData) return '<p class="muted">Não há lançamentos observados para calcular total, média, série mensal ou alertas.</p>';
  const maxMonth = Math.max(1, ...f.meses.map(month => month.valor));
  const categoryTotal = f.categorias.reduce((sum, category) => sum + category.valor, 0) || 1;
  const period = f.periodo || {}, periodLabel = citizenQuotaPeriod(period.inicio, period.fim);
  const complement = f.complementoMoradia;
  /* Um gráfico por ano (o mais recente primeiro), para caber no celular. */
  const years = [...new Set(f.meses.map(month => month.year))].sort((a, b) => b - a);
  const isPeak = month => f.alertas.some(alert => alert.tipo === 'pico' && String(alert.periodo).startsWith(`${month.year}-`)
    && (alert.meses || [{ mes: alert.mes }]).some(marked => marked.mes === month.month));
  const yearChart = year => `<p class="k">${year}</p><div class="citizen-months">${f.meses.filter(month => month.year === year).map(month => `<div><small>${Math.round(month.valor / 1e3)}k</small><b class="mt"><i style="height:${month.valor > 0 ? Math.max(2, month.valor / maxMonth * 100) : 0}%" class="${isPeak(month) ? 'hot' : ''}"></i></b><span>${SHORT_MONTHS[month.month]}</span></div>`).join('')}</div>`;
  return `<section class="citizen-detail-part citizen-expense-original"><h3 class="k">Cota parlamentar · ${esc(periodLabel || 'total')}</h3>
    <p><b>Total da cota${periodLabel ? ` de ${esc(periodLabel)}` : ''}:</b> ${brl(f.total, 2)}, somando todas as notas publicadas até agora.${Number.isFinite(f.mediaMensal) ? ` Média de ${brl(f.mediaMensal, 2)} por mês nos ${period.meses} meses com notas.` : ''}</p>
    <p class="muted">${f.pessoa?.role === 'deputado' ? 'Mandato atual, desde fev/2023.' : `Desde fev/2023, início da legislatura atual.${profileMandateStartNote(mandate)}`} Valores da época, sem correção pela inflação.</p>
    ${profileQuotaDifferenceNote(f, cost)}
    ${complement && Number.isFinite(complement.valor) ? `<p class="muted">À parte: complemento do auxílio-moradia lançado na cota, ${brl(complement.valor, 2)} em ${complement.notas} ${complement.notas === 1 ? 'nota' : 'notas'}. A Câmara publica esse valor como negativo; ele não reduz o total acima.</p>` : ''}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Mês a mês</h3>
    ${years.map(yearChart).join('')}
    <p class="muted">Os últimos meses ainda podem crescer: as notas são publicadas com atraso.</p>
  </section>
  <section class="citizen-detail-part"><h3 class="k">Com o que gastou</h3>
    ${f.categorias.slice(0, 6).map(category => `<div class="citizen-bar"><div><span>${esc(category.nome)}</span><b class="mono">${category.valor === 0 ? 'R$ 0' : formatCitizenAmount(category.valor)}</b></div><div class="bar"><i style="width:${f.categorias[0].valor ? category.valor / f.categorias[0].valor * 100 : 0}%"></i></div><small class="muted">${Math.round(category.valor / categoryTotal * 100)}% do total</small></div>`).join('')}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Para quem foi o dinheiro</h3>
    ${f.fornecedores.map(x => `<div class="citizen-bar"><div><span>${esc(citizenName(x.name))}</span><b class="mono">${formatCitizenAmount(x.valor)}</b></div><div class="bar"><i style="width:${f.total ? x.valor / f.total * 100 : 0}%;background:var(--accent)"></i></div><small class="muted">${f.total ? Math.round(x.valor / f.total * 100) : 0}% do total · ${x.notas} ${x.notas === 1 ? 'nota' : 'notas'}</small></div>`).join('')}
  </section>
  <section class="citizen-detail-part"><h3 class="k">Maiores notas${periodLabel ? ` · ${esc(periodLabel)}` : ''}</h3>
    ${f.maiores.map(m => `<${m.documentUrl ? `a href="${esc(m.documentUrl)}" target="_blank" rel="noopener"` : 'div'} class="item"><span class="mono muted" style="width:52px">${SHORT_MONTHS[m.month]}/${String(m.year).slice(2)}</span><span class="g"><span>${esc(citizenName(m.fornecedor || 'Fornecedor não informado'))}</span><span class="muted">${esc(m.categoria)}${m.documentUrl ? ' · ver nota ↗' : ''}</span></span><span class="mono" style="font-weight:700">${brl(m.valor)}</span></${m.documentUrl ? 'a' : 'div'}>`).join('')}
  </section>`;
}
/* A cota do custo do mandato usa só os meses com as quatro partes; esta média usa todos os meses com notas. */
function profileQuotaDifferenceNote(f, cost) {
  const quota = cost?.parts?.quota?.usedMonthsAverageCents, used = Array.isArray(cost?.usedMonths) ? cost.usedMonths.length : 0;
  if (!Number.isFinite(f.mediaMensal) || !Number.isSafeInteger(quota) || !used || Math.round(f.mediaMensal * 100) === quota) return '';
  return `<p class="muted">No custo do mandato acima, a cota aparece como ${brl(quota / 100, 2)} por mês porque usa só os ${used} ${used === 1 ? 'mês' : 'meses'} com salário, auxílios, cota e gabinete publicados juntos. Aqui entram todos os ${f.periodo?.meses} meses com notas da cota; por isso os valores são diferentes.</p>`;
}
/* Cartão para compartilhar: as mesmas três respostas da ficha, em números curtos. */
function profileShareCard(f, shared, alerts, hasExpenseData) {
  const person = shared.person, senate = person.role === 'senador', cost = shared.cost;
  const average = person.role === 'deputado' && cost ? profileCostMoney(cost.monthlyAverageCents) : null;
  const costRow = average !== null
    ? { label: 'Custa em média por mês', values: [average], notes: [`${profileCostMonthList(cost.usedMonths)} · salário, auxílios, cota e gabinete`] }
    : { label: 'Cota parlamentar por mês', values: [hasExpenseData && Number.isFinite(f.mediaMensal) ? formatCitizenAmount(f.mediaMensal) : 'Sem dados'],
      notes: [hasExpenseData ? `média de ${citizenQuotaPeriod(f.periodo?.inicio, f.periodo?.fim)}` : 'ausência de dado não é zero'] };
  const presence = shared.presence, registered = senate ? shared.registeredPresence : null;
  const workRow = presence
    ? { label: senate ? 'Presença no Plenário em 2026' : `Presença no Plenário · ${citizenQuotaPeriod(presence.inicio, presence.fim) || 'mandato'}`, values: [`${Math.round(presence.presente / presence.dias * 100)}%`], notes: [`${presence.presente} de ${presence.dias} ${senate ? 'sessões' : 'dias'}`] }
    : registered
      ? { label: 'Presença registrada no Senado em 2026', values: [`${registered.presente} sessões`], notes: ['faltas e justificativas não apuradas'] }
      : { label: 'Presença no Plenário em 2026', values: ['Sem registro'], notes: ['ausência de dado não é zero'] };
  const alertRow = { label: 'Gastos incomuns na cota', values: [!hasExpenseData ? 'Sem dados' : alerts.length ? `${alerts.length} ${alerts.length === 1 ? 'alerta' : 'alertas'}` : 'Nenhum'],
    notes: ['pelas mesmas 2 regras para todos(as)'] };
  return {
    kicker: `Ficha · ${senate ? 'Senado' : 'Câmara'}`, title: citizenName(person.name),
    subtitle: [ROLE_LABELS[person.role], person.party, person.uf].filter(Boolean).join(' · '),
    rows: [costRow, workRow, alertRow], fileName: citizenName(person.name),
    footnote: `Fontes: ${senate ? 'Senado Federal' : 'Câmara dos Deputados'} (notas da cota${average !== null ? ', remuneração, gabinete' : ''} e presença). Retrato de ${f.snapshotAt ? f.snapshotAt.slice(0, 10) : 'data não informada'}.`,
  };
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
  const costAnswer = person.role === 'deputado' && shared.cost ? profileCostAnswer(shared.cost)
    : person.role === 'senador' && shared.senateCost ? senateCostAnswer(shared.senateCost, f)
    : profileExpenseAnswer(f, person, hasExpenseData);
  const alerts = f.alertas || [], isChamberPerson = person.role === 'deputado';
  const personNumber = String(person.id).split(':')[1];
  const presenceUrl = isChamberPerson && /^\d+$/.test(personNumber || '') ? `https://www.camara.leg.br/deputados/${personNumber}/presenca-plenario/2026` : null;
  const sourcesHtml = `<p>Cota é reembolso de gastos com o trabalho: escritório, divulgação, carro e viagens.</p>
    <p class="src">Fonte: notas da cota publicadas ${isChamberPerson ? 'pela Câmara (sem as passagens aéreas, que ficam fora do arquivo aberto)' : 'pelo Senado'}. Retrato de ${f.snapshotAt ? esc(f.snapshotAt.slice(0, 10)) : 'data não informada'}.</p>
    ${isChamberPerson ? `<p class="muted">Presença em sessões deliberativas do mandato atual, desde fev/2023. Média da Câmara: média das proporções individuais entre registros válidos. O selo compara os percentuais arredondados. Os dias observados podem variar entre mandatos.</p>
    ${presenceUrl ? `<a class="src" href="${esc(presenceUrl)}" target="_blank" rel="noopener">Fonte da presença no Plenário ↗</a>` : ''}
    <p class="muted">Os votos cobrem apenas a seleção do Placar em 2026. Cada votação abre seu resumo e fontes oficiais.</p>` : ''}
    ${!isChamberPerson ? ['presenca', 'votacoes'].map(key => { const source = profileSenateSource(key); return source ? `<p><b>${key === 'presenca' ? 'Presença' : 'Votações'} do Senado</b></p>${profileSource(source)}<p class="muted">${esc(source.detail || '')}</p>` : ''; }).join('') : ''}
    ${!isChamberPerson ? profileAttendanceSources(shared.id) : ''}
    <p class="muted">Alertas indicam registros para conferir, não conclusões de irregularidade. “Parecido com a média” mantém a faixa de diferença inferior a 10% na cota.</p>
    ${citizenSourceUrl(person) ? `<a class="fchip" href="${esc(citizenSourceUrl(person))}" target="_blank" rel="noopener">Página oficial ↗</a>` : ''}
    ${hasExpenseData ? `<a class="fchip" href="${esc('/api/c/gastos.csv?id=' + encodeURIComponent(person.id))}" download>Baixar todas as notas (CSV)</a>` : ''}
    ${hasExpenseData ? '<p class="muted">O arquivo traz uma nota por linha, desde fev/2023. Nas notas de 2023 a 2025, a coluna Documento fica vazia; o link da nota continua.</p>' : ''}`;
  return `${back}
    <div class="citizen-profile-head"><div class="profile">${citizenAvatar(person, 64)}<div><h1 class="n">${esc(citizenName(person.name))}</h1><span class="muted">${citizenRoleDescription(person)}</span>${election?.summary ? `<span class="pill citizen-election" data-tone="${esc(election.tone)}"><i></i>${esc(election.summary)}</span>` : ''}</div></div>
      <button type="button" class="fchip" data-cmp-start="${esc(shared.id)}">Comparar com outro(a) →</button></div>
    ${shareActionsHTML(profileShareCard(f, shared, alerts, hasExpenseData))}
    <span class="k citizen-answer-label">Em 3 respostas</span>
    <div class="citizen-answers">${costAnswer}${profileWorkAnswer(shared)}${profileAlertAnswer(alerts, f.coberturaAlertas)}</div>
    <h2 class="h">Ver mais</h2>
    ${profileSectionsHTML(person, {
      expenses: (person.role === 'deputado' ? profileCostDetails(shared.cost) : person.role === 'senador' ? senateCostDetails(shared.senateCost, f) : '') + profileExpenseDetails(f, hasExpenseData, person.role === 'deputado' ? shared.cost : null, shared.mandate),
      alerts: (alerts.length ? alerts.map(alert => alertCard(alert, { semPessoa: true })).join('') : '') + `<p class="muted">${alerts.length ? 'O que as regras avaliaram:' : alertCoverageState(f.coberturaAlertas).evaluated ? 'Nenhum alerta nos meses avaliados:' : 'Dados insuficientes para avaliar:'}</p>${alertCoverageState(f.coberturaAlertas).html || '<p class="muted">Sem notas do mandato desta pessoa.</p>'}${ALERT_RULES_HTML}<button type="button" class="more" data-go="alerts">Como funcionam os alertas →</button>`,
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
  const t = e.target.closest('[data-profile-votes-more],[data-profile-toggle],[data-profile-open],[data-politician],[data-home-retry],[data-alert-type],[data-alert-role],[data-alert-year],[data-alert-more],[data-alert-retry],[data-politician-role],[data-politician-order],[data-politician-more],[data-politician-retry]');
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
  if (t.dataset.alertYear !== undefined) { l.year = t.dataset.alertYear; return rerender(); }
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
