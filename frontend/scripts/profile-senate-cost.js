/* Senado: despesas identificadas do mandato, separadas do custo da Câmara.
   As partes do Senado (remuneração do senador, equipe do gabinete e cota) não têm a mesma definição
   das da Câmara: não há soma sob "custo do mandato" nem comparação com deputados(as). Cada parte vem
   da fonte com o período; uma soma só aparece em meses com as três partes, com a composição explícita. */
const SENATE_COST_PARTS = [
  ['remuneration', 'Remuneração do(a) senador(a)', 'Bruto da folha do Senado'],
  ['office', 'Equipe do gabinete', 'Comissionados do gabinete, bruto'],
  ['quota', 'Cota parlamentar', 'Despesas de reembolso'],
];
const SENATE_COST_REASONS = {
  fora_do_exercicio: 'Fora do exercício, segundo o histórico do Senado',
  nao_identificado: 'Não identificado nesta fonte',
  outra_lotacao: 'Não identificada no próprio gabinete (pode estar na Mesa ou numa liderança)',
  lotacao_compartilhada: 'Duas remunerações de senador(a) no mesmo gabinete (titular licenciado(a) e suplente); sem como separar',
  sem_lotacao_propria: 'Sem gabinete com o próprio nome no arquivo de remuneração do Senado',
  menos_de_3: 'Equipe com menos de 3 pessoas; total não divulgado para não expor remunerações individuais',
  sem_notas: 'Sem notas da cota no mês',
};
const senateCostReason = key => SENATE_COST_REASONS[key] || 'Não identificado nesta fonte';

/* Meses do recorte com as três partes, a cota vinda das notas do mandato na ficha. */
function senateCostMonths(cost, profileRecord) {
  const quota = {};
  for (const m of Array.isArray(profileRecord?.meses) ? profileRecord.meses : []) {
    if (Number.isFinite(m.valor)) quota[`${m.year}-${String(m.month).padStart(2, '0')}`] = Math.round(m.valor * 100);
  }
  return Object.entries(cost?.months || {}).sort(([a], [b]) => a.localeCompare(b)).map(([period, month]) => {
    const parts = {
      remuneration: profileCostInteger(month.remunerationCents) ? month.remunerationCents : null,
      office: profileCostInteger(month.officeCents) ? month.officeCents : null,
      quota: profileCostInteger(quota[period]) ? quota[period] : null,
    };
    const reasons = {
      remuneration: parts.remuneration === null ? month.remunerationReason : null,
      office: parts.office === null ? month.officeReason : null,
      quota: parts.quota === null ? (month.exercise === 'fora' ? 'fora_do_exercicio' : 'sem_notas') : null,
    };
    const any = Object.values(parts).some(value => value !== null);
    return { period, exercise: month.exercise, paidOutside: Boolean(month.paidOutsideExercise), officePeople: month.officePeople,
      parts, reasons, complete: Object.values(parts).every(value => value !== null), relevant: month.exercise === 'em_exercicio' || any };
  }).filter(month => month.relevant);
}

/* "fev/2023–jul/2026, set/2026": meses seguidos viram um trecho (sem o limite de período da Câmara). */
function senateCostMonthList(periods) {
  const serial = period => Number(period.slice(0, 4)) * 12 + Number(period.slice(5)) - 1;
  const runs = [];
  [...new Set(periods)].sort().forEach(period => {
    const last = runs[runs.length - 1];
    if (last && serial(period) === serial(last[1]) + 1) last[1] = period; else runs.push([period, period]);
  });
  return runs.map(([from, to]) => from === to ? profileCostLabel(from) : `${profileCostLabel(from)}–${profileCostLabel(to)}`).join(', ');
}
const senateCostAverage = values => values.length ? Math.floor(values.reduce((sum, value) => sum + value, 0) / values.length) : null;

