import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from backend import server as srv, votes

_MISSING = object()


def make_vote(identifier='2611313-31'):
    return {'id': identifier, 'date': '2026-09-03', 'proposition': 'PLP 74/2026', 'type': 'PLP',
            'title': 'Regras para benefícios tributários', 'summary': 'Resumo sobre benefícios tributários.',
            'decisionLabel': 'Substitutivo', 'yesMeaning': 'Aprovar o texto submetido.',
            'noMeaning': 'Rejeitar o texto submetido.', 'outcome': 'approved',
            'tally': {'yes': 346, 'no': 46, 'abstention': 3, 'total': 395},
            'themes': [{'id': 'tributos', 'label': 'Tributos'}],
            'sources': {'vote': 'https://camara.leg.br/voto', 'rollCall': 'https://camara.leg.br/lista',
                        'text': None, 'proposition': 'https://camara.leg.br/proposicao',
                        'decision': 'https://camara.leg.br/sessao'},
            'reviewedAt': '2026-09-04T12:00:00Z'}


def make_snapshot(items=None, details_version=_MISSING):
    items = [make_vote()] if items is None else items
    result = {'schemaVersion': 1, 'generatedAt': '2026-10-09T12:00:00Z',
              'period': {'start': '2023-02-01', 'end': '2026-10-09'},
              'coverage': {'inventoryCount': 1500, 'candidateCount': 160, 'reviewedCount': len(items),
                           'publishedCount': len(items), 'pendingCount': 140, 'detail': 'Cobertura revisada.'},
              'items': items}
    if details_version is not _MISSING:
        result['detailsVersion'] = details_version
    return result


class VoteApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_build_path = srv.BUILD_PATH
        self.snapshots = self.root / 'snapshots'
        self.snapshots.mkdir()
        self.original_snapshots_path = srv.votes.SNAPSHOTS_PATH
        srv.votes.SNAPSHOTS_PATH = self.snapshots
        self.httpd = srv.ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
        self.httpd.db_path = self.root / 'missing.sqlite3'
        self.httpd.prod = True
        self.httpd.cache = srv.ResponseCache()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        srv.votes.SNAPSHOTS_PATH = self.original_snapshots_path
        srv.BUILD_PATH = self.original_build_path
        self.temp.cleanup()

    def write_index(self, items=None, details_version=_MISSING):
        path = self.snapshots / votes.INDEX_NAME
        path.write_text(json.dumps(make_snapshot(items, details_version), ensure_ascii=False), encoding='utf-8')
        return path

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response, json.loads(response.read())

    def get_error(self, path):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.get(path)
        error = context.exception
        body = json.loads(error.read())
        error.close()
        return error.code, body

    def test_vote_routes_work_without_database_and_bypass_response_cache(self):
        self.write_index()
        response, listing = self.get('/api/c/votes')
        self.assertEqual(response.status, 200)
        self.assertTrue(listing['available'])
        self.assertEqual(listing['total'], 1)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(len(self.httpd.cache.items), 0)

        detail_dir = self.snapshots / votes.DETAILS_DIRECTORY
        detail_dir.mkdir()
        (detail_dir / '2611313-31.json').write_text(json.dumps({
            'id': '2611313-31',
            'participants': [{'id': 'camara:123', 'name': 'Ana Deputada', 'party': 'ABC', 'uf': 'SP', 'vote': 'Sim'}],
            'partyTotals': [{'party': 'ABC', 'yes': 1, 'no': 0, 'other': 0}],
        }), encoding='utf-8')
        _, detail = self.get('/api/c/votes/2611313-31')
        self.assertTrue(detail['participantsAvailable'])
        self.assertEqual(detail['vote']['id'], '2611313-31')

    def test_query_filters_and_pagination_are_applied_by_the_http_route(self):
        second = make_vote('2611313-32')
        second.update({'date': '2026-09-02', 'proposition': 'PEC 10/2026', 'type': 'PEC',
                       'title': 'Mudança constitucional', 'summary': 'Resumo constitucional.',
                       'themes': [{'id': 'constituicao', 'label': 'Constituição'}]})
        self.write_index([make_vote(), second])
        _, result = self.get('/api/c/votes?q=BENEFICIOS&type=plp&page=1&pageSize=1')
        self.assertTrue(result['available'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['pageCount'], 1)
        self.assertEqual(result['items'][0]['id'], '2611313-31')

    def test_listing_is_private_and_detail_file_is_lazy_loaded(self):
        self.write_index()
        detail_dir = self.snapshots / votes.DETAILS_DIRECTORY
        detail_dir.mkdir()
        (detail_dir / '2611313-31.json').write_text(json.dumps({
            'id': '2611313-31', 'participants': [], 'partyTotals': []}), encoding='utf-8')
        original_loader = votes._load_json
        loaded_paths = []

        def recording_loader(path):
            loaded_paths.append(Path(path).name)
            return original_loader(path)

        with patch.object(votes, '_load_json', side_effect=recording_loader):
            _, listing = self.get('/api/c/votes')
            self.assertEqual(loaded_paths, [votes.INDEX_NAME])
            serialized = json.dumps(listing)
            self.assertNotIn('participants', serialized)
            self.assertNotIn('partyTotals', serialized)
            _, detail = self.get('/api/c/votes/2611313-31')
        self.assertIn('2611313-31.json', loaded_paths)
        self.assertTrue(detail['participantsAvailable'])

    def test_api_reads_generation_details_without_exposing_generation_version(self):
        version = 'd' * 64
        self.write_index(details_version=version)
        details_path = self.snapshots / votes.DETAILS_DIRECTORY / version / '2611313-31.json'
        details_path.parent.mkdir(parents=True)
        details_path.write_text(json.dumps({
            'id': '2611313-31',
            'participants': [{'id': 'camara:123', 'name': 'Ana Deputada', 'party': 'ABC', 'uf': 'SP', 'vote': 'Sim'}],
            'partyTotals': [{'party': 'ABC', 'yes': 1, 'no': 0, 'other': 0}],
        }), encoding='utf-8')
        _, listing = self.get('/api/c/votes')
        _, detail = self.get('/api/c/votes/2611313-31')
        self.assertTrue(detail['participantsAvailable'])
        self.assertEqual(detail['participants'][0]['name'], 'Ana Deputada')
        self.assertNotIn('detailsVersion', json.dumps(listing))
        self.assertNotIn('detailsVersion', json.dumps(detail))

    def test_invalid_or_traversal_identifiers_return_404(self):
        self.write_index()
        self.assertEqual(self.get_error('/api/c/votes/not-an-id')[0], 404)
        self.assertEqual(self.get_error('/api/c/votes/2611313-30')[0], 404)
        self.assertEqual(self.get_error('/api/c/votes/%2e%2e%2f2611313-31')[0], 404)

    def test_vote_deep_link_serves_generic_scoreboard_shell_and_invalid_paths_stay_404(self):
        build_path = self.root / 'index.html'
        build_path.write_text('<html><head><title>App</title></head><body><main id="app"></main></body></html>',
                              encoding='utf-8')
        srv.BUILD_PATH = build_path
        request = urllib.request.Request(self.base + '/placar/2611313-31')
        with urllib.request.urlopen(request) as response:
            html = response.read().decode('utf-8')
        self.assertIn('<title>Placar das votações da Câmara · Painel Público</title>', html)
        self.assertIn(f'<link rel="canonical" href="{self.base}/placar">', html)
        self.assertEqual(self.get_error('/placar/not-a-vote')[0], 404)

    def test_missing_snapshot_differs_from_valid_empty_snapshot(self):
        _, missing = self.get('/api/c/votes')
        self.assertFalse(missing['available'])
        self.assertEqual(missing['items'], [])
        self.write_index([])
        _, empty = self.get('/api/c/votes')
        self.assertTrue(empty['available'])
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['total'], 0)
        self.assertEqual(empty['period']['start'], '2023-02-01')

    def test_corrupt_detail_preserves_summary_but_reports_participants_unavailable(self):
        self.write_index()
        detail_dir = self.snapshots / votes.DETAILS_DIRECTORY
        detail_dir.mkdir()
        (detail_dir / '2611313-31.json').write_text('{invalid', encoding='utf-8')
        _, detail = self.get('/api/c/votes/2611313-31')
        self.assertTrue(detail['available'])
        self.assertFalse(detail['participantsAvailable'])
        self.assertEqual(detail['vote']['title'], 'Regras para benefícios tributários')
        self.assertEqual(detail['participants'], [])


if __name__ == '__main__':
    unittest.main()
