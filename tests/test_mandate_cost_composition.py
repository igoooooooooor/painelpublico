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

class MandatePeriodTests(unittest.TestCase):
    def setUp(self):
        components = {key: 0 for key in GROSS_COMPONENTS}
        components.update(fixed_remuneration=10000, allowances=2000)
        self.parts = {'payroll': {}, 'quota': {}, 'office': {}, 'housing': {}}
        self.service = {}
        for period, office in (('2024-11', 20000), ('2024-12', None)):
            self.parts['payroll'][period] = {'period': period, 'status': 'complete', 'detailStatus': 'complete',
                                             'sheets': [{'period': period, 'componentsCents': components}]}
            self.parts['quota'][period] = {'period': period, 'status': 'available', 'amountCents': 4000,
                                           'housingComplementRows': 0, 'completeSnapshot': True}
            if office is not None:
                self.parts['office'][period] = {'period': period, 'status': 'available',
                                                'sourceStatus': 'imported', 'amountCents': office}
            self.service[period] = {'period': period, 'status': 'in_office', 'daysInOffice': 30}

    def test_period_covers_the_mandate_until_july_2026(self):
        from ingest.mandate_cost_composition import PERIODS
        self.assertEqual((PERIODS[0], PERIODS[-1], len(PERIODS)), ('2023-02', '2026-07', 42))

    def test_confirmed_office_gap_keeps_the_month_with_the_part_empty(self):
        row = compose_month(self.parts, self.service['2024-12'], '2024-12')
        self.assertTrue(row['eligible'])
        self.assertEqual(row['sourceGaps'], ['office'])
        self.assertIsNone(row['valuesCents']['office'])
        person = compose_person({'id': 'camara:1', 'house': 'camara', 'parts': self.parts}, {'months': self.service})
        self.assertEqual(person['usedMonths'], ['2024-11', '2024-12'])
        self.assertEqual(person['sourceGapMonths'], {'2024-12': ['office']})
        # O gabinete usa só nov/2024; as outras partes usam os dois meses. Nada vira zero.
        self.assertEqual(person['parts']['office']['usedMonthsAverageCents'], 20000)
        self.assertEqual(person['monthlyAverageCents'], 10000 + 2000 + 4000 + 20000)

    def test_unconfirmed_office_gap_still_blocks_the_month(self):
        del self.parts['office']['2024-11']
        self.assertFalse(compose_month(self.parts, self.service['2024-11'], '2024-11')['eligible'])

    def test_history_quota_sums_cents_and_keeps_the_complement(self):
        import json
        import tempfile
        from pathlib import Path
        from ingest.mandate_cost_composition import history_quota
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data/imports').mkdir(parents=True)
            rows = [{'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2023, 'month': 3, 'amount': 10.1,
                     'category': 'X'},
                    {'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2023, 'month': 3, 'amount': -5.0,
                     'category': 'COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA'}]
            (root / 'data/imports/legislative-2023.json').write_text(json.dumps({
                'sources': [{'id': 'camara_ceap', 'status': 'imported', 'url': 'u'}], 'expenses': rows}))
            month = history_quota(root, 2023)['camara:1']['2023-03']
        self.assertEqual(month['amountCents'], 510)
        self.assertEqual(month['housingComplementSignedCents'], -500)
        self.assertTrue(month['completeSnapshot'])


class MandateSnapshotApiTests(unittest.TestCase):
    def test_profile_loads_only_approved_person_and_house(self):
        import json
        import tempfile
        from pathlib import Path
        from backend.profiles import profile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {'id': 'camara:1', 'house': 'camara', 'periodStart': '2023-02',
                      'periodEnd': '2026-07', 'monthlyAverageCents': 12000}
            (root / 'mandate-cost.json').write_text(json.dumps({'profiles': {'camara:1': record, 'senado:1': record}}))
            result = profile('camara:1', root / 'perfis.json')
            self.assertEqual(result['mandateCost']['monthlyAverageCents'], 12000)
            self.assertIsNone(profile('senado:1', root / 'perfis.json'))
            self.assertIsNone(profile('camara:2', root / 'perfis.json'))
