import csv
import datetime as dt
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ingest import chamber_sigepa
from ingest.legislative import load_chamber_expenses


def analytic_page(rows, total):
    """Página analítica mínima, no formato da Câmara (tbody com as linhas e a linha de total)."""
    body = ''.join(
        f'''<tr><td>{supplier}</td><td>{tax}</td><td>
            {date}</td><td>
            {number}</td><td>{shown}</td><td></td><td id="analitico{index}">
            {shown}</td><td><a id="linkAnalitico{index}" href="/cota-parlamentar/documento?nuDeputadoId=3292&amp;
            numMes={month}&amp;
            numAno={year}&amp;
            despesa=998&amp;idDocumento={number}&amp;idDocumentoFiscal={fiscal}">detalhe</a></td></tr>'''
        for index, (supplier, tax, date, number, shown, month, year, fiscal) in enumerate(rows))
    return (f'<html><body><h1>Resultado da pesquisa</h1><table class="tabela-2"><thead><tr><th>Fornecedor</th></tr></thead>'
            f'<tbody>{body}<tr><td>Total</td><td></td><td></td><td></td><td></td><td></td><td id="totalFinalAnalitico">'
            f'{total}</td><td></td></tr></tbody></table></body></html>')


TICKETS = [
    ('LATAM Airlines Brasil', '02.012.862/0001-60', '27/06/2026', '9572293614502', 'R$3.144,45', 6, 2026, 'AC60'),
    ('Gol Linhas Aéreas', '07.575.651/0001-59', '22/06/2026', '1272306372631', 'R$2.817,38', 6, 2026, 'B1'),
    ('LATAM Airlines Brasil', '02.012.862/0001-60', '27/06/2026', '9572293614502', '(R$3.144,45)', 6, 2026, 'AC60'),
]
CSV_FIELDS = ['txNomeParlamentar', 'ideCadastro', 'sgUF', 'sgPartido', 'numSubCota', 'txtDescricao', 'txtFornecedor',
              'txtCNPJCPF', 'txtNumero', 'datEmissao', 'vlrLiquido', 'numMes', 'numAno', 'nuDeputadoId', 'ideDocumento',
              'urlDocumento']


def write_archive(path, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=';')
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, '') for field in CSV_FIELDS})
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Ano-2026.csv', buffer.getvalue())


def csv_row(month, category, amount, document, sub='1'):
    return {'txNomeParlamentar': 'Fulana', 'ideCadastro': '204398', 'sgUF': 'PR', 'sgPartido': 'X', 'numSubCota': sub,
            'txtDescricao': category, 'txtFornecedor': 'Fornecedor', 'txtCNPJCPF': '', 'txtNumero': document,
            'datEmissao': f'2026-{month:02d}-02T00:00:00', 'vlrLiquido': amount, 'numMes': str(month), 'numAno': '2026',
            'nuDeputadoId': '3292', 'ideDocumento': document}


