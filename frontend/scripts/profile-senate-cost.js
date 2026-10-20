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
  bruto_nao_positivo: 'Bruto da folha zero ou negativo (acerto ou abate-teto maior que o pagamento); não identificado',
};
/* Portal de transparência do(a) senador(a) no ano do mês: cota por tipo (com o detalhe mensal), subsídio e pessoal.
   `/ceaps/?ano=` responde 404 para todos (conferido em 19/10/2026); a página do ano é `/sen/<código>/?ano=`. */
const senatePortalUrl = (identifier, period, path = '') => {
  const code = /^senado:(\d+)$/.exec(String(identifier || ''))?.[1];
  const year = /^(\d{4})-\d{2}$/.exec(String(period || ''))?.[1];
  return code && year ? `https://www6g.senado.leg.br/transparencia/sen/${code}/${path}?ano=${year}` : null;
};
const senateQuotaPortalUrl = (identifier, period) => senatePortalUrl(identifier, period);
/* A folha que dá o valor é uma planilha de todo o Senado (CSV); no cartão, o link vai para uma página com contexto:
   a página do ano (subsídio do(a) senador(a)) ou a lista de pessoal do gabinete. */
const senateStaffPortalUrl = (identifier, period) => {
  const url = senatePortalUrl(identifier, period, 'pessoal/');
  return url ? `${url}&local=gabinete&vinculo=COMISSIONADO` : null;
};
const senatePartSource = (key, identifier, period) => {
  const year = String(period || '').slice(0, 4);
  if (key === 'quota') return [senateQuotaPortalUrl(identifier, period), `Cota de ${year} no portal do Senado`];
  if (key === 'office') return [senateStaffPortalUrl(identifier, period), `Equipe do gabinete em ${year} no portal do Senado`];
  return [senatePortalUrl(identifier, period), `Subsídio no portal do Senado (${year})`];
};
const senateCostReason = key => SENATE_COST_REASONS[key] || 'Não identificado nesta fonte';