function senateCostAnswer(cost, profileRecord) {
  const months = senateCostMonths(cost, profileRecord), complete = months.filter(month => month.complete);
  const range = cost?.periodStart && cost?.periodEnd ? `${profileCostLabel(cost.periodStart)}–${profileCostLabel(cost.periodEnd)}` : '';
  const ownOffice = Boolean(cost?.office);
  let principal, rows = '';
  const row = ([key, label, detail], value, scale, note) => {
    const money = profileCostMoney(value);
    const width = money !== null && scale > 0 && value > 0 ? Math.max(1, value / scale * 100).toFixed(1) : 0;
    return `<div class="citizen-cost-part" data-cost-part="${key}">
      <div class="citizen-cost-part-label"><span>${label}</span><b class="mono">${money === null ? 'Não identificado' : `${esc(money)}<small>/mês</small>`}</b></div>
      ${money !== null ? `<span class="citizen-cost-bar" aria-hidden="true"><i style="width:${width}%"></i></span>` : ''}
      <small>${esc(note || detail)}</small>
    </div>`;
  };
  if (complete.length) {
    /* Média só dos meses com as três partes: todas as partes sobre o mesmo conjunto de meses. */
    const averages = SENATE_COST_PARTS.map(([key]) => senateCostAverage(complete.map(month => month.parts[key])));
    const scale = Math.max(...averages);
    /* A média atravessa reajustes do subsídio: diz o valor do último mês identificado, para não parecer
       que o valor de hoje está errado. */
    const paid = months.filter(month => month.parts.remuneration !== null);
    const latest = paid[paid.length - 1];
    const changed = new Set(complete.map(month => month.parts.remuneration)).size > 1;
    /* Desde quando o valor atual é pago: volta enquanto os meses com remuneração têm o mesmo valor. */
    let since = paid.length - 1;
    while (since > 0 && paid[since - 1].parts.remuneration === latest?.parts.remuneration) since -= 1;
    const remunerationNote = latest && changed
      ? `Média do período, que inclui reajustes do subsídio. Valor atual: ${profileCostMoney(latest.parts.remuneration)}, pago desde ${profileCostLabel(paid[since].period)}`
      : '';
    rows = SENATE_COST_PARTS.map((part, index) => row(part, averages[index], scale, index === 0 ? remunerationNote : '')).join('');
    principal = `<div class="citizen-cost-main"><span>Em média</span><b class="mono">${esc(profileCostMoney(averages.reduce((a, b) => a + b, 0)))}</b><span>por mês</span></div>
      <p class="citizen-cost-period">${complete.length} ${complete.length === 1 ? 'mês' : 'meses'} com as três partes identificadas, de ${months.length} no recorte (${esc(range)}): ${esc(senateCostMonthList(complete.map(month => month.period)))}</p>`;
  } else {
    /* Sem mês completo: cada parte com os próprios meses, sem total. */
    const averages = SENATE_COST_PARTS.map(([key]) => {
      const values = months.filter(month => month.parts[key] !== null);
      return { value: senateCostAverage(values.map(month => month.parts[key])), periods: values.map(month => month.period) };
    });
    const scale = Math.max(0, ...averages.map(item => item.value || 0));
    rows = SENATE_COST_PARTS.map((part, index) => row(part, averages[index].value, scale,
      averages[index].periods.length ? `média de ${senateCostMonthList(averages[index].periods)} (${averages[index].periods.length} ${averages[index].periods.length === 1 ? 'mês' : 'meses'})` : '')).join('');
    principal = `<p class="citizen-cost-unavailable">Sem total mensal no recorte (${esc(range)}).</p>
      <p class="citizen-cost-period">${ownOffice ? 'Em nenhum mês as três partes foram identificadas juntas.' : esc(senateCostReason('sem_lotacao_propria')) + ': remuneração e equipe não identificadas.'} Cada parte aparece com os próprios meses.</p>`;
  }
  return `<section class="card hero citizen-answer citizen-cost-answer" data-profile-answer="expenses">
    <h2 class="h">Quanto custa?</h2>
    <span class="k">Senado · despesas identificadas do mandato</span>
    ${principal}
    <div class="citizen-cost-parts">${rows}</div>
    <p class="citizen-cost-note">Remuneração bruta do(a) senador(a) e da equipe comissionada do gabinete na folha do Senado, mais a cota parlamentar. Não compare com o custo de deputados(as): o Senado e a Câmara não publicam as mesmas partes. Folha suplementar (13º, férias), auxílios e servidores efetivos lotados no gabinete ficam fora. Valores da época, sem correção pela inflação. Mês a mês, com as lacunas e os motivos, em “Ver mais”.</p>
  </section>`;
}

