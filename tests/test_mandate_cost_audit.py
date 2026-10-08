import unittest
import sqlite3
import tempfile
from pathlib import Path

from ingest.mandate_cost_audit import cents, common_months, comparable, housing_overlap, existing_parts, COMPLEMENT_CATEGORY, observed_payroll_components


class MandateCostAuditTests(unittest.TestCase):
    @staticmethod
    def observation(value, **extra):
        return {'status': 'available', 'amountCents': value, 'period': '2026-01', **extra}

    def test_money_preserves_source_zero_and_missing(self):
        self.assertEqual(cents('0'), 0)
        self.assertEqual(cents('4253.00'), 425300)
        self.assertEqual(cents('-1747'), -174700)
        for value in (None, True, 'NaN', 'missing', '0.001'):
            self.assertIsNone(cents(value))

    def test_common_period_is_intersection_not_union_or_maximum(self):
        parts = {'quota': {f'2026-{m:02d}': self.observation(10, period=f'2026-{m:02d}') for m in range(1, 10)},
                 'office': {f'2026-{m:02d}': self.observation(0, period=f'2026-{m:02d}') for m in range(1, 8)}}
        del parts['office']['2026-04']
        self.assertEqual(common_months(parts, ['quota', 'office']),
                         ['2026-01', '2026-02', '2026-03', '2026-05', '2026-06', '2026-07'])
        self.assertEqual(common_months(parts, ['quota', 'office', 'payroll']), [])
        parts['office']['2026-01']['stale'] = True
        self.assertNotIn('2026-01', common_months(parts, ['quota', 'office']))

    def test_observed_supplements_are_kept_separate_from_completeness(self):
        observation = {'period': '2026-01', 'status': 'partial', 'sheets': [
            {'period': '2026-01', 'componentsCents': {'allowances': 0, 'salary': 100}},
            {'period': '2026-01', 'componentsCents': {'allowances': 20}}]}
        self.assertEqual(observed_payroll_components(observation), {'allowances': 20, 'salary': None})
        observation['sheets'][1]['period'] = '2026-02'
        self.assertEqual(observed_payroll_components(observation), {})

    def test_declared_period_must_match_map_key(self):
        parts = {'quota': {'2026-02': self.observation(10, period='2026-01')}}
        self.assertEqual(common_months(parts, ['quota']), [])

    def test_existing_sources_preserve_negative_zero_and_reject_mixed_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            db = sqlite3.connect(path)
            db.executescript("""CREATE TABLE authorities(id,name,role);
                CREATE TABLE roster(authorityId);
                CREATE TABLE sources(id,url,fetchedAt);
                CREATE TABLE expenses(authorityId,month,sourceId,amountCents,category,year,kind);
                INSERT INTO authorities VALUES ('camara:1','Exemplo','deputado');
                INSERT INTO roster VALUES ('camara:1');
                INSERT INTO sources VALUES ('camara_ceap','https://example.gov/source','2026-10-06');""")
            for month, value, category in [(1, -100, COMPLEMENT_CATEGORY), (2, 0, COMPLEMENT_CATEGORY), (3, 50, 'OTHER')]:
                db.execute('INSERT INTO expenses VALUES (?,?,?,?,?,?,?)',
                           ('camara:1', month, 'camara_ceap', value, category, 2026, 'reembolso'))
            db.commit()
            parts = existing_parts(path, {}, 2026, [1, 2, 3, 4])['camara:1']['parts']['quota']
            self.assertEqual(parts['2026-01']['housingComplementSignedCents'], -100)
            self.assertEqual(parts['2026-02']['housingComplementSignedCents'], 0)
            self.assertIsNone(parts['2026-03']['housingComplementSignedCents'])
            self.assertIsNone(parts['2026-04']['amountCents'])
            self.assertEqual(parts['2026-01']['sourceUrl'], 'https://example.gov/source')
            self.assertEqual(parts['2026-01']['fetchedAt'], '2026-10-06')
            db.execute("INSERT INTO expenses VALUES ('camara:1',1,'other_source',999,'OTHER',2026,'reembolso')")
            db.commit()
            conflicted = existing_parts(path, {}, 2026, [1])['camara:1']['parts']['quota']['2026-01']
            self.assertTrue(conflicted['sourceConflict'])
            self.assertIsNone(conflicted['amountCents'])
            db.close()

    def test_overlap_checks_numbers_and_periods_without_netting_source_signs(self):
        payroll = {'period': '2026-01', 'allowancesCents': 600000}
        housing = {'period': '2026-01', 'housingAllowanceCents': 425300, 'quotaComplementCents': 174700}
        quota = {'period': '2026-01', 'housingComplementSignedCents': -174700}
        result = housing_overlap(payroll, housing, quota)
        self.assertTrue(result['payrollEqualsAllowancePlusComplement'])
        self.assertTrue(result['quotaComplementOppositeSign'])
        self.assertFalse(result['automaticDeduplication'])
        quota['period'] = '2026-02'
        self.assertEqual(housing_overlap(payroll, housing, quota)['status'], 'unavailable')
        quota['period'] = '2026-01'
        housing['housingAllowanceCents'] = None
        self.assertEqual(housing_overlap(payroll, housing, quota)['status'], 'unavailable')

    def test_no_cross_house_comparison_even_with_same_components(self):
        left = {'house': 'camara', 'parts': {'quota': {'2026-01': self.observation(0)}}}
        right = {'house': 'senado', 'parts': left['parts']}
        self.assertFalse(comparable(left, right, ['quota']))
        right['house'] = 'camara'
        self.assertTrue(comparable(left, right, ['quota']))
        self.assertFalse(comparable(left, right, ['quota', 'office']))
        right['parts'] = {'quota': {'2026-02': self.observation(100)}}
        self.assertFalse(comparable(left, right, ['quota']))


if __name__ == '__main__':
    unittest.main()
