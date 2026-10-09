import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend import citizen, public_store as store
from backend.quota_history import import_history


class CitizenPoliticiansTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'citizen.sqlite3'
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
            self.assertIn('camara:paid', {person['id'] for person in citizen.politicians(db, {'pageSize': 100})['itens']})
            former = citizen.politician(db, 'camara:former')['pessoa']
            self.assertTrue(former['foraDaLista'])
            self.assertFalse(former['current'])
        # Nova lista oficial sem camara:paid: a pessoa continua só no arquivo de despesas.
        self.payload['authorities'][2]['sourceId'] = 'camara_ceap'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            listed = citizen.politicians(db, {'pageSize': 100})
            self.assertNotIn('camara:paid', {person['id'] for person in listed['itens']})
            self.assertEqual(listed['cobertura']['deputado']['count'], 2)
            ficha = citizen.politician(db, 'camara:paid')
            self.assertTrue(ficha['pessoa']['foraDaLista'])
            self.assertEqual(ficha['total'], 123.45)
            self.assertEqual(citizen.summary(db)['parlamentares']['deputado'], {'total': 2, 'comReembolsos': 1})

    def test_roster_coverage_pagination_filters_and_excludes_expense_only_authorities(self):
        with closing(store.connect(self.db_path)) as db, db:
            first = citizen.politicians(db, {'page': 1, 'pageSize': 2})
            second = citizen.politicians(db, {'page': 2, 'pageSize': 2})
            senators = citizen.politicians(db, {'cargo': 'senador', 'pageSize': 100})
            senator_profile = citizen.politician(db, 'senado:current')
            deputies_by_spend = citizen.politicians(
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
            listing = citizen.politicians(db, {'pageSize': 100})
            rows = {item['id']: item for item in listing['itens']}
            no_data = citizen.politician(db, 'camara:no-data')
            observed_zero = citizen.politician(db, 'camara:zero')

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
            result = citizen.summary(db)

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
            result = citizen.parties(db)
        parties = {item['sigla']: item for item in result['itens']}

        teste = parties['TESTE']
        self.assertEqual(teste['membros'], 4)
        self.assertEqual(teste['deputado']['membros'], 3)
        self.assertEqual(teste['deputado']['comDados'], 2)
        self.assertAlmostEqual(teste['deputado']['gasto'], 123.45)
        self.assertAlmostEqual(teste['deputado']['media'], 61.725)
        self.assertEqual(teste['senador']['membros'], 1)
        self.assertEqual([person['id'] for person in teste['top']], ['camara:paid', 'senado:current', 'camara:zero'])
        self.assertNotIn('camara:former', [person['id'] for person in teste['top']])

        outro = parties['OUTRO']
        self.assertEqual(outro['deputado']['comDados'], 0)
        self.assertIsNone(outro['deputado']['gasto'])
        self.assertIsNone(outro['deputado']['media'])
        self.assertIsNone(outro['senador'])
        self.assertEqual(outro['top'], [])
        self.assertEqual(result['itens'][0]['sigla'], 'TESTE')


if __name__ == '__main__':
    unittest.main()


class PeakRuleTests(unittest.TestCase):
    """Pico: piso pelos colegas, meses seguidos como um alerta só e escala do ano no cartão.

    2025 entra pelo histórico do mandato (quota_history), como na base real: a referência de 2026 usa
    os 12 meses anteriores, atravessando o ano.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / 'pico.sqlite3'
        authorities, expenses = [], []
        profiles = {f'camara:{i}': [40000] * 6 for i in range(1, 7)}            # colegas: R$ 40 mil por mês
        profiles['camara:20'] = [2000, 2000, 2000, 22000, 22000, 2000]           # gasta pouco; "pico" abaixo do típico
        profiles['camara:30'] = [40000, 40000, 40000, 100000, 100000, 40000]    # sobe de patamar em abril e maio
        profiles['camara:group:9'] = profiles['camara:30']                        # conta de liderança: id com dois ':'
        for ident, monthly_totals in profiles.items():
            role = 'conta_institucional' if ':group:' in ident else 'deputado'
            authorities.append({'id': ident, 'name': f'Pessoa {ident}', 'role': role, 'party': 'AAA', 'uf': 'SP',
                                'sourceId': 'camara_deputies_current', 'branch': 'legislativo', 'sphere': 'federal'})
            for month, amount in enumerate(monthly_totals, 1):
                expenses.append({'id': f'{ident}:{month}', 'authorityId': ident, 'sourceId': 'camara_ceap', 'year': 2026,
                                 'month': month, 'date': f'2026-{month:02d}-10', 'category': 'Escritório', 'kind': 'reembolso',
                                 'amount': amount, 'supplier': {'key': f'k{ident}:{month}', 'name': f'Empresa {ident} {month}'}})
        source = Path(self.temp.name) / 'in.json'
        source.write_text(json.dumps({'sources': [{'id': signal, 'label': signal, 'status': 'imported', 'fetchedAt': '2026-10-06T00:00:00+00:00'}
                                                  for signal in ('camara_deputies_current', 'camara_ceap')],
                                      'authorities': authorities, 'expenses': expenses}), encoding='utf-8')
        store.import_documents([source], self.db_path)
        history = Path(self.temp.name) / 'camara-ceap-2025.json'
        history.write_text(json.dumps({
            'house': 'camara', 'year': 2025,
            'source': {'id': 'camara_ceap_2025', 'label': 'Cota 2025', 'status': 'imported', 'fetchedAt': '2026-10-06T00:00:00+00:00'},
            'notes': [{'authorityId': ident, 'month': month, 'date': f'2025-{month:02d}-10', 'category': 'Escritório', 'kind': 'reembolso',
                       'amountCents': monthly_totals[0] * 100, 'supplier': {'key': f'h{ident}:{month}', 'name': 'Empresa'}}
                      for ident, monthly_totals in profiles.items() for month in range(1, 13)]}), encoding='utf-8')
        import_history([history], self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_low_spender_month_below_peers_is_not_a_spike_and_consecutive_months_are_one_alert(self):
        with closing(store.connect(self.db_path)) as db, db:
            peaks = citizen.rows(db, "SELECT * FROM signals WHERE type='pico' ORDER BY id")
            self.assertEqual([signal['authorityId'] for signal in peaks], ['camara:30', 'camara:group:9'])
            self.assertEqual(peaks[0]['period'], '2026-04')
            people = {'camara:30': {'id': 'camara:30', 'name': 'Pessoa 30', 'role': 'deputado'}}
            alert = citizen._alert(db, peaks[0], people, {})
            ranking = citizen.politicians(db, {'ordem': 'alertas', 'pageSize': 3})['itens']
        self.assertEqual(alert['titulo'], 'Meses acima da referência: abril a maio de 2026')
        self.assertIn('a referência dos 12 meses anteriores era R$ 40.000', alert['frase'])
        self.assertEqual((alert['serie'][0]['ano'], alert['serie'][0]['mes']), (2025, 4))  # a janela atravessa o ano
        self.assertEqual(alert['serie'][0]['estado'], 'historico_insuficiente')
        self.assertEqual([m['mes'] for m in alert['meses']], [4, 5])  # só os meses marcados pela regra
        self.assertIn('Em maio, a cota somou R$ 100.000', alert['frase'])
        self.assertNotIn('junho', alert['frase'])
        self.assertNotIn('nivel', alert)
        self.assertIn('Em 2026, gastou', alert['contexto']['frase'])
        self.assertIn('por mês em média', alert['contexto']['frase'])  # mensal contra mensal
        self.assertGreater(alert['contexto']['diferenca'], 0)
        self.assertEqual(ranking[0]['id'], 'camara:30')
        self.assertEqual(ranking[0]['valorAlertas'], 200000)  # abril e maio, cada nota uma vez

    def test_radar_reads_ids_with_extra_colons_and_lists_only_politicians(self):
        with closing(store.connect(self.db_path)) as db, db:
            group_label = citizen.rows(db, "SELECT * FROM signals WHERE authorityId='camara:group:9' AND type='pico'")[0]
            alert = citizen._alert(db, group_label, {}, {})
            radar = citizen.radar(db, {'pageSize': 50})
        self.assertEqual(alert['mes'], 4)
        self.assertEqual([a['pessoa']['id'] for a in radar['itens']], ['camara:30'])
        self.assertEqual(radar['contagem']['pico'], 1)
        self.assertEqual(radar['anos'], [{'ano': 2026, 'total': 1}])
        self.assertEqual(radar['periodo'], {'inicio': '2025-01', 'fim': '2026-06'})

    def test_long_run_gets_one_summary_sentence(self):
        months = [{'month': m, 'valueCents': v * 100, 'referenceCents': 4_000_000, 'multiple': v / 40000}
                  for m, v in ((7, 80000), (8, 90000), (9, 100000))]
        signal = {'id': 'pico:x', 'authorityId': 'camara:30', 'sourceId': 'camara_ceap', 'type': 'pico', 'amountCents': 27_000_000,
                  'period': '2026-07', 'description': '', 'detail': json.dumps({'ruleVersion': 'cota-alertas-v3', 'baseline': 'rolling12',
                  'year': 2026, 'months': months, 'floorCents': 0, 'series': [], 'partial': False})}
        with closing(store.connect(self.db_path)) as db, db:
            alert = citizen._alert(db, signal, {}, {})
        self.assertEqual(alert['frase'], 'De julho a setembro de 2026, a cota ficou acima da referência em 3 meses seguidos, '
                         'de 2,0 a 2,5 vezes a mediana dos 12 meses anteriores de cada mês. Nesses meses, somou R$ 270.000.')

    def test_history_notes_enter_the_alert_value_once_and_radar_filters_by_year(self):
        with closing(store.connect(self.db_path)) as db, db:
            hist = db.execute("SELECT COUNT(*) FROM signals WHERE type='fornecedor' AND period='2025'").fetchone()[0]
            radar_2025 = citizen.radar(db, {'pageSize': 50, 'ano': '2025', 'tipo': 'pico,fornecedor'})
            coverage = citizen.alert_coverage(db, 'camara:30')
        self.assertEqual(hist, 0)  # cada mês num fornecedor diferente: sem concentração
        self.assertEqual(radar_2025['total'], 0)
        self.assertEqual([(c['regra'], c['ano']) for c in coverage], [('pico', 2026), ('fornecedor', 2026), ('pico', 2025), ('fornecedor', 2025)])
        self.assertEqual(coverage[2]['naoAvaliados'][0]['motivo'], 'historico_insuficiente')


class CategoryNameTests(unittest.TestCase):
    def test_senate_air_tickets_are_not_labeled_as_bus_and_boat(self):
        self.assertEqual(citizen.category_name('Passagens aéreas, aquáticas e terrestres nacionais'), 'Passagens aéreas')
        self.assertEqual(citizen.category_name('PASSAGEM AÉREA - REEMBOLSO'), 'Passagens aéreas')
        self.assertEqual(citizen.category_name('PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS'), 'Ônibus e barco')


class SupplierSentenceTests(unittest.TestCase):
    def test_share_always_comes_with_absolute_values_and_months(self):
        detail = {'supplierCents': 3_200_000, 'totalCents': 3_500_000, 'share': 0.9143, 'records': 12, 'monthsWithNotes': 12}
        sentence = citizen._supplier_sentence(detail, 'Imobiliária', 'jan–dez/2025')
        self.assertIn('Nas notas disponíveis de jan–dez/2025 (12 meses com notas), que somam R$ 35.000, R$ 32.000 (91%)', sentence)

    def test_intermediation_is_not_presented_as_agency_revenue(self):
        detail = {'supplierCents': 600_000_00, 'totalCents': 800_000_00, 'share': 0.75, 'records': 163, 'monthsWithNotes': 12,
                  'intermediation': {'records': 150, 'airlines': ['GOL', 'LATAM']}}
        sentence = citizen._supplier_sentence(detail, 'Agência', '2025')
        self.assertIn('foram pagos a Agência por passagens de outras companhias (GOL, LATAM; 150 de 163 notas)', sentence)
        self.assertIn('não a receita da agência', sentence)
