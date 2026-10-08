"""Offline evidence/coverage audit for mandate costs; not a public total or API.

Reads the existing SQLite without migration and optional collection snapshots.
No network, no extrapolation, no conversion of missing records to zero.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
COMPLEMENT_CATEGORY = 'COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA'


def cents(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        scaled = Decimal(str(value)) * 100
        return int(scaled) if scaled.is_finite() and scaled == scaled.to_integral_value() else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def common_months(parts, required):
    """Intersection of explicitly usable observations, never just min/max dates."""
    sets = [{month for month, row in parts.get(part, {}).items()
             if row.get('status') == 'available' and isinstance(row.get('amountCents'), int)
             and not isinstance(row.get('amountCents'), bool) and not row.get('stale')
             and row.get('period') == month}
            for part in required]
    return sorted(set.intersection(*sets)) if sets else []


def comparable(left, right, required):
    """Conservative eligibility for a future comparison; never compares Houses."""
    if left.get('house') not in ('camara', 'senado') or left.get('house') != right.get('house'):
        return False
    left_months = common_months(left.get('parts', {}), required)
    right_months = common_months(right.get('parts', {}), required)
    return bool(left_months) and left_months == right_months


def housing_overlap(payroll, housing, quota):
    """Numeric cross-check only; never infer an accounting correction or total."""
    periods = {row.get('period') for row in (payroll, housing, quota)}
    if len(periods) != 1 or None in periods:
        return {'status': 'unavailable', 'reason': 'different-or-missing-periods'}
    values = [payroll.get('allowancesCents'), housing.get('housingAllowanceCents'),
              housing.get('quotaComplementCents'), quota.get('housingComplementSignedCents')]
    if any(value is None or isinstance(value, bool) or not isinstance(value, int) for value in values[:3]):
        return {'status': 'unavailable', 'reason': 'missing-components'}
    payroll_aux, aid, complement, quota_complement = values
    # An equality is evidence of numeric overlap for this observation, not proof
    # of all benefit types, all months, or the sign semantics of the CEAP file.
    return {'status': 'checked', 'period': payroll['period'],
            'payrollEqualsAllowance': payroll_aux == aid,
            'payrollEqualsAllowancePlusComplement': payroll_aux == aid + complement,
            'quotaComplementOppositeSign': quota_complement == -complement if quota_complement is not None else None,
            'quotaComplementSameSign': quota_complement == complement if quota_complement is not None else None,
            'automaticDeduplication': False}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def existing_parts(database, profiles, year, months):
    connection = sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        roster = connection.execute('''SELECT DISTINCT a.id,a.name,a.role FROM authorities a
            JOIN roster r ON r.authorityId=a.id WHERE a.role IN ('deputado','senador') ORDER BY a.id''').fetchall()
        sources = {row['id']: dict(row) for row in connection.execute('SELECT * FROM sources')}
        observed = {}
        for row in connection.execute('''SELECT e.authorityId,e.month,e.sourceId,
                sum(e.amountCents) amountCents,count(*) rowCount,
                sum(CASE WHEN category=? THEN amountCents ELSE 0 END) complementCents,
                sum(CASE WHEN category=? THEN 1 ELSE 0 END) complementRows
                FROM expenses e JOIN roster r ON r.authorityId=e.authorityId
                WHERE e.year=? AND e.kind='reembolso'
                GROUP BY e.authorityId,e.month,e.sourceId''', (COMPLEMENT_CATEGORY, COMPLEMENT_CATEGORY, year)):
            observed.setdefault((row['authorityId'], row['month']), []).append(dict(row))
        result = {}
        for person in roster:
            identifier = person['id']
            house = identifier.split(':')[0]
            office = profiles.get(identifier, {}).get('gabinete', {})
            parts = {'quota': {}, 'office': {}}
            for month in months:
                period = f'{year}-{month:02d}'
                rows = observed.get((identifier, month), [])
                row = rows[0] if len(rows) == 1 else None
                source = sources.get(row['sourceId'] if row else ('camara_ceap' if house == 'camara' else 'senado_ceaps'), {})
                parts['quota'][period] = {
                    'status': 'available' if row else 'unavailable',
                    'amountCents': row['amountCents'] if row else None,
                    'rowCount': sum(item['rowCount'] for item in rows),
                    'sourceConflict': len(rows) > 1,
                    'sourceIds': [item['sourceId'] for item in rows],
                    'housingComplementSignedCents': row['complementCents'] if row and row['complementRows'] else None,
                    'housingComplementRows': row['complementRows'] if row else 0,
                    'period': period, 'sourceUrl': source.get('url'), 'fetchedAt': source.get('fetchedAt'),
                    'detail': 'Soma dos lançamentos observados; ausência de linha não confirma zero nem competência completa.'}
                amount = cents(office.get('months', {}).get(str(month))) if office.get('period') == str(year) else None
                parts['office'][period] = {
                    'status': 'available' if amount is not None else 'unavailable',
                    'amountCents': amount, 'period': period, 'sourceStatus': office.get('status'),
                    'sourceUrl': office.get('sourceUrl'), 'fetchedAt': office.get('fetchedAt'),
                    'sourceUpdatedAt': office.get('sourceUpdatedAt'), 'stale': bool(office.get('stale')),
                    'staffCount': None,
                    'detail': 'Verba de gabinete; não inclui todos os encargos. Contagem mensal de equipe não publicada neste snapshot.'}
            result[identifier] = {'id': identifier, 'name': person['name'], 'house': house, 'parts': parts}
        return result
    finally:
        connection.close()


def observed_payroll_components(observation):
    """Sum explicitly published sheets per component, never estimate a missing one."""
    sheets = observation.get('sheets', [])
    period = observation.get('period')
    if (not sheets or any(sheet.get('period') != period for sheet in sheets)
            or any('duplicate-components' in issue for issue in observation.get('issues', []))):
        return {}
    keys = set().union(*(sheet.get('componentsCents', {}) for sheet in sheets))
    result = {}
    for key in keys:
        values = [sheet.get('componentsCents', {}).get(key) for sheet in sheets]
        result[key] = sum(values) if all(isinstance(v, int) and not isinstance(v, bool) for v in values) else None
    return result


def build(root=ROOT, year=2026, months=tuple(range(1, 10))):
    profiles = read_json(root / 'data/snapshots/perfis.json').get('profiles', {})
    people = existing_parts(root / 'data/na-lupa.sqlite3', profiles, year, months)
    # Preserve collector observations with their own schemas and provenance.
    inputs = {}
    for part, filename in [('payroll', 'chamber-payroll.json'), ('housing', 'chamber-housing.json')]:
        snapshot = read_json(root / 'data/snapshots' / filename)
        inputs[part] = {'path': filename, 'generatedAt': snapshot.get('generatedAt')}
        for identifier, person in people.items():
            person['parts'][part] = snapshot.get('profiles', {}).get(identifier, {}).get('months', {})
    for person in people.values():
        person['overlapChecks'] = {}
        person['observedPayrollComponents'] = {}
        for month in months:
            period = f'{year}-{month:02d}'
            payroll = person['parts']['payroll'].get(period, {})
            components = observed_payroll_components(payroll)
            person['observedPayrollComponents'][period] = components
            person['overlapChecks'][period] = housing_overlap(
                {'period': payroll.get('period'), 'allowancesCents': components.get('allowances')},
                person['parts']['housing'].get(period, {}), person['parts']['quota'].get(period, {}))
    coverage = {}
    for house in ('camara', 'senado'):
        members = [p for p in people.values() if p['house'] == house]
        coverage[house] = {'roster': len(members), 'months': {}}
        for month in months:
            period = f'{year}-{month:02d}'
            coverage[house]['months'][period] = {
                part: dict(Counter(p['parts'].get(part, {}).get(period, {}).get('status', 'unavailable') for p in members))
                for part in ('quota', 'office', 'payroll', 'housing')}
            payroll_rows = [p['parts']['payroll'].get(period, {}) for p in members]
            coverage[house]['months'][period]['payrollEvidence'] = {
                'withPublishedSheets': sum(bool(row.get('sheets')) for row in payroll_rows),
                'withAdditionalSheets': sum(len(row.get('sheets', [])) > 1 for row in payroll_rows),
                'completeDetailTables': sum(row.get('detailStatus') == 'complete' for row in payroll_rows),
                'completeMonthlyCoverage': sum(row.get('status') == 'complete' for row in payroll_rows)}
    return {'schemaVersion': 1, 'year': year,
            'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'kind': 'evidence-audit-not-public-cost-total', 'inputs': inputs,
            'comparisonPolicy': 'same-house-same-parts-same-confirmed-months-only',
            'coverage': coverage, 'profiles': people}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = build(args.root, args.year)
    output = args.root / 'data/snapshots/mandate-cost-audit.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(output)
    print(json.dumps(result['coverage'], ensure_ascii=False))


if __name__ == '__main__':
    main()