class AnalyticPageTests(unittest.TestCase):
    def test_tickets_and_refunds_keep_sign_month_and_fiscal_id_and_close_with_the_page_total(self):
        rows = chamber_sigepa.parse_analytic(analytic_page(TICKETS, 'R$2.817,38'))
        self.assertEqual([row['amount'] for row in rows], ['3144.45', '2817.38', '-3144.45'])
        self.assertEqual(rows[0], {'year': 2026, 'month': 6, 'date': '2026-06-27', 'supplier': 'LATAM Airlines Brasil',
                                   'taxId': '02.012.862/0001-60', 'document': '9572293614502', 'amount': '3144.45',
                                   'fiscalId': 'AC60'})

    def test_empty_result_is_zero_tickets_but_an_unexpected_page_or_wrong_total_is_an_error(self):
        self.assertEqual(chamber_sigepa.parse_analytic(analytic_page([], '')), [])
        with self.assertRaises(ValueError):
            chamber_sigepa.parse_analytic('<html><body>Erro interno</body></html>')
        with self.assertRaises(ValueError):
            chamber_sigepa.parse_analytic(analytic_page(TICKETS, 'R$9.999,00'))

    def test_collection_starts_when_the_annual_file_stopped_carrying_tickets(self):
        today = dt.date(2026, 10, 19)
        self.assertIsNone(chamber_sigepa.month_range(2024, today))
        self.assertEqual(chamber_sigepa.month_range(2025, today), ((2025, 8), (2025, 12)))
        self.assertEqual(chamber_sigepa.month_range(2026, today), ((2026, 1), (2026, 10)))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.archive = self.root / 'camara-2026.csv.zip'
        write_archive(self.archive, [
            csv_row(6, 'COMBUSTÍVEIS E LUBRIFICANTES.', '100.00', 'a1'),
            # Estorno avulso que o arquivo ainda traz: a lista da página do mês o substitui, sem contar duas vezes.
            csv_row(6, 'PASSAGEM AÉREA - SIGEPA', '-50.00', 'old', sub='998'),
        ])

    def tearDown(self):
        self.directory.cleanup()

    def collect(self, page):
        return chamber_sigepa.collect(2026, self.archive, self.root, today=dt.date(2026, 10, 19),
                                      fetch=lambda url: page, attempts=1, delay=0)

    def test_page_tickets_replace_file_rows_in_covered_months_with_a_link_to_the_month_list(self):
        self.collect(analytic_page(TICKETS, 'R$2.817,38'))
        expenses, stats = load_chamber_expenses(self.archive, 2026, {}, 'camara_ceap')
        sigepa = [row for row in expenses if row['category'] == 'PASSAGEM AÉREA - SIGEPA']
        self.assertEqual(sorted(row['amount'] for row in sigepa), [-3144.45, 2817.38, 3144.45])
        self.assertEqual(round(sum(row['amount'] for row in expenses), 2), 2917.38)
        self.assertTrue(all(row['documentUrl'].startswith('https://www.camara.leg.br/cota-parlamentar/analitico?nuDeputadoId=3292')
                            and 'dataInicio=6/2026&dataFim=6/2026' in row['documentUrl'] for row in sigepa))
        self.assertEqual({row['authorityId'] for row in expenses}, {'camara:204398'})
        self.assertEqual(stats['sigepa']['rowsAdded'], 3)
        self.assertEqual(stats['sigepa']['rowsReplaced'], 1)
        self.assertEqual(len({row['id'] for row in expenses}), len(expenses))
        self.assertIn('vêm da página analítica da cota', chamber_sigepa.sigepa_detail(stats))

    def test_failed_page_keeps_the_previous_collection_and_never_turns_into_zero(self):
        self.collect(analytic_page(TICKETS, 'R$2.817,38'))
        result = self.collect('<html>Erro</html>')
        person = result['deputies']['3292']
        self.assertEqual(person['status'], 'imported')
        self.assertEqual(len(person['rows']), 3)
        self.assertIn('lastError', person)
        # Sem coleta anterior, a pessoa fica sem consulta e o arquivo anual segue como veio.
        (self.root / 'camara-sigepa-2026.json').unlink()
        result = self.collect('<html>Erro</html>')
        self.assertEqual(result['failed'], ['3292'])
        expenses, stats = load_chamber_expenses(self.archive, 2026, {}, 'camara_ceap')
        self.assertEqual(sorted(row['amount'] for row in expenses), [-50.0, 100.0])
        self.assertEqual(stats['sigepa']['rowsReplaced'], 0)

    def test_collection_is_sequential_oldest_first_and_stops_on_budget_or_repeated_failures(self):
        write_archive(self.archive, [csv_row(6, 'X', '1', 'a'), {**csv_row(6, 'X', '1', 'b'), 'ideCadastro': '9', 'nuDeputadoId': '9'}])
        seen = []

        def fetch(url):
            seen.append(url.split('nuDeputadoId=')[1].split('&')[0])
            return analytic_page([], '')
        ticks = iter([0, 0, 100, 100])
        first = chamber_sigepa.collect(2026, self.archive, self.root, today=dt.date(2026, 10, 19), fetch=fetch,
                                       attempts=1, delay=0, budget_seconds=10, clock=lambda: next(ticks))
        self.assertEqual(first['consultedThisRun'], 1)
        self.assertEqual(len(first['failed']), 1)  # o outro ficou para a próxima, sem virar zero
        chamber_sigepa.collect(2026, self.archive, self.root, today=dt.date(2026, 10, 19), fetch=fetch,
                               attempts=1, delay=0, budget_seconds=10, clock=iter([0, 0, 100, 100]).__next__)
        self.assertNotEqual(seen[0], seen[1])  # quem nunca foi consultado vai primeiro

        def blocked(url):
            raise TimeoutError('sem resposta')
        result = chamber_sigepa.collect(2026, self.archive, self.root, today=dt.date(2026, 10, 19), fetch=blocked,
                                        attempts=1, delay=0, stop_after_failures=1)
        self.assertEqual(result['consultedThisRun'], 1)
        self.assertEqual(sorted(item['status'] for item in result['deputies'].values()), ['imported', 'imported'])

    def test_analytic_error_falls_back_to_the_summary_only_when_it_proves_there_are_no_tickets(self):
        summary = ('<h1>Resultado da pesquisa</h1><table><tr><td>TELEFONIA</td><td>R$ 813,44</td></tr>'
                   '<tr><td>Total</td><td>R$ 813,44</td></tr></table>')

        def fetch(url):
            if '/analitico?' in url:
                raise OSError('HTTP Error 500')
            return summary
        result = self.collect_with(fetch)
        self.assertEqual(result['deputies']['3292']['status'], 'imported')
        self.assertEqual(result['deputies']['3292']['rows'], [])
        self.assertIn('resumo por tipo', result['deputies']['3292']['evidence'])
        (self.root / 'camara-sigepa-2026.json').unlink()
        with_tickets = summary.replace('TELEFONIA', 'PASSAGEM AÉREA - SIGEPA')
        result = self.collect_with(lambda url: (_ for _ in ()).throw(OSError('500')) if '/analitico?' in url else with_tickets)
        self.assertEqual(result['failed'], ['3292'])  # há bilhetes que não dá para listar: dado ausente

    def collect_with(self, fetch):
        return chamber_sigepa.collect(2026, self.archive, self.root, today=dt.date(2026, 10, 19), fetch=fetch,
                                      attempts=1, delay=0)

    def test_without_a_cache_the_annual_file_is_read_as_before(self):
        expenses, stats = load_chamber_expenses(self.archive, 2026, {}, 'camara_ceap')
        self.assertEqual(len(expenses), 2)
        self.assertEqual(stats['sigepa'], {'applied': False})
        self.assertEqual(chamber_sigepa.sigepa_detail(stats), '')

    def test_apply_rebuilds_chamber_rows_of_a_saved_document_and_keeps_other_sources(self):
        self.collect(analytic_page(TICKETS, 'R$2.817,38'))
        document = self.root / 'legislative.json'
        document.write_text(json.dumps({
            'sources': [{'id': 'camara_ceap', 'detail': 'Arquivo anual.'}, {'id': 'senado_ceaps', 'detail': 'Senado.'}],
            'authorities': [{'id': 'senado:1', 'name': 'S'}],
            'expenses': [{'sourceId': 'senado_ceaps', 'id': 's1', 'amount': 10}, {'sourceId': 'camara_ceap', 'id': 'velha'}],
        }), encoding='utf-8')
        chamber_sigepa.apply_to_document(document, 2026, self.root)
        chamber_sigepa.apply_to_document(document, 2026, self.root)  # reaplicar não duplica
        saved = json.loads(document.read_text(encoding='utf-8'))
        chamber = [row for row in saved['expenses'] if row['sourceId'] == 'camara_ceap']
        self.assertEqual(len(chamber), 4)
        self.assertNotIn('velha', {row['id'] for row in chamber})
        self.assertIn({'sourceId': 'senado_ceaps', 'id': 's1', 'amount': 10}, saved['expenses'])
        self.assertEqual(saved['sources'][0]['detail'].count('Passagens SIGEPA'), 1)
        self.assertEqual(saved['sources'][1]['detail'], 'Senado.')


if __name__ == '__main__':
    unittest.main()
