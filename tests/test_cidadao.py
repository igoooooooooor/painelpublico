import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend import cidadao, public_store as store


class CidadaoPoliticosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'cidadao.sqlite3'
        self.payload = {
            'sources': [
                {'id': source, 'label': source, 'status': 'imported'}
                for source in (
                    'camara_deputies_current', 'senado_senators_current',
                    'camara_ceap', 'senado_ceaps',
                )
            ],
            'authorities': [
                self.authority('camara:no-data', 'Ada Sem Dados', 'deputado', 'camara_deputies_current'),
                self.authority('camara:zero', 'Beto Zero', 'deputado', 'camara_deputies_current'),
                self.authority('camara:paid', 'Caio Pago', 'deputado', 'camara_deputies_current'),
                {
                    **self.authority('senado:current', 'Dora Senadora', 'senador', 'senado_senators_current'),
                    'position': 'Mandato <titular> & participação',
                    'employmentStatus': 'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular',
                },
                self.authority('camara:former', 'Eva Ex-Deputada', 'deputado', 'camara_ceap'),
            ],
            'expenses': [
                self.expense('expense:zero', 'camara:zero', 'camara_ceap', 0),
                self.expense('expense:paid', 'camara:paid', 'camara_ceap', 123.45),
                self.expense('expense:senator', 'senado:current', 'senado_ceaps', 50),
                self.expense('expense:former', 'camara:former', 'camara_ceap', 75),
            ],
        }
        self.import_data()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def authority(identifier, name, role, source_id):
        return {
            'id': identifier, 'name': name, 'role': role, 'branch': 'legislativo',
            'sphere': 'federal', 'institution': 'Congresso Nacional', 'uf': 'SP',
            'party': 'TESTE', 'sourceId': source_id,
            'sourceUrl': 'https://example.gov.br/parlamentar',
        }

    @staticmethod
    def expense(identifier, authority_id, source_id, amount):
        return {
            'id': identifier, 'authorityId': authority_id, 'sourceId': source_id,
            'year': 2026, 'month': 1, 'date': '2026-01-12',
            'category': 'Escritório', 'kind': 'reembolso', 'amount': amount,
            'supplier': None,
        }

    def import_data(self):
        source = self.root / 'input.json'
        source.write_text(json.dumps(self.payload), encoding='utf-8')
        store.import_documents([source], self.db_path)

    def test_roster_coverage_pagination_filters_and_excludes_expense_only_authorities(self):
        with closing(store.connect(self.db_path)) as db, db:
            first = cidadao.politicos(db, {'page': 1, 'pageSize': 2})
            second = cidadao.politicos(db, {'page': 2, 'pageSize': 2})
            senators = cidadao.politicos(db, {'cargo': 'senador', 'pageSize': 100})
            senator_profile = cidadao.politico(db, 'senado:current')
            deputies_by_spend = cidadao.politicos(
                db, {'cargo': 'deputado', 'ordem': 'gasto', 'pageSize': 100},
            )

        self.assertEqual(first['total'], 4)
        self.assertEqual(second['total'], 4)
        self.assertEqual(first['pageSize'], 2)
        self.assertEqual(len(first['itens']), 2)
        self.assertEqual(len(second['itens']), 2)
        self.assertEqual(
            {item['id'] for item in first['itens'] + second['itens']},
            {'camara:no-data', 'camara:zero', 'camara:paid', 'senado:current'},
        )
        self.assertEqual(senators['total'], 1)
        self.assertEqual([item['id'] for item in senators['itens']], ['senado:current'])
        senator = senators['itens'][0]
        self.assertEqual(senator['position'], 'Mandato <titular> & participação')
        self.assertEqual(senator['employmentStatus'], 'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular')
        self.assertEqual(senator['sourceUrl'], 'https://example.gov.br/parlamentar')
        self.assertEqual(senator_profile['pessoa']['position'], 'Mandato <titular> & participação')
        self.assertEqual(senator_profile['pessoa']['employmentStatus'], 'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular')
        self.assertIsNone(first['itens'][0]['position'])
        self.assertEqual(first['cobertura'], {
            'deputado': {'count': 3, 'withExpenses': 2},
            'senador': {'count': 1, 'withExpenses': 1},
        })
        self.assertEqual(
            [item['id'] for item in deputies_by_spend['itens']],
            ['camara:paid', 'camara:zero', 'camara:no-data'],
        )

    def test_absent_reimbursements_are_null_but_observed_zero_remains_zero(self):
        with closing(store.connect(self.db_path)) as db, db:
            listing = cidadao.politicos(db, {'pageSize': 100})
            rows = {item['id']: item for item in listing['itens']}
            no_data = cidadao.politico(db, 'camara:no-data')
            observed_zero = cidadao.politico(db, 'camara:zero')

        self.assertIsNone(rows['camara:no-data']['gasto'])
        self.assertFalse(rows['camara:no-data']['hasExpenseData'])
        self.assertEqual(rows['camara:no-data']['expenseCount'], 0)
        self.assertEqual(rows['camara:zero']['gasto'], 0)
        self.assertTrue(rows['camara:zero']['hasExpenseData'])
        self.assertEqual(rows['camara:zero']['expenseCount'], 1)
        self.assertIsNone(no_data['pessoa']['position'])
        self.assertIsNone(no_data['pessoa']['employmentStatus'])

        self.assertIsNone(no_data['total'])
        self.assertFalse(no_data['hasExpenseData'])
        self.assertEqual(no_data['expenseCount'], 0)
        self.assertEqual(no_data['meses'], [])
        self.assertEqual(no_data['categorias'], [])
        self.assertEqual(observed_zero['total'], 0)
        self.assertTrue(observed_zero['hasExpenseData'])
        self.assertEqual(observed_zero['expenseCount'], 1)
        self.assertEqual(observed_zero['meses'], [
            {'year': 2026, 'month': 1, 'valor': 0},
        ])

    def test_party_summary_counts_roster_and_keeps_missing_spending_null(self):
        self.payload['authorities'].append(
            {**self.authority('camara:outro', 'Fábio Outro', 'deputado', 'camara_deputies_current'), 'party': 'OUTRO'})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            result = cidadao.partidos(db)
        parties = {item['sigla']: item for item in result['itens']}

        teste = parties['TESTE']
        self.assertEqual(teste['membros'], 4)
        self.assertEqual(teste['deputado']['membros'], 3)
        self.assertEqual(teste['deputado']['comDados'], 2)
        self.assertAlmostEqual(teste['deputado']['gasto'], 123.45)
        self.assertAlmostEqual(teste['deputado']['media'], 61.725)
        self.assertEqual(teste['senador']['membros'], 1)
        self.assertEqual([p['id'] for p in teste['top']], ['camara:paid', 'senado:current', 'camara:zero'])
        self.assertNotIn('camara:former', [p['id'] for p in teste['top']])

        outro = parties['OUTRO']
        self.assertEqual(outro['deputado']['comDados'], 0)
        self.assertIsNone(outro['deputado']['gasto'])
        self.assertIsNone(outro['deputado']['media'])
        self.assertIsNone(outro['senador'])
        self.assertEqual(outro['top'], [])
        self.assertEqual(result['itens'][0]['sigla'], 'TESTE')


if __name__ == '__main__':
    unittest.main()
