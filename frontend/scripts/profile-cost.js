/* Custo do mandato atual na Câmara (fev/2023 até o último mês do snapshot), a partir da página individual
   de remuneração, da cota e da verba do gabinete. Valores da época, em centavos. */
const PROFILE_COST_START = '2023-02';
const PROFILE_COST_MANDATE_END = '2027-01';
const PROFILE_COST_SHORT = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const PROFILE_COST_LONG = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
const PROFILE_COST_PERIODS = new Set(Array.from({ length: 60 }, (_, index) => {
  const year = 2023 + Math.floor(index / 12);
  return `${year}-${String(index % 12 + 1).padStart(2, '0')}`;
}).filter(period => period >= PROFILE_COST_START && period <= PROFILE_COST_MANDATE_END));
const profileCostLabel = period => `${PROFILE_COST_SHORT[Number(period.slice(5)) - 1]}/${period.slice(0, 4)}`;
const PROFILE_COST_MONTHS = Object.fromEntries([...PROFILE_COST_PERIODS].map(period => [period, profileCostLabel(period)]));
const profileCostLongLabel = period => `${PROFILE_COST_LONG[Number(period.slice(5)) - 1]} de ${period.slice(0, 4)}`;
/* Fim do período: o último mês do snapshot (último mês com as quatro partes publicadas). */
function profileCostEnd(cost) {
  if (PROFILE_COST_PERIODS.has(cost?.periodEnd)) return cost.periodEnd;
  const months = cost?.months && typeof cost.months === 'object' ? Object.keys(cost.months) : [];
  return months.filter(period => PROFILE_COST_PERIODS.has(period)).sort().at(-1) || null;
}
function profileCostRange(cost) {
  const end = profileCostEnd(cost);
  return end ? `${profileCostLabel(PROFILE_COST_START)}–${profileCostLabel(end)}` : `desde ${profileCostLabel(PROFILE_COST_START)}`;
}
const PROFILE_COST_PARTS = [
  ['office', 'Verba do gabinete', 'Verba do gabinete'],
  ['remuneration', 'Salário bruto', 'Página de remuneração'],
  ['quota', 'Cota parlamentar', 'Notas da cota'],
  ['allowances', 'Auxílios', 'Página de remuneração'],
];

function profileCostInteger(value) {
  return Number.isSafeInteger(value) && !Object.is(value, -0);
}

