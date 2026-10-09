/* Custo do mandato atual na Câmara (fev/2023–jul/2026), a partir da página individual de remuneração,
   da cota e da verba do gabinete. Valores da época, em centavos. */
const PROFILE_COST_START = '2023-02';
const PROFILE_COST_END = '2026-07';
const PROFILE_COST_SHORT = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const PROFILE_COST_LONG = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
const PROFILE_COST_PERIODS = new Set(Array.from({ length: 48 }, (_, index) => {
  const year = 2023 + Math.floor(index / 12);
  return `${year}-${String(index % 12 + 1).padStart(2, '0')}`;
}).filter(period => period >= PROFILE_COST_START && period <= PROFILE_COST_END));
const profileCostLabel = period => `${PROFILE_COST_SHORT[Number(period.slice(5)) - 1]}/${period.slice(0, 4)}`;
const PROFILE_COST_MONTHS = Object.fromEntries([...PROFILE_COST_PERIODS].map(period => [period, profileCostLabel(period)]));
const PROFILE_COST_RANGE = `${profileCostLabel(PROFILE_COST_START)}–${profileCostLabel(PROFILE_COST_END)}`;
const PROFILE_COST_PARTS = [
  ['remuneration', 'Salário bruto', 'Página de remuneração'],
  ['allowances', 'Auxílios', 'Página de remuneração'],
  ['quota', 'Cota parlamentar', 'Notas da cota'],
  ['office', 'Verba do gabinete', 'Verba do gabinete'],
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
  if (!/^camara:\d+$/.test(personId || '') || !PROFILE_COST_PERIODS.has(period)) return '';
  return `<details class="citizen-cost-notes" data-cost-notes="${esc(period)}" data-cost-person="${esc(personId)}">
    <summary>${esc(label)}</summary><div class="citizen-cost-notes-body" aria-live="polite"></div></details>`;
}

