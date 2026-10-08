"""Compose a Câmara monthly average from local source snapshots.

No network, database writes, ranking or cross-House comparison. Housing amounts
are reconciliation evidence only; allowances enter through individual payroll.
The individual official payroll page is the person's record; the anonymous
sheet inventory is kept only as a footnote and never blocks a month.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from ingest.mandate_cost_audit import build as build_audit, observed_payroll_components

ROOT = Path(__file__).resolve().parents[1]
PERIODS = tuple(f'2026-{month:02d}' for month in range(1, 8))
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
    original = row.get('source', row)
    return {'url': original.get('url', original.get('sourceUrl')),
            'fetchedAt': original.get('fetchedAt'), 'period': row.get('period')}


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
    reasons = []
    if service_status != 'in_office':
        reasons.append('outside_mandate' if outside else 'exercise_unknown')
    if not payroll_read:
        reasons.append('payroll_unavailable')
    if quota.get('completeSnapshot') is not True:
        reasons.append('quota_snapshot_unverified')
    if office.get('sourceStatus') != 'imported':
        reasons.append('office_incomplete')
    if any(value is None for value in values.values()):
        reasons.append('missing_parts')
    # Preserve observed signed evidence in details; never clamp negative values.
    housing_value = housing.get('housingAllowanceCents') if valid(housing, period) else None
    discrepancy = (allowances is not None and integer(housing_value) and allowances != housing_value)
    inventory = payroll.get('sheetCoverage') or {}
    return {'period': period, 'exercise': service_status, 'daysInOffice': service.get('daysInOffice'),
            'exerciseSource': service.get('source'), 'valuesCents': values,
            'eligible': not reasons, 'exclusionReasons': reasons,
            'knownSumCents': sum(values.values()) if not reasons else None,
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


def compose_person(person, service):
    if person.get('house') != 'camara':
        return None
    months = {period: compose_month(person['parts'], service.get('months', {}).get(period, {}), period)
              for period in PERIODS}
    used = [period for period, row in months.items() if row['eligible']]
    total = sum(months[period]['knownSumCents'] for period in used)
    summaries = {}
    for part in PARTS:
        available = [period for period, row in months.items()
                     if row['exercise'] == 'in_office' and row['valuesCents'][part] is not None]
        amount = sum(months[p]['valuesCents'][part] for p in available) if available else None
        summaries[part] = {'months': available, 'amountCents': amount,
                           # Médias arredondadas para baixo ao centavo, como o número principal.
                           'averageCents': amount // len(available) if available else None,
                           'usedMonthsAverageCents': sum(months[p]['valuesCents'][part] for p in used) // len(used) if used else None,
                           'sources': [months[p]['sources'][part] for p in available]}
    complement_months = [p for p, r in months.items() if r['exercise'] == 'in_office' and r['complementSignedCents'] is not None]
    christmas_months = [p for p, r in months.items() if r['exercise'] == 'in_office' and r['christmasBonusCents'] is not None]
    inventory_months = [p for p, r in months.items() if p in used and (r['payrollInventory'] or {}).get('status') == 'partial']
    return {'id': person['id'], 'house': 'camara', 'periodStart': PERIODS[0], 'periodEnd': PERIODS[-1],
            'months': months, 'usedMonths': used,
            'monthlyAverageCents': total // len(used) if used else None,
            'parts': summaries, 'complement': {'months': complement_months,
                'signedAmountCents': sum(months[p]['complementSignedCents'] for p in complement_months) if complement_months else None},
            'christmasBonus': {'months': christmas_months,
                'amountCents': sum(months[p]['christmasBonusCents'] for p in christmas_months) if christmas_months else None,
                'sources': [months[p]['sources']['remuneration'] for p in christmas_months]},
            'payrollInventoryPartialMonths': inventory_months,
            'policy': 'individual-payroll-page;average-of-in-office-months-with-all-parts;christmas-bonus-apart;'
                      'payroll-allowances-only;exclude-quota-housing-complement;no-ranking'}


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
    people = {identifier: compose_person(person, service.get('profiles', {}).get(identifier, {}))
              for identifier, person in audit['profiles'].items() if person['house'] == 'camara'}
    return {'schemaVersion': 2, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'periods': list(PERIODS), 'profiles': people,
            'quotaVerification': {key: quota_check.get(key) for key in ('completeSnapshot', 'sourceArchiveSha256', 'sourceFetchedAt')},
            'coverage': {'profiles': len(people), 'withPrincipal': sum(p['monthlyAverageCents'] is not None for p in people.values())}}


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
