from datetime import date
import unittest

from ingest import senate_participation as participation


def vote(session, day, rows):
    return {'id': f'senado:{session}:1', 'data': day, 'rows': [[i, 'Nome', 'P', 'UF', label] for i, label in rows]}


class SessionStatusTests(unittest.TestCase):
    def test_vote_or_chair_wins_over_other_labels_in_the_same_session(self):
        self.assertEqual(participation.session_status({'Atividade parlamentar', 'Sim'}), ('participou', None))
        self.assertEqual(participation.session_status({'Presidente (art. 51 RISF)'}), ('participou', None))
        self.assertEqual(participation.session_status({'Presente – Não registrou voto', 'Licença saúde'}), ('presente_sem_voto', None))
        self.assertEqual(participation.session_status({'Licença saúde'}), ('ausencia_com_motivo', 'Licença saúde'))
        self.assertEqual(participation.session_status({'Não Compareceu'}), ('nao_compareceu', None))
        self.assertEqual(participation.session_status(set()), ('sem_registro', None))


class BuildTests(unittest.TestCase):
    def test_only_sessions_in_office_count_and_missing_rows_are_not_absences(self):
        votes = [vote(1, '2025-03-10', [('senado:1', 'Sim')]),
                 vote(2, '2025-04-10', [('senado:1', 'Missão da Casa no País/exterior')]),
                 vote(3, '2025-05-10', [('senado:2', 'Sim')]),
                 vote(4, '2026-01-10', [('senado:1', 'Não Compareceu')])]
        exercises = {'senado:1': [(date(2025, 1, 1), date(2025, 12, 31))]}
        result = participation.build(votes, ['senado:1'], exercises, {})['senado:1']
        self.assertEqual(result['sessions'], 3)  # a sessão de 2026 fica fora do exercício
        self.assertEqual(result['counts']['participou'], 1)
        self.assertEqual(result['counts']['ausencia_com_motivo'], 1)
        self.assertEqual(result['counts']['sem_registro'], 1)
        self.assertEqual(result['counts']['nao_compareceu'], 0)
        self.assertEqual(result['reasons'], {'Missão da Casa no País/exterior': 1})


if __name__ == '__main__':
    unittest.main()