function senateCostDetails(cost, profileRecord) {
  if (!cost || typeof cost !== 'object') return '';
  const months = senateCostMonths(cost, profileRecord);
  const sources = Object.fromEntries((cost.sources || []).map(source => [source.competence, source]));
  const exerciseUrl = cost.exerciseSource && typeof profileSafeUrl === 'function'
    ? profileSafeUrl(String(cost.exerciseSource).replace('{codigo}', String(cost.id).split(':')[1])) : null;
  const monthCard = month => {
    const source = sources[month.period] && typeof profileSafeUrl === 'function' ? profileSafeUrl(sources[month.period].url) : null;
    const status = month.exercise === 'em_exercicio' ? 'Em exercício' : month.exercise === 'fora' ? 'Fora do exercício' : 'Exercício não confirmado';
    const missing = SENATE_COST_PARTS.filter(([key]) => month.parts[key] === null);
    const known = SENATE_COST_PARTS.filter(([key]) => month.parts[key] !== null);
    const sum = known.reduce((total, [key]) => total + month.parts[key], 0);
    const total = !known.length ? '' : missing.length
      ? `<p class="citizen-cost-partial">Total parcial: <b class="mono">${esc(profileCostMoney(sum))}</b> — ${missing.map(([, label]) => label.toLowerCase()).join(' e ')} não ${missing.length === 1 ? 'identificada' : 'identificadas'}</p>`
      : `<p>Total do mês: <b class="mono">${esc(profileCostMoney(sum))}</b></p>`;
    const parts = SENATE_COST_PARTS.map(([key, label]) => {
      const value = profileCostMoney(month.parts[key]);
      const people = key === 'office' && value !== null && month.officePeople ? ` (${month.officePeople} pessoas)` : '';
      /* Lacuna: o motivo vai embaixo do nome da parte, em texto corrido, sem apertar a coluna do nome. */
      return value !== null
        ? `<li><span>${label}</span><b class="mono">${esc(value) + people}</b></li>`
        : `<li class="citizen-cost-gap"><span>${label}</span><small>${esc(senateCostReason(month.reasons[key]))}</small></li>`;
    }).join('');
    return `<div class="citizen-cost-month" data-cost-month="${month.period}">
      <b>${esc(profileCostLabel(month.period))}</b>
      <span>${esc(status)}${month.paidOutside ? ' · remuneração paga fora do exercício (licença ou afastamento)' : ''}${source ? ` · <a href="${esc(source)}" target="_blank" rel="noopener">Folha do mês ↗</a>` : ''}</span>
      <ul class="citizen-cost-month-parts">${parts}</ul>
      ${total}
    </div>`;
  };
  const years = [...new Set(months.map(month => month.period.slice(0, 4)))].reverse();
  const rows = years.map(year => `<details class="citizen-cost-year" data-cost-year="${year}"><summary>${year}</summary>${months.filter(month => month.period.startsWith(year)).reverse().map(monthCard).join('')}</details>`).join('');
  return `<section class="citizen-detail-part citizen-cost-details"><h3 class="k">Despesas identificadas mês a mês · Senado</h3>
    <p class="muted">Remuneração: a linha de senador(a) da folha normal no gabinete com o nome da pessoa, no arquivo mensal de remuneração do Senado, que não traz nome nem identificador; a ligação é pelo nome do gabinete, conferida. Equipe: soma bruta dos comissionados desse gabinete. Cota: notas de reembolso do mês. Mês em exercício segundo o histórico de exercício do Senado${exerciseUrl ? ` (<a href="${esc(exerciseUrl)}" target="_blank" rel="noopener">conferir ↗</a>)` : ''}. Sem dado não é zero: cada lacuna diz o motivo.</p>
    ${rows ? `<div class="citizen-cost-months">${rows}</div>` : '<p class="muted">Sem meses no recorte.</p>'}
  </section>`;
}