function profileCostMoney(cents) {
  if (!profileCostInteger(cents)) return null;
  return (cents / 100).toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function profileCostPeriods(values) {
  return Array.isArray(values) ? [...new Set(values.filter(period => PROFILE_COST_PERIODS.has(period)))].sort() : [];
}

const profileCostSerial = period => Number(period.slice(0, 4)) * 12 + Number(period.slice(5)) - 1;

/* "fev/2023–jul/2026, 42 meses"; meses não seguidos viram trechos separados por vírgula. */
function profileCostMonthList(values, { count = true } = {}) {
  const periods = profileCostPeriods(values);
  if (!periods.length) return 'nenhum mês';
  const runs = [];
  periods.forEach(period => {
    const last = runs.at(-1);
    if (last && profileCostSerial(period) === profileCostSerial(last.at(-1)) + 1) last.push(period);
    else runs.push([period]);
  });
  const label = runs.map(run => run.length === 1 ? profileCostLabel(run[0])
    : `${profileCostLabel(run[0])}–${profileCostLabel(run.at(-1))}`).join(', ');
  return count ? `${label}, ${periods.length} ${periods.length === 1 ? 'mês' : 'meses'}` : label;
}

function profileCostSafeSource(source) {
  if (!source || typeof source !== 'object' || !PROFILE_COST_PERIODS.has(source.period)
      || typeof profileSafeUrl !== 'function') return null;
  const url = profileSafeUrl(source.url);
  return url ? { url, period: source.period } : null;
}

/* Um link por parte: o mês mais recente com fonte. Os demais meses ficam nos detalhes. */
function profileCostLatestSource(sources) {
  const links = (Array.isArray(sources) ? sources : []).map(profileCostSafeSource).filter(Boolean);
  return links.sort((left, right) => left.period.localeCompare(right.period)).at(-1) || null;
}

function profileCostAllOutside(cost) {
  const months = cost?.months && typeof cost.months === 'object' ? cost.months : {};
  const present = [...PROFILE_COST_PERIODS].filter(period => months[period]);
  return present.length > 0 && present.every(period => months[period].exercise === 'outside_mandate');
}

/* A fonte da cota de cada mês do mandato abre a lista de notas daquele mês, não o arquivo anual. */
function profileCostNotesToggle(personId, period, label) {
  if (!/^(camara|senado):\d+$/.test(personId || '') || !PROFILE_COST_PERIODS.has(period)) return '';
  return `<details class="citizen-cost-notes" data-cost-notes="${esc(period)}" data-cost-person="${esc(personId)}">
    <summary>${esc(label)}</summary><div class="citizen-cost-notes-body" aria-live="polite"></div></details>`;
}

function profileCostNotesHTML(data, personId) {
  const money = value => profileCostMoney(Math.round(value * 100)) || 'Sem dado';
  const notes = Array.isArray(data?.notas) ? data.notas : [];
  if (!notes.length) return '<p class="muted">Nenhuma nota de reembolso publicada neste mês.</p>';
  const [year, month] = String(data.periodo).split('-');
  const senate = /^senado:/.test(String(personId || ''));
  const rows = notes.map(note => {
    const url = typeof profileSafeUrl === 'function' ? profileSafeUrl(note.documentUrl) : null;
    return `<li><span class="citizen-cost-note-who">${esc(note.fornecedor || 'Fornecedor não informado')}</span><b class="mono">${esc(money(note.valor))}</b>
      <small>${esc(note.data ? dateBR(note.data) : 'sem data')} · ${esc(note.categoria || '')}</small>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${note.listaDaCamara ? 'Bilhetes do mês na Câmara' : 'Nota'} ↗</a>` : senate ? '' : '<span class="muted">Documento não publicado pela Câmara</span>'}</li>`;
  }).join('');
  const complement = data.complemento ? `<p class="muted">À parte, fora desse total: complemento do auxílio-moradia, ${esc(money(data.complemento.valor))} em ${data.complemento.notas} ${data.complemento.notas === 1 ? 'nota' : 'notas'}.</p>` : '';
  const fileUrl = typeof profileSafeUrl === 'function' ? profileSafeUrl(data.fonte?.url) : null;
  /* Desde ago/2025 as passagens emitidas pela agência da Câmara (SIGEPA) não estão no arquivo anual: vêm da
     página analítica da cota. Sem dizer isso, a soma da planilha não fecha com o total. */
  const page = data.passagensDaPagina && Number(data.passagensDaPagina.notas) > 0 ? data.passagensDaPagina : null;
  const pageUrl = page && typeof profileSafeUrl === 'function' ? profileSafeUrl(page.url) : null;
  const pageText = page ? ` Depois, some ${esc(money(page.valor))} das ${page.notas} ${page.notas === 1 ? 'linha' : 'linhas'} de passagem aérea emitida pela agência da Câmara (SIGEPA), que o arquivo anual deixou de trazer em ago/2025 e que a Câmara lista na ${pageUrl ? `<a href="${esc(pageUrl)}" target="_blank" rel="noopener">página dos bilhetes do mês</a>` : 'página analítica da cota'}.` : '';
  /* Senado: o portal tem o detalhe do mês por tipo de despesa, com o total de cada tipo; a soma deles dá o total. */
  if (senate) {
    const official = (Array.isArray(data.detalhesOficiais) ? data.detalhesOficiais : []).map(item => {
      const url = typeof profileSafeUrl === 'function' ? profileSafeUrl(item.url) : null;
      return `<li>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(item.categoria)} em ${esc(profileCostLabel(data.periodo))} ↗</a>` : esc(item.categoria)}: <b class="mono">${esc(money(item.valor))}</b></li>`;
    }).join('');
    return `<ul class="citizen-cost-note-list">${rows}</ul>
    <p><b>Total: ${esc(money(data.total))}</b>, soma das ${notes.length} ${notes.length === 1 ? 'nota' : 'notas'} acima.</p>
    ${official ? `<p class="muted">No portal do Senado, cada tipo de despesa tem o detalhe do mês, com o total do tipo; somados, dão o total acima:</p><ul class="citizen-cost-official">${official}</ul>` : ''}`;
  }
  return `<ul class="citizen-cost-note-list">${rows}</ul>
    <p><b>Total: ${esc(money(data.total))}</b>, soma das ${notes.length} ${notes.length === 1 ? 'nota' : 'notas'} acima.</p>${complement}
    <p class="muted">${page ? 'As notas vêm do arquivo oficial da Câmara e, as passagens emitidas pela agência, da página de bilhetes da Câmara.' : 'Todas as notas vêm do arquivo oficial da Câmara, com ou sem documento.'} O documento é uma cópia da nota que a Câmara nem sempre publica; em outubro de 2026, deixou de publicar os das notas de telefonia. Para conferir na planilha da Câmara${fileUrl ? ` (<a href="${esc(fileUrl)}" target="_blank" rel="noopener">arquivo anual</a>, com todos os deputados, cerca de 40 MB)` : ''}: filtre <code>ideCadastro</code> = ${esc(String(personId).split(':')[1])} e <code>numMes</code> = ${Number(month)} e some a coluna <code>vlrLiquido</code>${data.complemento ? ', sem as linhas de <code>COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA</code>, que ficam fora desse total' : ''}.${pageText}</p>`;
}