/* Meses do recorte com as três partes, a cota vinda das notas do mandato na ficha. */
function senateCostMonths(cost, profileRecord) {
  const quota = {};
  for (const m of Array.isArray(profileRecord?.meses) ? profileRecord.meses : []) {
    if (Number.isFinite(m.valor)) quota[`${m.year}-${String(m.month).padStart(2, '0')}`] = Math.round(m.valor * 100);
  }
  return Object.entries(cost?.months || {}).sort(([a], [b]) => a.localeCompare(b)).map(([period, month]) => {
    // Bruto zero ou negativo (acerto ou abate-teto) não é a remuneração do mês: fica como não identificado.
    const parts = {
      remuneration: profileCostInteger(month.remunerationCents) && month.remunerationCents > 0 ? month.remunerationCents : null,
      office: profileCostInteger(month.officeCents) ? month.officeCents : null,
      quota: profileCostInteger(quota[period]) ? quota[period] : null,
    };
    const reasons = {
      remuneration: parts.remuneration === null ? (profileCostInteger(month.remunerationCents) ? 'bruto_nao_positivo' : month.remunerationReason) : null,
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
/* O mês mais recente com as três partes e as notas da cota assentadas (mesma regra da Câmara, `profileCostPickMonth`). */
function senateCostLatest(months, asOf) {
  const complete = months.filter(month => month.complete);
  const pick = profileCostPickMonth(complete.map(month => month.period), asOf);
  const month = pick && complete.find(item => item.period === pick.period);
  if (!month) return null;
  return { ...pick, month, cents: SENATE_COST_PARTS.reduce((sum, [key]) => sum + month.parts[key], 0) };
}
/* Meses da média: os com as três partes e as notas da cota assentadas (mesma regra da Câmara). */
function senateCostAverageMonths(months, asOf) {
  const complete = months.filter(month => month.complete);
  const periods = new Set(profileCostSettledPeriods(complete.map(month => month.period), asOf));
  return complete.filter(month => periods.has(month.period));
}
/* O que falta na base no mês seguinte; o fim do recorte não prova que a fonte ainda não publicou a folha. */
function senateCostNextGap(cost, months, period) {
  const next = profileCostNextPeriod(period), label = profileCostLabel(next);
  const month = months.find(item => item.period === next);
  if (!month) {
    if (cost?.periodEnd && next > cost.periodEnd) return `A base do painel ainda não inclui a folha de ${label}.`;
    return cost?.months?.[next]?.exercise === 'fora' ? `Em ${label}, estava fora do exercício.` : '';
  }
  const missing = SENATE_COST_PARTS.filter(([key]) => month.parts[key] === null).map(([, partLabel]) => profileCostLowerFirst(partLabel));
  return missing.length ? `Em ${label}, ${missing.length === 1 ? 'falta' : 'faltam'} ${profileCostJoin(missing)}.` : '';
}
const senateCostAverage = values => values.length ? Math.floor(values.reduce((sum, value) => sum + value, 0) / values.length) : null;

function senateCostAnswer(cost, profileRecord) {
  const months = senateCostMonths(cost, profileRecord), complete = senateCostAverageMonths(months, profileRecord?.snapshotAt);
  const range = cost?.periodStart && cost?.periodEnd ? `${profileCostLabel(cost.periodStart)}–${profileCostLabel(cost.periodEnd)}` : '';
  const ownOffice = Boolean(cost?.office);
  const sourceRows = (Array.isArray(cost?.sources) ? cost.sources : []).filter(source => profileSafeUrl(source?.url))
    .sort((first, second) => String(first.competence).localeCompare(String(second.competence)));
  const latestPayroll = sourceRows.at(-1);
  let principal, rows = '';
  const row = ([key, label, detail], value, scale, note, sourceUrl = null, sourceLabel = '', perMonth = true) => {
    const money = profileCostMoney(value);
    const width = money !== null && scale > 0 && value > 0 ? Math.max(1, value / scale * 100).toFixed(1) : 0;
    return `<div class="citizen-cost-part" data-cost-part="${key}">
      <div class="citizen-cost-part-label"><span>${label}</span><b class="mono">${money === null ? 'Não identificado' : `${esc(money)}${perMonth ? '<small>/mês</small>' : ''}`}</b></div>
      ${money !== null ? `<span class="citizen-cost-bar" aria-hidden="true"><i style="width:${width}%"></i></span>` : ''}
      <small>${esc(note || detail)}${sourceUrl ? ` · <a href="${esc(sourceUrl)}" target="_blank" rel="noopener">${esc(sourceLabel)} ↗</a>` : ''}</small>
    </div>`;
  };
  const latest = senateCostLatest(months, profileRecord?.snapshotAt);
  if (latest) {
    /* Número principal: o mês mais recente com as três partes e a cota madura; as linhas são daquele mês e
       somam o total. A média dos meses com as três partes fica como contexto. */
    const averages = SENATE_COST_PARTS.map(([key]) => senateCostAverage(complete.map(month => month.parts[key])));
    const average = averages.reduce((a, b) => a + b, 0);
    const values = SENATE_COST_PARTS.map(([key]) => latest.month.parts[key]);
    const scale = Math.max(...values);
    const payroll = sourceRows.find(source => source.competence === latest.period);
    rows = SENATE_COST_PARTS.map((part, index) => row(part, values[index], scale, '',
      ...senatePartSource(part[0], cost?.id, latest.period), false)).join('');
    principal = `<div class="profile-cost-total"><span>Somou</span><b class="mono">${esc(profileCostShort(latest.cents))}</b><span>em ${esc(profileCostLabel(latest.period))}</span></div>
      <p class="citizen-cost-exact">Valor exato: <span class="mono">${esc(profileCostMoney(latest.cents))}</span>, a soma das três partes abaixo</p>
      ${profileCostStackedComposition(values, latest.cents, SENATE_COST_PARTS.map(([, label]) => label))}
      ${profileCostWhyMonth(latest, latest.settled && !latest.later.length ? senateCostNextGap(cost, months, latest.period) : '')}
      <p class="citizen-cost-period">Média: <span class="mono">${esc(profileCostMoney(average))}</span> por mês, ${complete.length} ${complete.length === 1 ? 'mês' : 'meses'} com as três partes identificadas${latest.settled ? ' e as notas da cota já assentadas' : ''}, dos ${months.length} ${months.length === 1 ? 'mês' : 'meses'} em exercício ou com dado no recorte (${esc(range)}): ${esc(senateCostMonthList(complete.map(month => month.period)))}</p>`;
  } else {
    /* Sem mês completo: cada parte com os próprios meses, sem total. */
    const averages = SENATE_COST_PARTS.map(([key]) => {
      const values = months.filter(month => month.parts[key] !== null);
      return { value: senateCostAverage(values.map(month => month.parts[key])), periods: values.map(month => month.period) };
    });
    const scale = Math.max(0, ...averages.map(item => item.value || 0));
    const lastQuotaPeriod = averages[SENATE_COST_PARTS.findIndex(([key]) => key === 'quota')].periods.at(-1) || cost?.periodEnd;
    rows = SENATE_COST_PARTS.map((part, index) => row(part, averages[index].value, scale,
      averages[index].periods.length ? `média de ${senateCostMonthList(averages[index].periods)} (${averages[index].periods.length} ${averages[index].periods.length === 1 ? 'mês' : 'meses'})` : '',
      ...senatePartSource(part[0], cost?.id, part[0] === 'quota' ? lastQuotaPeriod : latestPayroll?.competence || cost?.periodEnd))).join('');
    principal = `<p class="citizen-cost-unavailable">Sem total mensal no recorte (${esc(range)}).</p>
      <p class="citizen-cost-period">${ownOffice ? 'Em nenhum mês as três partes foram identificadas juntas.' : esc(senateCostReason('sem_lotacao_propria')) + ': remuneração e equipe não identificadas.'} Cada parte aparece com os próprios meses.</p>`;
  }
  return `<article class="card profile-cost-breakdown" data-profile-cost-house="senado">
    <span class="k">${latest ? 'Mês mais recente · ' : ''}Despesas identificadas · Senado</span>
    ${principal}
    <div class="citizen-cost-parts">${rows}</div>
    <div class="profile-card-links"><button type="button" class="more" data-profile-open="expenses">Como calculamos e ver mês a mês →</button><button type="button" class="more" data-profile-open="sources">Fontes e datas →</button></div>
  </article>`;
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
      <span>${esc(status)}${month.paidOutside ? ' · remuneração paga fora do exercício (licença ou afastamento)' : ''}${source ? ` · <a href="${esc(source)}" target="_blank" rel="noopener" title="Planilha de remuneração de todo o Senado no mês">Planilha da folha (CSV) ↓</a>` : ''}</span>
      <ul class="citizen-cost-month-parts">${parts}</ul>
      ${total}
    </div>`;
  };
  const years = [...new Set(months.map(month => month.period.slice(0, 4)))].reverse();
  const rows = years.map(year => `<details class="citizen-cost-year" data-cost-year="${year}"><summary>${year}</summary>${months.filter(month => month.period.startsWith(year)).reverse().map(monthCard).join('')}</details>`).join('');
  return `<section class="citizen-detail-part citizen-cost-details"><h3 class="k">Despesas identificadas mês a mês · Senado</h3>
    <p class="muted">Remuneração bruta do(a) senador(a) e da equipe comissionada do gabinete na folha do Senado, mais a cota parlamentar. Não compare com o custo de deputados(as): o Senado e a Câmara não publicam as mesmas partes. Folha suplementar (13º, férias), auxílios e servidores efetivos lotados no gabinete ficam fora. Valores da época, sem correção pela inflação.</p>
    <p class="muted">Remuneração: a linha de senador(a) da folha normal no gabinete com o nome da pessoa, no arquivo mensal de remuneração do Senado, que não traz nome nem identificador; a ligação é pelo nome do gabinete, conferida. Equipe: soma bruta dos comissionados desse gabinete. Cota: notas de reembolso do mês. Mês em exercício segundo o histórico de exercício do Senado${exerciseUrl ? ` (<a href="${esc(exerciseUrl)}" target="_blank" rel="noopener">conferir ↗</a>)` : ''}. Sem dado não é zero: cada lacuna diz o motivo.</p>
    ${SENATE_COST_MONTH_RULE}
    ${rows ? `<div class="citizen-cost-months">${rows}</div>` : '<p class="muted">Sem meses no recorte.</p>'}
  </section>`;
}

/* "Qual mês aparece", na versão do Senado: a mesma folga da Câmara, com o aviso de que no Senado as notas da
   cota podem entrar até abril do ano seguinte (o prazo que os alertas usam). */
const SENATE_COST_MONTH_RULE = `<p class="muted"><b>Qual mês aparece no “Quanto custa?”:</b> o mais recente com as três partes identificadas e com ${PROFILE_COST_SETTLE_MONTHS} meses de folga até a data das notas importadas, a mesma regra da Câmara. No Senado, as notas da cota podem ser apresentadas até o fim de abril do ano seguinte, então mesmo um mês com a folga ainda pode receber notas; por isso os alertas da cota do Senado esperam esse prazo maior. O mês muda a cada atualização dos dados.</p>`;

/* Seção "Equipe e verba de gabinete" do Senado: o mês mais recente com equipe identificada e a média dos
   meses em exercício com equipe e com as notas da cota assentadas (o mesmo corte do cartão de custo), a partir
   da mesma folha. No Senado não há verba de gabinete publicada como na Câmara. */
function senateOfficeHTML(cost, asOf = null) {
  const entries = Object.entries(cost?.months || {}).sort(([a], [b]) => a.localeCompare(b));
  const known = entries.filter(([, month]) => profileCostInteger(month.officeCents));
  if (!known.length) {
    const last = entries[entries.length - 1]?.[1];
    return `<p class="muted">Equipe do gabinete não identificada na folha do Senado: ${esc(senateCostReason(last?.officeReason || 'sem_lotacao_propria').toLowerCase())}. Ausência de dado não significa gasto zero.</p>`;
  }
  const [latestPeriod, latest] = known[known.length - 1];
  const settled = new Set(profileCostSettledPeriods(known.map(([period]) => period), asOf));
  const averaged = known.filter(([period, month]) => settled.has(period) && month.exercise !== 'fora');
  const basis = averaged.length ? averaged : known;
  const average = senateCostAverage(basis.map(([, month]) => month.officeCents));
  const source = (cost.sources || []).find(item => item.competence === latestPeriod);
  const url = source && typeof profileSafeUrl === 'function' ? profileSafeUrl(source.url) : null;
  const periods = basis.map(([period]) => period);
  const left = known.length - basis.length;
  return `<div><span class="big">${esc(profileCostMoney(latest.officeCents))}</span><span class="muted"> · equipe do gabinete em ${esc(profileCostLabel(latestPeriod))}</span></div>
    ${latest.officePeople ? `<p>${esc(latest.officePeople)} pessoas comissionadas nesse mês.</p>` : ''}
    <p>Média de <b class="mono">${esc(profileCostMoney(average))}</b> por mês em ${basis.length} ${basis.length === 1 ? 'mês' : 'meses'} com equipe identificada${averaged.length ? ' e as notas da cota já assentadas, o mesmo corte do cartão de custo' : ''} (${esc(senateCostMonthList(periods))}).${left ? ` ${left === 1 ? 'Fica fora da média 1 mês' : `Ficam fora da média ${left} meses`}: os mais recentes, com notas ainda chegando, ou fora do exercício.` : ''}</p>
    <p class="muted">Soma bruta da folha normal dos comissionados lotados no gabinete com o nome da pessoa, no arquivo mensal de remuneração do Senado. 13º, férias, auxílios e servidores efetivos ficam fora. O Senado não publica uma verba de gabinete como a da Câmara; não compare os dois valores. Os nomes da equipe não são guardados.</p>
    <span class="src">${senateStaffPortalUrl(cost.id, latestPeriod) ? `<a href="${esc(senateStaffPortalUrl(cost.id, latestPeriod))}" target="_blank" rel="noopener">Equipe do gabinete no portal do Senado ↗</a>` : ''}${url ? `${senateStaffPortalUrl(cost.id, latestPeriod) ? ' · ' : ''}<a href="${esc(url)}" target="_blank" rel="noopener">Planilha da folha de ${esc(profileCostLabel(latestPeriod))} (CSV, todo o Senado) ↓</a>` : ''}</span>`;
}

/* Números do Senado para o comparativo, com as mesmas regras do cartão: total só dos meses com as três partes e
   as notas da cota assentadas;
   remuneração e equipe pela média dos meses em que cada uma foi identificada. */
function senateCostFigures(cost, profileRecord) {
  const months = senateCostMonths(cost, profileRecord), complete = senateCostAverageMonths(months, profileRecord?.snapshotAt);
  const partAverage = key => {
    const values = months.filter(month => month.parts[key] !== null).map(month => month.parts[key]);
    return values.length ? { cents: senateCostAverage(values), months: values.length } : null;
  };
  const total = complete.length
    ? { cents: SENATE_COST_PARTS.reduce((sum, [key]) => sum + senateCostAverage(complete.map(month => month.parts[key])), 0), months: complete.length }
    : null;
  const latestOffice = [...months].reverse().find(month => month.parts.office !== null);
  // Partes do total sobre os mesmos meses completos (a imagem de compartilhar mostra a composição).
  const parts = complete.length ? SENATE_COST_PARTS.map(([key]) => ({ key, cents: senateCostAverage(complete.map(month => month.parts[key])) })) : [];
  // A ficha e a imagem mostram o mês mais recente; o comparativo segue com a média.
  const latest = senateCostLatest(months, profileRecord?.snapshotAt);
  return { total, parts, latest, remuneration: partAverage('remuneration'), office: partAverage('office'), officePeople: latestOffice?.officePeople || null };
}
