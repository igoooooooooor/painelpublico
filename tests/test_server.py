import gzip
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from backend import public_store as store, server as srv


class ProdServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'base.sqlite3'
        doc = Path(self.temp.name) / 'in.json'
        doc.write_text(json.dumps({'sources': [{'id': 'camara_deputies_current', 'label': 'x', 'status': 'imported'}],
                                   'authorities': [{'id': 'camara:1', 'name': 'Ana', 'role': 'deputado', 'party': 'AAA',
                                                    'sourceId': 'camara_deputies_current'}], 'expenses': []}), encoding='utf-8')
        store.import_documents([doc], self.db)
        self.httpd = srv.ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
        self.httpd.db_path, self.httpd.prod, self.httpd.cache = self.db, True, srv.ResponseCache()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.temp.cleanup()

    def get(self, path, gz=False):
        req = urllib.request.Request(self.base + path, headers={'Accept-Encoding': 'gzip'} if gz else {})
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return r, json.loads(gzip.decompress(body) if r.headers.get('Content-Encoding') == 'gzip' else body)

    def test_cached_response_is_reused_until_the_database_file_changes(self):
        r, first = self.get('/api/c/partidos')
        self.assertEqual(first['itens'][0]['sigla'], 'AAA')
        self.assertIn('max-age', r.headers['Cache-Control'])
        self.assertEqual(r.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(len(self.httpd.cache.items), 1)

        with store.connect(self.db) as db:
            db.execute("UPDATE authorities SET party='BBB'")
        stat = self.db.stat()
        os.utime(self.db, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        _, second = self.get('/api/c/partidos', gz=True)
        self.assertEqual(second['itens'][0]['sigla'], 'BBB')
        self.assertEqual(len(self.httpd.cache.items), 1)

    def test_home_summary_route_returns_full_roster_contract(self):
        response, summary = self.get('/api/c/resumo')
        self.assertEqual(response.status, 200)
        self.assertEqual(summary['parlamentares']['deputado'], {'total': 1, 'comReembolsos': 0})
        self.assertEqual(summary['parlamentares']['senador'], {'total': 0, 'comReembolsos': 0})
        self.assertIsNone(summary['reembolsos']['deputado']['total'])
        self.assertIsNone(summary['reembolsos']['deputado']['media'])
        self.assertEqual(summary['categoriasCamara'], [])
        self.assertEqual(summary['topCamara'], [])

    def test_profile_is_served_on_demand_from_snapshot_and_missing_is_404(self):
        snap = Path(self.temp.name) / 'perfis.json'
        snap.write_text(json.dumps({'generatedAt': 'x', 'profiles': {'camara:1': {'name': 'Ana', 'projetos': {'total': 2}}}}),
                        encoding='utf-8')
        original = srv.profiles.SNAPSHOTS_PATH
        srv.profiles.SNAPSHOTS_PATH = Path(self.temp.name)
        try:
            _, found = self.get('/api/c/perfil/camara%3A1')
            self.assertEqual(found['name'], 'Ana')
            self.assertEqual(found['projetos']['total'], 2)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get('/api/c/perfil/camara%3A2')
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()
        finally:
            srv.profiles.SNAPSHOTS_PATH = original

    def test_senate_activity_is_reloaded_and_served_without_a_database(self):
        snapshots = Path(self.temp.name) / 'snapshots'
        snapshots.mkdir()
        snap = snapshots / 'senado-atividade.json'
        original = srv.profiles.SNAPSHOTS_PATH
        old_db = self.httpd.db_path
        self.httpd.db_path = Path(self.temp.name) / 'missing.sqlite3'
        srv.profiles.SNAPSHOTS_PATH = snapshots
        try:
            snap.write_text(json.dumps({'generatedAt': 'first', 'year': 2026}), encoding='utf-8')
            response, first = self.get('/api/c/senado/atividade')
            self.assertEqual(response.status, 200)
            self.assertEqual(first['generatedAt'], 'first')

            old_stat = snap.stat()
            snap.write_text(json.dumps({'generatedAt': 'second', 'year': 2026}), encoding='utf-8')
            os.utime(snap, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000))
            _, second = self.get('/api/c/senado/atividade')
            self.assertEqual(second['generatedAt'], 'second')

            snap.unlink()
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get('/api/c/senado/atividade')
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()
        finally:
            srv.profiles.SNAPSHOTS_PATH = original
            self.httpd.db_path = old_db

    def test_malformed_senate_activity_snapshot_returns_404(self):
        snapshots = Path(self.temp.name) / 'snapshots'
        snapshots.mkdir()
        (snapshots / 'senado-atividade.json').write_text('{invalid', encoding='utf-8')
        original = srv.profiles.SNAPSHOTS_PATH
        srv.profiles.SNAPSHOTS_PATH = snapshots
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get('/api/c/senado/atividade')
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()
        finally:
            srv.profiles.SNAPSHOTS_PATH = original

    def test_snapshot_cache_is_scoped_to_path_and_cleared_after_removal(self):
        first_path = Path(self.temp.name) / 'first.json'
        second_path = Path(self.temp.name) / 'second.json'
        first_path.write_text(json.dumps({'generatedAt': 'first'}), encoding='utf-8')
        first_stat = first_path.stat()
        second_path.write_text(json.dumps({'generatedAt': 'second'}), encoding='utf-8')

        self.assertEqual(srv.profiles.senate_activity(first_path)['generatedAt'], 'first')
        self.assertEqual(srv.profiles.senate_activity(second_path)['generatedAt'], 'second')
        first_path.unlink()
        self.assertIsNone(srv.profiles.senate_activity(first_path))
        first_path.write_text(json.dumps({'generatedAt': 'recreated'}), encoding='utf-8')
        os.utime(first_path, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns))
        self.assertEqual(srv.profiles.senate_activity(first_path)['generatedAt'], 'recreated')

    def test_senate_projects_merge_only_for_senators_and_allow_missing_base_snapshot(self):
        snapshots = Path(self.temp.name) / 'snapshots'
        snapshots.mkdir()
        profile_path = snapshots / 'perfis.json'
        project_data = {'status': 'imported', 'period': '2023-2026', 'total': 1,
                        'items': [{'id': 'PL-1', 'titulo': 'Projeto'}]}
        profile_path.write_text(json.dumps({
            'generatedAt': 'base-date',
            'profiles': {
                'senado:10': {'id': 'senado:10', 'role': 'senador', 'contato': {'email': 'x'},
                              'projetos': {'status': 'old'}},
                'camara:10': {'id': 'camara:10', 'role': 'deputado',
                              'projetos': {'status': 'camara'}}
            }
        }), encoding='utf-8')
        (snapshots / 'senado-projetos.json').write_text(json.dumps({
            'generatedAt': 'projects-date',
            'profiles': {
                'senado:10': {'projetos': project_data},
                'senado:11': {'projetos': project_data},
                'camara:10': {'projetos': {'status': 'must-not-merge'}}
            }
        }), encoding='utf-8')

        merged = srv.profiles.profile('senado:10', profile_path)
        self.assertEqual(merged['contato'], {'email': 'x'})
        self.assertEqual(merged['role'], 'senador')
        self.assertEqual(merged['projetos'], project_data)
        self.assertEqual(merged['generatedAt'], 'base-date')
        chamber = srv.profiles.profile('camara:10', profile_path)
        self.assertEqual(chamber['projetos'], {'status': 'camara'})

        profile_path.unlink()
        minimal = srv.profiles.profile('senado:11', profile_path)
        self.assertEqual(minimal['id'], 'senado:11')
        self.assertEqual(minimal['role'], 'senador')
        self.assertEqual(minimal['projetos'], project_data)
        self.assertEqual(minimal['generatedAt'], 'projects-date')
        self.assertIsNone(srv.profiles.profile('senado:12', profile_path))

    def test_profile_csv_downloads_notes_and_unknown_or_removed_routes_are_404(self):
        with urllib.request.urlopen(self.base + '/api/c/gastos.csv?id=camara%3A1') as r:
            body = r.read().decode('utf-8')
            self.assertEqual(r.headers['Content-Type'], 'text/csv; charset=utf-8')
            self.assertIn('filename="gastos-cota-ana.csv"', r.headers['Content-Disposition'])
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
        self.assertTrue(body.startswith('﻿Parlamentar;Competência;'))
        self.assertEqual(len(self.httpd.cache.items), 0)
        for path in ('/api/c/gastos.csv?id=camara%3A2', '/api/authorities', '/api/expenses.csv', '/api/coverage'):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.get(path)
                self.assertEqual(ctx.exception.code, 404)
                ctx.exception.close()

    def test_profile_includes_2026_election_result_from_snapshot(self):
        snapshots = Path(self.temp.name) / 'eleicoes'
        snapshots.mkdir()
        profile_path = snapshots / 'perfis.json'
        profile_path.write_text(json.dumps({'generatedAt': 'base', 'profiles': {'camara:1': {'id': 'camara:1', 'role': 'deputado'}}}),
                                encoding='utf-8')
        (snapshots / 'eleicoes-2026.json').write_text(json.dumps({
            'generatedAt': 'tse', 'segundoTurno': '2026-10-25', 'metodo': 'nome civil e nascimento',
            'fonte': {'sourceUrl': 'https://dadosabertos.tse.jus.br/dataset/candidatos-2026'},
            'profiles': {'camara:1': {'status': 'encontrada', 'cargo': 'DEPUTADO FEDERAL', 'situacao': 'ELEITO POR QP'},
                         'camara:2': {'status': 'sem-correspondencia'}}}), encoding='utf-8')
        merged = srv.profiles.profile('camara:1', profile_path)
        self.assertEqual(merged['eleicao2026']['situacao'], 'ELEITO POR QP')
        self.assertEqual(merged['eleicao2026']['segundoTurno'], '2026-10-25')
        self.assertEqual(merged['eleicao2026']['fonte']['sourceUrl'], 'https://dadosabertos.tse.jus.br/dataset/candidatos-2026')
        only_election = srv.profiles.profile('camara:2', profile_path)
        self.assertEqual((only_election['role'], only_election['eleicao2026']['status']), ('deputado', 'sem-correspondencia'))
        self.assertIsNone(srv.profiles.profile('camara:3', profile_path))

    def test_healthcheck_reports_missing_database(self):
        self.db.unlink()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get('/healthz')
        self.assertEqual(ctx.exception.code, 503)
        ctx.exception.close()


if __name__ == '__main__':
    unittest.main()
