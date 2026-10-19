"""Read-only consistency checks for numeric values exposed by the site."""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

from backend import citizen, config, votes


OPTIONAL_SNAPSHOTS = ('presenca.json', 'mandate-cost.json', 'senate-cost.json', votes.INDEX_NAME)
MONTHLY_COST_ROUNDING_TOLERANCE = 0.005
QUOTA_AUDIT_EXAMPLES = 20


def _new_report(db_path, snapshots_path):
    return {
        'status': 'ok',
        'database': str(db_path),
        'snapshots': str(snapshots_path),
        'counts': {'checks': 0, 'items': 0, 'issues': 0, 'skipped': 0},
        'issues': [],
        'skipped': [],
    }


def _check(report, condition, code, location, message, details=None):
    report['counts']['checks'] += 1
    if condition:
        return True
    issue = {'code': code, 'location': location, 'message': message}
    if details is not None:
        issue['details'] = _json_safe(details)
    report['issues'].append(issue)
    report['counts']['issues'] += 1
    return False


def _skip(report, location, message):
    report['skipped'].append({'location': location, 'message': message})
    report['counts']['skipped'] += 1


def _item(report):
    report['counts']['items'] += 1


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    return value


def _check_finite_values(value, report, location):
    """Check all numeric leaves in a bounded API response or snapshot."""
    if isinstance(value, dict):
        for key, child in value.items():
            _check_finite_values(child, report, f'{location}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_finite_values(child, report, f'{location}[{index}]')
    elif _is_number(value):
        _check(report, _is_finite_number(value), 'non_finite_number', location,
               'Numeric value must be finite.', value)


def audit_summary_payload(summary, report):
    """Check the numeric invariants in the public /api/c/resumo response."""
    _check_finite_values(summary, report, 'api.summary')
    if not isinstance(summary, dict):
        _check(report, False, 'invalid_summary', 'api.summary', 'Summary API response must be an object.')
        return

    parliamentarians = summary.get('parlamentares')
    reimbursements = summary.get('reembolsos')
    monthly_cost = summary.get('custoMensal')
    for field, value in (('parlamentares', parliamentarians), ('reembolsos', reimbursements),
                         ('custoMensal', monthly_cost)):
        _check(report, isinstance(value, dict), 'invalid_summary_section', f'api.summary.{field}',
               f'Summary section {field} must be an object.')

    if not all(isinstance(value, dict) for value in (parliamentarians, reimbursements, monthly_cost)):
        return

    for role in citizen.ROLES:
        _item(report)
        person_counts = parliamentarians.get(role)
        reimbursement = reimbursements.get(role)
        costs = monthly_cost.get(role)
        location = f'api.summary.{role}'
        _check(report, isinstance(person_counts, dict), 'invalid_role_summary', f'{location}.parlamentares',
               'Parliamentarian summary must be an object.')
        _check(report, isinstance(reimbursement, dict), 'invalid_role_summary', f'{location}.reembolsos',
               'Reimbursement summary must be an object.')
        _check(report, isinstance(costs, dict), 'invalid_role_summary', f'{location}.custoMensal',
               'Monthly cost summary must be an object.')
        if not all(isinstance(value, dict) for value in (person_counts, reimbursement, costs)):
            continue

        total = person_counts.get('total')
        with_reimbursements = person_counts.get('comReembolsos')
        _check(report, _is_count(total), 'invalid_roster_total', f'{location}.parlamentares.total',
               'Roster total must be a nonnegative integer.', total)
        _check(report, _is_count(with_reimbursements), 'invalid_roster_coverage',
               f'{location}.parlamentares.comReembolsos', 'Roster coverage must be a nonnegative integer.',
               with_reimbursements)
        if _is_count(total) and _is_count(with_reimbursements):
            _check(report, with_reimbursements <= total, 'roster_coverage_exceeds_total',
                   f'{location}.parlamentares', 'People with reimbursement data cannot exceed the roster total.',
                   {'comReembolsos': with_reimbursements, 'total': total})

        reimbursement_count = reimbursement.get('comRegistros')
        _check(report, _is_count(reimbursement_count), 'invalid_roster_coverage',
               f'{location}.reembolsos.comRegistros', 'Reimbursement coverage must be a nonnegative integer.',
               reimbursement_count)
        if _is_count(total) and _is_count(reimbursement_count):
            _check(report, reimbursement_count <= total, 'roster_coverage_exceeds_total',
                   f'{location}.reembolsos.comRegistros', 'People with reimbursement records cannot exceed the roster total.',
                   {'comRegistros': reimbursement_count, 'total': total})
        if _is_count(with_reimbursements) and _is_count(reimbursement_count):
            _check(report, reimbursement_count == with_reimbursements, 'summary_coverage_mismatch',
                   f'{location}.reembolsos.comRegistros',
                   'Reimbursement coverage must match the parliamentarian summary.',
                   {'comReembolsos': with_reimbursements, 'comRegistros': reimbursement_count})

        cost_total = costs.get('total')
        cost_count = costs.get('comCusto')
        _check(report, _is_count(cost_total), 'invalid_roster_total', f'{location}.custoMensal.total',
               'Cost denominator must be a nonnegative integer.', cost_total)
        _check(report, _is_count(cost_count), 'invalid_roster_coverage', f'{location}.custoMensal.comCusto',
               'Cost coverage must be a nonnegative integer.', cost_count)
        if _is_count(cost_total) and _is_count(cost_count):
            _check(report, cost_count <= cost_total, 'roster_coverage_exceeds_total',
                   f'{location}.custoMensal', 'People with a monthly cost cannot exceed the roster total.',
                   {'comCusto': cost_count, 'total': cost_total})
        if _is_count(total) and _is_count(cost_total):
            _check(report, cost_total == total, 'cost_roster_total_mismatch',
                   f'{location}.custoMensal.total', 'Cost denominator must match the roster total.',
                   {'costTotal': cost_total, 'rosterTotal': total})

        minimum, mean, maximum = (costs.get('minimo'), costs.get('media'), costs.get('maximo'))
        if _is_count(cost_count) and cost_count == 0:
            _check(report, minimum is None and mean is None and maximum is None,
                   'cost_without_coverage', f'{location}.custoMensal',
                   'Monthly cost statistics must remain unavailable when no people have cost data.')
        elif all(_is_finite_number(value) for value in (minimum, mean, maximum)):
            _check(report,
                   minimum - MONTHLY_COST_ROUNDING_TOLERANCE <= mean <= maximum + MONTHLY_COST_ROUNDING_TOLERANCE,
                   'monthly_cost_order', f'{location}.custoMensal',
                   'Monthly cost values must satisfy minimum <= mean <= maximum within half a cent of rounding.',
                   {'minimo': minimum, 'media': mean, 'maximo': maximum,
                    'tolerance': MONTHLY_COST_ROUNDING_TOLERANCE})
        else:
            _check(report, False, 'incomplete_monthly_cost', f'{location}.custoMensal',
                   'Monthly cost statistics must all be finite numbers when cost coverage is nonzero.',
                   {'minimo': minimum, 'media': mean, 'maximo': maximum, 'comCusto': cost_count})


def audit_parties_payload(parties, report):
    """Check numeric coverage in the public /api/c/partidos response."""
    _check_finite_values(parties, report, 'api.parties')
    if not isinstance(parties, dict):
        _check(report, False, 'invalid_parties', 'api.parties', 'Parties API response must be an object.')
        return
    items = parties.get('itens')
    _check(report, isinstance(items, list), 'invalid_party_items', 'api.parties.itens',
           'Parties API items must be a list.')
    if not isinstance(items, list):
        return

    for index, party in enumerate(items):
        _item(report)
        location = f'api.parties.itens[{index}]'
        _check(report, isinstance(party, dict), 'invalid_party', location, 'Party item must be an object.')
        if not isinstance(party, dict):
            continue
        party_members = party.get('membros')
        _check(report, _is_count(party_members), 'invalid_party_member_count', f'{location}.membros',
               'Party member count must be a nonnegative integer.', party_members)
        combined_members = 0
        combined_members_valid = _is_count(party_members)
        for role in citizen.ROLES:
            role_counts = party.get(role)
            if role_counts is None:
                continue
            role_location = f'{location}.{role}'
            _check(report, isinstance(role_counts, dict), 'invalid_party_role', role_location,
                   'Party role metrics must be an object when present.')
            if not isinstance(role_counts, dict):
                combined_members_valid = False
                continue
            members = role_counts.get('membros')
            if _is_count(members):
                combined_members += members
            else:
                combined_members_valid = False
            with_data = role_counts.get('comDados')
            people_with_alerts = role_counts.get('comAlerta')
            alert_events = role_counts.get('alertas')
            for field, value in (('membros', members), ('comDados', with_data),
                                 ('comAlerta', people_with_alerts), ('alertas', alert_events)):
                _check(report, _is_count(value), 'invalid_party_count', f'{role_location}.{field}',
                       f'{field} must be a nonnegative integer.', value)
            if all(_is_count(value) for value in (members, with_data, people_with_alerts)):
                _check(report, people_with_alerts <= with_data <= members, 'party_people_coverage_order',
                       role_location, 'Party people counts must satisfy 0 <= comAlerta <= comDados <= membros.',
                       {'comAlerta': people_with_alerts, 'comDados': with_data, 'membros': members})
            if _is_count(people_with_alerts) and _is_count(alert_events):
                _check(report, people_with_alerts <= alert_events, 'party_alert_events_below_people',
                       role_location, 'Alert event count cannot be below the number of people with alerts.',
                       {'comAlerta': people_with_alerts, 'alertas': alert_events})
            # alertas is an event count. It may legitimately exceed the number of people.
        if combined_members_valid:
            _check(report, party_members == combined_members, 'party_house_members_mismatch', location,
                   'Party member count must equal the sum of its House member counts.',
                   {'membros': party_members, 'houseMembers': combined_members})


def audit_attendance_rows(rows, report, location='snapshot.presenca.json'):
    if not isinstance(rows, list):
        _check(report, False, 'invalid_attendance_snapshot', location,
               'Attendance snapshot must contain a list of rows.')
        return
    for index, row in enumerate(rows):
        _item(report)
        row_location = f'{location}[{index}]'
        _check(report, isinstance(row, dict), 'invalid_attendance_row', row_location,
               'Attendance row must be an object.')
        if not isinstance(row, dict):
            continue
        days, present, absent, justified = (row.get('dias'), row.get('presente'), row.get('falta'),
                                            row.get('justificadas'))
        values = {'dias': days, 'presente': present, 'falta': absent, 'justificadas': justified}
        for field, value in values.items():
            _check(report, _is_count(value), 'invalid_attendance_count', f'{row_location}.{field}',
                   f'{field} must be a nonnegative integer.', value)
        if not all(_is_count(value) for value in values.values()):
            continue
        _check(report, days > 0, 'invalid_attendance_days', f'{row_location}.dias',
               'Attendance denominator must be positive.', days)
        if days > 0:
            _check(report, present + absent + justified == days, 'attendance_totals_mismatch', row_location,
                   'Presence, absences, and justified absences must sum to the session day count.',
                   {'presente': present, 'falta': absent, 'justificadas': justified, 'dias': days})


def published_chamber_quota_rows(snapshot, report):
    """Extract only numeric monthly quota values published for Câmara profiles."""
    if not isinstance(snapshot, dict):
        _check(report, False, 'invalid_mandate_cost_snapshot', 'snapshot.mandate-cost.json',
               'Mandate-cost snapshot must be an object.')
        return []
    profiles = snapshot.get('profiles')
    _check(report, isinstance(profiles, dict), 'invalid_mandate_cost_profiles',
           'snapshot.mandate-cost.json.profiles', 'Mandate-cost profiles must be an object.')
    if not isinstance(profiles, dict):
        return []

    published = []
    for identifier, profile in profiles.items():
        if not isinstance(profile, dict) or profile.get('house') != 'camara':
            continue
        months = profile.get('months')
        if not isinstance(months, dict):
            continue
        for period, month in months.items():
            if not isinstance(month, dict):
                continue
            values = month.get('valuesCents')
            if not isinstance(values, dict):
                continue
            cents = values.get('quota')
            if not isinstance(cents, int) or isinstance(cents, bool):
                continue
            match = re.fullmatch(r'(\d{4})-(\d{2})', str(period))
            if not match or not 1 <= int(match.group(2)) <= 12:
                _check(report, False, 'invalid_mandate_cost_period',
                       f'snapshot.mandate-cost.json.profiles.{identifier}.months.{period}',
                       'A published monthly quota must use a YYYY-MM period.', period)
                continue
            published.append({'authorityId': str(identifier), 'period': str(period),
                              'year': int(match.group(1)), 'month': int(match.group(2)),
                              'storedCents': cents})
    return published


def audit_chamber_quota_rows(published, db, report):
    """Compare stored quota cents with the citizen API's observed reimbursement rowset.

    A month containing only housing-complement rows is observed and has a non-complement
    quota of zero. A month with no reimbursement or complement row is left unverified, not
    filled with a zero. Signed reimbursements are summed as stored.
    """
    result = {'publishedMonths': len(published), 'comparedMonths': 0, 'mismatchMonths': 0,
              'unobservedMonths': 0, 'mismatchExamples': [], 'unobservedExamples': []}
    if not published:
        report['quotaRecomposition'] = result
        return

    identifiers = sorted({row['authorityId'] for row in published})
    years = [min(row['year'] for row in published), max(row['year'] for row in published)]
    target_values = ','.join('( ? )' for _ in identifiers)
    query = f'''WITH target_authorities(id) AS (VALUES {target_values}), observed AS (
            SELECT e.authorityId,e.year,e.month,e.amountCents,e.kind
            FROM expenses e JOIN target_authorities t ON t.id=e.authorityId
            WHERE e.year BETWEEN ? AND ? AND e.kind IN ('reembolso','complemento_moradia')
        UNION ALL
            SELECT h.authorityId,h.year,h.month,h.amountCents,h.kind
            FROM quota_history h JOIN target_authorities t ON t.id=h.authorityId
            WHERE h.year BETWEEN ? AND ? AND h.kind IN ('reembolso','complemento_moradia'))
        SELECT authorityId,year,month,COUNT(*) observedRows,
            SUM(CASE WHEN kind='reembolso' THEN 1 ELSE 0 END) reimbursementRows,
            SUM(CASE WHEN kind='reembolso' THEN amountCents ELSE 0 END) reimbursementCents
        FROM observed GROUP BY authorityId,year,month'''
    params = [*identifiers, *years, *years]
    try:
        database_rows = db.execute(query, params).fetchall()
    except sqlite3.Error as error:
        _check(report, False, 'quota_recomposition_failed', 'database.expenses+quota_history',
               'Could not recompute published monthly quota from reimbursement rows.', str(error))
        report['quotaRecomposition'] = result
        return

    observed = {(row['authorityId'], int(row['year']), int(row['month'])): row
                for row in database_rows}
    for published_row in published:
        key = (published_row['authorityId'], published_row['year'], published_row['month'])
        database_row = observed.get(key)
        if database_row is None:
            result['unobservedMonths'] += 1
            if len(result['unobservedExamples']) < QUOTA_AUDIT_EXAMPLES:
                result['unobservedExamples'].append({
                    'authorityId': published_row['authorityId'], 'period': published_row['period'],
                    'storedCents': published_row['storedCents'], 'databaseCents': None,
                })
            continue

        result['comparedMonths'] += 1
        report['counts']['checks'] += 1
        database_cents = int(database_row['reimbursementCents'])
        if database_cents != published_row['storedCents']:
            result['mismatchMonths'] += 1
            if len(result['mismatchExamples']) < QUOTA_AUDIT_EXAMPLES:
                result['mismatchExamples'].append({
                    'authorityId': published_row['authorityId'], 'period': published_row['period'],
                    'storedCents': published_row['storedCents'], 'databaseCents': database_cents,
                    'databaseReimbursementRows': int(database_row['reimbursementRows']),
                    'databaseObservedRows': int(database_row['observedRows']),
                })

    _check(report, result['mismatchMonths'] == 0, 'mandate_cost_quota_mismatch',
           'snapshot.mandate-cost.json.profiles.*.months.*.valuesCents.quota',
           'Published Câmara quota cents must match the observed database reimbursement sum.',
           {'mismatchMonths': result['mismatchMonths'], 'examples': result['mismatchExamples'],
            'examplesOmitted': max(0, result['mismatchMonths'] - len(result['mismatchExamples']))})
    if result['unobservedMonths']:
        examples = ', '.join(f"{row['authorityId']} {row['period']}" for row in result['unobservedExamples'])
        omitted = max(0, result['unobservedMonths'] - len(result['unobservedExamples']))
        suffix = f'; {omitted} more omitted' if omitted else ''
        _skip(report, 'snapshot.mandate-cost.json.profiles.*.months.*.valuesCents.quota',
              f"{result['unobservedMonths']} published quota month(s) had no reimbursement or housing-complement rows; "
              f"left unverified rather than treating the missing database sum as zero. Examples: {examples}{suffix}.")
    report['quotaRecomposition'] = result


def audit_tally(tally, report, location):
    """Check a scoreboard tally while preserving unknown (null) published counts."""
    _check(report, isinstance(tally, dict), 'invalid_scoreboard_tally', location,
           'Scoreboard tally must be an object.')
    if not isinstance(tally, dict):
        return
    choices = ('yes', 'no', 'abstention')
    for field in (*choices, 'total'):
        value = tally.get(field)
        _check(report, value is None or _is_count(value), 'invalid_scoreboard_count', f'{location}.{field}',
               'Published vote counts must be nonnegative integers or null when unavailable.', value)
    total = tally.get('total')
    known_choices = [tally.get(field) for field in choices if _is_count(tally.get(field))]
    if _is_count(total):
        _check(report, sum(known_choices) <= total, 'scoreboard_tally_exceeds_total', location,
               'The sum of published choice counts cannot exceed the published total.',
               {'knownChoices': sum(known_choices), 'total': total})


def _reject_json_constant(value):
    raise ValueError(f'Invalid JSON numeric constant: {value}')


def _read_snapshot(path, report):
    if not path.is_file():
        _skip(report, str(path), 'Optional snapshot is unavailable; no numeric value was substituted.')
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_json_constant)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as error:
        _check(report, False, 'snapshot_unreadable', str(path),
               'Snapshot exists but could not be read as valid JSON.', str(error))
        return None


