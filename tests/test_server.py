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

    def test_healthcheck_reports_missing_database(self):
        self.db.unlink()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get('/healthz')
        self.assertEqual(ctx.exception.code, 503)


if __name__ == '__main__':
    unittest.main()
