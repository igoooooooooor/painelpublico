import unittest
from xml.etree import ElementTree as ET

from ingest.legislative import (
    add_senado_expense_authorities,
    senate_exercise_status,
    senate_roster_detail,
    senate_xml_authorities,
)


SOURCE_ID = 'senado_senators_current'
SOURCE_URL = 'https://legis.senado.leg.br/dadosabertos/senador/lista/atual'


def exercise(start, end=None, reason=None):
    item = ET.Element('Exercicio')
    for key, value in (('DataInicio', start), ('DataFim', end),
                       ('DescricaoCausaAfastamento', reason)):
        if value is not None:
            ET.SubElement(item, key).text = value
    return item


def senator(code='1', uf=None, mandate_uf='MA', participation='2º Suplente', intervals=()):
    item = ET.Element('Parlamentar')
    info = ET.SubElement(item, 'IdentificacaoParlamentar')
    for key, value in (('CodigoParlamentar', code), ('NomeParlamentar', f'Pessoa {code}'),
                       ('UfParlamentar', uf), ('SiglaPartidoParlamentar', 'TESTE')):
        if value is not None:
            ET.SubElement(info, key).text = value
    mandate = ET.SubElement(item, 'Mandato')
    for key, value in (('UfParlamentar', mandate_uf), ('DescricaoParticipacao', participation)):
        if value is not None:
            ET.SubElement(mandate, key).text = value
    ET.SubElement(mandate, 'Exercicios').extend(intervals)
    return item


def roster(*items):
    root = ET.Element('ListaParlamentarEmExercicio')
    metadata = ET.SubElement(root, 'Metadados')
    ET.SubElement(metadata, 'Versao').text = '06/10/2026 19:19:34'
    ET.SubElement(root, 'Parlamentares').extend(items)
    return senate_xml_authorities(ET.tostring(root), SOURCE_ID, SOURCE_URL)


class SenateRosterTests(unittest.TestCase):
    def test_transition_keeps_both_people_and_their_source_metadata(self):
        ended = senator(intervals=[exercise('2026-08-05', '2026-10-06', 'Retorno do titular')])
        returned = senator(code='2', participation='1º Suplente', intervals=[exercise('2026-10-06')])
        rows, version = roster(ended, returned)
        self.assertEqual([row['id'] for row in rows], ['senado:1', 'senado:2'])
        self.assertEqual(version, '06/10/2026 19:19:34')
        self.assertEqual(rows[0]['uf'], 'MA')
        self.assertEqual(rows[0]['position'], '2º Suplente')
        self.assertEqual(rows[0]['employmentStatus'],
                         'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular')
        self.assertEqual(rows[1]['employmentStatus'],
                         'Exercício sem término informado desde 06/10/2026')
        self.assertTrue(all(row['sourceId'] == SOURCE_ID for row in rows))
        detail = senate_roster_detail(rows, version)
        self.assertIn('2 registros do Senado', detail)
        self.assertIn('Registros não equivalem a cadeiras', detail)

    def test_uf_prefers_identification_then_mandate_and_keeps_missing_as_none(self):
        for uf, mandate_uf, expected in [(' SP ', 'MA', 'SP'), (' ', ' MA ', 'MA'),
                                         (None, None, None)]:
            with self.subTest(uf=uf, mandate_uf=mandate_uf):
                rows, _ = roster(senator(uf=uf, mandate_uf=mandate_uf, participation=None))
                self.assertEqual(rows[0]['uf'], expected)
                self.assertIsNone(rows[0]['position'])
                self.assertIsNone(rows[0]['employmentStatus'])

    def test_latest_exercise_is_selected_by_date_not_source_order(self):
        old = exercise('2023-02-02', '2024-01-31', 'Retorno do titular')
        new = exercise('2026-10-06')
        for intervals in ([old, new], [new, old]):
            self.assertEqual(senate_exercise_status(senator(intervals=intervals)),
                             'Exercício sem término informado desde 06/10/2026')

    def test_missing_invalid_or_conflicting_intervals_do_not_establish_status(self):
        cases = [[], [exercise(None)], [exercise('inválida')],
                 [exercise('2026-10-06', '2026-02-30')],
                 [exercise('2026-10-06', '2026-10-05')],
                 [exercise('2026-10-06'), exercise(None, '2026-10-06')],
                 [exercise('2026-10-06'), exercise('2026-10-06', '2026-10-07')]]
        for intervals in cases:
            with self.subTest(intervals=[ET.tostring(item) for item in intervals]):
                self.assertIsNone(senate_exercise_status(senator(intervals=intervals)))

    def test_expense_metadata_does_not_overwrite_roster_or_drop_former_senators(self):
        rows, _ = roster(senator(intervals=[exercise('2026-08-05', '2026-10-06')]))
        authorities = {row['id']: row for row in rows}
        original = dict(authorities['senado:1'])
        add_senado_expense_authorities(
            [{'codSenador': 1, 'nomeSenador': 'Nome da despesa'},
             {'codSenador': 3, 'nomeSenador': 'Pessoa histórica'}],
            authorities, 'senado_ceaps', SOURCE_URL,
        )
        self.assertEqual(authorities['senado:1'], original)
        self.assertEqual(authorities['senado:3']['sourceId'], 'senado_ceaps')
        self.assertNotIn('employmentStatus', authorities['senado:3'])

    def test_empty_source_is_a_failed_collection(self):
        with self.assertRaisesRegex(ValueError, 'no senators'):
            roster()


if __name__ == '__main__':
    unittest.main()