/* Carrega as notas só quando a pessoa abre a lista. */
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('toggle', event => {
    const details = event.target;
    if (!details?.matches?.('[data-cost-notes]') || !details.open || details.dataset.loaded) return;
    const body = details.querySelector('.citizen-cost-notes-body');
    const path = `/api/c/notas?id=${encodeURIComponent(details.dataset.costPerson)}&mes=${encodeURIComponent(details.dataset.costNotes)}`;
    details.dataset.loaded = '1';
    body.innerHTML = '<p class="muted">Carregando as notas…</p>';
    const get = typeof citizenGet === 'function' ? citizenGet : url => fetch(url, { headers: { Accept: 'application/json' } }).then(r => r.ok ? r.json() : Promise.reject(r));
    get(path).then(data => { body.innerHTML = profileCostNotesHTML(data, details.dataset.costPerson); })
      .catch(() => { delete details.dataset.loaded; body.innerHTML = '<p class="muted">Não deu para carregar as notas agora. Feche e abra de novo para tentar outra vez.</p>'; });
  }, true);
}

/* As notas da cota de um mês continuam chegando por semanas: em out/2026, a cota de set estava em cerca de
   20% do normal e a de jul, perto de 90%. Um mês só é o número principal com 3 meses de folga até a
   fotografia dos dados (`asOf`, a data das notas importadas). Sem essa data, não há como julgar e vale o mais recente. */
const PROFILE_COST_SETTLE_MONTHS = 3;
function profileCostSettled(period, asOf) {
  const reference = /^\d{4}-\d{2}/.test(String(asOf || '')) ? String(asOf).slice(0, 7) : null;
  return !reference || profileCostSerial(reference) - profileCostSerial(period) >= PROFILE_COST_SETTLE_MONTHS;
}
/* O mês mais recente com as notas da cota já assentadas; se nenhum tiver a folga, o mais recente, marcado como
   `settled: false`. `later`: meses completos mais novos, cuja cota ainda recebe notas. */
function profileCostPickMonth(periods, asOf) {
  const sorted = [...new Set(periods)].sort();
  const settled = sorted.filter(period => profileCostSettled(period, asOf)).at(-1);
  if (settled) return { period: settled, settled: true, later: sorted.filter(period => period > settled) };
  return sorted.length ? { period: sorted.at(-1), settled: false, later: [] } : null;
}
/* Meses que entram na média: os com as notas já assentadas; se nenhum tiver a folga, todos (o cartão avisa). */
function profileCostSettledPeriods(periods, asOf) {
  const sorted = [...new Set(periods)].sort();
  const settled = sorted.filter(period => profileCostSettled(period, asOf));
  return settled.length ? settled : sorted;
}

/* Média do mandato sobre os meses com as quatro partes e as notas já assentadas. Mesma conta de `principal` em
   ingest/mandate_cost_composition.py e de `chamber_average` em backend/costs.py: soma das médias de cada parte,
   arredondada para baixo uma vez; numa lacuna confirmada, a parte é média só dos meses em que foi publicada.
   Quando nenhum mês fica fora, vale o número do snapshot. */
function profileCostAverage(cost, asOf) {
  const used = profileCostPeriods(cost?.usedMonths);
  if (!used.length || !profileCostInteger(cost?.monthlyAverageCents)) return null;
  const months = profileCostSettledPeriods(used, asOf);
  if (months.length === used.length || !cost.months || typeof cost.months !== 'object') return { cents: cost.monthlyAverageCents, months: used };
  let numerator = 0n, denominator = 1n;
  for (const [key] of PROFILE_COST_PARTS) {
    const values = months.map(period => cost.months[period]?.valuesCents?.[key]).filter(profileCostInteger);
    if (!values.length) return null;
    const count = BigInt(values.length);
    numerator = numerator * count + values.reduce((sum, value) => sum + BigInt(value), 0n) * denominator;
    denominator *= count;
  }
  let cents = numerator / denominator;
  if (numerator % denominator !== 0n && numerator < 0n) cents -= 1n;
  return { cents: Number(cents), months };
}

/* Mês mais recente com as quatro partes publicadas e as notas da cota assentadas: o número principal da ficha. As
   partes são as daquele mês, então o total é a soma das linhas. Parte vazia (lacuna confirmada na fonte) não vira zero. */
function profileCostLatest(cost, asOf) {
  // Uma lacuna confirmada pode entrar na média de cada parte, mas nunca formar um total mensal completo.
  const complete = profileCostPeriods(cost?.usedMonths).filter(period =>
    PROFILE_COST_PARTS.every(([key]) => profileCostInteger(cost?.months?.[period]?.valuesCents?.[key])));
  const pick = profileCostPickMonth(complete, asOf);
  const month = pick ? cost?.months?.[pick.period] : null;
  if (!month || typeof month !== 'object') return null;
  const values = month.valuesCents && typeof month.valuesCents === 'object' ? month.valuesCents : {};
  const parts = PROFILE_COST_PARTS.map(([key]) => values[key]);
  return { ...pick, month, parts, totalCents: parts.reduce((sum, value) => sum + value, 0) };
}

