import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from backend import public_store as store, supplier_keys
from backend.config import SCHEMA_VERSION
from backend.database import ensure_schema
from ingest.legislative import supplier_fields

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'segredo-de-teste-' + '0' * 32
CPF = '52998224725'
LEGACY = 'cpf-sha256:' + hashlib.sha256(CPF.encode()).hexdigest()
FINGERPRINT = 'f' * 64


def with_secret(value=SECRET):
    supplier_keys._cache.clear()
    return mock.patch.dict(os.environ, {'PAINEL_SUPPLIER_SECRET': value})


class SupplierKeyTests(unittest.TestCase):
    def tearDown(self):
        supplier_keys._cache.clear()

    def test_cpf_key_is_keyed_and_matches_the_converted_legacy_key(self):
        with with_secret():
            key = supplier_keys.cpf_key(CPF)
            self.assertTrue(key.startswith('cpf-hmac:'))
            self.assertNotIn(LEGACY.split(':', 1)[1], key)
            self.assertEqual(supplier_keys.public_key(LEGACY), key)
            self.assertEqual(supplier_keys.public_key('cnpj:12345678000199'), 'cnpj:12345678000199')
            self.assertIsNone(supplier_keys.public_key(None))
        with with_secret('outro-segredo-' + '1' * 32):
            self.assertNotEqual(supplier_keys.cpf_key(CPF), key)

    def test_collector_never_writes_a_plain_cpf_hash(self):
        with with_secret():
            supplier = supplier_fields('Pessoa Física', '529.982.247-25', 'camara', 0)
        with with_secret():
            self.assertEqual(supplier['key'], supplier_keys.cpf_key(CPF))
        self.assertTrue(supplier['key'].startswith('cpf-hmac:'))
        self.assertIsNone(supplier['cnpj'])

    def test_secret_file_is_created_once_beside_the_database_and_short_secrets_fail(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'PAINEL_SUPPLIER_SECRET': ''}), \
                mock.patch.object(supplier_keys, 'DB_PATH', Path(directory) / 'base.sqlite3'):
            supplier_keys._cache.clear()
            first = supplier_keys.secret()
            path = Path(directory) / supplier_keys.SECRET_FILE
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            supplier_keys._cache.clear()
            self.assertEqual(supplier_keys.secret(), first)
            path.write_text('curto\n')
            supplier_keys._cache.clear()
            with self.assertRaises(RuntimeError):
                supplier_keys.secret()


class SupplierKeyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'base.sqlite3'
        self.secret = with_secret()
        self.secret.start()
        expenses = [{'id': f'camara_ceap:record:{month}', 'authorityId': 'camara:1', 'sourceId': 'camara_ceap', 'year': 2026,
                     'month': month, 'date': f'2026-{month:02d}-10', 'category': 'Locação', 'kind': 'reembolso',
                     'amount': 1000 if month < 6 else 9000, 'supplier': {'key': 'cnpj:x', 'name': 'Empresa', 'cnpj': '12345678000199'}}
                    for month in range(1, 7)]
        expenses.append({**expenses[0], 'id': f'camara_ceap:fingerprint:{FINGERPRINT}:1', 'amount': 5000,
                         'supplier': {'key': 'temporaria', 'name': 'Pessoa Física', 'cnpj': None}})
        self.payload = {'sources': [{'id': 'camara_ceap', 'label': 'CEAP', 'status': 'imported'}],
                        'authorities': [{'id': 'camara:1', 'name': 'Ana', 'role': 'deputado', 'sourceId': 'camara_ceap'}],
                        'expenses': expenses}
        path = self.root / 'in.json'
        path.write_text(json.dumps(self.payload), encoding='utf-8')
        store.import_documents([path], self.db_path)
        # Banco gravado antes da v9: a chave da pessoa física é o SHA-256 puro do CPF.
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("UPDATE suppliers SET key=? WHERE key='temporaria'", (LEGACY,))
            db.execute("UPDATE expenses SET supplierKey=? WHERE supplierKey='temporaria'", (LEGACY,))
            db.execute("INSERT INTO quota_categories(id,name) VALUES(1,'Locação')")
            db.execute('INSERT INTO quota_history_notes(authorityId,year,month,seq,categoryId,amountCents,supplierKey) '
                       "VALUES('camara:1',2025,3,1,1,700,?)", (LEGACY,))
            db.execute('PRAGMA user_version = 8')
            db.commit()

    def tearDown(self):
        self.secret.stop()
        supplier_keys._cache.clear()
        self.temp.cleanup()

    def counts(self, db):
        return (db.execute('SELECT COUNT(*), SUM(amountCents) FROM expenses').fetchone(),
                db.execute('SELECT COUNT(*) FROM quota_history_notes').fetchone()[0])

    def test_old_database_is_rekeyed_without_losing_notes(self):
        with closing(store.connect(self.db_path)) as db:
            before = self.counts(db)
        self.assertEqual(ensure_schema(self.db_path), SCHEMA_VERSION)
        expected = supplier_keys.public_key(LEGACY)
        with closing(store.connect(self.db_path)) as db:
            self.assertEqual(self.counts(db), before)
            self.assertEqual(supplier_keys.legacy_count(db), 0)
            self.assertEqual(db.execute('SELECT name FROM suppliers WHERE key=?', (expected,)).fetchone()[0], 'Pessoa Física')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quota_history_notes WHERE supplierKey=?', (expected,)).fetchone()[0], 1)
            ids = [row[0] for row in db.execute('SELECT id FROM expenses WHERE supplierKey=?', (expected,))]
            self.assertEqual(len(ids), 1)
            self.assertNotIn(FINGERPRINT, ids[0])  # o ID por conteúdo também carregava a chave antiga
            self.assertTrue(ids[0].startswith('camara_ceap:fingerprint:') and ids[0].endswith(':1'))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM signals WHERE id LIKE '%cpf-sha256%' OR detail LIKE '%cpf-sha256%'").fetchone()[0], 0)

    def test_import_of_an_old_file_stores_the_keyed_form(self):
        with closing(store.connect(self.db_path)) as db:
            db.execute('PRAGMA user_version = 9')
        self.payload['expenses'][-1]['supplier']['key'] = LEGACY
        path = self.root / 'old.json'
        path.write_text(json.dumps(self.payload), encoding='utf-8')
        store.import_documents([path], self.db_path)
        with closing(store.connect(self.db_path)) as db:
            self.assertEqual(supplier_keys.legacy_count(db), 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses WHERE supplierKey=?',
                                        (supplier_keys.public_key(LEGACY),)).fetchone()[0], 1)

    def test_data_release_refuses_a_database_with_old_keys(self):
        spec = importlib.util.spec_from_file_location('publish_data_keys', ROOT / 'scripts' / 'publish_data.py')
        publish = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publish)
        with self.assertRaises(RuntimeError):
            publish.package_database(self.db_path, self.root, 'data-2026-10-20')
        self.assertFalse((self.root / 'na-lupa-data-2026-10-20.sqlite3.gz').exists())
        ensure_schema(self.db_path)
        packed, _ = publish.package_database(self.db_path, self.root, 'data-2026-10-20')
        self.assertTrue(packed.is_file())


if __name__ == '__main__':
    unittest.main()
