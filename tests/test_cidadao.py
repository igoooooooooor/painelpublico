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

    def test_member_who_leaves_the_list_keeps_history_and_is_marked_outside(self):
        with closing(store.connect(self.db_path)) as db, db:
            self.assertIn('camara:paid', {p['id'] for p in cidadao.politicos(db, {'pageSize': 100})['itens']})
            former = cidadao.politico(db, 'camara:former')['pessoa']
            self.assertTrue(former['foraDaLista'])
            self.assertFalse(former['current'])
        # Nova lista oficial sem camara:paid: a pessoa continua só no arquivo de despesas.
        self.payload['authorities'][2]['sourceId'] = 'camara_ceap'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            listed = cidadao.politicos(db, {'pageSize': 100})
            self.assertNotIn('camara:paid', {p['id'] for p in listed['itens']})
            self.assertEqual(listed['cobertura']['deputado']['count'], 2)
            ficha = cidadao.politico(db, 'camara:paid')
            self.assertTrue(ficha['pessoa']['foraDaLista'])
            self.assertEqual(ficha['total'], 123.45)
            self.assertEqual(cidadao.resumo(db)['parlamentares']['deputado'], {'total': 2, 'comReembolsos': 1})

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

    def test_home_summary_uses_full_current_rosters_and_observed_expense_periods(self):
        amounts = []
        for index in range(10):
            identifier = f'camara:extra-{index:02d}'
            self.payload['authorities'].append(
                self.authority(identifier, f'Pessoa Extra {index:02d}', 'deputado', 'camara_deputies_current'))
            amount = (index + 1) * 25
            amounts.append(amount)
            expense = self.expense(f'expense:extra-{index:02d}', identifier, 'camara_ceap', amount)
            expense['month'] = index + 2
            expense['date'] = f'2026-{index + 2:02d}-12'
            expense['category'] = 'Alimentação' if index % 2 else 'Divulgação'
            self.payload['expenses'].append(expense)
        self.payload['authorities'].append(
            self.authority('senado:no-data', 'Senador Sem Dados', 'senador', 'senado_senators_current'))
        self.import_data()

        with closing(store.connect(self.db_path)) as db, db:
            result = cidadao.resumo(db)

        self.assertEqual(result['parlamentares'], {
            'deputado': {'total': 13, 'comReembolsos': 12},
            'senador': {'total': 2, 'comReembolsos': 1},
        })
        deputy_total = 123.45 + sum(amounts)
        self.assertEqual(result['reembolsos']['deputado'], {
            'total': deputy_total,
            'media': deputy_total / 12,
            'comRegistros': 12,
            'periodo': {'inicio': '2026-01', 'fim': '2026-11'},
        })
        self.assertEqual(result['reembolsos']['senador'], {
            'total': 50.0,
            'media': 50.0,
            'comRegistros': 1,
            'periodo': {'inicio': '2026-01', 'fim': '2026-01'},
        })
        categories = {item['nome']: item['valor'] for item in result['categoriasCamara']}
        self.assertEqual(categories['Escritório'], 123.45)
        self.assertEqual(categories['Alimentação'], sum(amount for i, amount in enumerate(amounts) if i % 2))
        self.assertEqual(categories['Divulgação'], sum(amount for i, amount in enumerate(amounts) if i % 2 == 0))
        self.assertEqual(sum(categories.values()), deputy_total)
        self.assertEqual(len(result['topCamara']), 12)
        self.assertEqual(result['topCamara'][0]['id'], 'camara:extra-09')
        self.assertEqual(result['topCamara'][-1]['id'], 'camara:zero')
        self.assertNotIn('camara:former', {item['id'] for item in result['topCamara']})

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


class PicoRuleTests(unittest.TestCase):
    """Pico: piso pelos colegas, meses seguidos como um alerta só e escala do ano no cartão."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / 'pico.sqlite3'
        authorities, expenses = [], []
        perfis = {f'camara:{i}': [40000] * 6 for i in range(1, 7)}            # colegas: R$ 40 mil por mês
        perfis['camara:20'] = [2000, 2000, 2000, 22000, 22000, 2000]           # gasta pouco; "pico" abaixo do típico
        perfis['camara:30'] = [40000, 40000, 40000, 100000, 100000, 40000]    # sobe de patamar em abril e maio
        perfis['camara:group:9'] = perfis['camara:30']                        # conta de liderança: id com dois ':'
        for ident, meses in perfis.items():
            role = 'conta_institucional' if ':group:' in ident else 'deputado'
            authorities.append({'id': ident, 'name': f'Pessoa {ident}', 'role': role, 'party': 'AAA', 'uf': 'SP',
                                'sourceId': 'camara_deputies_current', 'branch': 'legislativo', 'sphere': 'federal'})
            for month, amount in enumerate(meses, 1):
                expenses.append({'id': f'{ident}:{month}', 'authorityId': ident, 'sourceId': 'camara_ceap', 'year': 2026,
                                 'month': month, 'date': f'2026-{month:02d}-10', 'category': 'Escritório', 'kind': 'reembolso',
                                 'amount': amount, 'supplier': {'key': f'k{ident}:{month}', 'name': f'Empresa {ident} {month}'}})
        source = Path(self.temp.name) / 'in.json'
        source.write_text(json.dumps({'sources': [{'id': s, 'label': s, 'status': 'imported'} for s in ('camara_deputies_current', 'camara_ceap')],
                                      'authorities': authorities, 'expenses': expenses}), encoding='utf-8')
        store.import_documents([source], self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_low_spender_month_below_peers_is_not_a_spike_and_consecutive_months_are_one_alert(self):
        with closing(store.connect(self.db_path)) as db, db:
            picos = cidadao.rows(db, "SELECT * FROM signals WHERE type='pico' ORDER BY id")
            self.assertEqual([s['authorityId'] for s in picos], ['camara:30', 'camara:group:9'])
            self.assertEqual(picos[0]['period'], '2026-04')
            pessoas = {'camara:30': {'id': 'camara:30', 'name': 'Pessoa 30', 'role': 'deputado'}}
            alerta = cidadao._alerta(db, picos[0], pessoas, {})
            ranking = cidadao.politicos(db, {'ordem': 'alertas', 'pageSize': 3})['itens']
        self.assertEqual(alerta['titulo'], 'Gastos mais altos a partir de abril')
        self.assertEqual(alerta['seguidos'], [5])
        self.assertIn('Depois continuou alta: maio', alerta['frase'])
        self.assertIn('No ano, gastou', alerta['contexto']['frase'])
        self.assertGreater(alerta['contexto']['diferenca'], 0)
        self.assertEqual(ranking[0]['id'], 'camara:30')
        self.assertEqual(ranking[0]['valorAlertas'], 100000)

    def test_radar_reads_ids_with_extra_colons_and_lists_only_politicians(self):
        with closing(store.connect(self.db_path)) as db, db:
            grupo = cidadao.rows(db, "SELECT * FROM signals WHERE authorityId='camara:group:9' AND type='pico'")[0]
            alerta = cidadao._alerta(db, grupo, {}, {})
            radar = cidadao.radar(db, {'pageSize': 50})
        self.assertEqual(alerta['mes'], 4)
        self.assertEqual([a['pessoa']['id'] for a in radar['itens']], ['camara:30'])
        self.assertEqual(radar['contagem']['pico'], 1)
