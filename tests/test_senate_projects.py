import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from ingest import senate_projects


def process(identifier='9000001', title='PL 123/2026', *, objective='Iniciadora',
             presented='2026-03-01', authors='Senador Exemplo, Senadora Coautora'):
    return {
        'id': int(identifier),
        'identificacao': title,
        'objetivo': objective,
        'dataApresentacao': presented,
        'autoria': authors,
        'ementa': 'Ementa de exemplo.',
        'urlDocumento': 'https://legis.senado.gov.br/sdleg-getter/documento?dm=9000002',
    }


class SenateProjectsTests(unittest.TestCase):
    def test_roster_selects_only_current_senator_ids(self):
        payload = {'authorities': [
            {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
             'sourceId': 'senado_senators_current'},
            {'id': 'camara:5322', 'name': 'Deputado', 'role': 'deputado',
             'sourceId': 'camara_deputies_current'},
            {'id': 'senado:5323', 'name': 'Histórico', 'role': 'senador', 'sourceId': 'senado_ceaps'},
            {'id': 'senado:x', 'name': 'ID inválido', 'role': 'senador',
             'sourceId': 'senado_senators_current'},
        ]}
        self.assertEqual(senate_projects._senator_ids(payload), ['senado:5322'])

    def test_query_uses_author_code_dates_and_all_three_project_types(self):
        url = senate_projects._project_url('senado:5322', 2026, date(2026, 10, 7))
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['codigoParlamentarAutor'], ['5322'])
        self.assertEqual(query['sigla'], ['PL', 'PLP', 'PEC'])
        self.assertEqual(query['dataInicioApresentacao'], ['2026-01-01'])
        self.assertEqual(query['dataFimApresentacao'], ['2026-10-07'])
        self.assertNotIn('pagina', query)

    def test_author_filter_result_keeps_coauthored_projects_and_null_situation(self):
        coauthored = process('9000001', 'PEC 6/2026', authors='Senador Principal, Senador Romário')
        calls = []

        def request(url):
            calls.append(url)
            return [coauthored]

        result = senate_projects.fetch_senate_projects(
            'senado:5322', request_json=request, today=date(2026, 10, 7)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual((result['status'], result['total']), ('imported', 1))
        self.assertEqual(result['items'][0], {
            'id': '9000001', 'titulo': 'PEC 6/2026', 'ementa': 'Ementa de exemplo.',
            'situacao': None,
            'url': 'https://legis.senado.gov.br/sdleg-getter/documento?dm=9000002',
            'dataApresentacao': '2026-03-01',
        })

    def test_substitute_process_is_not_counted_as_a_2026_initiating_project(self):
        substitute = process(
            '8989920', 'PL 365/2026 (Substitutivo-CD)', objective='Substitutivo',
            presented='2026-02-04', authors='Câmara dos Deputados',
        )
        result = senate_projects.fetch_senate_projects(
            'senado:5322', request_json=lambda _: [substitute], today=date(2026, 10, 7)
        )
        self.assertEqual((result['status'], result['total'], result['items']), ('imported', 0, []))

    def test_successful_empty_list_is_zero_but_invalid_payload_is_unavailable(self):
        zero = senate_projects.fetch_senate_projects(
            'senado:5322', request_json=lambda _: [], today=date(2026, 10, 7)
        )
        failed = senate_projects.fetch_senate_projects(
            'senado:5322', request_json=lambda _: {'error': 'not an array'}, today=date(2026, 10, 7)
        )
        self.assertEqual((zero['status'], zero['total']), ('imported', 0))
        self.assertEqual((failed['status'], failed['total']), ('unavailable', None))
        self.assertIsNone(failed['fetchedAt'])

    def test_offline_snapshot_loads_cache_and_keeps_uncollected_profiles_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
                {'id': 'senado:5323', 'name': 'Senadora Exemplo', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            cache_root = root / 'data' / 'raw' / 'senado-projetos'
            senate_projects._write_cache('senado:5322', 2026, {
                'status': 'imported', 'period': '2026-01-01 a 2026-10-07',
                'sourceUrl': 'https://legis.senado.leg.br/dadosabertos/processo',
                'fetchedAt': '2026-10-07T12:00:00+00:00', 'total': 1,
                'items': [{'id': '9000001', 'titulo': 'PL 123/2026', 'ementa': 'Ementa',
                           'situacao': None,
                           'url': 'https://legis.senado.gov.br/sdleg-getter/documento?dm=9000002'}],
            }, cache_root)

            snapshot, stats = senate_projects.build_snapshot(root=root, today=date(2026, 10, 7))
            self.assertEqual(snapshot['year'], 2026)
            self.assertEqual(snapshot['profiles']['senado:5322']['projetos']['total'], 1)
            self.assertEqual(snapshot['profiles']['senado:5323']['projetos']['status'], 'unavailable')
            self.assertIsNone(snapshot['profiles']['senado:5323']['projetos']['total'])
            self.assertEqual(stats['imported'], 1)
            self.assertEqual(stats['unavailable'], 1)

    def test_refresh_failure_preserves_last_observation_as_stale_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            previous = {
                'status': 'imported', 'period': 'PL, PLP e PEC apresentados de 2026-01-01 a 2026-10-06',
                'sourceUrl': 'https://legis.senado.leg.br/dadosabertos/processo',
                'fetchedAt': '2026-10-06T12:00:00+00:00', 'total': 0, 'items': [],
            }
            senate_projects._write_cache('senado:5322', 2026, previous, cache_root)

            refreshed = senate_projects._collect_one(
                'senado:5322', 2026, cache_root, True,
                lambda _: (_ for _ in ()).throw(OSError('offline')),
                date(2026, 10, 7),
            )
            self.assertEqual(refreshed['status'], 'partial')
            self.assertEqual(refreshed['total'], 0)
            self.assertEqual(refreshed['fetchedAt'], previous['fetchedAt'])
            self.assertTrue(refreshed['stale'])
            self.assertIn('Falha ao atualizar', refreshed['detail'])
            self.assertEqual(senate_projects._read_cache('senado:5322', 2026, cache_root), refreshed)

    def test_mandate_collect_uses_february_start_filters_january_and_deduplicates_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            calls = []

            def request(url):
                query = parse_qs(urlsplit(url).query)
                calls.append((query['dataInicioApresentacao'][0], query['dataFimApresentacao'][0]))
                if query['dataInicioApresentacao'][0] == '2023-02-01':
                    return [
                        process('9000000', 'PL 1/2023', presented='2023-01-31'),
                        process('9000001', 'PL 2/2023', presented='2023-02-01'),
                    ]
                return [process('9000001', 'PL 2/2023', presented='2024-01-01')]

            snapshot, stats = senate_projects.build_mandate_snapshot(
                root=root, collect=True, request_json=request, today=date(2024, 1, 5)
            )
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual(calls, [('2023-02-01', '2023-12-31'), ('2024-01-01', '2024-01-05')])
            self.assertEqual(snapshot['year'], 2024)
            self.assertEqual((snapshot['startDate'], snapshot['endDate']), ('2023-02-01', '2024-01-05'))
            self.assertEqual((projects['status'], projects['total']), ('imported', 1))
            self.assertEqual([item['id'] for item in projects['items']], ['9000001'])
            self.assertEqual(projects['items'][0]['dataApresentacao'], '2023-02-01')
            self.assertEqual([row['status'] for row in projects['yearlyCoverage']], ['imported', 'imported'])
            self.assertEqual(stats['projects'], 1)

    def test_mandate_marks_failed_and_missing_years_incomplete_but_empty_success_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')

            def request(url):
                start = parse_qs(urlsplit(url).query)['dataInicioApresentacao'][0]
                if start == '2023-02-01':
                    raise OSError('offline')
                return []

            snapshot, _ = senate_projects.build_mandate_snapshot(
                root=root, collect=True, request_json=request, today=date(2024, 1, 5)
            )
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual((projects['status'], projects['total']), ('partial', None))
            self.assertEqual(projects['items'], [])
            self.assertEqual([row['status'] for row in projects['yearlyCoverage']], ['unavailable', 'imported'])
            self.assertIsNone(projects['yearlyCoverage'][0]['fetchedAt'])
            self.assertEqual(projects['yearlyCoverage'][1]['total'], 0)

    def test_mandate_reuses_only_cache_that_covers_requested_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            cache_root = root / 'data' / 'raw' / 'senado-projetos'
            for year, start, end, item in [
                (2023, date(2023, 2, 1), date(2023, 12, 31),
                 {'id': '9000001', 'titulo': 'PL 2/2023', 'ementa': 'Ementa',
                  'situacao': None, 'url': None, 'dataApresentacao': '2023-02-01'}),
                (2024, date(2024, 1, 1), date(2024, 1, 5),
                 {'id': '9000002', 'titulo': 'PL 3/2024', 'ementa': 'Ementa',
                  'situacao': None, 'url': None, 'dataApresentacao': '2024-01-05'}),
            ]:
                start_text, end_text = start.isoformat(), end.isoformat()
                senate_projects._write_cache('senado:5322', year, {
                    'status': 'imported',
                    'period': f'PL, PLP e PEC apresentados de {start_text} a {end_text}',
                    'sourceUrl': senate_projects._project_url('senado:5322', year, end, start),
                    'startDate': start_text, 'endDate': end_text,
                    'fetchedAt': f'{year}-12-31T12:00:00+00:00', 'total': 1, 'items': [item],
                }, cache_root)

            snapshot, _ = senate_projects.build_mandate_snapshot(
                root=root, collect=True,
                request_json=lambda _: self.fail('covered cache should be reused'),
                today=date(2024, 1, 5),
            )
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual((projects['status'], projects['total']), ('imported', 2))
            self.assertEqual([item['id'] for item in projects['items']], ['9000001', '9000002'])
            self.assertEqual([source['year'] for source in projects['sources']], [2023, 2024])

    def test_mandate_offline_snapshot_lists_uncached_years_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')

            snapshot, _ = senate_projects.build_mandate_snapshot(root=root, today=date(2024, 1, 5))
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual((projects['status'], projects['total']), ('unavailable', None))
            self.assertEqual([row['status'] for row in projects['yearlyCoverage']], ['unavailable', 'unavailable'])
            self.assertEqual(
                [(row['requestedStartDate'], row['requestedEndDate']) for row in projects['yearlyCoverage']],
                [('2023-02-01', '2023-12-31'), ('2024-01-01', '2024-01-05')],
            )
            self.assertTrue(all(row['observedStartDate'] is None for row in projects['yearlyCoverage']))

    def test_mandate_refetches_legacy_january_cache_without_project_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            cache_root = root / 'data' / 'raw' / 'senado-projetos'
            senate_projects._write_cache('senado:5322', 2023, {
                'status': 'imported',
                'period': 'PL, PLP e PEC apresentados de 2023-01-01 a 2023-12-31',
                'sourceUrl': senate_projects._project_url('senado:5322', 2023, date(2023, 12, 31)),
                'fetchedAt': '2024-01-02T12:00:00+00:00', 'total': 1,
                'items': [{'id': '9000001', 'titulo': 'PL 2/2023', 'ementa': 'Ementa',
                           'situacao': None, 'url': None}],
            }, cache_root)
            calls = []

            def request(url):
                calls.append(parse_qs(urlsplit(url).query)['dataInicioApresentacao'][0])
                return []

            snapshot, _ = senate_projects.build_mandate_snapshot(
                root=root, collect=True, request_json=request, today=date(2023, 12, 31)
            )
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual(calls, ['2023-02-01'])
            self.assertEqual((projects['status'], projects['total'], projects['items']), ('imported', 0, []))

    def test_mandate_limit_leaves_other_senators_cached_data_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
                {'id': 'senado:5323', 'name': 'Senadora Exemplo', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            cache_root = root / 'data' / 'raw' / 'senado-projetos'
            senate_projects._write_cache('senado:5323', 2023, {
                'status': 'imported',
                'period': 'PL, PLP e PEC apresentados de 2023-02-01 a 2023-12-31',
                'sourceUrl': senate_projects._project_url(
                    'senado:5323', 2023, date(2023, 12, 31), date(2023, 2, 1)
                ),
                'startDate': '2023-02-01', 'endDate': '2023-12-31',
                'fetchedAt': '2024-01-02T12:00:00+00:00', 'total': 0, 'items': [],
            }, cache_root)

            snapshot, stats = senate_projects.build_mandate_snapshot(
                root=root, collect=True, limit=1, request_json=lambda _: [], today=date(2023, 12, 31)
            )
            profiles = snapshot['profiles']
            self.assertEqual(stats['consultados'], 1)
            self.assertEqual(profiles['senado:5323']['projetos']['status'], 'imported')
            self.assertEqual(profiles['senado:5323']['projetos']['total'], 0)
            self.assertEqual(
                senate_projects._read_cache('senado:5323', 2023, cache_root)['fetchedAt'],
                '2024-01-02T12:00:00+00:00',
            )

    def test_failed_mandate_refresh_keeps_prior_items_and_fetched_at_as_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / 'data' / 'imports' / 'legislative.json'
            imports.parent.mkdir(parents=True)
            imports.write_text(json.dumps({'authorities': [
                {'id': 'senado:5322', 'name': 'Romário', 'role': 'senador',
                 'sourceId': 'senado_senators_current'},
            ]}), encoding='utf-8')
            cache_root = root / 'data' / 'raw' / 'senado-projetos'
            senate_projects._write_cache('senado:5322', 2023, {
                'status': 'imported',
                'period': 'PL, PLP e PEC apresentados de 2023-02-01 a 2023-12-31',
                'sourceUrl': senate_projects._project_url(
                    'senado:5322', 2023, date(2023, 12, 31), date(2023, 2, 1)
                ),
                'startDate': '2023-02-01', 'endDate': '2023-12-31',
                'fetchedAt': '2024-01-02T12:00:00+00:00', 'total': 1,
                'items': [{'id': '9000001', 'titulo': 'PL 2/2023', 'ementa': 'Ementa',
                           'situacao': None, 'url': None, 'dataApresentacao': '2023-02-01'}],
            }, cache_root)

            snapshot, _ = senate_projects.build_mandate_snapshot(
                root=root, collect=True, refresh=True,
                request_json=lambda _: (_ for _ in ()).throw(OSError('offline')),
                today=date(2023, 12, 31),
            )
            projects = snapshot['profiles']['senado:5322']['projetos']
            self.assertEqual((projects['status'], projects['total']), ('partial', None))
            self.assertEqual([item['id'] for item in projects['items']], ['9000001'])
            self.assertEqual(projects['yearlyCoverage'][0]['fetchedAt'], '2024-01-02T12:00:00+00:00')
            self.assertTrue(projects['yearlyCoverage'][0]['stale'])


if __name__ == '__main__':
    unittest.main()