const profileCostNextPeriod = period => {
  const serial = profileCostSerial(period) + 1;
  return `${Math.floor(serial / 12)}-${String(serial % 12 + 1).padStart(2, '0')}`;
};
const profileCostJoin = items => items.length > 1 ? `${items.slice(0, -1).join(', ')} e ${items.at(-1)}` : items[0] || '';
const profileCostCapitalize = text => text.charAt(0).toUpperCase() + text.slice(1);
const profileCostLowerFirst = text => text.charAt(0).toLowerCase() + text.slice(1);

/* O que falta na base no mês seguinte. Ausência no snapshot não prova ausência na fonte oficial. */
function profileCostNextGap(cost, period) {
  const next = profileCostNextPeriod(period);
  if (!PROFILE_COST_PERIODS.has(next)) return '';
  const label = profileCostLabel(next);
  const month = cost?.months?.[next];
  if (!month || typeof month !== 'object') return `A base do painel ainda não reúne todas as partes de ${label}.`;
  if (month.exercise === 'outside_mandate') return `Em ${label}, não estava no mandato.`;
  const values = month.valuesCents && typeof month.valuesCents === 'object' ? month.valuesCents : {};
  const missing = PROFILE_COST_PARTS.filter(([key]) => !profileCostInteger(values[key])).map(([, label]) => label.toLowerCase());
  if (month.exercise === 'in_office' && missing.length) return `Em ${label}, ${missing.length === 1 ? 'falta' : 'faltam'} ${profileCostJoin(missing)}.`;
  const reason = (Array.isArray(month.exclusionReasons) ? month.exclusionReasons : []).map(profileCostExclusionLabel).find(Boolean);
  return reason ? `Em ${label}: ${profileCostLowerFirst(reason)}` : '';
}

/* "Por que <mês>?": diz por que o número principal é aquele mês. (a) é o último mês com todas as partes e `next`
   diz o que falta no seguinte; (b) há meses completos mais novos, mas com notas da cota ainda chegando; (c) nenhum
   mês tem a folga, e a cota do mês mostrado ainda pode subir. */
function profileCostWhyMonth(latest, next = '') {
  if (!latest) return '';
  const label = profileCostLabel(latest.period);
  let reason, kind;
  if (!latest.settled) {
    kind = 'none-settled';
    reason = `Nenhum mês com todas as partes publicadas tem ainda as notas da cota assentadas. ${profileCostCapitalize(label)} é o mais recente com todas as partes, mas a cota dele ainda tem notas chegando: o valor pode subir.`;
  } else if (latest.later.length) {
    kind = 'quota-settling';
    const one = latest.later.length === 1;
    reason = `${profileCostCapitalize(profileCostJoin(latest.later.map(profileCostLabel)))} já ${one ? 'tem' : 'têm'} todas as partes publicadas, mas a cota ${one ? 'desse mês' : 'desses meses'} ainda tem notas chegando. ${profileCostCapitalize(label)} é o mês mais recente com as notas já assentadas.`;
  } else {
    kind = 'latest-complete';
    reason = `${profileCostCapitalize(label)} é o mês mais recente com todas as partes disponíveis na base do painel.${next ? ` ${next}` : ''}`;
  }
  return `<details class="citizen-cost-notes profile-cost-why" data-cost-why="${kind}"><summary>Por que ${esc(label)}?</summary>
    <p>${esc(reason)}</p>
    <p>As notas da cota chegam semanas depois do gasto, então um mês só aparece aqui com ${PROFILE_COST_SETTLE_MONTHS} meses de folga, quando as notas já estão assentadas. O mês avança a cada atualização dos dados.</p></details>`;
}

/* "Salário bruto" soma todas as tabelas da página de remuneração do mês (normal e complementares). Quando difere
   do subsídio de referência (PROFILE_SALARY), a linha diz por quê: a página oficial mostra o subsídio em destaque,
   e o leitor compararia os dois números. Só a partir da data em que o subsídio de referência vale. O motivo vem das
   linhas publicadas no mês (`remunerationComponentsCents`), com os nomes da Câmara; sem elas, fica o texto geral. */
