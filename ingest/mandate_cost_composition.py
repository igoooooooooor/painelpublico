"""Compose a Câmara monthly average over the current mandate from local source snapshots.

No network, database writes, ranking or cross-House comparison. Housing amounts
are reconciliation evidence only; allowances enter through individual payroll.
The individual official payroll page is the person's record; the anonymous
sheet inventory is kept only as a footnote and never blocks a month.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import math
import json
from pathlib import Path

from ingest.mandate_cost_audit import (COMPLEMENT_CATEGORY, build as build_audit, cents,
                                      observed_payroll_components)

ROOT = Path(__file__).resolve().parents[1]
# Mandato atual (legislatura 57) até o último mês com as quatro partes publicadas em 2026.
MANDATE_START = '2023-02'
CURRENT_YEAR = 2026
CURRENT_LAST_MONTH = 7
HISTORY_YEARS = (2023, 2024, 2025)
PERIODS = tuple(
    f'{year}-{month:02d}'
    for year in (*HISTORY_YEARS, CURRENT_YEAR)
    for month in range(1, (CURRENT_LAST_MONTH if year == CURRENT_YEAR else 12) + 1)
    if f'{year}-{month:02d}' >= MANDATE_START
)
# Lacunas confirmadas na própria fonte para todos os deputados: o mês entra na média
# com as partes publicadas e a parte ausente fica vazia, sem virar zero.
SOURCE_GAPS = {'2024-12': ('office',)}
# 13º salário fica fora da média mensal e aparece à parte.
CHRISTMAS_COMPONENT = 'christmas_bonus'
GROSS_COMPONENTS = ('fixed_remuneration', 'personal_advantages', 'commission_role',
                    'vacation_third', 'other_eventual_remuneration',
                    'permanence_bonus', 'constitutional_reduction')
PARTS = ('remuneration', 'allowances', 'quota', 'office')


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def valid(row, period):
    return row.get('period') == period and not row.get('stale')


def source(row):
    # Só link e mês por parte: com 42 meses, o resto da procedência fica nos snapshots de origem.
    original = row.get('source', row)
    return {'url': original.get('url', original.get('sourceUrl')), 'period': row.get('period')}


def compose_month(parts, service, period):
    payroll, housing, quota, office = (parts.get(key, {}).get(period, {})
                                      for key in ('payroll', 'housing', 'quota', 'office'))
    service_status = service.get('status') if service.get('period') == period and not service.get('stale') else 'unknown'
    outside = service_status == 'outside_mandate'
    # Todas as tabelas publicadas na página individual (normal, complementares, 13º) contam.
    payroll_read = valid(payroll, period) and payroll.get('detailStatus') == 'complete'
    components = observed_payroll_components(payroll) if payroll_read else {}
    gross = [components.get(key) for key in GROSS_COMPONENTS]
    remuneration = sum(gross) if components and all(integer(value) for value in gross) else None
    christmas = components.get(CHRISTMAS_COMPONENT)
    christmas = christmas if integer(christmas) and christmas != 0 else None
    allowances = components.get('allowances')
    if not integer(allowances):
        allowances = None
    quota_value = quota.get('amountCents')
    complement = quota.get('housingComplementSignedCents')
    quota_known = (valid(quota, period) and quota.get('status') == 'available'
                   and integer(quota_value) and not quota.get('sourceConflict'))
    complement_known = (quota.get('housingComplementRows') == 0 or integer(complement))
    quota_excluding_complement = quota_value - (complement or 0) if quota_known and complement_known else None
    office_value = office.get('amountCents') if (valid(office, period)
                   and office.get('status') == 'available' and integer(office.get('amountCents'))) else None
    values = dict(zip(PARTS, (remuneration, allowances, quota_excluding_complement, office_value)))
    gaps = [part for part in SOURCE_GAPS.get(period, ()) if values[part] is None]
    reasons = []
    if service_status != 'in_office':
        reasons.append('outside_mandate' if outside else 'exercise_unknown')
    if not payroll_read:
        reasons.append('payroll_unavailable')
    if quota.get('completeSnapshot') is not True:
        reasons.append('quota_snapshot_unverified')
    if office.get('sourceStatus') != 'imported' and 'office' not in gaps:
        reasons.append('office_incomplete')
    if any(value is None for part, value in values.items() if part not in gaps):
        reasons.append('missing_parts')
    # Preserve observed signed evidence in details; never clamp negative values.
    housing_value = housing.get('housingAllowanceCents') if valid(housing, period) else None
    discrepancy = (allowances is not None and integer(housing_value) and allowances != housing_value)
    inventory = payroll.get('sheetCoverage') or {}
    return {'period': period, 'exercise': service_status, 'daysInOffice': service.get('daysInOffice'),
            'exerciseSource': {'url': (service.get('source') or {}).get('url')} if service.get('source') else None,
            'valuesCents': values,
            'eligible': not reasons, 'exclusionReasons': reasons, 'sourceGaps': gaps,
            'knownSumCents': sum(v for v in values.values() if v is not None) if not reasons else None,
            'christmasBonusCents': christmas if payroll_read else None,
            'payrollStatus': payroll.get('status', 'unavailable'),
            # Nota de rodapé: o inventário anônimo de folhas não identifica deputados.
            'payrollInventory': {'status': inventory.get('status'),
                                 'missingSheetTypes': inventory.get('missingSheetTypes', [])} if inventory else None,
            'complementSignedCents': complement if quota_known and integer(complement) else None,
            'functionalPropertyDays': housing.get('functionalPropertyDays') if valid(housing, period) else None,
            'housingDiscrepancy': discrepancy, 'housingAllowanceForCheckCents': housing_value,
            'otherPayrollCents': {key: components.get(key) for key in ('daily_allowances', 'indemnity_benefits')},
            'sources': {'remuneration': source(payroll), 'allowances': source(payroll),
                        'quota': source(quota), 'office': source(office), 'housing': source(housing)}}


def principal(months, used):
    """Soma exata das médias de cada parte, arredondada para baixo uma única vez.

    Sem lacunas, é igual à média das somas mensais; numa lacuna confirmada, a parte
    ausente é média só dos meses em que foi publicada.
    """
    if not used:
        return None
    total = Fraction(0)
    for part in PARTS:
        values = [months[p]['valuesCents'][part] for p in used if months[p]['valuesCents'][part] is not None]
        if not values:
            return None
        total += Fraction(sum(values), len(values))
    return math.floor(total)


def compose_person(person, service):
    if person.get('house') != 'camara':
        return None
    months = {period: compose_month(person['parts'], service.get('months', {}).get(period, {}), period)
              for period in PERIODS}
    used = [period for period, row in months.items() if row['eligible']]
    summaries = {}
    for part in PARTS:
        part_used = [p for p in used if months[p]['valuesCents'][part] is not None]
        available = [period for period, row in months.items()
                     if row['exercise'] == 'in_office' and row['valuesCents'][part] is not None]
        amount = sum(months[p]['valuesCents'][part] for p in available) if available else None
        summaries[part] = {'months': available, 'amountCents': amount,
                           # Médias arredondadas para baixo ao centavo, como o número principal.
                           'averageCents': amount // len(available) if available else None,
                           # Lacuna da fonte: a parte é média só dos meses em que foi publicada.
                           'usedMonthsAverageCents': (sum(months[p]['valuesCents'][part] for p in part_used)
                                                      // len(part_used)) if part_used else None,
                           # A ficha mostra a fonte do mês mais recente; as demais ficam em cada mês.
                           'sources': [months[available[-1]]['sources'][part]] if available else []}
    complement_months = [p for p, r in months.items() if r['exercise'] == 'in_office' and r['complementSignedCents'] is not None]
    christmas_months = [p for p, r in months.items() if r['exercise'] == 'in_office' and r['christmasBonusCents'] is not None]
    inventory_months = [p for p, r in months.items() if p in used and (r['payrollInventory'] or {}).get('status') == 'partial']
    return {'id': person['id'], 'house': 'camara', 'periodStart': PERIODS[0], 'periodEnd': PERIODS[-1],
            'months': months, 'usedMonths': used,
            'monthlyAverageCents': principal(months, used),
            'sourceGapMonths': {p: months[p]['sourceGaps'] for p in used if months[p]['sourceGaps']},
            'parts': summaries, 'complement': {'months': complement_months,
                'signedAmountCents': sum(months[p]['complementSignedCents'] for p in complement_months) if complement_months else None},
            'christmasBonus': {'months': christmas_months,
                'amountCents': sum(months[p]['christmasBonusCents'] for p in christmas_months) if christmas_months else None,
                'sources': [months[p]['sources']['remuneration'] for p in christmas_months]},
            'payrollInventoryPartialMonths': inventory_months,
            'policy': 'individual-payroll-page;average-of-in-office-months-with-all-parts;christmas-bonus-apart;'
                      'payroll-allowances-only;exclude-quota-housing-complement;no-ranking;'
                      'mandate-period;nominal-values;confirmed-source-gaps-left-empty'}


def _read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def history_quota(root, year):
    """Monthly CEAP sums from the year's local import; the archive itself is the snapshot."""
    data = _read(root / f'data/raw/legislative/history/legislative-{year}.json')
    source = next((s for s in data.get('sources', []) if s.get('id') == 'camara_ceap'), {})
    if source.get('status') != 'imported':
        return {}
    totals = {}
    for row in data.get('expenses', []):
        if row.get('sourceId') != 'camara_ceap' or row.get('year') != year:
            continue
        value = cents(row.get('amount'))
        key = (row.get('authorityId'), f"{year}-{int(row['month']):02d}")
        bucket = totals.setdefault(key, {'amount': 0, 'rows': 0, 'complement': 0, 'complementRows': 0, 'invalid': False})
        if value is None:
            bucket['invalid'] = True
            continue
        bucket['amount'] += value
        bucket['rows'] += 1
        if row.get('category') == COMPLEMENT_CATEGORY:
            bucket['complement'] += value
            bucket['complementRows'] += 1
    result = {}
    for (identifier, period), bucket in totals.items():
        result.setdefault(identifier, {})[period] = {
            'status': 'unavailable' if bucket['invalid'] else 'available', 'period': period,
            'amountCents': None if bucket['invalid'] else bucket['amount'], 'rowCount': bucket['rows'],
            'sourceConflict': False, 'completeSnapshot': True,
            'housingComplementSignedCents': bucket['complement'] if bucket['complementRows'] else None,
            'housingComplementRows': bucket['complementRows'],
            'sourceUrl': source.get('url'), 'fetchedAt': source.get('fetchedAt')}
    return result


