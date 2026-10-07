/* Pure analysis rules for the spending radar. No network or DOM access. */
const SpendingAnalysis = (() => {
  const rules = Object.freeze({
    spikeRatio: 1.75,
    spikeDelta: 10000,
    minPreviousMonths: 3,
    invoiceMinimum: 10000,
    categoryShare: 0.5,
    categoryMinimum: 30000,
  });

  const monthNames = [
    'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
  ];

  const isFiniteNumber = value => typeof value === 'number' && Number.isFinite(value);
  const validNonnegative = value => isFiniteNumber(value) && value >= 0;
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function normalizeOptions(options) {
    const through = options && options.closedThrough;
    const year = options && options.year;
    return {
      closedThrough: isFiniteNumber(through) ? Math.max(0, Math.min(12, Math.trunc(through))) : 7,
      year: isFiniteNumber(year) ? Math.trunc(year) : 2026,
    };
  }

  function median(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function idPart(value) {
    return String(value == null ? '' : value);
  }

  function compareIds(left, right) {
    const a = idPart(left);
    const b = idPart(right);
    if (/^\d+$/.test(a) && /^\d+$/.test(b)) {
      const difference = Number(a) - Number(b);
      if (difference) return difference;
    }
    return a.localeCompare(b, 'en');
  }

  function analyze(deputados, options = {}) {
    const list = Array.isArray(deputados) ? deputados : [];
    const normalized = normalizeOptions(options);
    const alertsWithOrder = [];
    const rankings = [];
    let invoicesIncluded = 0;
    let invoicesReported = 0;

    for (const deputy of list) {
      const dep = deputy && typeof deputy === 'object' ? deputy : {};
      const depId = dep.id == null ? null : dep.id;
      const key = idPart(depId);
      const cota = dep.cota && typeof dep.cota === 'object' ? dep.cota : {};
      const porMes = cota.porMes && typeof cota.porMes === 'object' ? cota.porMes : {};
      const lancamentos = Array.isArray(cota.lancamentos) ? cota.lancamentos : [];
      const total = isFiniteNumber(cota.total) ? cota.total : null;
      const limit = isFiniteNumber(cota.limite) ? cota.limite : null;
      const share = total !== null && limit !== null && limit > 0 ? total / limit : null;

      rankings.push({ depId, total, limit, share });
      invoicesIncluded += lancamentos.length;
      if (validNonnegative(cota.notas)) invoicesReported += cota.notas;

      // A monthly spike is assessed only when every earlier month in the year
      // is explicitly present and valid. This prevents partial history from
      // being mistaken for a low baseline.
      for (let month = 1; month <= normalized.closedThrough; month += 1) {
        const monthKey = String(month);
        if (!own(porMes, monthKey) || !validNonnegative(porMes[monthKey])) continue;
        if (month - 1 < rules.minPreviousMonths) continue;

        const previousMonths = [];
        let completeHistory = true;
        for (let previousMonth = 1; previousMonth < month; previousMonth += 1) {
          const previousKey = String(previousMonth);
          if (!own(porMes, previousKey) || !validNonnegative(porMes[previousKey])) {
            completeHistory = false;
            break;
          }
          previousMonths.push({ month: previousMonth, amount: porMes[previousKey] });
        }
        if (!completeHistory) continue;

        const baseline = median(previousMonths.map(entry => entry.amount));
        if (!(baseline > 0)) continue;
        const amount = porMes[monthKey];
        const ratio = amount / baseline;
        if (ratio < rules.spikeRatio || amount - baseline < rules.spikeDelta) continue;

        alertsWithOrder.push({
          alert: {
            id: `pico:${key}:${month}`,
            depId,
            type: 'pico',
            title: `Pico mensal em ${monthNames[month - 1]} de ${normalized.year}`,
            amount,
            baseline,
            month,
            ratio,
            previousMonths,
            evidence: {
              year: normalized.year,
              thresholdRatio: rules.spikeRatio,
              minimumIncrease: rules.spikeDelta,
            },
          },
          month,
          index: -1,
          tie: '',
        });
      }

      // The exported dataset contains only a small sample of invoices. Large
      // invoice alerts therefore mean "worth opening the source record", not
      // a finding about a supplier, duplicate, or legality.
      for (let index = 0; index < lancamentos.length; index += 1) {
        const invoice = lancamentos[index];
        if (!invoice || typeof invoice !== 'object' || !validNonnegative(invoice.valor) || invoice.valor < rules.invoiceMinimum) continue;
        alertsWithOrder.push({
          alert: {
            id: `nota:${key}:${index}`,
            depId,
            type: 'nota',
            title: 'Nota de alto valor (R$ 10 mil ou mais)',
            amount: invoice.valor,
            ...(typeof invoice.cat === 'string' ? { category: invoice.cat } : {}),
            invoice,
            evidence: { source: 'cota.lancamentos', invoiceIndex: index },
          },
          month: 0,
          index,
          tie: '',
        });
      }

      const categories = Array.isArray(cota.categorias) ? cota.categorias : [];
      for (const category of categories) {
        if (!category || typeof category !== 'object' || typeof category.nome !== 'string') continue;
        if (category.nome === 'Sem detalhe no arquivo aberto') continue;
        if (!validNonnegative(category.valor) || category.valor < rules.categoryMinimum) continue;
        if (!(isFiniteNumber(cota.total) && cota.total > 0)) continue;
        const categoryShare = category.valor / cota.total;
        if (categoryShare < rules.categoryShare) continue;

        alertsWithOrder.push({
          alert: {
            id: `categoria:${key}:${category.nome}`,
            depId,
            type: 'categoria',
            title: 'Categoria concentra metade ou mais da cota',
            amount: category.valor,
            share: categoryShare,
            category: category.nome,
            evidence: {
              denominator: cota.total,
              minimumAmount: rules.categoryMinimum,
              minimumShare: rules.categoryShare,
            },
          },
          month: 0,
          index: -1,
          tie: category.nome,
        });
      }
    }

    alertsWithOrder.sort((left, right) => {
      const a = left.alert;
      const b = right.alert;
      return compareIds(a.depId, b.depId)
        || a.type.localeCompare(b.type, 'en')
        || left.month - right.month
        || left.index - right.index
        || left.tie.localeCompare(right.tie, 'en')
        || a.id.localeCompare(b.id, 'en');
    });

    rankings.sort((left, right) => {
      if (left.total === null && right.total !== null) return 1;
      if (left.total !== null && right.total === null) return -1;
      if (left.total !== null && right.total !== null && left.total !== right.total) return right.total - left.total;
      return compareIds(left.depId, right.depId);
    });

    return {
      alerts: alertsWithOrder.map(item => item.alert),
      rankings,
      coverage: {
        deputies: list.length,
        invoicesIncluded,
        invoicesReported,
        closedThrough: normalized.closedThrough,
      },
    };
  }

  return { analyze, rules };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = SpendingAnalysis;