const PROFILE_SALARY_LINES = {
  personal_advantages: 'Vantagens de Natureza Pessoal', commission_role: 'Função ou Cargo em Comissão',
  vacation_third: 'Férias (1/3 Constitucional)', other_eventual_remuneration: 'Outras Remunerações Eventuais/Provisórias',
  permanence_bonus: 'Abono Permanência', constitutional_reduction: 'Redutor Constitucional',
};
function profileCostSignedMoney(cents) {
  return `${cents < 0 ? '−' : '+'}${profileCostMoney(Math.abs(cents))}`;
}
function profileCostSalaryReasons(lines, subsidy, below, month) {
  const reasons = [];
  const fixed = lines.fixed_remuneration;
  if (profileCostInteger(fixed) && Math.abs(fixed - subsidy) > 100 && (fixed < subsidy) === below) {
    const days = month && Number.isInteger(month.daysInOffice) ? month.daysInOffice : null;
    const monthDays = /^\d{4}-\d{2}$/.test(String(month?.period || '')) ? new Date(Date.UTC(Number(month.period.slice(0, 4)), Number(month.period.slice(5)), 0)).getUTCDate() : null;
    const partial = below && days !== null && monthDays !== null && days < monthDays ? ` (${days} de ${monthDays} dias em exercício)` : '';
    reasons.push(`Remuneração Fixa de ${profileCostMoney(fixed)}${partial}`);
  }
  Object.entries(PROFILE_SALARY_LINES).forEach(([key, label]) => {
    const value = lines[key];
    if (!profileCostInteger(value) || value === 0 || (value < 0) !== below) return;
    const note = key === 'other_eventual_remuneration' && value < 0
      ? ', que a Câmara atribui a acertos de meses anteriores ou descontos de falta e impontualidade' : '';
    reasons.push(`${profileCostSignedMoney(value)} em “${label}”${note}`);
  });
  return reasons;
}
function profileCostSalaryNote(cents, period, month = null) {
  const reference = typeof PROFILE_SALARY !== 'undefined' ? PROFILE_SALARY?.deputado : null;
  if (!profileCostInteger(cents) || !reference || !Number.isFinite(reference.amount) || !/^\d{4}-\d{2}$/.test(String(period || ''))
      || String(reference.since || '').slice(0, 7) > period) return '';
  const subsidy = Math.round(reference.amount * 100);
  if (Math.abs(cents - subsidy) <= 100) return '';
  const money = profileCostMoney(subsidy), below = cents < subsidy;
  const lines = month && month.remunerationComponentsCents && typeof month.remunerationComponentsCents === 'object' ? month.remunerationComponentsCents : null;
  const reasons = lines ? profileCostSalaryReasons(lines, subsidy, below, month) : [];
  if (reasons.length) return `${below ? 'abaixo' : 'acima'} do subsídio de ${money}: ${reasons.join('; ')}`;
  return below
    ? `abaixo do subsídio de ${money}: redução ao teto constitucional, exercício por parte do mês ou outro desconto publicado`
    : `acima do subsídio de ${money}: inclui férias, retroativos ou outras parcelas pagas no mês`;
}
/* Valor da parte: do mês mais recente (`perMonth` falso) ou a média das partes sem mês completo. */
function profileCostPartRow([key, label, sourceLabel], value, scale, { source = null, detail = '', personId = null, gap = false, perMonth = false } = {}) {
  const money = profileCostMoney(value);
  const notes = key === 'quota' && source ? profileCostNotesToggle(personId, source.period, `Ver as notas de ${PROFILE_COST_MONTHS[source.period]}`) : '';
  const width = money !== null && scale > 0 && value > 0 ? Math.max(1, value / scale * 100).toFixed(1) : 0;
  return `<div class="citizen-cost-part" data-cost-part="${key}">
    <div class="citizen-cost-part-label"><span>${label}</span><b class="mono">${money === null ? (gap ? 'Não publicado pela Câmara' : 'Sem dado') : `${esc(money)}${perMonth ? '<small>/mês</small>' : ''}`}</b></div>
    ${money !== null ? `<span class="citizen-cost-bar" aria-hidden="true"><i style="width:${width}%"></i></span>` : ''}
    <small>${detail ? `${esc(detail)} · ` : ''}${notes || (source
      ? `<a href="${esc(source.url)}" target="_blank" rel="noopener" aria-label="${esc(sourceLabel)}, ${esc(PROFILE_COST_MONTHS[source.period])}">${esc(sourceLabel)} ↗</a>`
      : 'fonte indisponível')}</small>
  </div>`;
}

function profileCostChristmasLine(cost) {
  const months = profileCostPeriods(cost?.christmasBonus?.months);
  const value = months.length ? profileCostMoney(cost.christmasBonus.amountCents) : null;
  if (value === null) return '';
  const when = months.length === 1
    ? `em ${PROFILE_COST_LONG[Number(months[0].slice(5)) - 1]} de ${months[0].slice(0, 4)}`
    : `em ${profileCostMonthList(months, { count: false })}`;
  return `<p class="citizen-cost-extra">13º salário ${esc(when)}: <b class="mono">${esc(value)}</b> <span>(fora da média)</span></p>`;
}