def history_office(root):
    """Monthly office spending from the annual profile pages (reais → cents)."""
    data = _read(root / 'data/snapshots/chamber-mandate-history.json')
    result = {}
    for identifier, person in data.get('profiles', {}).items():
        rows = {}
        for period, value in person.get('office', {}).items():
            meta = person.get('sources', {}).get(period[:4], {}).get('office') or {}
            amount = cents(value)
            rows[period] = {'status': 'available' if amount is not None else 'unavailable',
                            'amountCents': amount, 'period': period,
                            'sourceStatus': 'imported' if meta.get('status') in ('imported', 'partial') else meta.get('status'),
                            'sourceUrl': meta.get('url'), 'fetchedAt': meta.get('fetchedAt'), 'stale': False}
        result[identifier] = rows
    return result


def history_parts(root, identifiers):
    """Parts and exercise for 2023–2025, keyed like the 2026 audit."""
    office = history_office(root)
    parts = {identifier: {'payroll': {}, 'housing': {}, 'quota': {}, 'office': dict(office.get(identifier, {}))}
             for identifier in identifiers}
    service = {identifier: {} for identifier in identifiers}
    for year in HISTORY_YEARS:
        quota = history_quota(root, year)
        payroll = _read(root / f'data/snapshots/chamber-payroll-{year}.json').get('profiles', {})
        housing = _read(root / f'data/snapshots/chamber-housing-{year}.json').get('profiles', {})
        exercise = _read(root / f'data/snapshots/chamber-service-{year}.json').get('profiles', {})
        for identifier in identifiers:
            parts[identifier]['quota'].update(quota.get(identifier, {}))
            parts[identifier]['payroll'].update(payroll.get(identifier, {}).get('months', {}))
            parts[identifier]['housing'].update(housing.get(identifier, {}).get('months', {}))
            service[identifier].update(exercise.get(identifier, {}).get('months', {}))
    return parts, service


