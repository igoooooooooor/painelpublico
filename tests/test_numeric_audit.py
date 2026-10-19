import contextlib
import hashlib
import io
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import audit_numbers


def summary_fixture():
    return {
        'parlamentares': {
            'deputado': {'total': 3, 'comReembolsos': 2},
            'senador': {'total': 2, 'comReembolsos': 0},
        },
        'reembolsos': {
            'deputado': {'comRegistros': 2, 'total': 1200.0, 'media': 100.0},
            'senador': {'comRegistros': 0, 'total': None, 'media': None},
        },
        'custoMensal': {
            'deputado': {'total': 3, 'comCusto': 2, 'minimo': 100.0, 'media': 150.0, 'maximo': 200.0},
            'senador': {'total': 2, 'comCusto': 0, 'minimo': None, 'media': None, 'maximo': None},
        },
    }


def parties_fixture(*, people_with_alerts=1, with_data=2, members=3, alert_events=12):
    return {
        'itens': [{
            'sigla': 'ABC',
            'membros': members,
            'deputado': {
                'membros': members,
                'comDados': with_data,
                'comAlerta': people_with_alerts,
                'alertas': alert_events,
            },
            'senador': None,
        }],
    }


class NumericAuditTests(unittest.TestCase):
    def setUp(self):
        self.report = audit_numbers._new_report('fixture.sqlite3', 'snapshots')

    def test_party_alert_event_count_can_exceed_people(self):
        audit_numbers.audit_parties_payload(
            parties_fixture(people_with_alerts=1, with_data=2, members=3, alert_events=40), self.report)

        self.assertEqual(self.report['issues'], [])

    def test_party_people_count_cannot_exceed_its_denominator(self):
        audit_numbers.audit_parties_payload(
            parties_fixture(people_with_alerts=3, with_data=2, members=3), self.report)

        self.assertIn('party_people_coverage_order', {issue['code'] for issue in self.report['issues']})

    def test_party_data_coverage_cannot_exceed_members(self):
        audit_numbers.audit_parties_payload(
            parties_fixture(people_with_alerts=1, with_data=4, members=3), self.report)

        self.assertIn('party_people_coverage_order', {issue['code'] for issue in self.report['issues']})

    def test_summary_checks_roster_coverage_and_cost_order(self):
        audit_numbers.audit_summary_payload(summary_fixture(), self.report)

        self.assertEqual(self.report['issues'], [])

    def test_summary_rejects_cost_coverage_over_roster_and_wrong_cost_order(self):
        summary = summary_fixture()
        summary['custoMensal']['deputado'].update(comCusto=4, minimo=200.0, media=150.0, maximo=100.0)

        audit_numbers.audit_summary_payload(summary, self.report)

        codes = {issue['code'] for issue in self.report['issues']}
        self.assertIn('roster_coverage_exceeds_total', codes)
        self.assertIn('monthly_cost_order', codes)

    def test_cost_order_allows_only_half_cent_of_rounding_difference(self):
        summary = summary_fixture()
        summary['custoMensal']['deputado'].update(minimo=100.0, media=99.996, maximo=100.0)

        audit_numbers.audit_summary_payload(summary, self.report)

        self.assertNotIn('monthly_cost_order', {issue['code'] for issue in self.report['issues']})

        summary['custoMensal']['deputado']['media'] = 99.99
        report = audit_numbers._new_report('fixture.sqlite3', 'snapshots')
        audit_numbers.audit_summary_payload(summary, report)
        self.assertIn('monthly_cost_order', {issue['code'] for issue in report['issues']})

    def test_cost_denominator_must_match_roster_total(self):
        summary = summary_fixture()
        summary['custoMensal']['deputado']['total'] = 2

        audit_numbers.audit_summary_payload(summary, self.report)

        self.assertIn('cost_roster_total_mismatch', {issue['code'] for issue in self.report['issues']})

    def test_party_house_member_counts_must_add_up_and_alerts_cover_people(self):
        parties = parties_fixture(people_with_alerts=2, with_data=2, members=3, alert_events=1)
        parties['itens'][0]['senador'] = {'membros': 1, 'comDados': 0, 'comAlerta': 0, 'alertas': 0}

        audit_numbers.audit_parties_payload(parties, self.report)

        codes = {issue['code'] for issue in self.report['issues']}
        self.assertIn('party_house_members_mismatch', codes)
        self.assertIn('party_alert_events_below_people', codes)

    def test_non_finite_values_are_reported_in_valid_json(self):
        summary = summary_fixture()
        summary['reembolsos']['deputado']['media'] = math.inf

        audit_numbers.audit_summary_payload(summary, self.report)

        self.assertIn('non_finite_number', {issue['code'] for issue in self.report['issues']})
        json.dumps(self.report, allow_nan=False)

    def test_attendance_counts_must_add_up_to_positive_days(self):
        audit_numbers.audit_attendance_rows([
            {'id': 1, 'dias': 10, 'presente': 8, 'falta': 1, 'justificadas': 1},
            {'id': 2, 'dias': 10, 'presente': 7, 'falta': 2, 'justificadas': 0},
            {'id': 3, 'dias': 0, 'presente': 0, 'falta': 0, 'justificadas': 0},
        ], self.report)

        codes = {issue['code'] for issue in self.report['issues']}
        self.assertIn('attendance_totals_mismatch', codes)
        self.assertIn('invalid_attendance_days', codes)

    def test_mandate_cost_quota_matches_observed_reimbursement_rows(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            schema_path = Path(audit_numbers.citizen.__file__).with_name('schema.sql')
            db.executescript(schema_path.read_text(encoding='utf-8'))
            db.execute('INSERT INTO sources(id,label) VALUES(?,?)', ('camara_ceap_2026', 'Cota da Câmara'))
            db.execute('INSERT INTO authorities(id,name,role) VALUES(?,?,?)',
                       ('camara:1', 'Parlamentar Teste', 'deputado'))
            db.execute('INSERT INTO quota_categories(id,name) VALUES(?,?)', (1, 'COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA'))

            def expense(identifier, month, cents, kind='reembolso'):
                db.execute('''INSERT INTO expenses(id,authorityId,sourceId,year,month,amountCents,kind,firstSeen,lastChanged)
                              VALUES(?,?,?,?,?,?,?,?,?)''',
                           (identifier, 'camara:1', 'camara_ceap_2026', 2026, month, cents, kind, 'test', 'test'))

            def history(month, seq, cents, complement=False):
                db.execute('''INSERT INTO quota_history_notes(authorityId,year,month,seq,categoryId,amountCents,complement)
                              VALUES(?,?,?,?,?,?,?)''',
                           ('camara:1', 2026, month, seq, 1, cents, int(complement)))

            # January is stale by R$ 1; the separate housing complement must not enter its sum.
            expense('jan-reembolso', 1, 700)
            expense('jan-housing', 1, 2000, 'complemento_moradia')
            # February spans expenses and history; the signed refund remains in the result.
            expense('feb-reembolso', 2, 250)
            history(2, 1, -500)
            history(2, 2, 9000, complement=True)
            # A complement-only observed month has zero non-complement quota, not missing data.
            history(3, 1, -276313, complement=True)
            # May and June have database rows but no published numeric quota to compare.
            expense('may-reembolso', 5, 1000)
            expense('jun-reembolso', 6, 3000)

            snapshot = {'profiles': {
                'camara:1': {'id': 'camara:1', 'house': 'camara', 'months': {
                    '2026-01': {'valuesCents': {'quota': 900}},
                    '2026-02': {'valuesCents': {'quota': -250}},
                    '2026-03': {'valuesCents': {'quota': 0}},
                    '2026-04': {'valuesCents': {'quota': 0}},
                    '2026-05': {'valuesCents': {'quota': None}},
                    '2026-06': {'exercise': 'outside_mandate'},
                }},
                'senado:2': {'id': 'senado:2', 'house': 'senado', 'months': {
                    '2026-01': {'valuesCents': {'quota': 1}},
                }},
            }}
            published = audit_numbers.published_chamber_quota_rows(snapshot, self.report)
            audit_numbers.audit_chamber_quota_rows(published, db, self.report)

        result = self.report['quotaRecomposition']
        self.assertEqual(result['publishedMonths'], 4)
        self.assertEqual(result['comparedMonths'], 3)
        self.assertEqual(result['mismatchMonths'], 1)
        self.assertEqual(result['unobservedMonths'], 1)
        self.assertEqual(result['mismatchExamples'], [{
            'authorityId': 'camara:1', 'period': '2026-01', 'storedCents': 900,
            'databaseCents': 700, 'databaseReimbursementRows': 1, 'databaseObservedRows': 2,
        }])
        self.assertIn('mandate_cost_quota_mismatch', {issue['code'] for issue in self.report['issues']})
        self.assertEqual(len(self.report['skipped']), 1)
        self.assertIn('rather than treating the missing database sum as zero', self.report['skipped'][0]['message'])

    def test_scoreboard_accepts_partially_known_tally(self):
        audit_numbers.audit_tally(
            {'yes': 4, 'no': None, 'abstention': 1, 'total': 5}, self.report, 'vote.tally')

        self.assertEqual(self.report['issues'], [])

    def test_scoreboard_does_not_infer_zero_for_unknown_total(self):
        audit_numbers.audit_tally(
            {'yes': 4, 'no': 2, 'abstention': None, 'total': None}, self.report, 'vote.tally')

        self.assertEqual(self.report['issues'], [])

    def test_scoreboard_rejects_known_choices_over_known_total(self):
        audit_numbers.audit_tally(
            {'yes': 4, 'no': None, 'abstention': 2, 'total': 5}, self.report, 'vote.tally')

        self.assertIn('scoreboard_tally_exceeds_total', {issue['code'] for issue in self.report['issues']})

    def test_missing_database_fails_and_optional_snapshots_stay_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = audit_numbers.main(['--db', str(root / 'missing.sqlite3'), '--snapshots', str(root)])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('database_missing', {issue['code'] for issue in result['issues']})
        self.assertEqual(result['counts']['skipped'], len(audit_numbers.OPTIONAL_SNAPSHOTS))
        self.assertTrue(all('unavailable' in item['message'] for item in result['skipped']))

    def test_cli_uses_custom_snapshots_and_opens_database_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / 'fixture.sqlite3'
            snapshots_path = root / 'custom-snapshots'
            snapshots_path.mkdir()
            schema_path = Path(audit_numbers.citizen.__file__).with_name('schema.sql')
            with sqlite3.connect(db_path) as db:
                db.executescript(schema_path.read_text(encoding='utf-8'))
                db.execute('PRAGMA user_version = 7')
                db.execute('INSERT INTO authorities(id,name,role,party) VALUES(?,?,?,?)',
                           ('camara:1', 'Parlamentar Teste', 'deputado', 'ABC'))
                db.execute('INSERT INTO roster(sourceId,authorityId) VALUES(?,?)',
                           ('camara_deputies_current', 'camara:1'))
            db.close()
            (snapshots_path / 'mandate-cost.json').write_text(json.dumps({
                'profiles': {'camara:1': {'id': 'camara:1', 'house': 'camara',
                                          'monthlyAverageCents': 12345, 'usedMonths': ['2026-01']}}
            }), encoding='utf-8')
            (snapshots_path / 'senate-cost.json').write_text('{"profiles": {}}', encoding='utf-8')

            before = hashlib.sha256(db_path.read_bytes()).hexdigest()
            original_connect = audit_numbers._connect_read_only
            original_summary = audit_numbers.citizen.summary
            original_snapshots_path = audit_numbers.config.SNAPSHOTS_PATH
            captured_summary = {}

            def verify_read_only(path):
                db = original_connect(path)
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('CREATE TABLE forbidden_write(id INTEGER)')
                return db

            def capture_summary(db):
                result = original_summary(db)
                captured_summary.update(result)
                return result

            output = io.StringIO()
            with patch.object(audit_numbers, '_connect_read_only', side_effect=verify_read_only), \
                    patch.object(audit_numbers.citizen, 'summary', side_effect=capture_summary), \
                    contextlib.redirect_stdout(output):
                status = audit_numbers.main(['--db', str(db_path), '--snapshots', str(snapshots_path)])

            result = json.loads(output.getvalue())
            after = hashlib.sha256(db_path.read_bytes()).hexdigest()

        self.assertEqual(status, 0)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['snapshots'], str(snapshots_path))
        self.assertEqual(audit_numbers.config.SNAPSHOTS_PATH, original_snapshots_path)
        self.assertEqual(result['counts']['skipped'], 2)
        self.assertTrue(all(Path(item['location']).name in {'presenca.json', 'chamber-votes.json'}
                            for item in result['skipped']))
        self.assertTrue(all('unavailable' in item['message'] for item in result['skipped']))
        self.assertEqual(captured_summary['custoMensal']['deputado']['comCusto'], 1)
        self.assertEqual(captured_summary['custoMensal']['deputado']['media'], 123.45)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