/* Número de destaque arredondado para mil; o valor exato fica logo abaixo. */
function profileCostShort(cents) {
  if (!profileCostInteger(cents)) return '—';
  const amount = cents / 100;
  return amount >= 1000 ? `R$ ${Math.round(amount / 1000).toLocaleString('pt-BR')} mil`
    : `R$ ${Math.round(amount).toLocaleString('pt-BR')}`;
}
function profileCostStackedComposition(parts, totalCents, labels) {
  if (!profileCostInteger(totalCents) || totalCents <= 0 || !Array.isArray(parts) || !Array.isArray(labels) || parts.length !== labels.length) return '';
  const descriptions = parts.map((value, index) => `${labels[index]}: ${profileCostMoney(value) || 'Sem dado'}`);
  const segments = parts.map((value, index) => {
    if (!profileCostInteger(value) || value <= 0) return '';
    const width = Math.min(100, value / totalCents * 100).toFixed(2);
    return `<i style="width:${width}%;background:var(--cat${index + 1})"></i>`;
  }).join('');
  return `<div class="profile-cost-stack" role="img" aria-label="${esc(descriptions.join('; '))}">${segments}</div>`;
}
function profileCostAnswer(cost, asOf) {
  const used = profileCostPeriods(cost?.usedMonths);
  const average = profileCostAverage(cost, asOf);
  const amount = average ? profileCostMoney(average.cents) : null;
  const hasPrincipal = used.length > 0 && amount !== null;
  const parts = cost?.parts && typeof cost.parts === 'object' ? cost.parts : {};
  const partOf = key => (parts[key] && typeof parts[key] === 'object' ? parts[key] : {});
  const latest = hasPrincipal ? profileCostLatest(cost, asOf) : null;
  let principal;
  let rows = '';
  let kicker = 'Média por mês';
  if (latest) {
    const { period, month, parts: values, totalCents } = latest;
    const label = PROFILE_COST_MONTHS[period];
    const gaps = new Set(Array.isArray(month.sourceGaps) ? month.sourceGaps : []);
    const sources = month.sources && typeof month.sources === 'object' ? month.sources : {};
    const scale = Math.max(0, ...values.filter(profileCostInteger));
    const christmas = profileCostMoney(month.christmasBonusCents);
    kicker = 'Mês mais recente';
    /* A Câmara publica R$ 0,00 de verba de gabinete para alguns suplentes que têm equipe listada (ex.: Hildo Rocha
       em 2025–2026): o zero é o publicado, mas o total do mês fica sem o custo da equipe e precisa dizer isso. */
    rows = PROFILE_COST_PARTS.map((entry, index) => profileCostPartRow(entry, values[index], scale,
      { source: profileCostSafeSource(sources[entry[0]]), personId: cost.id, gap: gaps.has(entry[0]),
        detail: entry[0] === 'remuneration' ? profileCostSalaryNote(values[index], period, month)
          : entry[0] === 'office' && values[index] === 0 ? 'a Câmara publica R$ 0,00 neste mês; o total pode estar sem o custo da equipe do gabinete' : '' })).join('');
    principal = `<div class="profile-cost-total"><span>Custou</span><b class="mono">${esc(profileCostShort(totalCents))}</b><span>em ${esc(label)}</span></div>
      <p class="citizen-cost-exact">Valor exato: <span class="mono">${esc(profileCostMoney(totalCents))}</span>, a soma das quatro partes abaixo</p>
      ${profileCostStackedComposition(values, totalCents, PROFILE_COST_PARTS.map(([, partLabel]) => partLabel))}
      ${profileCostWhyMonth(latest, latest.settled && !latest.later.length ? profileCostNextGap(cost, period) : '')}
      ${christmas !== null ? `<p class="citizen-cost-extra">13º salário em ${esc(label)}: <b class="mono">${esc(christmas)}</b> <span>(fora da soma)</span></p>` : ''}
      <p class="citizen-cost-period">Média do mandato: <span class="mono">${esc(amount)}</span> por mês, ${esc(profileCostMonthList(average.months))} em exercício. Só entram meses com salário, auxílios, cota e verba de gabinete publicados${latest.settled ? ' e com as notas da cota já assentadas' : ''}.</p>`;
  } else if (profileCostAllOutside(cost)) {
    const end = profileCostEnd(cost);
    kicker = 'Custo do mandato';
    principal = `<p class="citizen-cost-unavailable">Não estava no mandato entre ${esc(profileCostLongLabel(PROFILE_COST_START))}${end ? ` e ${esc(profileCostLongLabel(end))}` : ''}.</p>`;
  } else {
    const values = PROFILE_COST_PARTS.map(([key]) => partOf(key).averageCents);
    const scale = Math.max(0, ...values.filter(profileCostInteger));
    rows = PROFILE_COST_PARTS.map((entry, index) => {
      const part = partOf(entry[0]);
      const months = profileCostPeriods(part.months);
      return profileCostPartRow(entry, values[index], scale, { source: profileCostLatestSource(part.sources), personId: cost?.id,
        detail: months.length ? `média de ${profileCostMonthList(months)}` : '', perMonth: true });
    }).join('');
    principal = `<p class="citizen-cost-unavailable">Sem média mensal para o mandato (${esc(profileCostRange(cost))}).</p>
      <p class="citizen-cost-period">Em nenhum mês do mandato as quatro partes abaixo foram publicadas juntas. Veja cada parte com seus próprios meses.</p>`;
  }
  return `<article class="card profile-cost-breakdown" data-profile-cost-house="camara">
    <span class="k">${kicker} · Câmara · mandato 2023–2027</span>
    ${principal}
    ${rows ? `<div class="citizen-cost-parts">${rows}</div>` : ''}
    <div class="profile-card-links"><button type="button" class="more" data-profile-open="expenses">Como calculamos e ver mês a mês →</button><button type="button" class="more" data-profile-open="sources">Fontes e datas →</button></div>
  </article>`;
}

