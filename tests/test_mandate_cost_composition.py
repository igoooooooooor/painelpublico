import unittest
from ingest.mandate_cost_composition import GROSS_COMPONENTS, compose_month, compose_person


class MandateCompositionTests(unittest.TestCase):
    def setUp(self):
        self.period = '2026-06'
        components = {key: 0 for key in GROSS_COMPONENTS}
        components['christmas_bonus'] = 0
        components.update(fixed_remuneration=10000, allowances=2000)
        self.parts = {
            'payroll': {self.period: {'period': self.period, 'status': 'complete', 'detailStatus': 'complete',
                'sheets': [{'period': self.period, 'componentsCents': components}]}},
            'quota': {self.period: {'period': self.period, 'status': 'available', 'amountCents': 3000,
                'housingComplementSignedCents': -1000, 'housingComplementRows': 1, 'completeSnapshot': True}},
            'office': {self.period: {'period': self.period, 'status': 'available', 'sourceStatus': 'imported', 'amountCents': 20000}},
            'housing': {self.period: {'period': self.period, 'housingAllowanceCents': 9000, 'functionalPropertyDays': 0}},
        }
        self.service = {'period': self.period, 'status': 'in_office', 'daysInOffice': 30}

    def test_single_allowance_source_and_signed_complement_exclusion(self):
        row = compose_month(self.parts, self.service, self.period)
        self.assertEqual(row['knownSumCents'], 36000)
        self.assertEqual(row['complementSignedCents'], -1000)
        self.assertTrue(row['housingDiscrepancy'])
        self.parts['housing'][self.period]['housingAllowanceCents'] = 999999
        self.assertEqual(compose_month(self.parts, self.service, self.period)['knownSumCents'], 36000)

    def test_missing_housing_never_blocks_and_negative_adjustments_stay_signed(self):
        self.parts['housing'] = {}
        self.assertTrue(compose_month(self.parts, self.service, self.period)['eligible'])
        self.parts['payroll'][self.period]['sheets'][0]['componentsCents']['daily_allowances'] = -100
        row = compose_month(self.parts, self.service, self.period)
        self.assertTrue(row['eligible'])
        self.assertEqual(row['otherPayrollCents']['daily_allowances'], -100)
        self.assertEqual(row['knownSumCents'], 36000)

    def test_unverified_quota_rowset_cannot_enter_main(self):
        self.parts['quota'][self.period]['completeSnapshot'] = False
        row = compose_month(self.parts, self.service, self.period)
        self.assertFalse(row['eligible'])
        self.assertIn('quota_snapshot_unverified', row['exclusionReasons'])

    def test_partial_office_is_not_a_complete_part(self):
        self.parts['office'][self.period]['sourceStatus'] = 'partial'
        self.assertFalse(compose_month(self.parts, self.service, self.period)['eligible'])

    def test_anonymous_inventory_is_only_a_footnote(self):
        payroll = self.parts['payroll'][self.period]
        payroll.update(status='partial', sheetCoverage={'status': 'partial', 'missingSheetTypes': ['complementar - 1']})
        row = compose_month(self.parts, self.service, self.period)
        self.assertTrue(row['eligible'])
        self.assertEqual(row['knownSumCents'], 36000)
        self.assertEqual(row['payrollInventory']['status'], 'partial')
        person = compose_person({'id': 'camara:1', 'house': 'camara', 'parts': self.parts},
                                {'months': {self.period: self.service}})
        self.assertEqual(person['payrollInventoryPartialMonths'], [self.period])

    def test_unread_individual_page_blocks_month(self):
        self.parts['payroll'][self.period]['detailStatus'] = 'unavailable'
        row = compose_month(self.parts, self.service, self.period)
        self.assertIsNone(row['knownSumCents'])
        self.assertIn('payroll_unavailable', row['exclusionReasons'])

    def test_christmas_bonus_stays_out_of_average_and_is_reported_apart(self):
        advance = {key: 0 for key in (*GROSS_COMPONENTS, 'allowances')}
        advance['christmas_bonus'] = 5000
        self.parts['payroll'][self.period]['sheets'].append({'period': self.period, 'sheetType': 'advance_christmas_bonus',
            'componentsCents': advance})
        row = compose_month(self.parts, self.service, self.period)
        self.assertEqual(row['knownSumCents'], 36000)
        self.assertEqual(row['christmasBonusCents'], 5000)
        person = compose_person({'id': 'camara:1', 'house': 'camara', 'parts': self.parts},
                                {'months': {self.period: self.service}})
        self.assertEqual(person['christmasBonus'], {'months': [self.period], 'amountCents': 5000,
                                                    'sources': [row['sources']['remuneration']]})
        self.assertEqual(person['monthlyAverageCents'], 36000)

    def test_outside_mandate_is_distinct_from_missing_and_zero(self):
        self.service['status'] = 'outside_mandate'
        row = compose_month(self.parts, self.service, self.period)
        self.assertEqual(row['exercise'], 'outside_mandate')
        self.assertFalse(row['eligible'])
        self.assertEqual(row['valuesCents']['office'], 20000)
        self.assertEqual(compose_month(self.parts, {}, self.period)['exercise'], 'unknown')

    def test_source_zero_is_eligible_but_missing_or_stale_is_not(self):
        self.parts['office'][self.period]['amountCents'] = 0
        self.assertTrue(compose_month(self.parts, self.service, self.period)['eligible'])
        self.parts['office'][self.period]['amountCents'] = None
        self.assertFalse(compose_month(self.parts, self.service, self.period)['eligible'])
        self.parts['office'][self.period].update(amountCents=100, stale=True)
        self.assertFalse(compose_month(self.parts, self.service, self.period)['eligible'])

    def test_negative_adjustment_is_kept_and_wrong_period_is_excluded(self):
        sheet = self.parts['payroll'][self.period]['sheets'][0]
        sheet['componentsCents']['other_eventual_remuneration'] = -500
        self.assertEqual(compose_month(self.parts, self.service, self.period)['knownSumCents'], 35500)
        self.parts['payroll'][self.period]['period'] = '2026-05'
        self.assertFalse(compose_month(self.parts, self.service, self.period)['eligible'])

    def test_average_only_eligible_months_no_senate_total(self):
        person = {'id': 'camara:1', 'house': 'camara', 'parts': self.parts}
        result = compose_person(person, {'months': {self.period: self.service}})
        self.assertEqual(result['usedMonths'], ['2026-06'])
        self.assertEqual(result['monthlyAverageCents'], 36000)
        self.assertEqual(result['parts']['office']['usedMonthsAverageCents'], 20000)
        self.assertIsNone(compose_person({**person, 'house': 'senado'}, {}))
        self.assertIsNone(compose_person(person, {})['monthlyAverageCents'])

class MandateSnapshotApiTests(unittest.TestCase):
    def test_profile_loads_only_approved_person_and_house(self):
        import json
        import tempfile
        from pathlib import Path
        from backend.profiles import profile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {'id': 'camara:1', 'house': 'camara', 'periodStart': '2026-01',
                      'periodEnd': '2026-07', 'monthlyAverageCents': 12000}
            (root / 'mandate-cost.json').write_text(json.dumps({'profiles': {'camara:1': record, 'senado:1': record}}))
            result = profile('camara:1', root / 'perfis.json')
            self.assertEqual(result['mandateCost']['monthlyAverageCents'], 12000)
            self.assertIsNone(profile('senado:1', root / 'perfis.json'))
            self.assertIsNone(profile('camara:2', root / 'perfis.json'))
