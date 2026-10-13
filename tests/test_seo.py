import gzip
import json
import os
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
        self.assertIn('<div class="app" id="app"><div class="view" data-server-render="/deputado/1">', page)
        self.assertIn('<article class="seo-summary"><h1>Ana Ávila</h1>', page)
        self.assertIn('"@type": "BreadcrumbList"', page)
        self.assertIn(f'<meta property="og:image" content="{self.base}/og-image.png">', page)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', page)
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


class ServerContentTests(unittest.TestCase):
    """Conteúdo inicial das seções, páginas de votação, 404 em HTML, arquivos do build e invalidação por snapshot."""

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
                {'id': 'camara:3', 'name': 'Zé <Zed>', 'role': 'deputado', 'party': 'AAA', 'uf': 'MG', 'sourceId': 'camara_deputies_current'},
                {'id': 'senado:2', 'name': 'Bruno Bê', 'role': 'senador', 'party': 'BBB', 'uf': 'RJ', 'sourceId': 'senado_senators_current'}],
            'expenses': [{'id': 'e1', 'authorityId': 'camara:1', 'sourceId': 'camara_deputies_current', 'year': 2026, 'month': 3,
                          'date': '2026-03-01', 'category': 'Escritório', 'kind': 'reembolso', 'amount': 1234.5}]}), encoding='utf-8')
        store.import_documents([doc], self.db)
        self.dist = root / 'dist'
        (self.dist / 'assets').mkdir(parents=True)
        self.build = self.dist / 'index.html'
        self.build.write_text(PAGE.replace('<script>app()</script>', '<script src="/assets/app.0123456789ab.js" defer></script>'), encoding='utf-8')
        (self.dist / 'assets' / 'app.0123456789ab.js').write_text('console.log("app")' + ' ' * 2000, encoding='utf-8')
        self.snapshots = root / 'snapshots'
        self.snapshots.mkdir()
        (self.snapshots / 'presenca.json').write_text(json.dumps([
            {'id': 1, 'nome': 'Ana Ávila', 'partido': 'AAA', 'uf': 'SP', 'presente': 9, 'falta': 1, 'justificadas': 0, 'dias': 10, 'inicio': '2023-02', 'fim': '2026-09'},
            {'id': 3, 'nome': 'Zé', 'partido': 'AAA', 'uf': 'MG', 'presente': 4, 'falta': 6, 'justificadas': 0, 'dias': 10}]), encoding='utf-8')
        vote = {'id': '100-1', 'date': '2026-03-05', 'proposition': 'PL 1/2026', 'type': 'PL', 'title': 'Marco das <bicicletas>',
                'summary': 'Cria regras para ciclovias.', 'decisionLabel': 'Texto aprovado', 'yesMeaning': 'Aprovar o texto', 'noMeaning': 'Rejeitar o texto',
                'outcome': 'approved', 'tally': {'yes': 300, 'no': 100, 'abstention': 2, 'total': 402}, 'themes': [{'id': 'tema-1', 'label': 'Transporte'}],
                'sources': {'vote': 'https://dadosabertos.camara.leg.br/v/1', 'rollCall': 'https://www.camara.leg.br/r/1',
                            'proposition': 'https://www.camara.leg.br/p/1', 'text': None}, 'reviewedAt': '2026-10-01T12:00:00'}
        (self.snapshots / 'chamber-votes.json').write_text(json.dumps({
            'schemaVersion': 1, 'generatedAt': '2026-10-09T00:00:00', 'period': {'start': '2026-02-01', 'end': '2026-10-09'},
            'coverage': {'inventoryCount': 10, 'candidateCount': 2, 'reviewedCount': 2, 'publishedCount': 1, 'pendingCount': 0, 'excludedCount': 1, 'detail': ''},
            'items': [vote]}), encoding='utf-8')
        self.patches = [patch.object(srv, 'BUILD_PATH', self.build), patch.object(srv, 'ASSETS_PATH', self.dist / 'assets'),
                        patch.object(seo, 'SNAPSHOTS_PATH', self.snapshots), patch.object(seo.sections, 'SNAPSHOTS_PATH', self.snapshots),
                        patch.object(srv.votes, 'SNAPSHOTS_PATH', self.snapshots), patch.object(srv.cities, 'SNAPSHOTS_PATH', self.snapshots),
                        patch.object(srv.profiles, 'SNAPSHOTS_PATH', self.snapshots)]
        for item in self.patches:
            item.start()
        self.httpd = srv.ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
        self.httpd.db_path, self.httpd.prod, self.httpd.cache = self.db, True, srv.ResponseCache()
        self.httpd.snapshot_check_seconds = 0
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={'Accept-Encoding': 'gzip'})
        try:
            response = urllib.request.build_opener(NoRedirect).open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            return response, body.decode('utf-8')

    def test_sections_carry_their_content_links_and_structured_data_in_the_html(self):
        response, home = self.get('/')
        self.assertEqual(response.status, 200)
        self.assertIn('<div class="view" data-server-render="/">', home)
        self.assertIn('<h1 class="home-title">', home)
        self.assertIn('action="/politicos" method="get"', home)
        self.assertIn('href="/deputado/1"', home)  # quem mais usa a cota, com link real
        self.assertIn('"@type": "WebSite"', home)
        _, politicians = self.get('/politicos')
        self.assertIn('<a href="/deputado/1">Ana Ávila</a>', politicians)
        self.assertIn('<a href="/senador/2">Bruno Bê</a>', politicians)
        self.assertIn('Zé &lt;Zed&gt;', politicians)
        self.assertIn('"@type": "CollectionPage"', politicians)
        self.assertIn('"@type": "BreadcrumbList"', politicians)
        _, alerts = self.get('/alertas')
        self.assertIn('Alertas não indicam irregularidade', alerts)
        self.assertIn('alerts-rule-count">0</b>', alerts)
        _, attendance = self.get('/presenca')
        self.assertIn('data-server-render="/presenca"', attendance)
        self.assertIn('<a class="attendance-row" href="/deputado/3">', attendance)
        self.assertLess(attendance.index('href="/deputado/3"'), attendance.index('href="/deputado/1"'), 'menos presentes primeiro, como no app')
        self.assertIn('fev/2023–set/2026', attendance)
        _, parties = self.get('/partidos')
        self.assertIn('<th scope="row">AAA</th>', parties)
        self.assertIn('R$ 1.234', parties)
        self.assertIn('sem notas', parties)  # BBB sem reembolsos: ausência, não zero
        _, methodology = self.get('/metodologia')
        self.assertIn('id="methodology-alerts"', methodology)
        self.assertIn('1,75 vez a referência', methodology)
        _, about = self.get('/sobre')
        self.assertIn('<title>Sobre o projeto · Painel Público</title>', about)
        self.assertIn('"@type": "AboutPage"', about)
        self.assertIn('CC BY 4.0', about)
        _, city = self.get('/minha-cidade')
        self.assertIn('Minha cidade', city)
        _, compare = self.get('/comparar')
        self.assertIn('href="/politicos"', compare)

    def test_scoreboard_and_vote_pages_have_their_own_canonical_content_and_sitemap_entries(self):
        _, scoreboard = self.get('/placar')
        self.assertIn('<a href="/placar/100-1">Marco das &lt;bicicletas&gt;</a>', scoreboard)
        self.assertIn('Março de 2026', scoreboard)
        response, vote = self.get('/placar/100-1')
        self.assertEqual(response.status, 200)
        self.assertIn('<title>Marco das &lt;bicicletas&gt; · Placar · Painel Público</title>', vote)
        self.assertIn(f'<link rel="canonical" href="{self.base}/placar/100-1">', vote)
        self.assertIn('data-server-render="/placar/100-1"', vote)
        self.assertIn('Aprovar o texto', vote)
        self.assertIn('<dd>300</dd>', vote)
        self.assertIn('"legislationIdentifier": "PL 1/2026"', vote)
        self.assertIn('O link seguro para o texto exato votado ainda não está disponível.', vote)
        self.assertNotIn('noindex', vote)
        _, sitemap = self.get('/sitemap.xml')
        self.assertIn(f'<url><loc>{self.base}/placar/100-1</loc><lastmod>2026-10-01</lastmod></url>', sitemap)
        self.assertIn(f'<loc>{self.base}/sobre</loc>', sitemap)
        missing, body = self.get('/placar/999-9')
        self.assertEqual(missing.status, 404)
        self.assertIn('noindex', body)
        legacy, body = self.get('/placar/2611313-31')
        self.assertEqual(legacy.status, 200)
        self.assertIn('noindex', body)

    def test_unknown_pages_get_the_site_404_with_noindex_and_no_cache(self):
        response, body = self.get('/nao-existe')
        self.assertEqual(response.status, 404)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('<meta name="robots" content="noindex">', body)
        self.assertIn('Página não encontrada', body)
        self.assertIn('data-server-render="/nao-existe"', body)
        self.assertIn('<script src="/assets/app.0123456789ab.js" defer></script>', body)

    def test_build_assets_are_served_immutable_and_nothing_else_leaves_dist(self):
        response, body = self.get('/assets/app.0123456789ab.js')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Type'], 'text/javascript; charset=utf-8')
        self.assertEqual(response.headers['Cache-Control'], 'public, max-age=31536000, immutable')
        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
        self.assertTrue(body.startswith('console.log("app")'))
        (self.dist / 'segredo.json').write_text('{}', encoding='utf-8')
        for path in ('/assets/segredo.json', '/assets/../index.html', '/assets/app.zzzzzzzzzzzz.js', '/assets/app.0123456789ab.map'):
            with self.subTest(path=path):
                missing, _ = self.get(path)
                self.assertEqual(missing.status, 404)

    def test_page_cache_is_invalidated_when_a_snapshot_changes(self):
        _, before = self.get('/presenca')
        self.assertIn('<b class="mono">65%</b>', before)
        snapshot = self.snapshots / 'presenca.json'
        snapshot.write_text(json.dumps([{'id': 1, 'nome': 'Ana Ávila', 'partido': 'AAA', 'uf': 'SP', 'presente': 10, 'falta': 0, 'justificadas': 0, 'dias': 10}]), encoding='utf-8')
        stat = snapshot.stat()
        os.utime(snapshot, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        _, after = self.get('/presenca')
        self.assertIn('<b class="mono">100%</b>', after)
        self.assertEqual(sum(1 for key in self.httpd.cache.items if key[0] == 'page'), 1, 'a geração nova descarta a página anterior')

    def test_robots_and_llms_describe_the_site_for_crawlers_and_assistants(self):
        _, robots = self.get('/robots.txt')
        self.assertEqual(robots, f'User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {self.base}/sitemap.xml\n')
        _, llms = self.get('/llms.txt')
        for text in ('/placar/<id>', f'{self.base}/sobre', 'CC BY 4.0', 'Ausência de dado não significa zero'):
            self.assertIn(text, llms)