def _audit_scoreboard(index_path, report):
    if not index_path.is_file():
        _skip(report, str(index_path), 'Optional scoreboard snapshot is unavailable; no tally was treated as zero.')
        return

    first_page = votes.listing({'page': '1', 'pageSize': '24'}, index_path)
    _check(report, first_page.get('available') is True, 'scoreboard_unavailable', str(index_path),
           'The public scoreboard API could not validate this snapshot.')
    if first_page.get('available') is not True:
        return

    all_items = list(first_page.get('items') or [])
    for page in range(2, first_page.get('pageCount', 1) + 1):
        page_result = votes.listing({'page': str(page), 'pageSize': '24'}, index_path)
        if page_result.get('available') is not True:
            _check(report, False, 'scoreboard_page_unavailable', str(index_path),
                   f'The public scoreboard API could not load page {page}.')
            continue
        all_items.extend(page_result.get('items') or [])

    detail_unavailable = 0
    for index, item in enumerate(all_items):
        _item(report)
        identifier = item.get('id')
        detail = votes.detail(identifier, index_path) if isinstance(identifier, str) else None
        vote = detail.get('vote') if isinstance(detail, dict) else item
        if not isinstance(vote, dict):
            _check(report, False, 'invalid_scoreboard_vote', f'{index_path}[{index}]',
                   'Scoreboard vote detail must be an object.')
            continue
        _check_finite_values(vote, report, f'snapshot.chamber-votes.items[{index}]')
        audit_tally(vote.get('tally'), report, f'snapshot.chamber-votes.items[{index}].tally')
        for segment_index, segment in enumerate(vote.get('segments') or []):
            _item(report)
            audit_tally(segment.get('tally') if isinstance(segment, dict) else None, report,
                        f'snapshot.chamber-votes.items[{index}].segments[{segment_index}].tally')
        if not isinstance(detail, dict) or detail.get('participantsAvailable') is not True:
            detail_unavailable += 1
        else:
            for party_index, party in enumerate(detail.get('partyTotals') or []):
                if not isinstance(party, dict):
                    _check(report, False, 'invalid_scoreboard_party_total',
                           f'snapshot.chamber-votes.items[{index}].partyTotals[{party_index}]',
                           'Scoreboard party total must be an object.')
                    continue
                _check_finite_values(party, report,
                                     f'snapshot.chamber-votes.items[{index}].partyTotals[{party_index}]')
                for field in ('yes', 'no', 'other'):
                    _check(report, _is_count(party.get(field)), 'invalid_scoreboard_party_count',
                           f'snapshot.chamber-votes.items[{index}].partyTotals[{party_index}].{field}',
                           'Scoreboard party counts must be nonnegative integers.', party.get(field))
    if detail_unavailable:
        _skip(report, f'{index_path.parent / votes.DETAILS_DIRECTORY}',
              f'Roll-call detail snapshots are unavailable or invalid for {detail_unavailable} of {len(all_items)} votes.')