OUTSIDE_KEYS = ('period', 'exercise', 'daysInOffice', 'exerciseSource', 'eligible', 'exclusionReasons')


def compact(people):
    """Guarda cada link uma vez numa tabela comum; os meses apontam para ela.

    Meses fora do mandato ficam só com exercício e fonte, que é o que a ficha mostra.
    O backend reconstrói o formato completo (``backend.profiles.expand_mandate_cost``).
    """
    urls, index = [], {}

    def ref(source):
        url = (source or {}).get('url')
        if url is None:
            return None
        if url not in index:
            index[url] = len(urls)
            urls.append(url)
        return index[url]

    for person in people.values():
        if person is None:
            continue
        for period, month in list(person['months'].items()):
            if month['exercise'] == 'outside_mandate':
                month = person['months'][period] = {key: month[key] for key in OUTSIDE_KEYS}
            month['exerciseSource'] = ref(month['exerciseSource'])
            if 'sources' in month:
                month['sources'] = {part: ref(value) for part, value in month['sources'].items()}
            # Campos vazios saem do arquivo; o backend os devolve com o valor padrão.
            person['months'][period] = {key: value for key, value in month.items()
                                        if value is not None and value != [] and value is not False}
        for collection in (*person['parts'].values(), person['christmasBonus']):
            collection['sources'] = [[ref(item), item.get('period')] for item in collection['sources']]
    return urls


