import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import citizen, public_store as store
from backend.quota_history import import_history
from ingest.chamber_quota_history import build_year


def history_payload():
    """Arquivo anual no formato de ingest/legislative.py."""
    rows = []
    for month, amount, category in ((1, 999.0, 'Escritório'), (2, 100.0, 'Escritório'), (3, 300.0, 'Divulgação'),
                                    (3, -50.0, 'COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA')):
        rows.append({'id': f'h:{month}:{amount}', 'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2023,
                     'month': month, 'date': f'2023-{month:02d}-10', 'category': category, 'amount': amount,
                     'kind': 'reembolso', 'documentUrl': 'https://example.gov.br/n.pdf',
                     'supplier': {'key': 'k', 'name': 'Gráfica', 'cnpj': '12345678000199'}})
    rows.append({**rows[1], 'id': 'h:old', 'authorityId': 'camara:9'})
    return {
        'sources': [{'id': 'camara_ceap', 'label': 'Câmara: CEAP', 'status': 'imported', 'url': 'https://example.gov.br/2023.zip'},
                    {'id': 'senado_ceaps', 'label': 'Senado', 'status': 'imported'}],
        'authorities': [{'id': 'camara:1', 'name': 'Ana', 'role': 'deputado', 'sourceId': 'camara_deputies_current'},
                        {'id': 'camara:9', 'name': 'Quem saiu', 'role': 'deputado', 'sourceId': 'camara_ceap'}],
        'expenses': rows + [{**rows[1], 'id': 's:1', 'authorityId': 'senado:1', 'sourceId': 'senado_ceaps'}],
    }


class QuotaHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'test.sqlite3'
        self.current = {
            'sources': [{'id': 'camara_deputies_current', 'label': 'Lista', 'status': 'imported'},
                        {'id': 'camara_ceap', 'label': 'Câmara: CEAP', 'status': 'imported', 'period': '2026'}],
            'authorities': [{'id': 'camara:1', 'name': 'Ana', 'role': 'deputado', 'sourceId': 'camara_deputies_current'}],
            'expenses': [{'id': 'c:1', 'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2026, 'month': 1,
                          'date': '2026-01-05', 'category': 'Escritório', 'amount': 200.0, 'kind': 'reembolso',
                          'supplier': {'key': 'k', 'name': 'Gráfica', 'cnpj': '12345678000199'}}],
        }
        self.import_current()
        history = self.root / 'camara-ceap-2023.json'
        history.write_text(json.dumps(build_year(history_payload(), 2023)))
        import_history([history], self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def import_current(self):
        path = self.root / 'legislative.json'
        path.write_text(json.dumps(self.current))
        store.import_documents([path], self.db_path)

    def test_aggregates_start_in_february_2023_and_leave_out_the_senate(self):
        result = build_year(history_payload(), 2023)
        self.assertEqual(result['source']['id'], 'camara_ceap_2023')
        self.assertEqual({row['month'] for row in result['months']}, {2, 3})
        self.assertFalse(any(row['authorityId'].startswith('senado') for row in result['months']))
        kinds = {(row['category'], row['kind']) for row in result['months']}
        self.assertIn(('COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA', 'complemento_moradia'), kinds)

    def test_profile_sums_detailed_notes_and_history_with_monthly_average(self):
        with closing(store.connect(self.db_path)) as db, db:
            profile = citizen.politician(db, 'camara:1')
        self.assertEqual(profile['total'], 600.0)  # 100 + 300 (2023) + 200 (2026); complemento fora
        self.assertEqual(profile['periodo'], {'inicio': '2023-02', 'fim': '2026-01', 'meses': 3})
        self.assertEqual(profile['mediaMensal'], 200.0)  # só meses com notas: mês sem nota não é zero
        self.assertEqual(profile['expenseCount'], 3)
        self.assertEqual(profile['fornecedores'][0]['valor'], 600.0)
        self.assertEqual(profile['complementoMoradia']['meses'], ['2023-03'])
        self.assertEqual(profile['maiores'][0]['valor'], 300.0)

    def test_reimporting_the_current_year_keeps_history_and_vice_versa(self):
        self.import_current()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(citizen.politician(db, 'camara:1')['total'], 600.0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses WHERE sourceId='camara_ceap'").fetchone()[0], 1)
            # Quem saiu antes de 2026 ganha cadastro, sem mudar quem já existia.
            self.assertEqual(db.execute("SELECT sourceId FROM authorities WHERE id='camara:9'").fetchone()[0], 'camara_ceap_2023')
            self.assertEqual(db.execute("SELECT sourceId FROM authorities WHERE id='camara:1'").fetchone()[0], 'camara_deputies_current')
            # Alertas continuam calculados só sobre as notas detalhadas.
            self.assertEqual(db.execute("SELECT COUNT(*) FROM signals WHERE period LIKE '2023%'").fetchone()[0], 0)

    def test_month_notes_sum_to_the_month_and_only_exist_for_detailed_years(self):
        with closing(store.connect(self.db_path)) as db, db:
            notes = citizen.month_notes(db, 'camara:1', '2026-01')
            self.assertEqual((notes['total'], len(notes['notas'])), (200.0, 1))
            self.assertEqual(notes['notas'][0]['fornecedor'], 'Gráfica')
            self.assertIsNone(citizen.month_notes(db, 'camara:1', '2023-03'))  # só agregados
            self.assertIsNone(citizen.month_notes(db, 'camara:1', '2026-13'))
            self.assertIsNone(citizen.month_notes(db, 'camara:404', '2026-01'))

    def test_list_orders_by_monthly_average(self):
        with closing(store.connect(self.db_path)) as db, db:
            item = citizen.politicians(db, {'ordem': 'gasto'})['itens'][0]
        self.assertEqual((item['gasto'], item['gastoMensal'], item['inicio'], item['fim']), (600.0, 200.0, '2023-02', '2026-01'))


if __name__ == '__main__':
    unittest.main()
