import unittest

from backend import costs


def chamber_record(values_by_month, average=None):
    months = {period: {'valuesCents': values} for period, values in values_by_month.items()}
    return {'id': 'camara:1', 'house': 'camara', 'usedMonths': sorted(values_by_month), 'months': months,
            'monthlyAverageCents': average if average is not None else 1}


class SettledAverageTests(unittest.TestCase):
    """A média do mandato só usa meses com as notas da cota assentadas, como a ficha (profileCostAverage)."""

    def test_settled_cutoff_is_the_last_month_with_three_months_of_margin(self):
        from backend.settlement import settled_cutoff
        self.assertEqual(settled_cutoff('2026-10-13T03:17:32+00:00'), '2026-07')
        self.assertEqual(settled_cutoff('2026-02-01'), '2025-11')
        self.assertIsNone(settled_cutoff(None))
        self.assertIsNone(settled_cutoff('ontem'))

    def test_settled_periods_need_three_months_of_margin(self):
        periods = ['2026-09', '2026-07', '2026-08']
        self.assertEqual(costs.settled_periods(periods, '2026-10-13T03:17:32+00:00'), ['2026-07'])
        # Sem a data das notas não há como julgar; sem nenhum mês com folga, valem todos (a ficha avisa).
        self.assertEqual(costs.settled_periods(periods, None), ['2026-07', '2026-08', '2026-09'])
        self.assertEqual(costs.settled_periods(periods, '2026-09-01'), ['2026-07', '2026-08', '2026-09'])

    def test_chamber_average_drops_months_whose_quota_still_receives_notes(self):
        full = {'remuneration': 100, 'allowances': 0, 'quota': 50, 'office': 1000}
        record = chamber_record({'2026-06': full, '2026-07': {**full, 'quota': 51}, '2026-08': {**full, 'quota': 5}}, average=999)
        # Todos os meses assentados: vale o número do snapshot, que não muda.
        self.assertEqual(costs.chamber_average(record, '2026-12-01'), (999, ['2026-06', '2026-07', '2026-08']))
        # Ago ainda recebe notas: média de jun e jul, cada parte arredondada uma única vez no fim.
        self.assertEqual(costs.chamber_average(record, '2026-10-13'), (1150, ['2026-06', '2026-07']))
        self.assertIsNone(costs.chamber_average({**record, 'monthlyAverageCents': None}, '2026-10-13'))

    def test_chamber_gap_part_averages_only_the_months_it_was_published(self):
        full = {'remuneration': 100, 'allowances': 0, 'quota': 50, 'office': 1000}
        record = chamber_record({'2026-06': {**full, 'office': None}, '2026-07': full, '2026-09': full})
        self.assertEqual(costs.chamber_average(record, '2026-10-13'), (1150, ['2026-06', '2026-07']))

    def test_lists_use_the_same_settled_months_in_both_houses(self):
        full = {'remuneration': 100, 'allowances': 0, 'quota': 50, 'office': 1000}
        chamber = {'profiles': {'camara:1': chamber_record({'2026-07': full, '2026-09': {**full, 'quota': 0}}, average=1125)}}
        self.assertEqual(costs._chamber(chamber, '2026-10-13'), {'camara:1': {'house': 'camara', 'cents': 1150, 'months': 1}})
        month = {'remunerationCents': 100, 'officeCents': 1000}
        senate = {'profiles': {'senado:1': {'id': 'senado:1', 'months': {'2026-07': month, '2026-08': month, '2026-09': month}}}}
        quota = {('senado:1', '2026-07'): 90, ('senado:1', '2026-08'): 30, ('senado:1', '2026-09'): 10}
        self.assertEqual(costs._senate(senate, quota, '2026-10-13'), {'senado:1': {'house': 'senado', 'cents': 1190, 'months': 1}})
        self.assertEqual(costs._senate(senate, quota, None), {'senado:1': {'house': 'senado', 'cents': 1143, 'months': 3}})


if __name__ == '__main__':
    unittest.main()