def build(root=ROOT):
    audit = build_audit(root, 2026)
    path = root / 'data/snapshots/chamber-service.json'
    service = json.loads(path.read_text()) if path.exists() else {}
    from ingest.chamber_quota_audit import build_audit as audit_quota
    archive = root / 'data/raw/legislative/camara-2026.csv.zip'
    quota_check = audit_quota(archive, root / 'data/na-lupa.sqlite3')['currentRoster']['sourceCompleteness'] if archive.exists() else {}
    for identifier, person in audit['profiles'].items():
        for period, row in person['parts']['quota'].items():
            evidence = quota_check.get('profiles', {}).get(identifier, {}).get('months', {}).get(period, {})
            row['completeSnapshot'] = evidence.get('completeSnapshot') is True
    chamber = [identifier for identifier, person in audit['profiles'].items() if person['house'] == 'camara']
    old_parts, old_service = history_parts(root, chamber)
    people = {}
    for identifier in chamber:
        person = audit['profiles'][identifier]
        for part, rows in old_parts[identifier].items():
            person['parts'][part] = {**rows, **person['parts'].get(part, {})}
        current = service.get('profiles', {}).get(identifier, {})
        months = {**old_service[identifier], **current.get('months', {})}
        people[identifier] = compose_person(person, {**current, 'months': months})
    coverage = {'profiles': len(people), 'withPrincipal': sum(p['monthlyAverageCents'] is not None for p in people.values())}
    urls = compact(people)
    return {'schemaVersion': 4, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'periods': list(PERIODS), 'urls': urls, 'profiles': people,
            'quotaVerification': {key: quota_check.get(key) for key in ('completeSnapshot', 'sourceArchiveSha256', 'sourceFetchedAt')},
            'coverage': coverage}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = build(args.root)
    output = args.root / 'data/snapshots/mandate-cost.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    temporary.replace(output)
    print(json.dumps(result['coverage']))


if __name__ == '__main__':
    main()
