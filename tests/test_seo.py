import gzip
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend import public_store as store, seo, server as srv

PAGE = ('<!doctype html><html><head><title>Painel Público</title></head>'
        '<body><div class="app" id="app"></div><script>app()</script></body></html>')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


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
        _, llms = self.get('/llms.txt')
        self.assertIn('/deputado/<id>-<nome>', llms)

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

    def test_favicon_is_served_for_both_names(self):
        for path in ('/favicon.svg', '/favicon.ico'):
            response, body = self.get(path)
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
            self.assertIn('<svg', body)

    def test_pages_are_cached_like_the_api(self):
        self.get('/deputado/1-ana-avila')
        self.get('/deputado/1-ana-avila')
        self.assertEqual(sum(1 for key in self.httpd.cache.items if key[1] == 'page'), 1)

    def test_slug_and_money_helpers(self):
        self.assertEqual(seo.slug('Rui Falcão'), 'rui-falcao')
        self.assertEqual(seo.money_cents(22633099), 'R$ 226.330,99')
        self.assertEqual(seo.month_range(['2026-01', '2026-07', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06']), 'jan/2026–jul/2026, 7 meses')
        self.assertEqual(seo.month_range(['2023-02', '2023-03', '2026-07']), 'fev/2023–mar/2023, jul/2026, 3 meses')
        self.assertEqual(seo.month_range(['2026-01', '2026-03']), 'jan/2026, mar/2026, 2 meses')
        self.assertEqual(seo.shorten('um dois tres quatro', 12), 'um dois…')
        self.assertEqual(seo.shorten('curto'), 'curto')
