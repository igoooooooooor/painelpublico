"""Regras dos alertas da cota, num só lugar: geração dos sinais, explicação e simulação usam este cálculo.

Os alertas detectam variação de gasto e concentração em fornecedor. Não medem probabilidade de
irregularidade. Cada resultado guarda a versão da regra e os números usados (referência, piso e
meses marcados), e a cobertura registra por regra e período o que pôde ou não ser avaliado.

Prazos de apresentação das notas (meses ainda abertos não entram nos picos):
- Câmara: até 90 dias depois da despesa, lançada no mês a que se refere
  (https://www2.camara.leg.br/comunicacao/assessoria-de-imprensa/guia-para-jornalistas/cota-parlamentar).
  Um mês só é elegível quando a coleta da fonte aconteceu 90 dias ou mais depois do último dia do mês.
- Senado: comprovantes do exercício anterior até o último dia útil de abril do ano seguinte
  (APS 5/2014, art. 5º, § 3º). Um mês só é elegível com coleta posterior a 30 de abril do ano seguinte.
É um critério conservador de elegibilidade, não garantia de que a base esteja completa.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime, timedelta
from statistics import median

RULE_VERSION = 'cota-alertas-v3'
# Base publicada: mediana dos 12 meses anteriores completos, atravessando o ano (decisão de 8/10/2026).
PUBLISHED_BASELINE = 'rolling12'
# Início do mandato nas duas Casas: meses anteriores não entram nem contam como "sem notas".
MANDATE_START = (2023, 2)
# O cartão de pico mostra a janela usada, os meses marcados e até 3 meses seguintes.
SERIES_MONTHS_AFTER = 3
PEAK_MULTIPLE = 1.75
PEAK_MIN_DIFFERENCE_CENTS = 1_000_000
PEAK_MIN_PRIOR_MONTHS = 3
PEER_MIN_VALUES = 5
SUPPLIER_MIN_SHARE = 0.5
SUPPLIER_MIN_CENTS = 3_000_000
CHAMBER_DAYS = 90
# Fim do exercício: o saldo mensal não usado se acumula no ano e expira em 31/12 (Câmara: guia da cota;
# Senado: APS 5/2014, art. 5º, §§ 5º e 6º). Os alertas desses meses continuam, com esse contexto no cartão.
YEAR_END_MONTHS = (11, 12)

# Motivos de mês não avaliado na regra de pico.
NOT_EVALUATED = {
    'prazo_aberto': 'prazo de apresentação das notas ainda aberto na data da coleta',
    'historico_insuficiente': 'menos de 12 meses com notas antes deste mês (o mandato começa em fev/2023)',
    'sem_base': 'algum dos 12 meses anteriores sem notas ou com saldo negativo',
    'sem_referencia_colegas': 'sem meses fechados suficientes dos colegas para o piso',
    'sem_notas': 'sem notas publicadas no mês',
}


# Intermediação de passagens: o registro oficial cita uma companhia aérea que não é o fornecedor pago.
# Só há essa evidência no Senado (campo de detalhamento); a Câmara não publica a companhia.
AIRLINE_NAMES = {'LATAM': ('LATAM', 'TAM'), 'GOL': ('GOL',), 'AZUL': ('AZUL',)}


def is_intermediated(supplier_name, airline) -> bool:
    if not airline or airline not in AIRLINE_NAMES:
        return False
    words = set(re.findall(r'[A-Z0-9]+', unicodedata.normalize('NFKD', str(supplier_name or '')).upper()))
    return not any(name in words for name in AIRLINE_NAMES[airline])


def house_of(source_id: str) -> str:
    return 'senado' if str(source_id).startswith('senado') else 'camara'


def _fetch_date(fetched_at) -> date | None:
    if not fetched_at:
        return None
    try:
        return datetime.fromisoformat(str(fetched_at).replace('Z', '+00:00')).date()
    except ValueError:
        return None


def closes_on(source_id: str, year: int, month: int) -> date:
    """Primeiro dia em que uma coleta pode tratar o mês como elegível."""
    if house_of(source_id) == 'senado':
        return date(year + 1, 5, 1)
    return date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=CHAMBER_DAYS)


def month_closed(source_id: str, year: int, month: int, fetched_at) -> bool:
    fetched = _fetch_date(fetched_at)
    return fetched is not None and fetched >= closes_on(source_id, year, month)


def first_month(year: int) -> int:
    """Primeiro mês do ano dentro do mandato (fev em 2023, jan nos demais)."""
    return MANDATE_START[1] if year == MANDATE_START[0] else 1


def _peak_runs(series, closed, floor, first=1):
    """Base anual: avalia cada mês e devolve (meses avaliados, motivos de não avaliação, meses marcados com base)."""
    evaluated, skipped, flagged = [], {}, {}
    last = max(series) if series else 0
    for month in range(first, last + 1):
        value = series.get(month)
        if value is None:
            reason = 'sem_notas'
        elif not closed(month):
            reason = 'prazo_aberto'
        elif month - first < PEAK_MIN_PRIOR_MONTHS:
            reason = 'historico_insuficiente'
        else:
            before = [series.get(m) for m in range(first, month)]
            if any(v is None or v < 0 for v in before) or median(before) <= 0:
                reason = 'sem_base'
            elif floor is None:
                reason = 'sem_referencia_colegas'
            else:
                reason = None
                base = median(before)
                evaluated.append(month)
                if value >= base * PEAK_MULTIPLE and value - base >= PEAK_MIN_DIFFERENCE_CENTS and value >= floor:
                    flagged[month] = base
        if reason:
            skipped.setdefault(reason, []).append(month)
    return evaluated, skipped, flagged


# rolling12: 12 meses anteriores completos (base publicada). year: meses anteriores do mesmo ano (regra até a v2)
# e rolling-short: de 3 a 12 meses, conforme o histórico disponível; as duas só para comparação na simulação.
BASELINES = ('year', 'rolling12', 'rolling-short')
ROLLING_MONTHS = 12


def _rolling_series(series):
    """Junta os anos de cada pessoa e Casa numa série contínua, para a variante de 12 meses."""
    joined = {}
    for (authority, source, year), months in series.items():
        for month, value in months.items():
            joined.setdefault((authority, house_of(source)), {})[year * 12 + month - 1] = (source, value)
    return joined


def _rolling_peaks(series, floors, fetched_at_by_source, min_prior=ROLLING_MONTHS):
    """Referência = mediana dos 12 meses anteriores, atravessando o ano.

    Com min_prior=12 (base publicada), exige os 12 meses anteriores completos (todos com notas); com o
    histórico começando em fev/2023, isso só ocorre a partir de fev/2024, e antes disso o mês fica como
    histórico insuficiente. Com min_prior=3 (base curta, só na simulação), aceita de 3 a 12 meses
    conforme o histórico disponível. Em ambos, meses sem notas na janela impedem. O piso continua sendo
    o dos colegas no ano do mês avaliado.
    """
    out = {}
    for (authority, house), points in _rolling_series(series).items():
        first = min(points)
        for serial, (source, value) in sorted(points.items()):
            year, month = divmod(serial, 12)
            month += 1
            key = (authority, source, year)
            window = range(max(first, serial - 12), serial)
            before = [points.get(s, (None, None))[1] for s in window]
            if not month_closed(source, year, month, fetched_at_by_source.get(source)):
                reason = 'prazo_aberto'
            elif len(before) < min_prior:
                reason = 'historico_insuficiente'
            elif any(v is None or v < 0 for v in before) or median(before) <= 0:
                reason = 'sem_base'
            elif floors.get((source, year)) is None:
                reason = 'sem_referencia_colegas'
            else:
                reason = None
                base, floor = median(before), floors[(source, year)]
                entry = out.setdefault(key, ([], {}, {}))
                entry[0].append(month)
                if value >= base * PEAK_MULTIPLE and value - base >= PEAK_MIN_DIFFERENCE_CENTS and value >= floor:
                    entry[2][month] = base
            if reason:
                out.setdefault(key, ([], {}, {}))[1].setdefault(reason, []).append(month)
    for (authority, source, year), months in series.items():
        skipped = out.setdefault((authority, source, year), ([], {}, {}))[1]
        for month in range(first_month(year), max(months) + 1):
            if month not in months:
                skipped.setdefault('sem_notas', []).append(month)
    return out


def evaluate(records, fetched_at_by_source, baseline=PUBLISHED_BASELINE):
    """Calcula sinais, cobertura e valor sem duplicidade a partir das notas de reembolso.

    records: dicts com id, authorityId, sourceId, year, month, supplierKey, supplierName, amountCents.
    baseline: 'rolling12' (publicada, PUBLISHED_BASELINE), 'year' ou 'rolling-short' (só na simulação).
    Devolve {'signals', 'coverage', 'totals'}; nenhum valor ausente vira zero.
    """
    if baseline not in BASELINES:
        raise ValueError(f'Base desconhecida: {baseline}')
    series, by_supplier, totals, record_ids = {}, {}, {}, {}
    for r in records:
        key = (r['authorityId'], r['sourceId'], int(r['year']))
        month = int(r['month'])
        series.setdefault(key, {})[month] = series.get(key, {}).get(month, 0) + r['amountCents']
        totals[key] = totals.get(key, 0) + r['amountCents']
        record_ids.setdefault((*key, month), []).append((r['id'], r['amountCents']))
        if r.get('supplierKey'):
            entry = by_supplier.setdefault(key, {}).setdefault(r['supplierKey'], {'name': r.get('supplierName'), 'cents': 0, 'records': [],
                                                                                 'intermediated': 0, 'airlines': set()})
            entry['cents'] += r['amountCents']
            entry['records'].append((r['id'], r['amountCents']))
            if is_intermediated(r.get('supplierName'), r.get('airline')):
                entry['intermediated'] += 1
                entry['airlines'].add(r['airline'])

    def closed_for(source, year):
        return lambda month: month_closed(source, year, month, fetched_at_by_source.get(source))

    # Piso dos colegas: mediana dos meses fechados e positivos da mesma fonte e ano.
    peer_values = {}
    for (authority, source, year), months in series.items():
        closed = closed_for(source, year)
        for month, value in months.items():
            if value > 0 and closed(month):
                peer_values.setdefault((source, year), []).append(value)
    floors = {k: median(v) for k, v in peer_values.items() if len(v) >= PEER_MIN_VALUES}

    min_prior = {'year': PEAK_MIN_PRIOR_MONTHS, 'rolling12': ROLLING_MONTHS, 'rolling-short': PEAK_MIN_PRIOR_MONTHS}[baseline]
    rolling = None if baseline == 'year' else _rolling_peaks(series, floors, fetched_at_by_source, min_prior)
    peaks = {}
    for (authority, source, year), months in series.items():
        if rolling is None:
            peaks[(authority, source, year)] = _peak_runs(months, closed_for(source, year), floors.get((source, year)), first_month(year))
        else:
            evaluated, skipped, flagged = rolling.get((authority, source, year), ([], {}, {}))
            peaks[(authority, source, year)] = (evaluated, {k: sorted(v) for k, v in skipped.items()}, flagged)

    # Situação de cada mês (marcado, avaliado sem alerta ou o motivo de não avaliação) e valores por pessoa e
    # Casa numa linha do tempo contínua, para o cartão mostrar a janela usada, atravessando o ano.
    status, timeline = {}, {}
    for (authority, source, year), (evaluated, skipped, flagged) in peaks.items():
        house = house_of(source)
        for m in evaluated:
            status[(authority, house, year, m)] = 'flagged' if m in flagged else 'evaluated'
        for reason, skipped_months in skipped.items():
            for m in skipped_months:
                status.setdefault((authority, house, year, m), reason)
        for m, value in series[(authority, source, year)].items():
            timeline.setdefault((authority, house), {})[year * 12 + m - 1] = value

    def card_series(authority, source, year, run):
        """Série gravada no cartão. Base anual: o ano todo. Bases móveis: a janela de referência do primeiro
        mês marcado, os meses marcados e até SERIES_MONTHS_AFTER meses seguintes com notas observadas."""
        house = house_of(source)
        points = timeline[(authority, house)]
        if rolling is None:
            serials = range(year * 12 + first_month(year) - 1, year * 12 + max(series[(authority, source, year)]))
        else:
            start = max(min(points), year * 12 + run[0] - 1 - ROLLING_MONTHS)
            end = min(max(points), year * 12 + run[-1] - 1 + SERIES_MONTHS_AFTER)
            serials = range(start, end + 1)
        out = []
        for serial in serials:
            y, m = divmod(serial, 12)
            out.append({'year': y, 'month': m + 1, 'valueCents': points.get(serial),
                        'status': status.get((authority, house, y, m + 1), 'sem_notas')})
        return out

    signals, coverage, alert_records = [], [], {}
    for (authority, source, year), months in sorted(series.items()):
        fetched = fetched_at_by_source.get(source)
        floor = floors.get((source, year))
        evaluated, skipped, flagged = peaks[(authority, source, year)]
        coverage.append({'authorityId': authority, 'sourceId': source, 'year': year, 'rule': 'pico', 'detail': {
            'ruleVersion': RULE_VERSION, 'baseline': baseline, 'fetchedAt': fetched, 'evaluated': sorted(evaluated), 'flagged': sorted(flagged),
            'notEvaluated': skipped, 'floorCents': floor}})
        # Meses seguidos marcados viram um alerta só, com todos os meses efetivamente marcados. Cada alerta
        # fica dentro de um ano, como a cota, cujo saldo expira em 31/12.
        for month in sorted(flagged):
            if month - 1 in flagged:
                continue
            run = [month]
            while run[-1] + 1 in flagged:
                run.append(run[-1] + 1)
            marked = [{'month': m, 'valueCents': months[m], 'referenceCents': flagged[m],
                       'multiple': round(months[m] / flagged[m], 2)} for m in run]
            signal_id = f'pico:{authority}:{source}:{year}:{month}'
            signals.append({
                'id': signal_id, 'authorityId': authority, 'sourceId': source, 'type': 'pico',
                'title': 'Mês acima da referência', 'amountCents': sum(m['valueCents'] for m in marked),
                'period': f'{year}-{month:02d}', 'detail': {
                    'ruleVersion': RULE_VERSION, 'baseline': baseline, 'year': year, 'months': marked, 'floorCents': floor,
                    # Mês sem notas fica sem valor, nunca zero.
                    'series': card_series(authority, source, year, run),
                    'fetchedAt': fetched, 'partial': False,
                    'yearEndMonths': [m for m in run if m in YEAR_END_MONTHS],
                    'criteria': {'multiple': PEAK_MULTIPLE, 'minDifferenceCents': PEAK_MIN_DIFFERENCE_CENTS,
                                 'minPriorMonths': min_prior}}})
            alert_records[signal_id] = [rec for m in run for rec in record_ids[(authority, source, year, m)]]

        total = totals[(authority, source, year)]
        partial = not month_closed(source, year, 12, fetched)
        observed = sorted(months)
        coverage.append({'authorityId': authority, 'sourceId': source, 'year': year, 'rule': 'fornecedor', 'detail': {
            'ruleVersion': RULE_VERSION, 'fetchedAt': fetched, 'evaluated': total > 0, 'partial': partial,
            'monthsObserved': [observed[0], observed[-1]], 'reason': None if total > 0 else 'sem_total_positivo'}})
        if total <= 0:
            continue
        for supplier_key, entry in sorted(by_supplier.get((authority, source, year), {}).items()):
            share = entry['cents'] / total
            if entry['cents'] < SUPPLIER_MIN_CENTS or share < SUPPLIER_MIN_SHARE:
                continue
            signal_id = f'fornecedor:{authority}:{source}:{year}:{supplier_key}'
            signals.append({
                'id': signal_id, 'authorityId': authority, 'sourceId': source, 'type': 'fornecedor',
                'title': 'Concentração em fornecedor', 'amountCents': entry['cents'], 'period': str(year), 'detail': {
                    'ruleVersion': RULE_VERSION, 'year': year, 'supplierKey': supplier_key, 'supplierName': entry['name'],
                    'supplierCents': entry['cents'], 'totalCents': total, 'share': round(share, 4),
                    'records': len(entry['records']), 'monthsObserved': [observed[0], observed[-1]],
                    'partial': partial, 'fetchedAt': fetched,
                    # Maioria das notas cita outra companhia aérea: pagamentos intermediados por agência.
                    'intermediation': ({'records': entry['intermediated'], 'airlines': sorted(entry['airlines'])}
                                       if entry['intermediated'] * 2 > len(entry['records']) else None),
                    'monthsWithNotes': len(months),
                    'criteria': {'minShare': SUPPLIER_MIN_SHARE, 'minCents': SUPPLIER_MIN_CENTS}}})
            alert_records[signal_id] = entry['records']

    # Valor das despesas nos alertas: cada lançamento uma vez só, com estornos (valores negativos) mantidos.
    person_totals = {}
    for signal in signals:
        bucket = person_totals.setdefault(signal['authorityId'], {'records': {}, 'partial': False})
        bucket['records'].update(dict(alert_records[signal['id']]))
        bucket['partial'] = bucket['partial'] or signal['detail']['partial']
    totals_out = {authority: {'amountCents': sum(b['records'].values()), 'records': len(b['records']),
                              'partial': b['partial']} for authority, b in person_totals.items()}
    return {'signals': signals, 'coverage': coverage, 'totals': totals_out}


BASELINE_TEXT = {
    'year': 'mediana dos meses anteriores do mesmo ano, com ao menos 3 meses e sem lacunas',
    'rolling12': 'mediana dos 12 meses anteriores, todos com notas, atravessando o ano',
    'rolling-short': 'mediana de 3 a 12 meses anteriores, conforme o histórico, sem lacunas',
}


def describe(signal) -> str:
    """Critério em texto técnico, a partir do que foi gravado (sem recalcular)."""
    detail = signal['detail']

    def money(cents):
        return ('R$ ' + f'{cents / 100:,.2f}').replace(',', 'X').replace('.', ',').replace('X', '.')
    if signal['type'] == 'pico':
        months = '; '.join(f'mês {m["month"]}: {money(m["valueCents"])}, {m["multiple"]:.2f} vez(es) a referência de '
                           f'{money(m["referenceCents"])}' for m in detail['months'])
        reference = BASELINE_TEXT.get(detail.get('baseline', 'year'))
        return (f'{months}. Referência: {reference}. '
                f'Critério: 1,75 vez a referência, diferença de R$ 10.000 e acima do piso dos colegas '
                f'({money(detail["floorCents"])}). Só meses com prazo de apresentação encerrado na coleta.'
                f'{" Fim do exercício: o saldo não usado da cota se acumula no ano e expira em 31/12." if detail.get("yearEndMonths") else ""}'
                f' Regra {detail["ruleVersion"]}.')
    intermediation = detail.get('intermediation')
    middle = (f' Intermediação: {intermediation["records"]} de {detail["records"]} notas citam outra companhia aérea '
              f'({", ".join(intermediation["airlines"])}); o valor é o total pago pelas passagens, não a receita da agência.'
              if intermediation else '')
    return (f'{detail["supplierName"]}: {money(detail["supplierCents"])} de {money(detail["totalCents"])} '
            f'({detail["share"] * 100:.1f}%). Critério: pelo menos 50% e R$ 30.000 no ano.{middle}'
            f'{" Período parcial: o ano ainda pode receber notas." if detail["partial"] else ""} Regra {detail["ruleVersion"]}.')
