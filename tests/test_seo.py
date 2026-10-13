import gzip
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from backend import public_store as store, seo, server as srv

PAGE = ('<!doctype html><html><head><title>Painel Público</title></head>'
        '<body><div class="app" id="app"></div><script>app()</script></body></html>')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PresenceSummaryTests(unittest.TestCase):
    def test_search_summary_rejects_impossible_or_missing_attendance(self):
        valid = {'id': 1, 'presente': 9, 'falta': 1, 'justificadas': 0, 'dias': 10}
        invalid = [
            {**valid, 'presente': 20},
            {**valid, 'falta': -1},
            {**valid, 'dias': 0},
            {**valid, 'justificadas': None},
            {**valid, 'presente': True},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(seo, 'SNAPSHOTS_PATH', Path(directory)):
            snapshot = Path(directory) / 'presenca.json'
            for row in invalid:
                with self.subTest(row=row):
                    snapshot.write_text(json.dumps([row]), encoding='utf-8')
                    self.assertIsNone(seo._chamber_presence('1'))
            snapshot.write_text(json.dumps([valid]), encoding='utf-8')
            self.assertEqual(seo._chamber_presence('1'), valid)
            self.assertIsNone(seo._chamber_presence('2'))
            snapshot.write_text('{}', encoding='utf-8')
            self.assertIsNone(seo._chamber_presence('1'))


class SeoPagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / 'base.sqlite3'
        doc = root / 'in.json'
        doc.write_text(json.dumps({
            'sources': [{'id': 'camara_deputies_current', 'label': 'x', 'status': 'imported'},
                        {'id': 'senado_senators_current', 'label': 'y', 'status': 'imported'}],
            'authorities': [
                {'id': 'camara:1', 'name': 'Ana Ávila', 'role': 'deputado', 'party': 'AAA', 'uf': 'SP', 'sourceId': 'camara_deputies_current'},
                {'id': 'senado:2', 'name': 'Bruno <Bê>', 'role': 'senador', 'party': 'BBB', 'uf': 'RJ', 'sourceId': 'senado_senators_current'}],
            'expenses': [{'id': 'e1', 'authorityId': 'camara:1', 'sourceId': 'camara_deputies_current', 'year': 2026, 'month': 3,
                          'date': '2026-03-01', 'category': 'Escritório', 'kind': 'reembolso', 'amount': 1234.5}]}), encoding='utf-8')
        store.import_documents([doc], self.db)
        self.build = root / 'index.html'
        self.build.write_text(PAGE, encoding='utf-8')
        self.original_build = srv.BUILD_PATH
        srv.BUILD_PATH = self.build
        self.httpd = srv.ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
        self.httpd.db_path, self.httpd.prod, self.httpd.cache = self.db, True, srv.ResponseCache()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def tearDown(self):
        srv.BUILD_PATH = self.original_build
        self.httpd.shutdown(); self.httpd.server_close(); self.temp.cleanup()

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={'Accept-Encoding': 'gzip'})
        with urllib.request.build_opener(NoRedirect).open(request) as response:
            body = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            return response, body.decode('utf-8')

    def test_profile_page_has_metadata_summary_and_canonical_name(self):
        response, page = self.get('/deputado/1-ana-avila')
        self.assertEqual(response.status, 200)
        self.assertIn('<title>Ana Ávila (AAA-SP): quanto custa e como trabalha · Painel Público</title>', page)
        self.assertIn(f'<link rel="canonical" href="{self.base}/deputado/1-ana-avila">', page)
        self.assertIn('"@type": "Person"', page)
        self.assertIn('<div class="app" id="app"><article class="seo-summary"><h1>Ana Ávila</h1>', page)
        self.assertIn('R$ 1.234 por mês em reembolsos da cota (mar/2026, nos meses com notas)', page)
        self.assertIn('<script>app()</script>', page)

    def test_profile_without_name_redirects_and_unknown_or_wrong_house_is_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as redirect:
            self.get('/deputado/1')
        self.assertEqual(redirect.exception.code, 301)
        self.assertEqual(redirect.exception.headers['Location'], '/deputado/1-ana-avila')
        redirect.exception.close()
        for path in ('/deputado/999-x', '/deputado/2-bruno-be'):
            with self.assertRaises(urllib.error.HTTPError) as missing:
                self.get(path)
            self.assertEqual(missing.exception.code, 404)
            self.assertIn('noindex', gzip.decompress(missing.exception.read()).decode())
            missing.exception.close()

    def test_names_are_escaped_in_html_and_structured_data(self):
        _, page = self.get('/senador/2-bruno-be')
        self.assertIn('<h1>Bruno &lt;Bê&gt;</h1>', page)
        self.assertNotIn('<Bê>', page)

    def test_sections_robots_sitemap_and_llms(self):
        _, home = self.get('/')
        self.assertIn('"@type": "WebSite"', home)
        _, alerts = self.get('/alertas')
        self.assertIn('<title>Alertas de gastos incomuns na cota parlamentar · Painel Público</title>', alerts)
        _, robots = self.get('/robots.txt')
        self.assertIn('Disallow: /api/', robots)
        self.assertIn(f'Sitemap: {self.base}/sitemap.xml', robots)
        _, sitemap = self.get('/sitemap.xml')
        self.assertIn(f'<loc>{self.base}/deputado/1-ana-avila</loc>', sitemap)
        self.assertIn(f'<loc>{self.base}/senador/2-bruno-be</loc>', sitemap)
        self.assertIn(f'<loc>{self.base}/alertas</loc>', sitemap)
        self.assertIn(f'<loc>{self.base}/metodologia</loc>', sitemap)
        response, methodology = self.get('/metodologia')
        self.assertEqual(response.status, 200)
        self.assertIn('<title>Metodologia e perguntas · Painel Público</title>', methodology)
        _, llms = self.get('/llms.txt')
        self.assertIn('/deputado/<id>-<nome>', llms)
        self.assertIn(f'{self.base}/metodologia', llms)

    def test_party_pair_path_has_its_own_escaped_metadata(self):
        response, page = self.get('/partidos/PL-vs-PT')
        self.assertEqual(response.status, 200)
        self.assertIn('<title>PL × PT · Comparar partidos · Painel Público</title>', page)
        self.assertIn('<meta name="robots" content="noindex">', page)
        _, escaped = self.get('/partidos/%3Cb%3E-vs-PT')
        self.assertNotIn('<b> ×', escaped)
        self.assertIn('&lt;b&gt; × PT', escaped)

    def test_compare_pair_path_names_both_people_and_falls_back_for_unknown_ids(self):
        response, page = self.get('/comparar/deputado-1-vs-senador-2')
        self.assertEqual(response.status, 200)
        self.assertIn('Ana', page)
        self.assertIn('Bruno &lt;Bê&gt;', page)
        self.assertIn('· Comparar políticos · Painel Público</title>', page)
        self.assertIn('<meta name="robots" content="noindex">', page)
        _, unknown = self.get('/comparar/deputado-999-vs-senador-2')
        self.assertIn('<title>Comparar políticos · Painel Público</title>', unknown)
        _, wrong_role = self.get('/comparar/senador-1-vs-senador-2')
        self.assertIn('<title>Comparar políticos · Painel Público</title>', wrong_role)

    def test_city_path_has_metadata_canonical_name_and_works_without_the_database(self):
        self.httpd.snapshot_check_seconds = 0  # o teste troca o snapshot e lê em seguida
        snapshot = Path(self.temp.name) / 'cities.json'
        snapshot.write_text(json.dumps({'municipalities': [
            {'id': '3550308', 'name': 'São Paulo', 'uf': 'SP', 'population': 11451245, 'populationYear': 2024},
            {'id': '2605459', 'name': 'Fernando de Noronha', 'uf': 'PE', 'population': None}]}), encoding='utf-8')
        with patch.object(seo.cities, 'SNAPSHOTS_PATH', Path(self.temp.name)):
            response, page = self.get('/minha-cidade/3550308-sao-paulo')
            self.assertEqual(response.status, 200)
            self.assertIn('<title>São Paulo (SP): quem governa, contas da prefeitura e emendas · Painel Público</title>', page)
            self.assertIn(f'<link rel="canonical" href="{self.base}/minha-cidade/3550308-sao-paulo">', page)
            self.assertIn('"@type": "City"', page)
            self.assertIn('11.451.245 habitantes (estimativa de 2024)', page)
            self.assertIn('<h1>São Paulo</h1>', page)
            self.assertNotIn('noindex', page)
            with self.assertRaises(urllib.error.HTTPError) as moved:
                self.get('/minha-cidade/3550308')
            self.assertEqual(moved.exception.code, 301)
            self.assertEqual(moved.exception.headers['Location'], '/minha-cidade/3550308-sao-paulo')
            moved.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as moved:
                self.get('/minha-cidade/3550308-outro-nome/')
            self.assertEqual(moved.exception.headers['Location'], '/minha-cidade/3550308-sao-paulo')
            moved.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as missing:
                self.get('/minha-cidade/9999999-nenhuma')
            self.assertEqual(missing.exception.code, 404)
            self.assertIn('Cidade não encontrada', gzip.decompress(missing.exception.read()).decode('utf-8'))
            missing.exception.close()
            _, noronha = self.get('/minha-cidade/2605459-fernando-de-noronha')
            self.assertIn('<title>Fernando de Noronha (PE): quem governa', noronha)
            self.assertNotIn('habitantes', noronha)
            _, sitemap = self.get('/sitemap.xml')
            self.assertIn(f'<loc>{self.base}/minha-cidade/3550308-sao-paulo</loc>', sitemap)
            _, llms = self.get('/llms.txt')
            self.assertIn('/minha-cidade/<código IBGE>-<nome>', llms)
            # Sem banco, a página da cidade continua inteira: ela só depende do snapshot.
            self.httpd.db_path = Path(self.temp.name) / 'absent.sqlite3'
            response, page = self.get('/minha-cidade/3550308-sao-paulo')
            self.assertEqual(response.status, 200)
            self.assertIn('<h1>São Paulo</h1>', page)
            self.httpd.db_path = self.db
        # Sem snapshot, qualquer cidade é 404 e o sitemap segue com seções e fichas.
        with patch.object(seo.cities, 'SNAPSHOTS_PATH', Path(self.temp.name) / 'nowhere'):
            with self.assertRaises(urllib.error.HTTPError) as missing:
                self.get('/minha-cidade/3550308-sao-paulo')
            self.assertEqual(missing.exception.code, 404)
            missing.exception.close()

    def test_favicon_is_served_for_both_names(self):
        for path in ('/favicon.svg', '/favicon.ico'):
            response, body = self.get(path)
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
            self.assertIn('<svg', body)

    def test_pages_are_cached_like_the_api(self):
        self.get('/deputado/1-ana-avila')
        self.get('/deputado/1-ana-avila')
        self.assertEqual(sum(1 for key in self.httpd.cache.items if key[0] == 'page'), 1)

    def test_slug_and_money_helpers(self):
        self.assertEqual(seo.slug('Rui Falcão'), 'rui-falcao')
        self.assertEqual(seo.money_cents(22633099), 'R$ 226.330,99')
        self.assertEqual(seo.month_range(['2026-01', '2026-07', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06']), 'jan/2026–jul/2026, 7 meses')
        self.assertEqual(seo.month_range(['2023-02', '2023-03', '2026-07']), 'fev/2023–mar/2023, jul/2026, 3 meses')
        self.assertEqual(seo.month_range(['2026-01', '2026-03']), 'jan/2026, mar/2026, 2 meses')
        self.assertEqual(seo.shorten('um dois tres quatro', 12), 'um dois…')
        self.assertEqual(seo.shorten('curto'), 'curto')
