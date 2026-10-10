import unittest

from ingest import chamber_vote_report as report
from ingest.chamber_vote_inventory import CollectionError


def fixture(*, abstention=None, vote='Não', date='20/05/2026', method='Nominal Eletrônica',
            voter_name='João &amp; Silva', total=3, extra_row=''):
    abstention_row = '' if abstention is None else f'<tr><th>Abstenção:</th><td>{abstention}</td></tr>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Fixture</title>
    <script>ignore this unrelated script</script></head><body>
    <p>SESSÃO EXTRAORDINÁRIA Nº 097 - {date}</p>
    <p><strong>Abertura da sessão:</strong> {date} 11:55<br>
    <strong>Encerramento da sessão:</strong> {date} 22:37</p>
    <p><strong>Proposição:</strong> PL Nº 1625/2026 - SUBEMENDA SUBSTITUTIVA - {method}</p>
    <p><strong>Início da votação:</strong> {date} 21:24<br>
    <strong>Encerramento da votação:</strong> {date} 21:36</p>
    <div id="listaVotacao"><table>
      <tr><th>Sim:</th><td>2</td></tr>
      {abstention_row}
      <tr><th>Não:</th><td>1</td></tr>
      <tr><th>Total da Votação:</th><td>{total}</td></tr>
      <tr><th>Total Quorum:</th><td>{total}</td></tr>
    </table></div>
    <div id="listagem"><table><thead><tr><th>Parlamentar</th><th>UF</th><th>Voto</th></tr></thead>
      <tbody><tr><th colspan="3">Partido A</th></tr>
      <tr><td>{voter_name}</td><td>SP</td><td>Sim</td></tr>
      <tr><td>Maria D'Ávila</td><td>RJ</td><td>{vote}</td></tr>
      <tr><td colspan="3"><strong>Total Partido A: 2</strong></td></tr>
      <tr><th colspan="3">Partido B</th></tr>
      <tr><td>Úrsula Nunes</td><td>MG</td><td>Sim</td></tr>
      <tr><td colspan="3"><strong>Total Partido B: 1</strong></td></tr>
      {extra_row}
    </table></div>
    <table id="orientacao"><tr><td>Wrong Person</td><td>ZZ</td><td>Talvez</td></tr></table>
    <footer>Orientação da liderança: Talvez; não é voto nominal.</footer></body></html>'''


class ChamberVoteReportTests(unittest.TestCase):
    def test_parses_official_table_shape_and_ignores_orientation_and_footer(self):
        parsed = report.parse_roll_call(fixture())
        self.assertEqual(parsed['date'], '2026-05-20')
        self.assertEqual(parsed['proposition'], {'type': 'PL', 'number': 1625, 'year': 2026})
        self.assertEqual(parsed['object'], 'SUBEMENDA SUBSTITUTIVA')
        self.assertEqual(parsed['endedAt'], '2026-05-20T21:36')
        self.assertEqual(parsed['tally'], {'yes': 2, 'no': 1, 'abstention': None, 'total': 3})
        self.assertEqual([row['name'] for row in parsed['participants']],
                         ['João & Silva', "Maria D'Ávila", 'Úrsula Nunes'])
        self.assertEqual([row['party'] for row in parsed['participants']],
                         ['Partido A', 'Partido A', 'Partido B'])

    def test_keeps_absent_abstention_distinct_from_explicit_zero(self):
        absent = report.parse_roll_call(fixture())['tally']['abstention']
        zero = report.parse_roll_call(fixture(abstention=0))['tally']['abstention']
        self.assertIsNone(absent)
        self.assertEqual(zero, 0)

    def test_decodes_latin1_and_html_entities(self):
        source = fixture().replace('<meta charset="utf-8">', '<meta charset="iso-8859-1">')
        parsed = report.parse_roll_call(source.encode('iso-8859-1'))
        self.assertEqual(parsed['participants'][0]['name'], 'João & Silva')
        self.assertEqual(parsed['participants'][2]['name'], 'Úrsula Nunes')

    def test_rejects_symbolic_method_and_date_mismatch(self):
        with self.assertRaises(CollectionError):
            report.parse_roll_call(fixture(method='Simbólica'))
        with self.assertRaisesRegex(CollectionError, 'Data divergente'):
            report.parse_roll_call(fixture(date='21/05/2026').replace(
                'Encerramento da votação:</strong> 21/05/2026',
                'Encerramento da votação:</strong> 20/05/2026'))

    def test_accepts_session_and_vote_after_midnight_dated_by_the_opening(self):
        source = (fixture()
                  .replace('Encerramento da sessão:</strong> 20/05/2026 22:37',
                           'Encerramento da sessão:</strong> 21/05/2026 00:40')
                  .replace('Início da votação:</strong> 20/05/2026 21:24', 'Início da votação:</strong> 21/05/2026 00:24')
                  .replace('Encerramento da votação:</strong> 20/05/2026 21:36',
                           'Encerramento da votação:</strong> 21/05/2026 00:39'))
        parsed = report.parse_roll_call(source)
        self.assertEqual(parsed['date'], '2026-05-20')
        self.assertEqual(parsed['endedAt'], '2026-05-21T00:39')
        with self.assertRaisesRegex(CollectionError, 'Data divergente'):
            report.parse_roll_call(source.replace('Encerramento da sessão:</strong> 21/05/2026',
                                                  'Encerramento da sessão:</strong> 22/05/2026'))
        with self.assertRaisesRegex(CollectionError, 'fora do horário da sessão'):
            report.parse_roll_call(fixture().replace('Encerramento da sessão:</strong> 20/05/2026 22:37',
                                                     'Encerramento da sessão:</strong> 20/05/2026 21:30'))

    def test_unanimous_report_without_no_row_derives_zero_only_from_the_total(self):
        source = (fixture(vote='Sim').replace('<tr><th>Não:</th><td>1</td></tr>', '')
                  .replace('<tr><th>Sim:</th><td>2</td></tr>', '<tr><th>Sim:</th><td>3</td></tr>'))
        parsed = report.parse_roll_call(source)
        self.assertEqual(parsed['tally'], {'yes': 3, 'no': 0, 'abstention': None, 'total': 3})
        with self.assertRaisesRegex(CollectionError, 'Contagem de Não ausente'):
            report.parse_roll_call(fixture().replace('<tr><th>Não:</th><td>1</td></tr>', ''))

    def test_rejects_malformed_voter_rows_unknown_choices_and_duplicate_names(self):
        malformed = fixture(extra_row='<tr><td>Incomplete</td><td>SP</td></tr>')
        with self.assertRaises(CollectionError):
            report.parse_roll_call(malformed)
        with self.assertRaisesRegex(CollectionError, 'opção de voto inválida'):
            report.parse_roll_call(fixture(vote='Talvez'))
        duplicate = fixture(extra_row=(
            '<tr><th colspan="3">Partido C</th></tr>'
            '<tr><td>João &amp; Silva</td><td>SP</td><td>Não</td></tr>'
            '<tr><td colspan="3">Total Partido C: 1</td></tr>'))
        with self.assertRaisesRegex(CollectionError, 'duplicado'):
            report.parse_roll_call(duplicate.replace('Total da Votação:</th><td>3',
                                                     'Total da Votação:</th><td>4')
                                      .replace('Total Quorum:</th><td>3',
                                               'Total Quorum:</th><td>4'))

    def test_requires_unique_counts_and_reconciled_tally(self):
        duplicate_count = fixture().replace(
            '<tr><th>Não:</th><td>1</td></tr>',
            '<tr><th>Não:</th><td>1</td></tr><tr><th>Não:</th><td>1</td></tr>')
        with self.assertRaisesRegex(CollectionError, 'duplicada'):
            report.parse_roll_call(duplicate_count)
        with self.assertRaisesRegex(CollectionError, 'diverge'):
            report.parse_roll_call(fixture(total=4))

    def test_presiding_and_obstruction_rows_do_not_inflate_tally_total(self):
        special_rows = (
            '<tr><th colspan="3">Partido C</th></tr>'
            '<tr><td>Deputada Presidente</td><td>DF</td><td>Art. 17</td></tr>'
            '<tr><td colspan="3">Total Partido C: 1</td></tr>'
            '<tr><th colspan="3">Partido D</th></tr>'
            '<tr><td>Deputado em Obstrução</td><td>DF</td><td>Obstrução</td></tr>'
            '<tr><td colspan="3">Total Partido D: 1</td></tr>')
        parsed = report.parse_roll_call(fixture(extra_row=special_rows))
        self.assertEqual(len(parsed['participants']), 5)
        self.assertEqual(parsed['tally']['total'], 3)
        self.assertEqual([row['vote'] for row in parsed['participants'][-2:]],
                         ['Artigo 17', 'Obstrução'])

    def test_maps_only_exact_normalized_name_and_uf_to_a_unique_deputy_id(self):
        rows = [{'name': 'João   & Silva', 'uf': 'SP', 'party': 'Partido A', 'vote': 'Sim'}]
        deputies = [
            {'id': 101, 'nome': 'JOAO & SILVA', 'siglaUf': 'SP'},
            {'id': 102, 'nome': "Maria D'Ávila", 'siglaUf': 'RJ'},
        ]
        matched = report.identify_participants(rows, deputies)
        self.assertEqual(matched, [{
            'deputado_': {'id': 101, 'nome': 'João   & Silva',
                          'siglaPartido': 'Partido A', 'siglaUf': 'SP'},
            'tipoVoto': 'Sim',
        }])
        with self.assertRaisesRegex(CollectionError, 'não encontrado'):
            report.identify_participants(
                [{'name': 'João & Silva Junior', 'uf': 'SP', 'party': 'A', 'vote': 'Sim'}], deputies)
        ambiguous = deputies + [{'id': 103, 'nome': 'João & Silva', 'siglaUf': 'SP'}]
        with self.assertRaisesRegex(CollectionError, 'ambígua'):
            report.identify_participants(rows, ambiguous)
        repeated_report = rows + [{**rows[0], 'vote': 'Não'}]
        with self.assertRaisesRegex(CollectionError, 'duplicado'):
            report.identify_participants(repeated_report, deputies)


if __name__ == '__main__':
    unittest.main()
