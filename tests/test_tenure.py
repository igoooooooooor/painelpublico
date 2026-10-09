import unittest

from ingest import tenure


def senate(*mandates):
    """mandates: (início da 1ª legislatura, fim da 2ª, [inícios de exercício])"""
    return {'MandatoParlamentar': {'Parlamentar': {'Mandatos': {'Mandato': [
        {'PrimeiraLegislaturaDoMandato': {'DataInicio': start, 'DataFim': None},
         'SegundaLegislaturaDoMandato': {'DataFim': end},
         'Exercicios': {'Exercicio': [{'DataInicio': e} for e in exercises]}} for start, end, exercises in mandates]}}}}


class SenateTenureTests(unittest.TestCase):
    def test_contiguous_mandates_count_and_a_gap_breaks_the_chain(self):
        renan = senate(('2019-02-01', '2027-01-31', ['2019-02-01']), ('2011-02-01', '2019-01-31', ['2011-02-01']),
                       ('2003-02-01', '2011-01-31', ['2003-02-01']), ('1995-02-01', '2003-01-31', ['1995-02-01']))
        self.assertEqual(tenure.senate_since(renan), '1995-02-01')
        amin = senate(('2019-02-01', '2027-01-31', ['2019-02-01']), ('1991-02-01', '1999-01-31', ['1991-02-01']))
        self.assertEqual(tenure.senate_since(amin), '2019-02-01')

    def test_substitute_counts_from_first_exercise_and_unexercised_mandates_do_not_count(self):
        self.assertEqual(tenure.senate_since(senate(('2023-02-01', '2031-01-31', ['2026-05-06', '2025-02-03']))), '2025-02-03')
        self.assertIsNone(tenure.senate_since(senate(('2023-02-01', '2031-01-31', []))))


def chamber(*entries):
    return [{'idLegislatura': leg, 'situacao': situation, 'dataHora': when, 'descricaoStatus': status}
            for leg, situation, when, status in entries]


class ChamberTenureTests(unittest.TestCase):
    def test_consecutive_legislatures_including_old_start_records(self):
        entries = chamber((57, 'Exercício', '2023-02-01T00:00', ''), (56, 'Exercício', '2019-02-01T00:00', ''),
                          (52, 'Exercício', '2003-02-01T00:00', ''), (53, 'Exercício', '2007-02-01T00:00', ''),
                          (54, 'Exercício', '2011-02-01T00:00', ''), (55, 'Exercício', '2015-02-01T00:00', ''),
                          (51, None, '2023-02-01T00:00', 'Nome no início da legislatura / Partido no início da legislatura'))
        self.assertEqual(tenure.chamber_since(entries), '1999-02-01')  # data genérica trocada pelo início da 51ª

    def test_gap_and_no_current_legislature(self):
        gap = chamber((57, 'Exercício', '2023-02-01T00:00', ''), (55, 'Exercício', '2015-02-01T00:00', ''))
        self.assertEqual(tenure.chamber_since(gap), '2023-02-01')
        self.assertIsNone(tenure.chamber_since(chamber((56, 'Exercício', '2019-02-01T00:00', ''))))
        mid_term = chamber((57, 'Exercício', '2025-04-10T00:00', ''))  # suplente que assumiu no meio
        self.assertEqual(tenure.chamber_since(mid_term), '2025-04-10')


if __name__ == '__main__':
    unittest.main()
