import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import alert_rules


def records(authority, source, year, monthly, supplier=None):
    """Uma nota por mês, com valores em reais; supplier opcional para todas."""
    return [{'id': f'{authority}:{year}:{month}', 'authorityId': authority, 'sourceId': source, 'year': year, 'month': month,
             'supplierKey': supplier or f'{authority}:{month}', 'supplierName': 'Empresa', 'amountCents': round(value * 100)}
            for month, value in enumerate(monthly, 1) if value is not None]


def peers(source, year=2026, months=6, value=40000):
    return [r for i in range(6) for r in records(f'camara:p{i}', source, year, [value] * months)]


class ClosingTests(unittest.TestCase):
    def test_chamber_needs_ninety_days_after_the_end_of_the_month(self):
        self.assertFalse(alert_rules.month_closed('camara_ceap', 2026, 6, '2026-09-27T23:00:00+00:00'))
        self.assertTrue(alert_rules.month_closed('camara_ceap', 2026, 6, '2026-09-28T00:00:00+00:00'))
        self.assertFalse(alert_rules.month_closed('camara_ceap', 2026, 6, None))

    def test_senate_waits_for_the_end_of_april_of_the_next_year(self):
        self.assertFalse(alert_rules.month_closed('senado_ceaps', 2026, 1, '2027-04-30T12:00:00+00:00'))
        self.assertTrue(alert_rules.month_closed('senado_ceaps', 2026, 1, '2027-05-01T00:00:00+00:00'))


class PeakTests(unittest.TestCase):
    FETCHED = {'camara_ceap': '2026-10-06T00:00:00+00:00'}

    def test_explanation_only_lists_months_that_met_every_criterion(self):
        # Abril e maio passam; junho é 1,75× a referência, mas fica abaixo da diferença mínima de R$ 10 mil.
        person = records('camara:1', 'camara_ceap', 2026, [4000, 4000, 4000, 40000, 40000, 9000])
        result = alert_rules.evaluate(person + peers('camara_ceap'), self.FETCHED)
        peaks = [s for s in result['signals'] if s['type'] == 'pico']
        self.assertEqual(len(peaks), 1)
        self.assertEqual([m['month'] for m in peaks[0]['detail']['months']], [4, 5])
        self.assertEqual(peaks[0]['amountCents'], 8_000_000)
        self.assertEqual(peaks[0]['detail']['ruleVersion'], alert_rules.RULE_VERSION)

    def test_year_end_months_stay_flagged_and_carry_the_context(self):
        person = records('camara:1', 'camara_ceap', 2025, [4000] * 10 + [4000, 40000])
        result = alert_rules.evaluate(person + peers('camara_ceap', year=2025, months=12), {'camara_ceap': '2026-10-06T00:00:00+00:00'})
        peak = next(s for s in result['signals'] if s['type'] == 'pico')
        self.assertEqual(peak['period'], '2025-12')
        self.assertEqual(peak['detail']['yearEndMonths'], [12])
        self.assertIn('expira em 31/12', alert_rules.describe(peak))

    def test_open_months_and_gaps_are_recorded_as_not_evaluated(self):
        person = records('camara:1', 'camara_ceap', 2026, [4000, None, 4000, 40000, 40000, 4000, 4000, 4000])
        result = alert_rules.evaluate(person + peers('camara_ceap', months=8), self.FETCHED)
        coverage = next(c for c in result['coverage'] if c['authorityId'] == 'camara:1' and c['rule'] == 'pico')['detail']
        self.assertEqual(coverage['evaluated'], [])  # fevereiro sem notas tira a base de abril a junho
        self.assertEqual(coverage['notEvaluated']['sem_notas'], [2])
        self.assertEqual(coverage['notEvaluated']['prazo_aberto'], [7, 8])
        self.assertEqual(coverage['notEvaluated']['sem_base'], [1, 3, 4, 5, 6])

    def test_senate_months_of_the_current_year_are_not_evaluated(self):
        person = records('senado:1', 'senado_ceaps', 2026, [4000, 4000, 4000, 40000, 40000, 4000])
        result = alert_rules.evaluate(person, {'senado_ceaps': '2026-10-06T00:00:00+00:00'})
        self.assertFalse([s for s in result['signals'] if s['type'] == 'pico'])
        coverage = next(c for c in result['coverage'] if c['rule'] == 'pico')['detail']
        self.assertEqual(coverage['notEvaluated']['prazo_aberto'], [1, 2, 3, 4, 5, 6])


class TotalsTests(unittest.TestCase):
    def test_value_counts_each_record_once_and_keeps_refunds(self):
        person = records('camara:1', 'camara_ceap', 2026, [4000, 4000, 4000, 50000, 4000, 4000], supplier='cnpj:1')
        person.append({'id': 'refund', 'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2026, 'month': 4,
                       'supplierKey': 'cnpj:1', 'supplierName': 'Empresa', 'amountCents': -100_000})
        result = alert_rules.evaluate(person + peers('camara_ceap'), {'camara_ceap': '2026-10-06T00:00:00+00:00'})
        types = sorted(s['type'] for s in result['signals'] if s['authorityId'] == 'camara:1')
        self.assertEqual(types, ['fornecedor', 'pico'])  # a nota de abril está nos dois alertas
        total = result['totals']['camara:1']
        self.assertEqual(total['amountCents'], 7_000_000 - 100_000)  # o ano inteiro uma vez só, com o estorno
        self.assertTrue(total['partial'])  # a concentração de 2026 é de período parcial

    def test_closed_year_concentration_is_not_partial(self):
        person = records('camara:1', 'camara_ceap', 2025, [40000] * 12, supplier='cnpj:1')
        result = alert_rules.evaluate(person, {'camara_ceap': '2026-04-01T00:00:00+00:00'})
        concentration = next(s for s in result['signals'] if s['type'] == 'fornecedor')
        self.assertFalse(concentration['detail']['partial'])


if __name__ == '__main__':
    unittest.main()
