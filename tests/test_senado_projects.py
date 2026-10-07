import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from ingest import senado_projects


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
        self.assertEqual(senado_projects._senator_ids(payload), ['senado:5322'])

    def test_query_uses_author_code_dates_and_all_three_project_types(self):
        url = senado_projects._project_url('senado:5322', 2026, date(2026, 10, 7))
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

        result = senado_projects.fetch_senado_projects(
            'senado:5322', request_json=request, today=date(2026, 10, 7)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual((result['status'], result['total']), ('imported', 1))
        self.assertEqual(result['items'][0], {
            'id': '9000001', 'titulo': 'PEC 6/2026', 'ementa': 'Ementa de exemplo.',
            'situacao': None,
            'url': 'https://legis.senado.gov.br/sdleg-getter/documento?dm=9000002',
        })

    def test_substitute_process_is_not_counted_as_a_2026_initiating_project(self):
        substitute = process(
            '8989920', 'PL 365/2026 (Substitutivo-CD)', objective='Substitutivo',
            presented='2026-02-04', authors='Câmara dos Deputados',
        )
        result = senado_projects.fetch_senado_projects(
            'senado:5322', request_json=lambda _: [substitute], today=date(2026, 10, 7)
        )
        self.assertEqual((result['status'], result['total'], result['items']), ('imported', 0, []))

    def test_successful_empty_list_is_zero_but_invalid_payload_is_unavailable(self):
        zero = senado_projects.fetch_senado_projects(
            'senado:5322', request_json=lambda _: [], today=date(2026, 10, 7)
        )
        failed = senado_projects.fetch_senado_projects(
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
            senado_projects._write_cache('senado:5322', 2026, {
                'status': 'imported', 'period': '2026-01-01 a 2026-10-07',
                'sourceUrl': 'https://legis.senado.leg.br/dadosabertos/processo',
                'fetchedAt': '2026-10-07T12:00:00+00:00', 'total': 1,
                'items': [{'id': '9000001', 'titulo': 'PL 123/2026', 'ementa': 'Ementa',
                           'situacao': None,
                           'url': 'https://legis.senado.gov.br/sdleg-getter/documento?dm=9000002'}],
            }, cache_root)

            snapshot, stats = senado_projects.build_snapshot(root=root, today=date(2026, 10, 7))
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
            senado_projects._write_cache('senado:5322', 2026, previous, cache_root)

            refreshed = senado_projects._collect_one(
                'senado:5322', 2026, cache_root, True,
                lambda _: (_ for _ in ()).throw(OSError('offline')),
                date(2026, 10, 7),
            )
            self.assertEqual(refreshed['status'], 'partial')
            self.assertEqual(refreshed['total'], 0)
            self.assertEqual(refreshed['fetchedAt'], previous['fetchedAt'])
            self.assertTrue(refreshed['stale'])
            self.assertIn('Falha ao atualizar', refreshed['detail'])
            self.assertEqual(senado_projects._read_cache('senado:5322', 2026, cache_root), refreshed)


if __name__ == '__main__':
    unittest.main()