/* "Qual mês aparece no Quanto custa?", no "Como calculamos" das duas Casas. */
const PROFILE_COST_MONTH_RULE = `<p class="muted"><b>Qual mês aparece no “Quanto custa?”:</b> o mais recente com todas as partes publicadas e com ${PROFILE_COST_SETTLE_MONTHS} meses de folga até a data das notas importadas. As notas da cota entram semanas depois do gasto: na base de outubro de 2026, a cota de setembro estava em cerca de 20% do normal e a de julho, perto de 90%. Os meses mais novos ficam fora do número principal e da média até as notas assentarem. O mês muda a cada atualização dos dados.</p>`;

const PROFILE_COST_GAP_LABELS = { office: 'a verba do gabinete' };

/* Lacunas confirmadas na fonte: o mês entra na média e a parte fica vazia. */
function profileCostGaps(cost) {
  const gaps = cost?.sourceGapMonths && typeof cost.sourceGapMonths === 'object' ? cost.sourceGapMonths : {};
  return Object.entries(gaps).filter(([period, parts]) => PROFILE_COST_PERIODS.has(period) && Array.isArray(parts))
    .map(([period, parts]) => [period, parts.filter(part => PROFILE_COST_GAP_LABELS[part])]).filter(([, parts]) => parts.length);
}

function profileCostGapNote(cost) {
  return profileCostGaps(cost).map(([period, parts]) =>
    ` A Câmara não publicou ${parts.map(part => PROFILE_COST_GAP_LABELS[part]).join(' e ')} de ${PROFILE_COST_MONTHS[period]}; essa parte fica vazia no mês e sua média usa os demais meses.`).join('');
}

function profileCostExclusionLabel(reason) {
  const labels = {
    outside_mandate: 'Fora do mandato neste mês.',
    exercise_unknown: 'Não foi possível confirmar o exercício do mandato neste mês.',
    payroll_unavailable: 'A página individual de remuneração deste mês não foi lida por completo.',
    missing_parts: 'Faltou pelo menos uma das quatro partes neste mês.',
    quota_snapshot_unverified: 'As notas da cota deste mês não foram conferidas contra o arquivo oficial.',
    office_incomplete: 'Os dados da verba do gabinete deste mês estão incompletos.',
  };
  return labels[reason] || null;
}

function profileCostDaysInMonth(period) {
  return new Date(Number(period.slice(0, 4)), Number(period.slice(5)), 0).getDate();
}

function profileCostMonthlyParts(month, personId) {
  const values = month.valuesCents && typeof month.valuesCents === 'object' ? month.valuesCents : {};
  const sources = month.sources && typeof month.sources === 'object' ? month.sources : {};
  const gaps = new Set(Array.isArray(month.sourceGaps) ? month.sourceGaps : []);
  const notes = profileCostInteger(values.quota) ? profileCostNotesToggle(personId, month.period, 'Ver as notas da cota deste mês') : '';
  const rows = PROFILE_COST_PARTS.map(([key, label]) => {
    const value = profileCostMoney(values[key]);
    if (value === null) return `<li><span>${label}</span><b>${gaps.has(key) ? 'Não publicado pela Câmara' : 'Sem dado'}</b></li>`;
    const source = profileCostSafeSource(sources[key]);
    const withNotes = key === 'quota' && notes;
    const sourceLink = withNotes ? '<span class="muted">Notas ↓</span>' : source
      ? `<a href="${esc(source.url)}" target="_blank" rel="noopener" aria-label="Fonte de ${esc(label)} em ${esc(PROFILE_COST_MONTHS[source.period])}">Fonte ↗</a>`
      : '<span class="muted">Sem link</span>';
    return `<li><span>${label}</span><b class="mono">${esc(value)}</b>${sourceLink}</li>`;
  }).join('');
  return `<ul class="citizen-cost-month-parts">${rows}</ul>${notes}`;
}

