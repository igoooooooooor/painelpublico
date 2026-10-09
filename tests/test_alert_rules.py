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


class YearBaselinePeakTests(unittest.TestCase):
    """Base anual (regra até a v2): continua na simulação, para comparação."""
    FETCHED = {'camara_ceap': '2026-10-06T00:00:00+00:00'}

    def test_explanation_only_lists_months_that_met_every_criterion(self):
        # Abril e maio passam; junho é 1,75× a referência, mas fica abaixo da diferença mínima de R$ 10 mil.
        person = records('camara:1', 'camara_ceap', 2026, [4000, 4000, 4000, 40000, 40000, 9000])
        result = alert_rules.evaluate(person + peers('camara_ceap'), self.FETCHED, baseline='year')
        peaks = [s for s in result['signals'] if s['type'] == 'pico']
        self.assertEqual(len(peaks), 1)
        self.assertEqual([m['month'] for m in peaks[0]['detail']['months']], [4, 5])
        self.assertEqual(peaks[0]['amountCents'], 8_000_000)
        self.assertEqual(peaks[0]['detail']['ruleVersion'], alert_rules.RULE_VERSION)

    def test_series_covers_the_whole_year_with_each_month_status(self):
        # O cartão mostra o ano inteiro: depois do alerta, junho volta à referência e julho ainda está no prazo.
        person = records('camara:1', 'camara_ceap', 2026, [4000, 4000, 4000, 40000, 40000, 4000, 30000])
        result = alert_rules.evaluate(person + peers('camara_ceap', months=7), self.FETCHED, baseline='year')
        peak = next(s for s in result['signals'] if s['type'] == 'pico' and s['authorityId'] == 'camara:1')
        self.assertEqual([(p['month'], p['status']) for p in peak['detail']['series']],
                         [(1, 'historico_insuficiente'), (2, 'historico_insuficiente'), (3, 'historico_insuficiente'),
                          (4, 'flagged'), (5, 'flagged'),
                          (6, 'evaluated'), (7, 'prazo_aberto')])
        self.assertEqual(peak['detail']['series'][6]['valueCents'], 3_000_000)

    def test_year_end_months_stay_flagged_and_carry_the_context(self):
        person = records('camara:1', 'camara_ceap', 2025, [4000] * 10 + [4000, 40000])
        result = alert_rules.evaluate(person + peers('camara_ceap', year=2025, months=12), {'camara_ceap': '2026-10-06T00:00:00+00:00'}, baseline='year')
        peak = next(s for s in result['signals'] if s['type'] == 'pico')
        self.assertEqual(peak['period'], '2025-12')
        self.assertEqual(peak['detail']['yearEndMonths'], [12])
        self.assertIn('expira em 31/12', alert_rules.describe(peak))

    def test_open_months_and_gaps_are_recorded_as_not_evaluated(self):
        person = records('camara:1', 'camara_ceap', 2026, [4000, None, 4000, 40000, 40000, 4000, 4000, 4000])
        result = alert_rules.evaluate(person + peers('camara_ceap', months=8), self.FETCHED, baseline='year')
        coverage = next(c for c in result['coverage'] if c['authorityId'] == 'camara:1' and c['rule'] == 'pico')['detail']
        self.assertEqual(coverage['evaluated'], [])  # fevereiro sem notas tira a base de abril a junho
        self.assertEqual(coverage['notEvaluated']['sem_notas'], [2])
        self.assertEqual(coverage['notEvaluated']['prazo_aberto'], [7, 8])
        self.assertEqual(coverage['notEvaluated']['historico_insuficiente'], [1, 3])
        self.assertEqual(coverage['notEvaluated']['sem_base'], [4, 5, 6])

    def test_senate_months_of_the_current_year_are_not_evaluated(self):
        person = records('senado:1', 'senado_ceaps', 2026, [4000, 4000, 4000, 40000, 40000, 4000])
        result = alert_rules.evaluate(person, {'senado_ceaps': '2026-10-06T00:00:00+00:00'})
        self.assertFalse([s for s in result['signals'] if s['type'] == 'pico'])
        coverage = next(c for c in result['coverage'] if c['rule'] == 'pico')['detail']
        self.assertEqual(coverage['notEvaluated']['prazo_aberto'], [1, 2, 3, 4, 5, 6])


def mandate(authority, monthly_2023, monthly_2024, peer_value=40000):
    """Notas de fev/2023 a dez/2024 (listas começam em fevereiro e em janeiro) e colegas para o piso."""
    notes = records(authority, 'camara_ceap_2023', 2023, [None] + monthly_2023) + records(authority, 'camara_ceap_2024', 2024, monthly_2024)
    notes += [r for year, source, months in ((2023, 'camara_ceap_2023', [None] + [peer_value] * 11),
                                             (2024, 'camara_ceap_2024', [peer_value] * 12))
              for i in range(6) for r in records(f'camara:p{i}', source, year, months)]
    return notes


