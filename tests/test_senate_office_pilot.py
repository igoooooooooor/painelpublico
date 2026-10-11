import json
from pathlib import Path
import tempfile
import unittest

from ingest import senate_office_pilot as pilot

FIELDS = pilot.EXPECTED_FIELDS
SENTINEL = 'PRIVATE_STAFF_SENTINEL'


def row(vinculo, lotacao, gross='1000,00', folha='Normal', cargo=SENTINEL, auxilio='0'):
    values = dict.fromkeys(FIELDS, '0')
    values.update({'VÍNCULO': vinculo, 'CATEGORIA': cargo, 'CARGO': cargo, 'LOTAÇÃO EXERCÍCIO': lotacao,
                   'TIPO FOLHA': folha, 'REMUN_BASICA': gross, 'AUXÍLIOS': auxilio})
    return ';'.join(values[f] for f in FIELDS)


def csv_bytes(rows):
    return '\r\n'.join(['ÚLTIMA ATUALIZAÇÃO;30/09/2026 05:00', ';'.join(FIELDS), *rows]).encode('cp1252')


OFFICE = 'Gabinete do Senador Fulano de Tal'


def month_rows():
    return [
        row('PARLAMENTAR', OFFICE, '46.366,19', auxilio='5000,00'),
        row('PARLAMENTAR', OFFICE, '9000,00', folha='Suplementar'),
        *[row('COMISSIONADO', OFFICE, '10000,00') for _ in range(3)],
        row('COMISSIONADO', OFFICE, '7000,00', folha='Suplementar'),  # 13º de alguém que já está na folha normal
        row('EFETIVO', OFFICE, '30000,00'),  # uma pessoa só: total suprimido
        row('COMISSIONADO', 'Gabinete da Senadora Outra Pessoa', '99999,00'),
    ]


class SenateOfficePilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.map_path = Path(self.temp.name) / 'map.json'
        self.map_path.write_text(json.dumps({'offices': [
            {'id': 'senado:1', 'name': 'Fulano de Tal', 'office': 'Fulano de Tal', 'checkedAt': '2026-10-09'}]}), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def build(self, rows):
        return pilot.build(fetcher=lambda period: csv_bytes(rows), map_path=self.map_path, competences=['2026-09'])

    def test_subsidy_office_and_career_staff_are_separate_aggregates(self):
        month = self.build(month_rows())['senators'][0]['months'][0]
        self.assertEqual(month['subsidyGrossCents'], 4_636_619)
        self.assertEqual(month['subsidyOtherCents'], 500_000)  # auxílio fora do bruto
        self.assertEqual(month['senatorSupplementaryRows'], 1)
        self.assertEqual(month['office']['people'], 3)  # folha suplementar não dobra a contagem
        self.assertEqual(month['office']['grossCents'], 3_000_000)
        self.assertEqual(month['office']['supplementaryGrossCents'], 700_000)
        self.assertEqual(month['careerStaff'], {'people': 1, 'grossCents': None, 'otherCents': None,
                                                'supplementaryGrossCents': None, 'supplementaryRows': 0, 'suppressed': True})

    def test_no_staff_row_reaches_the_output(self):
        payload = json.dumps(self.build(month_rows()), ensure_ascii=False)
        self.assertNotIn(SENTINEL, payload)
        self.assertNotIn('Outra Pessoa', payload)
        self.assertNotIn('99999', payload)

    def test_missing_or_ambiguous_senator_row_is_not_zero(self):
        without = [r for r in month_rows() if not r.startswith('PARLAMENTAR;') or 'Suplementar' in r]
        self.assertEqual(self.build(without)['senators'][0]['months'][0]['subsidyGrossCents'], None)
        self.assertEqual(self.build(without)['senators'][0]['months'][0]['subsidyReason'], 'sem_linha_no_gabinete')
        doubled = month_rows() + [row('PARLAMENTAR', OFFICE, '46.366,19')]
        self.assertEqual(self.build(doubled)['senators'][0]['months'][0]['subsidyReason'], 'mais_de_uma_linha')
        absent = [row('COMISSIONADO', 'Gabinete da Senadora Outra Pessoa')]
        month = self.build(absent)['senators'][0]['months'][0]
        self.assertEqual((month['subsidyGrossCents'], month['subsidyReason'], month['office']['people']), (None, 'lotacao_ausente', 0))

    def test_unexpected_header_stops_before_reading_rows(self):
        broken = csv_bytes(month_rows()).replace(b'REMUN_BASICA', b'OUTRA_COLUNA')
        with self.assertRaises(pilot.PilotError):
            pilot.build(fetcher=lambda period: broken, map_path=self.map_path, competences=['2026-09'])

    def test_map_rejects_unchecked_or_repeated_entries(self):
        entry = {'id': 'senado:1', 'name': 'X', 'office': 'X', 'checkedAt': '2026-10-09'}
        self.map_path.write_text(json.dumps({'offices': [entry, {**entry, 'id': 'senado:2'}]}), encoding='utf-8')
        with self.assertRaises(pilot.PilotError):  # mesma lotação para duas pessoas
            pilot.load_map(self.map_path)
        self.map_path.write_text(json.dumps({'offices': [{'id': 'senado:1', 'name': 'X', 'office': 'X'}]}), encoding='utf-8')
        with self.assertRaises(pilot.PilotError):
            pilot.load_map(self.map_path)

    def test_versioned_map_covers_the_mandate_with_evidence(self):
        offices, entries = pilot.load_map()
        self.assertGreaterEqual(len(entries), 81)
        self.assertTrue(all(e['evidence'] for e in entries))
        self.assertEqual(offices['senado:5411'], 'Weverton Rocha')  # nome diferente do cadastro, conferido à mão
        self.assertEqual(pilot.COMPETENCES[0], '2023-02')

    def test_suggest_lists_only_offices_outside_the_map(self):
        rows = month_rows() + [row('PARLAMENTAR', 'Gabinete da Senadora Nova Pessoa', '46.366,19')]
        found = pilot.suggest({'senado:9': 'Nova Pessoa'}, fetcher=lambda period: csv_bytes(rows), map_path=self.map_path, periods=['2026-09'])
        self.assertEqual(found, [{'office': 'Nova Pessoa', 'months': ['2026-09'], 'exactMatches': ['senado:9']}])

if __name__ == '__main__':
    unittest.main()


class AutoAcceptTests(unittest.TestCase):
    def test_unique_exact_name_is_accepted_and_ambiguous_names_wait_for_review(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as temp:
            map_path = Path(temp) / 'map.json'
            auto_path = Path(temp) / 'auto.json'
            map_path.write_text(json.dumps({'offices': [
                {'id': 'senado:1', 'name': 'Fulano de Tal', 'office': 'Fulano de Tal', 'checkedAt': '2026-10-09'}]}), encoding='utf-8')
            rows = [row('PARLAMENTAR', OFFICE, '46.366,19'),
                    row('PARLAMENTAR', 'Gabinete da Senadora Nova Pessoa', '46.366,19'),
                    row('PARLAMENTAR', 'Gabinete do Senador Nome Repetido', '46.366,19'),
                    row('PARLAMENTAR', 'Gabinete do Senador Sem Cadastro', '46.366,19')]
            people = {'senado:1': 'Fulano de Tal', 'senado:9': 'Nova Pessoa', 'senado:10': 'Nome Repetido', 'senado:11': 'Nome Repetido'}
            accepted, review = pilot.auto_accept(people, fetcher=lambda period: csv_bytes(rows), map_path=map_path,
                                                 auto_path=auto_path, periods=['2026-09'], today=datetime(2026, 10, 11))
            self.assertEqual([(e['id'], e['office'], e['checkedAt']) for e in accepted], [('senado:9', 'Nova Pessoa', '2026-10-11')])
            self.assertEqual(sorted(item['office'] for item in review), ['Nome Repetido', 'Sem Cadastro'])
            offices, entries = pilot.load_map(map_path, auto_path)
            self.assertEqual(offices['senado:9'], 'Nova Pessoa')
            self.assertTrue(entries[-1]['auto'])
            # Segunda execução: nada novo e nenhuma duplicata.
            accepted, _ = pilot.auto_accept(people, fetcher=lambda period: csv_bytes(rows), map_path=map_path,
                                            auto_path=auto_path, periods=['2026-09'])
            self.assertEqual(accepted, [])
            self.assertEqual(len(json.loads(auto_path.read_text())['offices']), 1)
            # A tabela manual prevalece sobre uma entrada automática com o mesmo ID.
            auto_path.write_text(json.dumps({'offices': [{'id': 'senado:1', 'name': 'x', 'office': 'Outra', 'checkedAt': '2026-10-11'}]}))
            self.assertEqual(pilot.load_map(map_path, auto_path)[0], {'senado:1': 'Fulano de Tal'})