function profileCostDetails(cost, asOf) {
  if (!cost || typeof cost !== 'object') return '';
  const months = cost.months && typeof cost.months === 'object' ? cost.months : {};
  const eligible = new Set(profileCostPeriods(cost.usedMonths));
  const used = new Set(profileCostAverage(cost, asOf)?.months || []);
  const monthCard = period => {
    const month = months[period];
    if (!month || typeof month !== 'object') return '';
    const inOffice = month.exercise === 'in_office';
    const days = Number.isInteger(month.daysInOffice) ? month.daysInOffice : null;
    const status = inOffice
      ? (days !== null && days < profileCostDaysInMonth(period) ? `Em exercício por ${days} ${days === 1 ? 'dia' : 'dias'}` : 'Em exercício')
      : month.exercise === 'outside_mandate' ? 'Fora do mandato' : 'Exercício não confirmado';
    const exerciseSource = month.exerciseSource && typeof profileSafeUrl === 'function' ? profileSafeUrl(month.exerciseSource.url) : null;
    /* Fora do mandato, as partes ausentes são esperadas e não precisam de explicação. */
    const reasons = (inOffice && Array.isArray(month.exclusionReasons) ? month.exclusionReasons : []).map(profileCostExclusionLabel).filter(Boolean);
    const christmas = inOffice ? profileCostMoney(month.christmasBonusCents) : null;
    const housingSource = profileCostSafeSource(month.sources?.housing);
    const housing = inOffice && typeof month.housingDiscrepancy === 'boolean' && profileCostInteger(month.housingAllowanceForCheckCents) && housingSource
      ? `<p class="muted">Conferência com o portal de moradia: ${month.housingDiscrepancy ? 'valores diferentes' : 'valores iguais'}; o portal não entra na soma. <a href="${esc(housingSource.url)}" target="_blank" rel="noopener">Conferir ↗</a></p>` : '';
    const property = inOffice && Number.isInteger(month.functionalPropertyDays) && month.functionalPropertyDays > 0
      ? `<p class="muted">Apartamento funcional: ${month.functionalPropertyDays} ${month.functionalPropertyDays === 1 ? 'dia' : 'dias'} (sem valor estimado).</p>` : '';
    return `<div class="citizen-cost-month" data-cost-month="${period}">
      <b>${esc(PROFILE_COST_MONTHS[period])}</b>
      <span>${esc(status)}${used.has(period) ? ' · <span class="citizen-cost-used">entra na média</span>' : eligible.has(period) && !profileCostSettled(period, asOf) ? ' · fora da média: notas da cota ainda podem chegar' : ''}${exerciseSource ? ` · <a href="${esc(exerciseSource)}" target="_blank" rel="noopener">Conferir ↗</a>` : ''}</span>
      ${inOffice ? profileCostMonthlyParts(month, cost.id) : ''}
      ${christmas !== null ? `<p class="muted">13º salário${period.endsWith('-06') ? ' (adiantamento)' : ''}: ${esc(christmas)} (fora da média).</p>` : ''}
      ${reasons.map(label => `<p class="muted">${esc(label)}</p>`).join('')}
      ${property}${housing}
    </div>`;
  };
  /* Um bloco por ano; o ano mais recente começa aberto. */
  const years = [...new Set([...PROFILE_COST_PERIODS].map(period => period.slice(0, 4)))].reverse();
  const rows = years.map((year, index) => {
    const cards = [...PROFILE_COST_PERIODS].filter(period => period.startsWith(year)).map(monthCard).filter(Boolean).join('');
    return cards ? `<details class="citizen-cost-year" data-cost-year="${year}"><summary>${year}</summary>${cards}</details>` : '';
  }).join('');
  const complementMonths = profileCostPeriods(cost.complement?.months);
  const complementValue = complementMonths.length ? profileCostMoney(cost.complement?.signedAmountCents) : null;
  const complement = complementValue !== null
    ? `<p><b>Complemento do auxílio-moradia lançado na cota:</b> ${esc(complementValue)} em ${esc(profileCostMonthList(complementMonths))}. A Câmara publica esse valor com sinal negativo; ele aparece aqui como publicado e fica fora da média acima.</p>` : '';
  const inventoryMonths = profileCostPeriods(cost.payrollInventoryPartialMonths);
  const inventory = inventoryMonths.length
    ? `<p class="muted citizen-cost-footnote">Nota: em ${esc(profileCostMonthList(inventoryMonths, { count: false }))}, o inventário mensal da Câmara lista folhas complementares sem identificar a qual deputado(a) pertencem. A média usa o que a página individual de remuneração publica para esta pessoa.</p>` : '';
  return `<section class="citizen-detail-part citizen-cost-details"><h3 class="k">Custo do mandato mês a mês · ${esc(profileCostRange(cost))}</h3>
    ${profileCostChristmasLine(cost)}
    <p class="citizen-cost-note">Soma salário bruto, auxílios, cota parlamentar e verba do gabinete. Fichas de senadores(as) mostram as despesas do Senado à parte, com partes diferentes; os números não são comparáveis. Valores da época, sem correção pela inflação.${profileCostGapNote(cost)} Fora da conta: encargos do gabinete e apartamento funcional. Detalhes e fontes de cada mês em “Ver mais”.</p>
    <p class="muted">Como calculamos: em cada mês em exercício, somamos a remuneração bruta de todas as tabelas da página individual (normal, complementares), os auxílios dessa mesma página, a cota parlamentar sem o complemento de moradia e a verba do gabinete. A média usa só os meses com as quatro partes publicadas e com as notas da cota já assentadas; meses parciais não são estimados para o mês inteiro. Se a Câmara não publicou uma parte para ninguém naquele mês, o mês entra com essa parte vazia e a média dela usa os outros meses. O 13º fica à parte. Diárias e vantagens indenizatórias não entram. Valores da época, sem correção pela inflação, arredondados para baixo ao centavo.</p>
    ${PROFILE_COST_MONTH_RULE}
    ${complement}
    ${rows ? `<div class="citizen-cost-months">${rows}</div>` : '<p class="muted">Sem detalhes mensais disponíveis.</p>'}
    ${inventory}
  </section>`;
}
