import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

from backend.profiles import profile
from ingest import senate_cost


def pilot_month(subsidy, reason=None, office=3_000_000, people=20, suppressed=False):
    return {'subsidyGrossCents': subsidy, 'subsidyReason': reason,
            'office': {'grossCents': office, 'people': people, 'suppressed': suppressed}}


PILOT = {
    'sources': [{'competence': p, 'url': f'https://example/{p}', 'sourceUpdatedAt': None} for p in ('2026-07', '2026-08', '2026-09')],
    'rules': {},
    'senators': [{'id': 'senado:1', 'office': 'Fulano', 'months': [
        pilot_month(None, 'lotacao_ausente', office=None, people=0),
        pilot_month(4_636_619),
        pilot_month(None, 'mais_de_uma_linha', office=None, people=2, suppressed=True),
    ]}],
}


class ExerciseTests(unittest.TestCase):
    def test_month_is_in_office_when_any_day_overlaps(self):
        intervals = [(date(2026, 7, 20), date(2026, 8, 2))]
        self.assertEqual(senate_cost.month_exercise(intervals, '2026-07'), 'em_exercicio')
        self.assertEqual(senate_cost.month_exercise(intervals, '2026-08'), 'em_exercicio')
        self.assertEqual(senate_cost.month_exercise(intervals, '2026-09'), 'fora')
        self.assertEqual(senate_cost.month_exercise([(date(2026, 9, 1), None)], '2026-10'), 'em_exercicio')
        self.assertEqual(senate_cost.month_exercise(None, '2026-09'), 'desconhecido')

    def test_intervals_come_from_every_mandate(self):
        payload = {'MandatoParlamentar': {'Parlamentar': {'Mandatos': {'Mandato': [
            {'Exercicios': {'Exercicio': {'DataInicio': '2023-02-01', 'DataFim': '2023-12-12'}}},
            {'Exercicios': {'Exercicio': [{'DataInicio': '2026-05-06'}]}}]}}}}
        self.assertEqual(senate_cost.exercise_intervals(payload), [(date(2023, 2, 1), date(2023, 12, 12)), (date(2026, 5, 6), None)])


class BuildTests(unittest.TestCase):
    def build(self, intervals):
        return senate_cost.build(PILOT, {'senado:1': 'Fulano', 'senado:2': 'Sem Gabinete'},
                                 {'senado:1': intervals, 'senado:2': intervals}, {})['profiles']

    def test_absence_is_out_of_office_only_when_the_history_confirms_it(self):
        confirmed = self.build([(date(2026, 8, 1), None)])['senado:1']['months']['2026-07']
        self.assertEqual(confirmed['remunerationReason'], 'fora_do_exercicio')
        unconfirmed = self.build(None)['senado:1']['months']['2026-07']
        self.assertEqual(unconfirmed['remunerationReason'], 'nao_identificado')
        self.assertIsNone(unconfirmed['remunerationCents'])

    def test_reasons_for_shared_office_small_team_and_no_own_office(self):
        records = self.build([(date(2026, 1, 1), None)])
        september = records['senado:1']['months']['2026-09']
        self.assertEqual((september['remunerationReason'], september['officeReason']), ('lotacao_compartilhada', 'menos_de_3'))
        self.assertEqual(records['senado:1']['months']['2026-08']['remunerationCents'], 4_636_619)
        self.assertEqual(records['senado:2']['months']['2026-08']['remunerationReason'], 'sem_lotacao_propria')

    def test_payment_outside_exercise_is_kept_and_marked(self):
        month = self.build([(date(2026, 1, 1), date(2026, 7, 31))])['senado:1']['months']['2026-08']
        self.assertEqual(month['remunerationCents'], 4_636_619)
        self.assertTrue(month['paidOutsideExercise'])


class ProfileTests(unittest.TestCase):
    def test_senate_cost_is_attached_only_to_senate_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = senate_cost.build(PILOT, {'senado:1': 'Fulano'}, {'senado:1': None}, {})
            snapshot['profiles']['camara:1'] = {**snapshot['profiles']['senado:1'], 'id': 'camara:1'}
            (root / 'senate-cost.json').write_text(json.dumps(snapshot), encoding='utf-8')
            result = profile('senado:1', root / 'perfis.json')
            self.assertEqual(result['senateCost']['months']['2026-08']['remunerationCents'], 4_636_619)
            self.assertEqual(result['senateCost']['periodStart'], '2026-07')
            self.assertIsNone(profile('camara:1', root / 'perfis.json'))


if __name__ == '__main__':
    unittest.main()