def _connect_read_only(path):
    uri = f'{path.resolve().as_uri()}?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def audit_numbers(db_path=None, snapshots_path=None):
    db_path = Path(db_path).expanduser() if db_path is not None else config.DB_PATH
    snapshots_path = Path(snapshots_path).expanduser() if snapshots_path is not None else config.SNAPSHOTS_PATH
    report = _new_report(db_path, snapshots_path)

    optional_snapshots = {}
    for filename in OPTIONAL_SNAPSHOTS:
        if filename in ('presenca.json', votes.INDEX_NAME):
            continue
        snapshot = _read_snapshot(snapshots_path / filename, report)
        optional_snapshots[filename] = snapshot
        if snapshot is not None:
            _check_finite_values(snapshot, report, f'snapshot.{filename}')
    quota_snapshot = optional_snapshots.get('mandate-cost.json')
    published_quota = (published_chamber_quota_rows(quota_snapshot, report)
                       if quota_snapshot is not None else [])

    if not db_path.is_file():
        _check(report, False, 'database_missing', str(db_path), 'Database file is missing; numeric audit cannot run.')
        if published_quota:
            _skip(report, 'snapshot.mandate-cost.json.profiles.*.months.*.valuesCents.quota',
                  'Quota recomposition was skipped because the missing database was already reported.')
    else:
        quota_audit_attempted = False
        try:
            db = _connect_read_only(db_path)
            original_snapshots_path = config.SNAPSHOTS_PATH
            try:
                if quota_snapshot is not None:
                    quota_audit_attempted = True
                    audit_chamber_quota_rows(published_quota, db, report)
                # citizen.summary calls costs.monthly_costs, which reads this configured snapshot directory.
                config.SNAPSHOTS_PATH = snapshots_path
                summary = citizen.summary(db)
                parties = citizen.parties(db)
            finally:
                config.SNAPSHOTS_PATH = original_snapshots_path
                db.close()
            audit_summary_payload(summary, report)
            audit_parties_payload(parties, report)
        except Exception as error:  # A bad or outdated local DB must still produce an actionable report.
            _check(report, False, 'database_audit_failed', str(db_path),
                   'Could not read the public summary and parties APIs from this database.', str(error))
            if published_quota and not quota_audit_attempted:
                _skip(report, 'snapshot.mandate-cost.json.profiles.*.months.*.valuesCents.quota',
                      'Quota recomposition was skipped because the database could not be read; the database error was reported above.')

    attendance_path = snapshots_path / 'presenca.json'
    attendance = _read_snapshot(attendance_path, report)
    if attendance is not None:
        _check_finite_values(attendance, report, 'snapshot.presenca.json')
        audit_attendance_rows(attendance, report)

    _audit_scoreboard(snapshots_path / votes.INDEX_NAME, report)
    report['status'] = 'failed' if report['counts']['issues'] else 'ok'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audit exposed site numbers without modifying local data.')
    parser.add_argument('--db', type=Path, default=config.DB_PATH, help='SQLite database path (read-only).')
    parser.add_argument('--snapshots', type=Path, default=config.SNAPSHOTS_PATH,
                        help='Directory containing optional JSON snapshots.')
    args = parser.parse_args(argv)
    report = audit_numbers(args.db, args.snapshots)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 1 if report['counts']['issues'] else 0


if __name__ == '__main__':
    sys.exit(main())