function profileCostNotesHTML(data, personId) {
  const money = value => profileCostMoney(Math.round(value * 100)) || 'Sem dado';
  const notes = Array.isArray(data?.notas) ? data.notas : [];
  if (!notes.length) return '<p class="muted">Nenhuma nota de reembolso publicada neste mês.</p>';
  const [year, month] = String(data.periodo).split('-');
  const rows = notes.map(note => {
    const url = typeof profileSafeUrl === 'function' ? profileSafeUrl(note.documentUrl) : null;
    return `<li><span class="citizen-cost-note-who">${esc(note.fornecedor || 'Fornecedor não informado')}</span><b class="mono">${esc(money(note.valor))}</b>
      <small>${esc(note.data ? note.data.split('-').reverse().join('/') : 'sem data')} · ${esc(note.categoria || '')}</small>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Nota ↗</a>` : '<span class="muted">Sem link</span>'}</li>`;
  }).join('');
  const complement = data.complemento ? `<p class="muted">À parte, fora desse total: complemento do auxílio-moradia, ${esc(money(data.complemento.valor))} em ${data.complemento.notas} ${data.complemento.notas === 1 ? 'nota' : 'notas'}.</p>` : '';
  const fileUrl = typeof profileSafeUrl === 'function' ? profileSafeUrl(data.fonte?.url) : null;
  return `<ul class="citizen-cost-note-list">${rows}</ul>
    <p><b>Total: ${esc(money(data.total))}</b>, soma das ${notes.length} ${notes.length === 1 ? 'nota' : 'notas'} acima.</p>${complement}
    <p class="muted">Para conferir na planilha da Câmara${fileUrl ? ` (<a href="${esc(fileUrl)}" target="_blank" rel="noopener">arquivo anual</a>, com todos os deputados, cerca de 40 MB)` : ''}: filtre <code>ideCadastro</code> = ${esc(String(personId).split(':')[1])} e <code>numMes</code> = ${Number(month)} e some a coluna <code>vlrLiquido</code>.</p>`;
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

function profileCostPartRow([key, label, sourceLabel], part, value, scale, detail, personId) {
  const money = profileCostMoney(value);
  const source = profileCostLatestSource(part.sources);
  const notes = key === 'quota' && source ? profileCostNotesToggle(personId, source.period, `Ver as notas de ${PROFILE_COST_MONTHS[source.period]}`) : '';
  const width = money !== null && scale > 0 && value > 0 ? Math.max(1, value / scale * 100).toFixed(1) : 0;
  return `<div class="citizen-cost-part" data-cost-part="${key}">
    <div class="citizen-cost-part-label"><span>${label}</span><b class="mono">${money === null ? 'Sem dado' : `${esc(money)}<small>/mês</small>`}</b></div>
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

function profileCostAnswer(cost) {
  const used = profileCostPeriods(cost?.usedMonths);
  const amount = profileCostMoney(cost?.monthlyAverageCents);
  const hasPrincipal = used.length > 0 && amount !== null;
  const parts = cost?.parts && typeof cost.parts === 'object' ? cost.parts : {};
  const partOf = key => (parts[key] && typeof parts[key] === 'object' ? parts[key] : {});
  let principal;
  let rows = '';
  if (hasPrincipal) {
    const values = PROFILE_COST_PARTS.map(([key]) => partOf(key).usedMonthsAverageCents);
    const scale = Math.max(0, ...values.filter(profileCostInteger));
    rows = PROFILE_COST_PARTS.map((entry, index) => profileCostPartRow(entry, partOf(entry[0]), values[index], scale, '', cost?.id)).join('');
    principal = `<div class="citizen-cost-main"><span>Custa em média</span><b class="mono">${esc(amount)}</b><span>por mês</span></div>
      <p class="citizen-cost-period">${esc(profileCostMonthList(used))} em exercício</p>`;
  } else if (profileCostAllOutside(cost)) {
    principal = '<p class="citizen-cost-unavailable">Não estava no mandato entre fevereiro de 2023 e julho de 2026.</p>';
  } else {
    const values = PROFILE_COST_PARTS.map(([key]) => partOf(key).averageCents);
    const scale = Math.max(0, ...values.filter(profileCostInteger));
    rows = PROFILE_COST_PARTS.map((entry, index) => {
      const months = profileCostPeriods(partOf(entry[0]).months);
      return profileCostPartRow(entry, partOf(entry[0]), values[index], scale, months.length ? `média de ${profileCostMonthList(months)}` : '', cost?.id);
    }).join('');
    principal = `<p class="citizen-cost-unavailable">Sem média mensal para o mandato (${PROFILE_COST_RANGE}).</p>
      <p class="citizen-cost-period">Em nenhum mês do mandato as quatro partes abaixo foram publicadas juntas. Veja cada parte com seus próprios meses.</p>`;
  }
  return `<section class="card hero citizen-answer citizen-cost-answer" data-profile-answer="expenses">
    <h2 class="h">Quanto custa?</h2>
    <span class="k">Câmara · mandato 2023–2027</span>
    ${principal}
    ${rows ? `<div class="citizen-cost-parts">${rows}</div>` : ''}
    ${profileCostChristmasLine(cost)}
    ${rows ? `<p class="citizen-cost-note">Soma salário bruto, auxílios, cota parlamentar e verba do gabinete. Fichas de senadores(as) mostram só a cota, porque salário e gabinete do Senado não estão nesta base; os dois números não são comparáveis. Valores da época, sem correção pela inflação.${profileCostGapNote(cost)} Fora da conta: encargos do gabinete e apartamento funcional. Detalhes e fontes de cada mês em “Ver mais”.</p>` : ''}
  </section>`;
}

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

function profileCostDetails(cost) {
  if (!cost || typeof cost !== 'object') return '';
  const months = cost.months && typeof cost.months === 'object' ? cost.months : {};
  const used = new Set(profileCostPeriods(cost.usedMonths));
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
      <span>${esc(status)}${used.has(period) ? ' · <span class="citizen-cost-used">entra na média</span>' : ''}${exerciseSource ? ` · <a href="${esc(exerciseSource)}" target="_blank" rel="noopener">Conferir ↗</a>` : ''}</span>
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
  return `<section class="citizen-detail-part citizen-cost-details"><h3 class="k">Custo do mandato mês a mês · ${PROFILE_COST_RANGE}</h3>
    <p class="muted">Como calculamos: em cada mês em exercício, somamos a remuneração bruta de todas as tabelas da página individual (normal, complementares), os auxílios dessa mesma página, a cota parlamentar sem o complemento de moradia e a verba do gabinete. A média usa só os meses com as quatro partes publicadas; meses parciais não são estimados para o mês inteiro. Se a Câmara não publicou uma parte para ninguém naquele mês, o mês entra com essa parte vazia e a média dela usa os outros meses. O 13º fica à parte. Diárias e vantagens indenizatórias não entram. Valores da época, sem correção pela inflação, arredondados para baixo ao centavo.</p>
    ${complement}
    ${rows ? `<div class="citizen-cost-months">${rows}</div>` : '<p class="muted">Sem detalhes mensais disponíveis.</p>'}
    ${inventory}
  </section>`;
}
