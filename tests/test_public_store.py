import csv
import gzip
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import public_store as store
from backend.database import backup_database, check_database, migrate


class PublicStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'test.sqlite3'
        self.payload = {
            'sources': [{'id': 'test', 'label': 'Fonte oficial de teste', 'status': 'imported', 'url': 'https://example.gov.br', 'period': '2026', 'scope': 'fixture'}],
            'authorities': [{'id': f'p:{i}', 'name': f'José {i}', 'role': 'deputado', 'sphere': 'federal', 'branch': 'legislativo',
                             'institution': 'Câmara', 'uf': 'SP', 'sourceId': 'test'} for i in range(7)],
            'expenses': []}
        for i in range(7):
            for month in range(1, 6):
                self.payload['expenses'].append({'id': f'e:{i}:{month}', 'authorityId': f'p:{i}', 'sourceId': 'test',
                    'year': 2026, 'month': month, 'date': f'2026-{month:02d}-15', 'category': 'Escritório', 'kind': 'reembolso',
                    'amount': 40000 if i == 0 and month == 4 else 10000 + i,
                    'documentId': 'SAME-DOCUMENT', 'supplier': {'key': 'x', 'name': 'Empresa', 'cnpj': '12345678000199'}})
        self.import_data()

    def tearDown(self):
        self.temp.cleanup()

    def import_data(self):
        path = self.root / 'input.json'
        path.write_text(json.dumps(self.payload))
        store.import_documents([path], self.db_path)

    def test_count_pagination_and_accent_search(self):
        with closing(store.connect(self.db_path)) as db, db:
            result = store.authorities(db, {'q': 'jose', 'page': 2, 'pageSize': 3})
            self.assertEqual(result['total'], 7)
            self.assertEqual(len(result['items']), 3)
            self.assertEqual(result['items'][0]['name'], 'José 3')
            self.assertEqual(store.authorities(db, {'q': "%' OR 1=1 --"})['total'], 0)

    def test_exact_money_and_signed_refunds_no_document_deduplication(self):
        self.payload['expenses'].append({**self.payload['expenses'][0], 'id': 'refund', 'amount': -0.01})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            result = store.expenses(db, {'authorityId': 'p:0'})
            self.assertEqual(result['total'], 6)
            self.assertEqual(result['totalAmount'], 79999.99)
            self.assertEqual(store.supplier_detail(db, 'cnpj:12345678000199')['summary']['authorityCount'], 7)

    def test_idempotence_and_failed_transaction_preserve_previous_data(self):
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            stamp = db.execute('SELECT firstSeen FROM expenses LIMIT 1').fetchone()[0]
            self.assertEqual(store.coverage(db)['totals']['expenses'], 35)
        self.payload['expenses'][0]['supplier']['cnpj'] = '12345678900'
        with self.assertRaises(ValueError):
            self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(store.coverage(db)['totals']['expenses'], 35)
            self.assertEqual(db.execute('SELECT firstSeen FROM expenses LIMIT 1').fetchone()[0], stamp)

    def test_month_filters_include_competence_not_issue_date(self):
        self.payload['expenses'][0]['date'] = '2025-12-01'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            filtered = store.expenses(db, {'from': '2026-01', 'to': '2026-01', 'authorityId': 'p:0'})
            self.assertEqual(filtered['total'], 1)
            self.assertEqual(filtered['items'][0]['date'], '2025-12-01')
            with self.assertRaises(ValueError):
                store.expenses(db, {'from': '2026-05', 'to': '2026-01'})
            with self.assertRaises(ValueError):
                store.expenses(db, {'from': '2026-01-31'})

    def test_source_counts_include_expense_and_roster_provenance(self):
        self.payload['sources'].append({'id': 'roster', 'label': 'Cadastro', 'status': 'partial'})
        self.payload['authorities'][0]['sourceId'] = 'roster'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            sources = {s['id']: s for s in store.coverage(db)['sources']}
            self.assertEqual(sources['test']['authorityCount'], 7)
            self.assertEqual(sources['test']['metadataAuthorityCount'], 6)
            self.assertEqual(sources['test']['expenseAuthorityCount'], 7)
            self.assertEqual(sources['roster']['authorityCount'], 1)
            self.assertTrue(store.authority_detail(db, 'p:0')['benchmark']['available'])

    def test_changes_since_tracks_document_period_and_public_metadata(self):
        with closing(store.connect(self.db_path)) as db, db:
            initial = db.execute('SELECT MAX(lastChanged) FROM expenses').fetchone()[0]
        self.payload['expenses'][0]['documentUrl'] = 'https://example.gov.br/corrected'
        self.payload['expenses'][1]['month'] = 7
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            changed = store.expenses(db, {'since': initial})['items']
            self.assertEqual({e['id'] for e in changed}, {'e:0:1', 'e:0:2'})
            initial = db.execute('SELECT MAX(lastChanged) FROM expenses').fetchone()[0]
        for e in self.payload['expenses']:
            e['supplier']['name'] = 'Empresa corrigida'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(store.expenses(db, {'since': initial})['total'], 35)
            db.execute("UPDATE expenses SET lastChanged='2099-01-01T00:00:00.123456+00:00' WHERE id='e:0:1'")
            self.assertEqual(store.expenses(db, {'since': '2099-01-01T00:00:00.123Z'})['total'], 1)
            self.assertEqual(store.expenses(db, {'since': '2099-01-01T00:00:00.124Z'})['total'], 0)

    def test_ambiguous_personal_document_reference_is_omitted(self):
        self.payload['expenses'][0]['documentId'] = '000.000.000-00'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT documentId FROM expenses WHERE id='e:0:1'").fetchone()[0], '')

    def test_comparable_peers_and_signal_latest_month_exclusion(self):
        with closing(store.connect(self.db_path)) as db, db:
            result = store.authority_detail(db, 'p:0')
            self.assertTrue(result['benchmark']['available'])
            self.assertEqual(result['benchmark']['peerCount'], 6)
            self.assertEqual(result['benchmark']['median'], 10003.5)
            signals = store.signals(db, {'authorityId': 'p:0', 'type': 'pico'})['items']
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0]['period'], '2026-04')
        self.payload['authorities'][1]['uf'] = 'RJ'
        self.payload['authorities'][2]['uf'] = 'RJ'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertFalse(store.authority_detail(db, 'p:0')['benchmark']['available'])

    def test_mandate_metadata_does_not_split_reimbursement_peers(self):
        for i, authority in enumerate(self.payload['authorities']):
            authority.update(role='senador', institution='Senado Federal',
                             position='Titular' if i else '2º Suplente',
                             employmentStatus=f'Exercício sem término informado desde 0{i + 1}/10/2026')
        self.import_data()
        with closing(store.connect(self.db_path)) as db:
            result = store.authority_detail(db, 'p:0')['benchmark']
            self.assertTrue(result['available'])
            self.assertEqual(result['peerCount'], 6)
            self.assertEqual(result['median'], 10003.5)
            self.assertNotIn('situação funcional', result['scope'])

        # Salary comparisons must still require matching position and status.
        for expense in self.payload['expenses']:
            expense['kind'] = 'remuneracao'
        self.import_data()
        with closing(store.connect(self.db_path)) as db:
            result = store.authority_detail(db, 'p:0')['benchmark']
            self.assertFalse(result['available'])
            self.assertEqual(result['peerCount'], 0)

    def test_salary_not_added_to_reimbursements_and_missing_not_zero(self):
        salary = {**self.payload['expenses'][0], 'id': 'pay', 'kind': 'remuneracao', 'amount': 0, 'supplier': None}
        self.payload['expenses'].append(salary)
        self.payload['authorities'].append({**self.payload['authorities'][0], 'id': 'no-pay', 'name': 'Sem remuneração importada'})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            data = store.expenses(db, {'authorityId': 'p:0'})
            self.assertIsNone(data['totalAmount'])
            self.assertEqual(len(data['totalsByKind']), 2)
            self.assertEqual(store.authority_detail(db, 'no-pay')['summary'], [])

    def test_csv_full_export_and_formula_escaping(self):
        self.payload['authorities'][0]['name'] = '  =HYPERLINK("x")'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            text = ''.join(store.csv_chunks(db, {'authorityId': 'p:0', 'pageSize': 1}))
            data = list(csv.reader(io.StringIO(text.lstrip('\ufeff')), delimiter=';'))
            self.assertEqual(len(data), 6)
            self.assertTrue(data[1][1].startswith("'  ="))

    def test_streaming_gzip_import(self):
        path = self.root / 'stream.jsonl.gz'
        with gzip.open(path, 'wt', encoding='utf-8') as output:
            for kind, key in [('source', 'sources'), ('authority', 'authorities'), ('expense', 'expenses')]:
                for item in self.payload[key]:
                    output.write(json.dumps({'type': kind, 'data': item}) + '\n')
        store.import_documents([path], self.db_path)
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(store.coverage(db)['totals']['expenses'], 35)

    def test_legacy_schema_migrates_once_and_preserves_data(self):
        db = sqlite3.connect(self.root / 'legacy.sqlite3')
        db.execute('''CREATE TABLE authorities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, branch TEXT, sphere TEXT,
            institution TEXT, uf TEXT, party TEXT, sourceId TEXT, sourceUrl TEXT)''')
        db.execute('''INSERT INTO authorities
            (id,name,institution) VALUES (?,?,?)''', ('old:1', 'José da Silva', 'Câmara'))
        db.commit()
        self.assertEqual(migrate(db), 1)
        self.assertEqual(migrate(db), 1)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        row = db.execute('SELECT id,name,searchText,positionCount FROM authorities').fetchone()
        self.assertEqual(row, ('old:1', 'José da Silva', 'jose da silva camara', 1))
        db.close()

    def test_failed_migration_rolls_back_schema_and_version(self):
        db = sqlite3.connect(self.root / 'rollback.sqlite3')
        db.execute('CREATE TABLE authorities (legacy_id TEXT)')
        db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            migrate(db)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in db.execute('PRAGMA table_info(authorities)')}
        self.assertEqual(tables, {'authorities'})
        self.assertEqual(columns, {'legacy_id'})
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        db.close()

    def test_check_missing_database_is_read_only(self):
        missing = self.root / 'absent.sqlite3'
        result = check_database(missing)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'missing')
        self.assertFalse(missing.exists())

    def test_importer_reports_missing_or_empty_import_directory_without_creating_db(self):
        for import_dir, expected in (
            (self.root / 'missing-imports', 'Pasta de importação não encontrada'),
            (self.root / 'empty-imports', 'Nenhum arquivo JSON ou JSONL para importar'),
        ):
            with self.subTest(import_dir=import_dir):
                if import_dir.name == 'empty-imports':
                    import_dir.mkdir()
                database_path = self.root / f'{import_dir.name}.sqlite3'
                error_output = io.StringIO()
                with redirect_stderr(error_output):
                    with self.assertRaises(SystemExit) as error:
                        store.main(['--db', str(database_path)], import_dir=import_dir)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(expected, error_output.getvalue())
                self.assertFalse(database_path.exists())

    def test_online_backup_copies_database_and_never_overwrites(self):
        output = self.root / 'backup.sqlite3'
        self.assertEqual(backup_database(self.db_path, output), output)
        backup = sqlite3.connect(output)
        try:
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 35)
        finally:
            backup.close()

        protected = self.root / 'protected.sqlite3'
        protected.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            backup_database(self.db_path, protected)
        self.assertEqual(protected.read_bytes(), b'keep me')


if __name__ == '__main__':
    unittest.main()