class RollingPeakTests(unittest.TestCase):
    """Base publicada: mediana dos 12 meses anteriores completos, atravessando o ano."""
    FETCHED = {'camara_ceap_2023': '2026-10-06T00:00:00+00:00', 'camara_ceap_2024': '2026-10-06T00:00:00+00:00'}

    def test_published_baseline_is_twelve_complete_months(self):
        self.assertEqual(alert_rules.PUBLISHED_BASELINE, 'rolling12')
        self.assertEqual(alert_rules.RULE_VERSION, 'cota-alertas-v3')

    def test_history_is_insufficient_before_february_2024(self):
        result = alert_rules.evaluate(mandate('camara:1', [4000] * 11, [4000, 50000] + [4000] * 10), self.FETCHED)
        coverage = {c['year']: c['detail'] for c in result['coverage'] if c['authorityId'] == 'camara:1' and c['rule'] == 'pico'}
        self.assertEqual(coverage[2023]['evaluated'], [])
        self.assertEqual(coverage[2023]['notEvaluated'], {'historico_insuficiente': list(range(2, 13))})  # janeiro não é do mandato
        self.assertEqual(coverage[2024]['notEvaluated'], {'historico_insuficiente': [1]})
        self.assertEqual(coverage[2024]['flagged'], [2])
        peak = next(s for s in result['signals'] if s['type'] == 'pico' and s['authorityId'] == 'camara:1')
        self.assertEqual(peak['detail']['baseline'], 'rolling12')
        self.assertEqual(peak['detail']['months'][0]['referenceCents'], 400_000)
        self.assertEqual(peak['detail']['criteria']['minPriorMonths'], 12)
        self.assertIn('12 meses anteriores', alert_rules.describe(peak))

    def test_card_series_shows_the_window_across_the_year_and_three_months_after(self):
        result = alert_rules.evaluate(mandate('camara:1', [4000] * 11, [4000] * 5 + [60000] + [4000] * 6), self.FETCHED)
        peak = next(s for s in result['signals'] if s['type'] == 'pico' and s['authorityId'] == 'camara:1')
        series = peak['detail']['series']
        self.assertEqual((series[0]['year'], series[0]['month']), (2023, 6))  # 12 meses antes de junho/2024
        self.assertEqual((series[-1]['year'], series[-1]['month']), (2024, 9))
        self.assertEqual(series[0]['status'], 'historico_insuficiente')
        self.assertEqual([p['status'] for p in series if p['year'] == 2024 and p['month'] in (5, 6, 7)],
                         ['evaluated', 'flagged', 'evaluated'])

    def test_a_month_without_notes_in_the_window_blocks_the_next_twelve(self):
        months_2023 = [4000] * 4 + [None] + [4000] * 6  # sem notas em jun/2023
        result = alert_rules.evaluate(mandate('camara:1', months_2023, [4000] * 12), self.FETCHED)
        coverage = next(c['detail'] for c in result['coverage'] if c['authorityId'] == 'camara:1' and c['rule'] == 'pico' and c['year'] == 2024)
        self.assertEqual(coverage['notEvaluated']['sem_base'], [2, 3, 4, 5, 6])
        self.assertEqual(coverage['evaluated'], list(range(7, 13)))


class TotalsTests(unittest.TestCase):
    def test_value_counts_each_record_once_and_keeps_refunds(self):
        person = records('camara:1', 'camara_ceap', 2026, [4000, 4000, 4000, 50000, 4000, 4000], supplier='cnpj:1')
        person.append({'id': 'refund', 'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2026, 'month': 4,
                       'supplierKey': 'cnpj:1', 'supplierName': 'Empresa', 'amountCents': -100_000})
        result = alert_rules.evaluate(person + peers('camara_ceap'), {'camara_ceap': '2026-10-06T00:00:00+00:00'}, baseline='year')
        types = sorted(s['type'] for s in result['signals'] if s['authorityId'] == 'camara:1')
        self.assertEqual(types, ['fornecedor', 'pico'])  # a nota de abril está nos dois alertas (base anual)
        total = result['totals']['camara:1']
        self.assertEqual(total['amountCents'], 7_000_000 - 100_000)  # o ano inteiro uma vez só, com o estorno
        self.assertTrue(total['partial'])  # a concentração de 2026 é de período parcial

    def test_closed_year_concentration_is_not_partial(self):
        person = records('camara:1', 'camara_ceap', 2025, [40000] * 12, supplier='cnpj:1')
        result = alert_rules.evaluate(person, {'camara_ceap': '2026-04-01T00:00:00+00:00'})
        concentration = next(s for s in result['signals'] if s['type'] == 'fornecedor')
        self.assertFalse(concentration['detail']['partial'])



class IntermediationTests(unittest.TestCase):
    def concentration(self, supplier_name, airline):
        notes = [{'id': f'n{m}', 'authorityId': 'senado:1', 'sourceId': 'senado_ceaps', 'year': 2025, 'month': m,
                  'supplierKey': 'cnpj:9', 'supplierName': supplier_name, 'amountCents': 5_000_00, 'airline': airline}
                 for m in range(1, 13)]
        result = alert_rules.evaluate(notes, {'senado_ceaps': '2026-06-01T00:00:00+00:00'})
        return next(s for s in result['signals'] if s['type'] == 'fornecedor')['detail']

    def test_agency_paid_for_another_airline_is_intermediation(self):
        detail = self.concentration('VITÓRIA RÉGIA', 'LATAM')
        self.assertEqual(detail['intermediation'], {'records': 12, 'airlines': ['LATAM']})
        self.assertEqual(detail['monthsWithNotes'], 12)

    def test_airline_paid_directly_or_no_evidence_is_not_intermediation(self):
        self.assertIsNone(self.concentration('TAM LINHAS AEREAS S/A', 'LATAM')['intermediation'])
        self.assertIsNone(self.concentration('AEROTUR SERVIÇOS', None)['intermediation'])


if __name__ == '__main__':
    unittest.main()
