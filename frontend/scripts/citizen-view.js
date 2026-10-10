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
  const year = Number(a.ano || String(a.periodo || '').slice(0, 4));
  const profileSourceUrl = opts.profile && String(p.id || '').startsWith('camara:') && Number.isInteger(year)
    ? `https://www.camara.leg.br/deputados/${String(p.id).slice(7)}?ano=${year}` : citizenSourceUrl(p);
  const profileSupplierHistory = opts.profile && a.tipo === 'fornecedor'
    ? `<details class="citizen-peak-history profile-supplier-history"><summary>Ver histórico e notas →</summary>
      <p>${esc(citizenName(a.fornecedor || 'Fornecedor não informado'))} recebeu ${Number.isFinite(a.valor) ? formatCitizenAmount(a.valor) : 'valor não informado'} de ${Number.isFinite(a.total) ? formatCitizenAmount(a.total) : 'total não informado'} nas notas observadas de ${esc(a.periodoObservado || String(a.periodo || year))}${Number.isInteger(a.mesesComNotas) ? `, em ${a.mesesComNotas} ${a.mesesComNotas === 1 ? 'mês' : 'meses'} com notas` : ''}.${a.parcial ? ' O período é parcial; o ano ainda pode receber notas.' : ''}</p>
      ${Array.isArray(a.fontesOficiais) && a.fontesOficiais.length ? `<p>Detalhamento oficial: ${a.fontesOficiais.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.label)} ↗</a>`).join(', ')}.${a.notaDocumento ? ` ${esc(a.notaDocumento)}` : ''}</p>` : profileSourceUrl ? `<a href="${esc(profileSourceUrl)}" target="_blank" rel="noopener">Ver as notas na fonte oficial ↗</a>` : ''}
    </details>` : '';
  return `<article class="card citizen-alert" data-kind="${cls}">
    <div class="citizen-top"><span class="citizen-chip ${cls}"><i></i>${label}</span><span class="muted">${a.tipo === 'pico' ? SHORT_MONTHS[a.mes] + '/' + String(a.periodo).slice(0, 4) : 'em ' + String(a.periodo).slice(0, 4)}</span></div>
    ${opts.semPessoa ? '' : `<button type="button" class="citizen-who" data-politician="${esc(p.id)}">${citizenAvatar(p, 40)}<span><b>${esc(citizenName(p.name))}</b><small>${citizenRoleDescription(p)}</small></span></button>`}
    <h3 class="citizen-title">${esc(a.titulo)}</h3>
    ${alertVisualization(a)}
    ${alertStatement(a)}
    ${a.contexto?.frase ? `<p class="citizen-context">${esc(a.contexto.frase)}</p>` : ''}
    ${alertYearEndNote(a)}
    ${profileSupplierHistory}
    <details class="citizen-why"><summary>Por que apareceu aqui?</summary><p>${alertExplanation(a)}</p><p class="muted">A regra mostra variação de gasto ou concentração em fornecedor; não mede irregularidade. Confira as notas na fonte oficial.</p></details>
    ${Array.isArray(a.fontesOficiais) && a.fontesOficiais.length ? `<p class="muted">Detalhamento oficial: ${a.fontesOficiais.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.label)} ↗</a>`).join(', ')}.${a.notaDocumento ? ` ${esc(a.notaDocumento)}` : ''}</p>` : ''}
    <div class="citizen-actions">${opts.semPessoa ? '' : `<button type="button" class="fchip" data-politician="${esc(p.id)}">Ver a ficha</button>`}${profileSourceUrl ? `<a class="fchip" href="${esc(profileSourceUrl)}" target="_blank" rel="noopener">Conferir na fonte ↗</a>` : ''}</div>
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
const ALERT_RULE_ICONS = {
  pico: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 17l5-5 4 3 8-9"/><path d="M15 6h5v5"/></svg>',
  fornecedor: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3v9l7 5"/></svg>'
};
/* Resumo das duas regras no topo: a regra e quantos alertas ela gerou no recorte. */
function alertRuleCards() {
  const counts = citizenState.alerts.counts;
  const rules = [
    ['pico', 'Mês acima da referência', 'O gasto do mês é pelo menos 1,75 vez a referência da própria pessoa (mediana dos 12 meses anteriores), com pelo menos R$ 10 mil de diferença, e fica acima do gasto típico dos(as) colegas.'],
    ['fornecedor', 'Concentração em fornecedor', 'Pelo menos 50% e R$ 30 mil das notas do ano foram para um mesmo fornecedor. Inclui passagens intermediadas por agência.']
  ];
  return `<div class="alerts-rules">${rules.map(([key, title, text]) => `<article class="card alerts-rule" data-kind="${key === 'pico' ? 'type-peak' : 'type-supplier'}">
      ${ALERT_RULE_ICONS[key]}<b>${title}</b><span>${text}</span>
      <b class="mono alerts-rule-count">${counts ? (counts[key] || 0).toLocaleString('pt-BR') : '—'}</b>
    </article>`).join('')}</div>`;
}
function alertTopPeople() {
  const topPeople = (citizenState.cache.get(TOP_ALERTS_PATH)?.itens || []).filter(person => person.alertas);
  if (!topPeople.length) return '';
  return `<div class="alerts-top"><span class="k">Valor das despesas nos alertas do mandato</span>
    <div class="faces citizen-top5">${topPeople.map(person => `<button type="button" class="face" data-politician="${esc(person.id)}">${citizenAvatar(person, 54)}<span>${esc(citizenName(person.name).split(' ')[0])}</span><em>${person.valorAlertas ? esc(formatCitizenAmount(person.valorAlertas)) + (person.valorAlertasParcial ? ' · parcial' : '') : `${person.alertas} ${person.alertas === 1 ? 'ALERTA' : 'ALERTAS'}`}</em></button>`).join('')}</div>
    <span class="muted">Soma das despesas observadas nos alertas, cada nota contada uma vez. Não é estimativa de prejuízo. "Parcial": inclui concentração calculada com o ano ainda aberto.</span></div>`;
}
function alertFilterGroup(label, attr, options, current) {
  return `<span class="alerts-seg" role="group" aria-label="${label}">${options.map(([k, n]) => `<button type="button" data-${attr}="${k}" aria-pressed="${current === k}">${n}</button>`).join('')}</span>`;
}
function alertsView() {
  const l = citizenState.alerts; loadAlerts(false); loadTopAlerts();
  const types = [['pico,fornecedor', 'Todos'], ['pico', 'Mês acima da referência'], ['fornecedor', 'Concentração em fornecedor']];
  const roles = [['', 'Todas'], ['deputado', 'Câmara'], ['senador', 'Senado']];
  const years = [['', 'Mandato'], ...(l.years || []).map(y => [String(y.ano), String(y.ano)])];
  const scope = l.year ? `em ${esc(l.year)}` : `no mandato${l.span ? ` (${esc(citizenQuotaPeriod(l.span.inicio, l.span.fim))})` : ''}`;
  return `<div class="alerts-page">
    <section class="alerts-hero">
      <div class="alerts-intro">
        <h1 class="h ph-t">Alertas</h1>
        <p class="ph-lead">Meses acima da referência e concentração em fornecedor nas notas da cota de deputados(as) e senadores(as), pelas mesmas regras para todos(as). Os alertas não indicam irregularidade: confira sempre as notas na fonte oficial.</p>
        <a class="alerts-how-link" href="#alerts-how">Como as regras funcionam →</a>
        ${alertTopPeople()}
      </div>
      ${alertRuleCards()}
    </section>
    <section class="alerts-filters" aria-label="Filtros">
      ${alertFilterGroup('Tipo de alerta', 'alert-type', types, l.type)}
      ${alertFilterGroup('Casa', 'alert-role', roles, l.role)}
      ${years.length > 2 || l.year ? alertFilterGroup('Período', 'alert-year', years, l.year) : ''}
      ${l.total !== null ? `<span class="muted alerts-status" role="status">${l.total.toLocaleString('pt-BR')} ${l.total === 1 ? 'alerta' : 'alertas'} ${scope} · dos mais recentes aos mais antigos</span>` : ''}
    </section>
    ${l.error ? `<section class="card"><p>Não deu para carregar os alertas agora.</p><p class="muted">${esc(l.error)}</p><button type="button" class="more" data-alert-retry>Tentar de novo</button></section>` : ''}
    <div class="alerts-grid">
      ${l.items.map(a => alertCard(a)).join('')}
      ${l.loading && !l.error ? skel('alerta', l.items.length ? 1 : 3) : ''}
    </div>
    ${!l.loading && l.total !== null && l.items.length < l.total ? `<button type="button" class="opt alerts-more" data-alert-more>Carregar mais alertas</button>` : ''}
    <section class="card citizen-how" id="alerts-how"><span class="k">Como funciona</span>
      <p><b>Mês acima da referência:</b> o gasto do mês passou de 1,75 vez a mediana dos 12 meses anteriores da própria pessoa. A avaliação começa em fevereiro de 2024, quando há 12 meses de mandato para comparar.</p>
      <p><b>Concentração em fornecedor:</b> metade ou mais do dinheiro do ano foi para a mesma empresa, ano a ano desde 2023.</p>
      <p class="muted">Pode ter explicação, como um evento no estado ou um contrato fixo. Os dados vêm das notas que a Câmara e o Senado publicam; as passagens aéreas da Câmara não entram nessa conta.</p>
    </section>
  </div>`;
}

/* ---------- Aba "Políticos" ---------- */
/* "Quem mais custa" com "Todos": as Casas não publicam as mesmas partes do custo, então a lista mostra
   dois blocos (Câmara e Senado), cada um ordenado por dentro, em vez de uma ordem única. */
const POLITICIAN_BLOCK_SIZE = 10;
function loadPoliticians(more) {
  const p = citizenState.politicians, key = `q=${p.query}&cargo=${p.role}&ordem=${p.order}`;
  if (!more && p.key === key) return;
  const blocks = p.order === 'gasto' && !p.role;
  if (!more) { p.key = key; p.page = 1; p.items = []; p.total = null; p.blocks = null; }
  p.loading = true; p.error = null;
  const query = `${p.query ? '&q=' + encodeURIComponent(p.query) : ''}`;
  const done = d => { p.averageSpend = d.medias; p.averageCost = d.custoMedias; p.coverage = d.cobertura; p.loading = false; if (['politicians'].includes(state.view)) renderPoliticianList(); };
  const fail = e => { if (p.key !== key) return; p.loading = false; p.error = citizenErrorMessage(e); if (['politicians'].includes(state.view)) renderPoliticianList(); };
  if (blocks) {
    Promise.all(ROLES_ORDER.map(role => citizenGet(`/api/c/politicos?pageSize=${POLITICIAN_BLOCK_SIZE}&page=1&ordem=gasto&cargo=${role}${query}`)))
      .then(([deputies, senators]) => { if (p.key !== key) return;
        p.blocks = { deputado: { items: deputies.itens, total: deputies.total }, senador: { items: senators.itens, total: senators.total } };
        p.items = [...deputies.itens, ...senators.itens]; p.total = deputies.total + senators.total; done(deputies); })
      .catch(fail);
    return;
  }
  const qs = `/api/c/politicos?pageSize=25&page=${p.page}&ordem=${p.order}${p.role ? '&cargo=' + p.role : ''}${query}`;
  citizenGet(qs).then(d => { if (p.key !== key) return; p.items = p.items.concat(d.itens); p.total = d.total; done(d); }).catch(fail);
}
const ROLES_ORDER = ['deputado', 'senador'];
/* "fev/2023–set/2026" a partir de "AAAA-MM"; a cota das duas Casas conta desde fev/2023. */
function citizenQuotaPeriod(start, end) {
  const label = value => typeof value === 'string' && /^\d{4}-\d{2}$/.test(value)
    ? `${['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][Number(value.slice(5)) - 1]}/${value.slice(0, 4)}` : null;
  const from = label(start), to = label(end);
  return from && to ? (from === to ? from : `${from}–${to}`) : '';
}
/* Linha da lista: o custo médio por mês da própria Casa (como no "Quanto custa?" da ficha), com a cota
   à parte. A barra e o "acima da média" comparam só com a mesma Casa. */
function politicianRow(person, max) {
  const hasExpenseData = person.hasExpenseData === undefined ? person.gastoMensal != null : Boolean(person.hasExpenseData);
  const cost = Number.isFinite(person.custoMensal) ? person.custoMensal : null;
  const quota = hasExpenseData && Number.isFinite(person.gastoMensal) ? person.gastoMensal : null;
  const houseAverage = citizenState.politicians.averageCost?.[person.role]?.media;
  const aboveAverage = cost !== null && houseAverage && cost > houseAverage * 1.25;
  const roleLabel = person.role === 'senador' ? 'Senador(a)' : 'Deputado(a)';
  const barWidth = cost !== null && cost > 0 ? Math.max(2, cost / max * 100) : 0;
  const details = [
    cost !== null && person.custoMeses ? `média de ${person.custoMeses} ${person.custoMeses === 1 ? 'mês' : 'meses'}` : cost === null ? 'custo não identificado' : '',
    quota === null ? 'sem despesa de cota observada' : `cota ${quota === 0 ? 'R$ 0' : formatCitizenAmount(quota)}`,
    aboveAverage ? `acima da média ${person.role === 'senador' ? 'do Senado' : 'da Câmara'}` : '',
    citizenState.politicians.order === 'alertas' && person.valorAlertas ? `${formatCitizenAmount(person.valorAlertas)} em alertas${person.valorAlertasParcial ? ' · parcial' : ''}` : '',
  ].filter(Boolean).join(' · ');
  /* À direita só o valor; os detalhes vão embaixo do nome, que assim não é cortado no celular. */
  return `<button type="button" class="citizen-row" data-politician="${esc(person.id)}">${citizenAvatar(person, 48)}<span class="citizen-rowtxt"><b>${esc(citizenName(person.name))}</b><small>${[roleLabel, person.party, person.uf].filter(Boolean).map(esc).join(' · ')}</small>
      <span class="citizen-rowbar"><i style="width:${barWidth}%" class="${aboveAverage ? 'hi' : ''}"></i></span><small class="citizen-rowdetail">${esc(details)}</small></span>
    <span class="citizen-rowval">${cost !== null ? `<b class="mono">${esc(formatCitizenAmount(cost))}</b><small>/mês</small>` : '<b class="mono">Sem custo</b>'}${person.alertas ? `<span class="citizen-chip info citizen-mini"><i></i>${person.alertas} ${person.alertas === 1 ? 'alerta' : 'alertas'}</span>` : ''}</span></button>`;
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
    <p class="muted">Custo por mês: o mesmo do “Quanto custa?” de cada ficha. Na Câmara, salário bruto, auxílios, cota e verba de gabinete, nos meses com as quatro partes. No Senado, remuneração do(a) senador(a), equipe comissionada do gabinete e cota, nos meses com as três. As Casas não publicam as mesmas partes: compare só dentro da mesma Casa. Sem mês com todas as partes, a linha diz “Sem custo”, sem estimativa.</p>
    ${Number.isFinite(coverage.custo?.deputado) && Number.isFinite(coverage.custo?.senador) ? `<p class="muted">Custo identificado para ${coverage.custo.deputado} de ${deputies.count} deputados(as) e ${coverage.custo.senador} de ${senators.count} senadores(as).</p>` : ''}
    <p class="muted">Despesas de cota observadas para ${deputies.withExpenses} de ${deputies.count} deputados(as) e ${senators.withExpenses} de ${senators.count} senadores(as).</p>${senateSeatNote}
  </details>`;
}
function politicianListHTML() {
  const p = citizenState.politicians;
  if (p.error) return `<section class="card"><p>Não deu para carregar a lista agora.</p><p class="muted">${esc(p.error)}</p><button type="button" class="more" data-politician-retry>Tentar de novo</button></section>`;
  if (!p.items.length && p.loading) return skel('lista', 8);
  if (!p.items.length) return `<section class="card"><p>Ninguém encontrado com “${esc(p.query)}”.</p><p class="muted">A busca mostra só deputados(as) federais e senadores(as) com mandato em curso. Eleitos(as) em 2026 aparecem a partir da posse, em 1º de fevereiro de 2027; vereadores(as), prefeitos(as) e governadores(as) não fazem parte da busca.</p><p class="muted">Tente só o sobrenome, a sigla do partido (PT, PL…) ou do estado (SP, MG…).</p></section>`;
  /* Escala da barra por Casa: um custo do Senado não encurta as barras da Câmara. */
  const scale = role => Math.max(1, ...p.items.filter(person => person.role === role && Number.isFinite(person.custoMensal)).map(person => person.custoMensal),
    (p.averageCost?.[role]?.media || 0) * 1.5);
  const rows = items => items.map(person => politicianRow(person, scale(person.role))).join('');
  if (p.blocks) {
    return ROLES_ORDER.filter(role => p.blocks[role].items.length).map(role => {
      const block = p.blocks[role], plural = role === 'senador' ? 'senadores(as)' : 'deputados(as)';
      return `<h3 class="k citizen-list-head">${role === 'senador' ? 'Senado' : 'Câmara'} · quem mais custa por mês</h3><section class="card citizen-list">${rows(block.items)}</section>
        ${block.total > block.items.length ? `<button type="button" class="opt citizen-more" data-politician-role="${role}">Ver todos os ${block.total} ${plural}</button>` : ''}`;
    }).join('') + '<p class="muted">Câmara e Senado aparecem separados: as duas Casas não publicam as mesmas partes do custo.</p>';
  }
  return `<span class="muted" role="status">${p.total} ${p.total === 1 ? 'pessoa' : 'pessoas'} · custo médio por mês na própria Casa</span><section class="card citizen-list">${rows(p.items)}</section>
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
  return `${pageHead('Deputados(as) e senadores(as)', 'Políticos', 'Busque qualquer um(a) e veja quanto custa por mês, com os alertas.')}
    <div id="citizen-politician-summary" class="citizen-roster-summary" role="status">${politicianCoverageHTML(p.coverage)}</div>
    <label class="search" for="citizen-search"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="citizen-search" type="search" placeholder="Nome, partido ou estado" value="${esc(p.query)}" autocomplete="off"></label>
    <div class="citizen-filters">
      <div class="chips" role="group" aria-label="Cargo">${[['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']].map(([k, n]) => `<button type="button" class="fchip" data-politician-role="${k}" aria-pressed="${p.role === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Ordenar">${[['nome', 'A–Z'], ['gasto', 'Quem mais custa'], ['alertas', 'Valor das despesas nos alertas']].map(([k, n]) => `<button type="button" class="fchip" data-politician-order="${k}" aria-pressed="${p.order === k}">${n}</button>`).join('')}</div>
    </div>
    <div class="citizen-actions"><button type="button" class="fchip" data-cmp-start="">Comparar dois(duas) lado a lado →</button><button type="button" class="fchip" data-go="parties">Comparar partidos →</button><button type="button" class="fchip" data-go="attendance">Presença dos deputados →</button></div>
    <div id="citizen-politician-list" class="citizen-stack" aria-live="polite">${politicianListHTML()}</div>
    <div id="citizen-politician-notes">${politicianCoverageNotesHTML(p.coverage)}</div>
    <span class="src">Valor: custo médio por mês, o mesmo do “Quanto custa?” da ficha, desde fev/2023, início da legislatura atual; a linha diz quantos meses entram na média. Embaixo, a média da cota parlamentar (reembolsos). Câmara e Senado não publicam as mesmas partes: a barra e o “acima da média” comparam só com a mesma Casa. Valores da época, sem correção pela inflação.</span>`;
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
function profileSummaryCards(shared, profileRecord, alerts, hasExpenseData) {
  const person = shared.person, senate = person.role === 'senador';
  let costLabel = 'Quanto custa?', costValue = 'Sem dados', costNote = 'Ausência de dado não significa gasto zero.';
  if (!senate && shared.cost) {
    if (Array.isArray(shared.cost.usedMonths) && shared.cost.usedMonths.length > 0
        && profileCostInteger(shared.cost.monthlyAverageCents)) {
      costValue = profileCostShort(shared.cost.monthlyAverageCents);
      costNote = `${profileCostMonthList(shared.cost.usedMonths)} · Câmara`;
    } else {
      costValue = 'Sem total';
      costNote = 'Não há mês com as quatro partes identificadas.';
    }
  } else if (senate && shared.senateCost) {
    const figures = senateCostFigures(shared.senateCost, profileRecord);
    if (figures.total && profileCostInteger(figures.total.cents)) {
      costValue = profileCostShort(figures.total.cents);
      costLabel = 'Quanto custa?';
      costNote = `${figures.total.months} ${figures.total.months === 1 ? 'mês' : 'meses'} com as três partes · Senado`;
    } else {
      costValue = 'Sem total';
      costLabel = 'Quanto custa?';
      costNote = 'Não há mês com as três partes identificadas.';
    }
  } else if (hasExpenseData && Number.isFinite(profileRecord.mediaMensal)) {
    costValue = profileCostShort(Math.round(profileRecord.mediaMensal * 100));
    costLabel = 'Quanto custa?';
    costNote = 'Só reembolsos observados; não é o custo total do mandato.';
  }

  const presence = shared.presence, registered = senate ? shared.registeredPresence : null;
  let presenceValue = 'Sem registro', presenceNote = 'Ausência de dado não significa zero presença.';
  if (presence && presence.dias > 0) {
    const percent = Math.round(presence.presente / presence.dias * 100);
    const unit = senate && profileSenateSource('presenca')?.unit === 'sessoes' ? 'sessões' : 'dias';
    presenceValue = `${percent}%`;
    presenceNote = `${presence.presente} de ${presence.dias} ${unit}`;
  } else if (registered && Number.isInteger(registered.presente)) {
    presenceValue = `${registered.presente}`;
    presenceNote = 'sessões com presença registrada; faltas não apuradas.';
  }

  const coverage = alertCoverageState(profileRecord.coberturaAlertas);
  const alertValue = alerts.length ? String(alerts.length) : coverage.evaluated ? '0' : '—';
  const alertNote = alerts.length ? `Mais recente: ${alerts[0].titulo || 'Título não informado'}. Alertas não indicam irregularidade.`
    : coverage.evaluated ? 'Nenhum alerta nos períodos avaliados; não indicam irregularidade.' : 'Dados insuficientes para avaliar; alertas não indicam irregularidade.';
  const hasMonthlyCost = costValue !== 'Sem dados' && costValue !== 'Sem total';
  return `<nav class="profile-summary-grid" aria-label="Resumo da ficha">
    <a class="card profile-summary-card" href="#profile-cost"><span class="k">${esc(costLabel)}</span><b class="mono">${esc(costValue)}${hasMonthlyCost ? '<small>/mês</small>' : ''}</b><small>${esc(costNote)}</small></a>
    <a class="card profile-summary-card" href="#profile-work"><span class="k">Aparece para trabalhar?</span><b class="mono">${esc(presenceValue)}${percentForSummary(shared) !== null ? '<small>presença</small>' : ''}</b><small>${esc(presenceNote)}</small></a>
    <a class="card profile-summary-card profile-summary-alert" href="#profile-alerts"><span class="k">Algum alerta na cota?</span><b class="mono">${esc(alertValue)}<small>${alerts.length || coverage.evaluated ? (alerts.length === 1 ? ' alerta' : ' alertas') : ''}</small></b><small>${esc(alertNote)}</small></a>
  </nav>`;
}
function percentForSummary(shared) {
  return shared.presence?.dias > 0 ? Math.round(shared.presence.presente / shared.presence.dias * 100) : null;
}
function profileCostPanel(shared, profileRecord, hasExpenseData) {
  const person = shared.person;
  const hasChamberTotal = person.role === 'deputado' && shared.cost
    && Array.isArray(shared.cost.usedMonths) && shared.cost.usedMonths.length > 0
    && profileCostInteger(shared.cost.monthlyAverageCents);
  let composition = person.role === 'deputado' && shared.cost ? profileCostAnswer(shared.cost)
    : person.role === 'senador' && shared.senateCost ? senateCostAnswer(shared.senateCost, profileRecord) : '';
  if (!composition) {
    const monthly = hasExpenseData && Number.isFinite(profileRecord.mediaMensal) ? profileRecord.mediaMensal : null;
    const period = profileRecord.periodo || {};
    const monthlyValue = monthly === null ? null : Math.round(monthly * 100);
    composition = `<article class="card profile-cost-breakdown" data-profile-cost-house="${person.role === 'senador' ? 'senado' : 'camara'}">
      <span class="k">${person.role === 'senador' ? 'Cota parlamentar · Senado' : 'Cota parlamentar · Câmara'}</span>
      ${monthlyValue === null ? '<p class="profile-cost-total-missing">Sem dados da cota neste recorte.</p><p class="muted">Ausência de dado não significa gasto zero.</p>' : `<div class="profile-cost-total"><span>Média por mês</span><b class="mono">${esc(profileCostShort(monthlyValue))}</b></div><p class="citizen-cost-exact">Valor exato: <span class="mono">${esc(brl(monthly, 2))}</span> por mês</p><p class="citizen-cost-period">${esc(citizenQuotaPeriod(period.inicio, period.fim) || 'período não informado')}${Number.isInteger(period.meses) ? `, ${period.meses} ${period.meses === 1 ? 'mês' : 'meses'} com notas` : ''}.</p>`}
      <p class="muted">Este valor reúne apenas reembolsos observados. ${person.role === 'senador' ? 'Remuneração e equipe do Senado não estão identificadas para esta ficha.' : 'Salário, auxílios e verba de gabinete não estão compostos nesta ficha.'} Não compare com o custo do mandato de outra Casa.</p>
      <div class="profile-card-links"><button type="button" class="more" data-profile-open="expenses">Ver detalhes da cota →</button><button type="button" class="more" data-profile-open="sources">Fontes e datas →</button></div>
    </article>`;
  }
  return `<section class="profile-area" id="profile-cost" aria-labelledby="profile-cost-title">
    <header class="profile-area-head"><h2 class="h" id="profile-cost-title">Quanto custa?</h2>
      <p>${person.role === 'senador' ? 'O Senado publica partes diferentes das da Câmara; os valores não são comparáveis.'
        : hasChamberTotal ? 'A média soma as quatro partes nos meses em que todas foram publicadas. Valores da época, sem correção pela inflação.'
          : shared.cost ? 'A média exige as quatro partes no mesmo mês. Sem um mês completo, não há total mensal.'
            : 'Só a cota parlamentar observada está disponível; não é o custo total mensal do mandato.'}</p>
    </header>
    <div class="profile-cost-grid">${composition}${profileQuotaPanel(profileRecord, shared, hasExpenseData)}</div>
  </section>`;
}
function profileQuotaPanel(profileRecord, shared, hasExpenseData) {
  if (!hasExpenseData) return `<article class="card profile-quota-panel"><span class="k">Onde gastou a cota</span>
    <p class="citizen-empty">Sem despesas observadas</p><p class="muted">Ausência de dado não significa gasto zero.</p></article>`;
  const categories = Array.isArray(profileRecord.categorias) ? profileRecord.categorias.slice(0, 6) : [];
  const suppliers = Array.isArray(profileRecord.fornecedores) ? profileRecord.fornecedores.slice(0, 3) : [];
  const total = Number.isFinite(profileRecord.total) ? profileRecord.total : null;
  const categoryScale = Math.max(0, ...categories.map(item => Number.isFinite(item.valor) ? item.valor : 0));
  const categoryRows = categories.length ? categories.map(item => {
    const value = Number.isFinite(item.valor) ? item.valor : null;
    const width = value !== null && categoryScale > 0 && value > 0 ? Math.min(100, value / categoryScale * 100) : 0;
    const share = value !== null && total > 0 ? `${Math.round(value / total * 100)}% do total` : '';
    return `<div class="profile-quota-row"><div><span>${esc(item.nome)}</span><b class="mono">${value === null ? 'Sem dado' : esc(profileQuotaAmount(value))}</b></div>
      ${value !== null && categoryScale > 0 ? `<span class="profile-quota-bar" aria-hidden="true"><i style="width:${width.toFixed(1)}%"></i></span>` : ''}<small>${share}</small></div>`;
  }).join('') : '<p class="muted">Categorias não disponíveis neste recorte.</p>';
  const supplierRows = suppliers.length ? suppliers.map(item => {
    const value = Number.isFinite(item.valor) ? item.valor : null;
    const share = value !== null && total > 0 ? `${Math.round(value / total * 100)}% do total` : '';
    return `<div class="profile-quota-row profile-supplier-row"><div><span>${esc(citizenName(item.name || 'Fornecedor não informado'))}</span><b class="mono">${value === null ? 'Sem dado' : esc(profileQuotaAmount(value))}</b></div>
      <small>${[share, Number.isInteger(item.notas) ? `${item.notas} ${item.notas === 1 ? 'nota' : 'notas'}` : 'contagem de notas não informada'].filter(Boolean).join(' · ')}</small></div>`;
  }).join('') : '<p class="muted">Fornecedores não disponíveis neste recorte.</p>';
  const count = Number.isInteger(profileRecord.expenseCount) ? profileRecord.expenseCount : null;
  const period = profileRecord.periodo ? citizenQuotaPeriod(profileRecord.periodo.inicio, profileRecord.periodo.fim) : '';
  const csv = `/api/c/gastos.csv?id=${encodeURIComponent(shared.id)}`;
  return `<article class="card profile-quota-panel">
    <div class="profile-quota-head"><span class="k">Onde gastou a cota</span><b class="mono">${total === null ? 'Total não informado' : `${esc(formatCitizenAmount(total))} no mandato`}</b></div>
    <p class="muted">${count === null ? 'Quantidade de notas não informada.' : `${count.toLocaleString('pt-BR')} ${count === 1 ? 'nota observada' : 'notas observadas'}`}${period ? ` · ${esc(period)}` : ''}</p>
    <div class="profile-quota-group"><h3 class="k">Categorias · até 6</h3>${categoryRows}</div>
    <div class="profile-quota-group"><h3 class="k">Maiores fornecedores · até 3</h3>${supplierRows}</div>
    <div class="profile-card-links"><a class="more" href="${esc(csv)}" download>${count === null ? 'Baixar notas da cota (CSV)' : `Baixar todas as ${count.toLocaleString('pt-BR')} notas (CSV)`} →</a><button type="button" class="more" data-profile-open="expenses">Ver meses e notas →</button></div>
  </article>`;
}
function profileQuotaAmount(value) { return value === 0 ? 'R$ 0' : formatCitizenAmount(value); }
function profileAttendanceCard(shared) {
  const person = shared.person, senate = person.role === 'senador';
  if (senate) profileSenateEnsure();
  const presence = shared.presence, registered = senate ? shared.registeredPresence : null;
  const unit = senate && profileSenateSource('presenca')?.unit === 'sessoes' ? 'sessões' : 'dias';
  const period = senate ? senatePresencePeriodLabel() : presence ? citizenQuotaPeriod(presence.inicio, presence.fim) : 'mandato';
  const percent = presence && presence.dias > 0 ? Math.round(presence.presente / presence.dias * 100) : null;
  const attendance = presence && presence.dias > 0 ? `<div class="profile-attendance-count"><b class="mono">${presence.presente}</b><span>de ${presence.dias} ${unit}</span></div><strong class="profile-attendance-percent">${percent}%</strong>
      ${attendanceBar(presence)}<div class="legend"><span><i></i>Presente ${presence.presente}</span><span><i class="justified"></i>Justificada ${presence.justificadas}</span><span><i class="absent"></i>Falta ${presence.falta}</span></div>
      ${averagePresenceLabel(shared, senate)}${presenceReasonsHTML(presence)}` : registered ? `<div class="profile-attendance-count"><b class="mono">${registered.presente}</b><span>sessões com presença registrada</span></div>
      <p class="muted">${Number.isInteger(registered.sessoesEmExercicio) ? `De ${registered.sessoesEmExercicio} sessões deliberativas com lista validada em que estava em exercício.` : `${profileSenateSource('presenca')?.sessionCount || ''} listas consultadas.`} Faltas e justificativas não apuradas; sem percentual de assiduidade.</p>`
      : '<p class="citizen-empty">Sem registro de presença</p><p class="muted">Ausência de dado não significa zero presença.</p>';
  let source = '';
  if (senate) source = profileSource(profileSenateSource('presenca'), 'Fonte do Diário do Senado');
  else {
    const personNumber = String(person.id).split(':')[1];
    source = /^\d+$/.test(personNumber || '')
      ? `<span class="src"><a href="https://www.camara.leg.br/deputados/${personNumber}/presenca-plenario/2026" target="_blank" rel="noopener">Fonte da presença na Câmara ↗</a></span>` : '';
  }
  return `<article class="card profile-work-card profile-presence-card">
    <span class="k">Presença no Plenário · ${esc(period || 'mandato')}</span>${attendance}${source}
    ${senate ? `<button type="button" class="more" data-profile-open="sources">Cobertura e fontes →</button>` : '<button type="button" class="more" data-go="attendance">Presença de todos(as) →</button>'}
  </article>`;
}
/* Motivos publicados pela Câmara para os dias justificados, do mais frequente ao menos. */
function presenceReasonsHTML(presence) {
  const reasons = Array.isArray(presence?.motivos) ? presence.motivos.filter(([reason, count]) => reason && count > 0) : [];
  if (!reasons.length) return '';
  return `<p class="profile-attendance-reasons"><b>Justificativas:</b> ${reasons.map(([reason, count]) => `${esc(String(reason).toLowerCase())} (${count})`).join(', ')}.</p>`;
}
function averagePresenceLabel(shared, senate) {
  const rows = profilePresenceRows(senate ? 'senado' : 'camara');
  if (!rows.length) return '';
  const average = Math.round(rows.reduce((sum, row) => sum + row.presente / row.dias, 0) / rows.length * 100);
  const percent = shared.presence?.dias > 0 ? Math.round(shared.presence.presente / shared.presence.dias * 100) : null;
  if (percent === null) return '';
  return `<p class="profile-attendance-average">${percent === average ? 'Perto da' : percent > average ? 'Acima da' : 'Abaixo da'} média ${senate ? 'do' : 'da'} ${senate ? 'Senado' : 'Câmara'}: ${average}%.</p>`;
}
function profileRecentVotesCard(shared) {
  const senate = shared.person.role === 'senador';
  if (senate) profileSenateEnsure();
  if (!senate && profileChamberVotesLoading(shared.id)) return `<article class="card profile-work-card profile-votes-card"><span class="k">Como votou · Placar</span>${skel('linhas', 3)}</article>`;
  const all = [...votesForPerson(shared.id)].sort((first, second) => String(second.vote?.data || '').localeCompare(String(first.vote?.data || '')));
  const latest = all.slice(0, 4);
  const items = latest.map(({ vote, recordedVote }) => {
    const label = recordedVote === null ? 'Sem registro importado'
      : vote.secreta ? 'Presença registrada · voto secreto'
        : senate && recordedVote === 'Presente' ? 'Presença registrada · sem voto' : String(recordedVote).trim();
    const visibleLabel = label ? label[0].toLocaleUpperCase('pt-BR') + label.slice(1) : '';
    const date = typeof vote.data === 'string' && /^\d{4}-\d{2}-\d{2}/.test(vote.data) ? dateBR(vote.data) : '';
    return profileVoteButton(vote, `<b>${esc(visibleLabel)}</b><span>${esc(vote.titulo)}</span>${date ? `<small>${esc(date)}</small>` : ''}`, 'profile-vote-preview-item');
  }).join('');
  const empty = senate && profileSenateSource('votacoes')?.status === 'unavailable'
    ? 'Dados de votações nominais do Senado indisponíveis neste recorte.'
    : `Sem registros individuais ${senate ? 'nas votações nominais do Senado' : 'nas votações do Placar'} neste recorte.`;
  return `<article class="card profile-work-card profile-votes-card">
    <span class="k">Como votou · ${senate ? 'Senado' : 'Placar'}</span>
    ${latest.length ? `<div class="profile-vote-preview">${items}</div>` : `<p class="muted">${empty}</p>`}
    <button type="button" class="more" data-profile-open="votes">Ver votações →</button>
  </article>`;
}
function profileAlertChronology(alerts) {
  return [...(Array.isArray(alerts) ? alerts : [])].map((alert, index) => ({ alert, index })).sort((first, second) => {
    const point = alert => {
      const match = /^(\d{4})(?:-(\d{2}))?/.exec(String(alert.periodo || ''));
      const year = Number(alert.ano || match?.[1] || 0);
      const month = alert.tipo === 'pico' ? Number(alert.mes || match?.[2] || 0) : match?.[2] ? Number(match[2]) : 13;
      return year * 100 + month;
    };
    return point(second.alert) - point(first.alert) || first.index - second.index;
  }).map(item => item.alert);
}
function profileAlertsSection(alerts, coverage) {
  const ordered = profileAlertChronology(alerts);
  const coverageState = alertCoverageState(coverage);
  const intro = ordered.length
    ? `${ordered.length} ${ordered.length === 1 ? 'alerta' : 'alertas'} na cota do mandato, dos mais recentes aos mais antigos. As regras detectam variação de gasto ou concentração; não indicam irregularidade.`
    : coverageState.evaluated ? 'Nenhum alerta nos períodos avaliados pelas regras da cota.' : 'Dados insuficientes para avaliar os alertas da cota.';
  return `<section class="profile-area" id="profile-alerts" aria-labelledby="profile-alerts-title">
    <header class="profile-area-head"><h2 class="h" id="profile-alerts-title">Alertas na cota</h2><p>${esc(intro)}</p></header>
    <div class="profile-alert-method"><h3 class="k">As duas regras</h3>${ALERT_RULES_HTML}<p>Alertas são registros para conferir, não conclusões de irregularidade. O prazo de apresentação das notas e a cobertura são considerados por Casa e por período.</p><button type="button" class="more" data-go="alerts">Metodologia completa →</button></div>
    ${ordered.length ? `<div class="profile-alert-list">${ordered.map(alert => alertCard(alert, { semPessoa: true, profile: true })).join('')}</div>` : ''}
    ${profileCoverageSection(coverage, ordered)}

  </section>`;
}
function profileCoverageSection(coverage, alerts = []) {
  const rows = Array.isArray(coverage) ? coverage.filter(row => Number.isInteger(Number(row?.ano))) : [];
  if (!rows.length) return `<section class="card profile-alert-coverage"><h3 class="k">O que foi avaliado</h3><p class="muted">Sem cobertura de avaliação importada para este perfil.</p></section>`;
  const grouped = new Map();
  rows.forEach(row => {
    const year = Number(row.ano), group = grouped.get(year) || [];
    group.push(row); grouped.set(year, group);
  });
  const orderedAlerts = profileAlertChronology(alerts);
  const years = [...grouped.keys()].sort((a, b) => b - a).map(year => {
    const rules = grouped.get(year).map(row => {
      const matchesAlert = orderedAlerts.some(alert => Number(alert.ano || String(alert.periodo || '').slice(0, 4)) === year
        && (row.regra === 'pico' ? alert.tipo === 'pico' : alert.tipo === 'fornecedor'));
      if (row.regra === 'fornecedor') return `<li><b>Concentração em fornecedor:</b> ${row.avaliado
        ? `avaliada nas notas de ${esc(row.periodo || year)}${row.parcial ? ' · período parcial, o ano ainda pode receber notas' : ''}${matchesAlert ? ' · alerta registrado' : ' · nenhum alerta encontrado'}`
        : `não avaliada em ${year} (sem total positivo de notas)`}.</li>`;
      const evaluated = Array.isArray(row.avaliados) ? row.avaliados : [];
      const marked = Array.isArray(row.marcados) ? row.marcados : [];
      const skipped = (Array.isArray(row.naoAvaliados) ? row.naoAvaliados : []).filter(item => item.meses?.length)
        .map(item => `${alertMonthList(item.meses, year)}: ${esc(item.texto)}`).join('; ');
      return `<li><b>Mês acima da referência:</b> ${evaluated.length ? `avaliados ${alertMonthList(evaluated, year)}` : `nenhum mês de ${year} pôde ser avaliado`}${marked.length ? ` · alertas em ${alertMonthList(marked, year)}` : matchesAlert ? ' · alerta registrado' : evaluated.length ? ' · nenhum alerta nos meses avaliados' : ''}${skipped ? `. Não avaliados: ${skipped}` : ''}.</li>`;
    }).join('');
    const collected = [...new Set(grouped.get(year).map(row => row.coletadoEm).filter(value => typeof value === 'string'))].sort().at(-1);
    const ruleVersion = [...new Set(grouped.get(year).map(row => row.regraVersao).filter(Boolean))].join(', ');
    return `<article class="profile-alert-coverage-year"><h4>${year}</h4><ul>${rules}</ul>${collected || ruleVersion ? `<small>${[ruleVersion ? `Regra ${ruleVersion}` : '', collected ? `coleta de ${dateBR(collected)}` : ''].filter(Boolean).join(' · ')}</small>` : ''}</article>`;
  }).join('');
  return `<section class="card profile-alert-coverage"><h3 class="k">O que foi avaliado</h3><div class="profile-alert-coverage-years">${years}</div></section>`;
}
const PROFILE_VOTE_LIMIT = new Map();
const PROFILE_VOTE_PAGE = 10;
/* Quantas votações têm voto identificado: fica em "Como votou", separado da presença. */
function profileVoteCountHTML(shared) {
  const senate = shared.person.role === 'senador';
  if (senate) profileSenateEnsure();
  if (senate ? profileSenateLoading() : profileChamberVotesLoading(shared.id)) return '';
  const votes = votesForPerson(shared.id), knownVotes = votes.filter(record => record.recordedVote !== null);
  const presenceOnlyCount = knownVotes.filter(record => ['Presente', 'Presidiu'].includes(record.recordedVote)).length;
  const identifiedVotes = knownVotes.filter(record => senate ? ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Não votou'].includes(record.recordedVote) : !['Presente', 'Presidiu'].includes(record.recordedVote));
  const recordedVoteCount = identifiedVotes.filter(record => record.recordedVote !== 'Não votou').length;
  const voteSource = senate ? profileSenateSource('votacoes') : null;
  const votePeriod = senate && typeof profileSectionPeriod === 'function' ? profileSectionPeriod(voteSource) : '';
  return `<p class="citizen-vote-count">${senate && voteSource?.status === 'unavailable' ? 'Dados de votações nominais do Senado indisponíveis neste recorte.'
      : identifiedVotes.length ? `${senate ? 'Voto identificado em' : 'Votou em'} <b>${recordedVoteCount} de ${senate ? knownVotes.length : votes.length}</b> ${senate ? `votações do Senado com registro individual${votePeriod ? ` · ${esc(votePeriod)}` : ''}` : 'votações do Placar'}`
        : presenceOnlyCount || (senate && knownVotes.length) ? `Sem voto nominal identificado neste recorte${votePeriod ? ` · ${esc(votePeriod)}` : ''}.`
          : `Sem registros individuais ${senate ? 'nas votações nominais do Senado' : 'nas votações do Placar'}${votePeriod ? ` · ${esc(votePeriod)}` : ''}.`}</p>
    ${presenceOnlyCount ? `<p class="muted">${presenceOnlyCount} ${presenceOnlyCount === 1 ? 'registro só de presença ou presidência' : 'registros só de presença ou presidência'}.</p>` : ''}
    ${!senate && votes.length > knownVotes.length ? `<p class="muted">Em ${votes.length - knownVotes.length} ${votes.length - knownVotes.length === 1 ? 'votação não há registro' : 'votações não há registro'} individual na lista oficial: pode ser ausência, licença ou período fora do mandato. A fonte não diz qual.</p>` : ''}
    ${senate ? `${senateParticipationSummary(shared.participation)}<p class="muted">Sem linha individual não significa falta. Atividade parlamentar e registro de presença não contam como voto.</p>` : ''}`;
}
function profileVoteDetails(shared) {
  const senate = shared.person.role === 'senador';
  if (senate) profileSenateEnsure();
  if (senate ? profileSenateLoading() : profileChamberVotesLoading(shared.id)) return skel('linhas', 3);
  const votes = votesForPerson(shared.id), limit = PROFILE_VOTE_LIMIT.get(shared.id) || PROFILE_VOTE_PAGE;
  const source = senate ? profileSenateSource('votacoes') : null;
  const votePeriod = senate ? profileSectionPeriod(source) || (source ? 'período não informado' : 'recorte indisponível') : '';
  return `<span class="k">${senate ? `Votações nominais do Senado · ${esc(votePeriod)}` : 'Votações do Placar · texto principal de PL, PLP e PEC desde fev/2023'} · ${votes.length || 'sem registros'}</span>
    ${votes.length ? `<div class="votes">${votes.slice(0, limit).map(({ vote, recordedVote }) => {
      const voteLabel = recordedVote == null ? 'Sem registro importado' : vote.secreta ? 'Presença registrada · voto secreto' : senate && recordedVote === 'Presente' ? 'Presença registrada · sem voto' : String(recordedVote).toLowerCase();
      return profileVoteButton(vote, `<b>${esc(voteLabel)}</b><span>${esc(vote.titulo)}</span>${senate ? `<small>${esc(dateBR(vote.data))} · fonte oficial ↗</small>` : ''}`);
    }).join('')}</div>` : `<p class="muted">${senate ? 'Votos nominais do Senado ainda não disponíveis neste recorte.' : 'Votações do Placar indisponíveis no momento.'}</p>`}
    ${votes.length > limit ? `<button type="button" class="more" data-profile-votes-more="${esc(shared.id)}">Mostrar mais votações (${votes.length - limit})</button>` : ''}
    <p class="muted">O resumo conta votos identificados na fonte. ${senate ? 'Presença sem voto, atividade parlamentar, licenças e presidência não contam como voto nominal.' : 'Presença em voto secreto e quem presidiu aparecem à parte.'} Ausência de registro não significa que a pessoa não votou.</p>
    ${source ? `${profileSource(source, 'Fonte das votações do Senado')}${source.detail ? `<p class="muted">${esc(datesInTextBR(source.detail))}</p>` : ''}` : ''}
`;
}
function profileExpenseAnswerDetails(profileRecord, person, hasExpenseData) {
  const html = profileExpenseAnswer(profileRecord, person, hasExpenseData)
    .replace(' data-profile-answer="expenses"', '')
    .replace('class="card hero citizen-answer"', 'class="profile-expense-fallback-details"');
  return `<div data-profile-expense-details>${html}</div>`;
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
    ? { label: senate ? `Presença no Plenário · ${senatePresencePeriodLabel()}` : `Presença no Plenário · ${citizenQuotaPeriod(presence.inicio, presence.fim) || 'mandato'}`, values: [`${Math.round(presence.presente / presence.dias * 100)}%`], notes: [`${presence.presente} de ${presence.dias} ${senate ? 'sessões' : 'dias'}`] }
    : registered
      ? { label: `Presença registrada no Senado · ${senatePresencePeriodLabel()}`, values: [`${registered.presente} sessões`],
        notes: [Number.isInteger(registered.sessoesEmExercicio) ? `de ${registered.sessoesEmExercicio} em exercício · faltas não apuradas` : 'faltas e justificativas não apuradas'] }
      : { label: `Presença no Plenário · ${senate ? senatePresencePeriodLabel() : 'mandato'}`, values: ['Sem registro'], notes: ['ausência de dado não é zero'] };
  const alertRow = { label: 'Gastos incomuns na cota', values: [!hasExpenseData ? 'Sem dados' : alerts.length ? `${alerts.length} ${alerts.length === 1 ? 'alerta' : 'alertas'}` : 'Nenhum'],
    notes: ['pelas mesmas 2 regras para todos(as)'] };
  return {
    kicker: `Ficha · ${senate ? 'Senado' : 'Câmara'}`, title: citizenName(person.name),
    subtitle: [ROLE_LABELS[person.role], person.party, person.uf].filter(Boolean).join(' · '),
    rows: [costRow, workRow, alertRow], fileName: citizenName(person.name),
    footnote: `Fontes: ${senate ? 'Senado Federal' : 'Câmara dos Deputados'} (notas da cota${average !== null ? ', remuneração, gabinete' : ''} e presença). Retrato de ${f.snapshotAt ? dateBR(f.snapshotAt) : 'data não informada'}.`,
  };
}
/* "Na Câmara desde 2007": início da sequência ininterrupta de mandatos até o atual, não da carreira. */
function profileTenureLabel(shared) {
  const tenure = shared.tenure, year = /^(\d{4})-\d{2}-\d{2}$/.exec(tenure?.since || '')?.[1];
  if (!year || !['camara', 'senado'].includes(tenure.house)) return '';
  const where = tenure.house === 'senado' ? 'No Senado' : 'Na Câmara';
  return `<span class="citizen-tenure" title="${esc(`Sem interrupção desde ${dateBR(tenure.since)}. Mandatos anteriores separados por um intervalo não entram.`)}">${where} desde ${year}</span>`;
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
  const alerts = f.alertas || [], isChamberPerson = person.role === 'deputado';
  const personNumber = String(person.id).split(':')[1];
  const presenceUrl = isChamberPerson && /^\d+$/.test(personNumber || '') ? `https://www.camara.leg.br/deputados/${personNumber}/presenca-plenario/2026` : null;
  const sourcesHtml = `<p>Cota é reembolso de gastos com o trabalho: escritório, divulgação, carro e viagens.</p>
    <p class="src">Fonte: notas da cota publicadas ${isChamberPerson ? 'pela Câmara (sem as passagens aéreas, que ficam fora do arquivo aberto)' : 'pelo Senado'}. Retrato de ${f.snapshotAt ? esc(dateBR(f.snapshotAt)) : 'data não informada'}.</p>
    ${isChamberPerson ? `<p class="muted">Presença em sessões deliberativas do mandato atual, desde fev/2023. Média da Câmara: média das proporções individuais entre registros válidos. O selo compara os percentuais arredondados. Os dias observados podem variar entre mandatos.</p>
    ${presenceUrl ? `<a class="src" href="${esc(presenceUrl)}" target="_blank" rel="noopener">Fonte da presença no Plenário ↗</a>` : ''}
    <p class="muted">Os votos cobrem apenas a seleção do Placar em 2026. Cada votação abre seu resumo e fontes oficiais.</p>` : ''}
    ${!isChamberPerson ? ['presenca', 'votacoes'].map(key => { const source = profileSenateSource(key); return source ? `<p><b>${key === 'presenca' ? 'Presença' : 'Votações'} do Senado</b></p>${profileSource(source)}<p class="muted">${esc(datesInTextBR(source.detail))}</p>` : ''; }).join('') : ''}
    ${!isChamberPerson ? profileAttendanceSources(shared.id) : ''}
    <p class="muted">Alertas indicam registros para conferir, não conclusões de irregularidade. “Parecido com a média” mantém a faixa de diferença inferior a 10% na cota.</p>
    ${citizenSourceUrl(person) ? `<a class="fchip" href="${esc(citizenSourceUrl(person))}" target="_blank" rel="noopener">Página oficial ↗</a>` : ''}
    ${hasExpenseData ? `<a class="fchip" href="${esc('/api/c/gastos.csv?id=' + encodeURIComponent(person.id))}" download>Baixar todas as notas (CSV)</a>` : ''}
    ${hasExpenseData ? '<p class="muted">O arquivo traz uma nota por linha, desde fev/2023. Nas notas de 2023 a 2025, a coluna Documento fica vazia; o link da nota continua.</p>' : ''}`;
  return `<div class="citizen-profile-view">${back}
    <header class="citizen-profile-head"><div class="profile">${citizenAvatar(person, 88)}<div class="citizen-profile-id"><h1 class="n">${esc(citizenName(person.name))}</h1><span class="citizen-profile-role">${citizenRoleDescription(person)}</span><span class="citizen-profile-tags">${profileTenureLabel(shared)}${election?.summary ? `<span class="pill citizen-election" data-tone="${esc(election.tone)}"><i></i>${esc(election.summary)}</span>` : ''}</span></div></div>
      <div class="citizen-profile-actions"><button type="button" class="fchip citizen-profile-compare" data-cmp-start="${esc(shared.id)}">Comparar com outro(a) →</button>${shareActionsHTML(profileShareCard(f, shared, alerts, hasExpenseData))}</div></header>
    ${profileSummaryCards(shared, f, alerts, hasExpenseData)}
    ${profileCostPanel(shared, f, hasExpenseData)}
    <section class="profile-area" id="profile-work" aria-labelledby="profile-work-title">
      <header class="profile-area-head"><h2 class="h" id="profile-work-title">Como trabalha</h2><p>Presença, projetos apresentados e os votos individuais disponíveis neste recorte.</p></header>
      <div class="profile-work-grid">${profileAttendanceCard(shared)}${profileProjectsCard(shared)}${profileRecentVotesCard(shared)}</div>
    </section>
    ${profileAlertsSection(alerts, f.coberturaAlertas)}
    <section class="profile-detail-area" aria-labelledby="profile-more-title"><h2 class="h" id="profile-more-title">Mais detalhes</h2>
    ${profileSectionsHTML(person, {
      expenses: (!shared.cost && !shared.senateCost ? profileExpenseAnswerDetails(f, person, hasExpenseData) : '') + (person.role === 'deputado' ? profileCostDetails(shared.cost) : person.role === 'senador' ? senateCostDetails(shared.senateCost, f) : '') + profileExpenseDetails(f, hasExpenseData, person.role === 'deputado' ? shared.cost : null, shared.mandate),
      alerts: `<p>Os cartões e a cobertura aparecem acima. Esta seção mantém as regras e os limites metodológicos junto dos demais detalhes.</p>${ALERT_RULES_HTML}<p class="muted">Alertas indicam registros para conferir, não conclusões de irregularidade. A falta de alerta não significa gasto baixo nem regular.</p><button type="button" class="more" data-go="alerts">Metodologia completa →</button>`,
      votes: `${profileVoteCountHTML(shared)}${profileVoteDetails(shared)}`, sources: sourcesHtml,
    })}</section>
  </div>`;
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
  if (t.dataset.profileVotesMore) { PROFILE_VOTE_LIMIT.set(t.dataset.profileVotesMore, (PROFILE_VOTE_LIMIT.get(t.dataset.profileVotesMore) || PROFILE_VOTE_PAGE) + PROFILE_VOTE_PAGE); return rerender(); }
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
